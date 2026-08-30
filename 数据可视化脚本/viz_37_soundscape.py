# -*- coding: utf-8 -*-
"""viz_37 可听的诗（音景）——参赛版页面生成脚本。

零参数复跑：
    python 数据可视化脚本/viz_37_soundscape.py

输入（只读）：
    data/stylometry/sound_stats.json   声音维度统计（当前全语料）
    data/stylometry/sound_dict.py      88 词条声音词典（六类 + 情感人工标注）
    data/poems.json                    语料正文（明星案例原文高亮用）

输出：
    output/37_可听的诗.html
    output/assets/competition/sound_page_data.json

页面内容：
    1. 六人声景指纹卡（玫瑰图 + 标志性声音芯片 + 无声诗占比 + 命中明细）
    2. 明星案例：《琵琶行》全文声词染色 / 王维五首精选的以声衬静 /
       杜甫哭声战鼓 vs 高适羌笛钟鼓（盛唐两种边声）
    3. 可听化：Web Audio 合成音色（默认静音，优雅降级）
    4. 方法与数据折叠区（口径 / 排除表 / 散文抬高计数说明 / 局限）

高亮算法与 data/stylometry/scan_sound.py 完全一致（先挖除 EXCLUDE_PATTERNS，
再按词长降序最长优先、不重叠匹配），并对每首明星案例断言：本脚本重算命中
与 sound_stats.json 的 per_poem 记录逐词一致，保证"页面上亮的 = 统计里算的"。
"""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STYLO = ROOT / "data" / "stylometry"
sys.path.insert(0, str(STYLO))
import sound_dict  # noqa: E402

STATS_JSON = STYLO / "sound_stats.json"
POEMS_JSON = ROOT / "data" / "poems.json"
FULL_MANIFEST_JSON = ROOT / "data" / "analysis" / "famous_poets_full_manifest.json"
OUT_HTML = ROOT / "output" / "37_可听的诗.html"
OUT_DATA = ROOT / "output" / "assets" / "competition" / "sound_page_data.json"

SIX_POETS = ["李白", "杜甫", "白居易", "苏轼", "陆游", "李清照"]
POET_COLORS = {
    "李白": "#426f94", "杜甫": "#7a5c3d", "白居易": "#26786e",
    "苏轼": "#b64b3f", "陆游": "#8a3b2f", "李清照": "#9c5d8f",
    "王维": "#4a7a52", "高适": "#a87527",
}
CATS = [
    {"id": "beast",  "name": "兽鸣",  "color": "#7a5c3d", "desc": "猿·蝉·马嘶·犬吠"},
    {"id": "bird",   "name": "鸟啼",  "color": "#a87527", "desc": "莺·杜鹃·乌啼·雁声"},
    {"id": "strings","name": "器乐",  "color": "#b64b3f", "desc": "琴·笛·琵琶·鼓角"},
    {"id": "bell",   "name": "钟磬",  "color": "#9c5d8f", "desc": "钟·磬·铃·更漏"},
    {"id": "nature", "name": "自然声","color": "#426f94", "desc": "风雨·流水·萧萧·滴"},
    {"id": "human",  "name": "人声",  "color": "#26786e", "desc": "歌·哭·砧·人语"},
]
CAT_NAMES = [c["name"] for c in CATS]

# 全语料最响篇目的体裁人工标注（诚实展示：散文/骈文命中不与诗歌同台竞争）
GENRE_NOTE = {
    "送孟东野序": "散文", "琵琶行": "歌行", "秦妇吟": "歌行",
    "秋怀十五首": "组诗", "畴昔篇": "歌行", "戚氏·晚秋天": "词",
    "滕王阁序": "骈文", "东坡先生墓志铭": "散文",
    "汴都赋": "赋", "莺莺传": "传奇", "与元九书": "书信",
    "乾元殿颂": "颂", "醉吟先生传": "传记", "古风五十九首": "组诗",
}

STAR_POEMS = {
    "pipa":    [("白居易", "琵琶行")],
    "wangwei": [("王维", "鹿柴"), ("王维", "竹里馆"), ("王维", "山居秋暝"),
                ("王维", "鸟鸣涧"), ("王维", "观猎")],
    "dufu":    [("杜甫", "兵车行"), ("杜甫", "石壕吏"), ("杜甫", "月夜忆舍弟")],
    "gaoshi":  [("高适", "塞上听吹笛"), ("高适", "和王七玉门关听吹笛"),
                ("高适", "燕歌行·并序")],
}

POEM_NOTES = {
    ("王维", "观猎"): "「角弓鸣」实为弓弦之声，被泛用动词「鸣」捕捉——词典归类近似之一，如实展示。",
    ("高适", "燕歌行·并序"): "序文中《燕歌行》篇名的「歌」亦被计入——含序文口径，与统计保持一致。",
    ("白居易", "琵琶行"): "含诗前序文：序中「琵琶」等命中一并计入，与 sound_stats 口径一致。",
}


def scan_positions(body: str, words_desc):
    """与 scan_sound.py 同口径的最长优先匹配，额外返回每处命中的位置。"""
    work = body
    marks = []  # (start, end, word, kind)  kind: hit / excl
    for pat in sound_dict.EXCLUDE_PATTERNS:
        idx = 0
        while True:
            i = work.find(pat, idx)
            if i < 0:
                break
            marks.append((i, i + len(pat), pat, "excl"))
            work = work[:i] + "□" * len(pat) + work[i + len(pat):]
            idx = i + len(pat)
    for w in words_desc:
        idx = 0
        while True:
            i = work.find(w, idx)
            if i < 0:
                break
            marks.append((i, i + len(w), w, "hit"))
            work = work[:i] + "□" * len(w) + work[i + len(w):]
            idx = i + len(w)
    marks.sort()
    segs, pos = [], 0
    for s, e, w, kind in marks:
        if s > pos:
            segs.append([body[pos:s], 0])
        segs.append([w, 1 if kind == "hit" else 2])
        pos = e
    if pos < len(body):
        segs.append([body[pos:], 0])
    hits = Counter(w for s, e, w, k in marks if k == "hit")
    return segs, hits, marks


def index_canonical_poems(poems):
    indexed = {}
    for poem in poems:
        key = (poem["author"], poem["title"])
        candidates = indexed.get(key)
        if candidates is None:
            indexed[key] = [poem]
        else:
            candidates.append(poem)
    return indexed


def select_canonical_poem(indexed, poet, title):
    candidates = indexed.get((poet, title), [])
    if len(candidates) != 1:
        raise ValueError(
            f"canonical 明星案例无法唯一定位: {(poet, title)}，候选={len(candidates)}"
        )
    return candidates[0]


def index_sound_records(records):
    indexes = {
        "by_canonical_id": {},
        "by_work_id": {},
        "by_body_hash": {},
    }
    for record in records:
        work_id = record.get("work_id")
        if work_id:
            if work_id in indexes["by_work_id"]:
                raise ValueError(f"sound per_poem work_id 重复: {work_id}")
            indexes["by_work_id"][work_id] = record
        canonical_id = record.get("canonical_gushiwen_id")
        if canonical_id:
            key = (record["poet"], canonical_id)
            if key in indexes["by_canonical_id"]:
                raise ValueError(f"sound per_poem canonical ID 重复: {key}")
            indexes["by_canonical_id"][key] = record
        hash_key = (record["poet"], record["body_hash"])
        candidates = indexes["by_body_hash"].get(hash_key)
        if candidates is None:
            indexes["by_body_hash"][hash_key] = [record]
        else:
            candidates.append(record)
    return indexes


def load_dual_corpus_metadata(stats, analysis_record_count, canonical_count):
    """从上游统计与 manifest 动态读取双层语料口径。"""
    manifest = json.loads(FULL_MANIFEST_JSON.read_text(encoding="utf-8"))
    analysis_count = manifest.get("record_count")
    canonical_evidence_count = manifest.get("canonical_count")
    if analysis_count != analysis_record_count:
        raise ValueError(
            "sound per_poem 与 full manifest 数量不一致: "
            f"per_poem={analysis_record_count}, manifest={analysis_count}"
        )
    if stats.get("generated_from_poems") != analysis_count:
        raise ValueError("sound_stats generated_from_poems 与 full manifest 不一致")
    if canonical_evidence_count != canonical_count:
        raise ValueError(
            "canonical 证据库与 full manifest 数量不一致: "
            f"poems={canonical_count}, manifest={canonical_evidence_count}"
        )
    corpus_source = str(stats.get("corpus_source") or "")
    corpus_path = str(stats.get("corpus_path") or "")
    if corpus_source != "analysis_full" or not corpus_path:
        raise ValueError(
            "viz37 状态层必须来自 analysis_full，且必须公开 corpus_path"
        )
    return {
        "corpus_source": corpus_source,
        "corpus_path": corpus_path,
        "analysis_count": analysis_count,
        "canonical_evidence_count": canonical_evidence_count,
    }


