"""Write an auto-generated decision log for a repo."""

import argparse

from repo_memory.config import get_repo
from repo_memory.decisions import generate


def main():
    parser = argparse.ArgumentParser(description="Write a decision log from the commit memory.")
    parser.add_argument("--repo", help="owner/name (default: REPO from .env, else psf/requests)")
    args = parser.parse_args()
    repo = get_repo(args.repo)

    path, count = generate(repo)
    if path:
        print(f"Wrote {count} decisions to {path}")


if __name__ == "__main__":
    main()