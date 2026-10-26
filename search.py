"""Ask a question on the command line and see which commit chunks match best."""

import sys

import chromadb
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"
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
    results = collection.query(query_embeddings=embedding, n_results=RESULTS)

    print(f"Question: {question}\n")
    for rank, (metadata, distance) in enumerate(
        zip(results["metadatas"][0], results["distances"][0]), start=1
    ):
        short_sha = metadata["sha"][:7]
        date = metadata["date"][:10]
        print(f"{rank}. {short_sha}  {date}  {metadata['message']}")
        print(f"   distance: {distance:.4f}")


if __name__ == "__main__":
    main()
