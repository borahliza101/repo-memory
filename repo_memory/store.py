"""Reading and writing the ChromaDB memory: collections, chunks, embeddings."""

from functools import lru_cache

import chromadb
from chromadb.api.shared_system_client import SharedSystemClient
from sentence_transformers import SentenceTransformer

from .chunking import build_entries
from .config import CHROMA_PATH, collection_name

MODEL_NAME = "all-MiniLM-L6-v2"
BATCH_SIZE = 100


@lru_cache(maxsize=1)
def get_model():
    """Load the embedding model once and reuse it afterwards."""
    return SentenceTransformer(MODEL_NAME)


def open_client():
    """Open a ChromaDB client that sees commits added by other processes.

    Chroma keeps its vector index cached inside a process, so a long-running
    app would never see commits that the watcher added until it was restarted.
    Clearing the system cache makes every new query read the current database.
    """
    SharedSystemClient.clear_system_cache()
    return chromadb.PersistentClient(path=CHROMA_PATH)


def open_collection(repo):
    """Open this repo's collection with a fresh view of the database."""
    return open_client().get_collection(collection_name(repo))


def known_repos(client):
    """Map each repo that has a memory to its collection name."""
    repos = {}
    for collection in client.list_collections():
        repo = (collection.metadata or {}).get("repo")
        if repo and collection.name.startswith("commits_"):
            repos[repo] = collection.name
    return repos


def unique_commits(collection):
    """One metadata row per commit (the collection stores several chunks each)."""
    metadatas = collection.get(include=["metadatas"])["metadatas"]
    by_sha = {metadata["sha"]: metadata for metadata in metadatas}
    return sorted(by_sha.values(), key=lambda metadata: metadata["date"])


def files_changed(collection, sha):
    """The changed filenames, read from that commit's summary chunk."""
    rows = collection.get(where={"sha": sha}, include=["documents"])
    for document in rows["documents"]:
        if "Files changed:" in document:
            line = document.split("Files changed:", 1)[1].splitlines()[0].strip()
            return [name.strip() for name in line.split(",") if name.strip()]
    return []


def stored_shas(name):
    """Every commit sha already in this repo's collection."""
    try:
        collection = open_client().get_collection(name)
    except Exception:
        return set()  # no memory for this repo yet
    metadatas = collection.get(include=["metadatas"])["metadatas"]
    return {metadata["sha"] for metadata in metadatas}


def add_chunks(ids, documents, metadatas, name, repo, reset=False):
    """Embed chunks and store them in this repo's collection."""
    client = chromadb.PersistentClient(path=CHROMA_PATH)
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
    """Build (or rebuild) the memory for one repo from a list of commits.

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
    """Add only the commits that are not in the memory yet (same as the watcher)."""
    client = chromadb.PersistentClient(path=CHROMA_PATH)
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