from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from poetry_agent.knowledge import (
    KnowledgeUnavailableError,
    PoetryKnowledgeRepository,
    sha256_path,
)
from poetry_agent.knowledge_builder import (
    KnowledgeBuildError,
    LlmConfig,
    RUNTIME_DIR,
    _build_rules_database,
    _llm_task,
    build_knowledge_base,
    objective_imagery_terms,
    stable_hash,
    validate_llm_result,
)


FIXTURE_POEMS = [
    {
        "title": "静夜思",
        "author": "李白",
        "dynasty": "唐",
        "body": "床前明月光，疑是地上霜。\n举头望明月，低头思故乡。",
        "source_poem_id": "fixture-jingyesi",
        "source_url": "https://example.invalid/jingyesi",
    },
    {
        "title": "江雪",
        "author": "柳宗元",
        "dynasty": "唐",
        "body": "千山鸟飞绝，万径人踪灭。\n孤舟蓑笠翁，独钓寒江雪。",
        "source_poem_id": "fixture-jiangxue",
    },
    {
        "title": "泊船瓜洲",
        "author": "王安石",
        "dynasty": "宋",
        "body": "京口瓜洲一水间，钟山只隔数重山。\n春风又绿江南岸，明月何时照我还。",
        # No source ID: exercises the content-hash fallback ID.
    },
]


