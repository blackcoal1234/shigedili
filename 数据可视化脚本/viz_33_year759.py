# -*- coding: utf-8 -*-
"""史料自动成片：从诗篇编年记录自动生成路线叙事。

零参数运行：
    python 数据可视化脚本/viz_33_year759.py

产出：
    output/33_平行时空759.html
    output/assets/competition/year759_data.json
    output/assets/competition/scene_prompt_manifest.json

路线不是人工在页面上绘制的。脚本合并 verified_poem_contexts.csv 与六份
候选编年表，按来源优先级和年份区间排序，并把同题记录与 poems.json 原文绑定。
连接线只表达可严格排序的相邻创作节点，不代表实际道路或航线。
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import zlib
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
POEMS_PATH = ROOT / "data" / "poems.json"
VERIFIED_PATH = ROOT / "data" / "reviewed" / "verified_poem_contexts.csv"
EMOTION_PATH = ROOT / "data" / "stylometry" / "emotion_profiles.json"
CANDIDATE_FILES = {
    "李白": ROOT / "data" / "candidates" / "libai_spirit_chronology.csv",
    "杜甫": ROOT / "data" / "candidates" / "dufu_spirit_chronology.csv",
    "白居易": ROOT / "data" / "candidates" / "baijuyi_spirit_chronology.csv",
    "苏轼": ROOT / "data" / "candidates" / "sushi_spirit_chronology.csv",
    "陆游": ROOT / "data" / "candidates" / "luyou_spirit_chronology.csv",
    "李清照": ROOT / "data" / "candidates" / "liqingzhao_spirit_chronology.csv",
}
OUT_HTML = ROOT / "output" / "33_平行时空759.html"
OUT_JSON = ROOT / "output" / "assets" / "competition" / "year759_data.json"
OUT_PROMPTS = ROOT / "output" / "assets" / "competition" / "scene_prompt_manifest.json"
SCENE_DIR = ROOT / "output" / "assets" / "competition" / "generated_scenes"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
YEAR_PRECISION_DISPLAY = {
    "year": "精确到年",
    "exact": "精确到年",
    "range": "年份范围",
    "approximate": "约年",
    "disputed": "系年有争议",
    "unknown": "未知",
}

POET_CONFIG = {
    "李白": {"key": "libai", "color": "#426f94", "dynasty": "唐", "school": "浪漫派"},
    "杜甫": {"key": "dufu", "color": "#7a5c3d", "dynasty": "唐", "school": "现实派"},
    "白居易": {"key": "baijuyi", "color": "#26786e", "dynasty": "唐", "school": "新乐府"},
    "苏轼": {"key": "sushi", "color": "#b64b3f", "dynasty": "宋", "school": "豪放派"},
    "陆游": {"key": "luyou", "color": "#8a3b2f", "dynasty": "宋", "school": "爱国派"},
    "李清照": {"key": "liqingzhao", "color": "#9c5d8f", "dynasty": "宋", "school": "婉约派"},
}

SCHOOL_COLORS = {
    "婉约派": "#2f78b7",
    "豪放派": "#c04a3a",
    "浪漫派": "#8a5a9d",
    "现实派": "#3b7d69",
    "新乐府": "#d39b2f",
    "爱国派": "#7b6045",
}

TITLE_ALIASES = {
    ("李白", "客中行"): "客中作",
    ("李白", "秋浦歌·其十五"): "秋浦歌十七首·十五",
    ("李白", "临路歌"): "临终歌",
}

def han_count(text: str) -> int:
    return len(re.findall(r"[\u3400-\u9fff]", text or ""))


def split_lines(body: str) -> list[str]:
    lines: list[str] = []
    for part in re.split(r"[。！？；\n]", body or ""):
        part = part.strip(" ，、：:；;。！？\t\r\n")
        if part:
            lines.append(part)
    return lines


def load_poems() -> tuple[list[dict], dict[tuple[str, str], list[dict]]]:
    poems = json.loads(POEMS_PATH.read_text(encoding="utf-8"))
    lookup: dict[tuple[str, str], list[dict]] = {}
    for poem in poems:
        poet = poem.get("poet") or poem.get("author")
        lookup.setdefault((poet, poem["title"]), []).append(poem)
    for rows in lookup.values():
        rows.sort(key=lambda p: (p.get("source_poem_id") or "", p.get("body_hash") or ""))
    return poems, lookup


def find_poem(lookup: dict[tuple[str, str], list[dict]], context: dict) -> dict:
    poet, title = context["poet"], context["title"]
    candidates = list(lookup.get((poet, title), []))
    alias = TITLE_ALIASES.get((poet, title))
    if not candidates and alias:
        candidates = list(lookup.get((poet, alias), []))
    if not candidates:
        normalized = re.sub(r"[·・\s]", "", title)
        for (who, name), rows in lookup.items():
            if who == poet and re.sub(r"[·・\s]", "", name) == normalized:
                candidates.extend(rows)
    if not candidates:
        raise KeyError(f"语料中找不到关联诗篇：{poet}《{title}》")
    if len(candidates) == 1:
        return candidates[0]

    source_blob = context.get("source_url", "") + " " + context.get("source_note", "")
    ids = set(re.findall(r"shiwenv_([0-9a-f]{8,})", source_blob, flags=re.I))
    ids.update(re.findall(r"/([0-9a-f]{12})\.aspx", source_blob, flags=re.I))
    by_id = [p for p in candidates if (p.get("source_poem_id") or "").lower() in {x.lower() for x in ids}]
    if len(by_id) == 1:
        return by_id[0]

    source_han = "".join(re.findall(r"[\u3400-\u9fff]", source_blob))
    scored: list[tuple[int, dict]] = []
    for poem in candidates:
        body_han = "".join(re.findall(r"[\u3400-\u9fff]", poem.get("body") or ""))
        best = 0
        for width in range(min(32, len(source_han)), 5, -1):
            if any(source_han[i:i + width] in body_han for i in range(len(source_han) - width + 1)):
                best = width
                break
        scored.append((best, poem))
    top_score = max(score for score, _ in scored)
    by_quote = [poem for score, poem in scored if score == top_score and score >= 6]
    if len(by_quote) == 1:
        return by_quote[0]

    body_groups: dict[str, list[dict]] = {}
    for poem in candidates:
        body_groups.setdefault(poem.get("body_hash") or poem.get("body") or "", []).append(poem)
    if len(body_groups) == 1:
        return candidates[0]
    raise AssertionError(
        f"同题语料存在多个正文且来源ID未消歧：{poet}《{title}》 "
        f"候选={[p.get('source_poem_id') for p in candidates]}"
    )


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = []
        for raw in csv.DictReader(fh):
            rows.append({str(k).strip(): (v.strip() if isinstance(v, str) else v) for k, v in raw.items()})
        return rows


def optional_int(value: str | None) -> int | None:
    value = (value or "").strip()
    return int(value) if value else None


def optional_float(value: str | None) -> float | None:
    value = (value or "").strip()
    return float(value) if value else None


def stable_id(row: dict) -> str:
    raw = "|".join([
        row.get("poet", ""), row.get("title", ""), row.get("year_start", ""),
        row.get("year_end", ""), row.get("source_url", ""), row.get("status", ""),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def load_contexts() -> tuple[list[dict], list[dict]]:
    selected: list[dict] = []
    superseded: list[dict] = []
    for row in read_csv(VERIFIED_PATH):
        row["review_state"] = "approved"
        row["year_precision"] = "year" if row.get("year_start") == row.get("year_end") else "range"
        selected.append(row)
    for poet, path in CANDIDATE_FILES.items():
        for row in read_csv(path):
            assert row.get("poet") == poet, f"候选文件作者错位：{path.name}"
            if row.get("status") == "superseded_by_verified":
                superseded.append(row)
                continue
            row["review_state"] = "candidate"
            selected.append(row)
    return selected, superseded


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_png(path: Path) -> tuple[bool, str]:
    """Validate the complete PNG envelope before exposing an optional asset."""
    if not path.is_file():
        return False, "文件不存在"
    try:
        payload = path.read_bytes()
    except OSError as exc:
        return False, f"读取失败：{exc}"
    if len(payload) < 45:
        return False, "文件过小"
    if not payload.startswith(PNG_SIGNATURE):
        return False, "PNG签名错误"

    offset = len(PNG_SIGNATURE)
    saw_ihdr = False
    saw_idat = False
    saw_iend = False
    while offset + 12 <= len(payload):
        length = int.from_bytes(payload[offset:offset + 4], "big")
        chunk_type = payload[offset + 4:offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        chunk_end = data_end + 4
        if chunk_end > len(payload):
            return False, "PNG数据块截断"
        expected_crc = int.from_bytes(payload[data_end:chunk_end], "big")
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(payload[data_start:data_end], actual_crc) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            return False, f"{chunk_type.decode('ascii', errors='replace')}校验失败"
        if not saw_ihdr:
            if chunk_type != b"IHDR" or length != 13:
                return False, "首个数据块不是有效IHDR"
            width = int.from_bytes(payload[data_start:data_start + 4], "big")
            height = int.from_bytes(payload[data_start + 4:data_start + 8], "big")
            if width <= 0 or height <= 0:
                return False, "IHDR尺寸无效"
            saw_ihdr = True
        if chunk_type == b"IDAT":
            saw_idat = True
        if chunk_type == b"IEND":
            if length != 0:
                return False, "IEND长度无效"
            saw_iend = True
            if chunk_end != len(payload):
                return False, "IEND后存在多余数据"
            break
        offset = chunk_end
    if not saw_ihdr:
        return False, "缺少IHDR"
    if not saw_idat:
        return False, "缺少IDAT"
    if not saw_iend:
        return False, "缺少IEND"
    return True, "有效PNG"


def precision_display(value: str | None) -> str:
    return YEAR_PRECISION_DISPLAY.get((value or "unknown").strip(), YEAR_PRECISION_DISPLAY["unknown"])


def scene_excerpt(body: str, evidence: str) -> list[str]:
    lines = split_lines(body)
    if not lines:
        return []
    selected: list[str] = []
    evidence = (evidence or "").strip()
    if evidence:
        for line in lines:
            if evidence in line or line in evidence:
                selected.append(line)
                break
    for line in lines:
        if line not in selected:
            selected.append(line)
        if len(selected) >= 4:
            break
    return selected


def make_prompt(scene: dict) -> dict:
    key = f"{scene['poet_key']}-{scene['id']}"
    image_file = SCENE_DIR / f"{key}.png"
    image_valid, image_note = validate_png(image_file)
    excerpt = "；".join(scene["poem_lines"][:2]) or "正文摘句缺失"
    prompt = (
        "用途：诗人史料行旅动画中的单一诗篇宽幅镜头。"
        f"具体诗篇：{scene['poet']}《{scene['poem_title']}》。"
        f"年份：{scene['year_label']}年（{scene['year_precision_display']}）。"
        f"地点：{scene['place_historical']}（今{scene['place_modern']}）。"
        f"正文摘句：『{excerpt}』。"
        f"史料等级：{scene['source_grade']}级，{scene['source_status']}，来源为{scene['source_name']}。"
        f"时代环境：{scene['dynasty']}代文人创作场景，服饰、器物、建筑与自然环境服从该镜头的时代和地点。"
        "风格：克制的中国水墨设色与电影分镜结合，纸张肌理，真实空间层次，非卡通。"
        "构图：3:2横幅，人物位于一侧三分之一，另一侧保留山水和地图信息空间。"
        "限制：画面内不要文字、印章、标志、现代物件、奇幻建筑；这是AI场景重建，不是肖像复原。"
    )
    return {
        "poet": scene["poet"],
        "poet_key": scene["poet_key"],
        "scene_id": scene["id"],
        "key": key,
        "year_start": scene["year_start"],
        "year_end": scene["year_end"],
        "year_precision": scene["year_precision"],
        "year_precision_display": scene["year_precision_display"],
        "place_historical": scene["place_historical"],
        "place_modern": scene["place_modern"],
        "poem_title": scene["poem_title"],
        "poem_excerpt": scene["poem_lines"][:2],
        "source_grade": scene["source_grade"],
        "source_name": scene["source_name"],
        "model": "gpt-image-2",
        "size": "1536x1024",
        "quality": "medium",
        "prompt": prompt,
        "output": f"generated_scenes/{key}.png",
        "status": "ready" if image_valid else "prompt_ready",
        "asset_validation": image_note,
        "disclosure": "AI场景重建，不是肖像复原；不参与史料计算。",
    }


def build_data() -> tuple[dict, dict]:
    poems, poem_lookup = load_poems()
    contexts, superseded = load_contexts()
    emotion_payload = json.loads(EMOTION_PATH.read_text(encoding="utf-8"))
    emotion_by_hash = {row["body_hash"]: row for row in emotion_payload["profiles"]}
    stories: list[dict] = []
    all_scenes: list[dict] = []
    unresolved: list[dict] = []

    for poet, cfg in POET_CONFIG.items():
        poet_contexts = [row for row in contexts if row.get("poet") == poet]
        assert poet_contexts, f"没有读到{poet}编年记录"
        dated: list[tuple[dict, dict]] = []
        for row in poet_contexts:
            grade = row.get("fact_grade") or "D"
            year_start = optional_int(row.get("year_start"))
            year_end = optional_int(row.get("year_end"))
            if grade == "D" or year_start is None or year_end is None:
                precision = row.get("year_precision") or "unknown"
                unresolved.append({
                    "poet": poet,
                    "title": row.get("title"),
                    "grade": grade,
                    "year_precision": precision,
                    "year_precision_display": precision_display(precision),
                    "reason": "D级且未找到可靠年份；排除于路线与碰撞之外",
                    "source_name": row.get("source_name") or "",
                    "source_url": row.get("source_url") or "",
                    "source_note": row.get("source_note") or "",
                })
                continue
            poem = find_poem(poem_lookup, row)
            dated.append((row, poem))

        dated.sort(key=lambda pair: (
            int(pair[0]["year_start"]), int(pair[0]["year_end"]),
            pair[1].get("source_poem_id") or "", stable_id(pair[0]),
        ))
        cfg = POET_CONFIG[poet]
        scenes: list[dict] = []
        previous_end: int | None = None
        for idx, (row, poem) in enumerate(dated):
            profile = emotion_by_hash.get(poem.get("body_hash")) or {}
            evidence_words = profile.get("evidence") or []
            lines = scene_excerpt(poem.get("body", ""), evidence_words[0] if evidence_words else "")
            lon = optional_float(row.get("lon"))
            lat = optional_float(row.get("lat"))
            map_eligible = lon is not None and lat is not None
            grade = row.get("fact_grade") or "C"
            source_status = "已审核" if row.get("review_state") == "approved" else "候选·推定"
            year_start = int(row["year_start"])
            year_end = int(row["year_end"])
            precision = row.get("year_precision") or ("year" if year_start == year_end else "range")
            sequence = "overlap" if previous_end is not None and year_start <= previous_end else "strict"
            previous_end = max(previous_end or year_end, year_end)
            chars = han_count("".join(lines))
            year_label = str(year_start) if year_start == year_end else f"{year_start}—{year_end}"
            place_hist = row.get("historical_place") or "创作地未定"
            place_modern = row.get("modern_city") or "未定位"
            school = poem.get("school") or cfg["school"]
            assert school == cfg["school"], f"{poet}流派字段不一致：{school}"
            scene = {
                "index": idx,
                "id": stable_id(row),
                "poet": poet,
                "poet_key": cfg["key"],
                "color": cfg["color"],
                "dynasty": row.get("dynasty") or cfg["dynasty"],
                "school": school,
                "year": year_start,
                "year_start": year_start,
                "year_end": year_end,
                "year_label": year_label,
                "year_precision": precision,
                "year_precision_display": precision_display(precision),
                "sequence": sequence,
                "place_historical": place_hist,
                "place_modern": place_modern,
                "province": row.get("province") or "",
                "lon": lon,
                "lat": lat,
                "map_eligible": map_eligible,
                "event": (
                    f"史料记录将《{poem['title']}》标注为{year_label}年"
                    f"（{precision_display(precision)}），创作地记为{place_hist}。"
                ),
                "poem_title": poem["title"],
                "source_poem_id": poem.get("source_poem_id") or "",
                "body_hash": poem.get("body_hash") or "",
                "poem_lines": lines,
                "poem_chars": han_count(poem.get("body", "")),
                "source_grade": grade,
                "source_status": source_status,
                "review_state": row.get("review_state"),
                "source_name": row.get("source_name") or "",
                "source_url": row.get("source_url") or "",
                "source_note": row.get("source_note") or "",
                "confidence": profile.get("confidence"),
                "life_label": "诗篇编年节点",
                "life_reason": "由作品系年表生成，不继承人工行旅叙事标签。",
                "emotion_label": profile.get("summary") or profile.get("primary_label") or "低置信文本特征",
                "valence": profile.get("valence"),
                "intensity": profile.get("arousal"),
                "emotion_evidence": "、".join(evidence_words[:4]),
                "relation": "同作者、同题记录与语料原文绑定",
                "relation_grade": grade,
                "read_seconds": max(9, min(24, 7 + chars // 3)),
            }
            image_key = f"{cfg['key']}-{scene['id']}"
            image_file = SCENE_DIR / f"{image_key}.png"
            image_valid, image_note = validate_png(image_file)
            scene["image_key"] = image_key
            scene["scene_image"] = (
                f"assets/competition/generated_scenes/{image_key}.png" if image_valid else ""
            )
            scene["scene_image_validation"] = image_note
            scenes.append(scene)
            all_scenes.append(scene)

        years = [scene["year_start"] for scene in scenes]
        end_year = max(scene["year_end"] for scene in scenes)
        segments = []
        for left, right in zip(scenes, scenes[1:]):
            strict_dates = left["year_end"] < right["year_start"]
            precise = left["year_precision"] not in {"disputed", "unknown"} and right["year_precision"] not in {"disputed", "unknown"}
            if strict_dates and precise and left["map_eligible"] and right["map_eligible"]:
                segments.append({
                    "from_id": left["id"], "to_id": right["id"],
                    "from_index": left["index"], "to_index": right["index"],
                    "coords": [[left["lon"], left["lat"]], [right["lon"], right["lat"]]],
                    "kind": "chronology", "certainty": "strict",
                })
        stories.append({
            "key": cfg["key"],
            "poet": poet,
            "dynasty": cfg["dynasty"],
            "school": cfg["school"],
            "color": cfg["color"],
            "title": f"{poet} · {min(years)}—{end_year}",
            "lede": f"系统从 {len(poet_contexts)} 条审核/候选系年中生成 {len(scenes)} 个可系年镜头",
            "year_start": min(years),
            "year_end": end_year,
            "scene_count": len(scenes),
            "mapped_scene_count": sum(1 for scene in scenes if scene["map_eligible"]),
            "context_count": len(poet_contexts),
            "segments": segments,
            "scenes": scenes,
        })

    assert len(stories) == 6, f"自动片单应覆盖6位诗人，实际{len(stories)}"
    assert len(contexts) == 127, f"来源去重后应为127条，实际{len(contexts)}"
    assert len(unresolved) == 5, f"D级未系年记录应为5条，实际{len(unresolved)}"
    assert len(all_scenes) == 122, f"可系年A-C镜头应为122，实际{len(all_scenes)}"
    mapped_count = sum(1 for scene in all_scenes if scene["map_eligible"])
    assert mapped_count == 113, f"可落图镜头应为113，实际{mapped_count}"

    province_school_counts: dict[str, Counter[str]] = {}
    school_totals: Counter[str] = Counter()
    for scene in all_scenes:
        if not scene["map_eligible"] or not scene["province"]:
            continue
        province_school_counts.setdefault(scene["province"], Counter())[scene["school"]] += 1
        school_totals[scene["school"]] += 1
    assert sum(school_totals.values()) == mapped_count, "省域流派汇总必须覆盖全部落图镜头"
    province_rows = []
    for province, counts in sorted(province_school_counts.items()):
        total = sum(counts.values())
        province_rows.append({
            "name": province,
            "total": total,
            "schools": [
                {
                    "name": school,
                    "color": color,
                    "count": counts[school],
                    "share": round(counts[school] / total, 4),
                }
                for school, color in SCHOOL_COLORS.items()
                if counts[school]
            ],
        })
    school_geography = {
        "basis": "当前六位诗人的可落图编年镜头；每个镜头计一次，不外推为全唐宋诗坛比例。",
        "total_nodes": mapped_count,
        "province_count": len(province_rows),
        "schools": [
            {
                "name": school,
                "color": color,
                "count": school_totals[school],
                "share": round(school_totals[school] / mapped_count, 4),
                "poets": [poet for poet, cfg in POET_CONFIG.items() if cfg["school"] == school],
            }
            for school, color in SCHOOL_COLORS.items()
        ],
        "provinces": province_rows,
    }

    by_year: dict[int, list[dict]] = {}
    for scene in all_scenes:
        if (
            scene["year_start"] == scene["year_end"]
            and scene["year_precision"] not in {"disputed", "unknown"}
        ):
            by_year.setdefault(scene["year_start"], []).append(scene)
    collisions = []
    for year, rows in sorted(by_year.items()):
        if len({row["poet"] for row in rows}) < 2:
            continue
        certainty = (
            "exact"
            if all(row["year_precision"] in {"year", "exact"} for row in rows)
            else "mixed"
        )
        certainty_display = "明确同年" if certainty == "exact" else "系年指向该年（含约年）"
        collisions.append({
            "year": year,
            "title": f"平行时空 {year}",
            "certainty": certainty,
            "certainty_display": certainty_display,
            "lede": f"{certainty_display}：{len(rows)} 个编年节点把不同诗人的处境并置",
            "scenes": rows,
        })
    collisions.sort(key=lambda row: (0 if row["year"] == 759 else 1, row["year"]))
    assert any(row["year"] == 759 for row in collisions), "应自动检测到759年同年碰撞"

    prompts = {
        "schema_version": 3,
        "generator_version": "auto-story/3.0",
        "generator": "gpt-image-2 prompt manifest",
        "network_note": "默认只生成本地计划；显式执行生成器才调用当前Codex provider。页面仅展示通过完整PNG校验的逐镜头资产。",
        "items": [make_prompt(scene) for scene in all_scenes],
    }
    assert len(prompts["items"]) == 122, "每个可系年镜头都应有一条图像提示"
    assert len({item["key"] for item in prompts["items"]}) == 122, "镜头图像键必须唯一"
    data = {
        "meta": {
            "page": "33_史料自动成片",
            "generator_version": "auto-story/3.0",
            "corpus_poems": len(poems),
            "story_count": len(stories),
            "scene_count": len(all_scenes),
            "mapped_scene_count": mapped_count,
            "selected_context_count": len(contexts),
            "superseded_count": len(superseded),
            "unresolved_count": len(unresolved),
            "collision_count": len(collisions),
            "default_mode": "manual_step",
            "engine": "Apache ECharts（Apache-2.0）+ 原生状态机",
            "input_sha256": {
                "poems.json": file_sha256(POEMS_PATH),
                "verified_poem_contexts.csv": file_sha256(VERIFIED_PATH),
                "emotion_profiles.json": file_sha256(EMOTION_PATH),
                **{path.name: file_sha256(path) for path in CANDIDATE_FILES.values()},
            },
        },
        "method": {
            "route_rule": "合并41条审核记录与六份候选编年，丢弃37条superseded候选；按year_start、year_end、作品ID稳定排序。",
            "line_rule": "只有相邻记录年份区间不重叠、均非争议系年且都有坐标时才连接；缺坐标或争议记录会断线。连线不代表实际道路。",
            "poem_rule": "同作者、同题记录与 poems.json 原文绑定；同题多正文优先使用来源URL中的作品ID消歧，不能消歧则停止构建。",
            "source_rule": "审核记录显示已审核；候选记录显示候选·推定。A/B/C进入时间轴，D级无系年记录只列入未决清单。",
            "collision_rule": "跨诗人且year_start等于year_end的记录自动聚合；year/exact组标为明确同年，含approximate组标为系年指向该年（含约年），disputed不进入碰撞。并置不证明诗人互相影响。",
            "school_rule": "流派标签来自与编年记录绑定的 poems.json；省域占比只统计本页六位诗人的113个有坐标镜头，同一地点的多个镜头分别计数，不外推为全唐宋诗坛比例。",
            "image_rule": "每个镜头独立匹配通过签名、IHDR尺寸、至少一个IDAT数据块、逐块CRC与IEND校验的PNG。AI场景重建，不是肖像复原；不参与史料计算。",
        },
        "stories": stories,
        "school_geography": school_geography,
        "collisions": collisions,
        "unresolved": unresolved,
        "diagnostics": {
            "superseded_count": len(superseded),
            "unmapped_dated_count": len(all_scenes) - mapped_count,
            "line_semantics": "chronology_only",
        },
        "scene_prompts": prompts["items"],
    }
    return data, prompts


HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' fill='%23f2f4f0'/%3E%3Cpath d='M15 13h34v8H23v9h22v8H23v13h-8z' fill='%23b64b3f'/%3E%3C/svg%3E">
<title>史料自动成片 · 平行时空759 · 诗行万里</title>
<style>
:root{--paper:#f2f4f0;--ink:#252b27;--muted:#6f756f;--line:#d9ddd7;--red:#b64b3f;--jade:#26786e;--gold:#a87527;--blue:#426f94;}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font-family:"Microsoft YaHei",sans-serif;line-height:1.7;letter-spacing:0;}
button,select{font:inherit}button{cursor:pointer}h1,h2,h3,.kai{font-family:KaiTi,STKaiti,"Microsoft YaHei",serif;font-weight:700;letter-spacing:0}
.wrap{width:min(1380px,calc(100% - 36px));margin:0 auto}.hero{padding:34px 0 22px;border-bottom:1px solid var(--line)}
.eyebrow{font-size:12px;letter-spacing:0;color:var(--red);font-weight:700}.hero h1{margin:4px 0 2px;font-size:clamp(30px,4vw,52px)}
.hero p{margin:4px 0;color:var(--muted);max-width:930px}.kpis{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}.kpi{border-left:3px solid var(--gold);padding:4px 10px;background:#fff8;font-size:13px}
.section{padding:26px 0}.section-title{display:flex;align-items:baseline;gap:10px;margin:0 0 12px}.section-title .no{color:var(--red);font-size:15px}.section-title h2{font-size:25px;margin:0}
.toolbar{display:grid;grid-template-columns:minmax(220px,1fr) auto auto;gap:12px;align-items:center;border:1px solid var(--line);background:#fff;padding:12px 14px;border-radius:6px}
.story-pick{display:flex;align-items:center;gap:10px;min-width:0}.story-pick label{font-size:12px;color:var(--muted);white-space:nowrap}.story-pick select{width:100%;min-width:0;border:1px solid #bcc4bb;background:#fff;color:var(--ink);padding:8px 10px;border-radius:4px}
.seg{display:flex;border:1px solid #bcc4bb;border-radius:4px;overflow:hidden}.seg button{border:0;border-right:1px solid #bcc4bb;background:#fff;padding:8px 11px;color:var(--muted)}.seg button:last-child{border-right:0}.seg button.on{background:var(--ink);color:#fff}
.actions{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}.btn{border:1px solid #aeb7ad;background:#fff;color:var(--ink);border-radius:4px;padding:8px 12px;min-height:40px}.btn.primary{background:var(--red);border-color:var(--red);color:#fff}.btn:disabled{opacity:.42;cursor:default}
.progress{grid-column:1/-1;display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:10px;font-size:12px;color:var(--muted)}.track{height:4px;background:#e4e8e2}.fill{height:100%;background:var(--red);width:0;transition:width .35s ease}
.stage{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(330px,.8fr);min-height:610px;border:1px solid var(--line);border-radius:6px;background:#fff;overflow:hidden;margin-top:12px}
.map-pane{position:relative;min-width:0;background:#edf0e8}.map{height:610px;width:100%}.map-note{position:absolute;left:14px;bottom:12px;right:14px;background:#fffffff0;border:1px solid var(--line);padding:8px 10px;font-size:12px;color:var(--muted);pointer-events:none;z-index:3}
.map-controls{position:absolute;z-index:3;top:14px;left:14px;width:min(290px,calc(100% - 28px));padding:11px 12px;border:1px solid #d3d9d2;border-radius:5px;background:#fffffff2;box-shadow:0 3px 14px #33413716}.map-control-head{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:8px}.map-control-head b{font-family:KaiTi,STKaiti,serif;font-size:17px}.map-control-head span{font-size:11px;color:var(--muted);white-space:nowrap}.map-layer-seg{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid #b9c1b8;border-radius:4px;overflow:hidden}.map-layer-seg button{border:0;border-right:1px solid #b9c1b8;background:#fff;color:var(--muted);padding:5px 6px;font-size:11px}.map-layer-seg button:hover{background:#eef1ed;color:var(--ink)}.map-layer-seg button:focus-visible{outline:2px solid var(--blue);outline-offset:-2px}.map-layer-seg button:last-child{border-right:0}.map-layer-seg button.on{background:var(--ink);color:#fff}.school-legend{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:4px 10px;margin-top:9px}.school-key{display:flex;align-items:center;gap:6px;min-width:0;font-size:11px;color:#505750}.school-swatch{width:18px;height:6px;flex:0 0 auto;background:var(--sc);transform:skewX(-28deg)}.school-key b{font-weight:600}.school-key span:last-child{color:var(--muted);margin-left:auto}
.story-pane{min-width:0;padding:22px;display:flex;flex-direction:column;gap:13px;border-left:1px solid var(--line);position:relative;overflow:hidden}.story-pane.with-art:before{content:"";position:absolute;inset:0;background-image:var(--scene);background-size:cover;background-position:center;opacity:.12;filter:saturate(.7)}.story-pane>*{position:relative}
.scene-head{border-top:3px solid var(--pc,var(--blue));padding-top:10px}.scene-head h3{font-size:24px;line-height:1.25;margin:0}.scene-meta{color:var(--muted);font-size:13px;margin-top:4px}.badges{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.badge{display:inline-flex;border:1px solid currentColor;border-radius:99px;padding:2px 8px;font-size:11px}.grade-a,.grade-b{color:var(--jade)}.grade-c{color:var(--gold)}.ai{color:#8a5b89}
.event{font-size:14px;color:#444;border-left:3px solid var(--gold);padding:7px 10px;background:#f7f3e9}.poem{font-family:KaiTi,STKaiti,serif;font-size:20px;line-height:1.75;padding:8px 0}.poem div{opacity:0;transform:translateY(5px);animation:linein .5s ease forwards}.poem div:nth-child(2){animation-delay:.12s}.poem div:nth-child(3){animation-delay:.24s}.poem div:nth-child(4){animation-delay:.36s}@keyframes linein{to{opacity:1;transform:none}}
.emotion{display:grid;grid-template-columns:1fr auto;gap:4px 10px;font-size:12px}.emotion .meter{grid-column:1/-1;height:5px;background:#e4e8e2}.emotion .meter i{display:block;height:100%;background:var(--pc,var(--blue));width:50%}
.source{margin-top:auto;border-top:1px dashed var(--line);padding-top:10px;font-size:12px;color:var(--muted)}.source details summary{cursor:pointer;color:var(--ink)}.source a{color:var(--blue)}
.ai-note{font-size:11px;color:#765d75}.ai-note code{font-family:Consolas,monospace;background:#fff;padding:1px 4px;border:1px solid var(--line)}
.collision{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.collision-card{background:#fff;border-top:3px solid var(--pc);padding:15px;border-radius:5px}.collision-card h3{margin:0}.collision-card .quote{font-family:KaiTi,STKaiti,serif;font-size:18px;margin:8px 0}.collision-card p{font-size:13px;color:var(--muted)}
.collision-pick{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 12px}.collision-pick label{font-size:12px;color:var(--muted)}.collision-pick select{min-width:min(260px,100%);max-width:100%;border:1px solid #bcc4bb;background:#fff;padding:7px 9px;border-radius:4px}.certainty{display:inline-flex;border:1px solid var(--gold);color:#765312;padding:2px 8px;border-radius:99px;font-size:11px}.certainty.exact{border-color:var(--jade);color:var(--jade)}
.pipeline{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line)}.pipe{background:#fff;padding:14px}.pipe b{display:block;color:var(--red);font-family:KaiTi,serif;font-size:18px}.pipe span{font-size:12px;color:var(--muted)}
.route-table{width:100%;border-collapse:collapse;font-size:12px}.route-table th,.route-table td{padding:8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}.route-table th{color:var(--muted);font-weight:500}.table-scroll{overflow:auto;background:#fff;border:1px solid var(--line);border-radius:5px}
.method{border:1px solid var(--line);background:#fff;border-radius:5px;padding:0 14px}.method summary{cursor:pointer;padding:12px 0}.method-body{border-top:1px solid var(--line);padding:12px 0 16px;font-size:13px;color:var(--muted)}.method-body li{margin:5px 0}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
footer{border-top:1px solid var(--line);padding:20px 0 36px;text-align:center}footer a{color:var(--blue);font-size:12px;margin:0 7px;text-decoration:none}footer a.active{color:var(--red);font-weight:700}
@media(max-width:820px){.wrap{width:min(100% - 18px,1380px)}.toolbar{grid-template-columns:1fr}.progress{grid-column:auto}.actions{justify-content:flex-start}.stage{grid-template-columns:1fr}.map{height:460px}.stage{min-height:0}.story-pane{border-left:0;border-top:1px solid var(--line);padding:17px}.collision{grid-template-columns:1fr}.pipeline{grid-template-columns:1fr 1fr}.hero{padding-top:22px}.section{padding:20px 0}}
@media(max-width:430px){.actions .btn{flex:1 1 calc(50% - 5px)}.seg{width:100%}.seg button{flex:1}.story-pick{align-items:flex-start;flex-direction:column}.map{height:440px}.map-controls{top:9px;left:9px;width:calc(100% - 18px);padding:9px}.map-control-head b{font-size:16px}.map-note{left:9px;right:9px;bottom:9px}.pipeline{grid-template-columns:1fr}.poem{font-size:18px}.scene-head h3{font-size:21px}footer a{display:inline-block;margin:4px 5px}}
</style>
</head>
<body>
<header class="hero"><div class="wrap">
  <div class="eyebrow">33 · 史料驱动的自动叙事</div>
  <h1>诗篇有年，行旅自动成片</h1>
  <p>系统合并诗篇系年、审核记录与候选史料，自动排序年份区间、落图并生成镜头。精确年份与约年均保留并明确标注；地图以省界内按比例交错的细线纹理呈现本页六位诗人的省域占比。</p>
  <div class="kpis"><span class="kpi" id="kCorpus"></span><span class="kpi" id="kStories"></span><span class="kpi" id="kScenes"></span><span class="kpi" id="kProvince"></span><span class="kpi" id="kCollision"></span></div>
</div></header>

<main class="wrap">
<section class="section">
  <div class="section-title"><span class="no">壹</span><h2>自动片单</h2></div>
  <div class="toolbar">
    <div class="story-pick"><label for="storySelect">由史料生成的影片</label><select id="storySelect"></select></div>
    <div class="seg" aria-label="播放模式"><button id="manualMode" class="on" aria-pressed="true" title="每站停留">逐站阅读</button><button id="autoMode" aria-pressed="false" title="按阅读时长自动前进">自动播放</button></div>
    <div class="actions"><button class="btn" id="restartBtn" title="回到本卷开头">↺ 重播</button><button class="btn" id="prevBtn" title="上一史料节点">← 上一步</button><button class="btn primary" id="nextBtn" title="下一史料节点">下一步 →</button></div>
    <div class="progress" id="storyProgress" role="progressbar" aria-label="本卷镜头进度" aria-valuemin="1" aria-valuenow="1" aria-valuemax="1"><span id="stepLabel">1 / 1</span><div class="track"><div class="fill" id="progressFill"></div></div><span id="readClock">逐站停留</span></div>
  </div>
  <div class="stage">
    <div class="map-pane">
      <div class="map" id="routeMap"></div>
      <div class="map-controls" aria-label="省域流派地图图层">
        <div class="map-control-head"><b>省域流派谱</b><span id="schoolSample"></span></div>
        <div class="map-layer-seg" aria-label="地图图层模式"><button type="button" class="on" data-map-mode="both" aria-pressed="true">叠加</button><button type="button" data-map-mode="school" aria-pressed="false">只看流派</button><button type="button" data-map-mode="route" aria-pressed="false">只看行旅</button></div>
        <div class="school-legend" id="schoolLegend"></div>
      </div>
      <div class="map-note" id="mapNote">等粗细线以固定小间隔铺满省域；颜色线数按真实样本占比分配并交错排列。悬停省份查看全部六个流派。</div>
    </div>
    <article class="story-pane" id="storyPane">
      <div class="sr-only" id="sceneStatus" role="status" aria-live="polite"></div>
      <div class="scene-head" id="sceneHead"><h3 id="sceneTitle"></h3><div class="scene-meta" id="sceneMeta"></div><div class="badges" id="sceneBadges"></div></div>
      <div class="event" id="sceneEvent"></div>
      <div class="poem" id="poemLines"></div>
      <div class="emotion"><span id="emotionLabel"></span><span id="emotionValue"></span><div class="meter"><i id="emotionMeter"></i></div></div>
      <div class="source" id="sourceBox"></div>
      <div class="ai-note" id="aiNote"></div>
    </article>
  </div>
</section>

<section class="section" id="collisionSection">
  <div class="section-title"><span class="no">贰</span><h2 id="collisionTitle">平行时空</h2></div>
  <div class="collision-pick"><label for="collisionSelect">自动检出组</label><select id="collisionSelect"></select><span class="certainty" id="collisionCertainty"></span></div>
  <p id="collisionLede" style="color:var(--muted);margin-top:-5px"></p>
  <div class="collision" id="collisionCards"></div>
</section>

<section class="section">
  <div class="section-title"><span class="no">叁</span><h2>自动成片规则</h2></div>
  <div class="pipeline">
    <div class="pipe"><b>01 诗篇系年</b><span>合并审核记录与仍有效的候选编年。</span></div>
    <div class="pipe"><b>02 地点落图</b><span>只使用诗篇系年记录中已有的地点坐标。</span></div>
    <div class="pipe"><b>03 时间排序</b><span>按年份区间与作品ID稳定排序，重叠区间不强排。</span></div>
    <div class="pipe"><b>04 绑定原诗</b><span>同作者诗题与 poems.json 原文逐项核对。</span></div>
    <div class="pipe"><b>05 生成镜头</b><span>停留时长由展示诗句长度计算，默认等待“下一步”。</span></div>
  </div>
  <details class="method" style="margin-top:12px"><summary>方法、来源与模型画面边界</summary><div class="method-body" id="methodBody"></div></details>
</section>

<section class="section">
  <div class="section-title"><span class="no">肆</span><h2>本卷节点证据</h2></div>
  <div class="table-scroll"><table class="route-table"><thead><tr><th>序</th><th>年份</th><th>地点</th><th>流派</th><th>诗篇</th><th>等级</th><th>来源</th></tr></thead><tbody id="routeRows"></tbody></table></div>
</section>

<section class="section" id="unresolvedSection">
  <div class="section-title"><span class="no">伍</span><h2>D级未决清单</h2></div>
  <p style="color:var(--muted)">以下5条未找到可靠年份，明确排除于路线与碰撞之外；保留来源与排除依据供复核。</p>
  <div class="table-scroll"><table class="route-table"><thead><tr><th>诗人</th><th>诗篇</th><th>年份精度</th><th>排除原因</th><th>来源与说明</th></tr></thead><tbody id="unresolvedRows"></tbody></table></div>
</section>
</main>

<footer><div class="wrap">
  <a href="29_参赛导航.html">29 参赛导航</a><a href="30_诗行万里_参赛版.html">30 总入口</a><a href="31_凝望罗盘.html">31 凝望</a><a href="32_身与心双层地图.html">32 身心地图</a><a class="active" href="33_平行时空759.html">33 自动成片</a><a href="34_一字识诗人.html">34 一字识诗人</a><a href="35_两种孤独与夸张签名.html">35 孤独与夸张</a><a href="36_同龄对齐.html">36 同龄对齐</a><a href="37_可听的诗.html">37 可听的诗</a><a href="38_唐宋意象潮汐.html">38 意象潮汐</a><a href="39_诗人自述生命卷.html">39 诗人自述生命卷</a>
</div></footer>

<script src="assets/pyecharts/v6/echarts.min.js"></script>
<script src="assets/pyecharts/v6/maps/china.js"></script>
<script>window.AUTO_STORY_DATA=__DATA__;</script>
<script>
(function(){
"use strict";
var D=window.AUTO_STORY_DATA, stories=D.stories, geography=D.school_geography, storyIndex=0, stepIndex=0, collisionIndex=0, auto=false, timer=0, chart=null, mapMode="both", schoolLineCache={}, schoolLineRefreshTimer=0, maxMapZoom=4.6;
var schoolByName={}, provinceByName={};geography.schools.forEach(function(row){schoolByName[row.name]=row;});geography.provinces.forEach(function(row){provinceByName[row.name]=row;});
function esc(s){return String(s==null?"":s).replace(/[&<>\"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c];});}
function fmt(v){if(v==null||v!==v){return "—";}return (v>0?"+":"")+Number(v).toFixed(2);}
function pct(v){return (Number(v)*100).toFixed(v>0&&v<.1?1:0)+"%";}
function currentStory(){return stories[storyIndex];}function currentScene(){return currentStory().scenes[stepIndex];}
function initMeta(){
 document.getElementById("kCorpus").textContent=D.meta.corpus_poems.toLocaleString("zh-CN")+"篇全量语料";
 document.getElementById("kStories").textContent=D.meta.story_count+"卷自动影片";
 document.getElementById("kScenes").textContent=D.meta.scene_count+"个可系年镜头 · "+D.meta.mapped_scene_count+"个落图";
 document.getElementById("kProvince").textContent=geography.province_count+"个省域有流派样本";
 document.getElementById("kCollision").textContent=D.meta.collision_count+"组年份碰撞";
 document.getElementById("schoolSample").textContent=geography.total_nodes+"镜头 · "+geography.province_count+"省域";
 document.getElementById("schoolLegend").innerHTML=geography.schools.map(function(row){return '<div class="school-key" style="--sc:'+row.color+'"><span class="school-swatch"></span><b>'+esc(row.name)+'</b><span>'+row.count+'</span></div>';}).join("");
 Array.prototype.forEach.call(document.querySelectorAll("[data-map-mode]"),function(button){button.addEventListener("click",function(){mapMode=button.getAttribute("data-map-mode");syncMapControls();renderMap();});});
 var sel=document.getElementById("storySelect"); stories.forEach(function(s,i){var o=document.createElement("option");o.value=String(i);o.textContent=s.title+" · "+s.scene_count+"站";sel.appendChild(o);});
 sel.addEventListener("change",function(){stopAuto();storyIndex=Number(sel.value);stepIndex=0;renderAll(true);});
 var collisionSel=document.getElementById("collisionSelect");D.collisions.forEach(function(c,i){var o=document.createElement("option");o.value=String(i);o.textContent=c.year+"年 · "+c.certainty_display+" · "+c.scenes.length+"项";collisionSel.appendChild(o);});
 collisionSel.addEventListener("change",function(){collisionIndex=Number(collisionSel.value);renderCollision();});
}
function syncMapControls(){
 Array.prototype.forEach.call(document.querySelectorAll("[data-map-mode]"),function(button){var on=button.getAttribute("data-map-mode")===mapMode;button.classList.toggle("on",on);button.setAttribute("aria-pressed",String(on));});
 document.getElementById("schoolLegend").style.opacity=mapMode==="route"?".38":"1";
 document.getElementById("mapNote").textContent=mapMode==="route"?"只有年份可严格排序且坐标完整的相邻诗篇才连线；断线不是数据错误。地图可缩放，点可悬停查看史料。":"等粗细线以固定小间隔铺满省域；颜色线数按真实样本占比分配并交错排列。悬停省份查看全部六个流派。";
}
function interleavedSchoolSamples(row){
 var samples=[];row.schools.forEach(function(school,schoolIndex){for(var sample=0;sample<school.count;sample++){samples.push({school:school,sample:sample,schoolIndex:schoolIndex,order:(sample+.5)/school.count});}});
 samples.sort(function(a,b){return a.order-b.order||a.schoolIndex-b.schoolIndex;});return samples;
}
function weightedStripeSamples(row,total){
 var allocated=row.schools.map(function(school,schoolIndex){var exact=school.count/row.total*total,count=Math.floor(exact);return {name:school.name,color:school.color,count:count,share:school.share,schoolIndex:schoolIndex,remainder:exact-count};}),used=allocated.reduce(function(sum,school){return sum+school.count;},0);
 allocated.slice().sort(function(a,b){return b.remainder-a.remainder||a.schoolIndex-b.schoolIndex;}).slice(0,total-used).forEach(function(school){school.count++;});
 return interleavedSchoolSamples({schools:allocated.filter(function(school){return school.count>0;})});
}
function provinceFeatureMap(){var payload=echarts.getMap&&echarts.getMap("china"),geojson=payload&&(payload.geoJSON||payload.geoJson),out={};if(geojson&&Array.isArray(geojson.features)){geojson.features.forEach(function(feature){var name=feature.properties&&feature.properties.name;if(name){out[name]=feature;}});}return out;}
function provinceRings(feature){
 var geometry=feature&&feature.geometry,coordinates=geometry&&geometry.coordinates;if(!coordinates){return [];}
 if(geometry.type==="Polygon"){return coordinates[0]?[coordinates[0]]:[];}
 if(geometry.type==="MultiPolygon"){return coordinates.map(function(polygon){return polygon[0];}).filter(function(ring){return Array.isArray(ring)&&ring.length>2;});}
 return [];
}
function clippedProvinceSegments(ring,offset,direction,normal){
 var hits=[],epsilon=1e-8;
 for(var i=0;i<ring.length;i++){
  var a=ring[i],b=ring[(i+1)%ring.length],da=a[0]*normal[0]+a[1]*normal[1]-offset,db=b[0]*normal[0]+b[1]*normal[1]-offset,denom=da-db;
  if(Math.abs(denom)<epsilon){continue;}var t=da/denom;if(t<-epsilon||t>1+epsilon){continue;}var point=[a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t];
  if(!hits.some(function(hit){return Math.abs(hit[0]-point[0])<epsilon&&Math.abs(hit[1]-point[1])<epsilon;})){hits.push(point);}
 }
 hits.sort(function(a,b){return (a[0]*direction[0]+a[1]*direction[1])-(b[0]*direction[0]+b[1]*direction[1]);});
 var segments=[];for(var h=0;h+1<hits.length;h+=2){segments.push([hits[h],hits[h+1]]);}return segments;
}
function schoolLineData(zoom){
 if(mapMode==="route"){return [];}var visualZoom=Math.max(1,Math.round((Number(zoom)||2.15)*10)/10),cached=schoolLineCache[mapMode];if(cached&&cached.zoom===visualZoom){return cached.data;}var features=provinceFeatureMap(),lines=[],direction=[1,.18],magnitude=Math.sqrt(1+.18*.18);direction=[direction[0]/magnitude,direction[1]/magnitude];var normal=[-direction[1],direction[0]],geoPitch=.1*2.15/visualZoom;
 geography.provinces.forEach(function(row){provinceRings(features[row.name]).forEach(function(ring){
  var actualByName={};row.schools.forEach(function(school){actualByName[school.name]=school;});var projections=ring.map(function(point){return point[0]*normal[0]+point[1]*normal[1];}),minProjection=Math.min.apply(null,projections),maxProjection=Math.max.apply(null,projections),stripeCount=Math.min(520,Math.max(1,Math.ceil((maxProjection-minProjection)/geoPitch))),samples=weightedStripeSamples(row,stripeCount);
  samples.forEach(function(entry,index){var offset=minProjection+(index+.5)/stripeCount*(maxProjection-minProjection),school=entry.school,actual=actualByName[school.name];clippedProvinceSegments(ring,offset,direction,normal).forEach(function(coords){lines.push({name:row.name+" · "+school.name,province:row.name,school:school.name,count:actual.count,share:actual.share,coords:coords,lineStyle:{color:school.color,width:1.2,opacity:mapMode==="both"?.88:.98},emphasis:{lineStyle:{width:2,opacity:1}}});});});
 });});schoolLineCache[mapMode]={zoom:visualZoom,data:lines};return lines;
}
function provinceRegions(){if(mapMode==="route"){return [];}return geography.provinces.map(function(row){return {name:row.name,itemStyle:{areaColor:"#edf0e8",borderColor:"#9ba49b",borderWidth:.8},emphasis:{itemStyle:{areaColor:"#edf0e8",borderColor:"#3f4941",borderWidth:1.4},label:{show:true,color:"#252b27",fontSize:11}}};});}
function provinceSummary(row,currentSchool){
 if(!row){return "";}var counts={};row.schools.forEach(function(school){counts[school.name]=school;});
 var entries=geography.schools.map(function(school){var item=counts[school.name],count=item?item.count:0,share=row.total?count/row.total:0;return '<span style="display:inline-block;width:12px;height:4px;background:'+school.color+';margin-right:5px;vertical-align:middle"></span>'+esc(school.name)+" "+count+" · "+pct(share);});
 return "<b>"+esc(row.name)+"</b> · "+row.total+"个落图镜头<br>"+entries.join("<br>")+(currentSchool?"<br><span style='color:#777'>当前线："+esc(currentSchool)+"</span>":"")+"<br><span style='color:#777'>当前六位诗人编年样本</span>";
}
function mapTooltip(p){
 var scene=p.data&&p.data.scene;if(scene){return "<b>"+esc(scene.place_historical)+"</b> · "+scene.year_label+"<br>"+esc(scene.poet)+" · "+esc(scene.school)+" · 《"+esc(scene.poem_title)+"》<br>"+esc(scene.source_status+" "+scene.source_grade+"级");}
 var line=p.data&&p.data.school,provinceName=line&&line.province||p.name,row=provinceByName[provinceName];if(!row||mapMode==="route"){return p.name||"";}
 return provinceSummary(row,line&&line.school);
}
function routeData(story){return story.scenes.filter(function(s){return s.map_eligible;}).map(function(s){var i=s.index;return {name:s.place_historical,value:[s.lon,s.lat],scene:s,symbolSize:i===stepIndex?17:(i<stepIndex?11:9),itemStyle:{color:i===stepIndex?"#a87527":(i<stepIndex?story.color:"#fff"),borderColor:story.color,borderWidth:2},label:{show:i===stepIndex,position:"right",formatter:s.place_historical+"·"+s.year_label,color:i<=stepIndex?"#252b27":"#8b918a",fontSize:11}};});}
function renderMap(){
 var story=currentStory(), showRoute=mapMode!=="school", guides=showRoute?story.segments.map(function(seg){return {coords:seg.coords};}):[], traveled=showRoute?story.segments.filter(function(seg){return seg.to_index<=stepIndex;}).map(function(seg){return {coords:seg.coords};}):[];
 var previousGeo=chart&&chart.getOption().geo&&chart.getOption().geo[0],geoZoom=previousGeo&&Number(previousGeo.zoom)||2.15,geoCenter=previousGeo&&previousGeo.center||[108,32];
 if(!chart){chart=echarts.init(document.getElementById("routeMap"));chart.setOption({geo:{map:"china"}},true);chart.clear();chart.on("georoam",function(){window.clearTimeout(schoolLineRefreshTimer);schoolLineRefreshTimer=window.setTimeout(function(){if(mapMode==="route"){return;}renderMap();chart.getZr().refreshImmediately();},160);});window.addEventListener("resize",function(){chart.resize();});}
 chart.setOption({animationDurationUpdate:0,tooltip:{trigger:"item",confine:true,formatter:mapTooltip},geo:{map:"china",roam:true,scaleLimit:{min:1.2,max:maxMapZoom},zoom:Math.min(maxMapZoom,geoZoom),center:geoCenter,regions:provinceRegions(),tooltip:{show:true,formatter:mapTooltip},itemStyle:{areaColor:"#edf0e8",borderColor:"#c3cabe",borderWidth:.7},emphasis:{itemStyle:{areaColor:"#e6ebe4"}}},series:[{id:"school-lines",name:"省域流派细线",type:"lines",coordinateSystem:"geo",z:3,animation:false,symbol:["none","none"],lineStyle:{curveness:0,cap:"butt"},data:schoolLineData(Math.min(maxMapZoom,geoZoom))},{id:"guide",type:"lines",coordinateSystem:"geo",z:4,silent:true,lineStyle:{color:"#9ba49b",width:1.2,type:"dashed"},data:guides},{id:"traveled",type:"lines",coordinateSystem:"geo",z:5,silent:true,lineStyle:{color:story.color,width:3.2,cap:"round"},data:traveled},{id:"nodes",type:"effectScatter",coordinateSystem:"geo",z:6,showEffectOn:"emphasis",rippleEffect:{scale:2.7,brushType:"stroke"},data:showRoute?routeData(story):[]}]},{notMerge:false,replaceMerge:["series"],lazyUpdate:false});
 chart.getZr().refreshImmediately();
}
function renderScene(resetClock){
 var story=currentStory(), s=currentScene(), pane=document.getElementById("storyPane");pane.style.setProperty("--pc",story.color);pane.classList.toggle("with-art",!!s.scene_image);pane.style.setProperty("--scene",s.scene_image?'url("'+s.scene_image+'")':"none");
 document.getElementById("sceneTitle").textContent=s.life_label+" · "+s.place_historical;
 document.getElementById("sceneMeta").textContent=s.poet+" · "+s.year_label+"年 · "+(s.map_eligible?(s.place_historical+"（今"+s.place_modern+"）"):"创作地未定 · 时间轴镜头");
 document.getElementById("sceneBadges").innerHTML='<span class="badge grade-'+s.source_grade.toLowerCase()+'">'+esc(s.source_status+" "+s.source_grade+"级")+'</span><span class="badge" style="color:'+(schoolByName[s.school]||{}).color+'">'+esc(s.school)+'</span><span class="badge">'+esc(s.year_precision_display)+'</span><span class="badge">场景 '+(stepIndex+1)+'/'+story.scene_count+'</span>'+(s.scene_image?'<span class="badge ai">AI场景重建</span>':'');
 document.getElementById("sceneEvent").textContent=s.event;
 var poem=document.getElementById("poemLines");poem.innerHTML="";s.poem_lines.forEach(function(line){var d=document.createElement("div");d.textContent=line+"。";poem.appendChild(d);});
 document.getElementById("emotionLabel").textContent="文本标注："+s.emotion_label+(s.emotion_evidence?" · 证据「"+s.emotion_evidence+"」":" · 词典未提取到情绪关键词");
 document.getElementById("emotionValue").textContent="情感 "+fmt(s.valence)+" / 强度 "+fmt(s.intensity);
 var val=s.valence==null?0:Number(s.valence);document.getElementById("emotionMeter").style.width=(50+Math.max(-1,Math.min(1,val))*48)+"%";
 document.getElementById("sourceBox").innerHTML='<details><summary>史料依据 · '+esc(s.source_name)+'</summary><div>'+esc(s.source_note)+'<br>关联规则：'+esc(s.relation)+'<br>文本情绪画像置信度：'+esc(s.confidence==null?"未给出":s.confidence)+' · <a href="'+esc(s.source_url)+'" rel="noreferrer">来源链接</a></div></details>';
 document.getElementById("aiNote").innerHTML=s.scene_image?'本图为 <b>AI场景重建，不是肖像复原</b>，且不参与史料计算。':'本镜头没有通过完整PNG校验的模型画面；生成提示已保存到 <code>scene_prompt_manifest.json</code>，史料动画保持完整。';
 document.getElementById("stepLabel").textContent=(stepIndex+1)+" / "+story.scene_count;document.getElementById("progressFill").style.width=((stepIndex+1)/story.scene_count*100).toFixed(1)+"%";
 var progress=document.getElementById("storyProgress");progress.setAttribute("aria-valuenow",String(stepIndex+1));progress.setAttribute("aria-valuemax",String(story.scene_count));progress.setAttribute("aria-valuetext","第"+(stepIndex+1)+"个镜头，共"+story.scene_count+"个");
 document.getElementById("sceneStatus").textContent=s.poet+"《"+s.poem_title+"》，"+s.year_label+"年，"+s.year_precision_display+"，第"+(stepIndex+1)+"个镜头";
 document.getElementById("prevBtn").disabled=stepIndex===0;document.getElementById("nextBtn").textContent=stepIndex===story.scene_count-1?"下一卷 →":"下一步 →";
 if(resetClock){document.getElementById("readClock").textContent=auto?(s.read_seconds+"秒后前进"):"逐站停留";scheduleAuto();}
 renderRows();
}
function renderRows(){var story=currentStory(), box=document.getElementById("routeRows");box.innerHTML=story.scenes.map(function(s,i){return '<tr'+(i===stepIndex?' style="background:#f7f3e9"':'')+'><td>'+(i+1)+'</td><td>'+s.year_label+'<br><span style="color:#777">'+esc(s.year_precision_display)+(s.sequence==="overlap"?" · 区间重叠":"")+'</span></td><td>'+esc(s.place_historical)+'<br><span style="color:#777">'+(s.map_eligible?("今"+esc(s.place_modern)):"未落图")+'</span></td><td><span class="badge" style="color:'+(schoolByName[s.school]||{}).color+'">'+esc(s.school)+'</span></td><td>《'+esc(s.poem_title)+'》</td><td>'+esc(s.source_grade)+' · '+esc(s.source_status)+'</td><td>'+esc(s.source_name)+'</td></tr>';}).join("");}
function renderCollision(){var c=D.collisions[collisionIndex];if(!c){document.getElementById("collisionSection").style.display="none";return;}document.getElementById("collisionSelect").value=String(collisionIndex);document.getElementById("collisionTitle").textContent=c.title+" · 系统检出的年份切面";document.getElementById("collisionLede").textContent=c.lede+"。并置仅表示系年落在同一数值年份，不证明诗人互相影响。";var certainty=document.getElementById("collisionCertainty");certainty.textContent=c.certainty_display;certainty.className="certainty "+c.certainty;document.getElementById("collisionCards").innerHTML=c.scenes.map(function(s){var color=stories.filter(function(st){return st.poet===s.poet;})[0].color;return '<article class="collision-card" style="--pc:'+color+'"><h3>'+esc(s.poet)+' · '+esc(s.place_historical)+'</h3><div>'+s.year+'年 · '+esc(s.year_precision_display)+' · 《'+esc(s.poem_title)+'》 · '+esc(s.source_status)+' '+esc(s.source_grade)+'级</div><div class="quote">「'+esc(s.emotion_evidence||s.poem_lines[0]||"")+'」</div><p>'+esc(s.event)+'</p></article>';}).join("");}
function renderUnresolved(){document.getElementById("unresolvedRows").innerHTML=D.unresolved.map(function(row){return '<tr><td>'+esc(row.poet)+'</td><td>《'+esc(row.title)+'》</td><td>'+esc(row.year_precision_display)+'</td><td>'+esc(row.reason)+'</td><td><a href="'+esc(row.source_url)+'" rel="noreferrer">'+esc(row.source_name)+'</a><br><span style="color:#777">'+esc(row.source_note)+'</span></td></tr>';}).join("");}
function renderMethod(){var m=D.method;document.getElementById("methodBody").innerHTML='<ol><li>'+esc(m.route_rule)+'</li><li>'+esc(m.line_rule)+'</li><li>'+esc(m.poem_rule)+'</li><li>'+esc(m.source_rule)+'</li><li>'+esc(m.collision_rule)+'</li><li>'+esc(m.school_rule)+'</li><li>'+esc(m.image_rule)+'</li></ol><p>动画引擎：'+esc(D.meta.engine)+'。模型图像属于气氛层，史料结论只来自本地审核数据。</p>';}
function renderAll(resetClock){document.getElementById("storySelect").value=String(storyIndex);renderMap();renderScene(resetClock);}
function next(){var story=currentStory();if(stepIndex<story.scene_count-1){stepIndex++;}else{storyIndex=(storyIndex+1)%stories.length;stepIndex=0;}renderAll(true);}
function prev(){if(stepIndex>0){stepIndex--;renderAll(true);}}
function stopTimer(){if(timer){window.clearTimeout(timer);timer=0;}}
function scheduleAuto(){stopTimer();if(!auto){return;}timer=window.setTimeout(next,currentScene().read_seconds*1000);}
function syncMode(){var manual=document.getElementById("manualMode"),play=document.getElementById("autoMode");manual.classList.toggle("on",!auto);play.classList.toggle("on",auto);manual.setAttribute("aria-pressed",String(!auto));play.setAttribute("aria-pressed",String(auto));}
function stopAuto(){auto=false;stopTimer();syncMode();}
document.getElementById("nextBtn").addEventListener("click",next);document.getElementById("prevBtn").addEventListener("click",prev);document.getElementById("restartBtn").addEventListener("click",function(){stepIndex=0;renderAll(true);});
document.getElementById("manualMode").addEventListener("click",function(){stopAuto();document.getElementById("readClock").textContent="逐站停留";});document.getElementById("autoMode").addEventListener("click",function(){auto=true;syncMode();renderScene(true);});
initMeta();syncMapControls();renderCollision();renderUnresolved();renderMethod();renderAll(true);
})();
</script>
</body></html>'''


def main() -> None:
    data, prompts = build_data()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_PROMPTS.write_text(json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = HTML.replace("__DATA__", payload)
    assert "https://" not in "\n".join(re.findall(r"<script[^>]*src=[^>]+>", html, flags=re.I))
    assert "NaN" not in html and "Infinity" not in html
    assert len(html.encode("utf-8")) > 5000
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"[ok] saved {OUT_HTML} ({data['meta']['story_count']}卷 / {data['meta']['scene_count']}节点 / {data['meta']['collision_count']}组同年碰撞)")


if __name__ == "__main__":
    main()
