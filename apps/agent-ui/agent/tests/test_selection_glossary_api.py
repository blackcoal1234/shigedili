from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from poetry_agent.cache import sha256_source_file
from poetry_agent.config import Settings, discover_project_root
from poetry_agent.knowledge import init_schema, manifest_path_for, sha256_path
from poetry_agent.main import create_app
from poetry_agent.selection_glossary import GlossaryQuota


class FakeGlossaryModelClient:
    model = "fake-glossary-model"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def explain(self, *, context: dict, mode: str) -> dict:
        self.calls.append({"context": context, "mode": mode})
        result = {
            "definition": "门的前面。",
            "inContext": "指诗中主人公居所门前。",
            "category": "方位短语",
            "sourceNote": "测试模型生成，待审核。",
        }
        if mode == "web":
            result["sources"] = [
                {"title": "示例来源", "url": "https://example.com/gloss"}
            ]
        return result


class SelectionGlossaryApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.temp_root = Path(cls.temporary.name)
        cls.project_root = discover_project_root()
        cls.database = cls.temp_root / "tiny-knowledge.sqlite3"
        cls.draft_path = cls.temp_root / "glossary-drafts.json"
        cls._build_tiny_knowledge_database()
        cls.model = FakeGlossaryModelClient()
        cls.settings = Settings(
            project_root=cls.project_root,
            cache_dir=cls.temp_root / "cache",
            llm_base_url="https://secret-provider.invalid/v1",
            llm_api_key="test-secret-api-key",
            llm_model="fake-glossary-model",
            allowed_origins=(),
            knowledge_base_path=cls.database,
        )
        cls.app = create_app(
            cls.settings,
            glossary_model_client=cls.model,
            glossary_draft_path=cls.draft_path,
        )
        cls.client = TestClient(cls.app)
        cls.poem_id = "2d0368e3fb76"

    @classmethod
    def _build_tiny_knowledge_database(cls) -> None:
        source_paths = (
            "data/poems.json",
            "data/spirit_image_dict.py",
            "data/image_dict.py",
            "data/classical_emotion_model.py",
            "data/classical_emotion_lexicon.py",
            "apps/agent-ui/agent/poetry_agent/knowledge.py",
            "apps/agent-ui/agent/poetry_agent/knowledge_builder.py",
        )
        source_hashes = {
            relative: sha256_source_file(cls.project_root / relative)
            for relative in source_paths
            if (cls.project_root / relative).is_file()
        }
        body = "妾发初覆额，折花门前剧。\n门前迟行迹。"
        lines = ("妾发初覆额，折花门前剧。", "门前迟行迹。")
        build_id = "selection-glossary-api-fixture"
        filters = {"fixture": "selection-glossary-api"}
        with sqlite3.connect(cls.database) as connection:
            init_schema(connection)
            connection.execute(
                "INSERT INTO poems(poem_id,source_poem_id,title,poet,dynasty,body,body_hash) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    "2d0368e3fb76",
                    "2d0368e3fb76",
                    "长干行·其一",
                    "李白",
                    "唐",
                    body,
                    hashlib.sha256(body.encode()).hexdigest(),
                ),
            )
            for line_no, text in enumerate(lines, 1):
                connection.execute(
                    "INSERT INTO lines(line_id,poem_id,line_no,stanza_no,text,"
                    "start_offset,end_offset,line_hash) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        f"fixture-line-{line_no}",
                        "2d0368e3fb76",
                        line_no,
                        1,
                        text,
                        0,
                        len(text),
                        hashlib.sha256(text.encode()).hexdigest(),
                    ),
                )
            connection.executemany(
                "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                (
                    ("build_id", build_id),
                    ("source_hashes", json.dumps(source_hashes, sort_keys=True)),
                    ("build_filters", json.dumps(filters, sort_keys=True)),
                ),
            )
            connection.commit()
        manifest_path_for(cls.database).write_text(
            json.dumps(
                {
                    "schemaVersion": "1.0",
                    "database": cls.database.name,
                    "databaseSha256": sha256_path(cls.database),
                    "buildId": build_id,
                    "sourceHashes": source_hashes,
                    "filters": filters,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        cls.temporary.cleanup()

    def post_selection(self, **overrides):
        payload = {
            "poemId": self.poem_id,
            "lineNo": 1,
            "startOffset": 2,
            "endOffset": 5,
            "mode": "model",
        }
        payload.update(overrides)
        return self.client.post("/knowledge/glosses/selection", json=payload)

    def test_camel_case_local_gloss_short_circuits_model(self) -> None:
        call_count = len(self.model.calls)
        response = self.post_selection()

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("ok", body["status"])
        self.assertEqual("初覆额", body["payload"]["term"])
        self.assertEqual("local", body["payload"]["method"])
        self.assertEqual("published", body["payload"]["reviewStatus"])
        self.assertEqual(call_count, len(self.model.calls))
        self.assertFalse(self.draft_path.exists())

    def test_model_and_web_results_are_saved_as_drafts(self) -> None:
        model_response = self.post_selection(
            lineNo=2, startOffset=0, endOffset=2, mode="model"
        )
        self.assertEqual(200, model_response.status_code)
        model_body = model_response.json()
        self.assertEqual("ok", model_body["status"])
        self.assertEqual("llm", model_body["payload"]["method"])
        self.assertEqual("draft", model_body["payload"]["reviewStatus"])
        self.assertTrue(model_body["payload"]["draftId"])
        self.assertTrue(self.draft_path.is_file())

        web_response = self.post_selection(
            lineNo=2, startOffset=0, endOffset=2, mode="web"
        )
        self.assertEqual(200, web_response.status_code)
        web_body = web_response.json()
        self.assertEqual("ok", web_body["status"])
        self.assertEqual("llm_web", web_body["payload"]["method"])
        self.assertEqual(
            [{"title": "示例来源", "url": "https://example.com/gloss"}],
            web_body["payload"]["sources"],
        )
        stored = json.loads(self.draft_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(stored["drafts"]), 2)

    def test_out_of_line_offset_is_business_invalid_request(self) -> None:
        response = self.post_selection(startOffset=10, endOffset=13)

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("invalid_request", body["status"])
        self.assertTrue(body["payload"]["sourceNote"])

    def test_schema_rejects_long_span_and_extra_fields(self) -> None:
        cases = (
            {
                "poemId": self.poem_id,
                "lineNo": 1,
                "startOffset": 0,
                "endOffset": 33,
                "mode": "model",
            },
            {
                "poemId": self.poem_id,
                "lineNo": 1,
                "startOffset": 2,
                "endOffset": 5,
                "mode": "model",
                "selectedText": "初覆额",
            },
        )
        for payload in cases:
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/knowledge/glosses/selection", json=payload
                )
                self.assertEqual(422, response.status_code)
                self.assertEqual("invalid_request", response.json()["status"])

    def test_missing_model_is_source_error_and_status_hides_credentials(self) -> None:
        no_model_settings = Settings(
            project_root=self.project_root,
            cache_dir=self.temp_root / "no-model-cache",
            llm_base_url="",
            llm_api_key="",
            llm_model="",
            allowed_origins=(),
            knowledge_base_path=self.database,
        )
        no_model_app = create_app(
            no_model_settings,
            glossary_model_client=None,
            glossary_draft_path=self.temp_root / "no-model-drafts.json",
        )
        with TestClient(no_model_app) as client:
            response = client.post(
                "/knowledge/glosses/selection",
                json={
                    "poemId": self.poem_id,
                    "lineNo": 2,
                    "startOffset": 0,
                    "endOffset": 2,
                    "mode": "model",
                },
            )
            self.assertEqual(200, response.status_code)
            self.assertEqual("source_error", response.json()["status"])

        status_response = self.client.get("/knowledge/glosses/status")
        self.assertEqual(200, status_response.status_code)
        serialized_status = json.dumps(status_response.json(), ensure_ascii=False)
        self.assertNotIn(self.settings.llm_api_key, serialized_status)
        self.assertNotIn(self.settings.llm_base_url, serialized_status)

    def test_model_selection_is_rate_limited_per_client(self) -> None:
        model = FakeGlossaryModelClient()
        app = create_app(
            self.settings,
            glossary_model_client=model,
            glossary_draft_path=self.temp_root / "quota-drafts.json",
            glossary_quota=GlossaryQuota(limit=1, window_seconds=60),
        )
        with TestClient(app) as client:
            first = client.post(
                "/knowledge/glosses/selection",
                json={
                    "poemId": self.poem_id,
                    "lineNo": 2,
                    "startOffset": 0,
                    "endOffset": 2,
                    "mode": "model",
                },
            )
            second = client.post(
                "/knowledge/glosses/selection",
                json={
                    "poemId": self.poem_id,
                    "lineNo": 2,
                    "startOffset": 2,
                    "endOffset": 4,
                    "mode": "model",
                },
            )
        self.assertEqual(200, first.status_code)
        self.assertEqual("ok", first.json()["status"])
        self.assertEqual(429, second.status_code)
        self.assertEqual("rate_limited", second.json()["status"])
        self.assertEqual(1, len(model.calls))


if __name__ == "__main__":
    unittest.main()
