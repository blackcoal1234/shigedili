"""检查主题版输出、入口链接、离线依赖与 manifest。"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"

CORE_OUTPUTS = (
    "00_主题数据库ER图.png",
    "08_诗作检索.html",
    "09_词典浏览.html",
    "15_诗人行旅与生命情感.html",
    "16_唐宋诗歌创作活动中心迁移.html",
    "17_同一意象的诗人情感差异.html",
    "18_数据质量与来源覆盖.html",
    "20_诗人精神地形图.html",
)

COMPETITION_OUTPUTS = (
    "29_参赛导航.html",
    "30_诗行万里_参赛版.html",
    "31_凝望罗盘.html",
    "32_身与心双层地图.html",
    "33_平行时空759.html",
    "34_一字识诗人.html",
    "35_两种孤独与夸张签名.html",
    "36_同龄对齐.html",
    "37_可听的诗.html",
    "38_唐宋意象潮汐.html",
    "39_诗人自述生命卷.html",
    "40_山河证道.html",
    "41_意象地理.html",
    "42_被想象的地方.html",
    "43_飞花令加行.html",
    "44_诗页.html",
)

# 29—39 号页沿用统一的全互链导航；40—44 号页由 29 号参赛导航
# 汇总进入，页面自身采用各自的任务/证据导航，不强制套用旧导航模板。
CROSS_NAV_OUTPUTS = COMPETITION_OUTPUTS[:11]

REQUIRED_ASSETS = (
    "assets/poem_page/poem_page_data.js",
)

REQUIRED = (
    *CORE_OUTPUTS,
    *COMPETITION_OUTPUTS,
    *REQUIRED_ASSETS,
    "index.html",
    "manifest.json",
)

LEGACY = (
    "01_诗人足迹.html",
    "03_诗人产出.html",
    "04_流派词云.png",
    "05_情感分布.html",
    "06_总览看板.html",
    "07_四季词摘选.html",
    "10_诗人对比.html",
    "11_流派画像.html",
    "12_市级诗歌地图.html",
    "13_诗词白话翻译.html",
    "14_文本相似与异常发现.html",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes())
    return digest.hexdigest()


def check_files() -> None:
    for name in REQUIRED:
        path = OUTPUT_DIR / name
        require(path.exists(), f"缺少输出：{name}")
        minimum = 5000 if path.suffix.lower() == ".html" else 100
        require(path.stat().st_size >= minimum, f"输出异常小：{name}")
    for name in LEGACY:
        require(not (OUTPUT_DIR / name).exists(), f"旧版输出仍在正式目录：{name}")


def check_html() -> None:
    for path in OUTPUT_DIR.glob("*.html"):
        html = path.read_text(encoding="utf-8")
        remote_scripts = re.findall(
            r"<script[^>]+src=[\"']https?://[^\"']+",
            html,
            flags=re.I,
        )
        require(not remote_scripts, f"{path.name} 仍引用远程脚本：{remote_scripts[:1]}")
        require("NaN" not in html and "Infinity" not in html, f"{path.name} 含非法数值")
    index_html = (OUTPUT_DIR / "index.html").read_text(encoding="utf-8")
    for name in (*CORE_OUTPUTS, COMPETITION_OUTPUTS[0]):
        require(name in index_html, f"总入口缺少链接：{name}")

    competition_index = (OUTPUT_DIR / COMPETITION_OUTPUTS[0]).read_text(
        encoding="utf-8"
    )
    for name in COMPETITION_OUTPUTS[1:]:
        require(name in competition_index, f"参赛导航缺少链接：{name}")

    for name in CROSS_NAV_OUTPUTS:
        html = (OUTPUT_DIR / name).read_text(encoding="utf-8")
        require(
            'rel="icon" href="data:' in html,
            f"参赛页缺少内嵌 favicon：{name}",
        )
        for target in CROSS_NAV_OUTPUTS:
            if target == name:
                continue
            require(target in html, f"参赛页导航缺少 {target}：{name}")
    for text in (
        "作诗时期轴",
        "当前作诗时期分析",
        "相邻审核节点比较",
        "当前诗作意象",
        "poem_imagery",
    ):
        require(text in index_html, f"生命痕迹首页缺少当前时期分析：{text}")

    journey_payload = json.loads(
        (ROOT / "data" / "reviewed" / "poet_journeys.json").read_text(
            encoding="utf-8-sig"
        )
    )
    journey_count = sum(
        len(poet_row.get("nodes", []))
        for poet_row in journey_payload.get("poets", [])
        if isinstance(poet_row, dict)
    )
    quality_html = (OUTPUT_DIR / "18_数据质量与来源覆盖.html").read_text(
        encoding="utf-8"
    )
    require(
        f"<td>审核行旅节点</td><td>{journey_count}</td>" in quality_html,
        "质量页行旅节点统计未与审核数据同步",
    )
    for text in (
        "候选审核状态",
        "核心作品采集尝试",
        "诗人身份处理状态",
        "背景候选版权边界",
        "批准主张证据完整性",
        "富背景完整度",
        "可发布完整版",
    ):
        require(text in quality_html, f"质量页缺少背景流水线指标：{text}")


def check_manifest() -> None:
    payload = json.loads((OUTPUT_DIR / "manifest.json").read_text(encoding="utf-8"))
    rows = {row["href"]: row for row in payload.get("outputs", [])}
    for name in REQUIRED:
        if name in {"index.html", "manifest.json"}:
            continue
        require(name in rows, f"manifest 缺少：{name}")
        path = OUTPUT_DIR / name
        require(rows[name].get("exists") is True, f"manifest 标记未生成：{name}")
        require(
            rows[name].get("bytes") == path.stat().st_size,
            f"manifest 字节数不一致：{name}",
        )
        require(rows[name].get("sha256") == sha256(path), f"manifest 哈希不一致：{name}")


def main() -> None:
    check_files()
    check_html()
    check_manifest()
    print(f"[ok] 主题输出检查通过：{len(REQUIRED)} 项")


if __name__ == "__main__":
    main()
