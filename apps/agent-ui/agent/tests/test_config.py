from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from poetry_agent.cache import SnapshotRepository
from poetry_agent.config import Settings, discover_project_root
from poetry_agent.health import health_payload


class SettingsTests(unittest.TestCase):
    def test_missing_model_configuration_is_degraded_but_constructible(self) -> None:
        root = discover_project_root()
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings.from_env(
                {"AGENT_CACHE_DIR": directory}, project_root=root
            )
            self.assertFalse(settings.model_configured)
            self.assertFalse(settings.embedding_configured)
            self.assertEqual("https://api.siliconflow.cn/v1", settings.embedding_base_url)
            self.assertEqual("BAAI/bge-m3", settings.embedding_model)
            self.assertEqual(8, settings.embedding_concurrency)
            self.assertEqual(
                {
                    "AGENT_LLM_BASE_URL",
                    "AGENT_LLM_API_KEY",
                    "AGENT_LLM_MODEL",
                },
                set(settings.missing_model_settings),
            )
            self.assertEqual(
                {
                    "AGENT_EMBEDDING_API_KEY",
                },
                set(settings.missing_embedding_settings),
            )
            result = health_payload(
                settings,
                SnapshotRepository(root, Path(directory)),
                "degraded_langgraph",
            )
            self.assertEqual("degraded", result["status"])
            self.assertFalse(result["agent"]["modelConfigured"])
            self.assertEqual(8123, result["port"])

    def test_cache_directory_rejects_data_and_output_trees_case_insensitively(self) -> None:
        root = discover_project_root()
        forbidden = (
            root / "data",
            root / "data" / "agent-cache",
            root / "output",
            root / "output" / "agent-cache",
            Path(str(root / "data" / "agent-cache").upper()),
            Path(str(root / "output" / "agent-cache").upper()),
        )
        for cache_dir in forbidden:
            with self.subTest(cache_dir=cache_dir):
                with self.assertRaisesRegex(ValueError, "data/output"):
                    Settings.from_env(
                        {"AGENT_CACHE_DIR": str(cache_dir)}, project_root=root
                    )

    def test_similarly_named_cache_directory_outside_data_output_is_allowed(self) -> None:
        root = discover_project_root()
        cache_dir = root / "data-cache" / "agent"
        settings = Settings.from_env(
            {"AGENT_CACHE_DIR": str(cache_dir)}, project_root=root
        )
        self.assertEqual(cache_dir.resolve(), settings.cache_dir)

    def test_siliconflow_embedding_configuration_is_independent_and_bounded(self) -> None:
        root = discover_project_root()
        settings = Settings.from_env(
            {
                "AGENT_EMBEDDING_API_KEY": "private",
                "AGENT_EMBEDDING_MODEL": "BAAI/bge-m3",
                "AGENT_EMBEDDING_BATCH_SIZE": "32",
                "AGENT_EMBEDDING_CONCURRENCY": "16",
                "AGENT_EMBEDDING_TIMEOUT": "12",
                "AGENT_EMBEDDING_RETRIES": "2",
            },
            project_root=root,
        )
        self.assertTrue(settings.embedding_configured)
        self.assertEqual(32, settings.embedding_batch_size)
        self.assertEqual(16, settings.embedding_concurrency)
        self.assertEqual(12.0, settings.embedding_timeout)
        self.assertEqual(2, settings.embedding_retries)
        self.assertNotIn("AGENT_EMBEDDING_BASE_URL", settings.missing_embedding_settings)
        incomplete = Settings.from_env(
            {
                "AGENT_EMBEDDING_BASE_URL": "",
                "AGENT_EMBEDDING_API_KEY": "private",
                "AGENT_EMBEDDING_MODEL": "BAAI/bge-m3",
            },
            project_root=root,
        )
        self.assertFalse(incomplete.embedding_configured)
        self.assertIn("AGENT_EMBEDDING_BASE_URL", incomplete.missing_embedding_settings)
        with self.assertRaisesRegex(ValueError, "CONCURRENCY"):
            Settings.from_env(
                {"AGENT_EMBEDDING_CONCURRENCY": "65"}, project_root=root
            )
        with self.assertRaisesRegex(ValueError, "BATCH_SIZE"):
            Settings.from_env(
                {"AGENT_EMBEDDING_BATCH_SIZE": "33"}, project_root=root
            )


if __name__ == "__main__":
    unittest.main()
