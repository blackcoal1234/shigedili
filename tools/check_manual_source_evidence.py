"""Validate the candidate-only source-gap and manual evidence artefacts."""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from poet_reference_corpus import load_roster


ROOT = Path(__file__).resolve().parent.parent
CANDIDATES = ROOT / "data" / "candidates"

BACKLOG = CANDIDATES / "poet_journey_gap_backlog.json"
TANG = CANDIDATES / "manual_source_evidence_tang_zero_event.jsonl"
SONG = CANDIDATES / "manual_source_evidence_song_zero_event.jsonl"
COORDINATES = CANDIDATES / "cbdb_event_coordinate_supplements.jsonl"

REQUIRED_EVIDENCE_FIELDS = {
    "poet",
    "evidence_id",
    "dynasty",
    "source_name",
    "source_url",
    "source_type",
    "source_record_id",
    "accessed_at",
    "identity_basis",
    "time_expression",
    "place_expression",
    "event_summary",
    "evidence_excerpt",
    "evidence_locator",
    "fact_grade",
    "candidate_status",
    "notes",
}
ALLOWED_EVIDENCE_STATUSES = {"event_candidate", "clue_only", "needs_manual_review"}
ALLOWED_GRADES = {"A", "B", "C", "D"}


def fail(message: str) -> None:
    raise AssertionError(message)


def load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        fail(f"missing JSONL: {path}")
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_no, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                fail(f"{path}:{line_no}: expected object")
            rows.append(value)
    if not rows:
        fail(f"empty JSONL: {path}")
    return rows


def valid_web_url(value: object) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def check_backlog(roster: set[str]) -> None:
    payload = json.loads(BACKLOG.read_text(encoding="utf-8-sig"))
    if payload.get("schema_version") != 2:
        fail("gap backlog schema_version must be 2 after coordinate reconciliation")
    entries = payload.get("entries")
    if not isinstance(entries, list) or len(entries) != 15:
        fail("gap backlog must contain the audited 15 entries")
    poets = [str(row.get("poet") or "") for row in entries if isinstance(row, dict)]
    if len(poets) != len(set(poets)) or not set(poets) <= roster:
        fail("gap backlog poets must be unique members of the 88-poet roster")
    kinds = Counter(str(row.get("gap_type") or "") for row in entries)
    if kinds != {"no_person_event": 9, "has_unresolved_person_event_coordinates": 6}:
        fail(f"unexpected gap split: {dict(kinds)}")
    if any(row.get("status") != "needs_manual_review" for row in entries):
        fail("every gap backlog row must remain needs_manual_review")
    if any("event" in row or "events" in row for row in entries):
        fail("the source-gap backlog must not manufacture event payloads")
    unresolved_rows = [
        row for row in entries
        if row.get("gap_type") == "has_unresolved_person_event_coordinates"
    ]
    if sum(int(row.get("coordinate_supplements") or 0) for row in unresolved_rows) != 19:
        fail("gap backlog must reconcile all 19 direct coordinate supplements")
    if sum(int(row.get("unresolved_event_coordinates") or 0) for row in unresolved_rows) != 11:
        fail("gap backlog must retain the 11 unresolved event coordinates")


