from __future__ import annotations

import importlib.util
import json
import multiprocessing
import sqlite3
import threading
import time
import concurrent.futures
from pathlib import Path
from typing import Any

import pytest


SCRIPT = Path(__file__).resolve().parents[4] / "tools" / "build_poetry_glossary_drafts.py"
SPEC = importlib.util.spec_from_file_location("build_poetry_glossary_drafts", SCRIPT)
assert SPEC and SPEC.loader
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


def write_input(path: Path, items: object) -> Path:
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return path


def selection(index: int = 1) -> dict[str, object]:
    return {
        "poemId": f"poem-{index}",
        "lineNo": 1,
        "startOffset": 0,
        "endOffset": 1,
        "mode": "model",
    }


class _Repository:
    def get_poem(self, poem_id: str) -> dict[str, object] | None:
        if poem_id != "poem-1":
            return None
        return {"poemId": poem_id, "title": "题", "lines": [{"lineNo": 1, "text": "松间"}]}


class _SlowModel:
    model = "test-model"

    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def explain(self, *, context: dict[str, object], mode: str) -> dict[str, str]:
        with self._lock:
            self.calls += 1
        time.sleep(0.03)
        return {"definition": "释义", "category": "意象"}


def _cross_process_merge(kind: str, path: str, index: int) -> None:
    if kind == "draft":
        from poetry_agent.selection_glossary import GlossaryDraftStore

        store = GlossaryDraftStore(Path(path))
        poem_id = f"poem-{index}"
        request = {
            "poemId": poem_id,
            "title": "题",
            "poet": "作者",
            "dynasty": "唐",
            "lineNo": 1,
            "line": "松间",
            "startOffset": 0,
            "endOffset": 1,
            "term": "松",
            "mode": "model",
        }
        draft_id = f"gloss-draft-{index:024d}"
        # Use the production identity helper so the strict store schema is exercised.
        from poetry_agent.selection_glossary import _draft_id
        draft_id = _draft_id(
            request["poemId"], request["lineNo"], request["startOffset"],
            request["endOffset"], request["mode"], "test-model",
        )
        store.get_or_create(
            draft_id, request,
            lambda: {
                "term": "松", "definition": "树名。", "inContext": "句中所写的松树。",
                "category": "植物", "method": "llm", "reviewStatus": "draft",
                "sourceNote": "模型生成，待人工审核", "sources": [], "model": "test-model",
                "draftId": draft_id, "reused": False,
            },
        )
    else:
        store = cli.BatchFailureStore(Path(path))
        store.merge([{
            "selectionId": f"selection-{index}", "status": "failed",
            "request": {"index": index}, "error": "test",
        }])


class DraftService:
    def __init__(
        self,
        store: Any,
        failures: set[str] | None = None,
        *,
        model: str = "test-model",
    ) -> None:
        self.store = store
        self.failures = failures or set()
        self.model = model
        self.calls = 0

    def explain(self, **kwargs: object) -> dict[str, object]:
        poem_id = str(kwargs["poem_id"])
        if poem_id in self.failures:
            return {
                "status": "source_error",
                "methodNote": "model failed",
                "payload": {"reviewStatus": "source_error", "error": "model failed"},
            }
        item = {
            "poemId": poem_id,
            "title": "题",
            "poet": "作者",
            "dynasty": "唐",
            "lineNo": kwargs["line_no"],
            "line": "松间",
            "startOffset": kwargs["start_offset"],
            "endOffset": kwargs["end_offset"],
            "term": "松",
            "mode": kwargs["mode"],
        }
        from poetry_agent.selection_glossary import _draft_id

        draft_id = _draft_id(
            item["poemId"],
            item["lineNo"],
            item["startOffset"],
            item["endOffset"],
            item["mode"],
            self.model,
        )
        existing = self.store.find(draft_id)
        if existing is not None:
            existing["reused"] = True
            return {"status": "ok", "payload": existing}
        self.calls += 1
        payload = {
            "draftId": draft_id,
            "reviewStatus": "draft",
            "term": "松",
            "definition": "释义",
            "inContext": "句中义",
            "category": "词语",
            "method": "llm_web" if item["mode"] == "web" else "llm",
            "sourceNote": (
                "模型联网检索，来源见引用，待人工审核"
                if item["mode"] == "web" else "模型生成，待人工审核"
            ),
            "sources": [],
            "model": self.model,
            "reused": False,
        }
        self.store.save(draft_id, item, payload)
        return {"status": "ok", "payload": payload}


