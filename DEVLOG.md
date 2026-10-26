\# Dev log



\## 1:10 PM – Starting

Idea: give a codebase a memory of why it changed. Choosing psf/requests as test data because it's popular and has thousands of human-written commits. Already noticed many commits are from dependabot, so I'll filter bots out.



\## 1:25 PM – Fetching commits

\- Used Alan to write fetch\_commits.py: gets the 300 newest commits from

&#x20; psf/requests, then fetches each one's message, author, date and code changes.

\- Finding: 57 of 300 (19%) were dependabot commits (automatic dependency

&#x20; bumps). They explain nothing about \*why\* code changed, so I skip bots.

\- Decision: cut each code change (patch) to 3000 characters so huge changes

&#x20; don't drown out the commit message, which carries most of the meaning.

\- Noticed: commit messages say \*what\* changed, but the \*why\* is often in the

&#x20; linked pull request (#7505 etc.). Possible later improvement: fetch PR

&#x20; descriptions too.

