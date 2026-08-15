from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from poetry_agent.config import Settings, discover_project_root
from poetry_agent.embedding_builder import build_poetry_embeddings
from poetry_agent.embeddings import EmbeddingProviderConfig, EmbeddingProviderError
from poetry_agent.knowledge_builder import build_knowledge_base
from poetry_agent.main import create_app


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.calls = 0

    @staticmethod
    def vector(text: str) -> list[float]:
        raw = [
            4.0 if "月" in text else 0.1,
            4.0 if "山" in text else 0.1,
            4.0 if "归" in text or "乡" in text else 0.1,
            1.0,
        ]
        norm = math.sqrt(sum(value * value for value in raw))
        return [value / norm for value in raw]

    def embed(self, texts):
        self.calls += 1
        return [self.vector(text) for text in texts], {
            "model": "BAAI/bge-m3",
            "usage": {},
        }


class FailingEmbeddingClient:
    def embed(self, _texts):
        raise EmbeddingProviderError("provider unavailable", status_code=503)


class PoetryEmbeddingApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.root = Path(cls.temporary.name)
        cls.project_root = discover_project_root()
        cls.knowledge = cls.root / "knowledge.sqlite3"
        build_knowledge_base(
            source=cls.project_root / "data" / "poems.json",
            output=cls.knowledge,
            poet="王维",
            limit=2,
            rebuild=True,
        )
        cls.vector_root = cls.root / "embeddings"
        cls.fake = FakeEmbeddingClient()
        config = EmbeddingProviderConfig(
            api_key="fixture", model="BAAI/bge-m3", batch_size=2, concurrency=2
        )
        build_poetry_embeddings(
            knowledge_path=cls.knowledge,
            output_root=cls.vector_root,
            client=cls.fake,  # type: ignore[arg-type]
            config=config,
            scopes=("poem", "line"),
        )
        settings = Settings(
            project_root=cls.project_root,
            cache_dir=cls.root / "cache",
            llm_base_url="",
            llm_api_key="",
            llm_model="",
            embedding_api_key="",
            embedding_model="BAAI/bge-m3",
            vector_root_path=cls.vector_root,
            allowed_origins=(),
            knowledge_base_path=cls.knowledge,
        )
        cls.app = create_app(settings)
        cls.app.state.embedding_repository.client = cls.fake
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        cls.temporary.cleanup()

    def test_status_exposes_ready_vector_index_without_api_key(self) -> None:
        payload = self.client.get("/knowledge/status").json()["payload"]
        self.assertTrue(payload["vector"]["ready"])
        self.assertEqual("BAAI/bge-m3", payload["vector"]["model"])
        self.assertEqual(4, payload["vector"]["dimension"])
        self.assertGreater(payload["vector"]["indexedLineCount"], 0)

    def test_semantic_and_hybrid_modes_reuse_existing_search_contract(self) -> None:
        for mode in ("semantic", "hybrid"):
            with self.subTest(mode=mode):
                response = self.client.get(
                    "/knowledge/search",
                    params={
                        "query": "月色下思念故乡",
                        "scope": "line",
                        "mode": mode,
                        "limit": 5,
                    },
                )
                self.assertEqual(200, response.status_code)
                body = response.json()
                self.assertEqual("ok", body["status"])
                payload = body["payload"]
                self.assertEqual(mode, payload["requestedMode"])
                self.assertFalse(payload["degraded"])
                self.assertTrue(payload["items"])
                self.assertTrue(all(0 <= item["score"] <= 1 for item in payload["items"]))
                self.assertTrue(all(item["poemId"] for item in payload["items"]))

    def test_provider_unavailable_degrades_to_lexical_without_error(self) -> None:
        repository = self.app.state.embedding_repository
        configured = repository.client
        repository.client = None
        try:
            body = self.client.get(
                "/knowledge/search",
                params={
                    "query": "供应商故障回退专用查询",
                    "scope": "line",
                    "mode": "semantic",
                    "limit": 5,
                },
            ).json()
        finally:
            repository.client = configured
        self.assertEqual("ok", body["status"])
        self.assertEqual("lexical", body["payload"]["retrievalMethod"])
        self.assertTrue(body["payload"]["degraded"])
        self.assertEqual(
            "vector_not_ready", body["payload"]["degradationReason"]
        )

    def test_provider_error_degrades_to_lexical_without_error(self) -> None:
        repository = self.app.state.embedding_repository
        configured = repository.client
        repository.client = FailingEmbeddingClient()
        try:
            body = self.client.get(
                "/knowledge/search",
                params={
                    "query": "向量供应商异常降级专用查询",
                    "scope": "line",
                    "mode": "semantic",
                    "limit": 5,
                },
            ).json()
        finally:
            repository.client = configured
        self.assertEqual("ok", body["status"])
        self.assertEqual("lexical", body["payload"]["retrievalMethod"])
        self.assertTrue(body["payload"]["degraded"])
        self.assertEqual(
            "embedding_provider_unavailable",
            body["payload"]["degradationReason"],
        )

    def test_post_tool_accepts_mode_and_invalid_mode_uses_422_envelope(self) -> None:
        good = self.client.post(
            "/tools/search_poetry_knowledge",
            json={"query": "明月", "scope": "line", "mode": "semantic", "limit": 3},
        )
        self.assertEqual(200, good.status_code)
        self.assertEqual("semantic", good.json()["payload"]["requestedMode"])

        invalid = self.client.post(
            "/tools/search_poetry_knowledge",
            json={"query": "明月", "mode": "unknown"},
        )
        self.assertEqual(422, invalid.status_code)
        self.assertEqual("invalid_request", invalid.json()["status"])


if __name__ == "__main__":
    unittest.main()
