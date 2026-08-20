from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from poetry_agent.glossary import PoetryGlossary
from poetry_agent.selection_glossary import (
    GlossaryDraftStore,
    GlossaryDraftStoreError,
    GlossaryQuota,
    GlossarySelectionService,
    OpenAICompatibleGlossaryClient,
)


class FakeRepository:
    def get_poem(self, poem_id: str):
        if poem_id != "poem-1":
            return None
        return {
            "poemId": poem_id,
            "title": "山居秋暝",
            "poet": "王维",
            "dynasty": "唐",
            "lines": [{"lineNo": 1, "text": "明月松间照，清泉石上流。"}],
        }


class FakeModel:
    model = "test-model"

    def __init__(self, result=None):
        self.calls = []
        self.result = result or {
            "definition": "月光从松林间照下。",
            "inContext": "描写山中月夜。",
            "category": "意象",
            "sourceNote": "模型生成，待审核。",
        }

    def explain(self, *, context, mode):
        self.calls.append((context, mode))
        return self.result


class SelectionGlossaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        glossary_path = self.root / "data" / "poetry_glossary.json"
        glossary_path.parent.mkdir()
        glossary_path.write_text(
            json.dumps(
                {
                    "glossaryVersion": "1.0.0",
                    "entries": [
                        {
                            "term_id": "gloss:明月",
                            "forms": ["明月"],
                            "definition": "明亮的月亮。",
                            "in_context": "本句中的月色。",
                            "category": "意象",
                            "source_note": "已审词典",
                            "status": "published",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.glossary = PoetryGlossary(self.root)
        self.drafts = self.root / "data" / "poetry_glossary_drafts.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def service(self, model=None):
        return GlossarySelectionService(
            FakeRepository(), self.glossary, model_client=model,
            draft_store=GlossaryDraftStore(self.drafts),
        )

    def test_exact_offsets_and_published_local_short_circuit(self) -> None:
        model = FakeModel()
        result = self.service(model).explain(
            poem_id="poem-1", line_no=1, start_offset=0, end_offset=2, mode="web"
        )
        self.assertEqual("ok", result["status"])
        self.assertEqual("明月", result["payload"]["term"])
        self.assertEqual("local", result["payload"]["method"])
        self.assertEqual("published", result["payload"]["reviewStatus"])
        self.assertEqual([], model.calls)
        self.assertFalse(self.drafts.exists())

    def test_range_outside_line_is_rejected(self) -> None:
        result = self.service().explain(
            poem_id="poem-1", line_no=1, start_offset=0, end_offset=99, mode="model"
        )
        self.assertEqual("invalid_request", result["status"])

    def test_missing_model_returns_source_error_without_draft(self) -> None:
        result = self.service().explain(
            poem_id="poem-1", line_no=1, start_offset=2, end_offset=4, mode="model"
        )
        self.assertEqual("source_error", result["status"])
        self.assertEqual("松间", result["payload"]["term"])
        self.assertEqual("source_error", result["payload"]["reviewStatus"])
        self.assertIsNone(result["payload"]["draftId"])
        self.assertFalse(self.drafts.exists())

    def test_draft_id_and_store_are_idempotent(self) -> None:
        service = self.service(FakeModel())
        first = service.explain(
            poem_id="poem-1", line_no=1, start_offset=2, end_offset=4, mode="model"
        )
        second = service.explain(
            poem_id="poem-1", line_no=1, start_offset=2, end_offset=4, mode="model"
        )
        stored = json.loads(self.drafts.read_text(encoding="utf-8"))
        self.assertEqual(first["payload"]["draftId"], second["payload"]["draftId"])
        self.assertEqual("llm", first["payload"]["method"])
        self.assertEqual("draft", first["payload"]["reviewStatus"])
        self.assertEqual(1, len(stored["drafts"]))
        self.assertTrue(second["payload"]["reused"])
        self.assertEqual(1, len(service.model_client.calls))
        self.assertTrue(service.draft_store.lock_path.exists())

    def test_concurrent_duplicate_selection_calls_model_once(self) -> None:
        class SlowModel(FakeModel):
            def __init__(self):
                super().__init__()
                self.call_lock = threading.Lock()

            def explain(self, *, context, mode):
                with self.call_lock:
                    self.calls.append((context, mode))
                time.sleep(0.08)
                return self.result

        model = SlowModel()
        services = [self.service(model) for _ in range(4)]
        barrier = threading.Barrier(len(services))

        def request(service):
            barrier.wait()
            return service.explain(
                poem_id="poem-1", line_no=1, start_offset=2,
                end_offset=4, mode="model")

        with ThreadPoolExecutor(max_workers=len(services)) as executor:
            results = list(executor.map(request, services))

        self.assertEqual(1, len(model.calls))
        self.assertTrue(all(result["status"] == "ok" for result in results))
        self.assertEqual(1, sum(not result["payload"]["reused"] for result in results))
        self.assertEqual(3, sum(result["payload"]["reused"] for result in results))
        self.assertEqual(1, len(json.loads(
            self.drafts.read_text(encoding="utf-8"))["drafts"]))

    def test_model_name_change_does_not_reuse(self) -> None:
        first = self.service(FakeModel()).explain(
            poem_id="poem-1", line_no=1, start_offset=2, end_offset=4, mode="model")
        second_service = GlossarySelectionService(
            FakeRepository(), self.glossary, model_client=FakeModel(),
            model_name="different-model", draft_store=GlossaryDraftStore(self.drafts))
        second = second_service.explain(
            poem_id="poem-1", line_no=1, start_offset=2, end_offset=4, mode="model")
        self.assertNotEqual(first["payload"]["draftId"], second["payload"]["draftId"])
        self.assertFalse(second["payload"]["reused"])

    def test_corrupt_draft_is_not_overwritten(self) -> None:
        self.drafts.write_text("{broken", encoding="utf-8")
        service = self.service(FakeModel())
        result = service.explain(
            poem_id="poem-1", line_no=1, start_offset=2, end_offset=4, mode="model")
        self.assertEqual("source_error", result["status"])
        self.assertEqual("{broken", self.drafts.read_text(encoding="utf-8"))
        with self.assertRaises(GlossaryDraftStoreError):
            service.draft_store.find("missing")

    def test_tampered_draft_is_not_reused_or_overwritten(self) -> None:
        service = self.service(FakeModel())
        first = service.explain(
            poem_id="poem-1", line_no=1, start_offset=2, end_offset=4, mode="model")
        original = self.drafts.read_text(encoding="utf-8")
        payload = json.loads(original)
        payload["drafts"][0]["result"]["sourceNote"] = "https://attacker.invalid/credential"
        tampered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        self.drafts.write_text(tampered, encoding="utf-8")

        result = service.explain(
            poem_id="poem-1", line_no=1, start_offset=2, end_offset=4, mode="model")
        self.assertEqual("source_error", result["status"])
        self.assertEqual(tampered, self.drafts.read_text(encoding="utf-8"))
        self.assertEqual(1, len(service.model_client.calls))
        self.assertTrue(first["payload"]["draftId"])

    def test_quota_is_checked_inside_store_lock_and_reuse_is_free(self) -> None:
        now = [100.0]
        quota = GlossaryQuota(limit=1, window_seconds=60, clock=lambda: now[0])
        model = FakeModel()
        service = GlossarySelectionService(
            FakeRepository(), self.glossary, model_client=model,
            draft_store=GlossaryDraftStore(self.drafts), quota=quota,
        )
        first = service.explain(
            poem_id="poem-1", line_no=1, start_offset=2, end_offset=4,
            mode="model", client_key="client-a")
        reused = service.explain(
            poem_id="poem-1", line_no=1, start_offset=2, end_offset=4,
            mode="model", client_key="client-a")
        limited = service.explain(
            poem_id="poem-1", line_no=1, start_offset=3, end_offset=5,
            mode="model", client_key="client-a")
        self.assertEqual("ok", first["status"])
        self.assertTrue(reused["payload"]["reused"])
        self.assertEqual("rate_limited", limited["status"])
        self.assertEqual(1, len(model.calls))
        now[0] = 161.0
        after_window = service.explain(
            poem_id="poem-1", line_no=1, start_offset=3, end_offset=5,
            mode="model", client_key="client-a")
        self.assertEqual("ok", after_window["status"])

    def test_web_sources_keep_only_plain_http_urls(self) -> None:
        model = FakeModel(
            {
                "definition": "松林之间。",
                "sources": [
                    {"title": "可信来源", "url": "https://example.com/note"},
                    {"title": "凭据", "url": "https://user:pass@example.com/private"},
                    {"title": "脚本", "url": "javascript:alert(1)"},
                    {"title": "本地", "url": "file:///tmp/note"},
                    {"title": {"bad": True}, "url": "https://bad.example"},
                    "not-an-object",
                ],
            }
        )
        result = self.service(model).explain(
            poem_id="poem-1", line_no=1, start_offset=2, end_offset=4, mode="web"
        )
        self.assertEqual("llm_web", result["payload"]["method"])
        self.assertEqual(
            [{"title": "可信来源", "url": "https://example.com/note"}],
            result["payload"]["sources"],
        )
        self.assertEqual("模型联网检索，来源见引用，待人工审核",
                         result["payload"]["sourceNote"])

    def test_html_and_oversized_model_text_is_rejected(self) -> None:
        model = FakeModel({"definition": "<b>bad</b>"})
        result = self.service(model).explain(
            poem_id="poem-1", line_no=1, start_offset=2, end_offset=4, mode="model")
        self.assertEqual("source_error", result["status"])
        model.result = {"definition": "x" * 2001}
        result = GlossarySelectionService(
            FakeRepository(), self.glossary, model_client=model,
            draft_store=GlossaryDraftStore(self.drafts)).explain(
                poem_id="poem-1", line_no=1, start_offset=2, end_offset=4, mode="model")
        self.assertEqual("source_error", result["status"])

    def test_provider_error_is_redacted(self) -> None:
        client = OpenAICompatibleGlossaryClient(
            "https://private.internal/v1", "secret-key", "model-x",
            transport=lambda endpoint, body: (_ for _ in ()).throw(
                RuntimeError("response body https://private.internal/leak secret-key")))
        with self.assertRaises(Exception) as raised:
            client.explain(context={"term": "松间"}, mode="model")
        message = str(raised.exception)
        self.assertNotIn("response body", message)
        self.assertNotIn("private.internal", message)
        self.assertNotIn("secret-key", message)

    def test_web_sources_are_limited_to_five(self) -> None:
        model = FakeModel({
            "definition": "松林之间。",
            "sources": [{"title": str(i), "url": f"https://example.com/{i}"}
                        for i in range(8)],
        })
        result = self.service(model).explain(
            poem_id="poem-1", line_no=1, start_offset=2, end_offset=4, mode="web")
        self.assertEqual(5, len(result["payload"]["sources"]))

    def test_openai_web_uses_responses_and_parses_url_citation(self) -> None:
        calls = []
        def transport(endpoint, body):
            calls.append((endpoint, body))
            return {
                "output_text": json.dumps({"definition": "松林之间。"}, ensure_ascii=False),
                "output": [{"content": [{"type": "output_text", "text": "ignored",
                    "annotations": [{"type": "url_citation", "url": "https://example.com/a",
                                     "title": "出处"}]}]}],
            }
        client = OpenAICompatibleGlossaryClient(
            "https://provider.test/v1", "secret", "model-x", transport=transport
        )
        result = client.explain(context={"term": "松间"}, mode="web")
        self.assertEqual("https://provider.test/v1/responses", calls[0][0])
        self.assertEqual([{"type": "web_search"}], calls[0][1]["tools"])
        self.assertEqual([{"title": "出处", "url": "https://example.com/a"}], result["sources"])

    def test_openai_web_without_citation_is_source_error_and_not_saved(self) -> None:
        client = OpenAICompatibleGlossaryClient(
            "https://provider.test/v1", "secret", "model-x",
            transport=lambda endpoint, body: {
                "output_text": json.dumps({"definition": "无引用结果"}, ensure_ascii=False),
                "output": [],
            },
        )
        result = self.service(client).explain(
            poem_id="poem-1", line_no=1, start_offset=2, end_offset=4, mode="web"
        )
        self.assertEqual("source_error", result["status"])
        self.assertNotIn("url_citation", result["methodNote"])
        self.assertFalse(self.drafts.exists())

    def test_status_is_complete_tool_response(self) -> None:
        result = self.service().status()
        self.assertEqual("ok", result["status"])
        self.assertEqual("1.0", result["schemaVersion"])
        self.assertIn("draftStore", result["payload"])


if __name__ == "__main__":
    unittest.main()
