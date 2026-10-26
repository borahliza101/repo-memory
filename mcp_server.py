"""MCP server: expose Repo Memory as tools for coding agents.

Runs over stdio, so it must never print to stdout (stdout carries the protocol).
Anything diagnostic belongs on stderr, and these tools don't print at all.
"""

import logging
import os

from chromadb.errors import NotFoundError
from mcp.server.fastmcp import FastMCP

from ask import answer_question, format_ist, get_model, retrieve
from config import decisions_path

# Keep the logs quiet: stdout carries the MCP protocol, and noise makes the
# server harder to debug. Anything useful goes to stderr.
logging.basicConfig(level=logging.WARNING, force=True)
for noisy in ("mcp", "sentence_transformers", "transformers", "httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

DEFAULT_REPO = "borahliza101/repo-memory"
MAX_RESULTS = 20  # retrieve looks at this many candidates before ranking
GITHUB_COMMIT = "https://github.com/{repo}/commit/{sha}"

mcp = FastMCP("repo-memory")


def _commit_rows(repo, matches):
    """Turn retrieved chunks into the small shape an agent needs."""
    rows = []
    for match in matches:
        metadata = match["metadata"]
        rows.append(
            {
                "sha": metadata["sha"][:7],
                "date": format_ist(metadata["date"]),
                "message": metadata["message"],
                "url": GITHUB_COMMIT.format(repo=repo, sha=metadata["sha"]),
            }
        )
    return rows


def _missing_memory(repo):
    """The hint we return when a repo has no collection yet."""
    return {
        "error": f"No memory found for {repo}.",
        "hint": f"Run: python fetch_commits.py --repo {repo} && python build_memory.py --repo {repo}",
    }


@mcp.tool()
def ask_repo_history(question: str, repo: str = DEFAULT_REPO) -> dict:
    """Answer a question about a repository's history, citing the commits used.

    Answers come only from commits in the memory. If they don't contain the
    answer, the reply is "I couldn't find this in the history".

    Args:
        question: A plain-English question about why the code changed.
        repo: Repository as owner/name. Defaults to borahliza101/repo-memory.
    """
    try:
        matches, rewritten = retrieve(question, repo=repo, rewrite=True)
    except NotFoundError:
        return _missing_memory(repo)

    answer, matches = answer_question(question, matches, repo=repo)
    return {
        "repo": repo,
        "answer": answer,
        "rewritten_query": rewritten,
        "commits": _commit_rows(repo, matches),
    }


@mcp.tool()
def search_commits(query: str, repo: str = DEFAULT_REPO, k: int = 5) -> dict:
    """Find the commits closest to a query, without asking the LLM.

    Use this to look up commits yourself; it is faster than ask_repo_history
    and needs no language-model call.

    Args:
        query: Search text, ideally technical words used in commit messages.
        repo: Repository as owner/name. Defaults to borahliza101/repo-memory.
        k: How many commits to return (1 to 20). Defaults to 5.
    """
    k = max(1, min(k, MAX_RESULTS))
    try:
        matches, _ = retrieve(query, repo=repo, rewrite=False, k=k)
    except NotFoundError:
        return _missing_memory(repo)
    return {"repo": repo, "query": query, "commits": _commit_rows(repo, matches)}


@mcp.tool()
def get_decision_log(repo: str = DEFAULT_REPO) -> str:
    """Return the auto-generated decision log (markdown) for a repository.

    The log groups real design decisions by month, each with a reason and
    [shortsha] citations. Regenerate it with decisions.py after new commits.

    Args:
        repo: Repository as owner/name. Defaults to borahliza101/repo-memory.
    """
    path = decisions_path(repo)
    if not os.path.exists(path):
        return (
            f"No decision log for {repo} yet. "
            f"Run: python decisions.py --repo {repo}"
        )
    with open(path, encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    # Load the embedding model once, before serving, so the first call is fast.
    get_model()
    mcp.run(transport="stdio")