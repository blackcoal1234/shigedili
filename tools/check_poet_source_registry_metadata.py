"""Offline regression checks for poet source-registry metadata and refreshes."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import poet_source_registry as psr
import journey_source_pipeline as jsp


REQUIRED_SOURCE_METADATA = {
    "source_url",
    "access_level",
    "source_grade",
    "license",
    "license_note",
}


def verified_seed_source() -> dict[str, object]:
    return {
        "status": "audited_seed",
        "author_id": 15188,
        "identity_verified": True,
        "verified_author_name": "李白",
        "verified_dynasty": "Tang",
        "verified_author_id": 15188,
        "identity_verification_method": "souyun_open_poem_exact_name_dynasty_author_id",
        "identity_verified_at": "2026-08-09T00:00:00Z",
        "identity_verified_from": "fixture://verified/libai",
        "discovered_at": "2026-08-09T00:00:00Z",
        "discovered_from": "fixture://verified/libai",
    }


def verified_discovery_source() -> dict[str, object]:
    source = verified_seed_source()
    source.update(
        status="discovered",
        author_id=24680,
        verified_author_name="王维",
        verified_author_id=24680,
        identity_verified_from="fixture://verified/wangwei",
        discovered_from="fixture://verified/wangwei",
    )
    return source


def candidate_metadata_samples() -> dict[str, dict[str, object]]:
    """Build representative rows through the candidate-layer constructors."""
    cbdb = jsp._cbdb_common(
        poet="李白",
        person_id="32540",
        addr_id="fixture-address",
        event_type="residence",
        start=701,
        end=701,
        place="长安",
        pages="fixture-page",
        note="fixture",
        grade="B",
        cache_key="fixture-cbdb",
        source_url=jsp.CBDB_API,
    )
    souyun = jsp.make_work_chronology_candidate(
        "李白",
        {"poet": "李白", "title": "静夜思", "body": "床前明月光"},
        {"title": "静夜思", "work_id": "fixture-work", "precision": "year"},
        701,
        701,
        "fixture-souyun",
        jsp.SOUYUN_POEM_API,
        source_mode="api",
    )
    cnkgraph = jsp.make_cnkgraph_event_candidate(
        "李白",
        {
            "year_start": 701,
            "year_end": 701,
            "historical_place": "长安",
            "event_text": "fixture",
            "source_locator": "fixture-marker",
            "grade": "B",
            "method": "cnkgraph_biography_traces_v1",
        },
        "fixture-person",
        "fixture-cnkgraph",
        jsp.CNKGRAPH_BIOGRAPHY_API,
    )
    return {"cbdb": cbdb, "souyun": souyun, "cnkgraph": cnkgraph}


class RegistrySourceMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        with patch.object(psr, "utc_now", return_value="2026-08-09T00:00:00Z"):
            self.registry = psr.build_source_registry(
                identity_rows=[],
                audit={
                    "source": "fixture audit",
                    "unique": {"李白": "32540"},
                    "ambiguous": {"常建": ["94489", "147391"]},
                },
                souyun_probe={},
            )

    def test_all_264_source_entries_have_complete_candidate_layer_metadata(self) -> None:
        rows = self.registry["poets"]
        self.assertEqual(self.registry["schema_version"], 4)
        self.assertEqual(len(rows), 88)
        candidate_samples = candidate_metadata_samples()

        source_entries = [
            (row["poet"], source, row[source])
            for row in rows
            for source in ("cbdb", "souyun", "cnkgraph")
        ]
        self.assertEqual(len(source_entries), 88 * 3)
        for poet, source, entry in source_entries:
            with self.subTest(poet=poet, source=source):
                self.assertTrue(REQUIRED_SOURCE_METADATA <= entry.keys())
                self.assertTrue(str(entry["source_url"]).strip())
                self.assertTrue(str(entry["access_level"]).strip())
                self.assertTrue(str(entry["source_grade"]).strip())
                self.assertTrue(str(entry["license_note"]).strip())
                for key in REQUIRED_SOURCE_METADATA:
                    self.assertEqual(entry[key], candidate_samples[source][key])


class RegistryFreshProbeBlockerTests(unittest.TestCase):
    def test_audited_seed_with_two_exact_ids_is_ambiguous_and_stale_only(self) -> None:
        source = psr._souyun_entry(
            "李白",
            "Tang",
            {
                "status": "fetched",
                "names": ["李白", "李白"],
                "author_ids": [15188, 99999],
                "source_dynasties": ["Tang", "Tang"],
                "count": 2,
                "page_size": 20,
                "page0_records": 20,
            },
        )
        self.assertEqual(source["status"], "identity_ambiguous")
        self.assertIsNone(source["author_id"])
        self.assertEqual(source["candidate_author_ids"], [15188, 99999])
        self.assertEqual(source["stale_candidate_author_ids"], [15188])
        self.assertIs(source["identity_verified"], False)

    def test_audited_seed_with_page_size_zero_is_disambiguation_blocked(self) -> None:
        source = psr._souyun_entry(
            "李白",
            "Tang",
            {
                "status": "fetched",
                "names": ["李白"],
                "author_ids": [15188],
                "source_dynasties": ["Tang"],
                "count": 1,
                "page_size": 0,
                "page0_records": 0,
            },
        )
        self.assertEqual(
            source["status"],
            "discovered_author_id_but_api_requires_disambiguation",
        )
        self.assertEqual(source["author_id"], 15188)
        self.assertEqual(source["candidate_author_ids"], [15188])
        self.assertEqual(source["stale_candidate_author_ids"], [15188])
        self.assertIs(source["identity_verified"], False)

    def test_current_luyou_probe_keeps_seed_stale_under_disambiguation(self) -> None:
        probe = psr.load_souyun_identity_probe()
        row = next(
            item
            for item in probe["rows"]
            if isinstance(item, dict) and item.get("poet") == "陆游"
        )
        self.assertEqual(row["author_ids"], [0, 34522])
        self.assertEqual(row["page_size"], 0)
        self.assertEqual(row["page0_records"], 0)

        registry = psr.build_source_registry(
            identity_rows=[], audit={}, souyun_probe=probe
        )
        source = psr.registry_by_poet(registry)["陆游"]["souyun"]
        self.assertEqual(
            source["status"],
            "discovered_author_id_but_api_requires_disambiguation",
        )
        self.assertEqual(source["author_id"], 34522)
        self.assertEqual(source["candidate_author_ids"], [34522])
        self.assertEqual(source["stale_candidate_author_ids"], [34522])
        self.assertIs(source["identity_verified"], False)


class RegistryVerifiedSeedRefreshTests(unittest.TestCase):
    def test_every_declared_provenance_field_is_required_for_activation(self) -> None:
        for missing in psr._SOUYUN_VERIFIED_PROVENANCE_FIELDS:
            with self.subTest(missing=missing):
                old_source = verified_seed_source()
                old_source.pop(missing)
                self.assertFalse(
                    psr._is_verified_souyun_discovery(
                        old_source, poet="李白", dynasty="Tang"
                    )
                )
                fresh = {
                    "poets": [
                        {
                            "poet": "李白",
                            "dynasty": "Tang",
                            "souyun": {
                                "status": "name_query",
                                "author_id": None,
                                "identity_verified": False,
                            },
                        }
                    ]
                }
                existing = {
                    "poets": [
                        {
                            "poet": "李白",
                            "dynasty": "Tang",
                            "souyun": old_source,
                        }
                    ]
                }
                psr._preserve_souyun_discoveries(fresh, existing)
                source = fresh["poets"][0]["souyun"]
                self.assertEqual(source["status"], "name_query")
                self.assertIsNone(source["author_id"])
                self.assertIs(source["identity_verified"], False)
                self.assertEqual(source["stale_candidate_author_ids"], [15188])

    def test_refresh_preserves_full_verified_audited_seed_provenance_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "poet_source_registry.json"
            with patch.object(psr, "utc_now", return_value="initial-build"):
                existing = psr.build_source_registry(
                    identity_rows=[], audit={}, souyun_probe={}
                )
            old_source = psr.registry_by_poet(existing)["李白"]["souyun"]
            old_source.update(verified_seed_source())
            psr.write_source_registry(existing, path)

            with (
                patch.object(psr, "load_cbdb_identity_audit", return_value={}),
                patch.object(psr, "load_souyun_identity_probe", return_value={}),
                patch.object(
                    psr,
                    "utc_now",
                    side_effect=["first-refresh", "second-refresh"],
                ),
            ):
                first = psr.refresh_source_registry(identity_rows=[], path=path)
                first_text = path.read_text(encoding="utf-8")
                second = psr.refresh_source_registry(identity_rows=[], path=path)

            source = psr.registry_by_poet(first)["李白"]["souyun"]
            for key, value in verified_seed_source().items():
                with self.subTest(field=key):
                    self.assertEqual(source[key], value)
            self.assertEqual(second, first)
            self.assertEqual(first["generated_at"], "initial-build")
            self.assertEqual(path.read_text(encoding="utf-8"), first_text)
            self.assertEqual(json.loads(first_text), first)

    def test_probe_unique_verified_discovery_remains_idempotent_across_refreshes(self) -> None:
        probe = {
            "rows": [
                {
                    "poet": "王维",
                    "names": ["王维"],
                    "author_ids": [24680],
                    "source_dynasties": ["Tang"],
                    "status": "ok",
                    "count": 1,
                    "page_size": 20,
                    "page0_records": 1,
                }
            ]
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "poet_source_registry.json"
            with patch.object(psr, "utc_now", return_value="initial-build"):
                existing = psr.build_source_registry(
                    identity_rows=[], audit={}, souyun_probe=probe
                )
            psr.registry_by_poet(existing)["王维"]["souyun"].update(
                verified_discovery_source()
            )
            psr.write_source_registry(existing, path)

            with (
                patch.object(psr, "load_cbdb_identity_audit", return_value={}),
                patch.object(psr, "load_souyun_identity_probe", return_value=probe),
                patch.object(
                    psr,
                    "utc_now",
                    side_effect=["first-refresh", "second-refresh"],
                ),
            ):
                first = psr.refresh_source_registry(identity_rows=[], path=path)
                first_text = path.read_text(encoding="utf-8")
                second = psr.refresh_source_registry(identity_rows=[], path=path)

            source = psr.registry_by_poet(second)["王维"]["souyun"]
            for key, value in verified_discovery_source().items():
                with self.subTest(field=key):
                    self.assertEqual(source[key], value)
            self.assertEqual(second, first)
            self.assertEqual(path.read_text(encoding="utf-8"), first_text)

    def test_fresh_identity_blockers_keep_verified_seed_id_stale_only(self) -> None:
        for blocker, fresh_author_id in (
            ("identity_ambiguous", None),
            ("discovered_author_id_but_api_requires_disambiguation", 31001),
        ):
            with self.subTest(blocker=blocker):
                fresh = {
                    "poets": [
                        {
                            "poet": "李白",
                            "dynasty": "Tang",
                            "souyun": {
                                "status": blocker,
                                "author_id": fresh_author_id,
                                "identity_verified": False,
                            },
                        }
                    ]
                }
                existing = {
                    "poets": [
                        {
                            "poet": "李白",
                            "dynasty": "Tang",
                            "souyun": verified_seed_source(),
                        }
                    ]
                }

                psr._preserve_souyun_discoveries(fresh, existing)
                after_first = copy.deepcopy(fresh)
                psr._preserve_souyun_discoveries(fresh, existing)

                source = fresh["poets"][0]["souyun"]
                self.assertEqual(source["status"], blocker)
                self.assertEqual(source["author_id"], fresh_author_id)
                self.assertIs(source["identity_verified"], False)
                self.assertEqual(source["stale_candidate_author_ids"], [15188])
                for key in psr._SOUYUN_VERIFIED_PROVENANCE_FIELDS:
                    if key != "identity_verified":
                        self.assertNotIn(key, source)
                self.assertEqual(fresh, after_first)


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
