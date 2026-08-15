from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import httpx

from poetry_agent.embedding_builder import EmbeddingBuildError, build_poetry_embeddings
from poetry_agent.embeddings import (
    MAX_EMBEDDING_CHUNK_CHARS,
    EmbeddingProviderConfig,
    EmbeddingProviderError,
    EmbeddingUnavailableError,
    PoetryEmbeddingRepository,
    SiliconFlowEmbeddingClient,
    split_embedding_text,
    validate_embedding_response,
)
from poetry_agent.knowledge_builder import build_knowledge_base


POEMS = [
    {
        "title": "静夜思",
        "author": "李白",
        "dynasty": "唐",
        "body": "床前明月光，疑是地上霜。\n举头望明月，低头思故乡。",
        "source_poem_id": "vector-jingyesi",
    },
    {
        "title": "江雪",
        "author": "柳宗元",
        "dynasty": "唐",
        "body": "千山鸟飞绝，万径人踪灭。\n孤舟蓑笠翁，独钓寒江雪。",
        "source_poem_id": "vector-jiangxue",
    },
]


class FakeEmbeddingClient:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.fail_once = fail_once

    @staticmethod
    def vector(text: str) -> list[float]:
        raw = [
            5.0 if "月" in text else 0.2,
            5.0 if "雪" in text else 0.2,
            5.0 if "乡" in text else 0.2,
            1.0,
        ]
        norm = math.sqrt(sum(value * value for value in raw))
        return [value / norm for value in raw]

    def embed(self, texts: list[str]):
        self.calls.append(list(texts))
        if self.fail_once:
            self.fail_once = False
            raise EmbeddingProviderError("temporary fixture failure")
        return [self.vector(text) for text in texts], {
            "model": "BAAI/bge-m3",
            "usage": {"prompt_tokens": len(texts), "total_tokens": len(texts)},
        }


class SequenceHttpClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, dict]] = []

    def post(self, url: str, **kwargs):
        self.requests.append((url, kwargs))
        return self.responses.pop(0)


class ProtocolErrorHttpClient:
    def post(self, _url: str, **_kwargs):
        raise httpx.ProtocolError("connection reset")


class RejectContainingClient(FakeEmbeddingClient):
    def __init__(self, needle: str) -> None:
        super().__init__()
        self.needle = needle

    def embed(self, texts: list[str]):
        self.calls.append(list(texts))
        if any(self.needle in text for text in texts):
            raise EmbeddingProviderError("invalid fixture", status_code=400)
        return [self.vector(text) for text in texts], {
            "model": "BAAI/bge-m3",
            "usage": {"prompt_tokens": len(texts), "total_tokens": len(texts)},
        }