def published_identity(record, canonical_poem=None):
    work_id = str(record.get("work_id") or "").strip()
    body_hash = str(record.get("body_hash") or "").strip()
    if not work_id or not body_hash:
        raise ValueError("sound per_poem 作品缺少 work_id/body_hash")
    canonical_id = record.get("canonical_gushiwen_id") or None
    if canonical_poem is not None:
        expected_canonical_id = canonical_poem.get("source_poem_id") or None
        expected_body_hash = canonical_poem.get("body_hash")
        if expected_canonical_id and canonical_id != expected_canonical_id:
            raise ValueError("sound per_poem 与 canonical 证据的作品 ID 不一致")
        if expected_body_hash and body_hash != expected_body_hash:
            raise ValueError("sound per_poem 与 canonical 证据的 body_hash 不一致")
    return {
        "work_id": work_id,
        "canonical_gushiwen_id": canonical_id,
        "body_hash": body_hash,
    }


def sound_record_for_canonical(indexes, poem):
    poet = poem["author"]
    canonical_id = poem.get("source_poem_id")
    if canonical_id:
        record = indexes["by_canonical_id"].get((poet, canonical_id))
        if record is None:
            raise KeyError(f"sound per_poem 缺少 canonical ID: {(poet, canonical_id)}")
        return record
    work_id = poem.get("work_id")
    if work_id:
        record = indexes["by_work_id"].get(work_id)
        if record is None:
            raise KeyError(f"sound per_poem 缺少 work_id: {work_id}")
        return record
    hash_key = (poet, poem.get("body_hash"))
    candidates = indexes["by_body_hash"].get(hash_key, [])
    if len(candidates) > 1:
        raise ValueError(f"sound per_poem body_hash 非唯一，禁止回退: {hash_key}")
    if not candidates:
        raise KeyError(f"sound per_poem 缺少 canonical 正文: {hash_key}")
    return candidates[0]


def rank_for_canonical(ranked, indexes, poem):
    target = sound_record_for_canonical(indexes, poem)
    if target.get("work_id"):
        matches = [
            index for index, record in enumerate(ranked, 1)
            if record.get("work_id") == target["work_id"]
        ]
    elif target.get("canonical_gushiwen_id"):
        matches = [
            index for index, record in enumerate(ranked, 1)
            if record["poet"] == target["poet"]
            and record.get("canonical_gushiwen_id")
            == target["canonical_gushiwen_id"]
        ]
    else:
        matches = [
            index for index, record in enumerate(ranked, 1) if record is target
        ]
    if len(matches) != 1:
        raise ValueError(
            f"canonical 诗作排名无法唯一定位: "
            f"{(poem['author'], poem['title'], poem['body_hash'])}"
        )
    return matches[0]


