from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from poetry_agent.config import Settings, discover_project_root
from poetry_agent.main import create_app


class FastApiToolEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        settings = Settings(
            project_root=discover_project_root(),
            cache_dir=Path(self.temporary_directory.name) / "cache",
            llm_base_url="",
            llm_api_key="",
            llm_model="",
            allowed_origins=(),
        )
        self.app = create_app(settings)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.temporary_directory.cleanup()

    def assert_five_field_response(self, body, status: str) -> None:
        self.assertEqual(
            {"status", "schemaVersion", "sourceHashes", "methodNote", "payload"},
            set(body),
        )
        self.assertEqual(status, body["status"])

    def test_tool_routes_exist_with_existing_pydantic_request_models(self) -> None:
        expected = {
            "/tools/generate_poet_route": "GeneratePoetRouteInput",
            "/tools/play_poem_scenes": "PlayPoemScenesInput",
            "/tools/compare_imagery": "CompareImageryInput",
        }
        openapi_paths = self.app.openapi()["paths"]
        for path, model_name in expected.items():
            with self.subTest(path=path):
                self.assertIn(path, openapi_paths)
                schema = openapi_paths[path]["post"]["requestBody"]["content"][
                    "application/json"
                ]["schema"]
                self.assertTrue(schema["$ref"].endswith(f"/{model_name}"))

    def test_invalid_tool_parameters_return_five_fields_and_never_500(self) -> None:
        requests = (
            ("/tools/generate_poet_route", {"poet": 123}),
            (
                "/tools/generate_poet_route",
                {"poet": "李白", "include_approximate": "false"},
            ),
            ("/tools/play_poem_scenes", {"poet": "李白", "autoplay": 1}),
            ("/tools/compare_imagery", {"chapter_id": 7}),
        )
        for path, payload in requests:
            with self.subTest(path=path, payload=payload):
                response = self.client.post(path, json=payload)
                self.assertEqual(422, response.status_code)
                self.assert_five_field_response(response.json(), "invalid_request")

    def test_valid_tool_endpoint_forwards_to_shared_service(self) -> None:
        response = self.client.post(
            "/tools/generate_poet_route", json={"poet": "李白"}
        )
        self.assertEqual(200, response.status_code)
        self.assert_five_field_response(response.json(), "ok")

    def test_ready_route_reports_lightweight_knowledge_availability(self) -> None:
        response = self.client.get("/ready")
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertIn(body["status"], {"ok", "degraded"})
        self.assertIn("knowledgeBase", body["sources"])

    def test_runtime_repository_code_is_not_a_snapshot_content_source(self) -> None:
        expected = self.app.state.knowledge_repository.expected_sources
        self.assertNotIn("apps/agent-ui/agent/poetry_agent/knowledge.py", expected)
        self.assertIn(
            "apps/agent-ui/agent/poetry_agent/knowledge_builder.py", expected
        )


if __name__ == "__main__":
    unittest.main()