class PoetryKnowledgeIntegrationTests(unittest.TestCase):
    """Exercise the real offline compiler and read-only repository together."""

    @classmethod
    def setUpClass(cls) -> None:
        # A failed Windows atomic-publish test may temporarily retain the
        # SQLite handle through its traceback; do not mask that primary error
        # with a second cleanup error.
        cls._temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.root = Path(cls._temporary.name)
        cls.source = cls.root / "tiny-poems.json"
        cls.database = cls.root / "poetry.sqlite3"
        cls.source.write_text(
            json.dumps(FIXTURE_POEMS, ensure_ascii=False), encoding="utf-8"
        )
        cls.build_summary = build_knowledge_base(
            source=cls.source,
            output=cls.database,
            rebuild=True,
        )
        cls.repository = PoetryKnowledgeRepository(cls.database)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_tiny_corpus_builds_with_expected_counts_and_status(self) -> None:
        status = self.repository.status()
        self.assertTrue(status["available"])
        self.assertEqual(3, status["poemCount"])
        self.assertEqual(6, status["lineCount"])
        self.assertEqual(3, self.build_summary["poemCount"])
        self.assertEqual(6, self.build_summary["lineCount"])
        self.assertEqual(self.build_summary["buildId"], status["buildId"])

    def test_objective_imagery_terms_follow_the_live_lexicon(self) -> None:
        terms = objective_imagery_terms()
        words = [term.word for term in terms]

        self.assertGreater(len(terms), 160)
        self.assertEqual(len(words), len(set(words)))
        self.assertIn("玉门关", words)
        self.assertTrue(all(1 <= term.scale <= 5 for term in terms))
        self.assertTrue(all(term.description for term in terms))

    def test_public_builder_atomically_publishes_the_tiny_corpus(self) -> None:
        output = self.root / "public-build.sqlite3"
        manifest = build_knowledge_base(
            source=self.source,
            output=output,
            rebuild=True,
        )
        self.assertTrue(output.is_file())
        self.assertEqual(3, manifest["poemCount"])
        self.assertTrue(output.with_suffix(".manifest.json").is_file())

    def test_source_bodies_hashes_and_manifest_match_published_artifact(self) -> None:
        output = self.root / "integrity.sqlite3"
        manifest = build_knowledge_base(
            source=self.source,
            output=output,
            rebuild=True,
        )
        manifest_path = output.with_suffix(".manifest.json")
        persisted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest, persisted_manifest)
        self.assertEqual(sha256_path(output), manifest["databaseSha256"])
        self.assertEqual(
            sha256_path(self.source), manifest["sourceHashes"][str(self.source)]
        )

        with sqlite3.connect(output) as connection:
            stored = {
                title: (body, body_hash)
                for title, body, body_hash in connection.execute(
                    "SELECT title,body,body_hash FROM poems"
                )
            }
        for record in FIXTURE_POEMS:
            body, body_hash = stored[record["title"]]
            self.assertEqual(record["body"], body)
            self.assertEqual(stable_hash(record["body"]), body_hash)

    def test_manifest_is_required_and_tampering_blocks_every_public_read(self) -> None:
        output = self.root / "tamper.sqlite3"
        build_knowledge_base(source=self.source, output=output, rebuild=True)
        repository = PoetryKnowledgeRepository(output)
        repository.search(query="月", scope="line")

        with sqlite3.connect(output) as connection:
            connection.execute(
                "UPDATE poems SET title='TAMPERED' WHERE poem_id='fixture-jingyesi'"
            )
        for operation in (
            repository.status,
            lambda: repository.search(query="月", scope="line"),
            lambda: repository.get_poem("fixture-jingyesi"),
        ):
            with self.assertRaisesRegex(KnowledgeUnavailableError, "哈希不一致"):
                operation()

        clean = self.root / "missing-manifest.sqlite3"
        build_knowledge_base(source=self.source, output=clean, rebuild=True)
        clean.with_suffix(".manifest.json").unlink()
        with self.assertRaisesRegex(KnowledgeUnavailableError, "manifest 不存在"):
            PoetryKnowledgeRepository(clean).search(query="月", scope="line")

    def test_database_digest_is_cached_until_file_identity_changes(self) -> None:
        output = self.root / "digest-cache.sqlite3"
        build_knowledge_base(source=self.source, output=output, rebuild=True)
        repository = PoetryKnowledgeRepository(output)
        with patch(
            "poetry_agent.knowledge.sha256_path", wraps=sha256_path
        ) as digest:
            repository.status()
            repository.search(query="月", scope="line")
            repository.get_poem("fixture-jingyesi")
        self.assertEqual(1, digest.call_count)

    def test_quick_status_uses_manifest_without_hashing_database(self) -> None:
        with patch(
            "poetry_agent.knowledge.sha256_path",
            side_effect=AssertionError("quick status must not hash the database"),
        ):
            status = self.repository.quick_status()
        self.assertTrue(status["available"])
        self.assertEqual(3, status["poemCount"])

    def test_quick_status_rejects_missing_database(self) -> None:
        missing = self.root / "missing.sqlite3"
        manifest = json.loads(
            self.database.with_suffix(".manifest.json").read_text(encoding="utf-8")
        )
        manifest["database"] = missing.name
        missing.with_suffix(".manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        repository = PoetryKnowledgeRepository(missing)
        with self.assertRaisesRegex(KnowledgeUnavailableError, "知识库文件不存在"):
            repository.quick_status()

    def test_catalog_rows_are_aggregated_without_loading_corpus_json(self) -> None:
        rows, hashes = self.repository.catalog_rows()
        self.assertEqual(
            {"李白", "柳宗元", "王安石"}, {row["poet"] for row in rows}
        )
        self.assertTrue(all(row["workCount"] == 1 for row in rows))
        by_poet = {row["poet"]: row for row in rows}
        self.assertEqual("唐", by_poet["李白"]["dynasty"])
        self.assertEqual("宋", by_poet["王安石"]["dynasty"])
        self.assertEqual(self.build_summary["sourceHashes"], hashes)

    def test_declared_source_body_hash_must_match_exact_body(self) -> None:
        source = self.root / "bad-body-hash.json"
        record = {**FIXTURE_POEMS[0], "body_hash": "0" * 64}
        source.write_text(
            json.dumps([record], ensure_ascii=False), encoding="utf-8"
        )
        with self.assertRaisesRegex(KnowledgeBuildError, "正文哈希不匹配"):
            build_knowledge_base(
                source=source,
                output=self.root / "bad-body-hash.sqlite3",
                rebuild=True,
            )

    def test_second_builder_is_rejected_while_destination_lock_is_held(self) -> None:
        output = self.root / "locked-build.sqlite3"
        lock_path = RUNTIME_DIR / (
            "knowledge-build-" + stable_hash(output.resolve(), length=24) + ".lock"
        )
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("w+b")
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(KnowledgeBuildError, "已有知识库构建正在运行"):
                build_knowledge_base(
                    source=self.source,
                    output=output,
                    rebuild=True,
                )
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def test_poem_and_line_ids_are_stable_across_fresh_builds(self) -> None:
        second_database = self.root / "second.sqlite3"
        _build_rules_database(
            self.source,
            second_database,
            poet=None,
            limit=None,
        )

        def identifiers(path: Path) -> tuple[list[str], list[str]]:
            with sqlite3.connect(path) as connection:
                poem_ids = [row[0] for row in connection.execute(
                    "SELECT poem_id FROM poems ORDER BY poem_id"
                )]
                line_ids = [row[0] for row in connection.execute(
                    "SELECT line_id FROM lines ORDER BY poem_id,line_no"
                )]
            return poem_ids, line_ids

        first_ids = identifiers(self.database)
        self.assertEqual(first_ids, identifiers(second_database))
        self.assertIn("fixture-jingyesi", first_ids[0])
        fallback = next(value for value in first_ids[0] if value.startswith("local-"))
        self.assertEqual(30, len(fallback))
        self.assertTrue(all(":l0000" in value for value in first_ids[1]))

    def test_line_offsets_reproduce_exact_source_substrings(self) -> None:
        for source_record in FIXTURE_POEMS:
            poem_id = (
                source_record.get("source_poem_id")
                or next(
                    row["poemId"]
                    for row in self.repository.search(
                        query=source_record["title"], scope="poem", limit=10
                    )["items"]
                    if row["title"] == source_record["title"]
                )
            )
            detail = self.repository.get_poem(str(poem_id))
            self.assertIsNotNone(detail)
            assert detail is not None
            body = source_record["body"]
            for line in detail["lines"]:
                self.assertEqual(
                    line["text"], body[line["startOffset"] : line["endOffset"]]
                )
                self.assertTrue(line["text"].endswith("。"))

    def test_one_and_two_character_queries_use_literal_like_search(self) -> None:
        one = self.repository.search(query="月", scope="line", limit=20)
        self.assertEqual(3, one["total"])
        self.assertTrue(all("月" in item["text"] for item in one["items"]))

        two = self.repository.search(query="孤舟", scope="line", limit=20)
        self.assertEqual(1, two["total"])
        self.assertIn("孤舟", two["items"][0]["text"])

    def test_three_or_more_character_queries_use_fts(self) -> None:
        line_result = self.repository.search(
            query="春风又绿", scope="line", limit=20
        )
        self.assertEqual(1, line_result["total"])
        self.assertIn("春风又绿", line_result["items"][0]["text"])

        poem_result = self.repository.search(
            query="低头思故乡", scope="poem", limit=20
        )
        self.assertEqual(1, poem_result["total"])
        self.assertEqual("静夜思", poem_result["items"][0]["title"])

    def test_composed_poet_dynasty_imagery_and_emotion_filters(self) -> None:
        imagery = self.repository.search(
            query="",
            poet="柳宗元",
            dynasty="唐",
            imagery="孤舟",
            scope="poem",
            limit=20,
        )
        self.assertEqual(1, imagery["total"])
        self.assertEqual("江雪", imagery["items"][0]["title"])

        emotion = self.repository.search(
            query="孤舟",
            poet="柳宗元",
            dynasty="唐",
            imagery="孤舟",
            emotion="孤寂清冷",
            scope="line",
            limit=20,
        )
        self.assertEqual(1, emotion["total"])
        self.assertIn("孤舟", emotion["items"][0]["text"])

        mismatch = self.repository.search(
            query="", poet="柳宗元", dynasty="宋", scope="all", limit=20
        )
        self.assertEqual(0, mismatch["total"])

    def test_poem_and_line_details_include_provenance_and_rule_results(self) -> None:
        poem = self.repository.get_poem("fixture-jiangxue")
        self.assertIsNotNone(poem)
        assert poem is not None
        self.assertEqual("江雪", poem["title"])
        self.assertEqual(2, len(poem["lines"]))
        self.assertTrue(poem["analyses"])
        self.assertTrue(poem["imagery"])
        self.assertIn("孤舟", {item["label"] for item in poem["imagery"]})

        target = poem["lines"][1]
        line = self.repository.get_line(target["lineId"])
        self.assertIsNotNone(line)
        assert line is not None
        self.assertEqual(target["text"], line["text"])
        self.assertEqual("fixture-jiangxue", line["poemId"])
        self.assertTrue(line["analyses"])
        self.assertTrue(line["imagery"])
        self.assertTrue(line["emotions"])
        self.assertTrue(all(row["method"] == "rules" for row in line["analyses"]))

    def test_malicious_queries_are_literal_and_do_not_change_database(self) -> None:
        before = self.repository.status()
        values = (
            "' OR 1=1 --",
            '" OR poem_fts MATCH "*',
            "%_",
            "明月' UNION SELECT * FROM poems --",
        )
        for value in values:
            with self.subTest(value=value):
                result = self.repository.search(query=value, scope="all", limit=20)
                self.assertEqual(0, result["total"])
        after = self.repository.status()
        self.assertEqual(before["poemCount"], after["poemCount"])
        self.assertEqual(before["lineCount"], after["lineCount"])

    def test_parallel_searches_use_independent_read_only_connections(self) -> None:
        cases = [
            ("月", "line", 3),
            ("孤舟", "line", 1),
            ("春风又绿", "line", 1),
            ("低头思故乡", "poem", 1),
            ("江雪", "poem", 1),
        ] * 12

        def run(case: tuple[str, str, int]) -> tuple[int, str]:
            query, scope, _ = case
            result = self.repository.search(query=query, scope=scope, limit=20)
            return result["total"], result["schemaVersion"]

        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(run, cases))
        self.assertEqual(
            [(expected, "1.0") for _, _, expected in cases], results
        )


