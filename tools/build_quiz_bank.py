# -*- coding: utf-8 -*-
"""「山河证道」题库生成器：从核验事实包产出诗词版 GeoGuessr 题目。

设计原则：题即论据——每道题的答案、提示、证据链全部来自人工核验数据或
确定性语料统计，不带任何随机与模型生成（导读为规则模板拼装并显式标注）。

题目来源：verified_all_poet_fact_packages.jsonl 中
  - chronology 带 lon/lat 坐标
  - 有 A/B 级证据支撑 composition_place
的记录，正文从 poems.json 按（诗人, 诗题）回配并校验 body_hash。

每题字段：
  lines          展示句（隐去题目作者；剔除含诗人名的句子）
  answer         {modern, historical, province, lon, lat, year, grade}
  difficulty     1=诗中含古地名（考古今对照） 2=意象充分 3=意象含蓄
  hints          三级提示：province(×0.7) / place_map(×0.5) / imagery(×0.3)
  imagery_hits   证据链意象（词、类别、情感倾向、所在句）
  place_names    诗中出现的古地名及其今地映射（学习卡对照表）
  evidence       A/B 级证据出处（考据栏）
  context_facts  人工核验背景事实（考据栏）
  reading_intro  规则模板自动导读（导读栏，非人工考据）
  same_place_more 同地再读：语料中写到同一地的其他诗句

产出：output/assets/competition/quiz_bank.json
零参数可复跑，输出确定（无随机）。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))
sys.path.insert(0, str(ROOT / "tools"))

from data.place_dict import PLACE_DICT  # noqa: E402
from data.image_dict import IMAGE_DICT  # noqa: E402
from classical_emotion_model import classify_text  # noqa: E402
from build_place_profile import (  # noqa: E402
    MIN_ALIAS_LEN,
    best_place_grade,
    build_alias_index,
    load_fact_packages,
    norm_place,
)

POEMS_PATH = ROOT / "data" / "poems.json"
OUT_JSON = ROOT / "output" / "assets" / "competition" / "quiz_bank.json"

TARGET_QUESTIONS = 24
MIN_QUESTIONS = 20
MAX_PER_POET = 4  # 带坐标核验作地集中于六核心诗人，第一卷即「六家行迹卷」
TUTORIAL_N = 3
REGION_RADIUS_KM = 500.0
FAMOUS_POETS = {"李白", "杜甫", "白居易", "苏轼", "陆游", "李清照"}

# 章节划分：依卷内 24 题的实际作地分布划定（关即区域），省份全覆盖、无重叠。
# 通关一章解锁下一章与对应考据馆深链；集齐四章诗印为卷一通关。
CHAPTERS = (
    {
        "id": "ch1",
        "name": "两京·朔方",
        "theme": "都城气象与北地风霜——汴京、洛阳、青齐与燕山",
        "seal": "京",
        "color": "#426f94",
        "provinces": ("山东", "北京", "河南", "陕西", "山西", "河北", "天津",
                      "甘肃", "宁夏", "青海", "新疆", "内蒙古", "辽宁", "吉林", "黑龙江"),
        "archives": (
            {"title": "诗人行旅与生命情感", "url": "15_诗人行旅与生命情感.html",
             "note": "六家行旅全程地图与情感联动"},
            {"title": "凝望罗盘", "url": "31_凝望罗盘.html", "note": "方位词的文本地理"},
        ),
    },
    {
        "id": "ch2",
        "name": "巴蜀",
        "theme": "蜀道、锦城与夔门——险峻地理如何改写诗风",
        "seal": "蜀",
        "color": "#7a5c3d",
        "provinces": ("四川", "重庆"),
        "archives": (
            {"title": "身与心双层地图", "url": "32_身与心双层地图.html",
             "note": "实际行旅 vs 诗中遥想（「身在别处写此地」）"},
            {"title": "平行时空 759", "url": "33_平行时空759.html",
             "note": "白帝城遇赦那年，杜甫在做什么"},
        ),
    },
    {
        "id": "ch3",
        "name": "江南",
        "theme": "烟雨水乡的另一极——湖、扁舟与梅",
        "seal": "南",
        "color": "#26786e",
        "provinces": ("江苏", "浙江", "上海", "安徽"),
        "archives": (
            {"title": "意象地理", "url": "41_意象地理.html", "note": "意象×地域 lift 矩阵：江南为何是湖与梅"},
            {"title": "同一意象的诗人情感差异", "url": "17_同一意象的诗人情感差异.html",
             "note": "月/酒/舟/雁/雨在诗人间的异情"},
        ),
    },
    {
        "id": "ch4",
        "name": "荆楚·江右",
        "theme": "贬谪者的江湖——黄州、江州与岳阳",
        "seal": "楚",
        "color": "#b64b3f",
        "provinces": ("湖北", "湖南", "江西", "贵州", "云南", "广西", "广东", "海南", "福建"),
        "archives": (
            {"title": "诗人精神地形图", "url": "20_诗人精神地形图.html", "note": "李白五分期意象漂移"},
            {"title": "创作活动中心迁移", "url": "16_唐宋诗歌创作活动中心迁移.html",
             "note": "乱世之后创作中心南移"},
            {"title": "诗人自述生命卷", "url": "39_诗人自述生命卷.html", "note": "卷一终赏：88 人第一人称生命叙事"},
        ),
    },
)

SENT_SPLIT = re.compile(r"(?<=[。！？；])|\n")
HAN_LINE = re.compile(r"^[\u3400-\u9fff，。、！？；：·「」（）]+$")


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def split_sentences(body: str) -> list[str]:
    out = []
    for raw in SENT_SPLIT.split(body):
        seg = raw.strip()
        if not seg:
            continue
        if not HAN_LINE.match(seg):
            seg = re.sub(r"[^\u3400-\u9fff，。、！？；：·「」（）]", "", seg)
        if seg:
            out.append(seg)
    return out


def find_aliases(body: str, alias_index: dict[str, dict]) -> list[dict]:
    """诗中出现的古地名（>=2 字），按词长降序去子串冗余。"""
    hits = []
    for alias in sorted(alias_index, key=len, reverse=True):
        if alias in body:
            info = alias_index[alias]
            hits.append(
                {
                    "alias": alias,
                    "modern": info["modern"],
                    "province": norm_place(info["province"]),
                    "lon": info["lon"],
                    "lat": info["lat"],
                }
            )
    # 去掉被更长别名覆盖的短别名（如「金陵」命中时不再计「陵」类，本词典>=2字已较安全）
    kept, dropped = [], set()
    for i, h in enumerate(hits):
        for j, other in enumerate(hits):
            if i != j and h["alias"] in other["alias"] and h["alias"] != other["alias"]:
                dropped.add(i)
                break
    for i, h in enumerate(hits):
        if i not in dropped:
            kept.append(h)
    return kept


def find_imagery(body: str, sentences: list[str]) -> list[dict]:
    """意象证据链：词长优先（越长越具体），带所在句。"""
    image_map = {w: (cat, emo) for w, cat, emo in IMAGE_DICT}
    words = sorted((w for w in image_map if w in body), key=len, reverse=True)
    out = []
    for w in words[:8]:
        cat, emo = image_map[w]
        line = next((s for s in sentences if w in s), "")
        out.append(
            {
                "word": w,
                "cat": cat,
                "emotion": emo,
                "line": line[:26] + ("…" if len(line) > 26 else ""),
            }
        )
    return out


def pick_display_lines(
    sentences: list[str], poet: str, place_hits: list[dict], imagery: list[dict]
) -> list[str]:
    """选最多 3 句展示句：优先含地名/意象的教学句，剔除泄露诗人名的句子。"""
    scored = []
    alias_set = {h["alias"] for h in place_hits}
    imagery_set = {i["word"] for i in imagery}
    for idx, seg in enumerate(sentences):
        if poet and poet in seg:
            continue
        if not (3 <= len(seg) <= 44):
            continue
        score = 0
        if alias_set & set(seg[i : i + 3] for i in range(len(seg))):
            score += 3
        for a in alias_set:
            if a in seg:
                score += 2
        score += sum(1 for w in imagery_set if w in seg)
        scored.append((score, -idx, seg))
    scored.sort(key=lambda r: (-r[0], r[1]))
    picked = [s for _s, _i, s in scored[:3]]
    if len(picked) < 2:  # 兜底：放宽长度
        for idx, seg in enumerate(sentences):
            if poet and poet in seg:
                continue
            if 2 <= len(seg) <= 60 and seg not in picked:
                picked.append(seg)
            if len(picked) >= 2:
                break
    return picked[:3]


def build() -> dict:
    poems = json.loads(POEMS_PATH.read_text(encoding="utf-8"))
    poem_index: dict[tuple[str, str], dict] = {}
    for p in poems:
        poem_index[(p.get("poet") or p.get("author"), p.get("title"))] = p

    facts = load_fact_packages()
    alias_index = build_alias_index()

    # 核验作地样本（意象提示的统计底座）
    located: list[dict] = []
    for rec in facts:
        chron = rec.get("chronology") or {}
        lon, lat = chron.get("lon"), chron.get("lat")
        if lon is None or lat is None or best_place_grade(rec) not in {"A", "B"}:
            continue
        pm = poem_index.get((rec["poem_key"]["poet"], rec["poem_key"]["title"]))
        if not pm:
            continue
        located.append(
            {
                "lon": float(lon),
                "lat": float(lat),
                "modern": norm_place(chron.get("modern_place") or ""),
                "body": pm.get("body") or "",
            }
        )

    provinces_pool = sorted({norm_place((r.get("chronology") or {}).get("province") or "")
                             for r in facts
                             if (r.get("chronology") or {}).get("province")})

    candidates = []
    for rec in facts:
        chron = rec.get("chronology") or {}
        lon, lat = chron.get("lon"), chron.get("lat")
        grade = best_place_grade(rec)
        if lon is None or lat is None or grade not in {"A", "B"}:
            continue
        pm = poem_index.get((rec["poem_key"]["poet"], rec["poem_key"]["title"]))
        if not pm:
            continue
        body = pm.get("body") or ""
        if not isinstance(body, str) or not (8 <= len(body) <= 600):
            continue
        poet = rec["poem_key"]["poet"]
        title = rec["poem_key"]["title"]
        dynasty = rec["poem_key"]["dynasty"]
        hash_ok = hashlib.sha256(body.encode()).hexdigest() == rec["poem_key"].get("body_hash")

        sentences = split_sentences(body)
        place_hits = find_aliases(body, alias_index)
        imagery = find_imagery(body, sentences)
        lines = pick_display_lines(sentences, poet, place_hits, imagery)
        if not lines:
            continue

        answer_key = norm_place(chron.get("modern_place") or "")
        answer_aliases = [
            a for a, e in alias_index.items() if e["key"] == answer_key
        ] + ([chron.get("historical_place")] if chron.get("historical_place") else [])
        year = chron.get("year_start")
        emotion = classify_text(body, title)

        if place_hits:
            difficulty = 1
        elif len(imagery) >= 2:
            difficulty = 2
        else:
            difficulty = 3

        quality = (
            (2 if hash_ok else 0)
            + (2 if grade == "A" else 1)
            + (1 if place_hits else 0)
            + (1 if len(imagery) >= 3 else 0)
            + (1 if 16 <= len(body) <= 300 else 0)
        )

        # ---- 一级提示：省份圈定（干扰省从作地省份池确定性轮转取异省）----
        prov_correct = norm_place(chron.get("province") or "")
        decoy = ""
        if len(provinces_pool) > 1:
            idx = provinces_pool.index(prov_correct) if prov_correct in provinces_pool else 0
            rot = int(hashlib.md5(title.encode("utf-8")).hexdigest(), 16) % (len(provinces_pool) - 1)
            decoy = provinces_pool[(idx + 1 + rot) % len(provinces_pool)]
            if decoy == prov_correct:
                decoy = provinces_pool[(idx + 1) % len(provinces_pool)]

        # ---- 二级提示：古今地名对照 / 生平定位 ----
        if place_hits:
            parts = []
            for h in place_hits[:2]:
                seg = f"诗中「{h['alias']}」＝今{h['modern']}（{h['province']}）"
                if norm_place(h["modern"]) == answer_key:
                    seg += "——正是本作之地，落子即得"
                parts.append(seg)
            if not any(norm_place(h["modern"]) == answer_key for h in place_hits):
                parts.append("注意：诗中之地未必是写作之地，谨防「身在别处写此地」。")
            hint_place = {"kind": "place_map", "text": "；".join(parts)}
        else:
            ctx = ""
            for fact in rec.get("context_facts", []):
                ctx = re.sub(r"^来源记述[：:]", "", fact.get("text") or "").strip()
                if ctx:
                    break
            if not ctx:
                ctx = f"{poet}此期行迹见年谱考订"
            ctx = ctx[:70] + ("…" if len(ctx) > 70 else "")
            hint_place = {
                "kind": "biography",
                "text": f"诗人{poet}约于{year if year else '该'}年前后：{ctx}",
            }

        # ---- 三级提示：意象地域证据（基于核验作地样本的确定性统计）----
        hint_img = None
        for img in imagery:
            if len(img["word"]) < 2:
                continue
            w = img["word"]
            sample = [r for r in located if w in r["body"]]
            if len(sample) >= 3:
                near = [
                    r for r in sample
                    if haversine_km(float(lon), float(lat), r["lon"], r["lat"]) <= REGION_RADIUS_KM
                ]
                hint_img = {
                    "kind": "imagery_stat",
                    "word": w,
                    "n": len(sample),
                    "m": len(near),
                    "text": (
                        f"核验作地样本中，含「{w}」的诗作 {len(sample)} 首，"
                        f"其中 {len(near)} 首作于答案地 {int(REGION_RADIUS_KM)} 公里内"
                    ),
                }
                break
        if hint_img is None:
            hint_img = {
                "kind": "imagery_fallback",
                "text": f"此诗意象地域指向含蓄——换一个角度：{dynasty}代诗人{poet}的行迹与身份即是线索。",
            }

        # ---- 考据证据 ----
        evidence = [
            {
                "grade": ev.get("source_grade", "C"),
                "source": ev.get("source_name") or "",
                "excerpt": (ev.get("excerpt") or "")[:80],
                "url": ev.get("source_url") or "",
            }
            for ev in rec.get("evidence", [])
            if "composition_place" in ev.get("supports", [])
        ]
        context_facts = [
            re.sub(r"^来源记述[：:]", "", f.get("text") or "").strip()
            for f in rec.get("context_facts", [])
        ][:2]

        # ---- 导读（规则模板，非人工考据；讲解员口吻）----
        img_words = [i["word"] for i in imagery[:2]]
        emotion_label = emotion.get("primary_label") or "情绪未定"
        valence = emotion.get("valence", 0.0)
        place_name = chron.get("modern_place") or chron.get("historical_place") or answer_key
        year_txt = f"{year}年前后" if year else "系年待考的时候"
        mood = "偏暖" if valence >= 0.25 else ("偏冷" if valence <= -0.25 else "冷暖掺半")
        intro = (
            f"这首《{title}》读下来，{poet}此刻人应在{place_name}——{year_txt}的事。"
            + (f"通篇最扎眼的意象是「{'」和「'.join(img_words)}」，" if img_words else "通篇意象疏淡，")
            + f"逐句词典分析出的情绪是「{emotion_label}」，整体{mood}（愉悦度 {valence:+.1f}）。"
            + "年份与作地是人工核验过的，这段导语本身由规则模板拼成，仅作导读参考。"
        )

        # ---- 同地再读 ----
        same_place = []
        seen_keys = {(poet, title)}
        for pm2 in poems:
            body2 = pm2.get("body") or ""
            if not isinstance(body2, str) or len(body2) < 8:
                continue
            p2 = (pm2.get("poet") or pm2.get("author"), pm2.get("title"))
            if p2 in seen_keys:
                continue
            hit_alias = None
            for a in answer_aliases:
                if a and a in body2:
                    hit_alias = a
                    break
            if not hit_alias:
                continue
            line = next(
                (s for s in split_sentences(body2) if hit_alias in s and 4 <= len(s) <= 30),
                "",
            )
            if not line:
                continue
            same_place.append(
                {
                    "poet": p2[0],
                    "title": p2[1],
                    "alias": hit_alias,
                    "line": line[:30],
                    "famous": p2[0] in FAMOUS_POETS,
                }
            )
            seen_keys.add(p2)
            if len(same_place) >= 30:
                break
        same_place.sort(key=lambda r: (not r["famous"], r["poet"], r["title"]))
        same_place = same_place[:3]

        candidates.append(
            {
                "poet": poet,
                "title": title,
                "dynasty": dynasty,
                "hash_ok": hash_ok,
                "quality": quality,
                "question": {
                    "lines": lines,
                    "full_body": body,
                    "poet": poet,
                    "title": title,
                    "dynasty": dynasty,
                    "answer": {
                        "modern": chron.get("modern_place") or answer_key,
                        "historical": chron.get("historical_place") or "",
                        "province": prov_correct,
                        "lon": round(float(lon), 4),
                        "lat": round(float(lat), 4),
                        "year": year,
                        "grade": grade,
                    },
                    "difficulty": difficulty,
                    "place_names": place_hits[:4],
                    "imagery_hits": imagery,
                    "emotion": {
                        "primary": emotion_label,
                        "valence": valence,
                        "confidence": emotion.get("confidence_label", ""),
                    },
                    "hints": {
                        "province": {
                            "kind": "province",
                            "correct": prov_correct,
                            "decoy": decoy,
                            "text": f"此诗作于今{prov_correct}或{decoy}境内",
                        },
                        "place": hint_place,
                        "imagery": hint_img,
                    },
                    "evidence": evidence,
                    "context_facts": context_facts,
                    "reading_intro": {
                        "generated_by": "rules_template",
                        "label": "自动导读（规则模板拼装，非人工考据）",
                        "text": intro,
                    },
                    "same_place_more": same_place,
                },
            }
        )

    # ---- 选择：质量降序，每人最多 2 题，保证难度覆盖 ----
    candidates.sort(key=lambda c: (-c["quality"], c["poet"], c["title"]))
    selected, per_poet, diff_count = [], {}, {1: 0, 2: 0, 3: 0}
    for c in candidates:
        if len(selected) >= TARGET_QUESTIONS:
            break
        if per_poet.get(c["poet"], 0) >= MAX_PER_POET:
            continue
        selected.append(c)
        per_poet[c["poet"]] = per_poet.get(c["poet"], 0) + 1
        diff_count[c["question"]["difficulty"]] += 1
    # 难度 1 不足时从候选补足教学题
    if diff_count[1] < TUTORIAL_N:
        for c in candidates:
            if diff_count[1] >= TUTORIAL_N:
                break
            if c in selected or c["question"]["difficulty"] != 1:
                continue
            if per_poet.get(c["poet"], 0) >= MAX_PER_POET:
                continue
            selected.append(c)
            per_poet[c["poet"]] = per_poet.get(c["poet"], 0) + 1
            diff_count[1] += 1

    assert len(selected) >= MIN_QUESTIONS, (
        f"可用题目仅 {len(selected)} < {MIN_QUESTIONS}，请扩充事实包坐标覆盖"
    )

    # ---- 出卷顺序：教学题（难度1）在前，其后难度升序 ----
    selected.sort(
        key=lambda c: (
            c["question"]["difficulty"],
            -c["quality"],
            c["poet"],
            c["title"],
        )
    )
    questions = []
    for i, c in enumerate(selected, start=1):
        q = c["question"]
        q["id"] = f"Q{i:02d}"
        questions.append(q)

    # ---- 章节划分（关即区域）：按答案省份归章，章内难度升序 ----
    by_id = {q["id"]: q for q in questions}
    chapters_out = []
    assigned: set[str] = set()
    for ch in CHAPTERS:
        members = [
            q for q in questions
            if norm_place(q["answer"]["province"]) in ch["provinces"]
        ]
        ids = [q["id"] for q in members]
        assigned.update(ids)
        chapters_out.append(
            {
                "id": ch["id"],
                "name": ch["name"],
                "theme": ch["theme"],
                "seal": ch["seal"],
                "color": ch["color"],
                "question_ids": ids,
                "archives": [dict(a) for a in ch["archives"]],
            }
        )
    unassigned = [qid for qid in by_id if qid not in assigned]
    assert not unassigned, f"章节省份映射未覆盖：{unassigned}"
    assert all(len(c["question_ids"]) >= 3 for c in chapters_out), "存在题目不足 3 道的章节"

    meta = {
        "n_candidates": len(candidates),
        "n_selected": len(questions),
        "n_located_sample": len(located),
        "difficulty_dist": {str(k): v for k, v in diff_count.items() if v},
        "poets": sorted(per_poet.items()),
        "score_formula": "round(5000 * exp(-dist_km/300) * hint_multiplier)",
        "hint_policy": {
            "province": 0.7,
            "place": 0.5,
            "imagery": 0.3,
            "tutorial_free_first": TUTORIAL_N,
        },
        "policy": (
            "题目作地仅取人工核验 A/B 级证据记录；意象统计为核验样本确定性计数；"
            "导读为规则模板自动拼装并显式标注，非人工考据；展示句已剔除含诗人名的句子。"
        ),
        "generated_by": "tools/build_quiz_bank.py",
        "chapters_note": "卷一四章依 24 题实际作地分布划定（关即区域）；通关一章解锁下一章与考据馆。",
    }
    return {"meta": meta, "questions": questions, "chapters": chapters_out}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    data = build()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    print("OK  ->", OUT_JSON, f"({OUT_JSON.stat().st_size} bytes)")
    print(
        f"候选 {data['meta']['n_candidates']} | 入卷 {data['meta']['n_selected']} | "
        f"难度分布 {data['meta']['difficulty_dist']} | 核验作地样本 {data['meta']['n_located_sample']}"
    )
    poets = "、".join(f"{p}({n})" for p, n in data["meta"]["poets"])
    print("诗人分布:", poets)
    for ch in data["chapters"]:
        print(f"  章 {ch['name']}（印「{ch['seal']}」）{len(ch['question_ids'])} 题 · 考据馆 {len(ch['archives'])} 链")
    for q in data["questions"][:6]:
        first = q["lines"][0][:18]
        print(
            f"  {q['id']} 难{q['difficulty']} {q['dynasty']}·{q['poet']}《{q['title']}》"
            f"→ {q['answer']['modern']}({q['answer']['province']}) 「{first}」"
        )


if __name__ == "__main__":
    main()
