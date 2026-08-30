# -*- coding: utf-8 -*-
"""viz_31 凝望罗盘 —— 唐宋诗词方位凝望的文本地理（数媒可视化参赛版 31 号页面）

产出：
  output/31_凝望罗盘.html
  output/assets/competition/gaze_data.json

口径（与页面"方法与数据"折叠区一致）：
1. 对 analysis_full 六位诗人全作品扫描凝望表达：
   - 方位凝望：[东南西北/四隅]+望、望+[方位]、南顾/北顾；
   - 无方向凝望：回望/怅望/遥望/极目，以及 望+宾语（宾语取望后1-3字，
     经 place_dict 269 条古地名与手工常见名词表最长匹配过滤）。
   - "相望/瞻望/希望"等非凝望搭配按前字黑名单排除；三顾/相顾不计入。
2. 每处命中记录所在句（以。！？；换行切句，句内以逗号顿号切分析单元），
   情感值 = 对所在句跑 spirit_image_dict 最长匹配命中词的情感均值；
   无命中记 0 并标"中性"。曲线与配色描述作品文本特征，不断言诗人真实心理。
3. 故都回望指数：编年取 data/candidates/*_spirit_chronology.csv；
   status=superseded_by_verified 者以 data/reviewed/verified_poem_contexts.csv
   同题记录覆盖（标"已审核"），其余标"候选/推定"徽章；fact_grade=D 或缺年
   不入比率计算，仅列出。
4. 地理验证：仅对"方位凝望 + 句内含 place_dict 地名 + 该诗有编年坐标"的
   样本计算创作地→目标地方位角（atan2，经度差按纬度余弦修正），与文本
   自述方向比对；其余样本方向为文本自述，未做地理验证。

零参数直接复跑：python 数据可视化脚本/viz_31_gaze_compass.py
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "data"))
sys.path.insert(0, ROOT)

import place_dict as PD  # noqa: E402
import spirit_image_dict as SD  # noqa: E402
from tools.famous_poet_corpus import load_analysis_poems  # noqa: E402

OUT_HTML = os.path.join(ROOT, "output", "31_凝望罗盘.html")
OUT_JSON = os.path.join(ROOT, "output", "assets", "competition", "gaze_data.json")

SIX = ["李白", "杜甫", "白居易", "苏轼", "陆游", "李清照"]
POET_COLOR = {
    "李白": "#426f94", "杜甫": "#7a5c3d", "白居易": "#26786e",
    "苏轼": "#b64b3f", "陆游": "#8a3b2f", "李清照": "#9c5d8f",
}
POET_KEY = {"李白": "libai", "杜甫": "dufu", "白居易": "baijuyi",
            "苏轼": "sushi", "陆游": "luyou", "李清照": "liqingzhao"}

DIR8 = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
DIR2 = {"东南", "西南", "东北", "西北"}
DIR1 = {"东", "西", "南", "北"}
SPECIAL_PREV = {"回": "回望", "怅": "怅望", "遥": "遥望"}
# 前字黑名单：这些搭配里的"望"不是诗人向外凝望
PREV_BLOCK = {"相", "瞻", "希", "愿", "名", "德", "声", "冀", "观"}
# 望的常见宾语名词表（place_dict 之外的手工补充，最长匹配）
GAZE_NOUNS = [
    "明月", "残月", "秋月", "山月", "海月", "月", "故乡", "故园", "乡关", "乡国", "乡",
    "故国", "故都", "旧京", "神州", "中原", "中州", "帝京", "帝阙", "京华", "京国",
    "京阙", "王师", "美人", "人寰", "都门", "边邑", "行人", "青天", "天涯", "天门",
    "天", "云海", "白云", "孤云", "云", "雪山", "远山", "山", "沧海", "海", "大江",
    "江", "烽火", "关山", "陵阙", "翠微", "斗牛", "帝乡",
]
# 词牌名含"望"的，诗题扫描时排除
TITLE_CIPAI_BLOCK = ("望江南", "望海潮", "望远行", "望仙门", "望江东", "望梅花")
# 故都类词（口径固定；"京华"因在南宋常指行在临安、语义两可，不计入，见方法区）
GUDU_TERMS = ["汴京", "汴梁", "中州", "中原", "神州", "故国", "故都", "旧京", "旧都"]
# 地理验证：place_dict 之外的目标地补充映射（仅用于方位角计算）
GEO_EXTRA = {"都门": ("长安城门(今西安)", 108.95, 34.27)}

PLACE_ALIASES = set(PD.aliases())
OBJ_WORDS = sorted(PLACE_ALIASES | set(GAZE_NOUNS), key=len, reverse=True)
SPIRIT_WORDS = SD.words()  # 已按长度降序
SPIRIT_COUNT = len(SD.SPIRIT_DICT)

CJK = re.compile(r"[一-鿿]")
CORPUS_PATH = "data/analysis/famous_poets_full.jsonl.gz"
CANONICAL_PATH = "data/poems.json"


def cjk_len(text: str) -> int:
    return len(CJK.findall(text))


def split_sentences(body: str):
    for chunk in re.split(r"[\n。！？；]", body):
        chunk = chunk.strip()
        if chunk:
            yield chunk


def split_units(sentence: str):
    return [u for u in re.split(r"[，、：,]", sentence) if u]


def sentiment_of(sentence: str):
    """spirit_image_dict 最长匹配（不重叠），返回 (均值, 命中列表)。"""
    used = [False] * len(sentence)
    hits = []
    for w in SPIRIT_WORDS:
        start = 0
        while True:
            i = sentence.find(w, start)
            if i < 0:
                break
            span = range(i, i + len(w))
            if not any(used[j] for j in span):
                for j in span:
                    used[j] = True
                info = SD.lookup(w)
                hits.append({"word": w, "sentiment": info["sentiment"],
                             "cluster": info["cluster"]})
            start = i + 1
    if not hits:
        return 0.0, []
    mean = sum(h["sentiment"] for h in hits) / len(hits)
    return round(mean, 3), hits


def match_object(after: str):
    for L in (3, 2, 1):
        w = after[:L]
        if not w:
            continue
        if w in PLACE_ALIASES or w in GAZE_NOUNS:
            return w
    return None


def extract_from_text(text: str, source: str):
    """从一段文本（诗身或诗题）抽取凝望命中。返回命中 dict 列表（不含诗信息）。"""
    out = []
    for sent in split_sentences(text):
        for unit in split_units(sent):
            # 极目
            for m in re.finditer("极目", unit):
                obj = match_object(unit[m.end():m.end() + 3])
                out.append(dict(sentence=sent, unit=unit, verb="极目",
                                direction=None, obj=obj, source=source))
            # 望 / 顾
            for m in re.finditer("[望顾]", unit):
                i = m.start()
                ch = m.group()
                prev = unit[i - 1] if i >= 1 else ""
                prev2 = unit[i - 2:i] if i >= 2 else ""
                if ch == "顾":
                    if prev and prev in {"南", "北"}:
                        out.append(dict(sentence=sent, unit=unit, verb=prev + "顾",
                                        direction=prev, obj=None, source=source))
                    continue
                if prev and prev in PREV_BLOCK:
                    continue
                direction = None
                verb = None
                if prev2 and prev2 in DIR2:
                    direction, verb = prev2, prev2 + "望"
                elif prev and prev in DIR1:
                    direction, verb = prev, prev + "望"
                elif prev and prev in SPECIAL_PREV:
                    verb = SPECIAL_PREV[prev]
                after = unit[i + 1:i + 4]
                obj = match_object(after)
                if direction is None and obj is None and after[:1] and after[:1] in DIR1:
                    d2 = after[:2]
                    direction = d2 if d2 in DIR2 else after[:1]
                    verb = "望" + direction
                if direction is None and verb is None and obj is None:
                    continue
                if verb is None:
                    verb = "望" + (obj or "")
                out.append(dict(sentence=sent, unit=unit, verb=verb,
                                direction=direction, obj=obj, source=source))
    return out


def index_exact_canonical_by_title(poems):
    """仅返回诗人/诗题下唯一的 exact canonical 行；歧义题不挂事实。"""
    grouped = defaultdict(list)
    for poem in poems:
        if poem.get("canonical_match") and poem.get("canonical_gushiwen_id"):
            grouped[(poem["poet"], poem["title"])].append(poem)
    return {key: rows[0] for key, rows in grouped.items() if len(rows) == 1}


def load_chronology(poems_by_key):
    """六人编年：candidates CSV + verified 覆盖。返回 poet -> [row]。"""
    verified = {}
    vpath = os.path.join(ROOT, "data", "reviewed", "verified_poem_contexts.csv")
    with open(vpath, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            verified[(r["poet"], r["title"])] = r
    chron = defaultdict(list)
    for poet, key in POET_KEY.items():
        path = os.path.join(ROOT, "data", "candidates", f"{key}_spirit_chronology.csv")
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                row = dict(
                    poet=poet, title=r["title"], period=r["period"].strip(),
                    year_start=r["year_start"].strip(), year_end=r["year_end"].strip(),
                    fact_grade=r["fact_grade"].strip() or "D",
                    status=r["status"].strip(),
                    lon=r["lon"].strip(), lat=r["lat"].strip(),
                    modern_city=r["modern_city"].strip(),
                    source_name=r["source_name"].strip(),
                    source_note=r["source_note"].strip(),
                )
                v = verified.get((poet, r["title"]))
                if row["status"] == "superseded_by_verified" and v:
                    row.update(year_start=v["year_start"].strip() or row["year_start"],
                               year_end=v["year_end"].strip() or row["year_end"],
                               lon=v["lon"].strip() or row["lon"],
                               lat=v["lat"].strip() or row["lat"],
                               modern_city=v["modern_city"].strip() or row["modern_city"],
                               fact_grade=v["fact_grade"].strip() or row["fact_grade"],
                               status="verified",
                               source_name=v["source_name"].strip() or row["source_name"])
                canonical = poems_by_key.get((poet, r["title"]))
                row["body"] = canonical.get("body", "") if canonical else ""
                row["work_id"] = canonical.get("work_id") if canonical else None
                row["canonical_gushiwen_id"] = (
                    canonical.get("canonical_gushiwen_id") if canonical else None
                )
                row["body_hash"] = canonical.get("body_hash", "") if canonical else ""
                row["canonical_match"] = bool(canonical)
                chron[poet].append(row)
    return chron


def badge_of(row):
    if row["status"] == "verified":
        return "verified"
    return "candidate"


def bearing_dir8(lon0, lat0, lon1, lat1):
    """创作地(0)→目标地(1) 的 8 方位。经度差按纬度余弦修正。"""
    east = (lon1 - lon0) * math.cos(math.radians((lat0 + lat1) / 2))
    north = lat1 - lat0
    ang = math.degrees(math.atan2(east, north)) % 360  # 0=北 顺时针
    idx = int(((ang + 22.5) % 360) // 45)
    return DIR8[idx], round(ang, 1)


def main():
    poems, corpus_source = load_analysis_poems(fallback=False)
    poems = [p for p in poems if p["poet"] in SIX]
    poems_by_key = index_exact_canonical_by_title(poems)
    six_counts = Counter(p["poet"] for p in poems)

    # ---------- 1. 全语料凝望扫描 ----------
    all_hits = []
    seen_clause = set()  # 同一稳定作品内的同句同动词去重
    for p in poems:
        for h in extract_from_text(p["body"], "body"):
            key = (p["work_id"], h["sentence"], h["verb"])
            if key in seen_clause:
                continue
            seen_clause.add(key)
            senti, words = sentiment_of(h["sentence"])
            all_hits.append(dict(
                poet=p["poet"], title=p["title"], dynasty=p["dynasty"],
                work_id=p["work_id"], body_hash=p.get("body_hash", ""),
                canonical_gushiwen_id=p.get("canonical_gushiwen_id"),
                canonical_match=bool(p.get("canonical_match")),
                sentence=h["sentence"], unit=h["unit"], verb=h["verb"],
                direction=h["direction"],
                obj=h["obj"], sentiment=senti, neutral=(not words),
                spirit_words=words, source_url=p.get("source_url", ""),
            ))
    # 六人诗题之望（词牌名排除）
    title_gazes = defaultdict(list)
    for p in poems:
        if any(p["title"].startswith(c) for c in TITLE_CIPAI_BLOCK):
            continue
        if "望" in p["title"]:
            title_gazes[p["poet"]].append(p["title"])

    dir_hits = [h for h in all_hits if h["direction"]]
    nodir_hits = [h for h in all_hits if not h["direction"]]
    corpus_dir_count = Counter(h["direction"] for h in dir_hits)
    corpus_dir_senti = {d: round(sum(h["sentiment"] for h in dir_hits if h["direction"] == d)
                                 / max(1, corpus_dir_count[d]), 3) for d in DIR8}
    corpus_top_dir = max(DIR8, key=lambda d: corpus_dir_count.get(d, 0))

    # 六人汇总
    poet_summary = {}
    for poet in SIX:
        ph = [h for h in all_hits if h["poet"] == poet]
        pd_ = [h for h in ph if h["direction"]]
        pn = [h for h in ph if not h["direction"]]
        dc = Counter(h["direction"] for h in pd_)
        ds = {d: round(sum(h["sentiment"] for h in pd_ if h["direction"] == d)
                       / max(1, dc[d]), 3) for d in DIR8 if dc.get(d)}
        objs = Counter((h["obj"] or h["verb"]) for h in pn)
        top_dir = max(dc, key=dc.get) if dc else None
        if top_dir:
            top_n = dc[top_dir]
            tops = [d for d in DIR8 if dc.get(d) == top_n]
            best = max(pd_, key=lambda h: (h["direction"] == top_dir, -abs(h["sentiment"])))
            if len(tops) > 1:
                head = (f"方位凝望 {len(pd_)} 处，方向分散：{'、'.join(tops)} 各 {top_n} 次"
                        f"，如《{best['title']}》「{best['unit']}」")
            else:
                head = (f"方位凝望 {len(pd_)} 处，最强方向为「{top_dir}」（{top_n} 次）"
                        f"，如《{best['title']}》「{best['unit']}」")
        elif pn:
            to = objs.most_common(1)[0]
            head = f"现存语料未见方位凝望，{len(pn)} 处凝望皆落在对象上（最常见：{to[0]}）"
        else:
            head = "现存语料（本库收录范围内）未检出任何凝望表达"
        if title_gazes.get(poet):
            head += f"；诗题之望 {len(title_gazes[poet])} 首"
        poet_summary[poet] = dict(
            color=POET_COLOR[poet], n_dir=len(pd_), n_nodir=len(pn),
            dir_count={d: dc.get(d, 0) for d in DIR8},
            dir_senti=ds, headline=head,
            title_gazes=title_gazes.get(poet, []),
            hits=ph,
        )

    # ---------- 2. 编年与故都回望指数 ----------
    chron = load_chronology(poems_by_key)

    def rate_block(rows, terms):
        """rows -> {rate, chars, hits:[{title,term,count,sentence,...}], poems:[...]}"""
        total_chars = 0
        term_hits = []
        poem_list = []
        for r in rows:
            body = r["body"]
            chars = cjk_len(body)
            total_chars += chars
            cnt = 0
            for t in terms:
                c = body.count(t)
                if c:
                    cnt += c
                    for sent in split_sentences(body):
                        if t in sent:
                            term_hits.append(dict(title=r["title"], term=t,
                                                  sentence=sent, year=r["year_start"],
                                                  grade=r["fact_grade"], badge=badge_of(r),
                                                  source=r["source_name"]))
                            break
            poem_list.append(dict(title=r["title"], year=r["year_start"],
                                  grade=r["fact_grade"], badge=badge_of(r),
                                  chars=chars, term_count=cnt))
        rate = (sum(p["term_count"] for p in poem_list) / total_chars * 100) if total_chars else 0.0
        return dict(rate=round(rate, 3), chars=total_chars,
                    n_poems=len(rows), hits=term_hits, poems=poem_list)

    def usable(rows):
        ok = [r for r in rows if r["fact_grade"] != "D" and r["year_start"] and r["body"]]
        dropped = [dict(title=r["title"], grade=r["fact_grade"], status=r["status"],
                        reason=("fact_grade=D" if r["fact_grade"] == "D" else
                                ("缺系年" if not r["year_start"] else "语料缺文本")))
                   for r in rows if r not in ok]
        return ok, dropped

    # 李清照：南渡(1127)前后
    lqz_ok, lqz_drop = usable(chron["李清照"])
    lqz_pre = rate_block([r for r in lqz_ok if int(r["year_start"]) <= 1126], GUDU_TERMS)
    lqz_post = rate_block([r for r in lqz_ok if int(r["year_start"]) >= 1127], GUDU_TERMS)

    # 陆游：生于1125，全部作品在南渡后 → 按四分期
    ly_ok, ly_drop = usable(chron["陆游"])
    with open(os.path.join(ROOT, "data", "candidates", "luyou_life_stages.json"),
              encoding="utf-8") as f:
        ly_stages = json.load(f)["stages"]
    ly_stage_label = {str(s["index"]): f"{s['label']}（{s['year_start']}–{s['year_end']}）"
                      for s in ly_stages}
    ly_periods = []
    for idx in sorted({r["period"] for r in ly_ok if r["period"]}):
        rows = [r for r in ly_ok if r["period"] == idx]
        blk = rate_block(rows, GUDU_TERMS)
        blk["label"] = ly_stage_label.get(idx, f"第{idx}期")
        blk["period"] = idx
        ly_periods.append(blk)

    # 李白：五分期 长安 提及率
    LB_STAGE = {"1": "蜀中读书（~725）", "2": "干谒漫游（726–741）", "3": "长安翰林（742–744）",
                "4": "再漫游·安史（744–756）", "5": "永王案·流放·暮年（757–762）"}
    lb_ok, lb_drop = usable(chron["李白"])
    lb_periods = []
    for idx in ["1", "2", "3", "4", "5"]:
        rows = [r for r in lb_ok if r["period"] == idx]
        blk = rate_block(rows, ["长安"])
        blk["label"] = LB_STAGE[idx]
        blk["period"] = idx
        lb_periods.append(blk)
    lb_all_changan = sum(p["body"].count("长安") for p in poems if p["poet"] == "李白")
    lb_all_titles = sorted({p["title"] for p in poems
                            if p["poet"] == "李白" and "长安" in p["body"]})

    # ---------- 3. 地理验证 ----------
    geo_cases = []
    chron_lookup = {}
    for poet in SIX:
        for r in chron[poet]:
            if r["lon"] and r["lat"]:
                if r["canonical_gushiwen_id"]:
                    chron_lookup[r["canonical_gushiwen_id"]] = r
    for h in dir_hits:
        if h["poet"] not in SIX:
            continue
        if not h["canonical_match"]:
            continue
        r = chron_lookup.get(h["canonical_gushiwen_id"])
        if not r:
            continue
        # 目标地：直接宾语为地名，否则在含凝望动词的分析单元内扫 place_dict / 补充映射
        unit = h.get("unit") or h["sentence"]
        target = None
        if h["obj"] and (h["obj"] in PLACE_ALIASES or h["obj"] in GEO_EXTRA):
            target = h["obj"]
        else:
            scan = unit
            for w in OBJ_WORDS:
                if w in scan and (w in PLACE_ALIASES or w in GEO_EXTRA):
                    target = w
                    break
        if not target:
            continue
        if target in GEO_EXTRA:
            tname, tlon, tlat = GEO_EXTRA[target]
        else:
            info = PD.lookup(target)
            tname, tlon, tlat = f"{target}→今{info['modern']}", info["lon"], info["lat"]
        lon0, lat0 = float(r["lon"]), float(r["lat"])
        sector, ang = bearing_dir8(lon0, lat0, tlon, tlat)
        claimed = h["direction"]
        match = (claimed == sector) or (len(claimed) == 1 and claimed in sector)
        geo_cases.append(dict(
            poet=h["poet"], title=h["title"], sentence=h["sentence"], verb=h["verb"],
            work_id=h["work_id"], body_hash=h["body_hash"],
            canonical_gushiwen_id=h["canonical_gushiwen_id"], canonical_match=True,
            claimed=claimed, place_from=f"{r['modern_city']}", from_badge=badge_of(r),
            from_grade=r["fact_grade"], year=r["year_start"],
            target=target, target_mapped=tname, computed=sector, angle=ang,
            match=bool(match),
        ))
    geo_rate = (sum(1 for c in geo_cases if c["match"]) / len(geo_cases) * 100) if geo_cases else None

    # ---------- 4. 数据落盘 ----------
    payload = dict(
        generated_by="viz_31_gaze_compass.py",
        corpus_source=corpus_source,
        corpus_path=CORPUS_PATH if corpus_source == "analysis_full" else CANONICAL_PATH,
        analysis_count=len(poems),
        canonical_evidence_count=sum(1 for hit in all_hits if hit["canonical_match"]),
        corpus=dict(n_poems=len(poems), n_poets=len({p["poet"] for p in poems}),
                    six_counts={p: six_counts[p] for p in SIX},
                    n_hits=len(all_hits), n_dir=len(dir_hits),
                    n_nodir=len(nodir_hits), dir_count={d: corpus_dir_count.get(d, 0) for d in DIR8},
                    dir_senti=corpus_dir_senti, top_dir=corpus_top_dir,
                    n_poets_hit=len({h['poet'] for h in all_hits}),
                    n_poems_hit=len({(h['poet'], h['title']) for h in all_hits})),
        hits=all_hits,
        poets=poet_summary,
        gudu=dict(terms=GUDU_TERMS,
                  liqingzhao=dict(pre=lqz_pre, post=lqz_post, dropped=lqz_drop),
                  luyou=dict(periods=ly_periods, dropped=ly_drop),
                  libai=dict(periods=lb_periods, dropped=lb_drop,
                             all_changan=lb_all_changan, all_titles=lb_all_titles)),
        geo=dict(cases=geo_cases, match_rate=geo_rate),
    )
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, allow_nan=False, indent=1)

    # ---------- 5. 渲染 HTML ----------
    html = render_html(payload)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    # 自检
    with open(OUT_HTML, encoding="utf-8") as f:
        txt = f.read()
    assert not re.search(r'<script[^>]+src\s*=\s*["\']http', txt), "禁止远程 script"
    for bad in ("NaN", "Infinity"):
        assert bad not in txt, f"页面字面出现 {bad}"
    assert 'name="viewport"' in txt, "缺 viewport"
    assert os.path.getsize(OUT_HTML) >= 5000, "体积不足 5000 字节"
    print("[ok] saved", OUT_JSON)
    print("[ok] saved", OUT_HTML)


# ============================================================ HTML
def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def badge_html(kind, grade=None):
    if kind == "verified":
        b = '<span class="badge b-ver">已审核</span>'
    else:
        b = '<span class="badge b-cand">候选/推定</span>'
    if grade:
        b += f'<span class="badge b-grade">{esc(grade)} 级</span>'
    return b


def bar_row(label, rate, max_rate, color, sub, detail_id=None):
    w = 0 if max_rate <= 0 else max(2, round(rate / max_rate * 100))
    btn = f'<button class="ev-toggle" data-target="{detail_id}">证据</button>' if detail_id else ""
    return f"""
