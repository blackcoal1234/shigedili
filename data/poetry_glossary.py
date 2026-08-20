"""Shared local glossary loading and exact longest-match helpers."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class GlossaryEntry:
    term_id: str
    term: str
    definition: str
    in_context: str
    category: str
    source_note: str
    source_url: str = ""


@dataclass(frozen=True)
class GlossaryMatch:
    entry: GlossaryEntry
    start: int
    end: int


def load_glossary(path: Path) -> tuple[str, tuple[GlossaryEntry, ...]]:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("glossary must be an object")
    version = _required_text(raw.get("glossaryVersion", raw.get("glossary_version")))
    if not version:
        raise ValueError("glossary version must be nonempty")
    raw_entries = raw.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("glossary entries must be a list")
    entries: list[GlossaryEntry] = []
    term_ids: set[str] = set()
    all_forms: set[str] = set()
    for item in raw_entries:
        if not isinstance(item, dict):
            raise ValueError("glossary entry must be an object")
        term_id = _required_text(item.get("term_id", item.get("termId")))
        definition = _required_text(item.get("definition"))
        in_context = _required_text(item.get("in_context", item.get("inContext")))
        category = _required_text(item.get("category"))
        source_note = _required_text(item.get("source_note", item.get("sourceNote")))
        status = _required_text(item.get("status"))
        if not term_id or term_id in term_ids:
            raise ValueError("glossary term_id must be nonempty and unique")
        term_ids.add(term_id)
        forms = item.get("forms")
        if not isinstance(forms, list) or not forms:
            raise ValueError(f"glossary entry {term_id} forms must be a nonempty list")
        if any(not isinstance(form, str) or len(form.strip()) < 2 for form in forms):
            raise ValueError(f"glossary entry {term_id} forms must contain strings of at least 2 characters")
        normalized_forms = [form.strip() for form in forms]
        if any(form in all_forms for form in normalized_forms) or len(set(normalized_forms)) != len(normalized_forms):
            raise ValueError("glossary forms must be unique")
        all_forms.update(normalized_forms)
        if not all((definition, in_context, category, source_note, status)):
            raise ValueError(f"glossary entry {term_id} is missing required text")
        source_url = item.get("source_url", item.get("sourceUrl", ""))
        if not isinstance(source_url, str):
            raise ValueError(f"glossary entry {term_id} source_url must be a string")
        if status != "published":
            continue
        for term in normalized_forms:
            entries.append(
                GlossaryEntry(
                    term_id=term_id,
                    term=term,
                    definition=definition,
                    in_context=in_context,
                    category=category,
                    source_note=source_note,
                    source_url=source_url.strip(),
                )
            )
    return version, tuple(entries)


def match_text(text: str, entries: Iterable[GlossaryEntry]) -> list[GlossaryMatch]:
    ordered = tuple(entries)
    matches: list[GlossaryMatch] = []
    cursor = 0
    while cursor < len(text):
        candidates = (entry for entry in ordered if text.startswith(entry.term, cursor))
        entry = max(candidates, key=lambda candidate: len(candidate.term), default=None)
        match = None if entry is None else GlossaryMatch(entry, cursor, cursor + len(entry.term))
        if match is None:
            cursor += 1
            continue
        matches.append(match)
        cursor = match.end
    return matches


def _required_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def glossary_map(entries: Iterable[GlossaryEntry]) -> dict[str, dict[str, str]]:
    return {
        entry.term_id: {
            "termId": entry.term_id,
            "term": entry.term,
            "definition": entry.definition,
            "inContext": entry.in_context,
            "category": entry.category,
            "sourceNote": entry.source_note,
            "sourceUrl": entry.source_url,
        }
        for entry in entries
    }


def glossed_html(text: str, entries: Iterable[GlossaryEntry]) -> str:
    out: list[str] = []
    cursor = 0
    for match in match_text(text, entries):
        out.append(escape(text[cursor:match.start]))
        out.append(
            '<button type="button" class="gloss-term" '
            f'data-gloss-id="{escape(match.entry.term_id, quote=True)}" '
            f'aria-label="{escape(match.entry.term, quote=True)}">'
            f"{escape(text[match.start:match.end])}</button>"
        )
        cursor = match.end
    out.append(escape(text[cursor:]))
    return "".join(out)
