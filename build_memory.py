"""Turn a repo's commit JSON file into a searchable ChromaDB collection."""

import argparse
import json
from datetime import datetime, timezone
from functools import lru_cache

import chromadb
from sentence_transformers import SentenceTransformer

from config import collection_name, commits_path, get_repo

CHUNK_SIZE = 2000
CHUNK_OVERLAP = 200
MODEL_NAME = "all-MiniLM-L6-v2"
BATCH_SIZE = 100


@lru_cache(maxsize=1)
def get_model():
    """Load the embedding model once and reuse it afterwards."""
    return SentenceTransformer(MODEL_NAME)


def make_summary(commit):
    """Short text with only the purpose (message + filenames), no code."""
    short_sha = commit["sha"][:7]
    filenames = ", ".join(f["filename"] for f in commit["files"])

    return (
        f"Commit {short_sha} by {commit['author']} on {commit['date']}\n\n"
        f"Message: {commit['message']}\n\n"
        f"Files changed: {filenames}"
    )


def make_document(commit):
    """Turn one commit into a single text document, including the code changes."""
    filenames = ", ".join(f["filename"] for f in commit["files"])
    patches = "\n".join(f["patch"] for f in commit["files"])

    return f"{make_summary(commit)}\n\nChanges: {patches}"


def split_text(text):
    """Split long text into overlapping chunks so no context is lost at the edges."""
    if len(text) <= CHUNK_SIZE:
        return [text]

    chunks = []
    step = CHUNK_SIZE - CHUNK_OVERLAP
    start = 0
    while start < len(text):
        chunks.append(text[start : start + CHUNK_SIZE])
        if start + CHUNK_SIZE >= len(text):
            break
        start += step
    return chunks


def is_dependabot_merge(message):
    """A merge commit that brought in a dependabot pull request."""
    first_line = message.splitlines()[0] if message else ""
    return first_line.startswith("Merge pull request") and "/dependabot/" in first_line


def is_bot_commit(commit):
    """Skip real bots and dependabot merges, but keep humans who mention the word."""
    author = commit.get("author") or ""
    return author.endswith("[bot]") or is_dependabot_merge(commit.get("message") or "")


def build_entries(commits):
    """Turn commits into chunks: one summary chunk plus the code chunks each.

    Returns (ids, documents, metadatas, skipped_bot_commits).
    """
    ids = []
    documents = []
    metadatas = []
    skipped = 0

    for commit in commits:
        if is_bot_commit(commit):
            skipped += 1
            continue

        first_line = commit["message"].splitlines()[0] if commit["message"] else ""
        metadata = {
            "sha": commit["sha"],
            "author": commit["author"],
            "date": commit["date"],
            "message": first_line,
            # When this commit entered the memory, for the app's memory feed.
            "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

        # A short summary chunk, so the commit's purpose is easy to find.
        ids.append(f"{commit['sha']}-summary")
        documents.append(make_summary(commit))
        metadatas.append(metadata)

        # The full code chunks, so details are searchable as well. An empty
        # commit has no files, so its code chunk would just repeat the summary.
        if commit["files"]:
            for index, chunk in enumerate(split_text(make_document(commit))):
                ids.append(f"{commit['sha']}-{index}")
                documents.append(chunk)
                metadatas.append(metadata)

    return ids, documents, metadatas, skipped


def add_chunks(ids, documents, metadatas, name, repo, reset=False):
    """Embed chunks and store them in this repo's collection."""
    client = chromadb.PersistentClient(path="chroma_db")
    if reset:
        # Start clean, otherwise rebuilding would store duplicates.
        try:
            client.delete_collection(name)
        except Exception:
            pass  # no collection yet, nothing to delete

    # The collection remembers which repo it belongs to, for the app dropdown.
    collection = client.get_or_create_collection(name, metadata={"repo": repo})
    if not documents:
        return collection

    print(f"Embedding {len(documents)} chunks...")
    embeddings = get_model().encode(documents, show_progress_bar=True).tolist()

    # Add in batches to keep memory use low. Upsert never crashes on chunks we
    # already saved, so re-checking a commit is safe.
    for start in range(0, len(ids), BATCH_SIZE):
        end = start + BATCH_SIZE
        collection.upsert(
            ids=ids[start:end],
            documents=documents[start:end],
            embeddings=embeddings[start:end],
            metadatas=metadatas[start:end],
        )
    return collection


def build_repo_memory(repo, commits, progress=None):
    """Build (or update) the memory for one repo from a list of commits.

    Returns (collection, commit_count). When progress is given it is called
    with a short message so a UI can show what is happening.
    """
    ids, documents, metadatas, skipped = build_entries(commits)
    kept = len(commits) - skipped
    if progress:
        progress(f"Embedding {len(documents)} chunks...")

    name = collection_name(repo)
    collection = add_chunks(ids, documents, metadatas, name, repo, reset=True)
    return collection, kept


def add_missing_commits(repo, commits, progress=None):
    """Add only the commits that are not in the memory yet (same as watch.py)."""
    client = chromadb.PersistentClient(path="chroma_db")
    name = collection_name(repo)
    try:
        collection = client.get_collection(name)
    except Exception:
        return build_repo_memory(repo, commits, progress)

    known = {metadata["sha"] for metadata in collection.get(include=["metadatas"])["metadatas"]}
    missing = [commit for commit in commits if commit["sha"] not in known]
    if not missing:
        return collection, len(known)

    for commit in missing:
        ids, documents, metadatas, _ = build_entries([commit])
        if progress:
            progress(f"Adding {commit['sha'][:7]} {commit['message'].splitlines()[0][:50]}")
        add_chunks(ids, documents, metadatas, name, repo)
    return collection, len(known) + len(missing)


def main():
    parser = argparse.ArgumentParser(description="Build the searchable commit memory.")
    parser.add_argument("--repo", help="owner/name (default: REPO from .env, else psf/requests)")
    args = parser.parse_args()
    repo = get_repo(args.repo)

    path = commits_path(repo)
    with open(path, encoding="utf-8") as f:
        commits = json.load(f)
    print(f"Loaded {len(commits)} commits from {path}")

    ids, documents, metadatas, skipped = build_entries(commits)
    print(f"Skipped {skipped} bot commits")
    print(f"Built {len(documents)} chunks from {len(commits) - skipped} commits")

    name = collection_name(repo)
    collection = add_chunks(ids, documents, metadatas, name, repo, reset=True)
    print(f"Stored {len(commits) - skipped} commits and {collection.count()} chunks in {name}")


if __name__ == "__main__":
    main()