"""Keeping a repo's memory up to date as new commits arrive."""

import json
import os

from .chunking import is_dependabot_merge, make_summary
from .config import collection_name, state_path
from .github_client import get_commit_details, recent_commits
from .llm import RATE_LIMIT_MESSAGE, is_rate_limited
from .store import add_chunks, build_entries, stored_shas

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


def check_once(repo, state_file=None, name=None):
    """Add every recent commit that is not in the memory yet.

    Comparing full sha sets (not just the newest commit) means commits that were
    missed earlier are picked up too, not only commits newer than the last check.
    """
    name = name or collection_name(repo)
    state_file = state_file or state_path(repo)

    commits = recent_commits(repo, RECENT_COMMITS)
    if not commits:
        print("Repo has no commits yet.")
        return

    known = stored_shas(name)
    missing = [item for item in commits if item["sha"] not in known and not is_bot(item)]

    added = []
    added_summaries = []
    # Oldest first, so the newest commit is added last (and tops the feed).
    for item in reversed(missing):
        details = get_commit_details(repo, item["sha"])
        # Each new commit gets a summary chunk and its code chunks, like a build.
        ids, documents, metadatas, _ = build_entries([details])
        add_chunks(ids, documents, metadatas, name, repo)
        added.append(f"{details['sha'][:7]} {details['message'].splitlines()[0]}")
        # Keep the lightweight text for the decision log.
        added_summaries.append(
            {"sha": details["sha"], "date": details["date"], "text": make_summary(details)}
        )

    save_last_sha(state_file, commits[0]["sha"])

    if added:
        print(f"Added {len(added)} new commits: " + ", ".join(added))
        # Update the decision log with only the new commits. Never commit here:
        # a commit would create a new commit, which would wake this watcher again.
        try:
            from .decisions import generate_incremental

            path, count = generate_incremental(repo, added_summaries, len(known) + len(missing))
            if path:
                print(f"Updated {path} (+{count} decisions)")
        except Exception as error:
            if is_rate_limited(error):
                print(f"Skipped the decision log: {RATE_LIMIT_MESSAGE}.")
            else:
                print(f"Could not update the decision log: {error}")
    else:
        print("No new commits.")