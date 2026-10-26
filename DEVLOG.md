# Dev log

## 1:10 PM – Starting

Idea: give a codebase a memory of why it changed. Choosing psf/requests as test data because it's popular and has thousands of human-written commits. Already noticed many commits are from dependabot, so I'll filter bots out.

## 1:25 PM – Fetching commits

- Used Alan to write fetch_commits.py: gets the 300 newest commits from psf/requests, then fetches each one's message, author, date and code changes.
- Finding: 57 of 300 (19%) were dependabot commits (automatic dependency bumps). They explain nothing about *why* code changed, so I skip bots.
- Decision: cut each code change (patch) to 3000 characters so huge changes don't drown out the commit message, which carries most of the meaning.
- Noticed: commit messages say *what* changed, but the *why* is often in the linked pull request (#7505 etc.). Possible later improvement: fetch PR descriptions too.

## 2:00 PM – Building the memory + first evaluation

- Used Alan to write build_memory.py: 243 commits split into 462 chunks (message + code changes, 2000 chars, 200 overlap), embedded with all-MiniLM-L6-v2, stored in ChromaDB. Also search.py to test retrieval before adding an LLM.
- First test used the commit's own words ("why add hasattr checks") and found the right commit at rank 1. Too easy: real users won't know the exact wording.

### Evaluation: 5 reworded questions (no words copied from the commit message)

| Commit | Question | Found in top 5? |
| --- | --- | --- |
| dc9dbdf | When did the library officially start working with the newest Python version? | no |
| 5f3ff9b | Did they use a tool to find spelling mistakes? | no |
| 25340eb | Why were tests affected by the computer's network settings? | no |
| fd62809 | Was there a bug where the start of a web address got changed? | no |
| d38495c | Did they fix a broken link in the guide for people who want to help? | yes (rank 3) |

**Baseline: 1/5.**

### What I learned

- Short commit messages get drowned out by long code diffs in the same chunk, so the chunk stops "meaning" what the commit was for.
- Vague questions get plausible but wrong answers (asked about the "newest" Python version, got the 3.14 commit instead of 3.15).
- The same commit can fill several of the top 5 slots (duplicate chunks).
- Bot filter gap: "Merge pull request ... dependabot" commits get through, because a human clicked merge.

### Next

- Add a message-only chunk per commit, skip dependabot merges, return unique commits. Then re-run the same 5 questions and compare.
