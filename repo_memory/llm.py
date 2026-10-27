"""Talking to the LLM: rewrite a question, stream an answer, tidy citations."""

import os
import re

from dotenv import load_dotenv
from groq import Groq, RateLimitError

from .timefmt import format_ist

load_dotenv()

# Two models, because they are paid for with the same token budget:
# the big one writes the answer, the small one does the cheap background work.
# Groq retired llama-3.1-8b-instant, so the cheap default is gpt-oss-20b;
# set LIGHT_MODEL to any small model your account can use.
ANSWER_MODEL = os.getenv("ANSWER_MODEL", "openai/gpt-oss-120b")
LIGHT_MODEL = os.getenv("LIGHT_MODEL", "openai/gpt-oss-20b")

RATE_LIMIT_MESSAGE = "The AI is at its usage limit, try again in a minute"

SYSTEM_PROMPT = (
    "You answer questions about a software project's commit history. "
    "Use only the commits given to you, never outside knowledge. "
    "Do not add background knowledge, general programming advice, or facts that "
    "are not written in the commits. "
    "If the commits mention a change but do not say why, say that the commit does "
    "not explain it, instead of guessing. "
    "Cite commits only as [shortsha] in square brackets, for example [6f66281]. "
    "Do not use any other citation format, and cite the commit for every claim. "
    'If the commits do not contain the answer, reply exactly: '
    '"I couldn\'t find this in the history" and nothing else.'
)

REWRITE_PROMPT = (
    "You rewrite a user's question so it matches how developers write commit "
    "messages in the repository {repo}. "
    "Use the technical words those commits would use. "
    'For example "why do my login details disappear between requests" becomes '
    '"session cookie persistence, cookie jar". '
    "Reply with the short search query only: one line, no quotes, no explanation."
)


def get_groq_client():
    """Create the Groq client using the key from .env (the key is never printed)."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is missing from .env")
    return Groq(api_key=api_key)


def is_rate_limited(error):
    """True when Groq refused the call because the token budget ran out (HTTP 429)."""
    return isinstance(error, RateLimitError) or getattr(error, "status_code", None) == 429


def rewrite_query(question, repo):
    """Turn a user's wording into the technical words used in commit messages."""
    response = get_groq_client().chat.completions.create(
        model=LIGHT_MODEL,
        messages=[
            {"role": "system", "content": REWRITE_PROMPT.format(repo=repo)},
            {"role": "user", "content": question},
        ],
        temperature=0,  # same question should give the same query every time
    )
    # Keep it short and clean: first line, no wrapping quotes.
    text = response.choices[0].message.content.strip().splitlines()[0]
    query = text.strip().strip('"').strip()
    return query or question


def build_context(matches):
    """Turn the retrieved commits into text for the model to read."""
    blocks = []
    for match in matches:
        metadata = match["metadata"]
        blocks.append(
            f"Commit {metadata['sha'][:7]} by {metadata['author']} on {format_ist(metadata['date'])}\n"
            f"Message: {metadata['message']}\n"
            f"Code and files:\n{match['document']}"
        )
    return "\n\n---\n\n".join(blocks)


def _messages(question, matches):
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Question: {question}\n\nCommits:\n\n{build_context(matches)}",
        },
    ]


def stream_answer(question, matches, repo=None):
    """Yield the answer as the model writes it, so the UI can show it live."""
    if not matches:
        yield "I couldn't find this in the history"
        return

    stream = get_groq_client().chat.completions.create(
        model=ANSWER_MODEL, messages=_messages(question, matches), stream=True
    )
    for chunk in stream:
        piece = chunk.choices[0].delta.content
        if piece:
            yield piece


def answer_question(question, matches, repo=None):
    """Return the model's answer for the given commits (with citations tidied)."""
    if not matches:
        return "I couldn't find this in the history"

    response = get_groq_client().chat.completions.create(
        model=ANSWER_MODEL, messages=_messages(question, matches)
    )
    return normalize_citations(response.choices[0].message.content.strip())


def normalize_citations(answer):
    """Tidy up how the model writes citations.

    Models sometimes wrap citations in full-width brackets 【sha】, put spaces
    inside them like [ sha ], or forget the closing bracket like [ sha. All
    become [sha], so the app can link them.
    """
    answer = re.sub(r"【([0-9a-f]{7})】", r"[\1]", answer)
    answer = re.sub(r"\[\s*([0-9a-f]{7})\s*\]", r"[\1]", answer)
    # Missing closing bracket: "[ f780219." or "[f780219," (runs after the
    # complete-bracket rules above, so a valid [sha] is never touched).
    answer = re.sub(r"\[\s*([0-9a-f]{7})(?=[.,;:!?)]|$)", r"[\1]", answer)
    return answer


def normalize_stream(chunks):
    """Clean citations as chunks arrive, holding back split brackets.

    A citation can be split across chunks, so anything from an unclosed 【 to
    the end is held back until the closing 】 arrives (or the stream ends).
    """
    accumulated = ""
    written = 0
    for piece in chunks:
        accumulated += piece

        # Only convert text that cannot be the start of a half-received citation.
        safe = accumulated
        opening = safe.rfind("【")
        if opening != -1 and "】" not in safe[opening:]:
            safe = safe[:opening]

        text = normalize_citations(safe)
        if len(text) > written:
            yield text[written:]
            written = len(text)

    text = normalize_citations(accumulated)
    if len(text) > written:
        yield text[written:]