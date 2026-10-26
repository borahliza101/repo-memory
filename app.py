"""Streamlit web app for Repo Memory."""

import re

import chromadb
import streamlit as st

from ask import answer_question, get_model, retrieve
from config import collection_name, get_repo

# Page settings must be set before any other Streamlit output.
st.set_page_config(page_title="Repo Memory", page_icon="🧠")


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
    """Find the repos that already have a memory, from the collection metadata."""
    repos = []
    for collection in client.list_collections():
        repo = (collection.metadata or {}).get("repo")
        if repo and collection.name.startswith("commits_"):
            repos.append(repo)
    return sorted(set(repos))


model, client = load_resources()
repos = known_repos(client)

# Sidebar: pick the repo, then show what is stored for it.
with st.sidebar:
    st.header("Memory")
    if not repos:
        st.error("No memory found. Run fetch_commits.py and build_memory.py first.")
        st.stop()

    try:
        default_repo = get_repo()  # REPO from .env, if it has a memory
        default_index = repos.index(default_repo)
    except (SystemExit, ValueError):
        default_index = 0

    repo = st.selectbox("Repo", repos, index=default_index)
    collection = client.get_collection(collection_name(repo))
    metadatas = collection.get(include=["metadatas"])["metadatas"]
    commit_count = len({metadata["sha"] for metadata in metadatas})
    st.write(f"**Commits:** {commit_count}")
    st.write(f"**Chunks:** {collection.count()}")

st.title("Repo Memory")
st.write("Ask why a codebase changed.")

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

        # Citations like [6f66281] become links to the commits on GitHub.
        st.markdown(linkify(answer, matches, repo))
        if rewritten:
            st.caption(f"Search query: {rewritten}")

        # Show the commits the answer is allowed to come from.
        st.subheader("Commits used")
        for match in matches:
            metadata = match["metadata"]
            short_sha = metadata["sha"][:7]
            url = f"https://github.com/{repo}/commit/{metadata['sha']}"
            with st.container(border=True):
                st.markdown(f"**[{short_sha}]({url})** — {metadata['date'][:10]}")
                st.caption(metadata["author"])
                st.write(metadata["message"])