"""Streamlit web app for Repo Memory."""

import re
from datetime import datetime, timezone

import chromadb
import plotly.graph_objects as go
import streamlit as st

from ask import answer_question, format_ist, get_model, retrieve, to_ist
from config import get_repo

# Page settings must be set before any other Streamlit output.
st.set_page_config(page_title="Repo Memory", page_icon="🧠")

COLOR_USED = "#8b5cf6"  # violet dot for commits the answer used
COLOR_OTHER = "rgba(203, 213, 225, 0.6)"  # light grey for the rest
PREFERRED_REPO = "borahliza101/repo-memory"  # demo default, when it has a memory


def linkify(answer, matches, repo):
    """Turn each [shortsha] citation into a link to that commit on GitHub."""
    full_by_short = {match["metadata"]["sha"][:7]: match["metadata"]["sha"] for match in matches}

    def replace(match):
        short_sha = match.group(1)
        full_sha = full_by_short.get(short_sha)
        if not full_sha:
            return match.group(0)  # commit we didn't use: leave the text alone
        return f"[{short_sha}](https://github.com/{repo}/commit/{full_sha})"

    return re.sub(r"\[([0-9a-f]{7})\]", replace, answer)


@st.cache_resource
def load_resources():
    """Load the embedding model and the database only once per server run."""
    model = get_model()
    client = chromadb.PersistentClient(path="chroma_db")
    return model, client


def known_repos(client):
    """Map each repo that has a memory to its collection name."""
    repos = {}
    for collection in client.list_collections():
        repo = (collection.metadata or {}).get("repo")
        if repo and collection.name.startswith("commits_"):
            repos[repo] = collection.name
    return repos


def unique_commits(collection):
    """One metadata row per commit (the collection stores several chunks each)."""
    metadatas = collection.get(include=["metadatas"])["metadatas"]
    by_sha = {metadata["sha"]: metadata for metadata in metadatas}
    return sorted(by_sha.values(), key=lambda metadata: metadata["date"])


def timeline_figure(commits, used_shas):
    """One dot per commit on a date axis; used commits are bigger and labelled."""
    used = set(used_shas)
    is_used = [commit["sha"] in used for commit in commits]

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
            textposition="top center",
            textfont={"size": 11, "color": "#e2e8f0"},
            cliponaxis=False,  # keep sha labels visible above the dots
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
def memory_feed(collection):
    """The newest commits in the memory; refreshes every 30 seconds."""
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

    for metadata in recent:
        st.markdown(f"`{metadata['sha'][:7]}` {metadata['message']}")
        st.caption(time_ago(metadata.get("added_at")))


model, client = load_resources()
repos = known_repos(client)

# Sidebar: pick the repo, then show what is stored for it.
with st.sidebar:
    st.header("Memory")
    if not repos:
        st.error("No memory found. Run fetch_commits.py and build_memory.py first.")
        st.stop()

    try:
        # Demo default first, then whatever REPO says, then the first repo found.
        default_repo = PREFERRED_REPO if PREFERRED_REPO in repos else get_repo()
        default_index = sorted(repos).index(default_repo)
    except (SystemExit, ValueError):
        default_index = 0

    repo = st.selectbox("Repo", sorted(repos), index=default_index)
    collection = client.get_collection(repos[repo])
    commits = unique_commits(collection)

    st.write(f"**Commits:** {len(commits)}")
    st.write(f"**Chunks:** {collection.count()}")

    st.divider()
    st.subheader("Memory feed")
    memory_feed(collection)

# A new repo means any answer on screen belongs to the old one.
if st.session_state.get("answer_repo") != repo:
    for key in ("answer", "used", "rewritten", "matches", "answer_repo"):
        st.session_state.pop(key, None)

if commits:
    last_updated = format_ist(commits[-1]["date"])
else:
    last_updated = "never"

st.title("Repo Memory")
st.write("Ask why a codebase changed.")
st.markdown(f"**{repo}** · {len(commits)} commits remembered · last updated {last_updated}")
timeline_slot = st.empty()

question = st.text_input("Question", placeholder="Why did they add hasattr checks?")
ask_clicked = st.button("Ask")

if ask_clicked:
    if not question.strip():
        st.warning("Please type a question first.")
    else:
        with st.spinner("Searching commits and asking the model..."):
            matches, rewritten = retrieve(
                question, model=model, collection=collection, rewrite=True, repo=repo
            )
            answer, matches = answer_question(question, matches, repo=repo)

        st.session_state["answer_repo"] = repo
        st.session_state["answer"] = answer
        st.session_state["used"] = [match["metadata"]["sha"] for match in matches]
        st.session_state["rewritten"] = rewritten
        st.session_state["matches"] = matches

# Draw the timeline after the click, so the used commits can be highlighted.
if commits:
    used_shas = st.session_state.get("used", [])
    timeline_slot.plotly_chart(
        timeline_figure(commits, used_shas), width="stretch", key="timeline"
    )

if st.session_state.get("answer"):
    matches = st.session_state.get("matches", [])
    # Citations like [6f66281] become links to the commits on GitHub.
    st.markdown(linkify(st.session_state["answer"], matches, repo))
    if st.session_state.get("rewritten"):
        st.caption(f"Search query: {st.session_state['rewritten']}")

    # Show the commits the answer is allowed to come from.
    st.subheader("Commits used")
    for match in matches:
        metadata = match["metadata"]
        short_sha = metadata["sha"][:7]
        url = f"https://github.com/{repo}/commit/{metadata['sha']}"
        with st.container(border=True):
            st.markdown(f"**[{short_sha}]({url})** — {format_ist(metadata['date'])}")
            st.caption(metadata["author"])
            st.write(metadata["message"])