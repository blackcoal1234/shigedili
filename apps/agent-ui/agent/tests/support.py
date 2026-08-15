from __future__ import annotations

import json
from pathlib import Path

from poetry_agent.cache import (
    IMAGERY_SPEC,
    YEAR_SPEC,
    DatasetSnapshot,
    sha256_file,
    validate_imagery_data,
    validate_poems,
    validate_year_data,
)


class StaticRepository:
    """Read current authoritative outputs without exercising refresh in service tests."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self._poems = None
        self._datasets = {}

    @staticmethod
    def _read(path: Path):
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def load_poems(self):
        path = self.project_root / "data" / "poems.json"
        if self._poems is None:
            self._poems = self._read(path)
            validate_poems(self._poems)
        return self._poems, {"data/poems.json": sha256_file(path)}

    def ensure_dataset(self, spec):
        path = self.project_root / spec.generated_json
        if spec.key not in self._datasets:
            data = self._read(path)
            if spec.key == YEAR_SPEC.key:
                validate_year_data(data)
            elif spec.key == IMAGERY_SPEC.key:
                validate_imagery_data(data)
            else:
                spec.validator(data)
            self._datasets[spec.key] = data
        data = self._datasets[spec.key]
        return DatasetSnapshot(
            data=data,
            source_hashes={spec.generated_json: sha256_file(path)},
            cache_path=path,
            refreshed=False,
        )
