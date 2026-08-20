# -*- coding: utf-8 -*-
"""地域画像数据层（R1）：以「地方」为主角聚合诗歌证据。

视角反转：现有展项回答「诗人走了哪里」，本数据层回答「每个地方被写成了什么」。

产出：output/assets/competition/place_profile.json

口径（诚实分层，禁止冒充）：
  - composed  在地创作：仅来自人工核验事实包（A/B 级证据支撑 composition_place），
              每条带证据等级与出处；这是可考据的分子。
  - mentions  被写入：全量语料正文扫描（古地名别名词典命中），诗人在场与遥想
              无法在此层区分，统一计为「被写入」，样本量即语料量。
  - locality_rate 在地率：composed / (composed + mentions)，实验性指标，
              两侧样本口径不同（核验 vs 扫描），页面展示必须同时给出两侧 n。

意象/情感/季节：提及该地的诗作整体统计（image_dict 意象命中、
classical_emotion_model 情感画像、春夏秋冬字符粗计），均为规则方法，
不是外部权威标注，页面须照此声明。

零参数可复跑；扫描为确定性输出，不含随机。
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

from data.place_dict import PLACE_DICT  # noqa: E402
from data.image_dict import IMAGE_DICT  # noqa: E402
from classical_emotion_model import classify_text  # noqa: E402

POEMS_PATH = ROOT / "data" / "poems.json"
FACT_PATHS = (
    ROOT / "data" / "reviewed" / "verified_all_poet_fact_packages.jsonl",
    ROOT / "data" / "reviewed" / "verified_poem_fact_packages.jsonl",
)
OUT_JSON = ROOT / "output" / "assets" / "competition" / "place_profile.json"

MIN_ALIAS_LEN = 2          # 单字地名误报率高，扫描只用 >=2 字别名
GRADE_ORDER = {"A": 0, "B": 1, "C": 2}
SUFFIX_RE = re.compile(r"(省|市|县|区|特别行政区)$")
PUNCT_RE = re.compile(r"[。！？；;\n]")
HAN_RE = re.compile(r"[^\u3400-\u9fff]")


def norm_place(name: str) -> str:
    """「九江市/江西省」→「九江/江西」，统一古今两侧命名颗粒。"""
    return SUFFIX_RE.sub("", (name or "").strip())


def load_fact_packages() -> list[dict]:
    """读两个事实包并按 (诗人, 诗题) 去重，保留核验状态为 verified 的记录。"""
    seen: dict[tuple[str, str], dict] = {}
    for path in FACT_PATHS:
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("verification", {}).get("status") != "verified":
                    continue
                key = (rec["poem_key"]["poet"], rec["poem_key"]["title"])
                seen.setdefault(key, rec)
    return list(seen.values())


def best_place_grade(rec: dict) -> str | None:
    """支撑 composition_place 的最高（字母最小）证据等级。"""
    grades = [
        ev.get("source_grade", "C")
        for ev in rec.get("evidence", [])
        if "composition_place" in ev.get("supports", [])
    ]
    return min(grades, key=lambda g: GRADE_ORDER.get(g, 9)) if grades else None


def build_alias_index() -> dict[str, dict]:
    """别名 -> {modern, province, lon, lat, historical[]}；同一今地聚合成条目。"""
    index: dict[str, dict] = {}
    for alias, modern, province, lon, lat, _note in PLACE_DICT:
        if len(alias) < MIN_ALIAS_LEN:
            continue
        key = norm_place(modern)
        entry = index.setdefault(
            alias,
            {
                "key": key,
                "modern": modern,
                "province": province,
                "lon": lon,
                "lat": lat,
            },
        )
        index[alias] = entry
    return index


def scan_mentions(alias_index: dict[str, dict], poems: list[dict]) -> dict[str, dict]:
    """全量语料扫描：每个今地被哪些诗写入，并聚合意象/情感/朝代/季节。

    只统计正文中出现 >=2 字古地名别名的诗；同一诗对同一今地只计一次。
    """
    place_stats: dict[str, dict] = {}

    def slot(key: str) -> dict:
        return place_stats.setdefault(
            key,
            {
                "poems": [],            # (poet, title, dynasty, body)
                "imagery": Counter(),
                "imagery_emotion": defaultdict(list),
                "valences": [],
                "emotions": Counter(),
                "seasons": Counter(),
                "dynasties": Counter(),
            },
        )

    image_words = sorted({w for w, _c, _e in IMAGE_DICT if len(w) >= 1}, key=len, reverse=True)
    image_map = {w: (cat, emo) for w, cat, emo in IMAGE_DICT}

    for poem in poems:
        body = poem.get("body") or ""
        if not isinstance(body, str) or len(body) < 8:
            continue
        poet = poem.get("poet") or poem.get("author") or "佚名"
        title = poem.get("title") or ""
        dynasty = poem.get("dynasty") or ""

        hits: set[str] = set()
        for alias in alias_index:
            if alias in body:
                hits.add(alias_index[alias]["key"])
        if not hits:
            continue

        # 该诗意象/情感只算一次，分摊给它写到的每个地方
        imagery_hits = []
        for word in image_words:
            if word in body:
                cat, emo = image_map[word]
                imagery_hits.append((word, cat, emo))
        emotion = classify_text(body, title)
        valence = emotion.get("valence", 0.0)
        primary = emotion.get("primary_label") or "未定"
        han_only = HAN_RE.sub("", body + title * 3)  # 标题按 season_rules 口径加权
        season_counts = {s: han_only.count(s) for s in "春夏秋冬"}

        for key in hits:
            slot_data = slot(key)
            slot_data["poems"].append((poet, title, dynasty, body))
            for word, cat, emo in imagery_hits[:10]:  # 每诗最多贡献前10个意象，防长诗淹没
                slot_data["imagery"][word] += 1
                slot_data["imagery_emotion"][word].append(emo)
            if imagery_hits:
                slot_data["valences"].append(valence)
            slot_data["emotions"][primary] += 1
            for s, n in season_counts.items():
                if n:
                    slot_data["seasons"][s] += n

    return place_stats


def build() -> dict:
    poems = json.loads(POEMS_PATH.read_text(encoding="utf-8"))
    facts = load_fact_packages()
    alias_index = build_alias_index()

    # ---- composed：核验在地创作（A/B 级支撑 composition_place 且带坐标） ----
    composed: dict[str, list[dict]] = defaultdict(list)
    composed_coords: dict[str, tuple[float, float]] = {}
    composed_province: dict[str, str] = {}
    composed_historical: dict[str, set[str]] = defaultdict(set)
    n_facts_with_coords = 0
    for rec in facts:
        chron = rec.get("chronology") or {}
        lon, lat = chron.get("lon"), chron.get("lat")
        if lon is None or lat is None:
            continue
        grade = best_place_grade(rec)
        if grade not in {"A", "B"}:
            continue  # 在地创作只收 A/B；C 级不入分子
        n_facts_with_coords += 1
        key = norm_place(chron.get("modern_place") or "")
        if not key:
            continue
        year = chron.get("year_start")
        composed[key].append(
            {
                "poet": rec["poem_key"]["poet"],
                "title": rec["poem_key"]["title"],
                "dynasty": rec["poem_key"]["dynasty"],
                "year": year,
                "historical_place": chron.get("historical_place") or "",
                "grade": grade,
            }
        )
        composed_coords.setdefault(key, (float(lon), float(lat)))
        composed_province.setdefault(key, chron.get("province") or "")
        if chron.get("historical_place"):
            composed_historical[key].add(chron["historical_place"])

    # ---- mentions：全量语料扫描 ----
    place_stats = scan_mentions(alias_index, poems)

    # ---- 汇总成地方档案 ----
    dict_places = {}
    for alias_entry in alias_index.values():
        dict_places.setdefault(
            alias_entry["key"],
            {
                "modern": alias_entry["modern"],
                "province": alias_entry["province"],
                "lon": alias_entry["lon"],
                "lat": alias_entry["lat"],
            },
        )

    places_out = []
    keys = set(composed) | set(place_stats) | set(dict_places)
    for key in keys:
        base = dict_places.get(key) or {}
        comp = composed.get(key, [])
        stats = place_stats.get(key)
        mentions = []
        if stats:
            mentions = stats["poems"]
        if not comp and not mentions:
            continue  # 既无核验创作也无语料写入，不成档
        lon, lat = composed_coords.get(key, (base.get("lon"), base.get("lat")))
        if lon is None or lat is None:
            continue  # 无坐标无法落图

        province = norm_place(composed_province.get(key) or base.get("province") or "")
        top_imagery = []
        if stats:
            for word, cnt in stats["imagery"].most_common(8):
                cat, _emo = None, None
                for w, c, e in IMAGE_DICT:
                    if w == word:
                        cat, _emo = c, e
                        break
                emos = stats["imagery_emotion"].get(word) or [0.0]
                top_imagery.append(
                    {
                        "word": word,
                        "cat": cat,
                        "count": cnt,
                        "avg_emotion": round(sum(emos) / len(emos), 3),
                    }
                )
        avg_valence = None
        primary_emotion = None
        season_top = None
        dynasty_dist = {}
        sample_titles = []
        mention_poets = []
        if stats:
            if stats["valences"]:
                avg_valence = round(sum(stats["valences"]) / len(stats["valences"]), 3)
            primary_emotion = stats["emotions"].most_common(1)[0][0] if stats["emotions"] else None
            season_top = stats["seasons"].most_common(1)[0][0] if stats["seasons"] else None
            dynasty_dist = dict(stats["dynasties"].most_common())
            sample_titles = [
                {"poet": p, "title": t, "dynasty": d}
                for p, t, d, _b in sorted(stats["poems"], key=lambda r: (r[0], r[1]))[:10]
            ]
            mention_poets = sorted({p for p, _t, _d, _b in stats["poems"]})

        n_comp, n_ment = len(comp), len(mentions)
        locality_rate = round(n_comp / (n_comp + n_ment), 4) if (n_comp + n_ment) else None

        historical = sorted(
            composed_historical.get(key, set())
            | {a for a, e in alias_index.items() if e["key"] == key}
        )
        places_out.append(
            {
                "key": key,
                "modern": base.get("modern") or (comp[0]["historical_place"] if comp else key),
                "province": province,
                "historical_aliases": historical[:12],
                "lon": round(float(lon), 4),
                "lat": round(float(lat), 4),
                "composed_n": n_comp,
                "composed": sorted(comp, key=lambda r: (r["year"] is None, r["year"] or 0))[:12],
                "mentions_n": n_ment,
                "mention_poets_n": len(mention_poets),
                "mention_poets_sample": mention_poets[:20],
                "mention_sample_titles": sample_titles,
                "locality_rate": locality_rate,
                "imagery_top": top_imagery,
                "emotion": {
                    "avg_valence": avg_valence,
                    "primary": primary_emotion,
                    "basis": "classical_emotion_model 规则方法，统计提及该地的诗作",
                },
                "season_top": season_top,
                "dynasty_dist": dynasty_dist,
            }
        )

    places_out.sort(key=lambda r: (-(r["composed_n"] + r["mentions_n"]), r["key"]))

    meta = {
        "n_poems_corpus": len(poems),
        "n_fact_verified": len(facts),
        "n_fact_with_coords_ab": n_facts_with_coords,
        "n_places": len(places_out),
        "policy": (
            "composed=人工核验事实包（A/B 级证据支撑作地，带出处）；"
            "mentions=全量语料正文古地名扫描（含亲历与遥想，不作区分）；"
            "locality_rate=composed/(composed+mentions)，实验性指标，两侧样本口径不同，"
            "展示时必须同时给出两侧 n；意象/情感/季节为规则方法（课程词典），非权威标注。"
        ),
        "generated_by": "tools/build_place_profile.py",
    }
    return {"meta": meta, "places": places_out}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    data = build()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    top = data["places"][:12]
    print("OK  ->", OUT_JSON, f"({OUT_JSON.stat().st_size} bytes)")
    print(
        f"地方 {data['meta']['n_places']} 处 | "
        f"核验在地创作 {data['meta']['n_fact_with_coords_ab']} 首 | "
        f"语料 {data['meta']['n_poems_corpus']} 首"
    )
    for p in top:
        img = "、".join(i["word"] for i in p["imagery_top"][:4]) or "-"
        print(
            f"  {p['modern']:<4} {p['province']:<3} 在地创作{p['composed_n']:>2} "
            f"被写入{p['mentions_n']:>4}  在地率{p['locality_rate'] if p['locality_rate'] is not None else '-':<6} "
            f"意象:{img}"
        )


if __name__ == "__main__":
    main()