@pytest.mark.parametrize(
    "items",
    [
        [{"poemId": "x"}],
        [{**selection(), "mode": "publish"}],
        [{**selection(), "lineNo": True}],
    ],
)
def test_invalid_input_returns_nonzero(tmp_path: Path, items: object) -> None:
    input_path = write_input(tmp_path / "input.json", items)
    service = DraftService(cli.GlossaryDraftStore(tmp_path / "drafts.json"))
    assert cli.run(["--input", str(input_path)], service=service) == 2


def test_parser_exposes_no_publish_operation() -> None:
    parser = cli.build_parser()
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    assert "--publish" not in option_strings
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--input", "selections.json", "--publish"])
    assert exc_info.value.code == 2


def test_successful_run_does_not_mutate_formal_stores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    glossary_path = project_root / "data" / "poetry_glossary.json"
    knowledge_path = (
        project_root
        / "output"
        / "assets"
        / "knowledge"
        / "poetry_knowledge.sqlite3"
    )
    glossary_path.parent.mkdir(parents=True)
    knowledge_path.parent.mkdir(parents=True)
    glossary_path.write_bytes(b'{"sentinel":"formal-glossary"}\n')
    with sqlite3.connect(knowledge_path) as connection:
        connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel VALUES ('formal-knowledge')")

    glossary_before = glossary_path.read_bytes()
    knowledge_before = knowledge_path.read_bytes()
    monkeypatch.setattr(cli, "PROJECT_ROOT", project_root)

    input_path = write_input(tmp_path / "input.json", [selection()])
    output = tmp_path / "drafts.json"
    service = DraftService(cli.GlossaryDraftStore(output))
    assert cli.run(["--input", str(input_path), "--output", str(output)], service=service) == 0

    assert glossary_path.read_bytes() == glossary_before
    assert knowledge_path.read_bytes() == knowledge_before


def test_missing_llm_configuration_is_explicit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    input_path = write_input(tmp_path / "input.json", [selection()])

    def factory(output: Path, env: object) -> object:
        raise RuntimeError("缺少模型配置: AGENT_LLM_BASE_URL, AGENT_LLM_API_KEY, AGENT_LLM_MODEL")

    assert cli.run(["--input", str(input_path)], env={}, service_factory=factory) == 2
    error = capsys.readouterr().err
    assert "AGENT_LLM_API_KEY" in error
    assert "secret" not in error


def test_provider_exception_is_redacted_from_batch_failure_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    input_path = write_input(tmp_path / "input.json", [selection()])
    output = tmp_path / "drafts.json"
    secret = "https://provider.invalid/v1?api_key=super-secret"

    class ExplodingService:
        def explain(self, **kwargs: object) -> dict[str, object]:
            raise RuntimeError(f"provider failed at {secret}")

    assert cli.run(
        ["--input", str(input_path), "--output", str(output)],
        service=ExplodingService(),
    ) == 1
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    failures = json.loads(
        (tmp_path / "drafts.json.failures.json").read_text(encoding="utf-8")
    )
    assert failures["failures"][0]["error"] == "批处理调用失败: RuntimeError"
    assert secret not in json.dumps(failures, ensure_ascii=False)


