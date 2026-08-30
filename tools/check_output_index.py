"""校验 output/index.html 当前生命痕迹首页结构。"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
INDEX_HTML = OUTPUT_DIR / "index.html"
FULL_MANIFEST = ROOT / "data" / "analysis" / "famous_poets_full_manifest.json"
CANONICAL_JSON = ROOT / "data" / "poems.json"

FORBIDDEN_TEXT = (
    "演示路线",
    "Presentation Route",
    "用户体验流程",
    "USER FLOW",
    "足迹知识库口径",
    "DATA SCOPE",
    "DeepSeek API Key",
)

REQUIRED_TEXT = (
    "诗行万里",
    "诗人生命痕迹",
    "作诗时期轴",
    "当前作诗时期分析",
    "相邻审核节点比较",
    "当前诗作意象",
    "处境指数",
)

REQUIRED_LINKS = (
    "08_诗作检索.html",
    "09_词典浏览.html",
    "15_诗人行旅与生命情感.html",
    "16_唐宋诗歌创作活动中心迁移.html",
    "17_同一意象的诗人情感差异.html",
    "18_数据质量与来源覆盖.html",
    "20_诗人精神地形图.html",
    "29_参赛导航.html",
    "44_诗页.html",
    "manifest.json",
)


class IndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if values.get("id"):
            self.ids.add(values["id"])
        if tag == "a" and values.get("href"):
            self.hrefs.append(values["href"])


def assert_contains(html: str, text: str) -> None:
    if text not in html:
        raise AssertionError(f"入口页缺少文本：{text}")


def assert_absent(html: str, text: str) -> None:
    if text in html:
        raise AssertionError(f"入口页不应再展示内部导览/口径内容：{text}")


def main() -> None:
    if not INDEX_HTML.exists():
        raise AssertionError(f"缺少离线总入口页：{INDEX_HTML}")

    html = INDEX_HTML.read_text(encoding="utf-8")

    for text in REQUIRED_TEXT:
        assert_contains(html, text)
    for text in FORBIDDEN_TEXT:
        assert_absent(html, text)

    if '<meta name="viewport"' not in html:
        raise AssertionError("入口页缺少响应式 viewport")
    if re.search(r"<script[^>]+src=[\"']https?://", html, flags=re.I):
        raise AssertionError("入口页不应依赖远程脚本")

    parser = IndexParser()
    parser.feed(html)

    for href in REQUIRED_LINKS:
        if href not in parser.hrefs:
            raise AssertionError(f"入口页缺少链接：{href}")
        if not (OUTPUT_DIR / href).exists():
            raise AssertionError(f"入口页链接目标不存在：{href}")

    required_ids = {
        "appData",
        "poetSwitch",
        "journeyMap",
        "detailBody",
        "timeline",
        "periodAnalysisBody",
        "emotionTrend",
        "lifeSummary",
        "imageryTokens",
        "emotionList",
    }
    missing_ids = sorted(required_ids - parser.ids)
    if missing_ids:
        raise AssertionError(f"入口页缺少必要控件：{missing_ids}")
    match = re.search(
        r'<script id="appData" type="application/json">(.*?)</script>',
        html,
        flags=re.S,
    )
    if not match:
        raise AssertionError("入口页缺少 appData 数据")
    app_data = json.loads(match.group(1))
    full_manifest = json.loads(FULL_MANIFEST.read_text(encoding="utf-8"))
    canonical_count = len(json.loads(CANONICAL_JSON.read_text(encoding="utf-8")))
    if app_data.get("corpus_source") != "analysis_full":
        raise AssertionError("入口页状态层未使用 analysis_full")
    if app_data.get("analysis_count") != full_manifest.get("record_count"):
        raise AssertionError("入口页全作品计数与 full corpus manifest 不一致")
    if app_data.get("canonical_evidence_count") != canonical_count:
        raise AssertionError("入口页 canonical 证据计数不一致")

    print("output index check passed")
    print(INDEX_HTML)


if __name__ == "__main__":
    main()
