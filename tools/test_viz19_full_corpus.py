from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT / "数据可视化脚本"
SCRIPT_PATH = SCRIPT_DIR / "viz_19_life_trace_app.py"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SPEC = importlib.util.spec_from_file_location("viz19_full_corpus", SCRIPT_PATH)
assert SPEC and SPEC.loader
VIZ19 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VIZ19)


class Viz19FullCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = VIZ19.build_payload()
        cls.manifest = json.loads(
            (ROOT / "data/analysis/famous_poets_full_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        cls.canonical = json.loads(
            (ROOT / "data/poems.json").read_text(encoding="utf-8")
        )

    def test_six_profiles_use_manifest_full_counts_not_fixed_300(self) -> None:
        expected = self.manifest["counts"]["poet"]
        actual = {
            poet: self.payload["profiles"][poet]["poem_count"]
            for poet in VIZ19.TARGET_POETS
        }
        self.assertEqual(actual, {poet: expected[poet] for poet in VIZ19.TARGET_POETS})
        self.assertNotEqual(tuple(actual.values()), (300,) * len(VIZ19.TARGET_POETS))
        for poet, count in actual.items():
            profile = self.payload["profiles"][poet]
            self.assertEqual(profile["analysis_count"], count)
            self.assertIn(f"当前 {count} 首全作品状态语料", profile["life_summary"])
            self.assertTrue(profile["imagery"])
            self.assertTrue(profile["emotions"])

    def test_payload_declares_full_state_and_canonical_evidence_layers(self) -> None:
        canonical_counts = Counter(
            str(row.get("poet") or row.get("author") or "")
            for row in self.canonical
        )
        self.assertEqual(self.payload["corpus_source"], "analysis_full")
        self.assertEqual(
            self.payload["corpus_path"],
            "data/analysis/famous_poets_full.jsonl.gz",
        )
        self.assertEqual(self.payload["analysis_count"], self.manifest["record_count"])
        self.assertEqual(self.payload["canonical_evidence_count"], len(self.canonical))
        self.assertGreater(
            self.payload["analysis_count"], self.payload["canonical_evidence_count"]
        )
        self.assertEqual(
            self.payload["corpus"]["canonical_path"], "data/poems.json"
        )
        for poet in VIZ19.TARGET_POETS:
            profile = self.payload["profiles"][poet]
            self.assertEqual(
                profile["canonical_evidence_count"], canonical_counts[poet]
            )
            self.assertGreaterEqual(
                profile["analysis_count"], profile["canonical_evidence_count"]
            )

    def test_reviewed_nodes_use_exact_canonical_ids_and_poem_page_links(self) -> None:
        canonical_by_id = {
            (
                str(row.get("poet") or row.get("author") or ""),
                str(row["source_poem_id"]),
            ): row
            for row in self.canonical
        }
        seen_node_ids = set()
        for poet in VIZ19.TARGET_POETS:
            for node in self.payload["profiles"][poet]["nodes"]:
                seen_node_ids.add(node["id"])
                canonical_id = VIZ19.JOURNEY_CANONICAL_IDS[node["id"]]
                canonical = canonical_by_id[(poet, canonical_id)]
                self.assertEqual(node["canonical_poem_id"], canonical_id)
                self.assertEqual(node["linked_poem"]["canonical_poem_id"], canonical_id)
                self.assertEqual(node["poem_body"], canonical["body"])
                self.assertEqual(node["linked_poem"]["title"], canonical["title"])
                self.assertTrue(node["work_id"].startswith("fw_"))
                self.assertEqual(node["linked_poem"]["work_id"], node["work_id"])
                self.assertEqual(
                    node["poem_page_href"], f"44_诗页.html#poem={canonical_id}"
                )
        self.assertEqual(seen_node_ids, set(VIZ19.JOURNEY_CANONICAL_IDS))
        self.assertIn('href="44_诗页.html"', VIZ19.APP_TEMPLATE)
        self.assertIn("赏析诗页", VIZ19.APP_TEMPLATE)

    def test_same_title_collision_resolves_only_by_canonical_id(self) -> None:
        canonical = [
            {
                "poet": "甲",
                "title": "同题",
                "body": "第一首正文",
                "source_poem_id": "id-a",
            },
            {
                "poet": "甲",
                "title": "同题",
                "body": "第二首正文",
                "source_poem_id": "id-b",
            },
        ]
        analysis = [
            {
                "poet": "甲",
                "title": "同题",
                "body": "第一首正文",
                "work_id": "fw-a",
                "canonical_gushiwen_id": "id-a",
                "sources": [],
            },
            {
                "poet": "甲",
                "title": "同题",
                "body": "第二首正文",
                "work_id": "fw-b",
                "canonical_gushiwen_id": "id-b",
                "sources": [],
            },
        ]
        canonical_by_id, analysis_by_id = VIZ19.build_identity_indexes(
            canonical, analysis
        )
        node = {"id": "node-b", "linked_poem": {"title": "同题"}}
        poem, work = VIZ19.resolve_node_poem(
            "甲",
            node,
            canonical_by_id,
            analysis_by_id,
            identity_map={"node-b": "id-b"},
        )
        self.assertEqual(poem["body"], "第二首正文")
        self.assertEqual(work["work_id"], "fw-b")
        with self.assertRaises(KeyError):
            VIZ19.resolve_node_poem(
                "甲", node, canonical_by_id, analysis_by_id, identity_map={}
            )

    def test_ambiguous_legacy_context_does_not_cross_link_same_title(self) -> None:
        groups = {
            "甲": {
                "nodes": [
                    {"id": "n-a", "linked_poem": {"title": "同题"}},
                    {"id": "n-b", "linked_poem": {"title": "同题"}},
                ]
            }
        }
        with self.assertRaises(ValueError):
            VIZ19.bind_contexts_to_canonical_ids(
                {("甲", "同题"): {"source_name": "测试"}},
                groups,
                identity_map={"n-a": "id-a", "n-b": "id-b"},
            )


if __name__ == "__main__":
    unittest.main()
