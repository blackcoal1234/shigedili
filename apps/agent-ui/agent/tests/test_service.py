from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from poetry_agent.cache import SnapshotRepository, sha256_file
from poetry_agent.config import discover_project_root
from poetry_agent.service import (
    EXACT_PRECISIONS,
    PoetryDataService,
    classify_transport,
)
from poetry_agent.tools import build_langchain_tools

from tests.support import StaticRepository


class PoetryDataServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = discover_project_root()
        cls.service = PoetryDataService(StaticRepository(cls.root))
        cls.catalog = cls.service.catalog_poets()

    def assert_invalid_response(self, result) -> None:
        self.assertEqual(
            {"status", "schemaVersion", "sourceHashes", "methodNote", "payload"},
            set(result),
        )
        self.assertEqual("invalid_request", result["status"])

    def test_catalog_has_six_routes_and_eighty_two_evidence_gaps(self) -> None:
        self.assertEqual("ok", self.catalog["status"])
        payload = self.catalog["payload"]
        self.assertEqual(88, payload["poetCount"])
        self.assertEqual(6, payload["routeAvailableCount"])
        self.assertEqual(82, payload["insufficientEvidenceCount"])

        unavailable = [
            row for row in payload["poets"] if row["routeStatus"] == "insufficient_evidence"
        ]
        self.assertEqual(82, len(unavailable))
        for row in unavailable:
            result = self.service.generate_poet_route(row["poet"])
            self.assertEqual("insufficient_evidence", result["status"])
            self.assertEqual(row["workCount"], result["payload"]["corpusWorkCount"])
            self.assertEqual([], result["payload"]["scenes"])
            self.assertIn("longitude", result["payload"]["missingFacts"])

    def test_all_six_supported_poets_return_complete_routes(self) -> None:
        expected = {"李白", "杜甫", "白居易", "苏轼", "陆游", "李清照"}
        available = {
            row["poet"]
            for row in self.catalog["payload"]["poets"]
            if row["routeStatus"] == "available"
        }
        self.assertEqual(expected, available)
        for poet in expected:
            result = self.service.generate_poet_route(poet)
            self.assertEqual("ok", result["status"])
            self.assertGreater(result["payload"]["sceneCount"], 0)
            self.assertTrue(result["sourceHashes"])
            self.assertIn("renderHint", result["payload"])

    def test_transport_classifier_uses_only_explicit_travel_phrases(self) -> None:
        fixtures = (
            ("五月携家离成都乘舟东下", "boat", "乘舟东下"),
            ("奉诏后乘马车赴京", "carriage", "乘马车"),
            ("自剑门骑马赴成都", "horse", "骑马"),
            ("自驿舍徒步入山", "walk", "徒步"),
        )
        for note, expected_mode, expected_basis in fixtures:
            with self.subTest(note=note):
                profile = classify_transport({}, {"source_note": note})
                self.assertEqual(expected_mode, profile["transport_mode"])
                self.assertEqual("documented", profile["transport_certainty"])
                self.assertIn(expected_basis, profile["transport_basis"])

        unrelated = classify_transport(
            {}, {"source_note": "游池边见小娃撑船而作，作品写池上童趣。"}
        )
        self.assertEqual("journey", unrelated["transport_mode"])
        self.assertEqual("unspecified", unrelated["transport_certainty"])

    def test_route_segments_include_transport_contract(self) -> None:
        result = self.service.generate_poet_route("杜甫")
        self.assertEqual("ok", result["status"])
        segments = result["payload"]["routeSegments"]
        self.assertTrue(segments)
        for segment in segments:
            self.assertIn(segment["transport_mode"], {
                "boat", "horse", "carriage", "walk", "journey"
            })
            self.assertTrue(segment["transport_label"])
            self.assertTrue(segment["transport_basis"])
            self.assertIn(
                segment["transport_certainty"], {"documented", "unspecified"}
            )
        self.assertTrue(
            any(segment["transport_mode"] == "boat" for segment in segments)
        )

    def test_route_adds_visual_transition_for_coordinate_complete_gap(self) -> None:
        payload = self.service.generate_poet_route("李白")["payload"]
        start, end = payload["scenes"][0:2]
        transition = next(
            row
            for row in payload["visualTransitions"]
            if row["from_id"] == start["id"] and row["to_id"] == end["id"]
        )
        self.assertEqual("visual_transition", transition["kind"])
        self.assertEqual("not_asserted", transition["certainty"])
        self.assertFalse(transition["historical_claim"])
        self.assertEqual("journey", transition["transport_mode"])
        self.assertEqual(
            [[start["lon"], start["lat"]], [end["lon"], end["lat"]]],
            transition["coords"],
        )

    def test_route_skips_visual_transition_when_endpoint_is_unmapped(self) -> None:
        payload = self.service.generate_poet_route("白居易")["payload"]
        visual_pairs = {
            (row["from_id"], row["to_id"])
            for row in payload["visualTransitions"]
        }
        for start, end in zip(payload["scenes"], payload["scenes"][1:]):
            if not start["map_eligible"] or not end["map_eligible"]:
                self.assertNotIn((start["id"], end["id"]), visual_pairs)

    def test_historical_segment_prevents_duplicate_visual_transition(self) -> None:
        payload = self.service.generate_poet_route("李清照")["payload"]
        historical_pairs = {
            (row["from_id"], row["to_id"])
            for row in payload["routeSegments"]
        }
        visual_pairs = {
            (row["from_id"], row["to_id"])
            for row in payload["visualTransitions"]
        }
        self.assertTrue(historical_pairs.isdisjoint(visual_pairs))

    def test_precision_filters_remove_approximate_and_disputed(self) -> None:
        all_rows = self.service.generate_poet_route("李清照")
        exact_only = self.service.generate_poet_route(
            "李清照", include_approximate=False, include_disputed=False
        )
        self.assertEqual("ok", exact_only["status"])
        self.assertLess(
            exact_only["payload"]["sceneCount"], all_rows["payload"]["sceneCount"]
        )
        self.assertTrue(
            all(
                scene["year_precision"] in EXACT_PRECISIONS
                for scene in exact_only["payload"]["scenes"]
            )
        )
        selected_ids = {scene["id"] for scene in exact_only["payload"]["scenes"]}
        for segment in exact_only["payload"]["routeSegments"]:
            self.assertIn(segment["from_id"], selected_ids)
            self.assertIn(segment["to_id"], selected_ids)

    def test_scene_player_defaults_to_manual_pause(self) -> None:
        result = self.service.play_poem_scenes("李白")
        self.assertEqual("ok", result["status"])
        self.assertEqual("manual_step", result["payload"]["mode"])
        self.assertFalse(result["payload"]["autoplay"])
        self.assertTrue(result["payload"]["pauseAtEachScene"])

    def test_compare_imagery_rejects_unknown_terms(self) -> None:
        result = self.service.compare_imagery(["不存在的意象词"])
        self.assertEqual("invalid_request", result["status"])
        self.assertEqual(["不存在的意象词"], result["payload"]["unknownTerms"])
        self.assertEqual(160, len(result["payload"]["allowedTerms"]))

    def test_compare_imagery_defaults_to_actual_contrasts_with_evidence(self) -> None:
        result = self.service.compare_imagery(limit=8)
        self.assertEqual("ok", result["status"])
        payload = result["payload"]
        self.assertEqual("actual_top_contrasts", payload["selectionRule"])
        self.assertEqual(8, len(payload["comparisons"]))
        for row in payload["comparisons"]:
            self.assertIn("ratePer10k", row["tang"])
            self.assertIn("ratePer10k", row["song"])
            self.assertTrue(row["corpusEvidence"])

    def test_public_methods_strictly_reject_invalid_types_without_repository_access(
        self,
    ) -> None:
        service = PoetryDataService(object())
        calls = (
            lambda: service.generate_poet_route(123),
            lambda: service.generate_poet_route("李白", include_approximate=1),
            lambda: service.generate_poet_route("李白", include_disputed="true"),
            lambda: service.play_poem_scenes(None),
            lambda: service.play_poem_scenes("李白", start_scene_id=12),
            lambda: service.play_poem_scenes("李白", autoplay=0),
            lambda: service.compare_imagery(terms="月"),
            lambda: service.compare_imagery(terms=[1]),
            lambda: service.compare_imagery(terms=[]),
            lambda: service.compare_imagery(limit=True),
            lambda: service.compare_imagery(limit=2.5),
            lambda: service.compare_imagery(chapter_id=7),
            lambda: service.compare_imagery(chapter_id=" "),
        )
        for call in calls:
            with self.subTest(call=call):
                self.assert_invalid_response(call())

    def test_unknown_chapter_id_is_invalid_request(self) -> None:
        result = self.service.compare_imagery(chapter_id="missing-chapter")
        self.assert_invalid_response(result)

    @staticmethod
    def source_tree_fingerprint(root: Path):
        result = {}
        for directory in (root / "data", root / "output"):
            for path in directory.rglob("*"):
                if path.is_file():
                    result[path.relative_to(root).as_posix()] = (
                        sha256_file(path),
                        path.stat().st_mtime_ns,
                    )
        return result

    def test_all_tool_calls_leave_data_and_output_hashes_and_mtimes_unchanged(
        self,
    ) -> None:
        before = self.source_tree_fingerprint(self.root)
        with tempfile.TemporaryDirectory() as directory:
            service = PoetryDataService(
                SnapshotRepository(self.root, Path(directory) / "cache")
            )
            tools = {item.name: item for item in build_langchain_tools(service)}
            results = (
                tools["generate_poet_route"].invoke({"poet": "李白"}),
                tools["play_poem_scenes"].invoke({"poet": "李白"}),
                tools["compare_imagery"].invoke({"limit": 1}),
            )
            self.assertTrue(all(result["status"] == "ok" for result in results))
        after = self.source_tree_fingerprint(self.root)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
