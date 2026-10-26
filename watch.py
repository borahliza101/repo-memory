"""Watch a repo and add new commits to the memory as they arrive."""

import argparse
import time

from repo_memory.config import collection_name, get_repo, state_path
from repo_memory.watcher import check_once


def main():
    parser = argparse.ArgumentParser(description="Keep a repo's memory up to date.")
    parser.add_argument("--repo", help="owner/name (default: REPO from .env, else psf/requests)")
    parser.add_argument("--interval", type=int, default=60, help="seconds between checks")
    args = parser.parse_args()

    repo = get_repo(args.repo)
    name = collection_name(repo)
    state_file = state_path(repo)

    print(f"Watching {repo} every {args.interval}s, adding to {name}")
    try:
        while True:
            check_once(repo, state_file, name)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped watching.")


if __name__ == "__main__":
    main()