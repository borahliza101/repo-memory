"""Streamlit web app for Repo Memory."""

import json
import os
import re
from datetime import datetime, timezone

import plotly.graph_objects as go
import streamlit as st


from repo_memory.config import (
    collection_name,
    commits_path,
    decisions_path,
    get_repo,
    parse_repo_input,
)
from repo_memory.github_client import fetch_commits, repo_exists
from repo_memory.llm import (
    RATE_LIMIT_MESSAGE,
    is_rate_limited,
    normalize_citations,
    normalize_stream,
    rewrite_query,
    stream_answer,
)
from repo_memory.retrieval import retrieve
from repo_memory.store import (
    add_missing_commits,
    build_repo_memory,
    files_changed,
    get_model,
    known_repos,
    open_client,
    unique_commits,
)
from repo_memory.timefmt import format_ist, to_ist

# Page settings must be set before any other Streamlit output.
st.set_page_config(page_title="Repo Memory", page_icon="🧠")

COLOR_USED = "#8b5cf6"  # violet dot for commits the answer used
COLOR_OTHER = "rgba(203, 213, 225, 0.6)"  # light grey for the rest
PREFERRED_REPO = "borahliza101/repo-memory"  # demo default, when it has a memory

SUGGESTIONS = {
    "borahliza101/repo-memory": [
        ("When did I test watch mode?", "When did I test watch mode?"),
        ("Why summary chunks?", "Why did they add summary chunks?"),
        ("Changes after my own repo?", "What did they change after testing on my own repo?"),
        ("How was retrieval measured?", "How did they measure retrieval quality?"),
    ],
    "psf/requests": [
        ("Why hasattr checks?", "Why did they add hasattr checks?"),
        ("When was old Python dropped?", "When did they drop support for older Python versions?"),
        ("Why proxy vars broke tests?", "Why were tests affected by the computer's network settings?"),
        ("Broken link fixes?", "Did they fix a broken link in the guide for people who want to help?"),
    ],
}
FALLBACK_SUGGESTIONS = [
    ("What changed recently?", "What changed most recently?"),
    ("Why was this refactored?", "Why did they refactor this module?"),
    ("When was a bug fixed?", "When did they fix an error handling bug?"),
    ("What changed in tests?", "What did they change about testing?"),
]

# A little styling goes a long way: font, violet accents, lift on hover.
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [data-testid="stMarkdownContainer"] {
    font-family: 'Inter', ui-sans-serif, system-ui, sans-serif;
}

/* Text elements only. Never target every [class*="st-"] element: that also hits
   Streamlit's icon spans, which need their Material ligature font. */
[data-testid="stWidgetLabel"],
[data-testid="stCaptionContainer"],
[data-testid="stHeading"] h1,
[data-testid="stHeading"] h2,
[data-testid="stHeading"] h3,
[data-testid="stExpander"] summary,
[data-testid="stToastText"],
[data-testid="stTab"],
div.stButton > button,
div[data-testid="stSelectbox"] div[data-baseweb="select"] {
    font-family: 'Inter', ui-sans-serif, system-ui, sans-serif;
}

/* Icons: Streamlit draws them as ligature text. If another font wins, the
   ligature stops and the raw name shows up as text (e.g. "_arrow_right"). */
[data-testid="stIconMaterial"],
[data-testid*="Icon"],
[data-testid^="stIcon"],
.material-symbols-rounded,
.material-symbols-outlined {
    font-family: 'Material Symbols Rounded', 'Material Symbols Outlined' !important;
    font-weight: normal !important;
    font-style: normal !important;
    font-feature-settings: 'liga' !important;
    -webkit-font-feature-settings: 'liga' !important;
    letter-spacing: normal !important;
    text-transform: none !important;
    white-space: nowrap !important;
    word-wrap: normal !important;
    direction: ltr !important;
}

h1 { letter-spacing: -0.02em; }

/* Rounded, glowing question box */
div[data-testid="stTextInput"] input {
    border-radius: 14px;
    padding: 12px 16px;
    border: 1px solid rgba(139, 92, 246, 0.35);
    background: rgba(139, 92, 246, 0.05);
}
div[data-testid="stTextInput"] input:focus {
    border-color: #8b5cf6;
    box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.18);
}

