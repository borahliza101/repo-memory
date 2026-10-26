"""Fetch recent commits from GitHub and save them to data/commits_<repo>.json."""

import argparse
import json
import os

from repo_memory.config import commits_path, get_repo
from repo_memory.github_client import fetch_commits


def main():
    parser = argparse.ArgumentParser(description="Fetch recent commits from GitHub.")
    parser.add_argument("--repo", help="owner/name (default: REPO from .env, else psf/requests)")
    args = parser.parse_args()
    repo = get_repo(args.repo)

    def show_progress(index, total, short_sha, message):
        first_line = message.splitlines()[0] if message else ""
        print(f"[{index}/{total}] Saved {short_sha}: {first_line[:60]}")

    def show_skip(index, total, login):
        print(f"[{index}/{total}] Skipping bot commit ({login})")

    results = fetch_commits(repo, progress=show_progress, on_skip=show_skip)

    # One JSON file per repo, e.g. data/commits_psf_requests.json.
    os.makedirs("data", exist_ok=True)
    path = commits_path(repo)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Done. Saved {len(results)} commits to {path}")


if __name__ == "__main__":
    main()