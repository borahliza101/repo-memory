"""Turn data/commits.json into a searchable ChromaDB collection."""

import json
import os

import chromadb
from sentence_transformers import SentenceTransformer

CHUNK_SIZE = 2000
CHUNK_OVERLAP = 200
MODEL_NAME = "all-MiniLM-L6-v2"


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


def main():
    # 1. Load the commits we fetched earlier.
    with open(os.path.join("data", "commits.json"), encoding="utf-8") as f:
        commits = json.load(f)
    print(f"Loaded {len(commits)} commits")

    # 2. Build text documents for each commit, then split them into chunks.
    ids = []
    documents = []
    metadatas = []
    skipped = 0
    for commit in commits:
        # Skip bot merges too: their author looks human, but the message names dependabot.
        if "dependabot" in commit["message"].lower():
            skipped += 1
            continue

        first_line = commit["message"].splitlines()[0] if commit["message"] else ""
        metadata = {
            "sha": commit["sha"],
            "author": commit["author"],
            "date": commit["date"],
            "message": first_line,
        }

        # A short summary chunk, so the commit's purpose is easy to find.
        ids.append(f"{commit['sha']}-summary")
        documents.append(make_summary(commit))
        metadatas.append(metadata)

        # The full code chunks, so details are searchable as well.
        for index, chunk in enumerate(split_text(make_document(commit))):
            ids.append(f"{commit['sha']}-{index}")
            documents.append(chunk)
            metadatas.append(metadata)

    print(f"Skipped {skipped} bot commits")
    print(f"Built {len(documents)} chunks from {len(commits) - skipped} commits")

    # 3. Embed every chunk locally. The model downloads once, then works offline.
    print(f"Loading embedding model {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME)
    print("Embedding chunks (this may take a minute)...")
    embeddings = model.encode(documents, show_progress_bar=True).tolist()

    # 4. Store everything in a persistent database so it survives restarts.
    client = chromadb.PersistentClient(path="chroma_db")
    # Start clean, otherwise running this twice would store duplicates.
    try:
        client.delete_collection("commits")
    except Exception:
        pass  # no collection yet, nothing to delete
    collection = client.create_collection("commits")

    # Add in batches to keep memory use low.
    batch_size = 100
    for start in range(0, len(ids), batch_size):
        end = start + batch_size
        collection.add(
            ids=ids[start:end],
            documents=documents[start:end],
            embeddings=embeddings[start:end],
            metadatas=metadatas[start:end],
        )

    print(
        f"Stored {len(commits) - skipped} commits and {collection.count()} chunks in chroma_db/"
    )


if __name__ == "__main__":
    main()
