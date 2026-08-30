# -*- coding: utf-8 -*-
"""诗页译注赏析按需生成服务：查询已有（手写/LLM 层）或现场生成单首。

设计动机：全量批量生成耗时且非必需——读者在赏析诗页（44_诗页.html）打开一首
尚无译注赏析的诗时，前端按钮调用本服务，按需生成、当场返回、服务端留档；
留档默认写入 data/llm_rich_backgrounds/batch_auto_001.json，也可通过
AGENT_RICH_GUIDE_DIR 写入 release 外的持久目录；下次重建管线即进入正式数据层
（徽章「模型生成 · 非人工考据」，手写层仍优先）。

质量门禁与批量工具（tools/build_rich_guides_llm.py）完全同一套：
原句与正文逐字一致（不一致自动重试一次，仍不过则拒绝返回）、story 100–260 字、
注释≥2、赏析≥1；无 Key 时明确返回 unavailable，不做任何静默降级。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_AUTO_BATCH_THREAD_LOCK = threading.Lock()
_POEM_THREAD_LOCKS_GUARD = threading.Lock()
_POEM_THREAD_LOCKS: dict[str, tuple[threading.Lock, int]] = {}
_EVIDENCE_PROMPT_VERSION = "rich_guide_v2_evidence"
_RICH_GUIDE_DIR_ENV = "AGENT_RICH_GUIDE_DIR"
_AUTO_BATCH_NOTE = (
    "由 LLM 按需生成（CLI --poem-id 或 /knowledge/rich-guide），输入事实锚定三层"
    "作年作地，原句经逐字校验；待人工复核，非人工考据。"
)


@contextmanager
def _cross_process_file_lock(lock_path: Path):
    """Hold one byte of ``lock_path`` exclusively until the context exits."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _exclusive_batch_lock(batch_path: Path):
    """Serialize the shared auto batch across threads and OS processes."""
    batch_path = Path(batch_path)
    lock_path = batch_path.with_name(batch_path.name + ".lock")
    with _AUTO_BATCH_THREAD_LOCK, _cross_process_file_lock(lock_path):
        yield


def _poem_lock_path(lock_scope: Path, poem_id: str) -> Path:
    """Return a stable, repository-external lock path for one poem."""
    normalized_scope = os.path.normcase(str(Path(lock_scope).resolve()))
    scope_key = hashlib.sha256(normalized_scope.encode("utf-8")).hexdigest()[:24]
    poem_key = hashlib.sha256(poem_id.encode("utf-8")).hexdigest()
    return (
        Path(tempfile.gettempdir())
        / "poetry-rich-guide-singleflight"
        / scope_key
        / f"{poem_key}.lock"
    )


@contextmanager
def _exclusive_poem_lock(lock_scope: Path, poem_id: str):
    """Serialize one poem across service instances, threads, and processes.

    The registry guard is held only while borrowing/releasing a keyed thread
    lock. LLM work for different poem IDs therefore remains concurrent. The
    file lock extends the same key across worker processes. ``lock_scope`` is
    the configured archive directory, so releases sharing storage also share
    the single-flight lock.
    """
    lock_path = _poem_lock_path(lock_scope, poem_id)
    lock_key = str(lock_path)
    with _POEM_THREAD_LOCKS_GUARD:
        entry = _POEM_THREAD_LOCKS.get(lock_key)
        if entry is None:
            thread_lock = threading.Lock()
            references = 1
        else:
            thread_lock, references = entry
            references += 1
        _POEM_THREAD_LOCKS[lock_key] = (thread_lock, references)

    try:
        with thread_lock, _cross_process_file_lock(lock_path):
            yield
    finally:
        with _POEM_THREAD_LOCKS_GUARD:
            current_lock, references = _POEM_THREAD_LOCKS[lock_key]
            if references == 1:
                del _POEM_THREAD_LOCKS[lock_key]
            else:
                _POEM_THREAD_LOCKS[lock_key] = (current_lock, references - 1)


