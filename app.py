"""Streamlit web app for Repo Memory."""

import streamlit as st

from ask import answer_question, get_collection, get_model, retrieve

REPO = "psf/requests"

# Page settings must be set before any other Streamlit output.
st.set_page_config(page_title="Repo Memory", page_icon="🧠")


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
            matches = retrieve(question, model=model, collection=collection)
            answer, matches = answer_question(question, matches)

        st.markdown(answer)

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