"""检查“唐宋诗歌创作活动中心迁移”模块的数据与离线产物。"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "reviewed" / "verified_poem_contexts.csv"
POEMS_PATH = ROOT / "data" / "poems.json"
SCRIPT_PATH = ROOT / "数据可视化脚本" / "viz_16_literary_centers.py"
OUTPUT_PATH = ROOT / "output" / "16_唐宋诗歌创作活动中心迁移.html"

TARGET_POETS = {"李白", "杜甫", "白居易", "苏轼", "陆游", "李清照"}
EXPECTED_FIELDS = [
    "poet",
    "title",
    "dynasty",
    "year_start",
    "year_end",
    "historical_place",
    "modern_city",
    "province",
    "lon",
    "lat",
    "source_name",
    "source_url",
    "source_note",
    "fact_grade",
    "status",
]
LIFE_RANGES = {
    "李白": (701, 762),
    "杜甫": (712, 770),
    "白居易": (772, 846),
    "苏轼": (1037, 1101),
    "陆游": (1125, 1210),
    "李清照": (1084, 1156),
}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def load_poems() -> tuple[set[tuple[str, str, str]], int]:
    records = json.loads(POEMS_PATH.read_text(encoding="utf-8"))
    keys = {
        (
            str(row.get("poet") or row.get("author") or "").strip(),
            str(row.get("title") or "").strip(),
            str(row.get("dynasty") or "").strip(),
        )
        for row in records
    }
    target_count = sum(
        1
        for row in records
        if str(row.get("poet") or row.get("author") or "").strip() in TARGET_POETS
    )
    return keys, target_count


def check_csv(errors: list[str]) -> dict[str, object]:
    if not CSV_PATH.exists():
        fail(errors, f"缺少审核数据：{CSV_PATH}")
        return {}

    poem_keys, target_count = load_poems()
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != EXPECTED_FIELDS:
            fail(errors, f"CSV字段不一致：{reader.fieldnames}")
        rows = list(reader)

    # verified_poem_contexts.csv 还会服务生命轨迹等模块。文化中心页保持
    # 六位核心诗人可比样本，只校验并统计该研究范围内的记录。
    rows = [
        row
        for row in rows
        if str(row.get("poet") or "").strip() in TARGET_POETS
    ]

    if len(rows) < 20:
        fail(errors, f"审核样本不足20条：{len(rows)}")

    duplicates: set[tuple[str, str]] = set()
    seen: set[tuple[str, str]] = set()
    poet_counts = Counter()
    grade_counts = Counter()
    approved_mappable = 0

    for line_no, row in enumerate(rows, start=2):
        poet = str(row.get("poet") or "").strip()
        title = str(row.get("title") or "").strip()
        dynasty = str(row.get("dynasty") or "").strip()
        key = (poet, title)

        if key in seen:
            duplicates.add(key)
        seen.add(key)
        poet_counts[poet] += 1
        grade_counts[str(row.get("fact_grade") or "").strip().upper()] += 1

        if (poet, title, dynasty) not in poem_keys:
            fail(errors, f"第{line_no}行无法与 poems.json 精确匹配：{poet}《{title}》/{dynasty}")
        if str(row.get("status") or "").strip() != "approved":
            fail(errors, f"第{line_no}行不是 approved：{poet}《{title}》")
        if str(row.get("fact_grade") or "").strip().upper() not in {"A", "B", "C"}:
            fail(errors, f"第{line_no}行证据等级无效：{row.get('fact_grade')}")
        if not str(row.get("historical_place") or "").strip():
            fail(errors, f"第{line_no}行缺 historical_place")
        if not str(row.get("modern_city") or "").strip():
            fail(errors, f"第{line_no}行缺 modern_city")
        if not str(row.get("province") or "").strip():
            fail(errors, f"第{line_no}行缺 province")
        if not str(row.get("source_name") or "").strip():
            fail(errors, f"第{line_no}行缺 source_name")
        if not str(row.get("source_url") or "").strip().startswith("https://"):
            fail(errors, f"第{line_no}行 source_url 不是 HTTPS")
        if len(str(row.get("source_note") or "").strip()) < 18:
            fail(errors, f"第{line_no}行 source_note 过短，无法支持审核")

        try:
            start = int(str(row.get("year_start") or "").strip())
            end = int(str(row.get("year_end") or "").strip())
            lon = float(str(row.get("lon") or "").strip())
            lat = float(str(row.get("lat") or "").strip())
        except ValueError:
            fail(errors, f"第{line_no}行年份或坐标不是有效数值")
            continue

        if start > end:
            fail(errors, f"第{line_no}行年份区间倒置：{start}-{end}")
        life_start, life_end = LIFE_RANGES.get(poet, (0, 9999))
        if start < life_start or end > life_end:
            fail(errors, f"第{line_no}行年份超出诗人生卒范围：{poet} {start}-{end}")
        if not (73.0 <= lon <= 136.0 and 18.0 <= lat <= 54.0):
            fail(errors, f"第{line_no}行坐标超出中国范围：{lon},{lat}")
        else:
            approved_mappable += 1

    if duplicates:
        fail(errors, f"存在重复作者/诗题：{sorted(duplicates)}")
    missing_poets = TARGET_POETS - set(poet_counts)
    if missing_poets:
        fail(errors, f"缺少目标诗人：{sorted(missing_poets)}")
    for poet in sorted(TARGET_POETS):
        if poet_counts[poet] < 3:
            fail(errors, f"{poet}审核样本少于3条：{poet_counts[poet]}")

    return {
        "rows": len(rows),
        "approved_mappable": approved_mappable,
        "target_poems": target_count,
        "coverage": (100.0 * approved_mappable / target_count) if target_count else 0.0,
        "poet_counts": dict(poet_counts),
        "grade_counts": dict(grade_counts),
    }


def check_script(errors: list[str]) -> None:
    if not SCRIPT_PATH.exists():
        fail(errors, f"缺少可视化脚本：{SCRIPT_PATH}")
        return
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    required_tokens = [
        "verified_poem_contexts.csv",
        'status != "approved"',
        "GRADE_WEIGHT",
        "WORK_WEIGHT = 0.45",
        "POET_WEIGHT = 0.35",
        "EVIDENCE_WEIGHT = 0.20",
        "Timeline",
        "Geo",
        "assets/pyecharts/v6/maps/china.js",
        "不使用诗中提及地",
    ]
    for token in required_tokens:
        if token not in source:
            fail(errors, f"可视化脚本缺少关键实现：{token}")


def check_output(errors: list[str]) -> dict[str, object]:
    if not OUTPUT_PATH.exists():
        fail(errors, f"缺少输出页面，请先运行 viz_16_literary_centers.py：{OUTPUT_PATH}")
        return {}
    size = OUTPUT_PATH.stat().st_size
    if size < 50_000:
        fail(errors, f"输出页面体积异常：{size} bytes")
    html = OUTPUT_PATH.read_text(encoding="utf-8")
    required_tokens = [
        "唐宋诗歌创作活动中心迁移",
        "综合活跃度公式",
        "全部单项指标",
        "探索性",
        "创作活动分布",
        "不能代表唐宋全部诗歌",
        "不使用诗中提及地",
        "assets/pyecharts/v6/echarts.min.js",
        "assets/pyecharts/v6/maps/china.js",
    ]
    for token in required_tokens:
        if token not in html:
            fail(errors, f"输出页面缺少关键信息：{token}")
    if "https://assets.pyecharts.org" in html:
        fail(errors, "输出页面仍引用 pyecharts 远程资源")
    if "data:image" in html:
        fail(errors, "输出页面包含不必要的内嵌位图")
    return {"bytes": size}


def main() -> int:
    errors: list[str] = []
    csv_stats = check_csv(errors)
    check_script(errors)
    output_stats = check_output(errors)

    if errors:
        print("[FAIL] 唐宋诗歌创作活动中心迁移模块检查未通过：")
        for item in errors:
            print(f"  - {item}")
        return 1

    print("[OK] 唐宋诗歌创作活动中心迁移模块检查通过")
    print(
        "  数据："
        f"{csv_stats['approved_mappable']} / {csv_stats['rows']} 条审核记录入图；"
        f"覆盖目标诗作 {csv_stats['coverage']:.1f}%"
    )
    print(f"  诗人：{csv_stats['poet_counts']}")
    print(f"  等级：{csv_stats['grade_counts']}")
    print(f"  页面：{OUTPUT_PATH} ({output_stats['bytes']:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
