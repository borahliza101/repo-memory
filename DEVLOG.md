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

## 2:15 PM – Fixing retrieval

What I changed:

- Added a summary chunk per commit containing only the message and the list of changed filenames (no code), so the commit's purpose is not drowned out by long diffs. The code chunks are still there.
- Skipped commits whose message contains "dependabot", which catches bot merge commits that slipped past the author check.
- Changed search.py to fetch 20 chunks, keep only the best-scoring chunk per commit, then show the top 5 unique commits.

| Commit | Topic | Before | After |
| --- | --- | --- | --- |
| dc9dbdf | 3.15 support | no | no (ambiguous question) |
| 5f3ff9b | typo fixes | no | yes, rank 1 |
| 25340eb | proxy vars in tests | no | yes, rank 4 |
| fd62809 | leading slashes | no | no (vocabulary gap: "start of a web address" vs "leading slashes in path_url") |
| d38495c | broken link | yes | no (ambiguous: all 5 results were real broken-link fixes) |

**Score: 1/5 -> 2/5. On the 3 questions with one clear answer: 2/3.**

Lessons:

- Summary chunks fixed short-message commits.
- Good test questions need exactly one right answer.
- Small embedding models miss vocabulary gaps (idea: let the LLM rewrite the question into technical terms before searching).

## 4:15 PM – Answers

ask.py works end to end with Groq gpt-oss-120b. Tested "Why did they add hasattr checks?": it combined 3 commits from different months (8f6cda9, 6f205ff, 6f66281) into one explanation. I checked its citation against GitHub: the quoted comment in 6f205ff is real. It refuses unrelated questions ("capital of France" -> "I couldn't find this in the history").

## 4:30 PM – Fair test

Caught data leakage: my first rewrite prompt used my own test question as its example, so the improvement on fd62809 wasn't a fair test. Replaced the example and re-measured.

| Question | No rewrite | With rewrite | Rewritten query |
| --- | --- | --- | --- |
| 3.15 support | miss | miss | Python 3.12 support added |
| typo fixes | hit | hit | spellcheck integration, typo detection |
| proxy vars in tests | hit | hit | test suite failures due to network configuration and proxy settings |
| leading slashes | miss | miss | url scheme normalization bug |
| broken link | miss | miss | docs broken link fix |

**Score: 2/5 without rewrite, 2/5 with rewrite.**

Set temperature=0 so this is repeatable. An earlier run at the default temperature scored 3/5 by finding fd62809 at rank 2, but that result does not reproduce at temperature=0, so the gain was sampling luck rather than a real improvement.

## 5:00 PM – Testing on my own repo

Running the whole pipeline on borahliza101/repo-memory exposed three bugs that psf/requests never showed:

- The bot filter was too broad: it dropped any commit whose message contained "dependabot", so two of my own commits disappeared from the memory. It now skips only bot accounts ("[bot]" logins) and merges of dependabot pull requests ("Merge pull request" plus "/dependabot/"). After the fix psf/requests keeps 215 commits (28 skipped, down from 30), and my repo keeps all 10 (0 skipped, where 2 would have been lost).
- The rewrite prompt said "a Python HTTP library", so on a small personal repo it rewrote questions towards the wrong vocabulary. It now uses the actual repo name.
- The model sometimes cited commits with full-width brackets (【sha】), which the app's link conversion did not recognise, so those citations came out as plain text. Answers are now normalised to [sha] before links are built.

Testing on a second repo was worth more than another question on the first one: every bug was about an assumption that happened to hold for a big, well-labelled library.
