"""Unit tests for the pure parts of Repo Memory. No network, no real model."""

import unittest

from repo_memory import chunking, decisions, llm, retrieval, watcher
from repo_memory.config import collection_name, commits_path, decisions_path, get_repo, parse_repo_input


class ConfigTests(unittest.TestCase):
    def test_parse_repo_input(self):
        cases = {
            "https://github.com/owner/name": "owner/name",
            "http://github.com/owner/name/": "owner/name",
            "github.com/owner/name": "owner/name",
            "owner/name": "owner/name",
            "https://github.com/owner/name.git": "owner/name",
            "": None,
            "not a repo": None,
            "a/b/c": None,
        }
        for text, expected in cases.items():
            self.assertEqual(parse_repo_input(text), expected, text)

    def test_names_and_paths(self):
        repo = "borahliza101/repo-memory"
        self.assertEqual(collection_name(repo), "commits_borahliza101_repo-memory")
        self.assertTrue(commits_path(repo).endswith("commits_borahliza101_repo-memory.json"))
        self.assertTrue(decisions_path(repo).endswith("borahliza101_repo-memory.md"))

    def test_get_repo_validation(self):
        self.assertEqual(get_repo("owner/name"), "owner/name")
        with self.assertRaises(SystemExit):
            get_repo("owner-only")


class ChunkingTests(unittest.TestCase):
    def commit(self, sha="a" * 40, message="Fix a thing", files=None, author="Dev"):
        return {
            "sha": sha,
            "message": message,
            "author": author,
            "date": "2026-01-01T00:00:00Z",
            "files": files if files is not None else [{"filename": "x.py", "patch": "+code"}],
        }

    def test_short_text_is_one_chunk(self):
        self.assertEqual(chunking.split_text("hello"), ["hello"])

    def test_long_text_has_overlap(self):
        text = "x" * 5000
        chunks = chunking.split_text(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= chunking.CHUNK_SIZE for chunk in chunks))
        self.assertEqual(chunks[0][-chunking.CHUNK_OVERLAP:], chunks[1][: chunking.CHUNK_OVERLAP])

    def test_build_entries_summary_first_then_code(self):
        ids, documents, metadatas, skipped = chunking.build_entries([self.commit()])
        self.assertEqual(ids[0], "a" * 40 + "-summary")
        self.assertTrue(ids[1].endswith("-0"))
        self.assertIn("Files changed: x.py", documents[0])
        self.assertIn("Changes:", documents[1])
        self.assertEqual(skipped, 0)
        self.assertIn("added_at", metadatas[0])

    def test_empty_commit_has_only_summary(self):
        ids, documents, _, _ = chunking.build_entries([self.commit(files=[])])
        self.assertEqual(len(ids), 1)
        self.assertTrue(ids[0].endswith("-summary"))

    def test_bots_are_skipped_but_humans_mentioning_dependabot_are_kept(self):
        bot = self.commit(sha="b" * 40, author="dependabot[bot]")
        merge = self.commit(
            sha="c" * 40,
            author="Dev",
            message="Merge pull request #1 from acme/dependabot/npm_and_yarn/x",
        )
        human = self.commit(sha="d" * 40, author="Dev", message="Tweak dependabot config")
        ids, _, _, skipped = chunking.build_entries([bot, merge, human])
        self.assertEqual(skipped, 2)
        self.assertEqual({chunk_id.split("-")[0] for chunk_id in ids}, {"d" * 40})


class LLMTests(unittest.TestCase):
    def test_normalize_citations(self):
        self.assertEqual(
            llm.normalize_citations("Fixed in [ f140c94 ] and 【f780219】."),
            "Fixed in [f140c94] and [f780219].",
        )

    def test_normalize_stream_handles_split_brackets(self):
        chunks = ["Because ", "【6f66", "281】 and ", "【", "25340eb", "】."]
        self.assertEqual("".join(llm.normalize_stream(iter(chunks))), "Because [6f66281] and [25340eb].")

    def test_stream_without_matches_refuses(self):
        self.assertEqual("".join(llm.stream_answer("q", [])), "I couldn't find this in the history")


class RetrievalTests(unittest.TestCase):
    def test_merges_queries_and_keeps_best_per_commit(self):
        class Vec(list):
            def tolist(self):
                return list(self)

        class Batch(list):
            """Mimics the array the real encode() returns."""

            def tolist(self):
                return [list(vector) for vector in self]

        class FakeModel:
            def encode(self, texts):
                # The rewritten query is flagged so the fake collection can vary.
                return Batch([Vec([1.0 if "technical" in texts[0] else 0.0])])

        class FakeCollection:
            def query(self, query_embeddings, n_results, include):
                # The rewritten query ranks "b" better than the original does.
                if query_embeddings[0][0] == 1.0:
                    rows = [("b", 0.1), ("a", 0.5)]
                else:
                    rows = [("a", 0.2), ("b", 0.9)]
                return {
                    "documents": [[f"doc-{sha}" for sha, _ in rows]],
                    "metadatas": [[{"sha": sha, "date": "2026-01-01", "message": sha} for sha, _ in rows]],
                    "distances": [[distance for _, distance in rows]],
                }

        matches, rewritten = retrieval.retrieve(
            "question",
            model=FakeModel(),
            collection=FakeCollection(),
            repo="owner/name",
            rewritten="technical rewrite",
            k=2,
        )
        # Best distance per commit across both searches: b 0.1, a 0.2.
        self.assertEqual([m["metadata"]["sha"] for m in matches], ["b", "a"])
        self.assertAlmostEqual(matches[0]["distance"], 0.1)
        self.assertEqual(rewritten, "technical rewrite")


class DecisionTests(unittest.TestCase):
    def test_parse_decision(self):
        parsed = decisions.parse_decision("- abc1234 | 2026-05-01 | Use hasattr | proxy objects need it")
        self.assertEqual(parsed["sha"], "abc1234")
        self.assertEqual(parsed["title"], "Use hasattr")
        self.assertIsNone(decisions.parse_decision("not a decision"))
        self.assertIsNone(decisions.parse_decision("abc1234 | 2026-05-01 | only three parts"))

    def test_adds_detail(self):
        self.assertFalse(decisions.adds_detail("add hasattr checks", "Add hasattr checks (#1)"))
        self.assertTrue(decisions.adds_detail("proxy objects need it", "Add hasattr checks"))

    def test_render_groups_by_month_newest_first(self):
        rows = [
            {"sha": "aaaaaaa", "date": "2026-04-02", "sort": "2026-04-02", "title": "April one", "why": "w"},
            {"sha": "bbbbbbb", "date": "2026-05-03", "sort": "2026-05-03", "title": "May one", "why": "w"},
        ]
        text = decisions.render_log("owner/name", rows, 2)
        self.assertIn("Auto-generated by Repo Memory from 2 commits", text)
        self.assertLess(text.index("## May 2026"), text.index("## April 2026"))
        self.assertIn("[aaaaaaa]", text)


class WatcherTests(unittest.TestCase):
    def test_is_bot(self):
        self.assertTrue(watcher.is_bot({"author": {"login": "dependabot[bot]"}}))
        self.assertTrue(
            watcher.is_bot(
                {"author": {"login": "dev"}, "commit": {"message": "Merge pull request #1 from x/dependabot/y"}}
            )
        )
        self.assertFalse(
            watcher.is_bot({"author": {"login": "dev"}, "commit": {"message": "Update dependabot.yml"}})
        )


if __name__ == "__main__":
    unittest.main()