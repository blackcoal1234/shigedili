"""Read-only published glossary matching for knowledge-base poem lines."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class GlossaryEntry:
    term_id: str
    term: str
    forms: tuple[str, ...]
    definition: str
    in_context: str | None = None
    category: str | None = None
    source_note: str | None = None


@dataclass(frozen=True)
class GlossarySnapshot:
    version: str | None
    entries: tuple[GlossaryEntry, ...]
    error: str | None = None


class PoetryGlossary:
    """Load a project glossary lazily and match published terms in lines."""

    def __init__(self, project_root: Path, path: Path | None = None) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.path = (path or self.project_root / "data" / "poetry_glossary.json").resolve()
        self._identity: tuple[int, int, int] | None = None
        self._snapshot = GlossarySnapshot(None, ())

    def snapshot(self) -> GlossarySnapshot:
        try:
            stat = self.path.stat()
        except OSError:
            self._identity = None
            self._snapshot = GlossarySnapshot(
                None, (), f"词典文件不存在: {self.path}"
            )
            return self._snapshot
        identity = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
        if identity == self._identity:
            return self._snapshot
        self._identity = identity
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
            self._snapshot = self._parse(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            self._snapshot = GlossarySnapshot(None, (), f"词典读取失败: {exc}")
        return self._snapshot

    @staticmethod
    def _parse(raw: Any) -> GlossarySnapshot:
        if not isinstance(raw, Mapping):
            return GlossarySnapshot(None, (), "词典顶层必须是对象")
        version = _required_text(raw.get("glossaryVersion", raw.get("glossary_version")))
        if not version:
            return GlossarySnapshot(None, (), "词典版本不能为空")
        raw_entries = raw.get("entries")
        if not isinstance(raw_entries, list):
            return GlossarySnapshot(version, (), "词典条目必须是数组")
        entries: list[GlossaryEntry] = []
        term_ids: set[str] = set()
        all_forms: set[str] = set()
        for index, item in enumerate(raw_entries):
            if not isinstance(item, Mapping):
                return GlossarySnapshot(version, (), f"词典第 {index + 1} 条必须是对象")
            term_id = _required_text(item.get("term_id", item.get("termId")))
            if not term_id or term_id in term_ids:
                return GlossarySnapshot(version, (), "词典 term_id 必须非空且唯一")
            term_ids.add(term_id)
            raw_forms = item.get("forms")
            if not isinstance(raw_forms, list) or not raw_forms:
                return GlossarySnapshot(version, (), f"词典条目 {term_id} 的 forms 必须是非空数组")
            if any(not isinstance(form, str) or len(form.strip()) < 2 for form in raw_forms):
                return GlossarySnapshot(version, (), f"词典条目 {term_id} 的 form 必须是至少 2 个字符的字符串")
            forms = [form.strip() for form in raw_forms]
            if any(form in all_forms for form in forms) or len(set(forms)) != len(forms):
                return GlossarySnapshot(version, (), "词典 forms 不得重复")
            all_forms.update(forms)
            definition = _required_text(item.get("definition"))
            in_context = _required_text(item.get("in_context", item.get("inContext")))
            category = _required_text(item.get("category"))
            source_note = _required_text(item.get("source_note", item.get("sourceNote")))
            status = _required_text(item.get("status"))
            if not all((definition, in_context, category, source_note, status)):
                return GlossarySnapshot(version, (), f"词典条目 {term_id} 缺少必填文本字段")
            source_url = item.get("source_url", item.get("sourceUrl", ""))
            if not isinstance(source_url, str):
                return GlossarySnapshot(version, (), f"词典条目 {term_id} 的 source_url 必须是字符串")
            if status != "published":
                continue
            entries.append(
                GlossaryEntry(
                    term_id=term_id,
                    term=forms[0],
                    forms=tuple(forms),
                    definition=definition,
                    in_context=in_context,
                    category=category,
                    source_note=source_note,
                )
            )
        return GlossarySnapshot(version, tuple(entries))

    def match_lines(self, lines: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        snapshot = self.snapshot()
        glosses: list[dict[str, Any]] = []
        for line in lines:
            text = str(line.get("text") or "")
            line_no = int(line.get("lineNo", line.get("line_no", 0)))
            cursor = 0
            while cursor < len(text):
                candidates = (
                    (entry, form)
                    for entry in snapshot.entries
                    for form in entry.forms
                    if text.startswith(form, cursor)
                )
                matched = max(candidates, key=lambda pair: len(pair[1]), default=None)
                if matched is None:
                    cursor += 1
                    continue
                entry, matched_form = matched
                start = cursor
                end = start + len(matched_form)
                glosses.append(
                    {
                        "termId": entry.term_id,
                        "term": entry.term,
                        "lineNo": line_no,
                        "startOffset": start,
                        "endOffset": end,
                        "definition": entry.definition,
                        "inContext": entry.in_context,
                        "category": entry.category,
                        "sourceNote": entry.source_note,
                    }
                )
                cursor = end
        return glosses


def _required_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
