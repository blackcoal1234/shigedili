from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from poetry_agent.glossary import PoetryGlossary


PROJECT_ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "offline_poetry_glossary", PROJECT_ROOT / "data" / "poetry_glossary.py"
)
assert SPEC and SPEC.loader
offline = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = offline
SPEC.loader.exec_module(offline)


def entry(term_id: str, forms: list[str], **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "term_id": term_id,
        "forms": forms,
        "definition": "definition",
        "in_context": "context",
        "category": "category",
        "source_note": "source",
        "status": "published",
    }
    value.update(overrides)
    return value


class PoetryGlossaryTests(unittest.TestCase):
    def write_glossary(self, root: Path, entries: list[dict[str, object]]) -> Path:
        path = root / "glossary.json"
        path.write_text(
            json.dumps({"glossaryVersion": "test-v1", "entries": entries}, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def test_chang_gan_sample_has_expected_line_relative_matches(self) -> None:
        records = json.loads((PROJECT_ROOT / "data" / "poems.json").read_text(encoding="utf-8-sig"))
        poem = next(row for row in records if row.get("source_poem_id") == "2d0368e3fb76")
        lines = [
            {"lineNo": line_no, "text": text}
            for line_no, text in enumerate(str(poem["body"]).splitlines(), 1)
        ]
        glossary = PoetryGlossary(PROJECT_ROOT)
        matches = glossary.match_lines(lines)
        self.assertEqual("1.0.0", glossary.snapshot().version)
        self.assertEqual(
            ["初覆额", "竹马", "青梅", "长干", "无嫌猜", "抱柱信", "望夫台", "瞿塘", "滟滪堆"],
            [match["term"] for match in matches],
        )
        for match in matches:
            line = lines[match["lineNo"] - 1]["text"]
            self.assertEqual(match["term"], line[match["startOffset"] : match["endOffset"]])

    def test_backend_longest_match_compares_actual_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write_glossary(root, [entry("first", ["abcdef", "ab"]), entry("second", ["abcd"])])
            matches = PoetryGlossary(root, path).match_lines([{"lineNo": 3, "text": "abcd"}])
        self.assertEqual([("second", 0, 4)], [(m["termId"], m["startOffset"], m["endOffset"]) for m in matches])

    def test_backend_preserves_dictionary_entry_and_form_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write_glossary(root, [entry("first", ["abcdef", "ab"]), entry("second", ["abcd"])])
            snapshot = PoetryGlossary(root, path).snapshot()
        self.assertEqual(["first", "second"], [item.term_id for item in snapshot.entries])
        self.assertEqual(("abcdef", "ab"), snapshot.entries[0].forms)

    def test_only_literal_status_published_is_loaded_by_both_loaders(self) -> None:
        entries = [
            entry("live", ["live"]),
            entry("review", ["review"], status="draft", review_status="published"),
            entry("boolean", ["boolean"], status="draft", published=True),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write_glossary(root, entries)
            backend = PoetryGlossary(root, path).snapshot()
            _, local = offline.load_glossary(path)
        self.assertEqual(["live"], [item.term_id for item in backend.entries])
        self.assertEqual(["live"], [item.term_id for item in local])

    def test_published_top_level_container_is_rejected_by_both_loaders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "glossary.json"
            path.write_text(
                json.dumps({"glossaryVersion": "test-v1", "published": [entry("live", ["live"])]}),
                encoding="utf-8",
            )
            self.assertIsNotNone(PoetryGlossary(root, path).snapshot().error)
            with self.assertRaises(ValueError):
                offline.load_glossary(path)

    def test_duplicate_term_ids_and_forms_are_rejected(self) -> None:
        cases = [
            [entry("same", ["one"]), entry("same", ["two"])],
            [entry("one", ["same"]), entry("two", ["same"])],
        ]
        for entries in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = self.write_glossary(root, entries)
                self.assertIsNotNone(PoetryGlossary(root, path).snapshot().error)
                with self.assertRaises(ValueError):
                    offline.load_glossary(path)

    def test_missing_required_fields_and_short_forms_are_rejected(self) -> None:
        cases = [entry("missing", ["valid"], category=""), entry("short", ["字"])]
        for invalid in cases:
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = self.write_glossary(root, [invalid])
                self.assertIsNotNone(PoetryGlossary(root, path).snapshot().error)
                with self.assertRaises(ValueError):
                    offline.load_glossary(path)

    def test_offline_longest_match_preserves_order_for_equal_lengths(self) -> None:
        entries = (
            offline.GlossaryEntry("short", "ab", "d", "c", "g", "s"),
            offline.GlossaryEntry("long", "abcd", "d", "c", "g", "s"),
            offline.GlossaryEntry("tie", "abcd", "d", "c", "g", "s"),
        )
        self.assertEqual("long", offline.match_text("abcd", entries)[0].entry.term_id)

    def test_glossed_html_escapes_text_and_attributes(self) -> None:
        item = offline.GlossaryEntry('id"<&', "明月", "d", "c", "g", "s")
        rendered = offline.glossed_html("<明月&", [item])
        self.assertEqual(
            '&lt;<button type="button" class="gloss-term" data-gloss-id="id&quot;&lt;&amp;" '
            'aria-label="明月">明月</button>&amp;',
            rendered,
        )

    def test_missing_dictionary_is_diagnostic_and_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            glossary = PoetryGlossary(Path(directory))
            self.assertEqual([], glossary.match_lines([]))
            self.assertIn("不存在", glossary.snapshot().error or "")


if __name__ == "__main__":
    unittest.main()
