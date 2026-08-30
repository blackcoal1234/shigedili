"""校验“同一意象的诗人情感差异”数据口径与离线页面。"""
from __future__ import annotations

import importlib.util
import math
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.imagery_emotion_rules import (
    EMOTIONS,
    IMAGERY_RULES,
    TARGET_IMAGERY,
    TARGET_POETS,
    matched_aliases,
    sample_level,
)
from tools.famous_poet_corpus import load_analysis_poems


SCRIPT = ROOT / "数据可视化脚本" / "viz_17_imagery_emotion_compare.py"
OUTPUT_HTML = ROOT / "output" / "17_同一意象的诗人情感差异.html"
LOCAL_ECHARTS = ROOT / "output" / "assets" / "pyecharts" / "v6" / "echarts.min.js"
REQUIRED_IDS = (
    "imagery_emotion_heatmap",
    "imagerySegment",
    "metricSelect",
    "heatmapTitle",
    "heatmapMeta",
    "viewSampleStatus",
    "evidenceTable",
    "methodTitle",
    "imagery-emotion-data",
    "imagery-emotion-interaction",
)
REQUIRED_TEXT = (
    "同象异情：诗人如何写同一个意象",
    "诗人 × 情感",
    "伴随意象与证据诗句",
    "P(e|i,p)",
    "P(e|p)",
    "lift",
    "&lt;10 不排名",
    "10–29 探索",
    "≥30 正式",
    "不预设固定情感",
)


