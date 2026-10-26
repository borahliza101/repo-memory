"""Shared settings: which repo to use, and where its data lives."""

import os
import re

from dotenv import load_dotenv

load_dotenv()

DEFAULT_REPO = "psf/requests"


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