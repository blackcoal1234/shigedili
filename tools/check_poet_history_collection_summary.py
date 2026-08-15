"""Fixture and current-data checks for the 88-poet history summary."""
from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from typing import Any

from build_poet_history_collection_summary import (
    MAIN_SOURCES,
    OUTPUT_DOC,
    OUTPUT_JSON,
    REQUIRED_INPUTS,
    SCOPE_NOTE,
    _semantic,
    build_summary,
    canonical_json,
    generate,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value, pretty=True), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8")


def make_fixture(root: Path, *, poet_count: int = 2, unknown_event: bool = False, dila: bool = True) -> None:
    poets = [f"诗人{index:02d}" for index in range(poet_count)]
    poems = [
        {"poet": poet, "author": poet, "dynasty": "唐" if index % 2 == 0 else "宋", "title": "测试诗"}
        for index, poet in enumerate(poets)
    ]
    events = [
        {"candidate_id": "event-1", "poet": poets[0], "source": "cbdb", "source_grade": "B", "status": "needs_review"},
        {
            "candidate_id": "event-2",
            "poet": poets[-1] if not unknown_event else "名单外诗人",
            "source": "cnkgraph",
            "source_grade": "B",
            "status": "needs_review",
            "latitude": 30.0,
            "longitude": 120.0,
        },
    ]
    works = [
        {"candidate_id": "work-1", "poet": poets[0], "source": "souyun", "source_grade": "C", "status": "needs_review"}
    ]
    statuses = []
    coverage_per_poet: dict[str, Any] = {}
    for poet in poets:
        coverage_per_poet[poet] = {}
        for source in MAIN_SOURCES:
            candidates = sum(row["poet"] == poet and row["source"] == source for row in events + works)
            statuses.append(
                {"poet": poet, "source": source, "status": "collected", "candidates": candidates, "identity_status": "fixture"}
            )
            coverage_per_poet[poet][source] = {
                "status": "collected",
                "reviewable_candidates": candidates,
                "stale_candidate_count": 0,
            }
    biographies = [{"poet": poet, "match_status": "matched", "source": "fixture-biography"} for poet in poets]
    kanripo = [{"poet": poets[0], "match_status": "matched", "source": "fixture-kanripo"}]
    gap = {
        "schema_version": 1,
        "generated_at": "2026-08-09T00:00:00+00:00",
        "entries": [{"poet": poets[-1], "status": "needs_manual_review", "gap_type": "zero_event", "priority": "P1"}],
    }
    manual_tang = [
        {"poet": poets[0], "candidate_status": "event_candidate", "fact_grade": "B", "source_record_id": "manual-1"}
    ]
    manual_song = [
        {"poet": poets[-1], "candidate_status": "lead_only", "fact_grade": "C", "source_record_id": "manual-2"}
    ]
    supplements = [
        {"candidate_id": "event-1", "poet": poets[0], "coordinate_grade": "A", "fact_grade": "B", "lat": 31.0, "lon": 121.0}
    ]
    values: dict[str, Any] = {
        "poems": poems,
        "events": events,
        "works": works,
        "source_status": statuses,
        "source_coverage": {"schema_version": 4, "per_poet": coverage_per_poet},
        "biographies": biographies,
        "kanripo": kanripo,
        "gap_backlog": gap,
        "manual_tang": manual_tang,
        "manual_song": manual_song,
        "coordinate_supplements": supplements,
    }
    for name, relative in REQUIRED_INPUTS.items():
        path = root / relative
        value = values[name]
        if relative.endswith(".jsonl"):
            _write_jsonl(path, value)
        else:
            _write_json(path, value)
    if dila:
        _write_jsonl(
            root / "data/candidates/poet_dila_person_matches.jsonl",
            [{"poet": poets[0], "match_status": "matched", "source": "DILA"}],
        )
        _write_json(
            root / "data/candidates/poet_dila_person_coverage.json",
            {
                "per_poet": [
                    {
                        "poet": poet,
                        "dila": {
                            "status": "matched" if index == 0 else "not_found",
                            "active_status": "matched" if index == 0 else "not_found",
                            "candidate_count": 1 if index == 0 else 0,
                        },
                    }
                    for index, poet in enumerate(poets)
                ]
            },
        )