<div class="bar-row">
  <div class="bar-label">{label}</div>
  <div class="bar-track"><div class="bar-fill" style="width:{w}%;background:{color}"></div>
    <span class="bar-val">{rate:.3f}</span></div>
  <div class="bar-sub">{sub} {btn}</div>
</div>"""


def evidence_items(hits):
    if not hits:
        return '<p class="muted">该组内未命中任何故都类词。</p>'
    out = []
    for h in hits:
        out.append(
            f'<div class="ev-item"><div class="ev-sent">{esc(h["sentence"])}</div>'
            f'<div class="ev-meta">《{esc(h["title"])}》 · 命中「{esc(h["term"])}」 · '
            f'系年 {esc(h["year"])} {badge_html(h["badge"], h["grade"])} · 来源：{esc(h["source"] or "见编年CSV")}</div></div>')
    return "".join(out)


def poem_table(poems_):
    rows = "".join(
        f'<tr><td>《{esc(p["title"])}》</td><td>{esc(p["year"])}</td>'
        f'<td>{badge_html(p["badge"], p["grade"])}</td>'
        f'<td>{p["chars"]}</td><td>{p["term_count"]}</td></tr>' for p in poems_)
    return ('<div class="tbl-wrap"><table><thead><tr><th>诗</th><th>系年</th><th>等级</th>'
            '<th>正文字数</th><th>命中次数</th></tr></thead><tbody>' + rows +
            "</tbody></table></div>")


def render_html(data):
    c = data["corpus"]
    g = data["gudu"]
    geo = data["geo"]

    # ---- 六人卡片 ----
    poet_cards = []
    for poet in SIX:
        ps = data["poets"][poet]
        color = ps["color"]
        chart = (f'<div class="rose" id="rose_{POET_KEY[poet]}"></div>' if ps["n_dir"]
                 else '<div class="rose empty"><div>—</div><p>此语料内无方位凝望命中<br>'
                      '（收录范围所限，非诗人全集结论）</p></div>')
        chips = []
        nodir = [h for h in ps["hits"] if not h["direction"]]
        seen = set()
        for h in nodir:
            lab = h["obj"] and ("望·" + h["obj"]) or h["verb"]
            if lab in seen:
                continue
            seen.add(lab)
            chips.append(f'<span class="chip">{esc(lab)}</span>')
        tg = ""
        if ps["title_gazes"]:
            tg = ('<p class="tgaze">诗题之望：' +
                  "、".join(f"《{esc(t)}》" for t in ps["title_gazes"]) + "</p>")
        poet_cards.append(f"""