def persist_auto_item(batch_path: Path, item: dict[str, Any]) -> Path:
    """Merge one item into the shared auto batch under a cross-process lock."""
    batch_path = Path(batch_path)
    audit = item.get("audit") if isinstance(item.get("audit"), dict) else {}
    generated_at = str(audit.get("generated_at") or "")
    written_at = (
        generated_at[:10]
        if len(generated_at) >= 10
        else datetime.now(timezone.utc).date().isoformat()
    )
    with _exclusive_batch_lock(batch_path):
        if batch_path.exists():
            payload = json.loads(batch_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                raise ValueError(f"自动译注批次结构无效：{batch_path}")
            payload["items"] = [
                existing
                for existing in payload["items"]
                if isinstance(existing, dict)
                and existing.get("poem_id") != item["poem_id"]
            ]
        else:
            payload = {
                "batch": batch_path.stem,
                "writer": f"llm:{audit.get('model') or 'unknown'}",
                "written_at": written_at,
                "note": _AUTO_BATCH_NOTE,
                "prompt_version": str(audit.get("prompt_version") or "unknown"),
                "items": [],
            }
        payload["items"].append(item)
        payload["items"].sort(
            key=lambda existing: (
                str(existing.get("poet") or ""),
                str(existing.get("title") or ""),
            )
        )
        payload["written_at"] = written_at
        audits = [
            existing.get("audit") if isinstance(existing.get("audit"), dict) else {}
            for existing in payload["items"]
            if isinstance(existing, dict)
        ]
        prompt_versions = sorted(
            {str(existing_audit.get("prompt_version") or "unknown") for existing_audit in audits}
            or {"unknown"}
        )
        models = sorted(
            {str(existing_audit.get("model") or "unknown") for existing_audit in audits}
            or {"unknown"}
        )
        payload["prompt_versions"] = prompt_versions
        payload["models"] = models
        payload["prompt_version"] = (
            prompt_versions[0] if len(prompt_versions) == 1 else "mixed"
        )
        payload["writer"] = f"llm:{models[0] if len(models) == 1 else 'mixed'}"

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=batch_path.parent,
                prefix=f".{batch_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
                )
            temporary_path.replace(batch_path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
    return batch_path


class RichGuideError(RuntimeError):
    def __init__(self, status_code: int, payload: dict[str, Any]):
        super().__init__(payload.get("reason", status_code))
        self.status_code = status_code
        self.payload = payload


class RichGuideService:
    def __init__(
        self,
        project_root: Path,
        *,
        base_url: str,
        api_key: str,
        model: str,
        kb_path: Path | None = None,
    ):
        self.root = project_root
        self.kb_path = (
            kb_path
            if kb_path is not None
            else project_root
            / "output"
            / "assets"
            / "knowledge"
            / "poetry_knowledge.sqlite3"
        )
        self.hand_dir = project_root / "data" / "assistant_rich_backgrounds"
        self.release_llm_dir = project_root / "data" / "llm_rich_backgrounds"
        configured_llm_dir = os.environ.get(_RICH_GUIDE_DIR_ENV, "").strip()
        self.llm_dir = (
            Path(configured_llm_dir).expanduser().resolve()
            if configured_llm_dir
            else self.release_llm_dir
        )
        self._llm_read_dirs = (self.release_llm_dir,)
        if os.path.normcase(str(self.llm_dir.resolve())) != os.path.normcase(
            str(self.release_llm_dir.resolve())
        ):
            self._llm_read_dirs += (self.llm_dir,)
        self.config = {
            "base_url": base_url.strip(),
            "api_key": api_key.strip(),
            "model": model.strip(),
            "concurrency": 1,
        }

    # ---------- 查询 ----------

    def load_poem(self, poem_id: str) -> dict[str, Any] | None:
        if not self.kb_path.exists():
            raise RichGuideError(503, {"status": "unavailable", "reason": "knowledge_base_missing"})
        db = sqlite3.connect(f"file:{self.kb_path}?mode=ro", uri=True, timeout=30)
        db.row_factory = sqlite3.Row
        cursor = db.execute(
            "SELECT poem_id, title, poet, dynasty, body, body_hash FROM poems WHERE poem_id = ?",
            (poem_id,),
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
            db.close()
        return dict(row) if row else None

    def find_existing(self, poem_id: str) -> dict[str, Any] | None:
        if self.hand_dir.exists():
            for batch in sorted(self.hand_dir.glob("batch_*.json")):
                try:
                    payload = json.loads(batch.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                for item in payload.get("items") or []:
                    if isinstance(item, dict) and str(item.get("poem_id") or "") == poem_id:
                        return {
                            "status": "exists",
                            "source": "hand",
                            "batch": str(payload.get("batch") or batch.stem),
                            "item": _public_item(item, "hand"),
                        }

        best: tuple[tuple[int, str, int, int, int], dict[str, Any]] | None = None
        for directory_index, llm_dir in enumerate(self._llm_read_dirs):
            if not llm_dir.exists():
                continue
            for batch_index, batch in enumerate(sorted(llm_dir.glob("batch_*.json"))):
                try:
                    payload = json.loads(batch.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                for item_index, item in enumerate(payload.get("items") or []):
                    if not isinstance(item, dict) or str(item.get("poem_id") or "") != poem_id:
                        continue
                    audit = item.get("audit") if isinstance(item.get("audit"), dict) else {}
                    mode = audit.get("reference_mode")
                    prompt_version = str(audit.get("prompt_version") or "")
                    if (
                        mode == "reviewed_references"
                        and prompt_version == "rich_guide_v2_evidence"
                    ):
                        constraint_rank = 3
                    elif mode == "poem_only" and prompt_version == "rich_guide_v2_evidence":
                        constraint_rank = 2
                    else:
                        constraint_rank = 1
                    rank = (
                        constraint_rank,
                        str(audit.get("generated_at") or ""),
                        directory_index,
                        batch_index,
                        item_index,
                    )
                    candidate = {
                        "status": "exists",
                        "source": "llm",
                        "batch": str(payload.get("batch") or batch.stem),
                        "item": _public_item(item, "llm"),
                    }
                    if best is None or rank > best[0]:
                        best = (rank, candidate)
        return best[1] if best else None

    # ---------- 生成 ----------

    def _tool_module(self):
        project_tools = self.root / "tools"
        source_tools = Path(__file__).resolve().parents[4] / "tools"
        tools_dir = str(project_tools if project_tools.exists() else source_tools)
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import build_rich_guides_llm as rg  # noqa: PLC0415  延迟导入，避免进程启动即加载

        return rg

    def _resolve_fact(self, poem: dict[str, Any]) -> dict[str, Any] | None:
        rg = self._tool_module()
        ppd = rg.ppd
        digest = poem.get("body_hash") or ""
        verified = ppd.load_approved_backgrounds()
        rule = ppd.load_promoted_facts(ppd.RULE_JSONL, "rule")
        ai = ppd.load_promoted_facts(ppd.AI_JSONL, "ai")
        for layer in (verified, rule, ai):
            if digest and digest in layer:
                return {k: v for k, v in layer[digest].items() if k in ("tier", "ys", "ye", "hp", "mp")}
        return None

    def generate(self, poem_id: str) -> dict[str, Any]:
        existing = self.find_existing(poem_id)
        if existing:
            return existing

        # The first lookup keeps the common cached path lock-free. Every
        # contender that misses it then joins this poem's single-flight. The
        # winner persists atomically before releasing the lock; followers see
        # that archive in this required second lookup and do not call the LLM.
        with _exclusive_poem_lock(self.llm_dir, poem_id):
            existing = self.find_existing(poem_id)
            if existing:
                return existing
            return self._generate_missing(poem_id)

    def _generate_missing(self, poem_id: str) -> dict[str, Any]:
        """Generate and persist a poem while its single-flight lock is held."""
        poem = self.load_poem(poem_id)
        if poem is None:
            raise RichGuideError(404, {"status": "not_found", "reason": "poem_id 不在知识库"})

        setting_names = {
            "base_url": "AGENT_LLM_BASE_URL",
            "api_key": "AGENT_LLM_API_KEY",
            "model": "AGENT_LLM_MODEL",
        }
        missing = [name for key, name in setting_names.items() if not self.config[key]]
        if missing:
            raise RichGuideError(
                503,
                {"status": "unavailable", "reason": "missing_env", "missing": missing},
            )

        rg = self._tool_module()
        fact = self._resolve_fact(poem)
        references = rg.load_references(
            self.root / "data" / "reviewed" / "poem_appreciation_references.json",
            poem.get("body_hash") or "",
        )
        prompt = rg.build_prompt(
            poem["title"], poem["poet"], poem["dynasty"], poem["body"], fact, references
        )
        errors: list[str] = []
        result: dict[str, Any] | None = None
        for _attempt in range(2):  # 首次 + 带错误信息重试一次
            try:
                result = rg.request_llm(
                    self.config,
                    prompt
                    + ("\n\n【上次输出的问题，必须修正】" + "；".join(errors) if errors else ""),
                )
            except RuntimeError as exc:
                raise RichGuideError(502, {"status": "upstream_error", "reason": str(exc)[:400]}) from exc
            errors = rg.validate_item(result, poem["body"], fact, references)
            if not errors:
                break
        if errors:
            raise RichGuideError(422, {"status": "quality_failed", "errors": errors[:5]})

        item = rg.package_generated_item(
            result,
            poem,
            fact,
            references,
            self.config["model"],
            {
                "via": "api",
                "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
        batch_name = self._persist(item)
        return {"status": "generated", "source": "llm", "batch": batch_name, "item": _public_item(item, "llm")}

    def _persist(self, item: dict[str, Any]) -> str:
        """留档到配置的 llm_rich_backgrounds 目录（单个累积文件）。"""
        path = persist_auto_item(self.llm_dir / "batch_auto_001.json", item)
        return path.stem


def _public_item(item: dict[str, Any], source: str) -> dict[str, Any]:
    """给前端的条目：与诗页 ag 结构一致（hw=false → 徽章「模型生成」）。"""
    audit = item.get("audit") if isinstance(item.get("audit"), dict) else {}
    raw_reference_mode = str(audit.get("reference_mode") or "")
    prompt_version = str(audit.get("prompt_version") or "")
    if (
        source == "llm"
        and prompt_version == _EVIDENCE_PROMPT_VERSION
        and raw_reference_mode in {"reviewed_references", "poem_only"}
    ):
        reference_mode = raw_reference_mode
    elif source == "llm":
        reference_mode = "legacy_unconstrained"
    else:
        reference_mode = None
    facts_anchor = (
        item.get("facts_anchor") if isinstance(item.get("facts_anchor"), dict) else {}
    )
    tier = facts_anchor.get("tier")
    anchor_tier = tier if tier in {"verified", "rule", "ai", "none"} else "none"
    public_sources = []
    raw_sources = item.get("sources") if reference_mode == "reviewed_references" else []
    for raw_source in raw_sources if isinstance(raw_sources, list) else []:
        if not isinstance(raw_source, dict):
            continue
        reference_id = raw_source.get("reference_id")
        name = raw_source.get("name")
        url = raw_source.get("url")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (reference_id, name, url)
        ):
            continue
        clean_reference_id = reference_id.strip()
        clean_url = url.strip()
        if not clean_reference_id.startswith("R") or not clean_url.startswith("https://"):
            continue
        public_sources.append(
            {
                "reference_id": clean_reference_id,
                "name": name.strip(),
                "url": clean_url,
            }
        )
    return {
        "poem_id": item.get("poem_id"),
        "story": item.get("story") or "",
        "notes": [
            {
                "original": str(n.get("original") or ""),
                "translation": str(n.get("translation") or ""),
                "annotations": [str(a) for a in (n.get("annotations") or []) if a],
            }
            for n in (item.get("line_notes") or [])
            if isinstance(n, dict)
        ],
        "ap": [str(x) for x in (item.get("appreciation_points") or []) if str(x).strip()],
        "batch": audit.get("via") == "api" and "auto" or None,
        "hw": source == "hand",
        "anchor_tier": anchor_tier,
        "sources": public_sources,
        **({"reference_mode": reference_mode} if source == "llm" else {}),
    }