def validate_summary(summary: dict[str, Any], *, expected_poets: int) -> None:
    poets = summary.get("poets")
    if not isinstance(poets, list) or len(poets) != expected_poets:
        raise AssertionError(f"expected {expected_poets} poet summaries, got {len(poets) if isinstance(poets, list) else type(poets)}")
    names = [row["poet"] for row in poets]
    if len(names) != len(set(names)) or names != sorted(names):
        raise AssertionError("poet rows must be unique and stably sorted")
    totals = summary["totals"]
    expected_sums = {
        "poets": len(poets),
        "poems": sum(row["poem_count"] for row in poets),
        "person_event_candidates": sum(row["person_events"]["candidate_count"] for row in poets),
        "direct_locatable_person_events": sum(row["person_events"]["direct_locatable_count"] for row in poets),
        "coordinate_supplements": sum(row["person_events"]["coordinate_supplement_count"] for row in poets),
        "locatable_person_events": sum(row["person_events"]["locatable_count"] for row in poets),
        "unlocated_person_events": sum(row["person_events"]["unlocated_count"] for row in poets),
        "work_chronology_candidates": sum(row["work_chronology"]["candidate_count"] for row in poets),
        "biography_reference_records": sum(row["references"]["biography"]["record_count"] for row in poets),
        "kanripo_reference_records": sum(row["references"]["kanripo"]["record_count"] for row in poets),
        "dila_reference_records": sum(row["references"]["dila"]["record_count"] for row in poets),
        "manual_evidence_records": sum(row["manual_evidence"]["record_count"] for row in poets),
        "manual_event_candidates": sum(row["manual_evidence"]["event_candidate_count"] for row in poets),
        "manual_clues": sum(row["manual_evidence"]["clue_count"] for row in poets),
        "gap_backlog_poets": sum(row["gap"]["listed"] for row in poets),
    }
    for field, expected in expected_sums.items():
        if totals[field] != expected:
            raise AssertionError(f"total mismatch {field}: {totals[field]} != {expected}")
    if totals["main_candidates"] != totals["person_event_candidates"] + totals["work_chronology_candidates"]:
        raise AssertionError("main candidate total does not reconcile")
    if totals["manual_evidence_records"] != totals["manual_event_candidates"] + totals["manual_clues"]:
        raise AssertionError("manual evidence total does not reconcile")
    if totals["main_source_status_rows"] != expected_poets * len(MAIN_SOURCES):
        raise AssertionError("main-source status rows must be exactly poet_count × 3")

    event_sources: Counter[str] = Counter()
    work_sources: Counter[str] = Counter()
    for row in poets:
        event_sources.update(row["person_events"]["by_source"])
        work_sources.update(row["work_chronology"]["by_source"])
        events = row["person_events"]
        if not (0 <= events["direct_locatable_count"] <= events["locatable_count"] <= events["candidate_count"]):
            raise AssertionError(f"{row['poet']} has inconsistent locatable person-event counts")
        if events["unlocated_count"] != events["candidate_count"] - events["locatable_count"]:
            raise AssertionError(f"{row['poet']} has inconsistent unlocated person-event count")
        if set(row["main_sources"]) != set(MAIN_SOURCES):
            raise AssertionError(f"{row['poet']} does not have exactly the three main sources")
        for source in MAIN_SOURCES:
            source_row = row["main_sources"][source]
            if source_row["status"] == "missing_status":
                raise AssertionError(f"{row['poet']}/{source} is missing a source-status row")
            if source_row["candidate_count"] != source_row["reported_candidate_count"]:
                raise AssertionError(f"{row['poet']}/{source} candidate count does not match source status")
    if dict(sorted(event_sources.items())) != summary["distributions"]["person_event_source"]:
        raise AssertionError("event source distribution does not reconcile")
    if dict(sorted(work_sources.items())) != summary["distributions"]["work_source"]:
        raise AssertionError("work source distribution does not reconcile")
    for source in MAIN_SOURCES:
        if sum(summary["distributions"]["main_source_status"][source].values()) != expected_poets:
            raise AssertionError(f"{source} status distribution does not cover all poets")
    if summary.get("scope_note") != SCOPE_NOTE:
        raise AssertionError("candidate-layer scope statement missing or altered")
    boundary = summary.get("candidate_layer_boundary", {})
    if any(boundary.get(key) for key in ("reviewed_data_included", "manual_evidence_promoted", "route_claims_created")):
        raise AssertionError("candidate/reviewed boundary flags are not false")


class FixtureTests(unittest.TestCase):
    def test_fixture_aggregation_and_dila(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)
            summary = build_summary(root)
            validate_summary(summary, expected_poets=2)
            self.assertEqual(2, summary["totals"]["locatable_person_events"])
            self.assertEqual(1, summary["totals"]["coordinate_supplements"])
            self.assertEqual(1, summary["totals"]["dila_reference_records"])
            self.assertTrue(summary["input_availability"]["dila_matches"])
            self.assertEqual("matched", summary["poets"][0]["references"]["dila"]["collection_status"])

    def test_unknown_poet_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root, unknown_event=True)
            with self.assertRaisesRegex(ValueError, "unknown"):
                build_summary(root)

    def test_unknown_manual_status_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root)
            manual_path = root / "data/candidates/manual_source_evidence_song_zero_event.jsonl"
            _write_jsonl(
                manual_path,
                [{"poet": "诗人01", "candidate_status": "typo", "fact_grade": "C", "source_record_id": "bad"}],
            )
            with self.assertRaisesRegex(ValueError, "unknown candidate_status"):
                build_summary(root)

    def test_generated_at_and_bytes_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_fixture(root, dila=False)
            output = root / "summary.json"
            doc = root / "summary.md"
            first, _, _ = generate(root, output_json=output, output_doc=doc)
            json_bytes = output.read_bytes()
            doc_bytes = doc.read_bytes()
            second, json_changed, doc_changed = generate(root, output_json=output, output_doc=doc)
            self.assertEqual(first["generated_at"], second["generated_at"])
            self.assertEqual(json_bytes, output.read_bytes())
            self.assertEqual(doc_bytes, doc.read_bytes())
            self.assertFalse(json_changed)
            self.assertFalse(doc_changed)


def integration_check() -> None:
    if not OUTPUT_JSON.exists() or not OUTPUT_DOC.exists():
        raise AssertionError("run build_poet_history_collection_summary.py before integration check")
    written = json.loads(OUTPUT_JSON.read_text(encoding="utf-8-sig"))
    validate_summary(written, expected_poets=88)
    fresh = build_summary(ROOT)
    if _semantic(written) != _semantic(fresh):
        raise AssertionError("written summary is stale relative to the current stable input snapshot")
    if not written.get("generated_at"):
        raise AssertionError("generated_at is empty")
    document = OUTPUT_DOC.read_text(encoding="utf-8")
    if SCOPE_NOTE not in document:
        raise AssertionError("Markdown does not state the current-snapshot/non-exhaustive boundary")
    if document.count("\n|") < 90:
        raise AssertionError("Markdown does not appear to contain the 88-poet table")


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FixtureTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1
    integration_check()
    print("[ok] current integration: 88 poets, no unknown poets, all aggregate totals reconcile")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