def test_concurrency_is_bounded(tmp_path: Path) -> None:
    input_path = write_input(tmp_path / "input.json", [selection(i) for i in range(12)])
    output = tmp_path / "drafts.json"
    lock = threading.Lock()
    active = 0
    maximum = 0

    class TrackingService(DraftService):
        def explain(self, **kwargs: object) -> dict[str, object]:
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            try:
                time.sleep(0.01)
                return super().explain(**kwargs)
            finally:
                with lock:
                    active -= 1

    service = TrackingService(cli.GlossaryDraftStore(output))
    assert cli.run(["--input", str(input_path), "--output", str(output), "--concurrency", "3"], service=service) == 0
    assert 1 < maximum <= 3


def test_rerun_is_idempotent_and_partial_failure_succeeds(tmp_path: Path) -> None:
    input_path = write_input(tmp_path / "input.json", [selection(1), selection(2)])
    output = tmp_path / "drafts.json"
    args = ["--input", str(input_path), "--output", str(output)]
    service = DraftService(cli.GlossaryDraftStore(output), {"poem-2"})

    assert cli.run(args, service=service) == 0
    assert cli.run(args, service=service) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert len(payload["drafts"]) == 1
    assert payload["drafts"][0]["result"]["reviewStatus"] == "draft"
    assert payload["drafts"][0]["result"]["model"] == "test-model"
    assert service.calls == 1
    failures = json.loads(
        (tmp_path / "drafts.json.failures.json").read_text(encoding="utf-8")
    )
    assert len(failures["failures"]) == 1
    assert failures["failures"][0]["status"] == "failed"


def test_all_failures_return_nonzero(tmp_path: Path) -> None:
    input_path = write_input(tmp_path / "input.jsonl", selection(1))
    output = tmp_path / "drafts.json"
    service = DraftService(cli.GlossaryDraftStore(output), {"poem-1"})
    assert cli.run(["--input", str(input_path), "--output", str(output)], service=service) == 1


def test_process_unwraps_tool_response_payload(tmp_path: Path) -> None:
    service = DraftService(cli.GlossaryDraftStore(tmp_path / "drafts.json"))
    record = cli._process(service, selection())
    assert record["status"] == "draft"
    assert record["result"]["reviewStatus"] == "draft"
    assert "payload" not in record["result"]


def test_client_uses_backend_protocol_and_web_responses() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def transport(endpoint: str, body: dict[str, object]) -> dict[str, object]:
        calls.append((endpoint, body))
        return {
            "output_text": json.dumps({"definition": "释义"}),
            "output": [
                {
                    "content": [
                        {
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://example.test/source",
                                    "title": "source",
                                }
                            ]
                        }
                    ]
                }
            ],
        }

    client = cli.OpenAISelectionClient(
        "https://provider.test/v1", "not-a-real-secret", "test-model", transport=transport
    )
    result = client.explain(context={"term": "月"}, mode="web")
    assert calls[0][0] == "https://provider.test/v1/responses"
    assert calls[0][1]["tools"] == [{"type": "web_search"}]
    assert result["sources"] == [
        {"url": "https://example.test/source", "title": "source"}
    ]


def test_client_model_uses_chat_completions_and_parses_json() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def transport(endpoint: str, body: dict[str, object]) -> dict[str, object]:
        calls.append((endpoint, body))
        return {"choices": [{"message": {"content": '{"definition":"释义"}'}}]}

    client = cli.OpenAISelectionClient(
        "https://provider.test/v1", "secret", "model-x", transport=transport
    )
    result = client.explain(context={"term": "月"}, mode="model")
    assert calls[0][0] == "https://provider.test/v1/chat/completions"
    assert calls[0][1]["model"] == "model-x"
    assert calls[0][1]["response_format"] == {"type": "json_object"}
    assert calls[0][1]["messages"][0]["role"] == "user"
    assert result["definition"] == "释义"
    assert result["model"] == "model-x"