def main() -> None:
    stats = json.loads(STATS_JSON.read_text(encoding="utf-8"))
    poems = json.loads(POEMS_JSON.read_text(encoding="utf-8"))
    words_desc = sound_dict.words()
    cat_of = {r[0]: r[1] for r in sound_dict.SOUND_DICT}
    sent_of = {r[0]: r[2] for r in sound_dict.SOUND_DICT}

    per_poet = stats["per_poet"]
    per_poem = stats["per_poem"]
    canonical_poems = index_canonical_poems(poems)
    sound_records = index_sound_records(per_poem)
    corpus_meta = load_dual_corpus_metadata(stats, len(per_poem), len(poems))

    # —— 全语料词频（证据句用）——
    corpus_words = Counter()
    for rec in per_poem:
        for w, n in rec["hits"]:
            corpus_words[w] += n
    corpus_total = sum(corpus_words.values())
    word_in_poems = Counter()  # 词出现在多少篇里
    for rec in per_poem:
        for w, n in rec["hits"]:
            word_in_poems[w] += 1

    # —— 最响篇目榜（含散文，如实标注体裁）——
    ranked = sorted(per_poem, key=lambda r: (-sum(n for _, n in r["hits"]), r["title"]))
    top_poems = [
        {
            **published_identity(record),
            "title": record["title"],
            "poet": record["poet"],
            "total": sum(n for _, n in record["hits"]),
            "genre": GENRE_NOTE.get(record["title"], "诗"),
        }
        for record in ranked[:6]
    ]

    # —— 六人卡片数据 ——
    poets_out = []
    for name in SIX_POETS:
        pp = per_poet[name]
        cat_counts = Counter()
        audible = []
        for rec in per_poem:
            if rec["poet"] != name:
                continue
            if rec["hits"]:
                audible.append({
                    **published_identity(rec),
                    "title": rec["title"],
                    "hits": rec["hits"],
                })
                for w, n in rec["hits"]:
                    cat_counts[cat_of[w]] += n
        assert sum(cat_counts.values()) == pp["hits_total"], name
        quiet_n = round(pp["quiet_ratio"] * pp["poem_count"])
        badge = ""
        if name == "白居易":
            top2 = sorted(audible, key=lambda a: -sum(n for _, n in a["hits"]))[:2]
            top2_hits = sum(sum(n for _, n in a["hits"]) for a in top2)
            badge = ("反直觉：高总命中与高无声占比并存——本语料 {} 首中 {} 首整首无声；"
                     "{} 次命中里 {} 次集中在《{}》《{}》两篇。").format(
                pp["poem_count"], quiet_n, pp["hits_total"], top2_hits,
                top2[0]["title"], top2[1]["title"])
        poets_out.append({
            "name": name, "color": POET_COLORS[name],
            "poems": pp["poem_count"], "hits": pp["hits_total"],
            "per100": pp["hits_per_100_chars"], "chars": pp["chars_total"],
            "quietN": quiet_n, "quietRatio": pp["quiet_ratio"],
            "catCounts": {c: cat_counts.get(c, 0) for c in CAT_NAMES},
            "sig": pp["soundscape_signature"],
            "audible": sorted(audible, key=lambda a: -sum(n for _, n in a["hits"])),
            "badge": badge,
        })

    # —— 明星案例：原文高亮（与统计逐词断言一致）——
    def build_poem(poet, title):
        canonical_poem = select_canonical_poem(canonical_poems, poet, title)
        body = canonical_poem["body"]
        segs, hits, marks = scan_positions(body, words_desc)
        rec = sound_record_for_canonical(sound_records, canonical_poem)
        assert hits == Counter(dict((w, n) for w, n in rec["hits"])), \
            "命中重算与 sound_stats 不一致: {} {}".format(poet, title)
        out = {**published_identity(rec, canonical_poem),
               "title": title, "poet": poet,
               "total": sum(hits.values()), "segs": segs,
               "hits": sorted(hits.items(), key=lambda kv: (-kv[1], kv[0]))}
        note = POEM_NOTES.get((poet, title))
        if note:
            out["note"] = note
        return out, marks, canonical_poem

    pipa, pipa_marks, pipa_canonical = build_poem("白居易", "琵琶行")
    pipa_body = pipa_canonical["body"]
    preface_len = pipa_body.find("\n")
    pipa_pref_pp = sum(1 for s, e, w, k in pipa_marks
                      if k == "hit" and w == "琵琶" and s < preface_len)
    # 单句四连击："杜鹃啼血猿哀鸣"
    line_hits = 0
    li = pipa_body.find("杜鹃啼血猿哀鸣")
    if li >= 0:
        line_hits = sum(1 for s, e, w, k in pipa_marks
                        if k == "hit" and li <= s < li + 7)
    pipa_rank = rank_for_canonical(ranked, sound_records, pipa_canonical)
    leader = ranked[0]
    leader_total = sum(n for _, n in leader["hits"])
    pipa_hit_map = dict(pipa["hits"])

    pipa["facts"] = [
        "共 {} 次命中、{} 种声音词，在全语料 {} 篇的单篇命中榜列第 {}；当前榜首为{}《{}》（{} 次）。".format(
            pipa["total"], len(pipa["hits"]), stats["generated_from_poems"], pipa_rank,
            leader["poet"], leader["title"], leader_total),
        "「琵琶」×{}：全语料「琵琶」共出现 {} 次，其中 {} 次在本篇诗前序文。".format(
            pipa_hit_map.get("琵琶", 0), corpus_words["琵琶"], pipa_pref_pp),
        "「嘈嘈」×2、「切切」×2：全语料「嘈嘈」共 {} 次（见于 {} 篇）、「切切」共 {} 次（见于 {} 篇）——大弦嘈嘈如急雨，小弦切切如私语。".format(
            corpus_words["嘈嘈"], word_in_poems["嘈嘈"], corpus_words["切切"], word_in_poems["切切"]),
        "「幽咽泉流冰下难」的「咽」按词典归入自然声（词条注明亦覆盖人声呜咽）；「杜鹃啼血猿哀鸣」一句连中 {} 词（杜鹃、啼、猿、鸣）——单句声音密度全篇之最。".format(line_hits),
    ]

    wangwei_pp = per_poet["王维"]
    ww_poems = []
    for poet, title in STAR_POEMS["wangwei"]:
        po, _, _ = build_poem(poet, title)
        ww_poems.append(po)
    ww_total = sum(p["total"] for p in ww_poems)
    assert ww_total <= wangwei_pp["hits_total"], "王维精选案例命中不应超过全库命中"
    wangwei = {
        "name": "王维", "color": POET_COLORS["王维"],
        "poems": ww_poems, "total": ww_total, "corpusTotal": wangwei_pp["hits_total"],
        "quietN": round(wangwei_pp["quiet_ratio"] * wangwei_pp["poem_count"]),
        "poemCount": wangwei_pp["poem_count"],
        "note": ("本语料王维 {} 首中 {} 首整首无声，全库共 {} 次声音命中；"
                 "本页选取的 {} 首经典作品合计 {} 次并全部点亮。这里展示的是“以声衬静”的可核案例，"
                 "不再把精选案例误写成王维全库总量。").format(
            wangwei_pp["poem_count"],
            round(wangwei_pp["quiet_ratio"] * wangwei_pp["poem_count"]),
            wangwei_pp["hits_total"], len(ww_poems), ww_total),
    }

    def border_side(key, name):
        pp = per_poet[name]
        cat_counts = Counter()
        for rec in per_poem:
            if rec["poet"] == name:
                for w, n in rec["hits"]:
                    cat_counts[cat_of[w]] += n
        ps = []
        for poet, title in STAR_POEMS[key]:
            po, _, _ = build_poem(poet, title)
            ps.append(po)
        return {"name": name, "color": POET_COLORS[name],
                "hits": pp["hits_total"], "chars": pp["chars_total"],
                "poemCount": pp["poem_count"],
                "cats": {c: cat_counts.get(c, 0) for c in CAT_NAMES},
                "poems": ps}

    dufu = border_side("dufu", "杜甫")
    gaoshi = border_side("gaoshi", "高适")
    du_hum = Counter()
    gao_hum = Counter()
    for rec in per_poem:
        for w, n in rec["hits"]:
            if cat_of[w] == "人声":
                if rec["poet"] == "杜甫":
                    du_hum[w] += n
                elif rec["poet"] == "高适":
                    gao_hum[w] += n
    border_reading = [
        "扩容后本库收录杜甫 {} 首/{} 字、高适 {} 首/{} 字；下图比较两人全库六类声音构成，上方原文只选三首作证据入口。".format(
            dufu["poemCount"], dufu["chars"], gaoshi["poemCount"], gaoshi["chars"]),
        "杜甫全库人声 {} 次，其中哭与泣合计 {} 次（哭×{}、泣×{}）；器乐类共 {} 次。".format(
            sum(du_hum.values()), du_hum["哭"] + du_hum["泣"], du_hum["哭"], du_hum["泣"], dufu["cats"]["器乐"]),
        "高适全库人声 {} 次，其中「歌」{} 次；器乐类共 {} 次。".format(
            sum(gao_hum.values()), gao_hum["歌"], gaoshi["cats"]["器乐"]),
        "这些差异是词典口径下的文本声景构成，可用于提出对读问题；具体时代阐释仍需回到上方原句与作品语境。",
    ]

    word_info = {r[0]: [r[1], r[2]] for r in sound_dict.SOUND_DICT}
    excl_reasons = [
        ["萧瑟", "萧瑟＝凋敝萧条，其「瑟」非乐器"],
        ["瑟缩", "瑟缩＝蜷缩，无声"],
        ["半江瑟瑟", "《暮江吟》「半江瑟瑟半江红」：瑟瑟作碧色解，非风声"],
        ["杜鹃花", "花名，非鸟啼"],
        ["钟山", "地名"],
        ["钟情", "钟＝聚集"],
        ["屋漏", "「床头屋漏」漏雨非更漏（防御性保留）"],
    ]

    data = {
        "meta": {
            **corpus_meta,
            "dictSize": stats["dict_size"],
            "corpusPoems": stats["generated_from_poems"],
            "corpusPoets": len(per_poet),
            "corpusHits": corpus_total,
            "excludeCount": len(sound_dict.EXCLUDE_PATTERNS),
        },
        "cats": CATS,
        "wordInfo": word_info,
        "corpusTop": [[w, n] for w, n in corpus_words.most_common(14)],
        "topPoems": top_poems,
        "poets": poets_out,
        "star": {
            "pipa": pipa,
            "wangwei": wangwei,
            "border": {"dufu": dufu, "gaoshi": gaoshi, "reading": border_reading},
        },
        "excludes": excl_reasons,
    }

    OUT_DATA.parent.mkdir(parents=True, exist_ok=True)
    OUT_DATA.write_text(
        json.dumps(data, ensure_ascii=False, indent=1),
        encoding="utf-8",
        newline="\n",
    )

    data_js = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    six_counts = "、".join("{} {}首".format(p, per_poet[p]["poem_count"]) for p in SIX_POETS)
    html = (TEMPLATE.replace("__DATA__", data_js)
            .replace("__CORPUS_POEMS__", str(stats["generated_from_poems"]))
            .replace("__ANALYSIS_COUNT__", str(corpus_meta["analysis_count"]))
            .replace(
                "__CANONICAL_EVIDENCE_COUNT__",
                str(corpus_meta["canonical_evidence_count"]),
            )
            .replace("__CORPUS_POETS__", str(len(per_poet)))
            .replace("__SIX_COUNTS__", six_counts)
            .replace("__PIPA_TOTAL__", str(pipa["total"]))
            .replace("__PIPA_RANK__", str(pipa_rank))
            .replace("__WW_SELECTED_TOTAL__", str(ww_total))
            .replace("__WW_SELECTED_N__", str(len(ww_poems)))
            .replace("__TOP_AUTHOR__", leader["poet"])
            .replace("__TOP_TITLE__", leader["title"])
            .replace("__TOP_TOTAL__", str(leader_total))
            .replace("__MING_TOTAL__", str(corpus_words.get("鸣", 0))))

    # —— 自检 ——
    assert "NaN" not in html, "页面字面出现 NaN"
    assert "Infin" + "ity" not in html, "页面字面出现无穷大字样"
    assert 'name="viewport"' in html, "缺 viewport"
    assert "http://" not in html and "https://" not in html, "出现远程地址"
    assert '<script src="assets/pyecharts/v6/echarts.min.js"></script>' in html
    OUT_HTML.write_text(html, encoding="utf-8", newline="\n")
    size = OUT_HTML.stat().st_size
    assert size >= 5000, "页面过小"
    print("[viz_37] OK  html={} bytes  data={} bytes  corpus_hits={}".format(
        size, OUT_DATA.stat().st_size, corpus_total))


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>37 · 可听的诗 —— 诗行万里</title>
<script src="assets/pyecharts/v6/echarts.min.js"></script>
<style>
:root{
  --paper:#f2f4f0; --ink:#252b27; --cinnabar:#b64b3f; --jade:#26786e;
  --gold:#a87527; --blue:#426f94; --card:#fbfcfa; --line:#d8ddd6;
  --muted:#6b736d;
}
*{box-sizing:border-box; margin:0; padding:0;}
html,body{background:var(--paper); color:var(--ink);
  font-family:"Microsoft YaHei","PingFang SC",sans-serif; line-height:1.75;}
body{overflow-x:hidden;}
h1,h2,h3,h4,.kai{font-family:KaiTi,STKaiti,"Microsoft YaHei",serif;}
.wrap{max-width:1180px; margin:0 auto; padding:0 20px;}
a{color:var(--blue); text-decoration:none;}
a:hover{text-decoration:underline;}

