"""Watch a repo for new commits and add them to the existing memory."""

import argparse
import json
import os
import time

from build_memory import add_chunks, build_entries, is_dependabot_merge
from config import collection_name, get_repo, state_path
from fetch_commits import API, get_commit_details, get_json

MAX_PAGES = 10  # safety cap: look at most 1000 commits back for the last seen one


def is_bot(item):
    """True for real bot accounts and dependabot merges, not for humans mentioning it."""
    login = (item.get("author") or {}).get("login") or ""
    message = (item.get("commit") or {}).get("message") or ""
    return login.endswith("[bot]") or is_dependabot_merge(message)


def read_last_sha(path):
    """Read the last sha we saw, or None on the very first run."""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("last_sha")


def save_last_sha(path, sha):
    """Remember where to resume the next time we check."""
    os.makedirs("data", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"last_sha": sha}, f)


def new_commits_since(repo, last_sha):
    """Return commits newer than last_sha, oldest first."""
    found = []
    for page in range(1, MAX_PAGES + 1):
        batch = get_json(f"{API}/repos/{repo}/commits?per_page=100&page={page}")
        if not batch:
            break
        for item in batch:
            if item["sha"] == last_sha:
                return list(reversed(found))
            found.append(item)
        if len(batch) < 100:
            break  # repo has fewer commits than we looked at
    return list(reversed(found))


def check_once(repo, state_file, name):
    """Look for new commits and add them to this repo's collection."""
    last_sha = read_last_sha(state_file)

    if last_sha is None:
        # First run: just remember the newest commit, then start from there.
        newest = get_json(f"{API}/repos/{repo}/commits?per_page=1")
        if not newest:
            print("Repo has no commits yet.")
            return
        sha = newest[0]["sha"]
        save_last_sha(state_file, sha)
        print(f"First run: starting from {sha[:7]}. Run build_memory.py if the memory is empty.")
        return

    commits = new_commits_since(repo, last_sha)
    added = []
    for item in commits:
        if is_bot(item):
            continue

        details = get_commit_details(repo, item["sha"])
        # Each new commit gets a summary chunk and its code chunks, like build_memory.
        ids, documents, metadatas, _ = build_entries([details])
        add_chunks(ids, documents, metadatas, name, repo)
        added.append(f"{details['sha'][:7]} {details['message'].splitlines()[0]}")

    if commits:
        save_last_sha(state_file, commits[-1]["sha"])

    if added:
        print(f"Added {len(added)} new commits: " + ", ".join(added))
    else:
        print("No new commits.")


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