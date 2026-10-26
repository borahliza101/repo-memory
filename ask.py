"""Answer a question about the commit history using a Groq-hosted LLM."""

import argparse
import os
import re
import sys
from functools import lru_cache

import chromadb
from dotenv import load_dotenv
from groq import Groq
from sentence_transformers import SentenceTransformer

from config import collection_name, get_repo

load_dotenv()  # read .env once, when this module is imported

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
    "Cite commits only as [shortsha] in square brackets, for example [6f66281]. "
    "Do not use any other citation format, and cite the commit for every claim. "
    'If the commits do not contain the answer, reply exactly: '
    '"I couldn\'t find this in the history" and nothing else.'
)

REWRITE_PROMPT = (
    "You rewrite a user's question so it matches how developers write commit "
    "messages in the repository {repo}. "
    "Use the technical words those commits would use. "
    'For example "why do my login details disappear between requests" becomes '
    '"session cookie persistence, cookie jar". '
    "Reply with the short search query only: one line, no quotes, no explanation."
)


@lru_cache(maxsize=1)
def get_model():
    """Load the embedding model once and reuse it afterwards."""
    return SentenceTransformer(MODEL_NAME)


@lru_cache(maxsize=None)
def get_collection(repo):
    """Open this repo's ChromaDB collection once and reuse it afterwards."""
    client = chromadb.PersistentClient(path="chroma_db")
    return client.get_collection(collection_name(repo))


def get_groq_client():
    """Create the Groq client using the key from .env (the key is never printed)."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is missing from .env")
    return Groq(api_key=api_key)


def rewrite_query(question, repo):
    """Turn a user's wording into the technical words used in commit messages."""
    response = get_groq_client().chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": REWRITE_PROMPT.format(repo=repo)},
            {"role": "user", "content": question},
        ],
        temperature=0,  # same question should give the same query every time
    )
    # Keep it short and clean: first line, no wrapping quotes.
    text = response.choices[0].message.content.strip().splitlines()[0]
    query = text.strip().strip('"').strip()
    return query or question


def retrieve(question, model=None, collection=None, rewrite=False, repo=None):
    """Find the top 5 unique commits, each with its best matching chunk.

    With rewrite=True the question is also asked in technical terms and both
    searches are merged, keeping each commit's best (smallest) distance.
    Returns (matches, rewritten_query), where rewritten_query is None if unused.
    """
    repo = repo or get_repo()
    model = model or get_model()
    collection = collection or get_collection(repo)

    rewritten = None
    queries = [question]
    if rewrite:
        rewritten = rewrite_query(question, repo)
        queries.append(rewritten)

    # Keep only the best chunk for each commit, so one commit can't fill the list.
    best_per_commit = {}
    for query in queries:
        embedding = model.encode([query]).tolist()
        results = collection.query(
            query_embeddings=embedding,
            n_results=CANDIDATES,
            include=["documents", "metadatas", "distances"],
        )
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
    return matches[:RESULTS], rewritten


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


def answer_question(question, matches=None, repo=None):
    """Return (answer, matches): the model's answer and the commits it saw."""
    if matches is None:
        matches, _ = retrieve(question, rewrite=True, repo=repo)
    if not matches:
        return "I couldn't find this in the history", matches

    response = get_groq_client().chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Question: {question}\n\nCommits:\n\n{build_context(matches)}",
            },
        ],
    )
    return normalize_citations(response.choices[0].message.content.strip()), matches


def normalize_citations(answer):
    """Models sometimes wrap citations in full-width brackets 【sha】; use [sha]."""
    return re.sub(r"【([0-9a-f]{7})】", r"[\1]", answer)


def main():
    # The question and the repo come from the command line.
    parser = argparse.ArgumentParser(description="Ask a question about a repo's history.")
    parser.add_argument("--repo", help="owner/name (default: REPO from .env, else psf/requests)")
    parser.add_argument("question", nargs="+", help="the question to ask")
    args = parser.parse_args()

    question = " ".join(args.question).strip()
    repo = get_repo(args.repo)

    # Find the commits that probably contain the answer, then ask the model.
    print(f"Searching {repo} for: {question}")
    try:
        matches, rewritten = retrieve(question, rewrite=True, repo=repo)
        print(f"Rewritten query: {rewritten}")
        answer, matches = answer_question(question, matches, repo=repo)
    except RuntimeError as error:
        raise SystemExit(str(error))

    # Show the answer, then the commits it was allowed to use.
    print(f"\n{answer}\n")
    print("Commits used:")
    for rank, match in enumerate(matches, start=1):
        metadata = match["metadata"]
        print(f"{rank}. {metadata['sha'][:7]}  {metadata['date'][:10]}  {metadata['message']}")


if __name__ == "__main__":
    main()