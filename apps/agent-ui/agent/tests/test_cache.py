from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from poetry_agent.cache import (
    DatasetSpec,
    SnapshotRepository,
    SourceDataError,
    sha256_file,
    sha256_source_file,
)


def validate_fixture(data):
    if data.get("schemaVersion") != "1.0" or "value" not in data:
        raise ValueError("invalid fixture")


class SnapshotRepositoryTests(unittest.TestCase):
    def test_source_hash_is_stable_across_lf_and_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.txt"
            source.write_bytes(b"first\nsecond\n")
            lf_hash = sha256_source_file(source)
            source.write_bytes(b"first\r\nsecond\r\n")

            self.assertEqual(lf_hash, sha256_source_file(source))
            self.assertNotEqual(sha256_file(source), sha256_source_file(source))

    def make_fixture(self, directory: str):
        root = Path(directory) / "project"
        cache = Path(directory) / "cache"
        source = root / "input" / "source.txt"
        generated = root / "output" / "assets" / "competition" / "fixture_data.json"
        source.parent.mkdir(parents=True)
        generated.parent.mkdir(parents=True)
        source.write_text("one", encoding="utf-8")
        spec = DatasetSpec(
            key="fixture",
            generated_json="output/assets/competition/fixture_data.json",
            generator="offline_generator.py",
            dependencies=("input/source.txt",),
            validator=validate_fixture,
            embedded_hash_path=("meta", "sourceHashes"),
            dependency_hash_keys=(("input/source.txt", "source.txt"),),
        )
        return root, cache, source, generated, spec

    @staticmethod
    def write_snapshot(generated: Path, source: Path, value: str) -> None:
        generated.write_text(
            json.dumps(
                {
                    "schemaVersion": "1.0",
                    "value": value,
                    "meta": {"sourceHashes": {"source.txt": sha256_file(source)}},
                }
            ),
            encoding="utf-8",
        )

    def test_existing_valid_snapshot_is_atomically_copied_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, cache, source, generated, spec = self.make_fixture(directory)
            self.write_snapshot(generated, source, "one")
            repository = SnapshotRepository(root, cache)

            first = repository.ensure_dataset(spec)
            second = repository.ensure_dataset(spec)

            self.assertTrue(first.refreshed)
            self.assertFalse(second.refreshed)
            self.assertEqual("one", second.data["value"])
            self.assertEqual(generated.read_bytes(), first.cache_path.read_bytes())
            manifest = json.loads((cache / "fixture.manifest.json").read_text())
            self.assertEqual(sha256_file(generated), manifest["cachedJsonSha256"])

            self.write_snapshot(generated, source, "external")
            refreshed = repository.ensure_dataset(spec)
            self.assertTrue(refreshed.refreshed)
            self.assertEqual("external", refreshed.data["value"])

    def test_stale_embedded_hash_requires_offline_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, cache, source, generated, spec = self.make_fixture(directory)
            self.write_snapshot(generated, source, "one")
            repository = SnapshotRepository(root, cache)
            repository.ensure_dataset(spec)
            cached_before = (cache / generated.name).read_bytes()
            generated_before = (sha256_file(generated), generated.stat().st_mtime_ns)

            source.write_text("two", encoding="utf-8")
            with self.assertRaisesRegex(SourceDataError, "请先运行离线生成器"):
                repository.ensure_dataset(spec)

            self.assertEqual(cached_before, (cache / generated.name).read_bytes())
            self.assertEqual(
                generated_before,
                (sha256_file(generated), generated.stat().st_mtime_ns),
            )

    def test_missing_snapshot_requires_offline_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, cache, _source, _generated, spec = self.make_fixture(directory)
            with self.assertRaisesRegex(SourceDataError, "请先运行离线生成器"):
                SnapshotRepository(root, cache).ensure_dataset(spec)

    def test_dataset_path_is_limited_to_competition_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, cache, source, generated, spec = self.make_fixture(directory)
            self.write_snapshot(generated, source, "one")
            outside_spec = DatasetSpec(
                key=spec.key,
                generated_json="output/fixture_data.json",
                generator=spec.generator,
                dependencies=spec.dependencies,
                validator=spec.validator,
                embedded_hash_path=spec.embedded_hash_path,
                dependency_hash_keys=spec.dependency_hash_keys,
            )
            with self.assertRaisesRegex(SourceDataError, "competition"):
                SnapshotRepository(root, cache).ensure_dataset(outside_spec)


if __name__ == "__main__":
    unittest.main()
