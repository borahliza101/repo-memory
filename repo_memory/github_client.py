"""GitHub REST API access: list commits, fetch details, check a repo exists."""

import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

MAX_COMMITS = 300
PER_PAGE = 100
PATCH_LIMIT = 3000  # cut long code patches down to this many characters
API = "https://api.github.com"


def get_headers():
    """Build the GitHub headers. The token is never printed."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is missing from .env")
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def get_json(url):
    """Call the GitHub API and return the JSON response."""
    response = requests.get(url, headers=get_headers(), timeout=30)
    if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
        # We ran out of requests; wait until GitHub resets the limit.
        reset = int(response.headers.get("X-RateLimit-Reset", time.time() + 60))
        wait = max(reset - int(time.time()), 1)
        print(f"Rate limit hit. Waiting {wait} seconds...")
        time.sleep(wait)
        response = requests.get(url, headers=get_headers(), timeout=30)
    response.raise_for_status()
    return response.json()


def list_commits(repo, max_commits=MAX_COMMITS, per_page=PER_PAGE):
    """Get the newest commits of a repo, a page at a time."""
    commits = []
    page = 1
    while len(commits) < max_commits:
        batch = get_json(f"{API}/repos/{repo}/commits?per_page={per_page}&page={page}")
        if not batch:
            break
        commits.extend(batch)
        print(f"Listed page {page}: {len(batch)} commits")
        page += 1
    return commits[:max_commits]


def get_commit_details(repo, sha):
    """Get one commit with its message, author, date and changed files."""
    data = get_json(f"{API}/repos/{repo}/commits/{sha}")
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


def repo_exists(repo):
    """True if the repo exists and is public. Returns (ok, message)."""
    try:
        get_json(f"{API}/repos/{repo}")
        return True, ""
    except requests.HTTPError as error:
        if error.response.status_code == 404:
            return False, f"Repo {repo} was not found. Check the name, and note that private repos are not supported."
        if error.response.status_code in (401, 403):
            return False, f"No access to {repo}. Only public repos can be read."
        return False, f"GitHub said {error.response.status_code} for {repo}."


def fetch_commits(repo, max_commits=MAX_COMMITS, per_page=PER_PAGE, progress=None, on_skip=None):
    """Fetch commits for a repo and return the cleaned-up commit records.

    progress: optional callback called with (index, total, short_sha, message)
    on_skip:  optional callback called with (index, total, login) for bot commits
    so a UI or CLI can show what is happening.
    """
    raw_commits = list_commits(repo, max_commits, per_page)
    results = []
    for index, item in enumerate(raw_commits, start=1):
        login = (item.get("author") or {}).get("login") or ""
        if login.endswith("[bot]"):
            if on_skip:
                on_skip(index, len(raw_commits), login)
            continue

        details = get_commit_details(repo, item["sha"])
        results.append(details)
        if progress:
            progress(index, len(raw_commits), details["sha"][:7], details["message"])
    return results


def recent_commits(repo, limit=100):
    """The newest commits from GitHub, newest first (one page)."""
    return get_json(f"{API}/repos/{repo}/commits?per_page={limit}&page=1")