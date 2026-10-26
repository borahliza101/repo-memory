"""Ask a question on the command line and see which commit chunks match best."""

import sys

import chromadb
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"
# Get more chunks than we need, because several chunks can belong to one commit.
CANDIDATES = 20
RESULTS = 5


def main():
    # Take the question from the command line, e.g. python search.py "why redirects"
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        raise SystemExit('Usage: python search.py "your question here"')

    # Load the same model used to build the memory, so vectors are comparable.
    model = SentenceTransformer(MODEL_NAME)
    embedding = model.encode([question]).tolist()

    # Open the saved database and find the closest chunks.
    client = chromadb.PersistentClient(path="chroma_db")
    collection = client.get_collection("commits")
    results = collection.query(query_embeddings=embedding, n_results=CANDIDATES)

    # Keep only the best chunk for each commit, so one commit can't fill the list.
    best_per_commit = {}
    for metadata, distance in zip(results["metadatas"][0], results["distances"][0]):
        sha = metadata["sha"]
        if sha not in best_per_commit or distance < best_per_commit[sha]["distance"]:
            best_per_commit[sha] = {"metadata": metadata, "distance": distance}

    # Results come back as a dict; sort by distance (smaller = closer match).
    matches = sorted(best_per_commit.values(), key=lambda item: item["distance"])

    print(f"Question: {question}\n")
    for rank, match in enumerate(matches[:RESULTS], start=1):
        metadata = match["metadata"]
        short_sha = metadata["sha"][:7]
        date = metadata["date"][:10]
        print(f"{rank}. {short_sha}  {date}  {metadata['message']}")
        print(f"   distance: {match['distance']:.4f}")


if __name__ == "__main__":
    main()
