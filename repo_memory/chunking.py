"""Turning commits into text chunks. No database, no network."""

from datetime import datetime, timezone

CHUNK_SIZE = 2000
CHUNK_OVERLAP = 200


def make_summary(commit):
    """Short text with only the purpose (message + filenames), no code."""
    short_sha = commit["sha"][:7]
    filenames = ", ".join(f["filename"] for f in commit["files"])

    return (
        f"Commit {short_sha} by {commit['author']} on {commit['date']}\n\n"
        f"Message: {commit['message']}\n\n"
        f"Files changed: {filenames}"
    )


def make_document(commit):
    """Turn one commit into a single text document, including the code changes."""
    patches = "\n".join(f["patch"] for f in commit["files"])

    return f"{make_summary(commit)}\n\nChanges: {patches}"


def split_text(text):
    """Split long text into overlapping chunks so no context is lost at the edges."""
    if len(text) <= CHUNK_SIZE:
        return [text]

    chunks = []
    step = CHUNK_SIZE - CHUNK_OVERLAP
    start = 0
    while start < len(text):
        chunks.append(text[start : start + CHUNK_SIZE])
        if start + CHUNK_SIZE >= len(text):
            break
        start += step
    return chunks


def is_dependabot_merge(message):
    """A merge commit that brought in a dependabot pull request."""
    first_line = message.splitlines()[0] if message else ""
    return first_line.startswith("Merge pull request") and "/dependabot/" in first_line


def is_bot_commit(commit):
    """Skip real bots and dependabot merges, but keep humans who mention the word."""
    author = commit.get("author") or ""
    return author.endswith("[bot]") or is_dependabot_merge(commit.get("message") or "")


def build_entries(commits):
    """Turn commits into chunks: one summary chunk plus the code chunks each.

    Returns (ids, documents, metadatas, skipped_bot_commits).
    """
    ids = []
    documents = []
    metadatas = []
    skipped = 0

    for commit in commits:
        if is_bot_commit(commit):
            skipped += 1
            continue

        first_line = commit["message"].splitlines()[0] if commit["message"] else ""
        metadata = {
            "sha": commit["sha"],
            "author": commit["author"],
            "date": commit["date"],
            "message": first_line,
            # When this commit entered the memory, for the app's memory feed.
            "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

        # A short summary chunk, so the commit's purpose is easy to find.
        ids.append(f"{commit['sha']}-summary")
        documents.append(make_summary(commit))
        metadatas.append(metadata)

        # The full code chunks, so details are searchable as well. An empty
        # commit has no files, so its code chunk would just repeat the summary.
        if commit["files"]:
            for index, chunk in enumerate(split_text(make_document(commit))):
                ids.append(f"{commit['sha']}-{index}")
                documents.append(chunk)
                metadatas.append(metadata)

    return ids, documents, metadatas, skipped