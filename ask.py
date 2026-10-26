"""Answer a question about the commit history using a Groq-hosted LLM."""

import os
import sys

import chromadb
from dotenv import load_dotenv
from groq import Groq
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"  # same embedding model used to build the memory
LLM_MODEL = "openai/gpt-oss-120b"
CANDIDATES = 20  # chunks to fetch before we pick the best per commit
RESULTS = 5

# Windows consoles can't always print special characters from the model's answer.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SYSTEM_PROMPT = (
    "You answer questions about a software project's commit history. "
    "Use only the commits given to you, never outside knowledge. "
    "Cite the commit for every claim using its short sha in square brackets, "
    "for example [6f66281]. "
    'If the commits do not contain the answer, reply exactly: '
    '"I couldn\'t find this in the history" and nothing else.'
)


def retrieve(question):
    """Find the top 5 unique commits, each with its best matching chunk."""
    model = SentenceTransformer(MODEL_NAME)
    embedding = model.encode([question]).tolist()

    client = chromadb.PersistentClient(path="chroma_db")
    collection = client.get_collection("commits")
    results = collection.query(
        query_embeddings=embedding,
        n_results=CANDIDATES,
        include=["documents", "metadatas", "distances"],
    )

    # Keep only the best chunk for each commit, so one commit can't fill the list.
    best_per_commit = {}
    for document, metadata, distance in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        sha = metadata["sha"]
        if sha not in best_per_commit or distance < best_per_commit[sha]["distance"]:
            best_per_commit[sha] = {
                "document": document,
                "metadata": metadata,
                "distance": distance,
            }

    matches = sorted(best_per_commit.values(), key=lambda item: item["distance"])
    return matches[:RESULTS]


def build_context(matches):
    """Turn the retrieved commits into text for the model to read."""
    blocks = []
    for match in matches:
        metadata = match["metadata"]
        blocks.append(
            f"Commit {metadata['sha'][:7]} by {metadata['author']} on {metadata['date'][:10]}\n"
            f"Message: {metadata['message']}\n"
            f"Code and files:\n{match['document']}"
        )
    return "\n\n---\n\n".join(blocks)


def main():
    # 1. Load the API key from .env. It is never printed.
    load_dotenv()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise SystemExit("GROQ_API_KEY is missing from .env")

    # 2. The question comes from the command line.
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        raise SystemExit('Usage: python ask.py "your question here"')

    # 3. Find the commits that probably contain the answer.
    print(f"Searching for: {question}")
    matches = retrieve(question)
    if not matches:
        print("I couldn't find this in the history")
        return

    # 4. Ask the model to answer using only those commits.
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Question: {question}\n\nCommits:\n\n{build_context(matches)}",
            },
        ],
    )
    answer = response.choices[0].message.content.strip()

    # 5. Show the answer, then the commits it was allowed to use.
    print(f"\n{answer}\n")
    print("Commits used:")
    for rank, match in enumerate(matches, start=1):
        metadata = match["metadata"]
        print(f"{rank}. {metadata['sha'][:7]}  {metadata['date'][:10]}  {metadata['message']}")


if __name__ == "__main__":
    main()