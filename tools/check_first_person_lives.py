"""校验“88位诗人第一人称生命卷”首轮数据契约与离线页面。"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from famous_poet_corpus import load_analysis_poems  # noqa: E402

POEMS_PATH = ROOT / "data" / "poems.json"
DATA_PATH = (
    ROOT / "output" / "assets" / "competition" / "first_person_lives_data.json"
)
HTML_PATH = ROOT / "output" / "39_诗人自述生命卷.html"
LOCAL_ECHARTS = (
    ROOT / "output" / "assets" / "pyecharts" / "v6" / "echarts.min.js"
)
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
DIMENSION_KEYS = ("valence", "arousal", "dominance", "anger_signal", "confidence")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_json(path: Path, label: str) -> Any:
    require(path.exists(), f"{label}缺失：{path}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AssertionError(f"{label}无法读取为 UTF-8 JSON：{path}（{exc}）") from exc


def nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def load_corpus() -> tuple[
    list[dict[str, Any]],
    set[str],
    Counter[str],
    dict[str, str],
    int,
    str,
]:
    raw = load_json(POEMS_PATH, "诗歌语料")
    rows = raw if isinstance(raw, list) else raw.get("poems") if isinstance(raw, dict) else None
    require(isinstance(rows, list), "data/poems.json 顶层必须是数组或含 poems 数组")

    poets: set[str] = set()
    canonical_counts: Counter[str] = Counter()
    bodies: dict[str, str] = {}
    for index, row in enumerate(rows):
        require(isinstance(row, dict), f"诗歌语料第 {index + 1} 行不是对象")
        poet = row.get("poet") or row.get("author")
        title = row.get("title")
        body_hash = row.get("body_hash")
        body = row.get("body")
        require(nonempty_text(poet), f"诗歌语料第 {index + 1} 行缺少诗人")
        require(nonempty_text(title), f"诗歌语料第 {index + 1} 行缺少题名")
        require(nonempty_text(body_hash), f"诗歌语料第 {index + 1} 行缺少 body_hash")
        require(isinstance(body, str), f"诗歌语料第 {index + 1} 行正文不是字符串")
        poet = str(poet)
        key = corpus_key(poet, str(title), str(body_hash))
        if key in bodies and bodies[key] != body:
            raise AssertionError(f"同一诗人/题名/body_hash 对应不同正文：{poet}《{title}》")
        bodies[key] = body
        poets.add(poet)
        canonical_counts[poet] += 1

    require(len(poets) == 88, f"data/poems.json 诗人集合应为 88 人，实际 {len(poets)} 人")
    analysis_rows, corpus_source = load_analysis_poems()
    analysis_counts: Counter[str] = Counter(
        str(row.get("poet") or row.get("author") or "") for row in analysis_rows
    )
    analysis_counts.pop("", None)
    require(set(analysis_counts) == poets, missing_extra_message("全作品分析诗人集合", set(analysis_counts), poets))
    work_ids = [str(row.get("work_id") or "") for row in analysis_rows]
    require(all(work_ids), "全作品分析语料存在空 work_id")
    require(len(work_ids) == len(set(work_ids)), "全作品分析语料 work_id 不唯一")
    require(all(analysis_counts[name] >= canonical_counts[name] for name in poets), "全作品篇数不得少于规范展示篇数")
    return rows, poets, analysis_counts, bodies, len(analysis_rows), corpus_source


def corpus_key(poet: str, title: str, body_hash: str) -> str:
    return "\u241f".join((poet, title, body_hash))


def round_number(row: dict[str, Any], fallback: int) -> int:
    value = row.get("round", row.get("number", row.get("id", fallback)))
    if isinstance(value, str):
        match = re.search(r"\d+", value)
        value = int(match.group()) if match else value
    require(isinstance(value, int) and not isinstance(value, bool), f"轮次编号非法：{value!r}")
    return value


def round_poets(row: dict[str, Any]) -> list[str]:
    value = row.get("poets", row.get("cohort"))
    if isinstance(value, dict):
        value = value.get("poets") or value.get("names")
    require(isinstance(value, list), "每个 rounds 项必须含 poets（或 cohort）数组")
    require(all(nonempty_text(name) for name in value), "轮次诗人名单含空值或非字符串")
    return [str(name) for name in value]


def check_project_and_rounds(payload: dict[str, Any], corpus_poets: set[str]) -> tuple[dict[str, int], int]:
    project = payload.get("project")
    require(isinstance(project, dict), "数据缺少 project 对象")
    expected_project = {
        "total_poets": 88,
        "rounds": 4,
        "cohort_size": 22,
    }
    for key, expected in expected_project.items():
        require(project.get(key) == expected, f"project.{key} 应为 {expected}，实际 {project.get(key)!r}")
    active_round = project.get("active_round")
    require(isinstance(active_round, int) and not isinstance(active_round, bool), "project.active_round 必须是整数")
    require(1 <= active_round <= 4, f"project.active_round 必须在 1–4，实际 {active_round!r}")
    require(project.get("active_poets") == 22, f"project.active_poets 应为 22，实际 {project.get('active_poets')!r}")
    require(project.get("generated_poets") == active_round * 22, f"project.generated_poets 应为 {active_round * 22}")

    rounds = payload.get("rounds")
    require(isinstance(rounds, list), "数据缺少 rounds 数组")
    require(len(rounds) == 4, f"rounds 应恰有 4 组，实际 {len(rounds)} 组")
    membership: dict[str, int] = {}
    observed_numbers: list[int] = []
    all_names: list[str] = []
    for fallback, row in enumerate(rounds, start=1):
        require(isinstance(row, dict), f"rounds[{fallback - 1}] 不是对象")
        number = round_number(row, fallback)
        names = round_poets(row)
        require(len(names) == 22, f"第 {number} 轮应为 22 人，实际 {len(names)} 人")
        require(len(names) == len(set(names)), f"第 {number} 轮内部有重复诗人")
        expected_status = "complete" if number < active_round else "active" if number == active_round else "planned"
        require(row.get("status") == expected_status, f"第 {number} 轮 status 应为 {expected_status}，实际 {row.get('status')!r}")
        observed_numbers.append(number)
        all_names.extend(names)
        for name in names:
            if name in membership:
                raise AssertionError(f"诗人 {name} 同时出现在第 {membership[name]}、{number} 轮")
            membership[name] = number

    require(sorted(observed_numbers) == [1, 2, 3, 4], f"轮次编号必须为 1–4，实际 {observed_numbers}")
    require(len(all_names) == 88, f"四轮名单总数应为 88，实际 {len(all_names)}")
    require(set(all_names) == corpus_poets, missing_extra_message("四轮诗人集合", set(all_names), corpus_poets))
    return membership, active_round


def missing_extra_message(label: str, actual: set[str], expected: set[str]) -> str:
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    return f"{label}与 data/poems.json 不一致；缺少={missing}，多出={extra}"


def check_dimension(value: Any, label: str) -> None:
    if value is None:
        return
    require(finite_number(value), f"{label} 必须是有限数字或 null，实际 {value!r}")
    require(-1 <= float(value) <= 1, f"{label} 越界：{value!r}")


def check_anger(value: Any, label: str) -> None:
    if value is None:
        return
    require(finite_number(value), f"{label} 必须是有限数字或 null，实际 {value!r}")
    require(0 <= float(value) <= 1, f"{label} 越界：{value!r}")


def grade_rank(value: Any) -> int:
    return {"A": 4, "B": 3, "C": 2, "D": 1}.get(str(value or "").upper(), 0)


def check_chapter(
    chapter: Any,
    *,
    poet: str,
    chapter_index: int,
    sources: dict[str, Any],
    corpus_bodies: dict[str, str],
) -> tuple[float, str]:
    label = f"{poet} 第 {chapter_index + 1} 章"
    require(isinstance(chapter, dict), f"{label} 不是对象")
    required_fields = (
        "id",
        "year_start",
        "year_end",
        "title",
        "event_fact",
        "first_person",
        "voice_mode",
        "voice_label",
        "place",
        "work",
        "dimensions",
        "source_ids",
        "assertion_status",
        "source_grade",
        "evidence_note",
    )
    missing = [field for field in required_fields if field not in chapter]
    require(not missing, f"{label} 缺少字段：{missing}")

    for field in ("id", "title", "event_fact", "first_person", "voice_label", "assertion_status", "source_grade", "evidence_note"):
        require(nonempty_text(chapter[field]), f"{label}.{field} 必须是非空字符串")
    require(
        chapter["voice_mode"] == "editorial_first_person_reconstruction",
        f"{label}.voice_mode 必须为 editorial_first_person_reconstruction，不得伪装成 direct_quote",
    )
    require(chapter["voice_mode"] != "direct_quote", f"{label} 把编辑重构误标为 direct_quote")

    year_start = chapter["year_start"]
    year_end = chapter["year_end"]
    require(finite_number(year_start), f"{label}.year_start 必须是有限年份")
    require(finite_number(year_end), f"{label}.year_end 必须是有限年份")
    require(float(year_start) <= float(year_end), f"{label} 年份区间倒置：{year_start}–{year_end}")
    age_range = chapter.get("age_range")
    if age_range is not None:
        require(
            isinstance(age_range, list)
            and len(age_range) == 2
            and all(finite_number(value) for value in age_range)
            and age_range[0] <= age_range[1],
            f"{label}.age_range 必须是递增的两个有限数字或 null",
        )

    dimensions = chapter["dimensions"]
    require(isinstance(dimensions, dict), f"{label}.dimensions 必须是对象")
    for key in DIMENSION_KEYS:
        require(key in dimensions, f"{label}.dimensions 缺少 {key}")
    for key in ("valence", "arousal", "dominance"):
        check_dimension(dimensions[key], f"{label}.dimensions.{key}")
    check_anger(dimensions["anger_signal"], f"{label}.dimensions.anger_signal")
    check_anger(dimensions["confidence"], f"{label}.dimensions.confidence")

    source_ids = chapter["source_ids"]
    require(isinstance(source_ids, list) and source_ids, f"{label}.source_ids 必须是非空数组")
    require(all(nonempty_text(source_id) for source_id in source_ids), f"{label}.source_ids 含空值")
    require(len(source_ids) == len(set(source_ids)), f"{label}.source_ids 含重复值")
    for source_id in source_ids:
        require(str(source_id) in sources, f"{label} 引用无法解析的 source_id：{source_id}")
    evidence_grades = [
        str(sources[str(source_id)].get("grade") or "").upper()
        for source_id in source_ids
        if grade_rank(sources[str(source_id)].get("grade"))
    ]
    if evidence_grades:
        weakest = min(evidence_grades, key=grade_rank)
        require(chapter["source_grade"] == weakest, f"{label}.source_grade 应取全部证据中的最低等级 {weakest}")

    place = chapter["place"]
    require(place is None or isinstance(place, (str, dict)), f"{label}.place 必须是 null、字符串或对象")
    work = chapter["work"]
    require(work is None or isinstance(work, dict), f"{label}.work 必须是 null 或对象")
    event = chapter.get("event")
    require(event is None or isinstance(event, dict), f"{label}.event 必须是 null 或对象")
    if isinstance(event, dict):
        event_start = event.get("year_start")
        event_end = event.get("year_end", event_start)
        require(finite_number(event_start) and finite_number(event_end), f"{label}.event 年份必须是有限数字")
        require(year_start <= event_start <= year_end and year_start <= event_end <= year_end, f"{label} 不得合并章节年份之外的事件：{event_start}–{event_end}")
    if isinstance(work, dict):
        work_year = work.get("year")
        require(finite_number(work_year), f"{label}.work.year 必须是有限数字")
        require(year_start <= work_year <= year_end, f"{label} 不得把 {work_year} 年作品画到 {year_start}–{year_end} 年")
        require(nonempty_text(work.get("work_id")), f"{label}.work.work_id 不能为空")
        require(nonempty_text(work.get("canonical_gushiwen_id")), f"{label}.work.canonical_gushiwen_id 不能为空")
    if isinstance(work, dict) and work.get("quote") not in (None, ""):
        quote = work["quote"]
        title = work.get("title")
        body_hash = work.get("body_hash")
        require(nonempty_text(quote), f"{label}.work.quote 必须是非空字符串")
        require(nonempty_text(title), f"{label} 有 quote 时 work.title 不能为空")
        require(nonempty_text(body_hash), f"{label} 有 quote 时 work.body_hash 不能为空")
        key = corpus_key(poet, str(title), str(body_hash))
        require(key in corpus_bodies, f"{label} 的诗作无法按诗人/题名/body_hash 回查：{poet}《{title}》")
        require(str(quote) in corpus_bodies[key], f"{label} 引用不是对应诗作正文的原样子串：{poet}《{title}》")

    return float(year_start), str(chapter["id"])


def check_poets(
    payload: dict[str, Any],
    *,
    membership: dict[str, int],
    active_round: int,
    corpus_poets: set[str],
    corpus_counts: Counter[str],
    corpus_bodies: dict[str, str],
) -> tuple[int, int]:
    poets = payload.get("poets")
    require(isinstance(poets, list), "数据缺少 poets 数组")
    require(len(poets) == 88, f"poets 应恰有 88 人，实际 {len(poets)} 人")
    names = [row.get("name") for row in poets if isinstance(row, dict)]
    require(len(names) == 88 and all(nonempty_text(name) for name in names), "poets 含非对象或空 name")
    require(len(names) == len(set(names)), "poets 存在重复诗人")
    require(set(names) == corpus_poets, missing_extra_message("poets 诗人集合", set(names), corpus_poets))

    sources = payload.get("sources")
    require(isinstance(sources, dict), "数据缺少顶层 sources 字典")
    require(all(nonempty_text(source_id) for source_id in sources), "sources 含空 source_id")
    for source_key, source in sources.items():
        require(isinstance(source, dict), f"sources[{source_key}] 必须是对象")
        require(source.get("id") == source_key, f"sources[{source_key}].id 与字典键不一致")
    require(
        (sources.get("analysis-corpus") or {}).get("kind") == "full_famous_poet_analysis_corpus",
        "sources 缺少名家全作品分析语料声明",
    )
    require(
        (sources.get("poems-corpus") or {}).get("kind") == "canonical_poem_corpus",
        "sources 缺少规范诗页证据语料声明",
    )
    verified_birth_sources = [
        source
        for source in sources.values()
        if source.get("kind") == "verified_birth_reference"
    ]
    require(len(verified_birth_sources) == 6, f"核定生年来源应为 6 条独立记录，实际 {len(verified_birth_sources)}")
    verified_urls = [str(source.get("url") or "") for source in verified_birth_sources]
    require(len(set(verified_urls)) == 6 and all(verified_urls), "6 位诗人的核定生年 URL 必须非空且彼此唯一")

    generated_count = 0
    chapter_count = 0
    chapter_ids: set[str] = set()
    required_fields = (
        "name",
        "dynasty",
        "round",
        "status",
        "corpus_poems",
        "readiness",
        "lifespan",
        "portrait",
        "chapters",
    )
    for row_index, poet_row in enumerate(poets):
        require(isinstance(poet_row, dict), f"poets[{row_index}] 不是对象")
        name = str(poet_row.get("name", ""))
        missing = [field for field in required_fields if field not in poet_row]
        require(not missing, f"{name or f'poets[{row_index}]'} 缺少字段：{missing}")
        require(nonempty_text(poet_row["dynasty"]), f"{name}.dynasty 不能为空")
        require(nonempty_text(poet_row["status"]), f"{name}.status 不能为空")
        require(isinstance(poet_row["round"], int) and not isinstance(poet_row["round"], bool), f"{name}.round 必须是整数")
        require(poet_row["round"] == membership[name], f"{name}.round 与 rounds 名单不一致")
        require(poet_row["corpus_poems"] == corpus_counts[name], f"{name}.corpus_poems 应为 {corpus_counts[name]}，实际 {poet_row['corpus_poems']!r}")
        require(isinstance(poet_row["readiness"], (dict, int, float)) and not isinstance(poet_row["readiness"], bool), f"{name}.readiness 必须是对象或数值")
        require(poet_row["lifespan"] is None or isinstance(poet_row["lifespan"], (dict, str)), f"{name}.lifespan 必须是 null、字符串或对象")

        chapters = poet_row["chapters"]
        require(isinstance(chapters, list), f"{name}.chapters 必须是数组")
        if poet_row["round"] <= active_round:
            generated_count += 1
            expected_status = "round_complete" if poet_row["round"] < active_round else "active_round_generated"
            gap_status = "round_evidence_gap" if poet_row["round"] < active_round else "active_round_evidence_gap"
            require(poet_row["status"] in {expected_status, gap_status}, f"已推进诗人 {name}.status 非法：{poet_row['status']!r}")
            if poet_row["status"] == gap_status:
                require(chapters == [], f"证据缺口诗人 {name}.chapters 必须为空")
            else:
                require(len(chapters) >= 4, f"已生成诗人 {name} 至少应有 4 章，实际 {len(chapters)} 章")
            portrait = poet_row["portrait"]
            require(isinstance(portrait, dict), f"已推进诗人 {name}.portrait 必须是对象")
            require(portrait.get("scope") == "corpus_textual_persona_not_personality_diagnosis", f"{name}.portrait.scope 必须明确非人格诊断")
            require(nonempty_text(portrait.get("summary")), f"{name}.portrait.summary 不得为空")
            require(nonempty_text(portrait.get("curve_reading")), f"{name}.portrait.curve_reading 不得为空")
            require(isinstance(portrait.get("anger"), dict) and nonempty_text(portrait["anger"].get("reading")), f"{name}.portrait.anger 必须提供幽愤/讽刺文本信号读法")
            require(portrait.get("sample_poems") == corpus_counts[name], f"{name}.portrait.sample_poems 未覆盖全作品")
        else:
            require(poet_row["status"] == "scheduled", f"后续轮次诗人 {name}.status 必须为 scheduled")
            require(chapters == [], f"后续轮次诗人 {name}.chapters 必须为空数组")
            require(poet_row["portrait"] is None, f"后续轮次诗人 {name}.portrait 必须为 null，不得提前生成")

        ordered: list[tuple[float, str]] = []
        for chapter_index, chapter in enumerate(chapters):
            year_and_id = check_chapter(
                chapter,
                poet=name,
                chapter_index=chapter_index,
                sources=sources,
                corpus_bodies=corpus_bodies,
            )
            ordered.append(year_and_id)
            require(year_and_id[1] not in chapter_ids, f"chapter.id 全局重复：{year_and_id[1]}")
            chapter_ids.add(year_and_id[1])
        require(ordered == sorted(ordered, key=lambda item: item[0]), f"{name}.chapters 未按 year_start 升序排列")
        chapter_count += len(chapters)

    require(generated_count == active_round * 22, f"已生成诗人应为 {active_round * 22} 人，实际 {generated_count} 人")
    timeline_count = sum(bool(row.get("chapters")) for row in poets if isinstance(row, dict))
    require(chapter_count >= timeline_count * 4, f"有时间轴的 {timeline_count} 人至少应有 {timeline_count * 4} 章，实际 {chapter_count} 章")
    return generated_count, chapter_count


class SemanticsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.search_inputs: list[dict[str, str]] = []
        self.selector_semantics = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.casefold(): value or "" for key, value in attrs}
        searchable = " ".join((attr.get("aria-label", ""), attr.get("placeholder", ""), attr.get("id", ""), attr.get("name", ""))).casefold()
        if tag.casefold() == "input" and (attr.get("type", "").casefold() == "search" or attr.get("role", "").casefold() == "searchbox") and ("诗人" in searchable or "poet" in searchable):
            self.search_inputs.append(attr)

        semantic_text = " ".join((attr.get("aria-label", ""), attr.get("id", ""), attr.get("data-role", ""), attr.get("class", ""))).casefold()
        has_poet_selector_label = ("诗人" in semantic_text or "poet" in semantic_text) and ("选择" in semantic_text or "selector" in semantic_text or "list" in semantic_text)
        has_listbox_role = attr.get("role", "").casefold() in {"listbox", "combobox"}
        if tag.casefold() == "select" or has_poet_selector_label or has_listbox_role:
            self.selector_semantics = True


def check_html() -> None:
    require(HTML_PATH.exists(), f"第一人称生命卷 HTML 缺失：{HTML_PATH}")
    require(HTML_PATH.stat().st_size <= MAX_OUTPUT_BYTES, f"HTML 超过 2 MiB：{HTML_PATH.stat().st_size} bytes")
    require(HTML_PATH.stat().st_size > 1024, f"HTML 体积异常小：{HTML_PATH.stat().st_size} bytes")
    require(LOCAL_ECHARTS.exists() and LOCAL_ECHARTS.stat().st_size > 1024, f"本地 ECharts 资源缺失：{LOCAL_ECHARTS}")

    html = HTML_PATH.read_text(encoding="utf-8")
    require("NaN" not in html and "Infinity" not in html, "页面含 NaN 或 Infinity")
    require('<meta name="viewport"' in html or "<meta name='viewport'" in html, "页面缺少响应式 viewport")
    require(re.search(r"<link\b[^>]*\brel=[\"'](?:shortcut )?icon[\"'][^>]*\bhref=[\"']data:", html, flags=re.I) is not None, "页面缺少 data: 内嵌 favicon")

    script_sources = re.findall(r"<script\b[^>]*\bsrc=[\"']([^\"']+)[\"']", html, flags=re.I)
    remote_scripts = [src for src in script_sources if re.match(r"(?:https?:)?//", src, flags=re.I)]
    require(not remote_scripts, f"页面包含远程 script，无法保证离线使用：{remote_scripts}")
    require(any(src.replace("\\", "/").endswith("assets/pyecharts/v6/echarts.min.js") for src in script_sources), "页面未引用本地 ECharts：assets/pyecharts/v6/echarts.min.js")

    require(re.search(r"编辑(?:性)?第一人称重构", html) is not None, "页面缺少“编辑性第一人称重构”声明")
    require(any(text in html for text in ("不是诗人原话", "并非诗人原话", "不等于诗人原话", "不可视作诗人原话")), "页面必须明确说明重构不是诗人原话")
    require(any(text in html for text in ("不等于史实", "不是史实", "并非史实", "不可视作史实", "不能替代史实")), "页面必须明确说明重构不等于史实")
    require("88位诗人" in html or "88 位诗人" in html or "88人" in html, "页面缺少 88 位诗人范围说明")

    parser = SemanticsParser()
    parser.feed(html)
    require(parser.search_inputs, "页面缺少带诗人语义的 search/searchbox 输入")
    require(parser.selector_semantics, "页面缺少诗人选择器的 listbox/combobox/select 或 aria-label 语义")


def main() -> None:
    require(DATA_PATH.exists(), f"第一人称生命卷数据缺失：{DATA_PATH}")
    require(DATA_PATH.stat().st_size <= MAX_OUTPUT_BYTES, f"JSON 超过 2 MiB：{DATA_PATH.stat().st_size} bytes")
    payload = load_json(DATA_PATH, "第一人称生命卷数据")
    require(isinstance(payload, dict), "第一人称生命卷 JSON 顶层必须是对象")

    canonical_rows, corpus_poets, corpus_counts, corpus_bodies, analysis_count, corpus_source = load_corpus()
    project = payload.get("project") or {}
    require(project.get("corpus_source") == corpus_source == "analysis_full", "生命卷未声明 analysis_full 来源")
    require(project.get("corpus_poems") == analysis_count, "生命卷全作品总数与 loader 不一致")
    require(project.get("canonical_evidence_poems") == len(canonical_rows), "生命卷规范证据总数不一致")
    membership, active_round = check_project_and_rounds(payload, corpus_poets)
    generated_count, chapter_count = check_poets(
        payload,
        membership=membership,
        active_round=active_round,
        corpus_poets=corpus_poets,
        corpus_counts=corpus_counts,
        corpus_bodies=corpus_bodies,
    )
    check_html()
    print(
        "[ok] 88位诗人第一人称生命卷首轮检查通过："
        f"4轮 × 22人 / 已推进至第 {active_round} 轮 / {generated_count} 人 / {chapter_count} 章"
    )
    print(DATA_PATH)
    print(HTML_PATH)


if __name__ == "__main__":
    main()
