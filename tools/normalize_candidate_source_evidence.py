"""Normalize manual evidence IDs/statuses and reconcile the source-gap backlog."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
CANDIDATES = ROOT / "data" / "candidates"
TANG = CANDIDATES / "manual_source_evidence_tang_zero_event.jsonl"
SONG = CANDIDATES / "manual_source_evidence_song_zero_event.jsonl"
COORDINATES = CANDIDATES / "cbdb_event_coordinate_supplements.jsonl"
BACKLOG = CANDIDATES / "poet_journey_gap_backlog.json"
SONG_DOC = ROOT / "docs" / "manual-source-evidence-song-zero-event.md"
GAP_DOC = ROOT / "docs" / "poet-journey-source-gap-audit.md"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(canonical(row) + "\n" for row in rows), encoding="utf-8")


def evidence_id(row: dict[str, Any]) -> str:
    identity = {
        "poet": row.get("poet"),
        "source_url": row.get("source_url"),
        "source_record_id": row.get("source_record_id"),
        "evidence_locator": row.get("evidence_locator"),
        "time_expression": row.get("time_expression"),
        "place_expression": row.get("place_expression"),
        "event_summary": row.get("event_summary"),
        "evidence_excerpt": row.get("evidence_excerpt"),
    }
    return hashlib.sha256(("manual-source-evidence-v1\0" + canonical(identity)).encode("utf-8")).hexdigest()


def normalize_evidence(path: Path) -> tuple[int, int]:
    rows = read_jsonl(path)
    for row in rows:
        if row.get("candidate_status") == "lead_only":
            row["candidate_status"] = "clue_only"
        row["evidence_id"] = evidence_id(row)
    write_jsonl(path, rows)
    return len(rows), sum(row.get("candidate_status") == "event_candidate" for row in rows)


def reconcile_backlog() -> tuple[int, int]:
    supplements = read_jsonl(COORDINATES)
    per_poet = Counter(str(row["poet"]) for row in supplements)
    backlog = json.loads(BACKLOG.read_text(encoding="utf-8-sig"))
    old_generated_at = str(backlog.get("generated_at") or "")
    old_semantic = dict(backlog)
    old_semantic.pop("generated_at", None)
    for entry in backlog["entries"]:
        if entry.get("gap_type") not in {
            "has_person_event_but_no_locatable_event",
            "has_unresolved_person_event_coordinates",
        }:
            continue
        poet = str(entry["poet"])
        located = int(per_poet.get(poet, 0))
        total = int(entry.get("event_candidates") or 0)
        entry["gap_type"] = "has_unresolved_person_event_coordinates"
        entry["locatable_events"] = located
        entry["coordinate_supplements"] = located
        entry["unresolved_event_coordinates"] = max(0, total - located)
        cbdb = entry.setdefault("current_sources", {}).setdefault("cbdb", {})
        cbdb["locatable_events"] = located
        cbdb["coordinate_supplements"] = located
        cbdb["coordinate_supplement_file"] = (
            "data/candidates/cbdb_event_coordinate_supplements.jsonl"
        )
    snapshot = backlog["event_snapshot"]
    located_total = len(supplements)
    unresolved = int(snapshot.get("gap_event_candidates") or 0) - located_total
    snapshot["coordinate_supplements"] = located_total
    snapshot["locatable_event_candidates_after_supplement"] = (
        int(snapshot.get("locatable_event_candidates") or 0) + located_total
    )
    snapshot["unlocated_event_candidates_after_supplement"] = (
        int(snapshot.get("unlocated_event_candidates") or 0) - located_total
    )
    snapshot["gap_locatable_events_after_supplement"] = located_total
    snapshot["gap_unresolved_event_coordinates"] = unresolved
    snapshot["person_event_without_locatable_poets"] = 0
    snapshot["poets_with_unresolved_event_coordinates"] = 6
    snapshot["coordinate_supplement_note"] = (
        "19 coordinates are direct CBDB ADDR_CODES joins and remain candidate-layer supplements; "
        "11 event coordinates still require review."
    )
    backlog["schema_version"] = 2
    new_semantic = dict(backlog)
    new_semantic.pop("generated_at", None)
    backlog["generated_at"] = (
        old_generated_at
        if old_semantic == new_semantic and old_generated_at
        else datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    BACKLOG.write_text(json.dumps(backlog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return located_total, unresolved


def update_docs(located: int, unresolved: int) -> None:
    if SONG_DOC.exists():
        SONG_DOC.write_text(
            SONG_DOC.read_text(encoding="utf-8-sig").replace("lead_only", "clue_only"),
            encoding="utf-8",
        )
    marker = "## 7. 坐标回填后更新"
    addition = (
        f"\n\n{marker}\n\n"
        f"候选层已通过 `ADDR_CODES` 直接关联补入 **{located}/30** 条坐标；仍有 "
        f"**{unresolved}** 条事件地点待人工定位。六位 P0 诗人的缺口类型由“完全无可定位事件”"
        "更新为 `has_unresolved_person_event_coordinates`。这些坐标仍是候选补充，不自动进入 "
        "`data/reviewed/`，也不以籍贯或现代代表城市替代事件地点。\n"
    )
    text = GAP_DOC.read_text(encoding="utf-8-sig")
    if marker in text:
        text = text.split(marker, 1)[0].rstrip()
    GAP_DOC.write_text(text + addition, encoding="utf-8")


def main() -> None:
    tang = normalize_evidence(TANG)
    song = normalize_evidence(SONG)
    located, unresolved = reconcile_backlog()
    update_docs(located, unresolved)
    print(
        "normalized candidate evidence: "
        f"tang={tang[0]}/{tang[1]}events song={song[0]}/{song[1]}events "
        f"coordinates={located} unresolved={unresolved}"
    )


if __name__ == "__main__":
    main()
