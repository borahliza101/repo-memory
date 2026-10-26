"""Finding the commits that best match a question."""

from .config import get_repo
from .llm import rewrite_query
from .store import get_model, open_collection

CANDIDATES = 20  # chunks to fetch before we pick the best per commit
RESULTS = 5


def retrieve(question, model=None, collection=None, rewrite=False, repo=None, k=RESULTS, rewritten=None):
    """Find the top k unique commits, each with its best matching chunk.

    With rewrite=True the question is also asked in technical terms and both
    searches are merged, keeping each commit's best (smallest) distance.
    Pass rewritten=... to reuse a query the caller already rewrote.
    Returns (matches, rewritten_query), where rewritten_query is None if unused.
    """
    repo = repo or get_repo()
    model = model or get_model()
    collection = collection or open_collection(repo)

    queries = [question]
    if rewritten is None and rewrite:
        rewritten = rewrite_query(question, repo)
    if rewritten:
        queries.append(rewritten)

    # Keep only the best chunk for each commit, so one commit can't fill the list.
    best_per_commit = {}
    for query in queries:
        embedding = model.encode([query]).tolist()
        results = collection.query(
            query_embeddings=embedding,
            n_results=CANDIDATES,
            include=["documents", "metadatas", "distances"],
        )
        for document, metadata, distance in zip(
            results["documents"][0], results["metadatas"][0], results["distances"][0]
        ):
            sha = metadata["sha"]
            if sha not in best_per_commit or distance < best_per_commit[sha]["distance"]:
                best_per_commit[sha] = {
                    "document": document,
                    "metadata": metadata,
                    "distance": distance,
                }

    matches = sorted(best_per_commit.values(), key=lambda item: item["distance"])
    return matches[:k], rewritten