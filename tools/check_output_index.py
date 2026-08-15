"""校验 output/index.html 面向用户的入口页结构。"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
INDEX_HTML = OUTPUT_DIR / "index.html"

FORBIDDEN_TEXT = (
    "演示路线",
    "Presentation Route",
    "用户体验流程",
    "USER FLOW",
    "足迹知识库口径",
    "DATA SCOPE",
    "CNKGraph 缓存",
    "DeepSeek API Key",
)

REQUIRED_TEXT = (
    "诗行万里 · 可视化总入口",
    "核心成果",
    "成果搜索",
    "类型筛选",
    "流派词云",
    "单派词云",
    "交付清单",
)

REQUIRED_LINKS = (
    "01_诗人足迹.html",
    "03_诗人产出.html",
    "04_流派词云.png",
    "05_情感分布.html",
    "06_总览看板.html",
    "08_诗作检索.html",
    "09_词典浏览.html",
    "10_诗人对比.html",
    "11_流派画像.html",
    "13_诗词白话翻译.html",
    "14_文本相似与异常发现.html",
    "manifest.json",
)

REQUIRED_WORDCLOUDS = (
    ("豪放派词云", "04_词云_豪放派.png"),
    ("婉约派词云", "04_词云_婉约派.png"),
    ("山水田园词云", "04_词云_山水田园.png"),
    ("边塞派词云", "04_词云_边塞派.png"),
)


class IndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.images: list[str] = []
        self.ids: set[str] = set()
        self.card_count = 0
        self.wordcloud_buttons: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if values.get("id"):
            self.ids.add(values["id"])
        if tag == "a" and values.get("href"):
            self.hrefs.append(values["href"])
        if tag == "img" and values.get("src"):
            self.images.append(values["src"])
        if tag == "article" and "output-card" in values.get("class", ""):
            self.card_count += 1
        if tag == "button" and "wordcloud-button" in values.get("class", ""):
            self.wordcloud_buttons.append(values)


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
    if re.search(r"https?://", html):
        raise AssertionError("入口页应保持离线可用，不应包含外链")

    parser = IndexParser()
    parser.feed(html)

    if "route" in parser.ids:
        raise AssertionError("入口页不应再保留 route 区块")
    if "footprintKnowledgeStatusPanel" in parser.ids:
        raise AssertionError("入口页不应再保留足迹知识库说明面板")
    if parser.card_count != 11:
        raise AssertionError(f"入口页应保留 11 张核心成果卡片，实际为 {parser.card_count}")

    for href in REQUIRED_LINKS:
        if href not in parser.hrefs:
            raise AssertionError(f"入口页缺少链接：{href}")
        if not (OUTPUT_DIR / href).exists():
            raise AssertionError(f"入口页链接目标不存在：{href}")

    required_ids = {
        "outputs",
        "wordclouds",
        "wordcloudPreviewImage",
        "wordcloudPreviewTitle",
        "wordcloudPreviewMeta",
        "wordcloudPreviewLink",
        "outputSearch",
        "outputKindFilter",
        "outputVisibleCount",
        "resetOutputFilters",
        "outputEmpty",
    }
    missing_ids = sorted(required_ids - parser.ids)
    if missing_ids:
        raise AssertionError(f"入口页缺少必要控件：{missing_ids}")

    wordcloud_map = {
        button.get("data-wordcloud-label", ""): button.get("data-wordcloud-src", "")
        for button in parser.wordcloud_buttons
    }
    for label, href in REQUIRED_WORDCLOUDS:
        if wordcloud_map.get(label) != href:
            raise AssertionError(f"词云预览按钮缺失或路径错误：{label} -> {href}")
        if href not in parser.hrefs:
            raise AssertionError(f"词云预览缺少原图链接：{href}")
        if not (OUTPUT_DIR / href).exists():
            raise AssertionError(f"词云图片不存在：{href}")

    if "04_词云_豪放派.png" not in parser.images:
        raise AssertionError("单派词云预览应默认显示豪放派词云")
    if "data-wordcloud-src" not in html or "wordcloudPreviewImage" not in html:
        raise AssertionError("单派词云应在本页内切换预览图片")

    print("output index check passed")
    print(INDEX_HTML)


if __name__ == "__main__":
    main()
