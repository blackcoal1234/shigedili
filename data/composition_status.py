"""考证作地样本状态统计。

该模块只读取本地 CSV，用于向入口页、验收单等交付页面解释：
candidate 可以按测试口径默认通过，但只有带有效经纬度的 approved 记录才会进入地图。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CANDIDATE_CSV = ROOT / "data" / "composition_place_candidates.csv"
REVIEW_CSV = ROOT / "data" / "composition_place_review_template.csv"
VERIFIED_CSV = ROOT / "data" / "verified_composition_places.csv"
LON_RANGE = (73.0, 136.0)
LAT_RANGE = (18.0, 54.0)
STATUS_NOTE = "测试口径，不代表全量真实考证；只有通过筛选且带有效经纬度的记录才进入足迹图。"


@dataclass(frozen=True)
class CompositionStatus:
    candidate_rows: int
    review_approved_rows: int
    verified_approved_rows: int
    mappable_approved_rows: int
    approved_without_coords: int
    note: str = STATUS_NOTE

    def as_dict(self) -> dict[str, int | str]:
        return {
            "candidate_rows": self.candidate_rows,
            "review_approved_rows": self.review_approved_rows,
            "verified_approved_rows": self.verified_approved_rows,
            "mappable_approved_rows": self.mappable_approved_rows,
            "approved_without_coords": self.approved_without_coords,
            "note": self.note,
        }


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _is_approved(row: dict[str, str]) -> bool:
    return (row.get("status") or "").strip() == "approved"


def _has_valid_coordinate(row: dict[str, str]) -> bool:
    if not (row.get("modern_place") or "").strip():
        return False
    try:
        lon = float((row.get("lon") or "").strip())
        lat = float((row.get("lat") or "").strip())
    except ValueError:
        return False
    return LON_RANGE[0] <= lon <= LON_RANGE[1] and LAT_RANGE[0] <= lat <= LAT_RANGE[1]


def composition_status() -> CompositionStatus:
    candidate_rows = read_rows(CANDIDATE_CSV)
    review_rows = read_rows(REVIEW_CSV)
    verified_rows = read_rows(VERIFIED_CSV)
    verified_approved = [row for row in verified_rows if _is_approved(row)]
    mappable = [row for row in verified_approved if _has_valid_coordinate(row)]
    return CompositionStatus(
        candidate_rows=sum(1 for row in candidate_rows if (row.get("status") or "").strip() == "candidate"),
        review_approved_rows=sum(1 for row in review_rows if _is_approved(row)),
        verified_approved_rows=len(verified_approved),
        mappable_approved_rows=len(mappable),
        approved_without_coords=len(verified_approved) - len(mappable),
    )