/* ── 页眉 ── */
header{padding:44px 0 10px; border-bottom:1px solid var(--line);
  background:linear-gradient(180deg,#eef1ec,var(--paper));}
.eyebrow{letter-spacing:.35em; color:var(--muted); font-size:13px;}
h1{font-size:clamp(28px,4.5vw,44px); letter-spacing:.12em; margin:6px 0 4px;}
h1 .accent{color:var(--cinnabar);}
.sub{color:var(--muted); max-width:760px; font-size:15px;}
.meta-strip{display:flex; flex-wrap:wrap; gap:10px 26px; margin:18px 0 8px;
  font-size:13px; color:var(--muted);}
.meta-strip b{color:var(--ink); font-size:17px; font-family:KaiTi,STKaiti,serif;}

/* ── 声音开关条 ── */
.audio-bar{display:flex; flex-wrap:wrap; align-items:center; gap:10px 14px;
  margin:16px 0 20px; padding:10px 14px; background:var(--card);
  border:1px solid var(--line); border-radius:10px;}
#audioToggle{font-family:KaiTi,STKaiti,serif; font-size:15px; cursor:pointer;
  padding:6px 16px; border-radius:20px; border:1.5px solid var(--ink);
  background:transparent; color:var(--ink); transition:all .2s;}
#audioToggle.on{background:var(--cinnabar); border-color:var(--cinnabar); color:#fff;}
#audioToggle:disabled{opacity:.45; cursor:not-allowed;}
.audio-note{font-size:12.5px; color:var(--muted);}
.cat-legend{display:flex; flex-wrap:wrap; gap:8px; width:100%;}
.cat-pill{display:inline-flex; align-items:center; gap:6px; font-size:13px;
  padding:4px 10px 4px 8px; border-radius:16px; border:1px solid var(--line);
  background:#fff; cursor:pointer; user-select:none; transition:transform .15s;}
.cat-pill:hover{transform:translateY(-1px);}
.cat-pill .dot{width:10px; height:10px; border-radius:50%; flex:none;}
.cat-pill small{color:var(--muted); font-size:11px;}
.cat-pill .play{font-size:10px; color:var(--muted);}

/* ── 区块 ── */
section{margin:38px 0;}
.sec-head{display:flex; align-items:baseline; gap:14px; flex-wrap:wrap;
  border-left:5px solid var(--cinnabar); padding-left:14px; margin-bottom:6px;}
.sec-head h2{font-size:24px; letter-spacing:.08em;}
.sec-head .tag{font-size:12px; color:var(--muted);}
.sec-note{color:var(--muted); font-size:13.5px; max-width:860px; margin-bottom:16px;}

/* ── 卡片与图表 ── */
.grid{display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:16px;}
.card{background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:16px 16px 12px; box-shadow:0 1px 3px rgba(37,43,39,.05);}
.card h3{font-size:20px; letter-spacing:.1em; display:flex; align-items:baseline; gap:10px;}
.card h3 .stat{font-family:"Microsoft YaHei"; font-size:12px; color:var(--muted);
  letter-spacing:0; font-weight:normal;}
.rose{width:100%; height:200px;}
.chart-wide{width:100%; height:320px;}
.chips{display:flex; flex-wrap:wrap; gap:6px; margin:8px 0 4px;}
.chip{display:inline-flex; align-items:center; gap:4px; font-size:13px;
  font-family:KaiTi,STKaiti,serif; padding:2px 9px; border-radius:5px;
  border:1px solid transparent; cursor:pointer; background:#fff;
  border-left-width:4px; transition:transform .12s;}
.chip:hover{transform:translateY(-1px);}
.chip .n{font-size:11px; color:var(--muted); font-family:"Microsoft YaHei";}
.quiet-row{display:flex; align-items:center; gap:10px; margin:10px 0 4px; font-size:12.5px;}
.quiet-bar{flex:1; height:8px; border-radius:4px; background:#e3e7e1; overflow:hidden;}
.quiet-bar i{display:block; height:100%; background:repeating-linear-gradient(
  -45deg,#b9c2ba 0 6px,#cdd4cc 6px 12px); border-radius:4px;}
.quiet-row b{font-family:KaiTi,STKaiti,serif;}
.badge{margin-top:8px; padding:8px 10px; font-size:12.5px; line-height:1.6;
  background:#fdf6ef; border:1px dashed var(--gold); border-radius:8px; color:#6d5322;}
details.plist{margin-top:8px; font-size:13px;}
details.plist summary{cursor:pointer; color:var(--blue); font-size:12.5px;}
details.plist ul{list-style:none; margin:6px 0 2px;}
details.plist li{padding:3px 0; border-top:1px dashed #e4e8e2; display:flex;
  flex-wrap:wrap; gap:4px 8px; align-items:center;}
details.plist li .t{font-family:KaiTi,STKaiti,serif; min-width:0;}
.mini-chip{font-size:11.5px; padding:0 6px; border-radius:4px; border-left:3px solid;
  background:#fff; font-family:KaiTi,STKaiti,serif; cursor:pointer;}
.mut{color:var(--muted); font-size:12px;}

/* ── 明星案例 ── */
.star-block{background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:20px; margin:18px 0;}
.star-block>h3{font-size:22px; letter-spacing:.1em; margin-bottom:4px;}
.star-block>h3 .who{font-size:14px; color:var(--muted); letter-spacing:.05em;}
.star-note{font-size:13.5px; color:var(--muted); max-width:900px; margin-bottom:12px;}
.pipa-grid{display:grid; grid-template-columns:minmax(0,1.35fr) minmax(260px,1fr); gap:18px;}
.pipa-grid>*{min-width:0;}
.poem-box{background:#fff; border:1px solid var(--line); border-radius:10px;
  padding:16px 18px; font-family:KaiTi,STKaiti,serif; font-size:16.5px;
  line-height:2.15; white-space:pre-wrap; max-height:430px; overflow-y:auto;}
.poem-box.small{max-height:none; font-size:16px; padding:12px 14px;}
.hit{padding:0 2px; border-radius:4px; border-bottom:2px solid; cursor:pointer;}
.excl{border-bottom:2px dotted #9aa39c; color:#8a938c;}
.facts{list-style:none; font-size:13.5px;}
.facts li{padding:8px 0 8px 14px; border-top:1px dashed #e2e6e0; position:relative;}
.facts li::before{content:"◆"; position:absolute; left:0; top:8px; font-size:9px;
  color:var(--cinnabar);}
.poemcards{display:grid; grid-template-columns:repeat(auto-fit,minmax(215px,1fr)); gap:12px;}
.pcard{background:#fff; border:1px solid var(--line); border-radius:10px; padding:12px 14px;}
.pcard h4{font-size:17px; letter-spacing:.1em; display:flex; justify-content:space-between;
  align-items:baseline;}
.pcard h4 .cnt{font-size:11.5px; color:var(--muted); font-family:"Microsoft YaHei";}
.pcard .poem-body{font-family:KaiTi,STKaiti,serif; font-size:15.5px; line-height:2.05;
  white-space:pre-wrap; margin-top:6px;}
.pcard .pnote{font-size:11.5px; color:var(--muted); margin-top:6px; border-top:1px dashed #e4e8e2; padding-top:5px;}
.border-grid{display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:14px;}
.border-col{border:1px solid var(--line); border-radius:10px; background:#fff; padding:14px;}
.border-col h4{font-size:19px; letter-spacing:.12em; margin-bottom:2px;}
.border-col .sub-line{font-size:12px; color:var(--muted); margin-bottom:8px;}
.reading{font-size:13.5px; max-width:960px;}
.reading li{margin:6px 0 6px 18px;}

/* ── 榜单表 ── */
.tbl-scroll{overflow-x:auto; max-width:100%;}
table.rank{border-collapse:collapse; font-size:13.5px; min-width:420px;}
table.rank th,table.rank td{padding:6px 14px 6px 0; text-align:left;
  border-bottom:1px solid #e4e8e2; white-space:nowrap;}
table.rank th{color:var(--muted); font-weight:normal; font-size:12px;}
table.rank .kai{font-size:15px;}
table.rank .genre-prose{color:var(--cinnabar);}

/* ── 方法区 ── */
details.method{background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:14px 18px; margin:30px 0;}
details.method summary{font-family:KaiTi,STKaiti,serif; font-size:18px; cursor:pointer;
  letter-spacing:.1em;}
details.method h4{margin:14px 0 4px; font-size:15.5px; color:var(--cinnabar);}
details.method p,details.method li{font-size:13.5px; color:#3d453f;}
details.method ul{margin-left:20px;}
details.method table{border-collapse:collapse; font-size:13px; margin:6px 0;}
details.method table td,details.method table th{border:1px solid var(--line);
  padding:4px 12px; text-align:left;}
details.method table th{background:#eef1ec; font-weight:normal;}

/* ── 提示浮层 / 页脚 ── */
#toast{position:fixed; left:50%; bottom:34px; transform:translateX(-50%) translateY(20px);
  background:var(--ink); color:#f2f4f0; font-size:13px; padding:8px 18px;
  border-radius:20px; opacity:0; pointer-events:none; transition:all .3s; z-index:50;
  max-width:86vw;}
#toast.show{opacity:.94; transform:translateX(-50%) translateY(0);}
footer{border-top:1px solid var(--line); margin-top:46px; padding:22px 0 34px;
  font-size:13px; color:var(--muted);}
.site-nav{display:flex; flex-wrap:wrap; gap:6px 16px; margin-bottom:10px;}
.site-nav a{white-space:nowrap;}
.site-nav .here{color:var(--cinnabar); font-weight:bold; white-space:nowrap;}

@media (max-width:900px){
  .pipa-grid{grid-template-columns:1fr;}
  .border-grid{grid-template-columns:1fr;}
}
@media (max-width:420px){
  .wrap{padding:0 12px;}
  .poem-box{font-size:15px; padding:12px;}
}
/* 固定画幅背景：使用克制的音景方案，不改变既有内容布局。 */
body{position:relative; min-height:100vh; background:transparent;}
body::before{content:""; position:fixed; inset:0; z-index:0; pointer-events:none;
  background:url("assets/generated/remaining_pages_20260830/37_soundscape_v1.png") center center / cover no-repeat;}
body::after{content:""; position:fixed; inset:0; z-index:0; pointer-events:none;
  background:rgba(242,244,240,.13);}
body>header,body>.wrap{position:relative; z-index:1;}
header{background:linear-gradient(180deg,rgba(238,241,236,.92),rgba(242,244,240,.82));}
.audio-bar,.card,.star-block,details.method{background:rgba(251,252,250,.91); backdrop-filter:blur(1px);}
.cat-pill,.chip,.mini-chip,.poem-box,.pcard,.border-col{background:rgba(255,255,255,.89);}
</style>
</head>
<body>
<script>window.SOUND_DATA=__DATA__;</script>

<header>
  <div class="wrap">
      <div class="eyebrow">诗行万里 · 37</div>
    <h1>可听的诗<span class="accent">。</span></h1>
    <p class="sub">给状态层 __ANALYSIS_COUNT__ 首全作品做一次「录音」：只统计<b>被听见的声音</b>——猿声、砧杵、琵琶、戍鼓、松风、人语。
      六类声音、八十八个词条，扫出每位诗人独有的声景指纹；明星案例则回到证据层 __CANONICAL_EVIDENCE_COUNT__ 首规范作品，逐字点亮《琵琶行》的一夜、王维的空山、盛唐的两种边声。</p>
    <div class="meta-strip" id="metaStrip"></div>
    <div class="audio-bar">
      <button id="audioToggle" aria-pressed="false">♪ 声音：关</button>
      <span class="audio-note">可听化为 Web Audio 合成的抽象音色（振荡器＋噪声＋包络，非真实录音），默认静音；开启后点击任意声音词/芯片即可试听 1–2 秒。音频不可用时自动降级，不影响任何视觉内容。</span>
      <div class="cat-legend" id="catLegend"></div>
    </div>
  </div>
</header>

<div class="wrap">

<section id="sec-corpus">
  <div class="sec-head"><h2>状态层 · 全作品声音榜</h2><span class="tag">88 词条 · 六类 · 最长优先不重叠匹配</span></div>
  <p class="sec-note">整个语料里最常被写下的声音。「歌」遥遥领先——古人写声音，首先写的是人自己发出的声音；其次才是鸣、啼这些自然的喉咙。条色即声音类别。</p>
  <div class="card"><div id="corpusChart" class="chart-wide"></div></div>
</section>

<section id="sec-poets">
  <div class="sec-head"><h2>六人声景指纹</h2><span class="tag">玫瑰图＝六类声音命中构成 · 芯片＝标志性声音（次数×偏爱度） · 灰条＝无声诗占比</span></div>
  <p class="sec-note">同一套词典扫过六个人的当前在库作品，比较人声、器乐、自然声等六类构成。「无声诗」指整首未出现词典内任何声音词——占比越高，越接近词典口径下的「默片诗人」。每张卡可展开命中明细核对证据。</p>
  <div class="grid" id="poetGrid"></div>
  <p class="mut" style="margin-top:10px">口径提醒：六人当前样本为 __SIX_COUNTS__；仍以本库收录为边界，密度与占比不外推为诗人全集结论。</p>
</section>

<section id="sec-star">
  <div class="sec-head"><h2>证据层 · 明星案例三间录音室</h2><span class="tag">稳定 ID 回配原文；亮的即统计里算的</span></div>

  <div class="star-block" id="starPipa">
    <h3>一、《琵琶行》：一首诗铺开的音墙 <span class="who">白居易 · __PIPA_TOTAL__ 次命中 · 全库第 __PIPA_RANK__</span></h3>
    <p class="star-note">声音词按六类染色——琵琶、嘈嘈、切切、幽咽次第出现。扩容后它不再被写成全库第一，实际名次与当前榜首都在右侧实时列出。</p>
    <div class="pipa-grid">
      <div>
        <div class="poem-box" id="pipaText"></div>
        <p class="mut" id="pipaNote" style="margin-top:6px"></p>
      </div>
      <div>
        <div class="chips" id="pipaChips"></div>
        <ul class="facts" id="pipaFacts"></ul>
        <h4 class="kai" style="margin:14px 0 4px">全语料最响篇目</h4>
        <div class="tbl-scroll"><table class="rank" id="rankTbl"></table></div>
      </div>
    </div>
  </div>

  <div class="star-block" id="starWw">
    <h3>二、王维：以声衬静 <span class="who">精选 __WW_SELECTED_N__ 首 · __WW_SELECTED_TOTAL__ 次命中全部点亮</span></h3>
    <p class="star-note" id="wwNote"></p>
    <div class="poemcards" id="wwCards"></div>
  </div>

  <div class="star-block" id="starBorder">
    <h3>三、盛唐两种边声 <span class="who">杜甫的哭声与战鼓 · 高适的羌笛与钟鼓</span></h3>
    <p class="star-note">同写战争与边地，两副耳朵录下两条完全不同的音轨。左右各选三首命中原文，下图为两人全部命中的六类构成对比。</p>
    <div class="border-grid" id="borderGrid"></div>
    <div class="card"><div id="dgChart" class="chart-wide" style="height:280px"></div></div>
    <ul class="reading" id="borderReading" style="margin-top:12px"></ul>
  </div>
</section>

<details class="method">
  <summary>方法与数据（口径 · 排除表 · 局限）</summary>
  <h4>词典口径：只收「被听见的声音」</h4>
  <p>声音词典共 88 词条（<code>data/stylometry/sound_dict.py</code>，人工整理，非权威词库）：只收在古典诗词中通常作为「被听见的声音」出现的词——声音源意象（猿声、钟、砧、羌笛、更漏……）与拟声词/听觉动词（啼、萧萧、滴、咽、喧……）。因此不收多为视觉呈现的近邻词：「雁」不收、只收「雁声」；「马」不收、只收「马嘶/嘶」；「波涛」不收、只收「涛声」。六类划分：兽鸣（广义动物含虫声）/ 鸟啼 / 器乐（丝竹与军中鼓角）/ 钟磬（报时宗教器声）/ 自然声 / 人声（人语歌哭与劳作市井声）。每词带 [-1,1] 情感倾向，为人工标注、仅供染色，不宣称权威。</p>
  <h4>匹配算法</h4>
  <p>与语料扫描端一致：先从文本挖除排除表片段，再按词长降序<b>最长优先、不重叠</b>贪心匹配——「猿声」只计一次，不再重复计「猿」。本页所有明星案例的高亮由同一算法现场重算，并逐词断言与 <code>sound_stats.json</code> 的 per_poem 记录一致后才写入页面。</p>
  <h4>排除表（匹配前挖除的已知误报）</h4>
  <table id="exclTbl"><tr><th>片段</th><th>排除原因</th></tr></table>
  <h4>散文抬高计数的说明</h4>
  <p>语料 __CORPUS_POEMS__ 篇中混有散文、赋、传奇与组诗合刊。当前单篇命中榜首为 __TOP_AUTHOR__《__TOP_TITLE__》（__TOP_TOTAL__ 次）；议论复沓、合刊篇幅与听觉场景并非同一概念，因此榜单逐项标注体裁。全语料统计数字（含声音榜的「鸣」__MING_TOTAL__ 次）不做体裁剔除，如实保留。</p>
  <h4>语料与样本口径</h4>
  <ul>
    <li><b>状态层</b>来自 <code>analysis_full</code>，覆盖 __CORPUS_POETS__ 位诗人、__ANALYSIS_COUNT__ 首全作品；声音总量、密度与无声诗占比均由这一层计算。</li>
    <li><b>证据层</b>为 __CANONICAL_EVIDENCE_COUNT__ 首 canonical 规范作品，仅用于明星案例原文与可核证据。每条发布作品均保留 <code>work_id</code>、可空的 <code>canonical_gushiwen_id</code> 与 <code>body_hash</code>，不按同名标题串联。</li>
    <li>六人状态样本为 __SIX_COUNTS__。所有占比、密度、无声诗占比只在本语料口径内成立。</li>
    <li>单篇长诗、组诗合刊或散文仍可能显著主导总命中，页面同时给出篇数、字数、密度与无声占比，避免只看一个总数。</li>
    <li>「无声诗占比」＝整首未出现词典内声音词的诗占比，是词典口径下的近似，不等于真实世界的无声。</li>
  </ul>
  <h4>归类近似（如实声明）</h4>
  <ul>
    <li>泛用动词「啼／鸣／噪」统一归鸟啼类，实际也覆盖猿啼、蝉鸣、弓弦鸣（王维《观猎》「角弓鸣」即一例，已在卡片注明）；长词优先已消化大部分误差。</li>
    <li>「咽」归自然声（泉声咽），也覆盖人声呜咽（《石壕吏》「泣幽咽」）；「萧萧」归自然声，也覆盖马鸣（《兵车行》「马萧萧」）。</li>
    <li>《琵琶行》「秋瑟瑟」按词典计自然声（风声义），而《暮江吟》「半江瑟瑟」为碧色义、已被排除表挖除——同字不同义，逐处人工核对。</li>
  </ul>
  <h4>可听化说明</h4>
  <p>六类音色全部由浏览器 Web Audio API 现场合成（振荡器、噪声缓冲与增益包络的抽象化音效），页面不加载任何音频文件，也不请求任何远程资源；不支持 Web Audio 的环境中开关自动禁用，全部视觉功能不受影响。</p>
  <h4>数据文件</h4>
  <p>本页数据快照：<code>output/assets/competition/sound_page_data.json</code>；上游统计：<code>data/stylometry/sound_stats.json</code>（schema v1，覆盖 __CORPUS_POETS__ 位诗人 / __CORPUS_POEMS__ 篇）。生成脚本 <code>数据可视化脚本/viz_37_soundscape.py</code> 零参数可复跑。</p>
</details>

</div>

<footer>
  <div class="wrap">
    <nav class="site-nav">
    <a href="29_参赛导航.html">29 作品目录</a>
      <a href="30_诗行万里_参赛版.html">30 总入口</a>
      <a href="31_凝望罗盘.html">31 凝望罗盘</a>
      <a href="32_身与心双层地图.html">32 身与心双层地图</a>
      <a href="33_平行时空759.html">33 平行时空759</a>
      <a href="34_一字识诗人.html">34 一字识诗人</a>
      <a href="35_两种孤独与夸张签名.html">35 两种孤独与夸张签名</a>
      <a href="36_同龄对齐.html">36 同龄对齐</a>
      <span class="here">37 可听的诗（本页）</span>
      <a href="38_唐宋意象潮汐.html">38 意象潮汐</a>
      <a href="39_诗人自述生命卷.html">39 诗人自述生命卷</a>
    </nav>
  <div>诗行万里 · 唐宋诗歌数字可视化 · 声音维度 —— 词典与统计口径见上方「方法与数据」。</div>
  </div>
</footer>

<div id="toast" role="status"></div>

<script>
(function(){
"use strict";
var D = window.SOUND_DATA;
var CAT_BY_NAME = {};
D.cats.forEach(function(c){ CAT_BY_NAME[c.name] = c; });
function catOf(w){ var i = D.wordInfo[w]; return i ? i[0] : "人声"; }
function sentOf(w){ var i = D.wordInfo[w]; return i ? i[1] : 0; }
function catColor(name){ var c = CAT_BY_NAME[name]; return c ? c.color : "#888"; }
function fmt(v){ return (typeof v === "number" && v === v) ? v : "—"; }
function pct(v){ return (typeof v === "number" && v === v) ? Math.round(v*100) + "%" : "—"; }
function tint(hex, a){
  var r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
  return "rgba(" + r + "," + g + "," + b + "," + a + ")";
}
function el(tag, cls, text){
  var e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

/* ───────── 音频（默认关，优雅降级） ───────── */
var AC = window.AudioContext || window.webkitAudioContext;
var audioOn = false, actx = null, master = null, noiseBuf = null, hinted = false;
var toggleBtn = document.getElementById("audioToggle");
function toast(msg){
  var t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._h);
  toast._h = setTimeout(function(){ t.classList.remove("show"); }, 2400);
}
if (!AC){
  toggleBtn.disabled = true;
  toggleBtn.textContent = "♪ 此浏览器不支持 Web Audio";
  toggleBtn.title = "音频不可用；全部视觉功能不受影响";
}
toggleBtn.addEventListener("click", function(){
  if (toggleBtn.disabled) return;
  if (!audioOn){
    try{
      if (!actx){
        actx = new AC();
        master = actx.createGain();
        master.gain.value = 0.28;
        master.connect(actx.destination);
      }
      if (actx.state === "suspended") actx.resume();
      audioOn = true;
      toggleBtn.classList.add("on");
      toggleBtn.setAttribute("aria-pressed","true");
      toggleBtn.textContent = "♪ 声音：开";
      toast("已开启合成音效——点击任意声音词试听");
    }catch(e){
      toggleBtn.disabled = true;
      toggleBtn.textContent = "♪ 音频初始化失败";
      toast("音频不可用；视觉内容不受影响");
    }
  } else {
    audioOn = false;
    toggleBtn.classList.remove("on");
    toggleBtn.setAttribute("aria-pressed","false");
    toggleBtn.textContent = "♪ 声音：关";
  }
});
function getNoise(){
  if (!noiseBuf){
    var sr = actx.sampleRate, len = Math.floor(sr * 2);
    noiseBuf = actx.createBuffer(1, len, sr);
    var d = noiseBuf.getChannelData(0);
    for (var i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
  }
  return noiseBuf;
}
function tone(type, f0, t, dur, peak, glideTo){
  var o = actx.createOscillator(), g = actx.createGain();
  o.type = type; o.frequency.setValueAtTime(f0, t);
  if (glideTo) o.frequency.exponentialRampToValueAtTime(glideTo, t + dur);
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(peak, t + 0.02);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  o.connect(g); g.connect(master);
  o.start(t); o.stop(t + dur + 0.05);
  return o;
}
var SYNTH = {
  bell: function(t){           // 钟磬：非谐分音长衰减
    [[1,0.55],[2.01,0.24],[2.98,0.16],[4.16,0.09]].forEach(function(p){
      var o = actx.createOscillator(), g = actx.createGain();
      o.type = "sine"; o.frequency.value = 196 * p[0];
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(p[1], t + 0.015);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 1.9);
      o.connect(g); g.connect(master); o.start(t); o.stop(t + 2);
    });
  },
  bird: function(t){           // 鸟啼：三声上扬滑音啁啾
    for (var i = 0; i < 3; i++){
      var st = t + i * 0.22;
      var o = actx.createOscillator(), g = actx.createGain();
      o.type = "sine";
      o.frequency.setValueAtTime(2200 + i * 160, st);
      o.frequency.exponentialRampToValueAtTime(3400, st + 0.07);
      o.frequency.exponentialRampToValueAtTime(1900, st + 0.15);
      g.gain.setValueAtTime(0.0001, st);
      g.gain.exponentialRampToValueAtTime(0.3, st + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, st + 0.17);
      o.connect(g); g.connect(master); o.start(st); o.stop(st + 0.2);
    }
  },
  beast: function(t){          // 兽鸣：下行哀啸带颤音
    var o = actx.createOscillator(), g = actx.createGain(), f = actx.createBiquadFilter();
    o.type = "sawtooth";
    o.frequency.setValueAtTime(640, t);
    o.frequency.exponentialRampToValueAtTime(290, t + 1.1);
    f.type = "lowpass"; f.frequency.value = 950;
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.22, t + 0.12);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 1.25);
    var lfo = actx.createOscillator(), lg = actx.createGain();
    lfo.frequency.value = 5.6; lg.gain.value = 0.08;
    lfo.connect(lg); lg.connect(g.gain);
    o.connect(f); f.connect(g); g.connect(master);
    o.start(t); o.stop(t + 1.3); lfo.start(t); lfo.stop(t + 1.3);
  },
  strings: function(t){        // 器乐：四声拨弦（琵琶轮指的抽象）
    [[0,294],[0.14,392],[0.28,440],[0.44,587]].forEach(function(p){
      var st = t + p[0];
      tone("triangle", p[1], st, 0.5, 0.3);
      var n = actx.createBufferSource(), ng = actx.createGain(), hp = actx.createBiquadFilter();
      n.buffer = getNoise(); hp.type = "highpass"; hp.frequency.value = 2500;
      ng.gain.setValueAtTime(0.12, st);
      ng.gain.exponentialRampToValueAtTime(0.0001, st + 0.03);
      n.connect(hp); hp.connect(ng); ng.connect(master);
      n.start(st); n.stop(st + 0.05);
    });
  },
  nature: function(t){         // 自然声：滤噪雨幕＋三滴清响
    var n = actx.createBufferSource(), lp = actx.createBiquadFilter(), g = actx.createGain();
    n.buffer = getNoise(); n.loop = true;
    lp.type = "lowpass"; lp.frequency.value = 1050;
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.24, t + 0.2);
    g.gain.setValueAtTime(0.24, t + 1.1);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 1.7);
    n.connect(lp); lp.connect(g); g.connect(master);
    n.start(t); n.stop(t + 1.8);
    [0.5, 0.9, 1.3].forEach(function(dt, i){
      tone("sine", 1500 + i * 260, t + dt, 0.09, 0.16);
    });
  },
  human: function(t){          // 人声：带颤音的低吟滑腔
    var o = actx.createOscillator(), g = actx.createGain();
    o.type = "sine";
    o.frequency.setValueAtTime(196, t);
    o.frequency.exponentialRampToValueAtTime(262, t + 0.5);
    o.frequency.exponentialRampToValueAtTime(175, t + 1.5);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.26, t + 0.25);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 1.6);
    var v = actx.createOscillator(), vg = actx.createGain();
    v.frequency.value = 5.2; vg.gain.value = 5;
    v.connect(vg); vg.connect(o.frequency);
    var h = actx.createOscillator(), hg = actx.createGain();
    h.type = "sine"; h.frequency.setValueAtTime(392, t);
    h.frequency.exponentialRampToValueAtTime(350, t + 1.5);
    hg.gain.setValueAtTime(0.0001, t);
    hg.gain.exponentialRampToValueAtTime(0.07, t + 0.3);
    hg.gain.exponentialRampToValueAtTime(0.0001, t + 1.6);
    o.connect(g); g.connect(master); h.connect(hg); hg.connect(master);
    o.start(t); o.stop(t + 1.7); v.start(t); v.stop(t + 1.7);
    h.start(t); h.stop(t + 1.7);
  }
};
function playCat(catName){
  if (!AC) return;
  if (!audioOn){
    if (!hinted){ toast("先开启页面顶部的「♪ 声音」开关，即可试听合成音色"); hinted = true; }
    else toast("声音开关未开启（页面顶部）");
    return;
  }
  try{
    var c = CAT_BY_NAME[catName];
    if (c && SYNTH[c.id]) SYNTH[c.id](actx.currentTime + 0.02);
  }catch(e){ /* 音频失败不影响视觉 */ }
}
document.addEventListener("click", function(ev){
  var n = ev.target.closest("[data-cat]");
  if (n) playCat(n.getAttribute("data-cat"));
});

/* ───────── 通用渲染部件 ───────── */
function chipNode(w, n, cls){
  var c = catOf(w), col = catColor(c);
  var b = el("button", cls || "chip");
  b.setAttribute("data-cat", c);
  b.title = w + " · " + c + " · 情感" + (sentOf(w) >= 0 ? "+" : "") + sentOf(w) +
            (n ? " · 出现" + n + "次" : "") + " · 点击试听该类音色";
  b.style.borderLeftColor = col;
  b.style.background = tint(col, 0.10);
  b.appendChild(document.createTextNode(w));
  if (n){ var s = el("span", "n", "×" + n); b.appendChild(s); }
  return b;
}
function renderSegs(container, segs){
  segs.forEach(function(sg){
    if (sg[1] === 1){
      var c = catOf(sg[0]), col = catColor(c);
      var sp = el("span", "hit", sg[0]);
      sp.setAttribute("data-cat", c);
      sp.title = sg[0] + " · " + c + " · 点击试听";
      sp.style.background = tint(col, 0.16);
      sp.style.borderBottomColor = col;
      container.appendChild(sp);
    } else if (sg[1] === 2){
      var ex = el("span", "excl", sg[0]);
      ex.title = sg[0] + " · 已被排除表挖除（非声音义）";
      container.appendChild(ex);
    } else {
      container.appendChild(document.createTextNode(sg[0]));
    }
  });
}

/* ───────── 页眉数据条 / 类别图例 ───────── */
(function(){
  var m = D.meta, ms = document.getElementById("metaStrip");
  [["状态层", fmt(m.analysis_count) + " 首 · " + fmt(m.corpusPoets) + " 位诗人"],
   ["证据层", fmt(m.canonical_evidence_count) + " 首规范作品"],
   ["声音词典", fmt(m.dictSize) + " 词条 · 六类"],
   ["全语料命中", fmt(m.corpusHits) + " 次"],
   ["排除表", fmt(m.excludeCount) + " 个已知误报片段"]].forEach(function(kv){
    var d = el("span"); d.appendChild(el("b", "", kv[1]));
    d.appendChild(document.createTextNode(" " + kv[0]));
    ms.appendChild(d);
  });
  var lg = document.getElementById("catLegend");
  D.cats.forEach(function(c){
    var p = el("span", "cat-pill");
    p.setAttribute("data-cat", c.name);
    p.title = "点击试听「" + c.name + "」类合成音色";
    var dot = el("i", "dot"); dot.style.background = c.color;
    p.appendChild(dot);
    p.appendChild(el("span", "", c.name));
    var sm = el("small", "", c.desc); p.appendChild(sm);
    p.appendChild(el("span", "play", "▶"));
    lg.appendChild(p);
  });
})();

/* ───────── ECharts ───────── */
var charts = [];
var hasEC = typeof window.echarts !== "undefined";
function mkChart(dom){
  if (!hasEC || !dom) return null;
  try{
    var ch = window.echarts.init(dom);
    charts.push(ch);
    return ch;
  }catch(e){ return null; }
}
var baseText = { color:"#252b27", fontFamily:'"Microsoft YaHei",sans-serif' };

/* 全语料榜（横条，按类别染色） */
(function(){
  var ch = mkChart(document.getElementById("corpusChart"));
  if (!ch) return;
  var rows = D.corpusTop.slice().reverse();
  ch.setOption({
    textStyle: baseText,
    grid:{left:8, right:46, top:8, bottom:8, containLabel:true},
    xAxis:{type:"value", splitLine:{lineStyle:{color:"#e3e7e1"}}, axisLabel:{color:"#6b736d"}},
    yAxis:{type:"category", data: rows.map(function(r){ return r[0]; }),
      axisLine:{lineStyle:{color:"#c9cfc7"}}, axisTick:{show:false},
      axisLabel:{fontFamily:"KaiTi,STKaiti,serif", fontSize:15}},
    tooltip:{trigger:"item", formatter:function(p){
      var w = rows[p.dataIndex][0];
      return w + " · " + catOf(w) + "<br>全语料命中 " + rows[p.dataIndex][1] + " 次";
    }},
    series:[{type:"bar", barWidth:"62%",
      data: rows.map(function(r){
        return { value:r[1], itemStyle:{ color: catColor(catOf(r[0])), borderRadius:[0,4,4,0] } };
      }),
      label:{show:true, position:"right", color:"#6b736d", fontSize:11,
        formatter:function(p){ return p.value; }}
    }]
  });
})();

/* 六人卡片（先建全部卡片，网格列宽定型后再统一初始化图表） */
(function(){
  var grid = document.getElementById("poetGrid");
  var pending = [];
  D.poets.forEach(function(p, idx){
    var card = el("div", "card");
    var h = el("h3", "", p.name);
    h.style.color = p.color;
    var st = el("span", "stat", "语料 " + fmt(p.poems) + " 首 · 命中 " + fmt(p.hits) +
      " 次 · 每百字 " + fmt(p.per100));
    h.appendChild(st);
    card.appendChild(h);
    var rose = el("div", "rose"); rose.id = "rose-" + idx;
    card.appendChild(rose);
    var chips = el("div", "chips");
    chips.appendChild(el("span", "mut", "标志性声音："));
    p.sig.forEach(function(sn){ chips.appendChild(chipNode(sn[0], sn[1])); });
    if (!p.sig.length) chips.appendChild(el("span", "mut", "（命中过少，无标志性声音）"));
    card.appendChild(chips);
    var qr = el("div", "quiet-row");
    qr.appendChild(el("b", "", "无声诗"));
    var bar = el("div", "quiet-bar");
    var fill = el("i"); fill.style.width = Math.round(p.quietRatio * 100) + "%";
    bar.appendChild(fill); qr.appendChild(bar);
    qr.appendChild(el("span", "", p.quietN + "/" + p.poems + "（" + pct(p.quietRatio) + "）"));
    card.appendChild(qr);
    if (p.badge) card.appendChild(el("div", "badge", p.badge));
    var det = el("details", "plist");
    var sm = el("summary", "", "命中明细（证据：" + p.audible.length + " 首有声诗）");
    det.appendChild(sm);
    var ul = el("ul");
    p.audible.forEach(function(a){
      var li = el("li");
      li.appendChild(el("span", "t kai", "《" + a.title + "》"));
      a.hits.forEach(function(hn){
        var mc = el("button", "mini-chip", hn[0] + (hn[1] > 1 ? "×" + hn[1] : ""));
        var col = catColor(catOf(hn[0]));
        mc.style.borderLeftColor = col;
        mc.setAttribute("data-cat", catOf(hn[0]));
        mc.title = hn[0] + " · " + catOf(hn[0]);
        li.appendChild(mc);
      });
      ul.appendChild(li);
    });
    det.appendChild(ul);
    det.appendChild(el("div", "mut", "其余 " + p.quietN + " 首整首未出现词典内声音词。"));
    card.appendChild(det);
    grid.appendChild(card);
    pending.push({ rose:rose, poet:p });
  });
  pending.forEach(function(item){
    var p = item.poet;
    var ch = mkChart(item.rose);
    if (ch){
      var data = D.cats.map(function(c){
        return { name:c.name, value:p.catCounts[c.name], itemStyle:{ color:c.color } };
      }).filter(function(d){ return d.value > 0; });
      ch.setOption({
        textStyle: baseText,
        tooltip:{trigger:"item", formatter:function(q){
          return q.name + "：" + q.value + " 次（" + q.percent + "%）";
        }},
        series:[{type:"pie", roseType:"area", radius:["10%","78%"], center:["50%","52%"],
          itemStyle:{borderColor:"#fbfcfa", borderWidth:1.5, borderRadius:3},
          label:{show:true, fontSize:11, color:"#6b736d",
            formatter:function(q){ return q.name; }},
          labelLine:{length:4, length2:4},
          data:data}]
      });
    }
  });
})();

/* 《琵琶行》 */
(function(){
  var s = D.star.pipa;
  renderSegs(document.getElementById("pipaText"), s.segs);
  if (s.note) document.getElementById("pipaNote").textContent = s.note;
  var chips = document.getElementById("pipaChips");
  chips.appendChild(el("span", "mut", s.hits.length + " 种声音词 · 共 " + s.total + " 次："));
  s.hits.forEach(function(hn){ chips.appendChild(chipNode(hn[0], hn[1])); });
  var ul = document.getElementById("pipaFacts");
  s.facts.forEach(function(f){ ul.appendChild(el("li", "", f)); });
  var tbl = document.getElementById("rankTbl");
  var thead = el("tr");
  ["篇目","作者","命中","体裁"].forEach(function(t){ thead.appendChild(el("th","",t)); });
  tbl.appendChild(thead);
  D.topPoems.forEach(function(r){
    var tr = el("tr");
    tr.appendChild(el("td", "kai", "《" + r.title + "》"));
    tr.appendChild(el("td", "", r.poet));
    tr.appendChild(el("td", "", String(r.total)));
    var g = el("td", (r.genre === "散文" || r.genre === "骈文") ? "genre-prose" : "", r.genre);
    tr.appendChild(g);
    tbl.appendChild(tr);
  });
})();

/* 王维 */
(function(){
  var s = D.star.wangwei;
  document.getElementById("wwNote").textContent = s.note;
  var wrap = document.getElementById("wwCards");
  s.poems.forEach(function(p){
    var c = el("div", "pcard");
    var h = el("h4", "kai", "《" + p.title + "》");
    h.appendChild(el("span", "cnt", p.total + " 次命中"));
    c.appendChild(h);
    var body = el("div", "poem-body");
    renderSegs(body, p.segs);
    c.appendChild(body);
    if (p.note) c.appendChild(el("div", "pnote", p.note));
    wrap.appendChild(c);
  });
})();

/* 杜甫 vs 高适 */
(function(){
  var b = D.star.border;
  var grid = document.getElementById("borderGrid");
  [b.dufu, b.gaoshi].forEach(function(side){
    var col = el("div", "border-col");
    var h = el("h4", "", side.name); h.style.color = side.color;
    col.appendChild(h);
    col.appendChild(el("div", "sub-line", "本语料 " + side.poemCount + " 首 · " +
      side.chars + " 字 · 共 " + side.hits + " 次命中"));
    side.poems.forEach(function(p){
      var pc = el("div");
      pc.style.marginBottom = "10px";
      var t = el("div", "kai", "《" + p.title + "》 ");
      t.style.fontSize = "16px"; t.style.letterSpacing = ".08em";
      t.appendChild(el("span", "mut", p.total + " 次"));
      pc.appendChild(t);
      var body = el("div", "poem-box small");
      body.style.maxHeight = "180px"; body.style.overflowY = "auto";
      renderSegs(body, p.segs);
      pc.appendChild(body);
      if (p.note) pc.appendChild(el("div", "mut", p.note));
      col.appendChild(pc);
    });
    grid.appendChild(col);
  });
  var ul = document.getElementById("borderReading");
  b.reading.forEach(function(r){ ul.appendChild(el("li", "", r)); });
  var ch = mkChart(document.getElementById("dgChart"));
  if (ch){
    var cats = D.cats.map(function(c){ return c.name; });
    ch.setOption({
      textStyle: baseText,
      tooltip:{trigger:"axis"},
      legend:{top:0, textStyle:{color:"#252b27"}},
      grid:{left:8, right:16, top:36, bottom:8, containLabel:true},
      xAxis:{type:"category", data:cats,
        axisLabel:{fontFamily:"KaiTi,STKaiti,serif", fontSize:13},
        axisLine:{lineStyle:{color:"#c9cfc7"}}},
      yAxis:{type:"value", name:"命中次数", splitLine:{lineStyle:{color:"#e3e7e1"}},
        axisLabel:{color:"#6b736d"}},
      series:[
        {name:"杜甫（哭声与战鼓）", type:"bar", barWidth:"26%",
          itemStyle:{color:b.dufu.color, borderRadius:[3,3,0,0]},
          data:cats.map(function(c){ return b.dufu.cats[c]; })},
        {name:"高适（羌笛与钟鼓）", type:"bar", barWidth:"26%",
          itemStyle:{color:b.gaoshi.color, borderRadius:[3,3,0,0]},
          data:cats.map(function(c){ return b.gaoshi.cats[c]; })}
      ]
    });
  }
})();

/* 排除表 */
(function(){
  var tbl = document.getElementById("exclTbl");
  D.excludes.forEach(function(r){
    var tr = el("tr");
    tr.appendChild(el("td", "kai", r[0]));
    tr.appendChild(el("td", "", r[1]));
    tbl.appendChild(tr);
  });
})();

window.addEventListener("resize", function(){
  charts.forEach(function(c){ try{ c.resize(); }catch(e){} });
});
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