<article class="poet-card" style="--pc:{color}">
  <h3><span class="dot"></span>{poet}</h3>
  <p class="headline">{esc(ps["headline"])}。</p>
  {chart}
  <div class="chips">{''.join(chips) or '<span class="muted">无「无方向凝望」命中</span>'}</div>
  {tg}
  <div class="ev-panel" id="ev_{POET_KEY[poet]}"><p class="muted">点击玫瑰图扇区或上方词条查看证据句。</p></div>
</article>""")

    # ---- 故都回望 ----
    lqz = g["liqingzhao"]
    max_r = max(lqz["pre"]["rate"], lqz["post"]["rate"], 0.001)
    lqz_bars = (
        bar_row("南渡前（≤1126）", lqz["pre"]["rate"], max_r, "#9c5d8f",
                f'{lqz["pre"]["n_poems"]} 首编年词 · {lqz["pre"]["chars"]} 字 · 命中 {sum(p["term_count"] for p in lqz["pre"]["poems"])} 次',
                "d_lqz_pre") +
        bar_row("南渡后（≥1127）", lqz["post"]["rate"], max_r, "#9c5d8f",
                f'{lqz["post"]["n_poems"]} 首编年词 · {lqz["post"]["chars"]} 字 · 命中 {sum(p["term_count"] for p in lqz["post"]["poems"])} 次',
                "d_lqz_post"))
    lqz_detail = (f'<div class="ev-detail" id="d_lqz_pre" hidden><h5>南渡前证据与入组诗目</h5>'
                  f'{evidence_items(lqz["pre"]["hits"])}{poem_table(lqz["pre"]["poems"])}</div>'
                  f'<div class="ev-detail" id="d_lqz_post" hidden><h5>南渡后证据与入组诗目</h5>'
                  f'{evidence_items(lqz["post"]["hits"])}{poem_table(lqz["post"]["poems"])}</div>')
    lqz_drop_note = ""
    if lqz["dropped"]:
        items = "、".join(f'《{esc(d["title"])}》（{esc(d["reason"])}）' for d in lqz["dropped"])
        lqz_drop_note = f'<p class="drop-note">不入比率、仅列出：{items}。</p>'

    ly = g["luyou"]
    ly_max = max([p["rate"] for p in ly["periods"]] + [0.001])
    ly_bars = "".join(
        bar_row(esc(p["label"]), p["rate"], ly_max, "#8a3b2f",
                f'{p["n_poems"]} 首 · {p["chars"]} 字 · 命中 {sum(x["term_count"] for x in p["poems"])} 次',
                f'd_ly_{p["period"]}') for p in ly["periods"])
    ly_details = "".join(
        f'<div class="ev-detail" id="d_ly_{p["period"]}" hidden><h5>{esc(p["label"])}</h5>'
        f'{evidence_items(p["hits"])}{poem_table(p["poems"])}</div>' for p in ly["periods"])
    ly_drop_note = ""
    if ly["dropped"]:
        items = "、".join(f'《{esc(d["title"])}》（{esc(d["reason"])}）' for d in ly["dropped"])
        ly_drop_note = f'<p class="drop-note">不入比率、仅列出：{items}。</p>'

    lb = g["libai"]
    lb_max = max([p["rate"] for p in lb["periods"]] + [0.001])
    lb_bars = "".join(
        bar_row(esc(p["label"]), p["rate"], lb_max, "#426f94",
                (f'{p["n_poems"]} 首 · {p["chars"]} 字 · 命中 {sum(x["term_count"] for x in p["poems"])} 次'
                 if p["n_poems"] else "此期无编年诗入组"),
                f'd_lb_{p["period"]}' if p["n_poems"] else None) for p in lb["periods"])
    lb_details = "".join(
        f'<div class="ev-detail" id="d_lb_{p["period"]}" hidden><h5>{esc(p["label"])}</h5>'
        f'{evidence_items(p["hits"])}{poem_table(p["poems"])}</div>'
        for p in lb["periods"] if p["n_poems"])
    lb_all_note = (f'补充口径：李白在本库全部 {c["six_counts"]["李白"]} 首（含未编年者）中，「长安」字面共出现 '
                   f'{lb["all_changan"]} 次（{ "、".join("《"+esc(t)+"》" for t in lb["all_titles"]) or "无"}）。')

    # ---- 地理验证 ----
    if geo["cases"]:
        rows = "".join(
            f'<tr><td>{esc(x["poet"])}</td><td>《{esc(x["title"])}》</td>'
            f'<td class="sent-cell">{esc(x["sentence"])}</td><td>{esc(x["claimed"])}</td>'
            f'<td>{esc(x["place_from"])}（{esc(x["year"])}，{ "已审核" if x["from_badge"]=="verified" else "候选"}·{esc(x["from_grade"])}级）</td>'
            f'<td>{esc(x["target_mapped"])}</td><td>{esc(x["computed"])}（{x["angle"]}°）</td>'
            f'<td>{"吻合" if x["match"] else "不吻合"}</td></tr>'
            for x in geo["cases"])
        geo_html = f"""
