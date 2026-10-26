"""Answer a question about a repo's history from the command line."""

import argparse

from repo_memory.config import get_repo
from repo_memory.llm import answer_question
from repo_memory.retrieval import retrieve
from repo_memory.timefmt import format_ist


def main():
    parser = argparse.ArgumentParser(description="Ask a question about a repo's history.")
    parser.add_argument("--repo", help="owner/name (default: REPO from .env, else psf/requests)")
    parser.add_argument("question", nargs="+", help="the question to ask")
    args = parser.parse_args()

    question = " ".join(args.question).strip()
    repo = get_repo(args.repo)

    print(f"Searching {repo} for: {question}")
    try:
        matches, rewritten = retrieve(question, rewrite=True, repo=repo)
        print(f"Rewritten query: {rewritten}")
        answer = answer_question(question, matches, repo=repo)
    except RuntimeError as error:
        raise SystemExit(str(error))

    print(f"\n{answer}\n")
    print("Commits used:")
    for rank, match in enumerate(matches, start=1):
        metadata = match["metadata"]
        print(f"{rank}. {metadata['sha'][:7]}  {format_ist(metadata['date'])}  {metadata['message']}")


if __name__ == "__main__":
    main()