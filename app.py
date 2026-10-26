"""Streamlit web app for Repo Memory."""

import re

import streamlit as st

from ask import answer_question, get_collection, get_model, retrieve

REPO = "psf/requests"

# Page settings must be set before any other Streamlit output.
st.set_page_config(page_title="Repo Memory", page_icon="🧠")


def linkify(answer, matches):
    """Turn each [shortsha] citation into a link to that commit on GitHub."""
    full_by_short = {match["metadata"]["sha"][:7]: match["metadata"]["sha"] for match in matches}

    def replace(match):
        short_sha = match.group(1)
        full_sha = full_by_short.get(short_sha)
        if not full_sha:
            return match.group(0)  # commit we didn't use: leave the text alone
        return f"[{short_sha}](https://github.com/{REPO}/commit/{full_sha})"

    return re.sub(r"\[([0-9a-f]{7})\]", replace, answer)


@st.cache_resource
def load_resources():
    """Load the embedding model and the database only once per server run."""
    model = get_model()
    collection = get_collection()
    # Count unique commits (each commit has several chunks in the collection).
    metadatas = collection.get(include=["metadatas"])["metadatas"]
    commit_count = len({metadata["sha"] for metadata in metadatas})
    return model, collection, commit_count


model, collection, commit_count = load_resources()

# Sidebar: what is stored in the memory right now.
with st.sidebar:
    st.header("Memory")
    st.write(f"**Repo:** {REPO}")
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
                question, model=model, collection=collection, rewrite=True
            )
            answer, matches = answer_question(question, matches)

        # Citations like [6f66281] become links to the commits on GitHub.
        st.markdown(linkify(answer, matches))
        if rewritten:
            st.caption(f"Search query: {rewritten}")

        # Show the commits the answer is allowed to come from.
        st.subheader("Commits used")
        for match in matches:
            metadata = match["metadata"]
            short_sha = metadata["sha"][:7]
            url = f"https://github.com/{REPO}/commit/{metadata['sha']}"
            with st.container(border=True):
                st.markdown(f"**[{short_sha}]({url})** — {metadata['date'][:10]}")
                st.caption(metadata["author"])
                st.write(metadata["message"])