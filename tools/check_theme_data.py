"""检查主题版语料、行旅、创作背景与精神地形图数据契约。"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

POEMS_JSON = ROOT / "data" / "poems.json"
JOURNEYS_JSON = ROOT / "data" / "reviewed" / "poet_journeys.json"
CONTEXTS_CSV = ROOT / "data" / "reviewed" / "verified_poem_contexts.csv"
SPIRIT_CHRONOLOGY_CSV = ROOT / "data" / "candidates" / "libai_spirit_chronology.csv"
SPIRIT_PAGE = ROOT / "output" / "20_诗人精神地形图.html"
TARGET_POETS = ("李白", "杜甫", "白居易", "苏轼", "陆游", "李清照")
ALLOWED_GRADES = {"A", "B", "C", "D"}
# 有系年争议、来源备注必须非空的诗（诚实性红线 4）
SPIRIT_CONTROVERSY_TITLES = {"蜀道难", "将进酒", "独坐敬亭山", "登金陵凤凰台"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def flatten_journeys(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    require(isinstance(payload, dict), "poet_journeys.json 顶层必须是对象或数组")
    if isinstance(payload.get("journeys"), list):
        return payload["journeys"]
    rows: list[dict[str, object]] = []
    for poet_row in payload.get("poets", []):
        require(isinstance(poet_row, dict), "poets 中必须是对象")
        poet = poet_row.get("poet") or poet_row.get("name")
        for event in poet_row.get(
            "events",
            poet_row.get("nodes", poet_row.get("stops", [])),
        ):
            require(isinstance(event, dict), "events 中必须是对象")
            item = dict(event)
            item.setdefault("poet", poet)
            rows.append(item)
    return rows


def value(row: dict[str, object], *keys: str) -> object:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row[key]
    return ""


def check_poems() -> tuple[list[dict[str, object]], set[tuple[str, str]]]:
    poems = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    # 2026-07 语料扩容（李白 55 首）后的新基线，防止语料回退
    require(len(poems) >= 1770, f"基础语料不足：{len(poems)}")
    poet_counts = Counter(str(row.get("poet") or row.get("author") or "") for row in poems)
    require(len(poet_counts) >= 80, f"诗人数不足：{len(poet_counts)}")
    for poet in TARGET_POETS:
        require(poet_counts[poet] >= 20, f"{poet}作品不足20首")

    seen: set[tuple[str, str]] = set()
    titles: set[tuple[str, str]] = set()
    for row in poems:
        poet = str(row.get("poet") or row.get("author") or "")
        title = str(row.get("title") or "")
        body = str(row.get("body") or "")
        require(poet and title and body, "诗词存在空作者、标题或正文")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        key = (poet, digest)
        require(key not in seen, f"重复正文：{poet}《{title}》")
        seen.add(key)
        titles.add((poet, title))
    print(f"[ok] 基础语料：{len(poems)}首 / {len(poet_counts)}位诗人")
    return poems, titles


def check_journeys() -> list[dict[str, object]]:
    require(JOURNEYS_JSON.exists(), f"缺少 {JOURNEYS_JSON}")
    payload = json.loads(JOURNEYS_JSON.read_text(encoding="utf-8-sig"))
    rows = flatten_journeys(payload)
    counts = Counter()
    for index, row in enumerate(rows, start=1):
        poet = str(value(row, "poet", "name"))
        counts[poet] += 1
        require(poet in TARGET_POETS, f"行旅第{index}条诗人不在目标名单：{poet}")
        require(value(row, "year_start", "year") != "", f"行旅第{index}条缺年份")
        require(value(row, "event_title", "event", "title") != "", f"行旅第{index}条缺事件")
        require(
            value(row, "historical_place", "place_historical", "place") != "",
            f"行旅第{index}条缺历史地点",
        )
        require(
            value(row, "modern_city", "modern_place", "place_modern") != "",
            f"行旅第{index}条缺现代城市",
        )
        require(
            value(row, "lon", "longitude") != ""
            and value(row, "lat", "latitude") != "",
            f"行旅第{index}条缺坐标",
        )
        grade = str(value(row, "fact_grade", "source_level") or "C").upper()
        require(grade in ALLOWED_GRADES, f"行旅第{index}条来源等级非法")
        source_url = str(value(row, "source_url"))
        require(source_url.startswith("http"), f"行旅第{index}条缺可访问来源URL")
        require(value(row, "source_name") != "", f"行旅第{index}条缺来源名称")
    for poet in TARGET_POETS:
        require(counts[poet] >= 5, f"{poet}行旅节点不足5条")
    print(f"[ok] 行旅数据：{len(rows)}条 / " + "、".join(f"{p}{counts[p]}" for p in TARGET_POETS))
    return rows


def check_contexts(titles: set[tuple[str, str]]) -> list[dict[str, str]]:
    require(CONTEXTS_CSV.exists(), f"缺少 {CONTEXTS_CSV}")
    with CONTEXTS_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    require(len(rows) >= 20, f"创作背景不足20条：{len(rows)}")
    counts = Counter()
    for index, row in enumerate(rows, start=1):
        poet = (row.get("poet") or "").strip()
        title = (row.get("title") or "").strip()
        counts[poet] += 1
        require((poet, title) in titles, f"背景第{index}条未匹配现有作品：{poet}《{title}》")
        require(row.get("year_start") or row.get("year"), f"背景第{index}条缺年份")
        require(row.get("modern_city") or row.get("modern_place"), f"背景第{index}条缺现代城市")
        require(row.get("lon") and row.get("lat"), f"背景第{index}条缺坐标")
        require((row.get("source_url") or "").startswith("http"), f"背景第{index}条缺来源URL")
        require((row.get("fact_grade") or "C").upper() in ALLOWED_GRADES, f"背景第{index}条等级非法")
    for poet in TARGET_POETS:
        require(counts[poet] >= 3, f"{poet}创作背景不足3条")
    print(f"[ok] 创作背景：{len(rows)}条 / " + "、".join(f"{p}{counts[p]}" for p in TARGET_POETS))
    return rows


def check_spirit_dict() -> None:
    from data.spirit_image_dict import CLUSTERS, SPIRIT_DICT

    require(len(CLUSTERS) == 5 and len(set(CLUSTERS)) == 5, "情感簇必须为五个且不重复")
    seen_words: set[str] = set()
    for row in SPIRIT_DICT:
        require(len(row) == 6, f"词条结构必须为六元组：{row!r}")
        word, _category, cluster, sentiment, scale, basis = row
        require(bool(str(word).strip()), "词条存在空词")
        require(word not in seen_words, f"词典存在重复词条：{word}")
        seen_words.add(word)
        require(cluster is None or cluster in CLUSTERS, f"{word} 情感簇非法：{cluster!r}")
        require(-1.0 <= float(sentiment) <= 1.0, f"{word} 情感值超出 [-1,1]：{sentiment}")
        if scale is None:
            require(not str(basis).strip(), f"{word} 无尺度却填了尺度依据")
        else:
            require(isinstance(scale, int) and 1 <= scale <= 5, f"{word} 空间尺度非法：{scale!r}")
            require(bool(str(basis).strip()), f"{word} 有尺度但缺尺度依据")
    clustered = sum(1 for row in SPIRIT_DICT if row[2] is not None)
    scaled = sum(1 for row in SPIRIT_DICT if row[4] is not None)
    print(f"[ok] 精神意象词典：{len(SPIRIT_DICT)}词条 / 归簇{clustered} / 有尺度{scaled}")


def check_spirit_chronology() -> None:
    require(SPIRIT_CHRONOLOGY_CSV.exists(), f"缺少候选编年：{SPIRIT_CHRONOLOGY_CSV}")
    with SPIRIT_CHRONOLOGY_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    require(len(rows) >= 20, f"李白候选编年不足20条：{len(rows)}")
    period_counts: Counter[str] = Counter()
    for index, row in enumerate(rows, start=1):
        title = (row.get("title") or "").strip()
        status = (row.get("status") or "").strip()
        require(
            status in {"candidate", "superseded_by_verified"},
            f"编年第{index}条状态非法（候选表只允许 candidate/superseded_by_verified）：{status}",
        )
        require((row.get("source_name") or "").strip() != "", f"编年第{index}条缺来源名称（红线1）：{title}")
        grade = (row.get("fact_grade") or "").strip().upper()
        require(grade in {"A", "B", "C"}, f"编年第{index}条等级非法：{grade}")
        if grade in {"A", "B"}:
            require(
                (row.get("source_url") or "").startswith("http"),
                f"编年第{index}条 {grade} 级缺可核实来源URL：{title}",
            )
        require(str(row.get("year_start") or "").strip().isdigit(), f"编年第{index}条缺起始年：{title}")
        require(str(row.get("year_end") or "").strip().isdigit(), f"编年第{index}条缺结束年：{title}")
        if title in SPIRIT_CONTROVERSY_TITLES:
            require(
                (row.get("source_note") or "").strip() != "",
                f"系年争议诗《{title}》缺争议备注（红线4）",
            )
        period_counts[str(row.get("period") or "").strip()] += 1
    # 期1（蜀中）目前没有可引用的编年记录，如实留空、不虚构；期2–5 每期至少 3 条
    for period in ("2", "3", "4", "5"):
        require(
            period_counts.get(period, 0) >= 3,
            f"第{period}期候选编年不足3条：{period_counts.get(period, 0)}",
        )
    summary = "、".join(f"期{p}×{period_counts[p]}" for p in sorted(period_counts))
    print(f"[ok] 李白候选编年：{len(rows)}条（{summary}；期1蜀中如实留空）")


def check_spirit_page() -> None:
    require(SPIRIT_PAGE.exists(), f"缺少精神地形图页面：{SPIRIT_PAGE}")
    html = SPIRIT_PAGE.read_text(encoding="utf-8")
    require("echarts.init" in html, "精神地形图页面缺少 echarts 初始化")
    require(
        'src="assets/pyecharts/v6/echarts.min.js"' in html,
        "精神地形图页面未引用本地 ECharts 资源",
    )
    require("推定" in html and "controversy" in html, "精神地形图页面缺少推定/争议样式标注")
    print(f"[ok] 精神地形图页面：{SPIRIT_PAGE.name}（含 echarts 初始化与推定标注）")


def main() -> None:
    _, titles = check_poems()
    check_journeys()
    check_contexts(titles)
    check_spirit_dict()
    check_spirit_chronology()
    check_spirit_page()
    print("[ok] 主题数据契约全部通过")


if __name__ == "__main__":
    main()
