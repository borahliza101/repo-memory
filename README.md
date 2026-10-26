# Repo Memory

A codebase that remembers *why* it changed.

## The problem

Every software project has a long history of changes (commits). When someone asks "why is this code written like this?", the answer is usually buried in hundreds of old commits. Nobody has time to scroll through them.

It's like a WhatsApp group with two years of messages: someone asks "why did we choose Goa over Manali?" and nobody remembers, even though the answer is in there somewhere.

## What it does

Repo Memory reads a project's commit history and answers questions about it in plain English, for example:

- "Why did they add hasattr checks to the protocol code?"
- "When did they change how redirects are handled, and why?"

Every answer cites the exact commits it came from, so you can check it.

## How it works

1. **Fetch:** get recent commits (message + code changes) from the GitHub API
2. **Clean:** skip bot commits (like dependabot) that add noise
3. **Chunk:** split each commit into pieces of text
4. **Embed:** turn each piece into a vector and store it in ChromaDB
5. **Ask:** find the commits closest to the question and let an open-source model answer using only those commits, citing their IDs

## Plan for this hackathon

- [ ] Fetch commits from a real repo (psf/requests)
- [ ] Build the commit memory (chunk + embed + store)
- [ ] Question answering with commit citations
- [ ] Simple web page to ask questions
- [ ] Stretch: generate a DECISIONS.md log of the project's key decisions

## Dev log

See DEVLOG.md for how my thinking changed while building this.

## Watch mode

`watch.py` keeps the memory up to date while you work. Every few seconds it checks for commits that arrived since the last check and adds them to the existing memory. Nothing is rebuilt.

```
python watch.py --repo psf/requests --interval 60
```

The first run only records the newest commit as a starting point, so build the memory first:

```
python fetch_commits.py --repo psf/requests
python build_memory.py --repo psf/requests
```

The last seen commit is saved in `data/state_<repo>.json`, and bot commits are skipped. New commits get the same treatment as the initial build: one summary chunk plus the code chunks.

Every script takes `--repo owner/name`, and each repo gets its own ChromaDB collection (`commits_psf_requests`, `commits_borahliza101_repo-memory`). You can also set `REPO=owner/name` in `.env` instead of passing the flag.
