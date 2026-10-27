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

## 6:15 PM – App searched a stale memory

The watcher and the app are separate processes. ChromaDB caches the vector index inside each process, so the app counted 13 commits (that read goes to SQLite) but only searched the 11 that existed when its process started, until a restart. Fixed by clearing Chroma's shared system cache before each query, so a new view of the index is opened every time. Verified with a two-process test: a process that saw 1 record before an external write retrieved that new record after the fix, where before it kept returning the old one.

## 7:00 PM – MCP server for coding agents

Made the memory usable from any coding agent: `mcp_server.py` speaks the Model Context Protocol over stdio with the official Python SDK and exposes three tools, `ask_repo_history`, `search_commits` and `get_decision_log`. The tools call the existing `ask.py` and `decisions.py` functions instead of copying them, so the CLI, the web app and the MCP server can never drift apart.

Three things worth remembering:

- A stdio server must never print to stdout, because stdout carries the protocol. The tools print nothing, and the server quiets the model download logs.
- The embedding model is loaded once when the server starts, so the first tool call is not slow.
- The SDK renamed `FastMCP` to `MCPServer` in version 2, so the project pins `mcp<2`.

`test_mcp.py` starts the server as a subprocess, lists the tools, and calls `ask_repo_history("When did I test watch mode?")`, which returns the answer plus the five commits it used. Connecting it: in Alan, **Settings → Account → Plugins → MCP → Add custom connector**, connector type **Command**, with the venv Python and `mcp_server.py` as the single argument; in Claude Code, `claude mcp add repo-memory -- "<python path>" "<script path>"`. Both need a path that exists wherever the agent runs, which is why a cloud sandbox wants an HTTPS connector instead.

## 8:30 PM – Remember any repo from the UI

The idea came from a friend who tried the app on a fresh machine: the only way in was the command line, and the first thing they hit was "No memory found" with no way forward. So the app now has a "Remember a new repo" box in the sidebar: paste a GitHub URL, pick how many recent commits to read, press "Build memory", and the repo is fetched, embedded and added to the dropdown. If the repo is already in the memory, the button says "Update" and only adds the commits that are missing, using the same logic as the watcher.

Three bugs came out of that feedback, all of which only a fresh install would show:

- The selectbox key could not be set after the widget was created, so the newly built repo was never selected. It now uses a pending key that is applied before the selectbox is built.
- The success message was lost on the rerun that followed the build, so the app looked like it had done nothing. It is now kept in session state and shown after the redraw.
- The form was hidden behind an early stop when no memory existed, which is exactly the case a new user is in. Now nothing stops before the form: a fresh install shows a welcome, the URL form and a psf/requests suggestion, and the selector, timeline, feed and Ask tab stay hidden until a memory exists.

Also tightened the answer prompt so the model does not add background knowledge that is not in the commits, and made sure citations written as [ f140c94 ] or 【f140c94】 are turned into [f140c94] before they are turned into links.

## 9:15 PM – Staying inside the token budget

Groq's free tier counts every token against one daily budget, and by the end of the day my own testing had eaten it: the app answered with an HTTP 429 instead of an answer, which is a bad look in a demo. Three changes to bring the cost down:

- Two models, both configurable in `.env`. `ANSWER_MODEL` (default `openai/gpt-oss-120b`) is only used to write the final answer, because that is the one place quality is visible. `LIGHT_MODEL` does query rewriting and the decision log, where a small model is plenty. I first pointed it at `llama-3.1-8b-instant`, but Groq has retired that model (a 404, not a rate limit), so the default is `openai/gpt-oss-20b`. Rewriting a question was previously as expensive as answering it.
- The decision log is now incremental. The watcher used to send the whole history to the model every time a commit arrived; it now sends only the new commits and merges the results into the existing markdown, reading the old entries back out of the file. On a repo with 200 commits that turns a 5-call rebuild into a 1-call update.
- A 429 is no longer an error in the UI. The app says "The AI is at its usage limit, try again in a minute" instead of a stack-trace message, and the watcher keeps adding commits to the memory while skipping the decision log for that round.

Also removed a leftover unused variable in the chunker while I was in there.