class EmbeddingContractTests(unittest.TestCase):
    def test_endpoint_and_response_order_are_openai_compatible(self) -> None:
        config = EmbeddingProviderConfig(
            base_url="https://api.siliconflow.cn/v1/",
            api_key="secret",
            model="BAAI/bge-m3",
        )
        self.assertEqual(
            "https://api.siliconflow.cn/v1/embeddings", config.endpoint
        )
        vectors, model, usage = validate_embedding_response(
            {
                "model": "BAAI/bge-m3",
                "data": [
                    {"index": 1, "embedding": [0.0, 2.0]},
                    {"index": 0, "embedding": [3.0, 0.0]},
                ],
                "usage": {"prompt_tokens": 4, "total_tokens": 4},
            },
            2,
        )
        self.assertEqual([[1.0, 0.0], [0.0, 1.0]], vectors)
        self.assertEqual("BAAI/bge-m3", model)
        self.assertEqual(4, usage["total_tokens"])

    def test_response_rejects_duplicate_index_bad_dimension_and_nan(self) -> None:
        invalid = [
            {
                "data": [
                    {"index": 0, "embedding": [1, 0]},
                    {"index": 0, "embedding": [0, 1]},
                ]
            },
            {
                "data": [
                    {"index": 0, "embedding": [1, 0]},
                    {"index": 1, "embedding": [0, 1, 2]},
                ]
            },
            {"data": [{"index": 0, "embedding": [float("nan"), 1]}]},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(EmbeddingProviderError):
                    validate_embedding_response(payload, len(payload["data"]))

    def test_client_retries_429_and_never_logs_or_sends_key_in_body(self) -> None:
        request = httpx.Request("POST", "https://api.siliconflow.cn/v1/embeddings")
        transport = SequenceHttpClient(
            [
                httpx.Response(429, text="rate", headers={"Retry-After": "0"}, request=request),
                httpx.Response(
                    200,
                    json={
                        "model": "BAAI/bge-m3",
                        "data": [{"index": 0, "embedding": [3.0, 4.0]}],
                    },
                    request=request,
                ),
            ]
        )
        client = SiliconFlowEmbeddingClient(
            EmbeddingProviderConfig(api_key="top-secret", retries=1),
            client=transport,  # type: ignore[arg-type]
            sleep=lambda _seconds: None,
        )
        vectors, _metadata = client.embed(["明月"])
        self.assertAlmostEqual(1.0, math.sqrt(sum(v * v for v in vectors[0])))
        self.assertEqual(2, len(transport.requests))
        _url, kwargs = transport.requests[-1]
        self.assertEqual("Bearer top-secret", kwargs["headers"]["Authorization"])
        self.assertNotIn("top-secret", json.dumps(kwargs["json"], ensure_ascii=False))

    def test_client_wraps_protocol_errors_without_exposing_key(self) -> None:
        client = SiliconFlowEmbeddingClient(
            EmbeddingProviderConfig(api_key="top-secret", retries=0),
            client=ProtocolErrorHttpClient(),  # type: ignore[arg-type]
        )
        with self.assertRaisesRegex(EmbeddingProviderError, "网络失败") as raised:
            client.embed(["明月"])
        self.assertNotIn("top-secret", str(raised.exception))

    def test_client_exposes_non_retryable_http_status_without_retrying(self) -> None:
        request = httpx.Request("POST", "https://api.siliconflow.cn/v1/embeddings")
        transport = SequenceHttpClient(
            [httpx.Response(400, text="invalid top-secret", request=request)]
        )
        client = SiliconFlowEmbeddingClient(
            EmbeddingProviderConfig(api_key="top-secret", retries=4),
            client=transport,  # type: ignore[arg-type]
        )
        with self.assertRaises(EmbeddingProviderError) as raised:
            client.embed(["明月"])
        self.assertEqual(400, raised.exception.status_code)
        self.assertNotIn("top-secret", str(raised.exception))
        self.assertEqual(1, len(transport.requests))

    def test_long_text_is_chunked_and_length_weighted_without_losing_tail(self) -> None:
        request = httpx.Request("POST", "https://api.siliconflow.cn/v1/embeddings")
        transport = SequenceHttpClient(
            [
                httpx.Response(
                    200,
                    json={
                        "model": "BAAI/bge-m3",
                        "data": [
                            {"index": 0, "embedding": [3.0, 0.0]},
                            {"index": 1, "embedding": [0.0, 4.0]},
                        ],
                        "usage": {"prompt_tokens": 10, "total_tokens": 10},
                    },
                    request=request,
                ),
                httpx.Response(
                    200,
                    json={
                        "model": "BAAI/bge-m3",
                        "data": [{"index": 0, "embedding": [0.0, 5.0]}],
                        "usage": {"prompt_tokens": 2, "total_tokens": 2},
                    },
                    request=request,
                ),
            ]
        )
        client = SiliconFlowEmbeddingClient(
            EmbeddingProviderConfig(api_key="secret", batch_size=2),
            client=transport,  # type: ignore[arg-type]
        )
        long_text = "甲" * (MAX_EMBEDDING_CHUNK_CHARS + 1)
        vectors, metadata = client.embed([long_text, "乙"])
        sent = [
            text
            for _url, kwargs in transport.requests
            for text in kwargs["json"]["input"]
        ]
        self.assertEqual(long_text, "".join(sent[:2]))
        self.assertTrue(all(len(text) <= MAX_EMBEDDING_CHUNK_CHARS for text in sent))
        self.assertGreater(vectors[0][0], 0.999)
        self.assertEqual([0.0, 1.0], vectors[1])
        self.assertEqual(2, metadata["request_count"])
        self.assertEqual(12, metadata["usage"]["total_tokens"])
        self.assertEqual(2, len(split_embedding_text(long_text)))


class EmbeddingBuilderIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temporary.name)
        self.source = self.root / "poems.json"
        self.source.write_text(json.dumps(POEMS, ensure_ascii=False), encoding="utf-8")
        self.knowledge = self.root / "knowledge.sqlite3"
        build_knowledge_base(source=self.source, output=self.knowledge, rebuild=True)
        self.vector_root = self.root / "embeddings"
        self.config = EmbeddingProviderConfig(
            api_key="fixture", model="BAAI/bge-m3", batch_size=2, concurrency=2
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_public_build_publishes_pointer_and_semantic_search(self) -> None:
        client = FakeEmbeddingClient()
        manifest = build_poetry_embeddings(
            knowledge_path=self.knowledge,
            output_root=self.vector_root,
            client=client,  # type: ignore[arg-type]
            config=self.config,
            scopes=("poem", "line"),
        )
        self.assertEqual("embedding-1.0", manifest["schemaVersion"])
        self.assertEqual(4, manifest["dimension"])
        self.assertEqual(
            MAX_EMBEDDING_CHUNK_CHARS,
            manifest["longTextPolicy"]["maxChunkCharacters"],
        )
        self.assertEqual(2, manifest["counts"]["poem"]["completed"])
        self.assertEqual(4, manifest["counts"]["line"]["completed"])
        self.assertTrue((self.vector_root / "current.json").is_file())
        pointer = json.loads(
            (self.vector_root / "current.json").read_text(encoding="utf-8")
        )
        artifact = self.vector_root / pointer["artifact"]
        self.assertTrue((artifact / "items.sqlite3").is_file())
        self.assertTrue((artifact / "lines.f32").is_file())

        repository = PoetryEmbeddingRepository(self.vector_root, self.knowledge)
        status = repository.status()
        self.assertTrue(status["available"])
        result = repository.search(
            "月亮与思乡",
            scope="line",
            query_vector=FakeEmbeddingClient.vector("月亮与思乡"),
            limit=3,
        )
        self.assertEqual("vector-jingyesi", result["items"][0]["poemId"])
        self.assertEqual("siliconflow_embedding_cosine", result["retrievalMethod"])
        self.assertGreaterEqual(result["items"][0]["score"], result["items"][1]["score"])
        filtered = repository.search(
            "月亮",
            scope="line",
            imagery="明月",
            query_vector=FakeEmbeddingClient.vector("月亮"),
            limit=10,
        )
        self.assertTrue(filtered["items"])
        self.assertTrue(
            all(item["poemId"] == "vector-jingyesi" for item in filtered["items"])
        )

        no_call = FakeEmbeddingClient(fail_once=True)
        reused = build_poetry_embeddings(
            knowledge_path=self.knowledge,
            output_root=self.vector_root,
            client=no_call,  # type: ignore[arg-type]
            config=self.config,
            scopes=("poem", "line"),
        )
        self.assertEqual(manifest["buildId"], reused["buildId"])
        self.assertEqual([], no_call.calls)

    def test_failed_batch_keeps_checkpoint_and_resume_completes(self) -> None:
        failing = FakeEmbeddingClient(fail_once=True)
        with self.assertRaisesRegex(EmbeddingBuildError, "已保留断点"):
            build_poetry_embeddings(
                knowledge_path=self.knowledge,
                output_root=self.vector_root,
                client=failing,  # type: ignore[arg-type]
                config=self.config,
                scopes=("line",),
            )
        self.assertFalse((self.vector_root / "current.json").exists())
        self.assertTrue(any(self.vector_root.rglob("*.building")))

        manifest = build_poetry_embeddings(
            knowledge_path=self.knowledge,
            output_root=self.vector_root,
            client=FakeEmbeddingClient(),  # type: ignore[arg-type]
            config=self.config,
            scopes=("line",),
        )
        self.assertEqual(4, manifest["counts"]["line"]["completed"])
        self.assertEqual(0, manifest["counts"]["line"]["failed"])

    def test_http_400_batch_is_bisected_and_resume_only_retries_bad_item(self) -> None:
        rejecting = RejectContainingClient("江雪")
        with self.assertRaisesRegex(EmbeddingBuildError, "已保留断点"):
            build_poetry_embeddings(
                knowledge_path=self.knowledge,
                output_root=self.vector_root,
                client=rejecting,  # type: ignore[arg-type]
                config=self.config,
                scopes=("poem",),
            )
        self.assertEqual([1, 1, 2], sorted(len(call) for call in rejecting.calls))

        recovered = FakeEmbeddingClient()
        manifest = build_poetry_embeddings(
            knowledge_path=self.knowledge,
            output_root=self.vector_root,
            client=recovered,  # type: ignore[arg-type]
            config=self.config,
            scopes=("poem",),
        )
        self.assertEqual(2, manifest["counts"]["poem"]["completed"])
        self.assertEqual(0, manifest["counts"]["poem"]["failed"])
        self.assertEqual(1, len(recovered.calls))
        self.assertEqual(1, len(recovered.calls[0]))
        self.assertIn("江雪", recovered.calls[0][0])

    def test_partial_artifact_is_marked_and_never_activated(self) -> None:
        failing = FakeEmbeddingClient(fail_once=True)
        manifest = build_poetry_embeddings(
            knowledge_path=self.knowledge,
            output_root=self.vector_root,
            client=failing,  # type: ignore[arg-type]
            config=self.config,
            scopes=("line",),
            allow_partial=True,
        )
        self.assertEqual("partial", manifest["status"])
        self.assertTrue(any(self.vector_root.rglob("*.building")))
        with self.assertRaises(EmbeddingUnavailableError):
            PoetryEmbeddingRepository(self.vector_root, self.knowledge).status()

    def test_repository_rejects_vector_manifest_bound_to_other_knowledge_build(self) -> None:
        build_poetry_embeddings(
            knowledge_path=self.knowledge,
            output_root=self.vector_root,
            client=FakeEmbeddingClient(),  # type: ignore[arg-type]
            config=self.config,
            scopes=("line",),
        )
        knowledge_manifest = self.knowledge.with_suffix(".manifest.json")
        payload = json.loads(knowledge_manifest.read_text(encoding="utf-8"))
        payload["buildId"] = "different-build"
        knowledge_manifest.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        with self.assertRaisesRegex(EmbeddingUnavailableError, "buildId"):
            PoetryEmbeddingRepository(self.vector_root, self.knowledge).status()


if __name__ == "__main__":
    unittest.main()
