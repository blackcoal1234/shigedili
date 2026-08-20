from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = PROJECT_ROOT / "data"
if str(DATA_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_DIR))

from classical_emotion_lexicon import EMOTION_SPECS, validate  # noqa: E402
from classical_emotion_model import classify_text  # noqa: E402


class ClassicalEmotionLexiconTests(unittest.TestCase):
    def test_validate_and_public_identifiers_are_unique(self) -> None:
        result = validate()

        self.assertEqual(len(EMOTION_SPECS), result["emotions"])
        self.assertGreater(result["keywords"], 0)
        self.assertEqual(len(EMOTION_SPECS), len(set(EMOTION_SPECS)))
        labels = [str(spec["label"]) for spec in EMOTION_SPECS.values()]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertTrue(all(emotion_id.isascii() for emotion_id in EMOTION_SPECS))

    def test_longest_keyword_wins_within_one_label(self) -> None:
        profile = classify_text("泪满衣襟")
        grief = next(row for row in profile["top_emotions"] if row["id"] == "grief")

        self.assertIn("泪满", grief["evidence"])
        self.assertNotIn("泪", grief["evidence"])


class ClassicalEmotionNegationTests(unittest.TestCase):
    def assert_emotion_absent(self, text: str, *emotion_ids: str) -> None:
        actual = {row["id"] for row in classify_text(text)["top_emotions"]}
        for emotion_id in emotion_ids:
            self.assertNotIn(emotion_id, actual, msg=f"{text!r} incorrectly matched {emotion_id}")

    def test_excluded_names_and_fixed_phrases(self) -> None:
        for text in ("莫愁", "长乐", "乐府"):
            with self.subTest(text=text):
                self.assert_emotion_absent(text, "joyful", "grief", "anxious_state")

    def test_negated_emotion_phrases_are_not_evidence(self) -> None:
        cases = (
            ("不悲", ("grief",)),
            ("不恨", ("grief", "indignant")),
            ("未伤心", ("grief",)),
            ("不相思", ("romantic", "boudoir_longing")),
        )
        for text, emotion_ids in cases:
            with self.subTest(text=text):
                self.assert_emotion_absent(text, *emotion_ids)


class ClassicalEmotionFineGrainedTests(unittest.TestCase):
    def test_new_fine_grained_labels_have_direct_positive_examples(self) -> None:
        cases = {
            "boudoir_longing": "独守空闺",
            "spring_regret": "惜春长怕花开早",
            "autumn_decline": "秋风萧瑟",
            "career_conflict": "穷则独善其身",
            "unrecognized_talent": "怀才不遇",
            "zen_awakened": "菩提本无树",
            "landscape_appreciation": "江山如画",
            "gratitude_exchange": "投我以木桃报之以琼瑶",
        }
        for expected, text in cases.items():
            with self.subTest(expected=expected, text=text):
                actual = {row["id"] for row in classify_text(text)["top_emotions"]}
                self.assertIn(expected, actual)

    def test_classify_text_output_contract_and_bounds(self) -> None:
        profile = classify_text("菩提本无树，江山如画。", title="山中偶题")
        required = {
            "primary", "primary_label", "family", "color", "top_emotions",
            "adjectives", "summary", "valence", "arousal", "dominance",
            "confidence", "confidence_label", "mixed", "rule_hits", "evidence",
        }

        self.assertTrue(required.issubset(profile))
        self.assertLessEqual(len(profile["top_emotions"]), 3)
        self.assertGreaterEqual(profile["valence"], -1.0)
        self.assertLessEqual(profile["valence"], 1.0)
        self.assertGreaterEqual(profile["arousal"], 0.0)
        self.assertLessEqual(profile["arousal"], 1.0)
        self.assertGreaterEqual(profile["dominance"], -1.0)
        self.assertLessEqual(profile["dominance"], 1.0)
        self.assertGreaterEqual(profile["confidence"], 0.0)
        self.assertLessEqual(profile["confidence"], 1.0)

    def test_empty_text_uses_the_same_contract(self) -> None:
        profile = classify_text("")

        self.assertIsNone(profile["primary"])
        self.assertEqual([], profile["top_emotions"])
        self.assertEqual(0, profile["rule_hits"])
        self.assertEqual(0.0, profile["valence"])
        self.assertEqual(0.35, profile["arousal"])
        self.assertEqual(0.0, profile["dominance"])


if __name__ == "__main__":
    unittest.main()