<p>对「方位凝望 + 句内含可定位地名 + 该诗有编年坐标」的 {len(geo["cases"])} 个样本，
以创作地→目标地方位角（atan2，经度差按纬度余弦修正）比对文本自述方向，
<strong>吻合率 {geo["match_rate"]:.0f}%</strong>（单字方向落入相邻 45° 扇区计吻合）。</p>
<div class="tbl-wrap"><table><thead><tr><th>诗人</th><th>诗</th><th>句</th><th>自述</th>
<th>创作地（编年）</th><th>目标地（映射）</th><th>计算方位</th><th>判定</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<p class="drop-note">判读注意：①古今地名映射会造成误判——《赤壁赋》"东望武昌"之武昌为今鄂州
（在黄州东南），place_dict 映射到今武汉则算出偏西，故该条"不吻合"是映射误差而非苏轼说错方向；
②凝望主语未必是诗人本人——《长恨歌》"东望都门"的主语是还京的玄宗一行（自周至东望长安，方位恰吻合），
《秋夜将晓》"南望王师"的主语是中原遗民；③其余未列样本的方向均为文本自述，未做地理验证。</p>"""
    else:
        geo_html = '<p>本次无满足条件的可验证样本：方向为文本自述，未做地理验证。</p>'

    data_json = json.dumps(
        dict(corpus=c, poets={p: {k: v for k, v in data["poets"][p].items()}
                              for p in SIX}, dir8=DIR8,
             dir_hits=[h for h in data["hits"] if h["direction"]]),
        ensure_ascii=False, allow_nan=False)

    tpl = HTML_TPL
    tpl = tpl.replace("__DATA__", data_json)
    tpl = tpl.replace("__N_HITS__", str(c["n_hits"]))
    tpl = tpl.replace("__N_DIR__", str(c["n_dir"]))
    tpl = tpl.replace("__N_NODIR__", str(c["n_nodir"]))
    tpl = tpl.replace("__N_POEMS_HIT__", str(c["n_poems_hit"]))
    tpl = tpl.replace("__N_POETS_HIT__", str(c["n_poets_hit"]))
    tpl = tpl.replace("__TOP_DIR__", esc(c["top_dir"]))
    tpl = tpl.replace("__TOP_DIR_N__", str(c["dir_count"][c["top_dir"]]))
    tpl = tpl.replace("__N_CORPUS__", str(c["n_poems"]))
    tpl = tpl.replace("__N_CORPUS_POETS__", str(c["n_poets"]))
    tpl = tpl.replace("__SPIRIT_COUNT__", str(SPIRIT_COUNT))
    tpl = tpl.replace("__SIX_COUNTS__", "、".join(f"{p} {c['six_counts'][p]} 首" for p in SIX))
    six_values = list(c["six_counts"].values())
    tpl = tpl.replace("__SIX_RANGE__", f"{min(six_values)}–{max(six_values)}")
    tpl = tpl.replace("__POET_CARDS__", "".join(poet_cards))
    tpl = tpl.replace("__LQZ_BARS__", lqz_bars)
    tpl = tpl.replace("__LQZ_DETAIL__", lqz_detail + lqz_drop_note)
    tpl = tpl.replace("__LY_BARS__", ly_bars)
    tpl = tpl.replace("__LY_DETAIL__", ly_details + ly_drop_note)
    tpl = tpl.replace("__LB_BARS__", lb_bars)
    tpl = tpl.replace("__LB_DETAIL__", lb_details)
    tpl = tpl.replace("__LB_ALL_NOTE__", lb_all_note)
    tpl = tpl.replace("__GEO__", geo_html)
    tpl = tpl.replace("__GUDU_TERMS__", "、".join(GUDU_TERMS))
    return tpl


HTML_TPL = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>31 · 凝望罗盘 —— 唐宋诗词方位凝望的文本地理</title>
<link rel="icon" href="data:,">
<script src="assets/pyecharts/v6/echarts.min.js"></script>
<style>
:root{
  --paper:#f2f4f0; --surface:#ffffff; --surface-soft:#f8f8f5;
  --ink:#252b27; --muted:#6f756f; --line:#d9ddd7; --line-strong:#b9c0b8;
  --cinnabar:#b64b3f; --jade:#26786e; --gold:#a87527; --blue:#426f94;
  --radius:6px; --shadow:0 10px 30px rgba(33,39,35,.07);
}
*{box-sizing:border-box}
body{
  margin:0; color:var(--ink);
  font-family:"Microsoft YaHei","PingFang SC","Segoe UI",sans-serif;
  background:
    linear-gradient(rgba(49,57,51,.025) 1px,transparent 1px),
    linear-gradient(90deg,rgba(49,57,51,.025) 1px,transparent 1px),
    var(--paper);
  background-size:24px 24px; line-height:1.7;
}
.wrap{max-width:1180px;margin:0 auto;padding:26px 18px 60px}
header.page{display:flex;gap:16px;align-items:flex-start;border-bottom:2px solid var(--ink);padding-bottom:18px;margin-bottom:8px}
.seal{width:52px;height:52px;flex:0 0 auto;display:grid;place-items:center;color:#fff;
  font-family:"STKaiti","KaiTi",serif;font-size:30px;background:var(--cinnabar);
  border:1px solid #ce7166;border-radius:6px}
h1{margin:0;font-family:"STKaiti","KaiTi",serif;font-size:clamp(26px,4vw,38px);letter-spacing:2px}
.sub{color:var(--muted);font-size:13px;margin-top:4px}
.crumb{margin-left:auto;color:var(--muted);font-size:12px;white-space:nowrap;padding-top:6px}
.crumb b{color:var(--cinnabar)}
@media(max-width:640px){
  header.page{flex-wrap:wrap}
  .crumb{margin-left:0;order:3;width:100%;padding-top:0}
  h1{letter-spacing:1px}
}
section{margin-top:34px}
h2{font-family:"STKaiti","KaiTi",serif;font-size:24px;margin:0 0 6px;border-left:5px solid var(--cinnabar);padding-left:12px}
h2 .en{font-size:12px;color:var(--muted);font-family:Georgia,serif;letter-spacing:1px;margin-left:8px}
.lead{color:var(--muted);font-size:14px;max-width:72em;margin:6px 0 16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:14px 0}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:12px 14px}
.tile .num{font-family:Georgia,serif;font-size:26px;font-weight:700;color:var(--cinnabar)}
.tile .lab{font-size:12px;color:var(--muted)}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:18px}
.compass-grid{display:grid;grid-template-columns:minmax(280px,460px) 1fr;gap:18px;align-items:start}
@media(max-width:860px){.compass-grid{grid-template-columns:1fr}}
#corpusRose{width:100%;height:360px}
.legend-sent{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-top:6px}
.legend-sent i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:4px;vertical-align:-1px}
.poets{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
.poet-card{background:var(--surface);border:1px solid var(--line);border-top:3px solid var(--pc);
  border-radius:var(--radius);box-shadow:var(--shadow);padding:16px}
.poet-card h3{margin:0 0 6px;font-family:"STKaiti","KaiTi",serif;font-size:21px}
.poet-card .dot{display:inline-block;width:12px;height:12px;border-radius:50%;background:var(--pc);margin-right:8px}
.headline{font-size:13px;color:var(--muted);min-height:3em}
.rose{width:100%;height:250px}
.rose.empty{display:grid;place-items:center;background:var(--surface-soft);
  border:1px dashed var(--line-strong);border-radius:var(--radius);color:var(--muted);
  text-align:center;font-size:12px;padding:10px}
.rose.empty div{font-size:30px;color:var(--line-strong)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.chip{font-size:12px;background:var(--surface-soft);border:1px solid var(--line);
  border-radius:20px;padding:2px 10px;cursor:pointer}
.chip:hover{border-color:var(--pc);color:var(--pc)}
.tgaze{font-size:12px;color:var(--muted);margin:8px 0 0}
.ev-panel{margin-top:10px;border-top:1px dashed var(--line);padding-top:8px;max-height:260px;overflow:auto}
.ev-item{padding:8px 10px;border-left:3px solid var(--line-strong);background:var(--surface-soft);
  border-radius:4px;margin-bottom:8px}
.ev-item.neg{border-left-color:var(--cinnabar)}
.ev-item.pos{border-left-color:var(--jade)}
.ev-sent{font-family:"STKaiti","KaiTi",serif;font-size:16px}
.ev-sent mark{background:#f3e5e1;color:var(--cinnabar);padding:0 2px;border-radius:2px}
.ev-meta{font-size:11px;color:var(--muted);margin-top:3px}
.muted{color:var(--muted);font-size:12px}
.badge{display:inline-block;font-size:10px;line-height:1;padding:3px 7px;border-radius:3px;
  margin:0 3px;vertical-align:1px;border:1px solid transparent}
.b-cand{color:var(--gold);border-color:var(--gold);background:#f7f1e4}
.b-ver{color:var(--jade);border-color:var(--jade);background:#e2efec}
.b-grade{color:var(--muted);border-color:var(--line-strong);background:var(--surface-soft)}
.case{margin-top:18px;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:18px}
.case h3{margin:0 0 4px;font-family:"STKaiti","KaiTi",serif;font-size:20px}
.case .note{font-size:12.5px;color:var(--muted);margin:2px 0 12px}
.bar-row{display:grid;grid-template-columns:minmax(120px,220px) 1fr;gap:8px 14px;align-items:center;margin:10px 0}
.bar-label{font-size:13px;text-align:right}
.bar-track{position:relative;height:22px;background:var(--surface-soft);border:1px solid var(--line);border-radius:4px;overflow:hidden}
.bar-fill{height:100%;border-radius:3px 0 0 3px;opacity:.85}
.bar-val{position:absolute;right:8px;top:0;line-height:22px;font-family:Georgia,serif;font-size:12px;font-weight:700}
.bar-sub{grid-column:2;font-size:11.5px;color:var(--muted);margin-top:-6px}
@media(max-width:560px){.bar-row{grid-template-columns:1fr}.bar-label{text-align:left}.bar-sub{grid-column:1}}
.ev-toggle{font:inherit;font-size:11px;color:var(--blue);background:none;border:1px solid var(--line);
  border-radius:3px;padding:1px 8px;cursor:pointer}
.ev-toggle:hover{border-color:var(--blue)}
.ev-detail{margin:10px 0;padding:12px;background:var(--surface-soft);border:1px dashed var(--line-strong);border-radius:4px}
.ev-detail h5{margin:0 0 8px;font-size:13px}
.tbl-wrap{overflow-x:auto;margin-top:10px}
table{border-collapse:collapse;font-size:12.5px;min-width:520px;width:100%}
th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
th{background:var(--surface-soft);font-weight:600;white-space:nowrap}
.sent-cell{font-family:"STKaiti","KaiTi",serif;min-width:180px}
.drop-note{font-size:12px;color:var(--muted);border-left:3px solid var(--gold);
  background:#f7f1e4;padding:8px 12px;border-radius:4px;margin-top:12px}
details.method{margin-top:40px;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}
details.method summary{cursor:pointer;padding:14px 18px;font-family:"STKaiti","KaiTi",serif;font-size:18px}
details.method .body{padding:0 22px 18px;font-size:13px;color:var(--muted)}
details.method h4{color:var(--ink);margin:14px 0 4px;font-size:14px}
nav.sibling{margin-top:26px;border-top:2px solid var(--ink);padding:12px 4px 4px;font-size:13px;display:flex;flex-wrap:wrap;gap:6px 14px}
nav.sibling a{color:var(--blue);text-decoration:none}
nav.sibling a:hover{text-decoration:underline}
nav.sibling .cur{color:var(--cinnabar);font-weight:700}
nav.sibling .home{font-weight:700}
footer{margin-top:14px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:14px}
/* ---- 固定主题背景：凝望罗盘 ---- */
html{background:#e8e7df}
body{position:relative;isolation:isolate;background:transparent}
body::before{content:"";position:fixed;inset:0;z-index:-2;pointer-events:none;
  background:url("assets/generated/remaining_pages_20260830/31_gaze_compass_v1.png") center center/cover no-repeat}
body::after{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;background:rgba(248,247,241,.27)}
.wrap{position:relative;z-index:1}
:root{--surface:rgba(255,255,252,.90);--surface-soft:rgba(248,248,245,.87)}
</style>
</head>
<body>
<div class="wrap">

<header class="page">
  <div class="seal">望</div>
  <div>
    <h1>凝望罗盘</h1>
    <div class="sub">唐宋诗词方位凝望的文本地理 —— 谁在望，望向哪个方向，望见了什么</div>
  </div>
  <div class="crumb">诗行万里 · 数媒可视化参赛系列 <b>31</b></div>
</header>

<section id="s-overview">
  <h2>罗盘总览<span class="en">GAZE COMPASS</span></h2>
  <p class="lead">对本库 __N_CORPUS__ 首唐宋诗词全文扫描"望"类凝望表达（东西南北四正与四隅之望、南北之顾、
  回望/怅望/遥望/极目，以及"望+宾语"），共命中 <b>__N_HITS__</b> 处，
  涉及 <b>__N_POETS_HIT__</b> 位诗人的 <b>__N_POEMS_HIT__</b> 首作品。其中方位明确者
  <b>__N_DIR__</b> 处——最强方向是<b>「__TOP_DIR__」（__TOP_DIR_N__ 次）</b>。
  扇区颜色表示该方向所在句的意象情感均值：红为愁苦、绿为豪逸（描述文本特征，非诗人心理）。</p>
  <div class="tiles">
    <div class="tile"><div class="num">__N_HITS__</div><div class="lab">凝望命中总数</div></div>
    <div class="tile"><div class="num">__N_DIR__</div><div class="lab">方位明确的凝望</div></div>
    <div class="tile"><div class="num">__N_NODIR__</div><div class="lab">无方向凝望（回望/怅望/遥望/极目/望+宾语）</div></div>
    <div class="tile"><div class="num">__TOP_DIR__</div><div class="lab">全语料最强方向（__TOP_DIR_N__ 次）</div></div>
  </div>
  <div class="panel compass-grid">
    <div>
      <div id="corpusRose"></div>
      <div class="legend-sent">
        <span><i style="background:#8a3b2f"></i>句意深愁（≤-0.4）</span>
        <span><i style="background:#b64b3f"></i>偏愁（-0.4~-0.15）</span>
        <span><i style="background:#9aa39b"></i>中性</span>
        <span><i style="background:#4f937f"></i>偏豪（0.15~0.4）</span>
        <span><i style="background:#26786e"></i>豪逸（≥0.4）</span>
      </div>
    </div>
    <div>
      <p class="muted" style="margin-top:0">点击左侧扇区，查看该方向全部证据句（全语料）。</p>
      <div class="ev-panel" id="ev_corpus" style="max-height:340px"><p class="muted">尚未选择方向。</p></div>
    </div>
  </div>
</section>

<section id="s-poets">
  <h2>六人罗盘<span class="en">SIX POETS</span></h2>
  <p class="lead">六位诗人的凝望玫瑰图：角度为方向，半径为次数，颜色为该向证据句的情感均值。
  样本为本库各人收录篇目（__SIX_COUNTS__），只代表收录范围内的文本特征。
  点击扇区或词条查看证据句。</p>
  <div class="poets">__POET_CARDS__</div>
</section>

<section id="s-gudu">
  <h2>故都回望指数<span class="en">OLD CAPITAL INDEX</span></h2>
  <p class="lead">统计口径：故都类词 = __GUDU_TERMS__（"京华"在南宋常指行在临安、语义两可，不计入，见方法区）；
  指数 = 编年作品中故都类词出现次数 ÷ 正文汉字数 × 100（每百字提及率）。
  编年来自六人精神编年候选表，<span class="badge b-cand">候选/推定</span>为未经人工复核的系年，
  <span class="badge b-ver">已审核</span>为人工审核系年覆盖；fact_grade=D 或缺年者不入计算、仅列出。</p>

  <div class="case">
    <h3>李清照 · 南渡（1127）前后 <span class="badge b-cand">编年多为候选</span></h3>
    <p class="note">李清照南渡前编年词中未出现故都类词；南渡后《永遇乐》"中州盛日"一类回望始见于笔端。
    样本小（各期不足十首），仅描述本库文本，不外推。</p>
    __LQZ_BARS__
    __LQZ_DETAIL__
  </div>

  <div class="case">
    <h3>陆游 · 四期分述 <span class="badge b-cand">编年含候选</span></h3>
    <p class="note">陆游生于 1125 年，全部作品都在南渡之后，无法做"前后对比"，改以四个人生分期呈现。
    其故都类词全部为"中原"，跨壮岁从戎、东归山阴到临终《示儿》，未曾中断。</p>
    __LY_BARS__
    __LY_DETAIL__
  </div>

  <div class="case">
    <h3>李白 · 五分期"长安"提及率 <span class="badge b-cand">编年全部为候选</span></h3>
    <p class="note">按五分期统计 23 首编年候选诗中"长安"字面的每百字提及率。
    蜀中期无编年诗入组；本组内"长安"仅见于流放暮年期《流夜郎赠辛判官》追忆长安旧游——
    样本极小，此结果只说明候选编年子集的分布，不能推断李白全集。</p>
    __LB_BARS__
    __LB_DETAIL__
    <p class="drop-note">__LB_ALL_NOTE__</p>
  </div>
</section>

<section id="s-geo">
  <h2>方向的地理验证<span class="en">BEARING CHECK</span></h2>
  __GEO__
</section>

<details class="method">
  <summary>方法与数据（口径 · 等级 · 局限）</summary>
  <div class="body">
    <h4>凝望表达的抽取口径</h4>
    <p>状态聚合语料为 data/analysis/famous_poets_full.jsonl.gz（六人 __N_CORPUS__ 首）。规范诗页、编年与地理证据仍以 data/poems.json 的 exact canonical match 为准。以。！？；与换行切句、句内以逗号顿号切分析单元后匹配：
    ①方位凝望：四正（东/西/南/北）与四隅（东北/东南/西北/西南）+"望"、"望"+方位、南顾/北顾；
    ②无方向凝望：回望/怅望/遥望/极目，以及"望+宾语"——宾语取"望"后 1–3 字，
    经 place_dict（269 条古地名）与手工常见名词表（明月/故乡/中原/王师/美人/都门等 48 词）最长匹配过滤。
    "相望/瞻望/希望/名望"等按前字黑名单排除；"三顾/相顾"不计入南北之顾。
    同一 work_id 内完全相同的句子只计一次。词牌名含"望"者（望江南等）不计入诗题之望。</p>
    <h4>情感值</h4>
    <p>对命中所在句以 spirit_image_dict（__SPIRIT_COUNT__ 词条人工词典）做最长匹配，取命中词情感值（-1~1）均值；
    无命中记 0 并标"中性"。该数值描述<b>作品文本的意象情感特征</b>，不断言诗人真实心理；
    不同诗人之间不做心理强弱排名（遵守项目 external_pressure 只做同人内部纵向比较的红线）。</p>
    <h4>编年与证据等级</h4>
    <p>故都回望指数使用 data/candidates/*_spirit_chronology.csv（六人 canonical 编年子集，B 级为主）：
    status=candidate 一律标注<span class="badge b-cand">候选/推定</span>；
    status=superseded_by_verified 者以 data/reviewed/verified_poem_contexts.csv 的人工审核记录覆盖并标
    <span class="badge b-ver">已审核</span>。fact_grade：A 史料直接系年 / B 权威年谱推定 / C 间接推定 / D 无法系年——
    D 级与缺年作品不进入比率计算，仅在各组"不入比率、仅列出"处交代。本页编年数据中无 disputed（两说并存）条目；
    若来源备注含两说，均已在证据行的来源字段保留原文。每根条形都可展开查看证据句、入组诗目、系年与来源。</p>
    <h4>已知局限</h4>
    <p>①样本量：六人收录 __SIX_RANGE__ 首，仍只代表本库范围，所有"最强方向""提及率"只对本库收录范围成立；
    ②凝望主语未必是诗人本人（《长恨歌》为玄宗一行、《秋夜将晓》为中原遗民），本页统计的是文本中的凝望行为；
    ③"京华"因南宋语境常指行在临安，为避免把"望行在"误记为"望故都"，未计入故都类词；
    ④方位验证仅覆盖少数可定位样本，且古今地名映射（如武昌→今武汉，而苏轼所望古武昌为今鄂州）会引入误差，
    其余方向均为文本自述；⑤"望+宾语"依赖名词表，未收录的宾语（如具体人名）会漏计。</p>
    <h4>数据文件</h4>
    <p>本页全部中间数据见 assets/competition/gaze_data.json（命中明细、六人汇总、故都指数、地理验证）。
    数据资产：analysis_full 六人 __N_CORPUS__ 首 / canonical poems.json 仅用于诗页与事实证据 / spirit_image_dict __SPIRIT_COUNT__ 词条 / place_dict 269 条古地名 /
    六人精神编年候选 CSV / verified_poem_contexts.csv 41 条人工审核系年。</p>
  </div>
</details>

<nav class="sibling">
  <a href="29_参赛导航.html">29 参赛导航</a>
  <a class="home" href="30_诗行万里_参赛版.html">30 总入口</a>
  <span class="cur">31 凝望罗盘</span>
  <a href="32_身与心双层地图.html">32 身与心双层地图</a>
  <a href="33_平行时空759.html">33 平行时空759</a>
  <a href="34_一字识诗人.html">34 一字识诗人</a>
  <a href="35_两种孤独与夸张签名.html">35 两种孤独与夸张签名</a>
  <a href="36_同龄对齐.html">36 同龄对齐</a>
  <a href="37_可听的诗.html">37 可听的诗</a>
  <a href="38_唐宋意象潮汐.html">38 意象潮汐</a>
  <a href="39_诗人自述生命卷.html">39 诗人自述生命卷</a>
</nav>
<footer>诗行万里 · 数媒可视化参赛系列 31 号 · 凝望罗盘 —— 图表描述作品文本特征，不断言诗人真实心理；
候选编年均以徽章标注。生成脚本：数据可视化脚本/viz_31_gaze_compass.py</footer>
</div>

<script>
var GAZE = __DATA__;
var DIR8 = GAZE.dir8;
function sentColor(v){
  if (v <= -0.4) return "#8a3b2f";
  if (v <= -0.15) return "#b64b3f";
  if (v >= 0.4) return "#26786e";
  if (v >= 0.15) return "#4f937f";
  return "#9aa39b";
}
function safeNum(v){ return (typeof v === "number" && v === v) ? v : 0; }
function roseOption(counts, sentis, small){
  var data = DIR8.map(function(d){
    var n = safeNum(counts[d]);
    var s = safeNum(sentis[d]);
    return { value:n, itemStyle:{ color:sentColor(s) }, senti:s };
  });
  return {
    polar:{ radius:[ "12%", "78%" ] },
    angleAxis:{ type:"category", data:DIR8, startAngle:112.5, clockwise:true,
      axisLine:{ lineStyle:{ color:"#b9c0b8" } },
      axisLabel:{ color:"#252b27", fontSize:small?11:13, fontFamily:"KaiTi,STKaiti,serif" } },
    radiusAxis:{ z:1, axisLabel:{ color:"#8b938c", fontSize:9 },
      splitLine:{ lineStyle:{ color:"#e3e7e1", type:"dashed" } },
      axisLine:{ show:false }, axisTick:{ show:false }, minInterval:1 },
    tooltip:{ trigger:"item", formatter:function(p){
      var s = p.data && typeof p.data.senti === "number" ? p.data.senti : 0;
      return p.name + "望：" + p.value + " 处<br>句情感均值 " + s.toFixed(2) + "（点击看证据）";
    } },
    series:[{ type:"bar", coordinateSystem:"polar", data:data, barCategoryGap:"18%",
      label:{ show:true, position:"outside", color:"#6f756f", fontSize:10,
        formatter:function(p){ return p.value > 0 ? p.value : ""; } } }]
  };
}
function evItemHtml(h){
  var cls = h.sentiment <= -0.15 ? "neg" : (h.sentiment >= 0.15 ? "pos" : "");
  var words = (h.spirit_words || []).map(function(w){
    return w.word + "(" + w.sentiment.toFixed(1) + ")";
  }).join(" ");
  var senti = h.neutral ? "中性（词典无命中，记0）" : "句情感 " + h.sentiment.toFixed(2) + "　意象：" + words;
  var sent = h.sentence.split(h.verb).join("<mark>" + h.verb + "</mark>");
  var src = h.source_url ? '　<a href="' + h.source_url + '" target="_blank" rel="noopener" style="color:#426f94">来源</a>' : "";
  return '<div class="ev-item ' + cls + '"><div class="ev-sent">' + sent + '</div>' +
    '<div class="ev-meta">《' + h.title + '》 · ' + h.poet + " · " + h.verb +
    (h.direction ? "（" + h.direction + "）" : "") + "　" + senti + src + "</div></div>";
}
function renderEv(el, hits, emptyMsg){
  if (!hits.length){ el.innerHTML = '<p class="muted">' + emptyMsg + "</p>"; return; }
  el.innerHTML = hits.map(evItemHtml).join("");
}
/* 总罗盘 */
var corpusChart = echarts.init(document.getElementById("corpusRose"));
corpusChart.setOption(roseOption(GAZE.corpus.dir_count, GAZE.corpus.dir_senti, false));
corpusChart.on("click", function(p){
  var d = p.name;
  var hits = GAZE.dir_hits.filter(function(h){ return h.direction === d; });
  var el = document.getElementById("ev_corpus");
  var head = '<p class="muted">「' + d + '」向凝望，全语料共 ' + hits.length + " 处：</p>";
  el.innerHTML = head + (hits.length ? hits.map(evItemHtml).join("") :
    '<p class="muted">该方向无命中。</p>');
});
/* 六人玫瑰 */
var charts = [corpusChart];
for (var poet in GAZE.poets){
  (function(poet){
    var ps = GAZE.poets[poet];
    var key = { "李白":"libai","杜甫":"dufu","白居易":"baijuyi","苏轼":"sushi","陆游":"luyou","李清照":"liqingzhao" }[poet];
    var dom = document.getElementById("rose_" + key);
    var evEl = document.getElementById("ev_" + key);
    if (dom){
      var ch = echarts.init(dom);
      ch.setOption(roseOption(ps.dir_count, ps.dir_senti, true));
      ch.on("click", function(p){
        renderEv(evEl, ps.hits.filter(function(h){ return h.direction === p.name; }),
                 "该方向无命中。");
      });
      charts.push(ch);
    }
    /* 词条点击：无方向证据 */
    var card = evEl ? evEl.closest(".poet-card") : null;
    if (card){
      card.querySelectorAll(".chip").forEach(function(chip){
        chip.addEventListener("click", function(){
          var lab = chip.textContent;
          renderEv(evEl, ps.hits.filter(function(h){
            var l = h.obj ? ("望·" + h.obj) : h.verb;
            return !h.direction && l === lab;
          }), "无命中。");
        });
      });
    }
  })(poet);
}
window.addEventListener("resize", function(){
  charts.forEach(function(c){ c.resize(); });
});
/* 证据折叠 */
document.querySelectorAll(".ev-toggle").forEach(function(btn){
  btn.addEventListener("click", function(){
    var el = document.getElementById(btn.getAttribute("data-target"));
    if (el) el.hidden = !el.hidden;
  });
});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