def load_visualization_module():
    spec = importlib.util.spec_from_file_location("viz_17_imagery_emotion_compare", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载可视化脚本：{SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(actual, expected, rel_tol=0, abs_tol=1e-6):
        raise AssertionError(f"{label} 计算错误：actual={actual}, expected={expected}")


def check_rules() -> None:
    if tuple(IMAGERY_RULES) != TARGET_IMAGERY:
        raise AssertionError("意象规则顺序或目标意象集合不一致")
    forbidden_keys = {"emotion", "emotions", "sentiment", "sentiment_value"}
    for imagery, rule in IMAGERY_RULES.items():
        bad = forbidden_keys.intersection(rule)
        if bad:
            raise AssertionError(f"{imagery} 被写入固定情感字段：{sorted(bad)}")
        aliases = tuple(rule.get("aliases") or ())
        if imagery not in aliases:
            raise AssertionError(f"{imagery} 规则缺少规范词本身")
        if len(aliases) != len(set(aliases)):
            raise AssertionError(f"{imagery} 存在重复别名")


def check_payload(payload: dict[str, object]) -> None:
    if payload["poets"] != list(TARGET_POETS):
        raise AssertionError("诗人顺序不符合项目口径")
    if payload["imagery"] != list(TARGET_IMAGERY):
        raise AssertionError("意象集合不符合项目口径")
    if payload["emotions"] != list(EMOTIONS):
        raise AssertionError("情感标签集合不符合规则模块")

    analysis_rows, corpus_source = load_analysis_poems(fallback=False)
    expected_totals = {
        poet: sum(1 for row in analysis_rows if row.get("poet") == poet)
        for poet in TARGET_POETS
    }
    totals = payload["poem_totals"]
    if {poet: int(totals[poet]) for poet in TARGET_POETS} != expected_totals:
        raise AssertionError(f"六位诗人计数与 loader 不一致：{totals} != {expected_totals}")
    expected_poem_count = sum(expected_totals.values())
    if int(payload["summary"]["poem_count"]) != expected_poem_count:
        raise AssertionError(f"全作品聚合总量应为 {expected_poem_count} 首")
    if payload["summary"]["corpus_source"] != corpus_source:
        raise AssertionError("语料来源标记与 loader 不一致")
    if int(payload["summary"]["analysis_count"]) != expected_poem_count:
        raise AssertionError("analysis_count 与 loader 六人总量不一致")

    has_multilabel_record = False
    distinct_profile_found = False
    for imagery in TARGET_IMAGERY:
        view = payload["views"][imagery]
        profiles: set[tuple[int, ...]] = set()
        expected_cells = len(TARGET_POETS) * len(EMOTIONS)
        if len(view["cells"]) != expected_cells:
            raise AssertionError(f"{imagery} 热力单元数量错误")

        cell_map = {
            (cell["poet"], cell["emotion"]): cell for cell in view["cells"]
        }
        for poet in TARGET_POETS:
            row = view["poets"][poet]
            sample_count = int(row["sample_count"])
            if row["level"] != sample_level(sample_count):
                raise AssertionError(f"{imagery}/{poet} 样本等级错误")
            poem_ids = [record["poem_id"] for record in row["records"]]
            if len(poem_ids) != len(set(poem_ids)):
                raise AssertionError(f"{imagery}/{poet} 同一诗作被重复计数")
            if int(row["matched_record_count"]) != sample_count:
                raise AssertionError(f"{imagery}/{poet} 命中计数与样本数不一致")
            if len(poem_ids) != int(row["evidence_record_count"]):
                raise AssertionError(f"{imagery}/{poet} 证据计数与展示记录不一致")
            if len(poem_ids) > 24:
                raise AssertionError(f"{imagery}/{poet} 证据超过 24 条")
            if bool(row["truncated"]) != (sample_count > len(poem_ids)):
                raise AssertionError(f"{imagery}/{poet} truncated 标记错误")

            conditional_profile: list[int] = []
            for record in row["records"]:
                if len(record["emotions"]) >= 2:
                    has_multilabel_record = True
                if not record["evidence"]:
                    raise AssertionError(f"{imagery}/{poet}/{record['title']} 缺少证据诗句")
                for evidence in record["evidence"]:
                    if not matched_aliases(str(evidence["line"]), imagery):
                        raise AssertionError(
                            f"{imagery}/{poet}/{record['title']} 的证据句未命中意象：{evidence['line']}"
                        )

            for emotion in EMOTIONS:
                cell = cell_map[(poet, emotion)]
                conditional_count = int(cell["conditional_count"])
                baseline_count = int(cell["baseline_count"])
                conditional_denominator = int(cell["conditional_denominator"])
                baseline_denominator = int(cell["baseline_denominator"])
                if conditional_denominator != sample_count:
                    raise AssertionError(f"{imagery}/{poet}/{emotion} 条件概率分母错误")
                if baseline_denominator != expected_totals[poet]:
                    raise AssertionError(f"{imagery}/{poet}/{emotion} 基线分母与 loader 不一致")
                expected_conditional = (
                    round(conditional_count / sample_count, 6) if sample_count else 0.0
                )
                expected_baseline = round(baseline_count / expected_totals[poet], 6)
                assert_close(
                    float(cell["conditional"]),
                    expected_conditional,
                    f"{imagery}/{poet}/{emotion} P(e|i,p)",
                )
                assert_close(
                    float(cell["baseline"]),
                    expected_baseline,
                    f"{imagery}/{poet}/{emotion} P(e|p)",
                )
                if expected_baseline == 0:
                    if cell["lift"] is not None:
                        raise AssertionError(f"{imagery}/{poet}/{emotion} 基线为 0 时 lift 应为空")
                else:
                    expected_lift = round(expected_conditional / expected_baseline, 6)
                    assert_close(
                        float(cell["lift"]),
                        expected_lift,
                        f"{imagery}/{poet}/{emotion} lift",
                    )
                conditional_profile.append(conditional_count)
            profiles.add(tuple(conditional_profile))
        if len(profiles) >= 2:
            distinct_profile_found = True

    if not has_multilabel_record:
        raise AssertionError("未发现多标签情感记录，规则疑似退化为单一情感赋值")
    if not distinct_profile_found:
        raise AssertionError("所有诗人的情感画像完全相同，无法支持跨诗人比较")


def check_html() -> None:
    if not OUTPUT_HTML.exists() or OUTPUT_HTML.stat().st_size < 40_000:
        raise AssertionError(f"输出 HTML 缺失或体积异常：{OUTPUT_HTML}")
    if not LOCAL_ECHARTS.exists() or LOCAL_ECHARTS.stat().st_size <= 1024:
        raise AssertionError(f"本地 ECharts 资源缺失：{LOCAL_ECHARTS}")

    html = OUTPUT_HTML.read_text(encoding="utf-8")
    if '<meta name="viewport"' not in html:
        raise AssertionError("页面缺少响应式 viewport")
    if re.search(
        r"<(?:script|link)\b[^>]+(?:src|href)=[\"']https?://",
        html,
        flags=re.IGNORECASE,
    ):
        raise AssertionError("页面包含远程资源依赖，不能保证离线使用")
    if 'src="assets/pyecharts/v6/echarts.min.js"' not in html:
        raise AssertionError("页面未引用本地 Pyecharts/ECharts 资源")
    for element_id in REQUIRED_IDS:
        if f'id="{element_id}"' not in html:
            raise AssertionError(f"页面缺少必要区块或控件：{element_id}")
    for text in REQUIRED_TEXT:
        if text not in html:
            raise AssertionError(f"页面缺少方法说明或标题：{text}")
    for imagery in TARGET_IMAGERY:
        if f'"{imagery}"' not in html:
            raise AssertionError(f"页面数据缺少意象：{imagery}")


def main() -> None:
    check_rules()
    module = load_visualization_module()
    payload = module.build_payload()
    check_payload(payload)
    check_html()
    print("imagery emotion compare check passed")
    print(
        f"{payload['summary']['poem_count']} poems / "
        f"{payload['summary']['imagery_poem_hits']} imagery-poem hits / "
        f"{payload['summary']['evidence_line_count']} evidence lines"
    )
    print(OUTPUT_HTML)


if __name__ == "__main__":
    main()