def test_real_service_duplicate_selection_calls_provider_once(tmp_path: Path) -> None:
    from poetry_agent.glossary import PoetryGlossary
    from poetry_agent.selection_glossary import GlossarySelectionService

    formal = tmp_path / "data" / "poetry_glossary.json"
    formal.parent.mkdir()
    formal.write_text(
        '{"glossaryVersion":"1.0.0","entries":[]}\n', encoding="utf-8"
    )
    model = _SlowModel()
    draft_path = tmp_path / "drafts.json"
    services = [GlossarySelectionService(
        _Repository(), PoetryGlossary(tmp_path), model_client=model,
        draft_store=cli.GlossaryDraftStore(draft_path),
    ) for _ in range(4)]
    barrier = threading.Barrier(len(services))

    def request(service: object) -> dict[str, object]:
        barrier.wait()
        return service.explain(poem_id="poem-1", line_no=1, start_offset=0,
                               end_offset=2, mode="model")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(request, services))
    assert model.calls == 1
    assert sum(not result["payload"]["reused"] for result in results) == 1
    assert sum(result["payload"]["reused"] for result in results) == 3
    assert len(json.loads(draft_path.read_text(encoding="utf-8"))["drafts"]) == 1


def test_build_service_uses_injected_model_and_preserves_formal_stores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    glossary = project_root / "data" / "poetry_glossary.json"
    knowledge = project_root / "output" / "assets" / "knowledge" / "poetry_knowledge.sqlite3"
    glossary.parent.mkdir(parents=True)
    knowledge.parent.mkdir(parents=True)
    glossary.write_bytes(b'{"glossaryVersion":"1.0.0","entries":[]}\n')
    with sqlite3.connect(knowledge) as connection:
        connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel VALUES ('formal')")
    before = (glossary.read_bytes(), knowledge.read_bytes())
    monkeypatch.setattr(cli, "PROJECT_ROOT", project_root)

    class FakeClient:
        model = "configured-model"

        def __init__(self, base_url: str, api_key: str, model: str) -> None:
            self.base_url = base_url
            self.api_key = api_key
            self.model = model

    monkeypatch.setattr(cli, "OpenAISelectionClient", FakeClient)
    service = cli._build_service(tmp_path / "drafts.json", {
        "AGENT_LLM_BASE_URL": "https://provider.test/v1",
        "AGENT_LLM_API_KEY": "secret",
        "AGENT_LLM_MODEL": "configured-model",
        "AGENT_KB_PATH": str(knowledge),
    })
    assert service.model_name == "configured-model"
    assert service.draft_store.path == (tmp_path / "drafts.json").resolve()
    assert (glossary.read_bytes(), knowledge.read_bytes()) == before


@pytest.mark.parametrize("kind", ["draft", "failure"])
def test_store_lock_serializes_cross_process_writers(tmp_path: Path, kind: str) -> None:
    path = tmp_path / ("drafts.json" if kind == "draft" else "batch.json")
    context = multiprocessing.get_context("spawn")
    processes = [context.Process(target=_cross_process_merge, args=(kind, str(path), index))
                 for index in range(6)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(15)
        assert not process.is_alive(), f"worker {process.pid} did not finish"
        assert process.exitcode == 0, f"worker {process.pid} failed: {process.exitcode}"
    result_path = path if kind == "draft" else path.with_name(path.name + ".failures.json")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    key = "drafts" if kind == "draft" else "failures"
    assert len(result[key]) == 6


def test_corrupt_failure_store_is_not_overwritten(tmp_path: Path) -> None:
    output = tmp_path / "drafts.json"
    failure_path = tmp_path / "drafts.json.failures.json"
    failure_path.write_text("not json", encoding="utf-8")
    input_path = write_input(tmp_path / "input.json", [selection()])
    service = DraftService(cli.GlossaryDraftStore(output))
    assert cli.run(["--input", str(input_path), "--output", str(output)], service=service) == 2
    assert failure_path.read_text(encoding="utf-8") == "not json"
