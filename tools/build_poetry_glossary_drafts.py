#!/usr/bin/env python3
"""Build resumable glossary drafts from JSON or JSONL selections."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = PROJECT_ROOT / "apps" / "agent-ui" / "agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from poetry_agent.selection_glossary import (  # noqa: E402
    GlossaryDraftStore,
    GlossaryDraftStoreError,
    OpenAICompatibleGlossaryClient,
)

REQUIRED_FIELDS = ("poemId", "lineNo", "startOffset", "endOffset", "mode")
_FAILURE_LOCK = threading.Lock()


class InputError(ValueError):
    """The batch input is malformed."""


class BatchFailureStore:
    """Persist resumable batch failures without touching the core draft store."""

    def __init__(self, draft_path: Path) -> None:
        resolved = Path(draft_path).expanduser().resolve()
        self.path = resolved.with_name(resolved.name + ".failures.json")

    @property
    def lock_path(self) -> Path:
        return self.path.with_name(self.path.name + ".lock")

    @contextmanager
    def _locked(self) -> Any:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _FAILURE_LOCK, self.lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def merge(self, records: Iterable[Mapping[str, Any]]) -> None:
        with self._locked():
            failures: dict[str, dict[str, Any]] = {}
            if self.path.is_file():
                try:
                    loaded = json.loads(self.path.read_text(encoding="utf-8-sig"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise GlossaryDraftStoreError("批处理失败记录损坏或无法读取") from exc
                if not isinstance(loaded, Mapping) or not isinstance(
                    loaded.get("failures"), list
                ):
                    raise GlossaryDraftStoreError("批处理失败记录结构无效")
                for item in loaded["failures"]:
                    if isinstance(item, Mapping) and isinstance(
                        item.get("selectionId"), str
                    ):
                        failures[item["selectionId"]] = dict(item)

            for item in records:
                selection_id = item.get("selectionId")
                if not isinstance(selection_id, str) or not selection_id:
                    continue
                if item.get("status") == "failed":
                    failures[selection_id] = dict(item)
                elif item.get("status") == "draft":
                    failures.pop(selection_id, None)
            output = {
                "version": 1,
                "failures": sorted(
                    failures.values(), key=lambda item: item["selectionId"]
                ),
            }
            temp = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
            try:
                temp.write_text(
                    json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                os.replace(temp, self.path)
            finally:
                temp.unlink(missing_ok=True)


class OpenAISelectionClient(OpenAICompatibleGlossaryClient):
    """CLI name for the backend client implementing explain(context=..., mode=...)."""


def _selection_id(item: Mapping[str, Any]) -> str:
    from hashlib import sha256

    identity = json.dumps(
        [item.get(field) for field in REQUIRED_FIELDS],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "gloss-selection-" + sha256(identity.encode("utf-8")).hexdigest()[:24]


def _validate_item(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise InputError(f"第 {index} 条必须是对象")
    missing = [field for field in REQUIRED_FIELDS if field not in raw]
    if missing:
        raise InputError(f"第 {index} 条缺少字段: {', '.join(missing)}")
    item = {field: raw[field] for field in REQUIRED_FIELDS}
    if not isinstance(item["poemId"], str) or not item["poemId"].strip():
        raise InputError(f"第 {index} 条 poemId 必须是非空字符串")
    item["poemId"] = item["poemId"].strip()
    for field in ("lineNo", "startOffset", "endOffset"):
        if isinstance(item[field], bool) or not isinstance(item[field], int):
            raise InputError(f"第 {index} 条 {field} 必须是整数")
    if item["lineNo"] < 1 or item["startOffset"] < 0 or item["endOffset"] <= item["startOffset"]:
        raise InputError(f"第 {index} 条行号或偏移无效")
    if item["mode"] not in {"model", "web"}:
        raise InputError(f"第 {index} 条 mode 必须是 model 或 web")
    return item


def load_input(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise InputError(f"无法读取输入: {exc}") from exc
    if not text.strip():
        raise InputError("输入为空")
    try:
        decoded = json.loads(text)
        raw_items = decoded if isinstance(decoded, list) else [decoded]
    except json.JSONDecodeError:
        raw_items = []
        for line_no, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                raw_items.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise InputError(f"JSONL 第 {line_no} 行无效: {exc.msg}") from exc
    if limit is not None:
        raw_items = raw_items[:limit]
    if not raw_items:
        raise InputError("输入没有可处理记录")
    return [_validate_item(item, index) for index, item in enumerate(raw_items, 1)]


def _build_service(output: Path, env: Mapping[str, str]) -> Any:
    from poetry_agent.config import Settings
    from poetry_agent.glossary import PoetryGlossary
    from poetry_agent.knowledge import PoetryKnowledgeRepository
    from poetry_agent.selection_glossary import SelectionGlossaryService

    settings = Settings.from_env(env, project_root=PROJECT_ROOT)
    if not settings.model_configured:
        raise RuntimeError("缺少模型配置: " + ", ".join(settings.missing_model_settings))
    client = OpenAISelectionClient(
        settings.llm_base_url, settings.llm_api_key, settings.llm_model
    )
    repository = PoetryKnowledgeRepository(settings.resolved_knowledge_base_path)
    glossary = PoetryGlossary(PROJECT_ROOT)
    return SelectionGlossaryService(
        repository,
        glossary,
        model_client=client,
        draft_store=GlossaryDraftStore(output),
        model_name=settings.llm_model,
    )


def _process(service: Any, item: Mapping[str, Any]) -> dict[str, Any]:
    selection_id = _selection_id(item)
    request = dict(item)
    try:
        response = service.explain(
            poem_id=item["poemId"],
            line_no=item["lineNo"],
            start_offset=item["startOffset"],
            end_offset=item["endOffset"],
            mode=item["mode"],
        )
        payload = response.get("payload") if isinstance(response, Mapping) else None
        if (
            not isinstance(response, Mapping)
            or response.get("status") != "ok"
            or not isinstance(payload, Mapping)
            or payload.get("reviewStatus") != "draft"
        ):
            note = None
            if isinstance(payload, Mapping):
                note = payload.get("error") or payload.get("sourceNote")
            if not note and isinstance(response, Mapping):
                note = response.get("methodNote")
            return {
                "selectionId": selection_id,
                "status": "failed",
                "request": request,
                "error": str(note or "未生成草稿"),
            }
        return {
            "selectionId": selection_id,
            "draftId": payload.get("draftId"),
            "status": "draft",
            "request": request,
            "result": dict(payload),
        }
    except Exception as exc:
        return {
            "selectionId": selection_id,
            "status": "failed",
            "request": request,
            "error": f"批处理调用失败: {type(exc).__name__}",
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/poetry_glossary_drafts.json"))
    parser.add_argument("--concurrency", type=int, default=16, choices=range(1, 65), metavar="1..64")
    parser.add_argument("--limit", type=int)
    return parser


def run(
    argv: Sequence[str] | None = None,
    *,
    service: Any | None = None,
    env: Mapping[str, str] | None = None,
    service_factory: Callable[[Path, Mapping[str, str]], Any] = _build_service,
) -> int:
    args = build_parser().parse_args(argv)
    if args.limit is not None and args.limit < 1:
        print("错误: --limit 必须是正整数", file=sys.stderr)
        return 2
    try:
        items = load_input(args.input, args.limit)
        active_service = service or service_factory(args.output, os.environ if env is None else env)
    except (InputError, RuntimeError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2

    records: list[dict[str, Any]] = []
    failure_store = BatchFailureStore(args.output)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = [pool.submit(_process, active_service, item) for item in items]
            for future in concurrent.futures.as_completed(futures):
                record = future.result()
                failure_store.merge([record])
                records.append(record)
    except GlossaryDraftStoreError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    succeeded = sum(record["status"] == "draft" for record in records)
    failed = len(records) - succeeded
    print(f"完成: draft={succeeded} failed={failed} output={args.output}")
    return 1 if succeeded == 0 else 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
