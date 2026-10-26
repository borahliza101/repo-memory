"""Build the searchable commit memory for a repo from its saved JSON file."""

import argparse
import json

from repo_memory.chunking import is_bot_commit
from repo_memory.config import commits_path, get_repo
from repo_memory.store import build_repo_memory


def main():
    parser = argparse.ArgumentParser(description="Build the searchable commit memory.")
    parser.add_argument("--repo", help="owner/name (default: REPO from .env, else psf/requests)")
    args = parser.parse_args()
    repo = get_repo(args.repo)

    path = commits_path(repo)
    with open(path, encoding="utf-8") as f:
        commits = json.load(f)
    print(f"Loaded {len(commits)} commits from {path}")

    skipped = sum(1 for commit in commits if is_bot_commit(commit))
    print(f"Skipped {skipped} bot commits")
    print(f"Built {len(commits) - skipped} commits into chunks")

    collection, kept = build_repo_memory(repo, commits, progress=print)
    print(f"Stored {kept} commits and {collection.count()} chunks in {collection.name}")


if __name__ == "__main__":
    main()