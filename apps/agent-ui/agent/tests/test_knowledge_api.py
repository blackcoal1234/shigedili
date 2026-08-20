from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

from poetry_agent.config import Settings, discover_project_root
from poetry_agent.knowledge_builder import build_knowledge_base
from poetry_agent.main import create_app


class PoetryKnowledgeApiIntegrationTests(unittest.TestCase):
    """Exercise the HTTP contracts against a small, real compiled snapshot."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.temp_root = Path(cls.temporary.name)
        cls.project_root = discover_project_root()
        cls.database = cls.temp_root / "tiny-knowledge.sqlite3"
        cls.manifest = build_knowledge_base(
            source=cls.project_root / "data" / "poems.json",
            output=cls.database,
            poet="王维",
            limit=2,
            rebuild=True,
        )
        settings = Settings(
            project_root=cls.project_root,
            cache_dir=cls.temp_root / "cache",
            llm_base_url="",
            llm_api_key="",
            llm_model="",
            allowed_origins=(),
            knowledge_base_path=cls.database,
        )
        cls.app = create_app(settings)
        cls.client = TestClient(cls.app)

        source_records = json.loads(
            (cls.project_root / "data" / "poems.json").read_text(
                encoding="utf-8-sig"
            )
        )
        cls.fixture_records = [
            row
            for row in source_records
            if (row.get("poet") or row.get("author")) == "王维"
        ][:2]
        cls.poem_id = str(cls.fixture_records[0]["source_poem_id"])

        poem_response = cls.client.get(f"/knowledge/poems/{cls.poem_id}")
        if poem_response.status_code != 200 or poem_response.json().get("status") != "ok":
            raise AssertionError(poem_response.text)
        cls.line_id = poem_response.json()["payload"]["lines"][0]["lineId"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        cls.temporary.cleanup()

    def assert_service_response(self, body: dict, expected_status: str) -> None:
        self.assertEqual(
            {"status", "schemaVersion", "sourceHashes", "methodNote", "payload"},
            set(body),
        )
        self.assertEqual(expected_status, body["status"])

    def test_get_status_reports_the_tiny_snapshot_without_model_config(self) -> None:
        response = self.client.get("/knowledge/status")
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assert_service_response(body, "ok")
        payload = body["payload"]
        self.assertTrue(payload["available"])
        self.assertEqual(2, payload["poemCount"])
        self.assertEqual(8, payload["lineCount"])
        self.assertEqual(self.manifest["buildId"], payload["buildId"])
        self.assertEqual(
            {"poet": "王维", "limit": 2}, payload["manifest"]["filters"]
        )

    def test_get_search_supports_composed_filters_and_offset_pagination(self) -> None:
        filtered = self.client.get(
            "/knowledge/search",
            params={
                "query": "大漠孤烟直",
                "poet": "王维",
                "dynasty": "唐",
                "imagery": "烟",
                "emotion": "孤寂清冷",
                "scope": "line",
                "limit": 10,
                "offset": 0,
            },
        )
        self.assertEqual(200, filtered.status_code)
        filtered_body = filtered.json()
        self.assert_service_response(filtered_body, "ok")
        filtered_payload = filtered_body["payload"]
        self.assertEqual(1, filtered_payload["total"])
        self.assertEqual("王维", filtered_payload["items"][0]["poet"])
        self.assertIn("大漠孤烟直", filtered_payload["items"][0]["text"])
        self.assertEqual("烟", filtered_payload["filters"]["imagery"])
        self.assertEqual("孤寂清冷", filtered_payload["filters"]["emotion"])

        first_page = self.client.get(
            "/knowledge/search",
            params={
                "query": "",
                "poet": "王维",
                "scope": "line",
                "limit": 2,
                "offset": 0,
            },
        ).json()["payload"]
        shifted_page = self.client.get(
            "/knowledge/search",
            params={
                "query": "",
                "poet": "王维",
                "scope": "line",
                "limit": 2,
                "offset": 1,
            },
        ).json()["payload"]
        self.assertEqual(8, first_page["total"])
        self.assertEqual(8, shifted_page["total"])
        self.assertEqual(1, shifted_page["offset"])
        self.assertEqual(first_page["items"][1], shifted_page["items"][0])

    def test_get_poem_and_url_encoded_line_id_return_details(self) -> None:
        poem_response = self.client.get(f"/knowledge/poems/{self.poem_id}")
        self.assertEqual(200, poem_response.status_code)
        poem_body = poem_response.json()
        self.assert_service_response(poem_body, "ok")
        self.assertEqual(self.poem_id, poem_body["payload"]["poemId"])
        self.assertEqual("山居秋暝", poem_body["payload"]["title"])
        self.assertEqual(4, len(poem_body["payload"]["lines"]))
        self.assertEqual("1.0.0", poem_body["payload"]["glossaryVersion"])
        self.assertEqual([], poem_body["payload"]["glosses"])

        encoded_line_id = quote(self.line_id, safe="")
        self.assertNotEqual(self.line_id, encoded_line_id)
        line_response = self.client.get(f"/knowledge/lines/{encoded_line_id}")
        self.assertEqual(200, line_response.status_code)
        line_body = line_response.json()
        self.assert_service_response(line_body, "ok")
        self.assertEqual(self.line_id, line_body["payload"]["lineId"])
        self.assertEqual(self.poem_id, line_body["payload"]["poemId"])
        self.assertEqual(
            self.fixture_records[0]["body"][
                line_body["payload"]["startOffset"] : line_body["payload"]["endOffset"]
            ],
            line_body["payload"]["text"],
        )

    def test_three_post_knowledge_tools_share_the_same_snapshot(self) -> None:
        search_response = self.client.post(
            "/tools/search_poetry_knowledge",
            json={
                "query": "明月松间照",
                "poet": "王维",
                "dynasty": "唐",
                "scope": "line",
                "limit": 5,
                "offset": 0,
            },
        )
        self.assertEqual(200, search_response.status_code)
        search_body = search_response.json()
        self.assert_service_response(search_body, "ok")
        self.assertEqual(1, search_body["payload"]["total"])
        searched_line_id = search_body["payload"]["items"][0]["lineId"]

        poem_response = self.client.post(
            "/tools/get_poem_knowledge", json={"poem_id": self.poem_id}
        )
        self.assertEqual(200, poem_response.status_code)
        poem_body = poem_response.json()
        self.assert_service_response(poem_body, "ok")
        self.assertEqual(self.poem_id, poem_body["payload"]["poemId"])

        line_response = self.client.post(
            "/tools/get_line_knowledge", json={"line_id": searched_line_id}
        )
        self.assertEqual(200, line_response.status_code)
        line_body = line_response.json()
        self.assert_service_response(line_body, "ok")
        self.assertEqual(searched_line_id, line_body["payload"]["lineId"])
        self.assertIn("明月松间照", line_body["payload"]["text"])

    def test_unknown_ids_are_http_200_business_insufficient_evidence(self) -> None:
        for path in (
            "/knowledge/poems/not-a-real-poem",
            "/knowledge/lines/not-a-real-line",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(200, response.status_code)
                body = response.json()
                self.assert_service_response(body, "insufficient_evidence")
                self.assertTrue(body["payload"]["notFound"])

        post_response = self.client.post(
            "/tools/get_poem_knowledge", json={"poem_id": "not-a-real-poem"}
        )
        self.assertEqual(200, post_response.status_code)
        self.assert_service_response(post_response.json(), "insufficient_evidence")

    def test_post_search_limit_overflow_returns_custom_422_contract(self) -> None:
        response = self.client.post(
            "/tools/search_poetry_knowledge",
            json={"query": "", "scope": "all", "limit": 51, "offset": 0},
        )
        self.assertEqual(422, response.status_code)
        body = response.json()
        self.assert_service_response(body, "invalid_request")
        issues = body["payload"]["validationErrors"]
        self.assertTrue(any(issue["field"] == "body.limit" for issue in issues))


if __name__ == "__main__":
    unittest.main()
