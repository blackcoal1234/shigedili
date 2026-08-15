from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from poetry_agent.knowledge import PoetryKnowledgeRepository
from poetry_agent.knowledge_builder import build_knowledge_base


POEM = {
    "title": "测试明月",
    "author": "测试诗人",
    "dynasty": "唐",
    "body": "床前明月光，低头思故乡。\n孤舟蓑笠翁，独钓寒江雪。",
    "source_poem_id": "llm-persistence-fixture",
}


def valid_model_result(prompt: str) -> dict[str, object]:
    """Build a response for the exact line IDs embedded in the user prompt."""

    first_id, second_id = _prompt_line_ids(prompt)
    return {
        "lines": [
            {
                "lineId": first_id,
                "interpretation": "模型特有词玄素以明月触发思乡。",
                "imagery": [{"label": "月色", "evidence": "明月"}],
                "emotions": [{"label": "乡思", "evidence": "思故乡"}],
                "confidence": 0.91,
            },
            {
                "lineId": second_id,
                "interpretation": "模型特有词清峦以孤舟与寒江构成冷寂画面。",
                "imagery": [{"label": "孤舟", "evidence": "孤舟"}],
                "emotions": [{"label": "孤清", "evidence": "独钓"}],
                "confidence": 0.87,
            },
        ]
    }


def _prompt_line_ids(prompt: str) -> list[str]:
    marker = "待分析行：\n"
    payload = json.loads(prompt.split(marker, 1)[1])
    return [str(row["lineId"]) for row in payload]


class LlmPersistenceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temporary.name)
        self.source = self.root / "poems.json"
        self.output = self.root / "knowledge.sqlite3"
        self.source.write_text(
            json.dumps([POEM], ensure_ascii=False), encoding="utf-8"
        )
        self.environment = patch.dict(
            "os.environ",
            {
                "AGENT_LLM_BASE_URL": "https://never-requested.invalid/v1",
                "AGENT_LLM_API_KEY": "unit-test-secret",
                "AGENT_LLM_MODEL": "mock-poetry-model",
            },
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    def test_public_build_persists_candidates_refreshes_fts_and_resumes(self) -> None:
        def response(_config, prompt: str) -> dict[str, object]:
            return valid_model_result(prompt)

        with patch(
            "poetry_agent.knowledge_builder._request_llm", side_effect=response
        ) as request_mock:
            first_manifest = build_knowledge_base(
                source=self.source,
                output=self.output,
                rebuild=True,
                use_llm=True,
                concurrency=2,
            )

        self.assertEqual(1, request_mock.call_count)
        self.assertEqual("completed", first_manifest["analysis"]["llm"])
        self.assertEqual("completed", first_manifest["llmRun"]["status"])
        self.assertEqual(1, first_manifest["llmRun"]["completedJobs"])
        self.assertEqual(0, first_manifest["llmRun"]["failedJobs"])

        with closing(sqlite3.connect(self.output)) as connection:
            connection.row_factory = sqlite3.Row
            llm_analyses = connection.execute(
                "SELECT * FROM analyses WHERE method='llm' ORDER BY line_id"
            ).fetchall()
            llm_imagery = connection.execute(
                "SELECT * FROM imagery_mentions WHERE method='llm' ORDER BY line_id"
            ).fetchall()
            llm_emotions = connection.execute(
                "SELECT * FROM emotion_mentions WHERE method='llm' ORDER BY line_id"
            ).fetchall()
            job = connection.execute("SELECT * FROM analysis_jobs").fetchone()
            run = connection.execute(
                "SELECT * FROM analysis_runs WHERE method='llm'"
            ).fetchone()
            fts_lines = connection.execute(
                "SELECT line_id,analysis_text FROM line_fts ORDER BY line_id"
            ).fetchall()
            fts_poem = connection.execute(
                "SELECT analysis_text FROM poem_fts WHERE poem_id=?",
                (POEM["source_poem_id"],),
            ).fetchone()

        self.assertEqual(2, len(llm_analyses))
        self.assertTrue(all(row["kind"] == "line_interpretation" for row in llm_analyses))
        self.assertTrue(all(row["model"] == "mock-poetry-model" for row in llm_analyses))
        with closing(sqlite3.connect(self.output)) as inspection:
            review_statuses = {
                row[0]
                for row in inspection.execute(
                    "SELECT DISTINCT review_status FROM analyses"
                )
            }
        self.assertEqual({"published_rules", "candidate"}, review_statuses)
        self.assertEqual(2, len(llm_imagery))
        self.assertEqual({"月色", "孤舟"}, {row["label"] for row in llm_imagery})
        self.assertTrue(all(row["target_scope"] == "line" for row in llm_imagery))
        self.assertEqual(2, len(llm_emotions))
        self.assertEqual({"乡思", "孤清"}, {row["label"] for row in llm_emotions})
        self.assertEqual("completed", job["status"])
        self.assertEqual(1, job["attempts"])
        self.assertIsNotNone(job["result_json"])
        self.assertEqual("completed", run["status"])
        self.assertTrue(any("模型特有词玄素" in row["analysis_text"] for row in fts_lines))
        self.assertIn("模型特有词清峦", fts_poem["analysis_text"])

        repository = PoetryKnowledgeRepository(self.output)
        fts_result = repository.search(
            query="模型特有词玄素", scope="line", limit=10
        )
        self.assertEqual(1, fts_result["total"])
        self.assertIn("llm", fts_result["items"][0]["analysisMethods"])

        with patch(
            "poetry_agent.knowledge_builder._request_llm",
            side_effect=AssertionError("已完成任务不应再请求模型"),
        ) as resume_mock:
            second_manifest = build_knowledge_base(
                source=self.source,
                output=self.output,
                rebuild=False,
                use_llm=True,
                concurrency=2,
            )

        resume_mock.assert_not_called()
        self.assertEqual("completed", second_manifest["llmRun"]["status"])
        self.assertEqual(0, second_manifest["llmRun"]["completedJobs"])
        self.assertEqual(0, second_manifest["llmRun"]["failedJobs"])
        with closing(sqlite3.connect(self.output)) as connection:
            self.assertEqual(
                1,
                connection.execute(
                    "SELECT attempts FROM analysis_jobs"
                ).fetchone()[0],
            )
            self.assertEqual(
                2,
                connection.execute(
                    "SELECT COUNT(*) FROM analyses WHERE method='llm'"
                ).fetchone()[0],
            )

    def test_semantically_invalid_result_is_failed_partial_and_atomic(self) -> None:
        def bad_response(_config, prompt: str) -> dict[str, object]:
            first_id, second_id = _prompt_line_ids(prompt)
            return {
                "lines": [
                    {
                        "lineId": first_id,
                        "interpretation": "这一条本身合法，但整个任务必须原子失败。",
                        "imagery": [{"label": "月色", "evidence": "明月"}],
                        "emotions": [{"label": "乡思", "evidence": "思故乡"}],
                        "confidence": 0.9,
                    },
                    {
                        "lineId": second_id,
                        "interpretation": "伪造了不在原文中的证据。",
                        "imagery": [{"label": "伪意象", "evidence": "原句并无此词"}],
                        "emotions": [],
                        "confidence": 0.9,
                    },
                ]
            }

        with (
            patch(
                "poetry_agent.knowledge_builder._request_llm",
                side_effect=bad_response,
            ) as request_mock,
            patch("poetry_agent.knowledge_builder.time.sleep") as sleep_mock,
        ):
            manifest = build_knowledge_base(
                source=self.source,
                output=self.output,
                rebuild=True,
                use_llm=True,
                concurrency=1,
            )

        self.assertEqual(5, request_mock.call_count)
        self.assertEqual(4, sleep_mock.call_count)
        self.assertEqual("partial", manifest["analysis"]["llm"])
        self.assertEqual("partial", manifest["llmRun"]["status"])
        self.assertEqual(0, manifest["llmRun"]["completedJobs"])
        self.assertEqual(1, manifest["llmRun"]["failedJobs"])

        with closing(sqlite3.connect(self.output)) as connection:
            connection.row_factory = sqlite3.Row
            job = connection.execute("SELECT * FROM analysis_jobs").fetchone()
            run = connection.execute(
                "SELECT * FROM analysis_runs WHERE method='llm'"
            ).fetchone()
            llm_analysis_count = connection.execute(
                "SELECT COUNT(*) FROM analyses WHERE method='llm'"
            ).fetchone()[0]
            llm_imagery_count = connection.execute(
                "SELECT COUNT(*) FROM imagery_mentions WHERE method='llm'"
            ).fetchone()[0]
            llm_emotion_count = connection.execute(
                "SELECT COUNT(*) FROM emotion_mentions WHERE method='llm'"
            ).fetchone()[0]
            fts_has_bad_text = connection.execute(
                "SELECT COUNT(*) FROM line_fts WHERE analysis_text LIKE '%这一条本身合法%'"
            ).fetchone()[0]

        self.assertEqual("failed", job["status"])
        self.assertEqual(1, job["attempts"])
        self.assertIn("evidence 不是原句子串", job["error"])
        self.assertIsNone(job["result_json"])
        self.assertEqual("partial", run["status"])
        self.assertEqual(0, llm_analysis_count)
        self.assertEqual(0, llm_imagery_count)
        self.assertEqual(0, llm_emotion_count)
        self.assertEqual(0, fts_has_bad_text)


if __name__ == "__main__":
    unittest.main()
