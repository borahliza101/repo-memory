"""Fetch recent commits from psf/requests and save them to data/commits.json."""

import json
import os
import time

import requests
from dotenv import load_dotenv

# Load the token from the .env file (never print it).
load_dotenv()
TOKEN = os.getenv("GITHUB_TOKEN")
if not TOKEN:
    raise SystemExit("GITHUB_TOKEN is missing from .env")

REPO = "psf/requests"
MAX_COMMITS = 300
PER_PAGE = 100
PATCH_LIMIT = 3000  # cut long code patches down to this many characters

# All GitHub API calls use this header so we get permission and a higher rate limit.
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}
API = "https://api.github.com"


def get_json(url):
    """Call the GitHub API and return the JSON response."""
    response = requests.get(url, headers=HEADERS, timeout=30)
    if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
        # We ran out of requests; wait until GitHub resets the limit.
        reset = int(response.headers.get("X-RateLimit-Reset", time.time() + 60))
        wait = max(reset - int(time.time()), 1)
        print(f"Rate limit hit. Waiting {wait} seconds...")
        time.sleep(wait)
        response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def list_commits():
    """Get the newest commits, a page at a time."""
    commits = []
    page = 1
    while len(commits) < MAX_COMMITS:
        url = f"{API}/repos/{REPO}/commits?per_page={PER_PAGE}&page={page}"
        batch = get_json(url)
        if not batch:
            break
        commits.extend(batch)
        print(f"Listed page {page}: {len(batch)} commits")
        page += 1
    return commits[:MAX_COMMITS]


def get_commit_details(sha):
    """Get one commit with its message, author, date and changed files."""
    data = get_json(f"{API}/repos/{REPO}/commits/{sha}")
    commit = data["commit"]

    files = []
    for changed in data.get("files", []):
        patch = changed.get("patch", "")
        files.append(
            {
                "filename": changed["filename"],
                "patch": patch[:PATCH_LIMIT],  # keep only the first 3000 characters
            }
        )

    return {
        "sha": data["sha"],
        "message": commit["message"],
        "author": (commit.get("author") or {}).get("name", "unknown"),
        "date": (commit.get("author") or {}).get("date", ""),
        "files": files,
    }


def main():
    raw_commits = list_commits()
    print(f"Found {len(raw_commits)} commits, now skipping bots and fetching details...")

    results = []
    for index, item in enumerate(raw_commits, start=1):
        login = (item.get("author") or {}).get("login") or ""
        if login.endswith("[bot]"):
            print(f"[{index}/{len(raw_commits)}] Skipping bot commit ({login})")
            continue

        details = get_commit_details(item["sha"])
        results.append(details)
        short_sha = details["sha"][:7]
        print(f"[{index}/{len(raw_commits)}] Saved {short_sha}: {details['message'].splitlines()[0][:60]}")

    os.makedirs("data", exist_ok=True)
    with open(os.path.join("data", "commits.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Done. Saved {len(results)} commits to data/commits.json")


if __name__ == "__main__":
    main()
