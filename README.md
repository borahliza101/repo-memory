\# Repo Memory



A codebase that remembers \*why\* it changed.



\## The problem



Every software project has a long history of changes (commits). When someone

asks "why is this code written like this?", the answer is usually buried in

hundreds of old commits. Nobody has time to scroll through them.



It's like a WhatsApp group with two years of messages: someone asks "why did we

choose Goa over Manali?" and nobody remembers, even though the answer is in

there somewhere.



\## What it does



Repo Memory reads a project's commit history and answers questions about it in

plain English, for example:



\- "Why did they add hasattr checks to the protocol code?"

\- "When did they change how redirects are handled, and why?"



Every answer cites the exact commits it came from, so you can check it.



\## How it works



1\. \*\*Fetch:\*\* get recent commits (message + code changes) from the GitHub API

2\. \*\*Clean:\*\* skip bot commits (like dependabot) that add noise

3\. \*\*Chunk:\*\* split each commit into pieces of text

4\. \*\*Embed:\*\* turn each piece into a vector and store it in ChromaDB

5\. \*\*Ask:\*\* find the commits closest to the question and let an open-source

&#x20;  model answer using only those commits, citing their IDs



\## Plan for this hackathon



\- \[ ] Fetch commits from a real repo (psf/requests)

\- \[ ] Build the commit memory (chunk + embed + store)

\- \[ ] Question answering with commit citations

\- \[ ] Simple web page to ask questions

\- \[ ] Stretch: generate a DECISIONS.md log of the project's key decisions



\## Dev log



See DEVLOG.md for how my thinking changed while building this.