def check_evidence(path: Path, expected_poets: set[str], roster: set[str]) -> tuple[int, int]:
    rows = load_jsonl(path)
    actual_poets = {str(row.get("poet") or "") for row in rows}
    if actual_poets != expected_poets or not actual_poets <= roster:
        fail(f"{path.name}: unexpected poet coverage: {sorted(actual_poets)}")
    keys: set[tuple[str, str, str, str]] = set()
    evidence_ids: set[str] = set()
    event_count = 0
    for index, row in enumerate(rows, 1):
        missing = REQUIRED_EVIDENCE_FIELDS - row.keys()
        if missing:
            fail(f"{path.name}:{index}: missing fields {sorted(missing)}")
        # One source record can legitimately support several separately located
        # claims.  Treat only the same record + locator + claim as a duplicate.
        key = (
            str(row["poet"]),
            str(row["source_record_id"]),
            str(row["evidence_locator"]),
            str(row["event_summary"]),
        )
        if key in keys:
            fail(f"{path.name}:{index}: duplicate source record {key}")
        keys.add(key)
        from normalize_candidate_source_evidence import evidence_id

        expected_id = evidence_id(row)
        if row["evidence_id"] != expected_id or expected_id in evidence_ids:
            fail(f"{path.name}:{index}: invalid or duplicate evidence_id")
        evidence_ids.add(expected_id)
        if row["candidate_status"] not in ALLOWED_EVIDENCE_STATUSES:
            fail(f"{path.name}:{index}: invalid candidate_status")
        if row["fact_grade"] not in ALLOWED_GRADES:
            fail(f"{path.name}:{index}: invalid fact_grade")
        if not valid_web_url(row["source_url"]):
            fail(f"{path.name}:{index}: invalid source_url")
        if not str(row["identity_basis"]).strip() or not str(row["evidence_locator"]).strip():
            fail(f"{path.name}:{index}: identity/evidence provenance is required")
        if len(str(row["evidence_excerpt"])) > 120:
            fail(f"{path.name}:{index}: excerpt is not a short evidence locator")
        if row["candidate_status"] == "event_candidate":
            event_count += 1
            if not str(row["time_expression"]).strip() or not str(row["place_expression"]).strip():
                fail(f"{path.name}:{index}: event candidate lacks time or place evidence")
            if not str(row["event_summary"]).strip():
                fail(f"{path.name}:{index}: event candidate lacks a summary")
    return len(rows), event_count


def check_coordinate_supplements(roster: set[str]) -> None:
    rows = load_jsonl(COORDINATES)
    required = {
        "candidate_id",
        "stable_link_key",
        "poet",
        "cbdb_person_id",
        "cbdb_addr_id",
        "place",
        "lat",
        "lon",
        "coordinate_source_table",
        "coordinate_source_row_id",
        "coordinate_source_database_sha256",
        "coordinate_grade",
        "fact_grade",
        "source_url",
        "note",
    }
    if len(rows) != 19:
        fail(f"expected 19 direct CBDB coordinate supplements, got {len(rows)}")
    if len({str(row.get("candidate_id")) for row in rows}) != len(rows):
        fail("coordinate supplement candidate_id values must be unique")
    if len({str(row.get("stable_link_key")) for row in rows}) != len(rows):
        fail("coordinate supplement stable_link_key values must be unique")
    for index, row in enumerate(rows, 1):
        missing = required - row.keys()
        if missing:
            fail(f"coordinate row {index}: missing fields {sorted(missing)}")
        if str(row["poet"]) not in roster:
            fail(f"coordinate row {index}: poet is outside the roster")
        lat, lon = float(row["lat"]), float(row["lon"])
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            fail(f"coordinate row {index}: invalid coordinate")
        if lat == 0 and lon == 0:
            fail(f"coordinate row {index}: rejected zero sentinel leaked into output")
        if row["coordinate_source_table"] != "ADDR_CODES":
            fail(f"coordinate row {index}: coordinates must be a direct ADDR_CODES join")
        if str(row["coordinate_source_row_id"]) != str(row["cbdb_addr_id"]):
            fail(f"coordinate row {index}: source row must match cbdb_addr_id")
        if row["coordinate_grade"] not in {"A", "B"} or row["fact_grade"] not in ALLOWED_GRADES:
            fail(f"coordinate row {index}: invalid grade")
        if not valid_web_url(row["source_url"]):
            fail(f"coordinate row {index}: invalid source URL")


def main() -> None:
    roster = {item.name for item in load_roster()}
    if len(roster) != 88:
        fail(f"expected 88 poets, got {len(roster)}")
    check_backlog(roster)
    tang_rows, tang_events = check_evidence(
        TANG,
        {"贺知章", "张继", "常建", "祖咏", "上官仪", "张志和", "聂夷中"},
        roster,
    )
    song_rows, song_events = check_evidence(SONG, {"石延年", "朱淑真"}, roster)
    check_coordinate_supplements(roster)
    print(
        "manual source evidence checks passed: "
        f"backlog=15 tang={tang_rows}/{tang_events}events "
        f"song={song_rows}/{song_events}events coordinates=19"
    )


if __name__ == "__main__":
    main()