class LlmResultValidationTests(unittest.TestCase):
    expected_lines = {
        "line-a": "床前明月光，低头思故乡。",
        "line-b": "孤舟蓑笠翁，独钓寒江雪。",
    }

    @classmethod
    def valid_result(cls) -> dict[str, object]:
        return {
            "lines": [
                {
                    "lineId": "line-a",
                    "interpretation": "月光引出对故乡的思念。",
                    "imagery": [{"label": "明月", "evidence": "明月"}],
                    "emotions": [{"label": "思乡", "evidence": "思故乡"}],
                    "confidence": 0.88,
                },
                {
                    "lineId": "line-b",
                    "interpretation": "孤舟与寒江共同形成清冷画面。",
                    "imagery": ["孤舟"],
                    "emotions": [{"label": "孤寂", "evidence": "独钓"}],
                    "confidence": "0.79",
                },
            ]
        }

    def test_validate_llm_result_accepts_complete_evidence_bound_json(self) -> None:
        validated = validate_llm_result(self.valid_result(), self.expected_lines)
        self.assertEqual(["line-a", "line-b"], [row["lineId"] for row in validated])
        self.assertEqual(0.88, validated[0]["confidence"])
        self.assertEqual(0.79, validated[1]["confidence"])
        self.assertEqual(
            [{"label": "孤舟", "evidence": "孤舟"}], validated[1]["imagery"]
        )

    def test_validate_llm_result_rejects_bad_json_shapes(self) -> None:
        invalid_results = (
            {},
            {"lines": "not-an-array"},
            {"lines": ["not-an-object"]},
            {
                "lines": [
                    {
                        "lineId": "line-a",
                        "interpretation": "释义",
                        "imagery": {"label": "明月", "evidence": "明月"},
                    }
                ]
            },
        )
        for result in invalid_results:
            with self.subTest(result=result), self.assertRaises(KnowledgeBuildError):
                validate_llm_result(result, self.expected_lines)

    def test_validate_llm_result_rejects_unknown_line_id(self) -> None:
        result = self.valid_result()
        result["lines"][0]["lineId"] = "invented-line"
        with self.assertRaisesRegex(KnowledgeBuildError, "未知或重复 lineId"):
            validate_llm_result(result, self.expected_lines)

    def test_validate_llm_result_rejects_fabricated_evidence(self) -> None:
        result = self.valid_result()
        result["lines"][0]["imagery"][0]["evidence"] = "原句中不存在的词"
        with self.assertRaisesRegex(KnowledgeBuildError, "evidence 不是原句子串"):
            validate_llm_result(result, self.expected_lines)

    def test_validate_llm_result_rejects_missing_line(self) -> None:
        result = self.valid_result()
        result["lines"] = result["lines"][:1]
        with self.assertRaisesRegex(KnowledgeBuildError, "未覆盖本批全部 lineId"):
            validate_llm_result(result, self.expected_lines)

    def test_llm_task_uses_mocked_response_without_network(self) -> None:
        result = self.valid_result()
        config = LlmConfig(
            base_url="https://never-requested.invalid/v1",
            api_key="not-a-real-key",
            model="mock-model",
            concurrency=1,
        )
        poem = {
            "dynasty": "唐",
            "poet": "测试诗人",
            "title": "测试诗",
        }
        lines = [
            {"line_id": line_id, "text": text}
            for line_id, text in self.expected_lines.items()
        ]
        with patch(
            "poetry_agent.knowledge_builder._request_llm", return_value=result
        ) as request_mock:
            rows, prompt_hash, input_hash = _llm_task(
                config, poem=poem, lines=lines
            )
        request_mock.assert_called_once()
        self.assertEqual(2, len(rows))
        self.assertEqual(64, len(prompt_hash))
        self.assertEqual(64, len(input_hash))


if __name__ == "__main__":
    unittest.main()
