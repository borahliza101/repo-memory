"""Watch a repo for new commits and add them to the existing memory."""

import argparse
import json
import os
import time

import chromadb
from chromadb.api.shared_system_client import SharedSystemClient

from build_memory import add_chunks, build_entries, is_dependabot_merge
from config import collection_name, get_repo, state_path
from fetch_commits import API, get_commit_details, get_json

RECENT_COMMITS = 100  # how many recent commits we compare against the memory


def is_bot(item):
    """True for real bot accounts and dependabot merges, not for humans mentioning it."""
    login = (item.get("author") or {}).get("login") or ""
    message = (item.get("commit") or {}).get("message") or ""
    return login.endswith("[bot]") or is_dependabot_merge(message)


def save_last_sha(path, sha):
    """Record the newest sha we saw, so the state file shows the last check."""
    os.makedirs("data", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"last_sha": sha}, f)


def recent_commits(repo):
    """The newest commits from GitHub, newest first (one page of 100)."""
    return get_json(f"{API}/repos/{repo}/commits?per_page={RECENT_COMMITS}&page=1")


def stored_shas(name):
    """Every commit sha already in this repo's collection."""
    # Drop Chroma's in-process cache, so writes from other processes are visible.
    SharedSystemClient.clear_system_cache()
    client = chromadb.PersistentClient(path="chroma_db")
    try:
        collection = client.get_collection(name)
    except Exception:
        return set()  # no memory for this repo yet
    metadatas = collection.get(include=["metadatas"])["metadatas"]
    return {metadata["sha"] for metadata in metadatas}


def check_once(repo, state_file, name):
    """Add every recent commit that is not in the memory yet.

    Comparing full sha sets (not just the newest commit) means commits that were
    missed earlier are picked up too, not only commits newer than the last check.
    """
    commits = recent_commits(repo)
    if not commits:
        print("Repo has no commits yet.")
        return

    known = stored_shas(name)
    missing = [
        item for item in commits if item["sha"] not in known and not is_bot(item)
    ]

    added = []
    # Oldest first, so the newest commit is added last (and tops the feed).
    for item in reversed(missing):
        details = get_commit_details(repo, item["sha"])
        # Each new commit gets a summary chunk and its code chunks, like build_memory.
        ids, documents, metadatas, _ = build_entries([details])
        add_chunks(ids, documents, metadatas, name, repo)
        added.append(f"{details['sha'][:7]} {details['message'].splitlines()[0]}")

    save_last_sha(state_file, commits[0]["sha"])

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