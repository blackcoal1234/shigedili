"""校验诗人行旅与生命情感数据及离线页面。"""
from __future__ import annotations

import ast
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
DATA_JSON = ROOT / "data" / "reviewed" / "poet_journeys.json"
POEMS_JSON = ROOT / "data" / "poems.json"
VIZ_SCRIPT = ROOT / "数据可视化脚本" / "viz_15_journey_emotion.py"
OUT_HTML = ROOT / "output" / "15_诗人行旅与生命情感.html"
EXPECTED_POETS = {"李白", "杜甫", "白居易", "苏轼", "陆游", "李清照"}
VALID_LEVELS = {"A", "B", "C"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def require_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    require(bool(text), f"缺少必填文本：{label}")
    return text


def require_number(value: object, lower: float, upper: float, label: str) -> float:
    require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{label} 必须是数值")
    number = float(value)
    require(lower <= number <= upper, f"{label} 超出范围 {lower}..{upper}：{number}")
    return number


def load_poems() -> dict[tuple[str, str], str]:
    rows = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    require(isinstance(rows, list) and rows, "poems.json 必须是非空数组")
    return {
        (
            str(row.get("poet") or row.get("author") or ""),
            str(row.get("title") or ""),
        ): str(row.get("body") or "")
        for row in rows
    }


def validate_data() -> tuple[dict[str, object], list[dict[str, object]]]:
    require(DATA_JSON.exists(), f"缺少行旅审核数据：{DATA_JSON}")
    payload = json.loads(DATA_JSON.read_text(encoding="utf-8"))
    require(payload.get("schema_version") == "1.0", "schema_version 应为 1.0")

    methodology = payload.get("methodology")
    require(isinstance(methodology, dict), "缺少 methodology")
    line_semantics = require_text(methodology.get("line_semantics"), "methodology.line_semantics")
    require("不代表" in line_semantics and "道路" in line_semantics, "必须明确连线不代表真实道路")
    require(set(methodology.get("source_levels", {})) == VALID_LEVELS, "必须定义 A/B/C 三级来源")
    require(set(methodology.get("three_layers", {})) == {"journey_fact", "life_context", "text_emotion"}, "必须定义三层分析口径")

    groups = payload.get("poets")
    require(isinstance(groups, list), "poets 必须是数组")
    names = {str(group.get("poet") or "") for group in groups}
    require(names == EXPECTED_POETS, f"诗人覆盖不符合要求：{sorted(names)}")

    poems = load_poems()
    all_nodes: list[dict[str, object]] = []
    ids: set[str] = set()
    linked_pairs: set[tuple[str, str]] = set()

    for group in groups:
        poet = require_text(group.get("poet"), "poet")
        require_text(group.get("dynasty"), f"{poet}.dynasty")
        nodes = group.get("nodes")
        require(isinstance(nodes, list) and len(nodes) >= 5, f"{poet} 至少需要 5 个节点")

        route_orders = [node.get("route_order") for node in nodes]
        require(route_orders == list(range(1, len(nodes) + 1)), f"{poet} route_order 必须从 1 连续递增")
        years = [node.get("year") for node in nodes]
        require(years == sorted(years), f"{poet} 节点必须按年代升序")

        for node in nodes:
            node_id = require_text(node.get("id"), f"{poet}.node.id")
            require(node_id not in ids, f"节点 id 重复：{node_id}")
            ids.add(node_id)

            require(isinstance(node.get("year"), int), f"{node_id}.year 必须是整数")
            require(600 <= int(node["year"]) <= 1300, f"{node_id}.year 超出唐宋项目合理范围")
            require(node.get("year_precision") in {"year", "approximate"}, f"{node_id}.year_precision 无效")
            require_text(node.get("year_label"), f"{node_id}.year_label")
            require_text(node.get("place_historical"), f"{node_id}.place_historical")
            require_text(node.get("place_modern"), f"{node_id}.place_modern")
            require_text(node.get("event"), f"{node_id}.event")
            require_number(node.get("longitude"), 73, 136, f"{node_id}.longitude")
            require_number(node.get("latitude"), 15, 54, f"{node_id}.latitude")

            source_level = require_text(node.get("source_level"), f"{node_id}.source_level")
            require(source_level in VALID_LEVELS, f"{node_id}.source_level 无效")
            require_text(node.get("source_name"), f"{node_id}.source_name")
            source_url = require_text(node.get("source_url"), f"{node_id}.source_url")
            parsed_url = urlparse(source_url)
            require(parsed_url.scheme in {"http", "https"} and bool(parsed_url.netloc), f"{node_id}.source_url 不合法")
            note = require_text(node.get("note"), f"{node_id}.note")
            confidence = require_number(node.get("confidence"), 0, 1, f"{node_id}.confidence")
            if source_level == "C":
                require("推定" in note or "约" in note, f"{node_id} 为 C 级但 note 未明示推定")
                require(confidence <= 0.75, f"{node_id} 为 C 级但置信度过高")

            life = node.get("life_context")
            require(isinstance(life, dict), f"{node_id}.life_context 必须是对象")
            require_text(life.get("label"), f"{node_id}.life_context.label")
            require_number(life.get("external_pressure"), 0, 1, f"{node_id}.life_context.external_pressure")
            require(life.get("analysis_level") == "C", f"{node_id} 生平处境归纳必须标 C")
            require_text(life.get("reason"), f"{node_id}.life_context.reason")

            linked = node.get("linked_poem")
            require(isinstance(linked, dict), f"{node_id}.linked_poem 必须是对象")
            title = require_text(linked.get("title"), f"{node_id}.linked_poem.title")
            relation = require_text(linked.get("relation"), f"{node_id}.linked_poem.relation")
            relation_level = require_text(linked.get("relation_level"), f"{node_id}.linked_poem.relation_level")
            require(relation_level in VALID_LEVELS, f"{node_id}.relation_level 无效")
            if relation_level == "C":
                require(
                    any(word in relation for word in ("推定", "不声称", "只作", "传统", "代表")),
                    f"{node_id} 为 C 级作品关联但未说明推定边界",
                )

            pair = (poet, title)
            require(pair in poems, f"作品未出现在 poems.json：{poet}《{title}》")
            linked_pairs.add(pair)
            emotion = linked.get("text_emotion")
            require(isinstance(emotion, dict), f"{node_id}.text_emotion 必须是对象")
            require_text(emotion.get("label"), f"{node_id}.text_emotion.label")
            require_number(emotion.get("valence"), -1, 1, f"{node_id}.text_emotion.valence")
            require_number(emotion.get("intensity"), 0, 1, f"{node_id}.text_emotion.intensity")
            require(emotion.get("analysis_level") == "C", f"{node_id} 文本情感标注必须标 C")
            evidence = require_text(emotion.get("evidence"), f"{node_id}.text_emotion.evidence")
            require(evidence in poems[pair], f"证据诗句未出现在原文：{poet}《{title}》 -> {evidence}")

            all_nodes.append(node)

    require(len(all_nodes) >= 25, "总节点数至少应为 25")
    require(len(linked_pairs) >= 25, "去重后的关联代表作应至少为 25 首")
    return payload, all_nodes


def validate_script() -> None:
    require(VIZ_SCRIPT.exists(), f"缺少可视化脚本：{VIZ_SCRIPT}")
    source = VIZ_SCRIPT.read_text(encoding="utf-8")
    ast.parse(source, filename=str(VIZ_SCRIPT))
    for token in (
        "poet_journeys.json",
        "poems.json",
        "Geo",
        "Scatter",
        "Bar",
        "localize_pyecharts_assets",
        "write_premium_chart_page",
        "localize_china_asset",
        "15_诗人行旅与生命情感.html",
    ):
        require(token in source, f"可视化脚本缺少必要实现：{token}")


def validate_output(nodes: list[dict[str, object]]) -> None:
    require(OUT_HTML.exists(), f"缺少可视化输出：{OUT_HTML}")
    html = OUT_HTML.read_text(encoding="utf-8")
    for text in (
        "诗人行旅与生命情感",
        "行旅事实",
        "生平处境",
        "文本情感",
        "不代表诗人实际行走的道路",
        "处境指数是项目人工编码",
        "节点证据账本",
        "返回总入口",
    ):
        require(text in html, f"输出页缺少必要文本：{text}")
    for poet in EXPECTED_POETS:
        require(poet in html, f"输出页未覆盖诗人：{poet}")
    for chart_id in ("journey_fact_geo", "text_emotion_scatter", "context_emotion_bar"):
        require(chart_id in html, f"输出页缺少图表：{chart_id}")
    require(str(len(nodes)) in html, "输出页应展示审核节点样本量")

    script_sources = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, flags=re.I)
    require(script_sources, "输出页缺少脚本资源")
    require(not any(re.match(r"https?://", src) for src in script_sources), f"输出页仍有远程脚本：{script_sources}")
    require("assets/pyecharts/v6/echarts.min.js" in script_sources, "ECharts 未切换为本地资源")
    require("assets/pyecharts/v6/maps/china.js" in script_sources, "中国地图 JS 未切换为本地资源")
    for src in script_sources:
        asset_path = OUT_HTML.parent / Path(src)
        require(asset_path.exists() and asset_path.stat().st_size > 1024, f"本地资源不存在或过小：{asset_path}")


def main() -> None:
    _, nodes = validate_data()
    validate_script()
    validate_output(nodes)
    grades = Counter(str(node["source_level"]) for node in nodes)
    print("journey emotion check passed")
    print(f"诗人：{len(EXPECTED_POETS)} 位；节点：{len(nodes)} 个；A/B/C：{grades.get('A', 0)}/{grades.get('B', 0)}/{grades.get('C', 0)}")
    print(OUT_HTML)


if __name__ == "__main__":
    main()
