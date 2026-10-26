"""Shared settings: which repo to use, and where its data lives."""

import os
import re
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

DEFAULT_REPO = "psf/requests"

# Where ChromaDB keeps its files. Override with CHROMA_PATH (used by tests).
CHROMA_PATH = os.getenv("CHROMA_PATH", "chroma_db")


def parse_repo_input(text):
    """Turn a GitHub URL or 'owner/name' into 'owner/name'.

    Accepts https://github.com/owner/name, github.com/owner/name, owner/name,
    and a trailing slash or .git suffix. Returns None if it makes no sense.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return None

    # Take the path part of a full URL.
    if "://" in cleaned:
        cleaned = urlparse(cleaned).path
    cleaned = cleaned.strip("/")
    if cleaned.lower().startswith("github.com/"):
        cleaned = cleaned[len("github.com/") :]
    cleaned = cleaned.removesuffix(".git")

    parts = [part for part in cleaned.split("/") if part]
    if len(parts) != 2:
        return None
    return f"{parts[0]}/{parts[1]}"


def get_repo(explicit=None):
    """Pick the repo: --repo wins, then REPO in .env, then psf/requests."""
    repo = (explicit or os.getenv("REPO") or DEFAULT_REPO).strip()
    if repo.count("/") != 1 or not all(part for part in repo.split("/")):
        raise SystemExit(f"Repo must look like owner/name, got: {repo}")
    return repo


def _slug(repo):
    """Make 'owner/name' safe for a file name and a collection name."""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", repo.replace("/", "_")).lower()


def collection_name(repo):
    """Every repo gets its own ChromaDB collection, e.g. commits_psf_requests."""
    return f"commits_{_slug(repo)}"


def commits_path(repo):
    return os.path.join("data", f"commits_{_slug(repo)}.json")


def state_path(repo):
    return os.path.join("data", f"state_{_slug(repo)}.json")


def decisions_path(repo):
    return os.path.join("decisions", f"{_slug(repo)}.md")