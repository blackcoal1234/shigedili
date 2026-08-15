"""Build the 88-poet history-collection candidate-layer summary.

This module only aggregates existing candidate/reference evidence.  It never
promotes a row into ``data/reviewed`` and it deliberately keeps manual leads
separate from structured person-event candidates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_JSON = ROOT / "data" / "candidates" / "poet_history_collection_summary.json"
OUTPUT_DOC = ROOT / "docs" / "poet-history-collection-summary.md"

SCOPE_NOTE = "当前可检索快照，非历史全集；全部记录仍处于候选/参考层，未经审核不得作为确定路线。"
MAIN_SOURCES = ("cbdb", "cnkgraph", "souyun")
MANUAL_STATUSES = {"event_candidate", "clue_only", "lead_only", "needs_manual_review", "no_new_evidence"}
REQUIRED_INPUTS = {
    "poems": "data/poems.json",
    "events": "data/candidates/journey_event_candidates.jsonl",
    "works": "data/candidates/work_chronology_supplements.jsonl",
    "source_status": "data/candidates/journey_source_status.jsonl",
    "source_coverage": "data/candidates/journey_source_coverage.json",
    "biographies": "data/candidates/poet_reference_biographies.jsonl",
    "kanripo": "data/candidates/poet_kanripo_catalog_matches.jsonl",
    "gap_backlog": "data/candidates/poet_journey_gap_backlog.json",
    "manual_tang": "data/candidates/manual_source_evidence_tang_zero_event.jsonl",
    "manual_song": "data/candidates/manual_source_evidence_song_zero_event.jsonl",
    "coordinate_supplements": "data/candidates/cbdb_event_coordinate_supplements.jsonl",
}
OPTIONAL_INPUTS = {
    "dila_matches": "data/candidates/poet_dila_person_matches.jsonl",
    "dila_coverage": "data/candidates/poet_dila_person_coverage.json",
}


def canonical_json(value: object, *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def atomic_write_if_changed(path: Path, payload: bytes) -> bool:
    """Atomically replace *path* only when bytes differ; return whether written."""
    if path.exists() and path.read_bytes() == payload:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return True


def _signature(path: Path) -> tuple[int, int, int] | None:
    if not path.exists():
        return None
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, getattr(stat, "st_ino", 0)


def read_stable_bundle(
    root: Path,
    *,
    retries: int = 8,
    delay: float = 0.25,
) -> tuple[dict[str, bytes], dict[str, bool]]:
    """Read a cross-file snapshot, retrying if any input changes mid-read."""
    required = {name: root / relative for name, relative in REQUIRED_INPUTS.items()}
    missing = [str(path) for path in required.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("missing required summary inputs: " + ", ".join(missing))
    all_paths = {**required, **{name: root / rel for name, rel in OPTIONAL_INPUTS.items()}}
    for attempt in range(retries):
        before = {name: _signature(path) for name, path in all_paths.items()}
        payloads = {
            name: path.read_bytes()
            for name, path in all_paths.items()
            if before[name] is not None
        }
        after = {name: _signature(path) for name, path in all_paths.items()}
        if before == after:
            return payloads, {name: name in payloads for name in OPTIONAL_INPUTS}
        if attempt + 1 < retries:
            time.sleep(delay * (attempt + 1))
    raise RuntimeError("summary inputs changed throughout snapshot read; retry after collectors settle")


def _json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON in {label}: {exc}") from exc


def _jsonl(payload: bytes, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, raw in enumerate(payload.decode("utf-8-sig").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL in {label}:{line_no}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{label}:{line_no}: expected an object")
        rows.append(row)
    return rows


def _counter(values: Iterable[Any]) -> dict[str, int]:
    return dict(sorted(Counter(str(value or "unknown") for value in values).items()))


def _nested_counter(rows: Iterable[Mapping[str, Any]], field: str) -> dict[str, int]:
    return _counter(row.get(field) for row in rows)


def _has_coordinates(row: Mapping[str, Any]) -> bool:
    def valid(value: Any) -> bool:
        try:
            return value not in (None, "") and float(value) == float(value)
        except (TypeError, ValueError):
            return False

    return (
        valid(row.get("latitude")) and valid(row.get("longitude"))
    ) or (valid(row.get("lat")) and valid(row.get("lon")))


def _roster(poems: Any) -> list[dict[str, Any]]:
    if not isinstance(poems, list):
        raise ValueError("data/poems.json must be a JSON array")
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in poems:
        if not isinstance(row, dict):
            raise ValueError("data/poems.json contains a non-object row")
        poet = str(row.get("poet") or row.get("author") or "").strip()
        if not poet:
            raise ValueError("data/poems.json contains a row without poet/author")
        dynasty = str(row.get("dynasty") or "unknown").strip() or "unknown"
        counts[poet][dynasty] += 1
    roster = []
    for poet in sorted(counts):
        dynasty_counts = counts[poet]
        dynasty = sorted(dynasty_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        roster.append(
            {
                "poet": poet,
                "dynasty": dynasty,
                "poem_count": sum(dynasty_counts.values()),
            }
        )
    return roster


def _require_known(rows: Iterable[Mapping[str, Any]], poets: set[str], label: str) -> None:
    unknown = sorted({str(row.get("poet") or "") for row in rows if str(row.get("poet") or "") not in poets})
    if unknown:
        raise ValueError(f"{label} contains unknown/missing poets: {unknown}")


def _group(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("poet"))].append(row)
    return grouped


def _manual_kind(status: Any) -> str:
    return "event" if status == "event_candidate" else "clue"


def _dila_poet_rows(rows: list[dict[str, Any]], poet: str) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("poet") or "") == poet]


def build_summary(root: Path = ROOT, *, snapshot_retries: int = 8) -> dict[str, Any]:
    payloads, optional_presence = read_stable_bundle(root, retries=snapshot_retries)
    parsed: dict[str, Any] = {}
    for name, payload in payloads.items():
        parsed[name] = _jsonl(payload, name) if REQUIRED_INPUTS.get(name, OPTIONAL_INPUTS.get(name, "")).endswith(".jsonl") else _json(payload, name)

    roster = _roster(parsed["poems"])
    poet_names = {row["poet"] for row in roster}
    rows_by_name = {
        "events": parsed["events"],
        "works": parsed["works"],
        "source_status": parsed["source_status"],
        "biographies": parsed["biographies"],
        "kanripo": parsed["kanripo"],
        "manual_tang": parsed["manual_tang"],
        "manual_song": parsed["manual_song"],
        "coordinate_supplements": parsed["coordinate_supplements"],
    }
    if optional_presence["dila_matches"]:
        rows_by_name["dila_matches"] = parsed["dila_matches"]
    dila_coverage_rows: list[dict[str, Any]] = []
    if optional_presence["dila_coverage"]:
        dila_coverage_rows = parsed["dila_coverage"].get("per_poet", [])
        if not isinstance(dila_coverage_rows, list):
            raise ValueError("dila_coverage.per_poet must be an array")
        rows_by_name["dila_coverage"] = dila_coverage_rows
    gap_entries = parsed["gap_backlog"].get("entries", [])
    if not isinstance(gap_entries, list):
        raise ValueError("gap_backlog.entries must be an array")
    rows_by_name["gap_backlog"] = gap_entries
    for label, rows in rows_by_name.items():
        if not isinstance(rows, list):
            raise ValueError(f"{label} must be an array/JSONL collection")
        _require_known(rows, poet_names, label)

    events = parsed["events"]
    works = parsed["works"]
    statuses = parsed["source_status"]
    biographies = parsed["biographies"]
    kanripo = parsed["kanripo"]
    manual = parsed["manual_tang"] + parsed["manual_song"]
    supplements = parsed["coordinate_supplements"]
    dila_matches = parsed.get("dila_matches", [])
    unknown_manual_statuses = sorted(
        {str(row.get("candidate_status") or "") for row in manual} - MANUAL_STATUSES
    )
    if unknown_manual_statuses:
        raise ValueError(f"manual evidence contains unknown candidate_status values: {unknown_manual_statuses}")

    event_index: dict[str, dict[str, Any]] = {}
    for row in events:
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id or candidate_id in event_index:
            raise ValueError(f"person-event candidate_id is empty or duplicated: {candidate_id!r}")
        event_index[candidate_id] = row
    supplement_ids_seen: set[str] = set()
    for row in supplements:
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id or candidate_id in supplement_ids_seen:
            raise ValueError(f"coordinate supplement candidate_id is empty or duplicated: {candidate_id!r}")
        supplement_ids_seen.add(candidate_id)
        event = event_index.get(candidate_id)
        if event is None:
            raise ValueError(f"coordinate supplement does not link to a person-event: {candidate_id}")
        if str(event.get("poet") or "") != str(row.get("poet") or ""):
            raise ValueError(f"coordinate supplement poet mismatch for {candidate_id}")

    event_by_poet = _group(events)
    work_by_poet = _group(works)
    status_by_poet = _group(statuses)
    bio_by_poet = _group(biographies)
    kanripo_by_poet = _group(kanripo)
    manual_by_poet = _group(manual)
    supplement_by_poet = _group(supplements)
    dila_by_poet = _group(dila_matches)
    dila_coverage_by_poet = {str(row["poet"]): row for row in dila_coverage_rows}
    gap_by_poet = {str(row["poet"]): row for row in gap_entries}
    coverage_per_poet = parsed["source_coverage"].get("per_poet", {})
    if not isinstance(coverage_per_poet, dict):
        raise ValueError("source_coverage.per_poet must be an object")
    coverage_unknown = sorted(set(coverage_per_poet) - poet_names)
    if coverage_unknown:
        raise ValueError(f"source_coverage contains unknown poets: {coverage_unknown}")
    coverage_missing = sorted(poet_names - set(coverage_per_poet))
    if coverage_missing:
        raise ValueError(f"source_coverage is missing poets: {coverage_missing}")

    poets_out: list[dict[str, Any]] = []
    for roster_row in roster:
        poet = roster_row["poet"]
        poet_events = event_by_poet.get(poet, [])
        poet_works = work_by_poet.get(poet, [])
        poet_manual = manual_by_poet.get(poet, [])
        poet_supplements = supplement_by_poet.get(poet, [])
        supplement_ids = {str(row.get("candidate_id") or "") for row in poet_supplements}
        direct_ids = {str(row.get("candidate_id") or "") for row in poet_events if _has_coordinates(row)}
        all_locatable_ids = direct_ids | supplement_ids

        status_lookup: dict[str, dict[str, Any]] = {}
        for row in status_by_poet.get(poet, []):
            source = str(row.get("source") or "")
            if source in MAIN_SOURCES:
                if source in status_lookup:
                    raise ValueError(f"duplicate source status for {poet}/{source}")
                status_lookup[source] = row
        main_sources: dict[str, Any] = {}
        for source in MAIN_SOURCES:
            source_events = [row for row in poet_events if row.get("source") == source]
            source_works = [row for row in poet_works if row.get("source") == source]
            status_row = status_lookup.get(source, {})
            coverage_row = coverage_per_poet.get(poet, {}).get(source, {})
            main_sources[source] = {
                "status": str(status_row.get("status") or coverage_row.get("status") or "missing_status"),
                "candidate_count": len(source_events) + len(source_works),
                "event_candidate_count": len(source_events),
                "work_candidate_count": len(source_works),
                "reported_candidate_count": int(status_row.get("candidates") or 0),
                "identity_status": str(status_row.get("identity_status") or ""),
                "reviewable_candidate_count": int(coverage_row.get("reviewable_candidates") or 0),
                "stale_candidate_count": int(coverage_row.get("stale_candidate_count") or 0),
            }

        bio_rows = bio_by_poet.get(poet, [])
        kr_rows = kanripo_by_poet.get(poet, [])
        dila_rows = dila_by_poet.get(poet, [])
        dila_coverage_row = dila_coverage_by_poet.get(poet, {}).get("dila", {})
        gap = gap_by_poet.get(poet)
        manual_event_count = sum(_manual_kind(row.get("candidate_status")) == "event" for row in poet_manual)
        poets_out.append(
            {
                **roster_row,
                "main_sources": main_sources,
                "person_events": {
                    "candidate_count": len(poet_events),
                    "direct_locatable_count": len(direct_ids),
                    "coordinate_supplement_count": len(poet_supplements),
                    "locatable_count": len(all_locatable_ids),
                    "unlocated_count": len(poet_events) - len(all_locatable_ids),
                    "by_source": _nested_counter(poet_events, "source"),
                    "by_grade": _nested_counter(poet_events, "source_grade"),
                },
                "work_chronology": {
                    "candidate_count": len(poet_works),
                    "by_source": _nested_counter(poet_works, "source"),
                    "by_grade": _nested_counter(poet_works, "source_grade"),
                },
                "references": {
                    "biography": {
                        "record_count": len(bio_rows),
                        "match_status": _nested_counter(bio_rows, "match_status"),
                    },
                    "kanripo": {
                        "record_count": len(kr_rows),
                        "match_status": _nested_counter(kr_rows, "match_status"),
                    },
                    "dila": {
                        "available": optional_presence["dila_matches"] or optional_presence["dila_coverage"],
                        "record_count": len(dila_rows),
                        "match_status": _nested_counter(dila_rows, "match_status"),
                        "collection_status": str(dila_coverage_row.get("status") or "not_available"),
                        "active_status": str(dila_coverage_row.get("active_status") or "not_available"),
                        "reported_candidate_count": int(dila_coverage_row.get("candidate_count") or 0),
                    },
                },
                "manual_evidence": {
                    "record_count": len(poet_manual),
                    "event_candidate_count": manual_event_count,
                    "clue_count": len(poet_manual) - manual_event_count,
                    "by_status": _nested_counter(poet_manual, "candidate_status"),
                    "by_grade": _nested_counter(poet_manual, "fact_grade"),
                },
                "gap": {
                    "listed": gap is not None,
                    "status": str(gap.get("status") if gap else "no_recorded_gap"),
                    "gap_type": str(gap.get("gap_type") if gap else ""),
                    "priority": str(gap.get("priority") if gap else ""),
                },
            }
        )

    main_status_distribution = {
        source: _counter(
            poet["main_sources"][source]["status"] for poet in poets_out
        )
        for source in MAIN_SOURCES
    }
    direct_ids_global = {str(row.get("candidate_id") or "") for row in events if _has_coordinates(row)}
    supplement_ids_global = {str(row.get("candidate_id") or "") for row in supplements}
    manual_events = sum(_manual_kind(row.get("candidate_status")) == "event" for row in manual)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": "",
        "scope_note": SCOPE_NOTE,
        "candidate_layer_boundary": {
            "reviewed_data_included": False,
            "manual_evidence_promoted": False,
            "route_claims_created": False,
        },
        "input_availability": {
            **{name: True for name in REQUIRED_INPUTS},
            **optional_presence,
        },
        "totals": {
            "poets": len(roster),
            "poems": sum(row["poem_count"] for row in roster),
            "main_source_status_rows": len(statuses),
            "person_event_candidates": len(events),
            "direct_locatable_person_events": len(direct_ids_global),
            "coordinate_supplements": len(supplements),
            "locatable_person_events": len(direct_ids_global | supplement_ids_global),
            "unlocated_person_events": len(events) - len(direct_ids_global | supplement_ids_global),
            "work_chronology_candidates": len(works),
            "main_candidates": len(events) + len(works),
            "biography_reference_records": len(biographies),
            "kanripo_reference_records": len(kanripo),
            "dila_reference_records": len(dila_matches),
            "manual_evidence_records": len(manual),
            "manual_event_candidates": manual_events,
            "manual_clues": len(manual) - manual_events,
            "gap_backlog_poets": len(gap_entries),
        },
        "distributions": {
            "main_source_status": main_status_distribution,
            "person_event_source": _nested_counter(events, "source"),
            "person_event_grade": _nested_counter(events, "source_grade"),
            "person_event_status": _nested_counter(events, "status"),
            "work_source": _nested_counter(works, "source"),
            "work_grade": _nested_counter(works, "source_grade"),
            "work_status": _nested_counter(works, "status"),
            "biography_match_status": _nested_counter(biographies, "match_status"),
            "biography_source": _nested_counter(biographies, "source"),
            "kanripo_match_status": _nested_counter(kanripo, "match_status"),
            "kanripo_source": _nested_counter(kanripo, "source"),
            "dila_match_status": _nested_counter(dila_matches, "match_status"),
            "dila_source": _nested_counter(dila_matches, "source"),
            "dila_collection_status": _counter(
                poet["references"]["dila"]["collection_status"] for poet in poets_out
            ),
            "manual_candidate_status": _nested_counter(manual, "candidate_status"),
            "manual_fact_grade": _nested_counter(manual, "fact_grade"),
            "manual_source_type": _nested_counter(manual, "source_type"),
            "coordinate_grade": _nested_counter(supplements, "coordinate_grade"),
            "coordinate_fact_grade": _nested_counter(supplements, "fact_grade"),
            "coordinate_source_database": _nested_counter(supplements, "coordinate_source_database"),
            "gap_status": _counter(poet["gap"]["status"] for poet in poets_out),
        },
        "poets": poets_out,
    }
    return summary


def _semantic(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result.pop("generated_at", None)
    return result


def preserve_generated_at(summary: dict[str, Any], output_path: Path) -> dict[str, Any]:
    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            existing = None
        if isinstance(existing, dict) and _semantic(existing) == _semantic(summary):
            summary["generated_at"] = str(existing.get("generated_at") or "")
    if not summary.get("generated_at"):
        summary["generated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return summary


def render_markdown(summary: Mapping[str, Any]) -> str:
    totals = summary["totals"]
    availability = summary["input_availability"]
    distributions = summary["distributions"]

    def compact(values: Mapping[str, int]) -> str:
        return "、".join(f"{key}={value}" for key, value in sorted(values.items())) or "无"

    lines = [
        "# 88位诗人史料候选层统一汇总",
        "",
        f"> **口径声明：{summary['scope_note']}**",
        "",
        f"生成时间（UTC）：`{summary['generated_at']}`",
        "",
        "## 全局快照",
        "",
        "| 指标 | 数量 |",
        "|---|---:|",
        f"| 诗人 | {totals['poets']} |",
        f"| 本地诗文 | {totals['poems']} |",
        f"| person-event 候选 | {totals['person_event_candidates']} |",
        f"| 可定位 person-event（含坐标补充） | {totals['locatable_person_events']} |",
        f"| CBDB 坐标补充 | {totals['coordinate_supplements']} |",
        f"| work chronology 候选 | {totals['work_chronology_candidates']} |",
        f"| 人工事件候选 / 线索 | {totals['manual_event_candidates']} / {totals['manual_clues']} |",
        f"| biography / Kanripo / DILA 参考记录 | {totals['biography_reference_records']} / {totals['kanripo_reference_records']} / {totals['dila_reference_records']} |",
        "",
        "DILA 文件状态：" + (
            "已纳入当前快照。"
            if availability.get("dila_matches") or availability.get("dila_coverage")
            else "当前不存在，已按可选输入明确记缺；后续生成后重跑即可纳入。"
        ),
        "",
        "## 全局来源与等级分布",
        "",
        f"- person-event 来源：{compact(distributions['person_event_source'])}",
        f"- person-event 等级：{compact(distributions['person_event_grade'])}",
        f"- work chronology 来源：{compact(distributions['work_source'])}",
        f"- work chronology 等级：{compact(distributions['work_grade'])}",
        f"- 人工证据状态：{compact(distributions['manual_candidate_status'])}",
        f"- 人工证据等级：{compact(distributions['manual_fact_grade'])}",
        f"- 坐标补充等级：{compact(distributions['coordinate_grade'])}",
        "",
        "## 逐人对账",
        "",
        "| 诗人 | CBDB | CNKGraph | 搜韵 | person-event（可定位/总数） | 坐标补充 | works | 人工事件/线索 | 参考（传记/KR/DILA） | 缺口状态 |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for poet in summary["poets"]:
        sources = poet["main_sources"]
        source_cell = {
            source: f"{sources[source]['status']} · {sources[source]['candidate_count']}"
            for source in MAIN_SOURCES
        }
        events = poet["person_events"]
        manual = poet["manual_evidence"]
        refs = poet["references"]
        lines.append(
            "| {poet} | {cbdb} | {cnkgraph} | {souyun} | {loc}/{events} | {supp} | {works} | {me}/{mc} | {bio}/{kr}/{dila} | {gap} |".format(
                poet=poet["poet"],
                cbdb=source_cell["cbdb"],
                cnkgraph=source_cell["cnkgraph"],
                souyun=source_cell["souyun"],
                loc=events["locatable_count"],
                events=events["candidate_count"],
                supp=events["coordinate_supplement_count"],
                works=poet["work_chronology"]["candidate_count"],
                me=manual["event_candidate_count"],
                mc=manual["clue_count"],
                bio=refs["biography"]["record_count"],
                kr=refs["kanripo"]["record_count"],
                dila=refs["dila"]["record_count"],
                gap=poet["gap"]["status"],
            )
        )
    lines.extend(
        [
            "",
            "## 数据边界",
            "",
            "- 本页只汇总 `data/candidates` 与参考语料；未读取或改写 `data/reviewed`。",
            "- 人工补采中的 `event_candidate` 仍单列，不并入 person-event 主候选数。",
            "- 籍贯、出生地、父辈任官地和无同记录时地组合不会被自动拼成路线。",
            "- `generated_at` 只在汇总语义变化时更新；相同语义输入会保持 JSON 与本文档字节不变。",
            "",
        ]
    )
    return "\n".join(lines)


def generate(
    root: Path = ROOT,
    *,
    output_json: Path = OUTPUT_JSON,
    output_doc: Path = OUTPUT_DOC,
    snapshot_retries: int = 8,
) -> tuple[dict[str, Any], bool, bool]:
    summary = preserve_generated_at(build_summary(root, snapshot_retries=snapshot_retries), output_json)
    json_changed = atomic_write_if_changed(output_json, canonical_json(summary, pretty=True).encode("utf-8"))
    doc_changed = atomic_write_if_changed(output_doc, render_markdown(summary).encode("utf-8"))
    return summary, json_changed, doc_changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output-json", type=Path, default=OUTPUT_JSON)
    parser.add_argument("--output-doc", type=Path, default=OUTPUT_DOC)
    parser.add_argument("--snapshot-retries", type=int, default=8)
    args = parser.parse_args()
    summary, json_changed, doc_changed = generate(
        args.root,
        output_json=args.output_json,
        output_doc=args.output_doc,
        snapshot_retries=args.snapshot_retries,
    )
    totals = summary["totals"]
    print(
        "[ok] poets={poets} events={events} locatable={locatable} works={works} manual={manual}; json={json_state} doc={doc_state}".format(
            poets=totals["poets"],
            events=totals["person_event_candidates"],
            locatable=totals["locatable_person_events"],
            works=totals["work_chronology_candidates"],
            manual=totals["manual_evidence_records"],
            json_state="written" if json_changed else "unchanged",
            doc_state="written" if doc_changed else "unchanged",
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