/* Commit cards: hover lift plus a subtle violet glow */
div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 14px;
    transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
}
div[data-testid="stVerticalBlockBorderWrapper"]:hover {
    transform: translateY(-3px);
    border-color: rgba(139, 92, 246, 0.55);
    box-shadow: 0 0 0 1px rgba(139, 92, 246, 0.45),
                0 10px 28px rgba(139, 92, 246, 0.16);
}

/* Pill-shaped buttons in the violet accent */
div.stButton > button,
div[data-testid="stTooltipHoverTarget"] > button {
    border-radius: 999px;
    border: 1px solid rgba(139, 92, 246, 0.35);
    transition: border-color .16s ease, color .16s ease, background .16s ease;
    white-space: normal;   /* let a long suggestion wrap instead of truncating */
    height: auto;
    min-height: 2.6em;
    line-height: 1.35;
}
div.stButton > button:hover {
    border-color: #8b5cf6;
    color: #c4b5fd;
    background: rgba(139, 92, 246, 0.10);
}

/* Friendly empty state */
.empty-state {
    border: 1px dashed rgba(139, 92, 246, 0.35);
    border-radius: 16px;
    padding: 22px 18px;
    text-align: center;
    color: #c7cbd6;
    margin: 6px 0 18px;
}
</style>
""",
    unsafe_allow_html=True,
)


def linkify(text, repo, commits):
    """Turn each [shortsha] citation into a link to that commit on GitHub."""
    text = normalize_citations(text)  # [ sha ] and 【sha】 become [sha] first
    full_by_short = {commit["sha"][:7]: commit["sha"] for commit in commits}

    def replace(match):
        short_sha = match.group(1)
        full_sha = full_by_short.get(short_sha)
        if not full_sha:
            return match.group(0)  # unknown commit: leave the text alone
        return f"[{short_sha}](https://github.com/{repo}/commit/{full_sha})"

    return re.sub(r"\[([0-9a-f]{7})\]", replace, text)


def timeline_figure(commits, used_shas):
    """One dot per commit on a date axis; used commits are bigger and labelled."""
    used = set(used_shas)
    is_used = [commit["sha"] in used for commit in commits]

    # Alternate the sha labels above and below the dots, so neighbours don't overlap.
    positions = []
    label_index = 0
    for flag in is_used:
        if flag:
            positions.append("top center" if label_index % 2 == 0 else "bottom center")
            label_index += 1
        else:
            positions.append("top center")

    figure = go.Figure(
        go.Scatter(
            x=[to_ist(commit["date"]).replace(tzinfo=None) for commit in commits],
            y=[0] * len(commits),
            mode="markers+text",
            marker={
                "size": [18 if flag else 10 for flag in is_used],
                "color": [COLOR_USED if flag else COLOR_OTHER for flag in is_used],
                "line": {"width": 0},
            },
            text=[commit["sha"][:7] if flag else "" for commit, flag in zip(commits, is_used)],
            textposition=positions,
            textfont={"size": 11, "color": "#e2e8f0"},
            cliponaxis=False,  # keep sha labels visible above the dots
            customdata=[commit["sha"] for commit in commits],  # lets clicks find the commit
            hovertext=[
                f"{commit['sha'][:7]} · {format_ist(commit['date'])}<br>{commit['message']}"
                for commit in commits
            ],
            hovertemplate="%{hovertext}<extra></extra>",
        )
    )
    figure.update_layout(
        height=180,
        margin={"l": 8, "r": 8, "t": 26, "b": 8},  # tight margins: no dead space
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        dragmode=False,
        xaxis={"type": "date", "showgrid": False, "zeroline": False, "color": "#94a3b8"},
        yaxis={"visible": False, "range": [-0.25, 0.25], "fixedrange": True},
        hoverlabel={"bgcolor": "#1f2937", "font": {"color": "#e5e7eb"}},
    )
    return figure


def time_ago(added_at):
    """Turn a stored timestamp into 'added N minutes ago'."""
    if not added_at:
        return "added earlier"
    then = datetime.fromisoformat(added_at)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)

    minutes = int((datetime.now(timezone.utc) - then).total_seconds() // 60)
    if minutes < 1:
        return "added just now"
    if minutes < 60:
        return f"added {minutes} minutes ago"
    if minutes < 60 * 24:
        return f"added {minutes // 60} hours ago"
    return f"added {minutes // (60 * 24)} days ago"


@st.fragment(run_every=30)
def memory_feed(collection_name_value):
    """The newest commits in the memory; refreshes every 30 seconds.

    It opens its own client each time, so commits that watch.py added since the
    last refresh are visible here.
    """
    collection = open_client().get_collection(collection_name_value)
    metadatas = collection.get(include=["metadatas"])["metadatas"]
    by_sha = {metadata["sha"]: metadata for metadata in metadatas}
    # Most recently added first; ties fall back to the commit date.
    recent = sorted(
        by_sha.values(),
        key=lambda metadata: (metadata.get("added_at") or "", metadata["date"]),
        reverse=True,
    )[:5]

    if not recent:
        st.caption("No commits yet.")
        return

    # Toast only for commits that appeared while the app was open.
    seen = st.session_state.get("feed_seen")
    if seen is None:
        st.session_state["feed_seen"] = set(by_sha)
    else:
        fresh = [metadata for metadata in recent if metadata["sha"] not in seen]
        for metadata in fresh:  # oldest first, so the newest toasts last
            seen.add(metadata["sha"])
        if fresh:
            # Remember the toasts for the redraw: a rerun would wipe them.
            st.session_state["pending_toasts"] = [
                f"New memory: {metadata['sha'][:7]} {metadata['message']}"
                for metadata in fresh
            ]
            # The header count and the timeline were drawn from the old list,
            # so redraw the whole app now that the memory has grown.
            st.rerun()

    for metadata in recent:
        st.markdown(f"`{metadata['sha'][:7]}` {metadata['message']}")
        st.caption(time_ago(metadata.get("added_at")))


def build_memory_form(repos, key_prefix="sidebar"):
    """The 'remember a repo' form, used in the sidebar and on the welcome screen."""
    input_key = f"{key_prefix}_repo_input"
    count_key = f"{key_prefix}_repo_count"

    # A suggestion button may ask for a repo to be filled in and built.
    pending = st.session_state.pop("pending_build", None)
    if pending:
        st.session_state[input_key] = pending

    new_repo_input = st.text_input(
        "GitHub URL or owner/name",
        placeholder="https://github.com/owner/name",
        key=input_key,
    )
    new_repo_count = st.number_input(
        "Recent commits",
        min_value=1,
        max_value=300,
        value=100,
        step=10,
        key=count_key,
    )

    # If the repo is already in the memory, we only add what is missing.
    parsed = parse_repo_input(new_repo_input)
    already_known = bool(parsed) and parsed in repos
    button_label = "Update" if already_known else "Build memory"
    clicked = st.button(button_label, key=f"{key_prefix}_build_btn", width="stretch")

    if not (clicked or pending):
        return

    if not parsed:
        st.error("Please enter a GitHub URL like https://github.com/owner/name")
        return

    target = parsed
    progress_bar = st.progress(0.0)
    status_box = st.empty()

    def show_status(message):
        status_box.markdown(message)

    def show_progress(index, total, short_sha, message):
        progress_bar.progress(min(index / total, 1.0))
        show_status(f"Fetching commit {index}/{total} (`{short_sha}`)...")

    try:
        show_status(f"Checking {target}...")
        ok, reason = repo_exists(target)
        if not ok:
            st.error(reason)
            return

        commits_data = fetch_commits(
            target, max_commits=int(new_repo_count), progress=show_progress
        )
        progress_bar.progress(1.0)
        show_status("Embedding...")
        if already_known:
            collection, count = add_missing_commits(target, commits_data, progress=show_status)
        else:
            collection, count = build_repo_memory(target, commits_data, progress=show_status)

        # Save the commits so the CLI can rebuild later.
        os.makedirs("data", exist_ok=True)
        with open(commits_path(target), "w", encoding="utf-8") as f:
            json.dump(commits_data, f, indent=2, ensure_ascii=False)

        show_status(f"Done: {count} commits remembered")
        # The rerun below would wipe these messages, so keep them.
        st.session_state["build_result"] = f"{target}: {count} commits remembered"
        st.session_state["pending_repo"] = target
        st.rerun()
    except Exception as error:
        st.error(f"Could not build the memory: {error}")


model = get_model()  # cached in repo_memory.store
# A fresh client on every run, so commits added by watch.py show up without a restart.
client = open_client()
repos = known_repos(client)

# Sidebar: pick the repo, see what is fresh, and peek under the hood.
with st.sidebar:
    st.header("Memory")
    if not repos:
        st.caption("No repos yet. Add your first one in the main panel.")

    if repos:
        try:
            # Demo default first, then whatever REPO says, then the first repo found.
            default_repo = PREFERRED_REPO if PREFERRED_REPO in repos else get_repo()
            default_index = sorted(repos).index(default_repo)
        except (SystemExit, ValueError):
            default_index = 0

        # A repo built just now may not be in the list yet, so add it.
        picked = st.session_state.get("selected_repo")
        if picked and picked not in repos:
            repos[picked] = collection_name(picked)
            default_index = sorted(repos).index(picked)

        # A repo that was just built: select it. This has to happen before the
        # selectbox below is created, because a widget key cannot be changed after.
        pending = st.session_state.pop("pending_repo", None)
        if pending:
            st.session_state["selected_repo"] = pending

        repo = st.selectbox(
            "Repo",
            sorted(repos),
            index=default_index,
            key="selected_repo",
        )
        collection = client.get_collection(repos[repo])
        # Read the commits fresh: watch.py may have added some since last time.
        commits = unique_commits(collection)

        st.divider()
        st.subheader("Memory feed")
        memory_feed(repos[repo])

        st.divider()
        with st.expander("Under the hood"):
            st.write(f"**Collection:** `{repos[repo]}`")
            st.write(f"**Chunks:** {collection.count()}")
            st.write("**Embedding model:** `all-MiniLM-L6-v2`")
            st.write("**LLM:** `openai/gpt-oss-120b` (Groq)")
            st.write("**Retrieval:** 20 candidates, best chunk per commit, top 5")

        st.divider()
        st.subheader("Remember a new repo")
        with st.expander("Add a repo to the memory"):
            build_memory_form(repos)

# Show the toasts that were queued before the last rerun.
for message in st.session_state.pop("pending_toasts", []):
    st.toast(message, icon="🧠")

# Show the result of a build that just finished.
build_result = st.session_state.pop("build_result", None)
if build_result:
    st.success(build_result)

# Fresh install: no memory yet. Show the welcome and the form, and stop after
# it, so the selector, feed, timeline and Ask tab stay hidden.
if not repos:
    st.title("Repo Memory")
    st.write("Ask why a codebase changed.")
    st.info("No repos remembered yet. Paste a public GitHub repo to get started.")

    if st.button("Try psf/requests", key="try_psf", width="stretch"):
        st.session_state["pending_build"] = "psf/requests"

    with st.expander("Add a repo to the memory", expanded=True):
        build_memory_form({}, key_prefix="welcome")

    st.stop()

# A new repo means any answer on screen belongs to the old one.
if st.session_state.get("answer_repo") != repo:
    for key in ("answer", "used", "rewritten", "matches", "answer_repo", "selected_commit"):
        st.session_state.pop(key, None)

if commits:
    last_updated = format_ist(commits[-1]["date"])
else:
    last_updated = "never"

st.title("Repo Memory")
st.write("Ask why a codebase changed.")
st.markdown(f"**{repo}** · {len(commits)} commits remembered · last updated {last_updated}")
timeline_slot = st.empty()

tab_ask, tab_decisions = st.tabs(["Ask", "Decisions"])

with tab_ask:
    # Suggested questions for this repo, above the input. The button shows a
    # short label; the full question is in the tooltip and is what gets asked.
    suggestions = SUGGESTIONS.get(repo, FALLBACK_SUGGESTIONS)
    clicked_suggestion = None
    columns = st.columns(len(suggestions))
    for column, (label, full_question) in zip(columns, suggestions):
        if column.button(
            label,
            key=f"suggest-{repo}-{label}",
            help=full_question,
            width="stretch",
        ):
            clicked_suggestion = full_question

    if clicked_suggestion:
        # Fill the box and ask right away.
        st.session_state["question"] = clicked_suggestion

    question = st.text_input(
        "Question",
        key="question",
        placeholder="Ask why something changed...",
    )
    ask_clicked = st.button("Ask", type="primary") or clicked_suggestion is not None

    has_answer = bool(st.session_state.get("answer"))

    if not has_answer and not ask_clicked:
        st.markdown(
            '<div class="empty-state">💬 Ask me anything about why this code changed.</div>',
            unsafe_allow_html=True,
        )

    if ask_clicked:
        if not question.strip():
            st.warning("Please type a question first.")
        else:
            # Live progress, one step at a time. The whole sequence is guarded,
            # because rewriting the question also uses the token budget.
            status = st.status("Rewriting your question...", expanded=True)
            answer = None
            try:
                rewritten = rewrite_query(question, repo)
                status.write(f"**Rewritten query:** {rewritten}")

                status.update(label="Searching commits...")
                status.write(f"Searching {len(commits)} commits...")
                matches, _ = retrieve(
                    question,
                    model=model,
                    collection=collection,
                    repo=repo,
                    rewritten=rewritten,
                )

                status.update(label="Reading the best commits...")
                status.write(f"Reading {len(matches)} commits...")

                status.update(label="Writing the answer...")
                answer_slot = st.empty()
                with answer_slot.container():
                    streamed = st.write_stream(
                        normalize_stream(stream_answer(question, matches, repo))
                    )
                answer = normalize_citations(streamed)
            except Exception as error:  # network, API or usage problem
                if is_rate_limited(error):
                    status.update(label="AI usage limit reached", state="error")
                    st.warning(RATE_LIMIT_MESSAGE)
                else:
                    status.update(label="Something went wrong", state="error")
                    st.error(f"Could not get an answer: {error}")

            if answer:
                status.update(label="Answer ready", state="complete", expanded=False)
                st.session_state["answer_repo"] = repo
                st.session_state["answer"] = answer
                st.session_state["used"] = [match["metadata"]["sha"] for match in matches]
                st.session_state["rewritten"] = rewritten
                st.session_state["matches"] = matches
                # Replace the raw stream with the polished version: real links.
                answer_slot.empty()
                st.markdown(linkify(answer, repo, [m["metadata"] for m in matches]))
                if rewritten:
                    st.caption(f"Search query: {rewritten}")

    # Redraw a stored answer on later reruns (e.g. after clicking a timeline dot).
    if st.session_state.get("answer") and not ask_clicked:
        matches = st.session_state.get("matches", [])
        st.markdown(
            linkify(st.session_state["answer"], repo, [m["metadata"] for m in matches])
        )
        if st.session_state.get("rewritten"):
            st.caption(f"Search query: {st.session_state['rewritten']}")

    if st.session_state.get("answer"):
        matches = st.session_state.get("matches", [])
        st.subheader("Commits used")
        for match in matches:
            metadata = match["metadata"]
            short_sha = metadata["sha"][:7]
            url = f"https://github.com/{repo}/commit/{metadata['sha']}"
            with st.container(border=True):
                st.markdown(f"**[{short_sha}]({url})** — {format_ist(metadata['date'])}")
                st.caption(metadata["author"])
                st.write(metadata["message"])

with tab_decisions:
    decision_file = decisions_path(repo)
    if os.path.exists(decision_file):
        with open(decision_file, encoding="utf-8") as f:
            st.markdown(linkify(f.read(), repo, commits))
    else:
        st.info(f"No decision log yet. Run: python decisions.py --repo {repo}")

# Draw the timeline after the click, so the used commits can be highlighted.
if commits:
    used_shas = st.session_state.get("used", [])
    timeline_slot.plotly_chart(
        timeline_figure(commits, used_shas),
        width="stretch",
        key="timeline",
        on_select="rerun",
        selection_mode="points",
    )

    # Clicking a dot opens that commit's details below the timeline.
    selection = st.session_state.get("timeline") or {}
    points = (selection.get("selection") or {}).get("points") or []
    if points:
        raw = points[0].get("customdata")
        selected_sha = raw[0] if isinstance(raw, list) and raw else raw
        chosen = next((c for c in commits if c["sha"] == selected_sha), None)
        if chosen:
            files = files_changed(collection, chosen["sha"])
            url = f"https://github.com/{repo}/commit/{chosen['sha']}"
            with st.container(border=True):
                st.markdown(f"**[{chosen['sha'][:7]}]({url})** — {chosen['message']}")
                st.caption(f"{chosen['author']} · {format_ist(chosen['date'])}")
                if files:
                    st.write("**Files changed:** " + ", ".join(f"`{name}`" for name in files))
                else:
                    st.write("**Files changed:** none (empty commit)")