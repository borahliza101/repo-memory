"""Test retrieval on the command line, with or without query rewriting."""

import argparse

from ask import retrieve
from config import get_repo


def main():
    parser = argparse.ArgumentParser(description="Search a repo's commit memory.")
    parser.add_argument("question", nargs="+", help="the question to search for")
    parser.add_argument("--repo", help="owner/name (default: REPO from .env, else psf/requests)")
    parser.add_argument(
        "--rewrite",
        action="store_true",
        help="also search with an LLM-rewritten technical query",
    )
    args = parser.parse_args()

    question = " ".join(args.question)
    repo = get_repo(args.repo)

    try:
        matches, rewritten = retrieve(question, rewrite=args.rewrite, repo=repo)
    except RuntimeError as error:
        raise SystemExit(str(error))

    print(f"Repo: {repo}")
    print(f"Question: {question}")
    if rewritten:
        print(f"Rewritten query: {rewritten}")
    print()

    for rank, match in enumerate(matches, start=1):
        metadata = match["metadata"]
        print(f"{rank}. {metadata['sha'][:7]}  {metadata['date'][:10]}  {metadata['message']}")
        print(f"   distance: {match['distance']:.4f}")


if __name__ == "__main__":
    main()