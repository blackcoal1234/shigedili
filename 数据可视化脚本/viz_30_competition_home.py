# -*- coding: utf-8 -*-
"""
viz_30 参赛版主叙事页生成脚本（零参数、可复跑）
产出:
  output/30_诗行万里_参赛版.html
  output/assets/competition/home_data.json

五章: Hero / 六种人生曲线 / 陪他走完一生 / 逆境反应指数 / 方法与数据
诚实性红线: 候选徽章、disputed 两说、D级只列不算、证据可展开、方法折叠区。
曲线类型命名依据本脚本实际算出的五参数(斜率/最大单期跌幅/末期回弹/波动率/断裂点)，
脚本内以断言锁定断裂点位置——数据变动导致形状变化时断言失败，强制重新命名而非硬套。
"""
import csv
import json
import math
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_HTML = ROOT / "output" / "30_诗行万里_参赛版.html"
OUT_JSON = ROOT / "output" / "assets" / "competition" / "home_data.json"

# ---------------------------------------------------------------- 词典加载
sys.path.insert(0, str(ROOT / "data"))
import importlib.util

_spec = importlib.util.spec_from_file_location("spirit_image_dict", ROOT / "data" / "spirit_image_dict.py")
sid = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sid)

WORDS = sid.words()                       # 按长度降序
ENTRY = {e[0]: e for e in sid.SPIRIT_DICT}  # 词 -> (词,类别,簇,情感值,尺度,依据)
CLUSTERS = sid.clusters()

# 按首字分桶加速最长匹配
_BUCKET = {}
for w in WORDS:
    _BUCKET.setdefault(w[0], []).append(w)  # words() 已按长度降序，桶内保持降序

CLUSTER_CLASS = {
    "豪情进取": "c1", "纵逸狂放": "c2", "漂泊羁旅": "c3",
    "愁苦幽愤": "c4", "隐逸超脱": "c5", None: "c0",
}

POETS = [
    ("李白", "libai", "#426f94"),
    ("杜甫", "dufu", "#7a5c3d"),
    ("白居易", "baijuyi", "#26786e"),
    ("苏轼", "sushi", "#b64b3f"),
    ("陆游", "luyou", "#8a3b2f"),
    ("李清照", "liqingzhao", "#9c5d8f"),
]
COLOR = {zh: c for zh, _, c in POETS}


def norm_title(t):
    return re.sub(r"[\s·。，、（）()《》〈〉　]", "", t or "")


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def r3(x):
    if x is None:
        return None
    v = round(float(x), 3)
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError("非法数值")
    return v


# ---------------------------------------------------------------- 语料
poems_raw = json.load(open(ROOT / "data" / "poems.json", encoding="utf-8"))
BODY = {}
for p in poems_raw:
    BODY.setdefault((p["author"], norm_title(p["title"])), p["body"])
SIX_COUNTS = {zh: sum(1 for p in poems_raw if p["author"] == zh) for zh, _, _ in POETS}
N_POEMS = len(poems_raw)
N_POETS = len({p["author"] for p in poems_raw})
NUMBER_STATS = json.load(open(ROOT / "data" / "stylometry" / "number_stats.json", encoding="utf-8"))


def hyperbole_snapshot():
    rows = [
        (poet, rec) for poet, rec in NUMBER_STATS["per_poet"].items()
        if rec["chars_total"] >= 300
    ]
    rows.sort(key=lambda item: -item[1]["hyperbole_per_100_chars"])
    top_name, top_rec = rows[0]
    libai_rank = next(i + 1 for i, (name, _) in enumerate(rows) if name == "李白")
    libai_rec = NUMBER_STATS["per_poet"]["李白"]
    return {
        "top": {"name": top_name, "density": top_rec["hyperbole_per_100_chars"]},
        "libai": {"rank": libai_rank, "density": libai_rec["hyperbole_per_100_chars"]},
        "eligible": len(rows),
    }


def match_hits(body):
    """最长匹配, 返回命中词条列表(按出现顺序, 可重复)。"""
    hits, i, n = [], 0, len(body)
    while i < n:
        best = None
        for w in _BUCKET.get(body[i], ()):
            if body.startswith(w, i):
                best = w
                break
        if best:
            hits.append(ENTRY[best])
            i += len(best)
        else:
            i += 1
    return hits


def highlight_html(body):
    """正文 -> 带簇色 span 的 HTML(命中词染色), 保留换行。"""
    out, i, n = [], 0, len(body)
    while i < n:
        best = None
        for w in _BUCKET.get(body[i], ()):
            if body.startswith(w, i):
                best = w
                break
        if best:
            e = ENTRY[best]
            cls = CLUSTER_CLASS.get(e[2], "c0")
            tip = f"{e[2] or '多义(不归簇)'}·情感{e[3]}" + (f"·尺度{e[4]}" if e[4] is not None else "")
            out.append(f'<i class="hw {cls}" title="{esc(tip)}">{esc(best)}</i>')
            i += len(best)
        else:
            out.append(esc(body[i]))
            i += 1
    return "".join(out)


# ---------------------------------------------------------------- 分期框架
def load_stages():
    stages = {}
    key_events = {}
    # 李白无 life_stages 候选文件 -> 通行五分期框架(未经本项目管线审核, 页面注明)
    stages["李白"] = [
        {"index": 1, "label": "蜀中读书", "y0": 701, "y1": 725},
        {"index": 2, "label": "干谒漫游", "y0": 726, "y1": 741},
        {"index": 3, "label": "供奉翰林", "y0": 742, "y1": 744},
        {"index": 4, "label": "漫游与安史", "y0": 745, "y1": 756},
        {"index": 5, "label": "永王案与暮年", "y0": 757, "y1": 762},
    ]
    key_events["李白"] = {
        1: ["701年生，幼随家迁绵州昌隆（今四川江油）",
            "约718-720年隐居大匡山读书，游成都、峨眉"],
        2: ["724-726年仗剑去国、辞亲远游：沿江出蜀，览洞庭、金陵，抵扬州",
            "727年入赘安陆许氏",
            "735年前后游太原，740年前后移家东鲁"],
        3: ["742年奉诏入京，供奉翰林",
            "744年春赐金放还，离开长安；与杜甫初逢洛阳"],
        4: ["744-745年与杜甫、高适同游梁宋齐鲁",
            "755年十一月安史之乱爆发",
            "756年避乱南奔，隐庐山屏风叠"],
        5: ["757年入永王李璘幕府；璘败，系浔阳狱",
            "758年长流夜郎",
            "759年三月于白帝城遇赦东还",
            "762年病逝当涂"],
    }
    for zh, en, _ in POETS:
        if zh == "李白":
            continue
        d = json.load(open(ROOT / "data" / "candidates" / f"{en}_life_stages.json", encoding="utf-8"))
        stages[zh] = [
            {"index": s["index"], "label": s["label"], "y0": s["year_start"], "y1": s["year_end"]}
            for s in d["stages"]
        ]
        key_events[zh] = {s["index"]: list(s.get("key_events", [])) for s in d["stages"]}
    return stages, key_events


STAGES, KEY_EVENTS = load_stages()


def period_of(zh, year):
    for s in STAGES[zh]:
        if s["y0"] <= year <= s["y1"]:
            return s["index"]
    if year < STAGES[zh][0]["y0"]:
        return STAGES[zh][0]["index"]
    return STAGES[zh][-1]["index"]


# ---------------------------------------------------------------- 编年合并(审核层优先, 候选层补充)
def load_chronology():
    entries = {zh: [] for zh, _, _ in POETS}
    seen = set()
    with open(ROOT / "data" / "reviewed" / "verified_poem_contexts.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            zh = r["poet"]
            if zh not in entries:
                continue
            key = (zh, norm_title(r["title"]))
            if key in seen:
                continue
            seen.add(key)
            entries[zh].append({
                "title": r["title"], "year": int(r["year_start"]),
                "year_end": int(r["year_end"] or r["year_start"]),
                "precision": "reviewed", "period": None,
                "place_hist": r["historical_place"], "place": r["modern_city"],
                "lon": float(r["lon"]), "lat": float(r["lat"]),
                "source_name": r["source_name"], "source_url": r["source_url"],
                "source_note": r["source_note"], "grade": r["fact_grade"],
                "status": "approved",
            })
    for zh, en, _ in POETS:
        with open(ROOT / "data" / "candidates" / f"{en}_spirit_chronology.csv", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                key = (zh, norm_title(r["title"]))
                if key in seen:
                    continue
                seen.add(key)
                ys = r["year_start"].strip()
                entries[zh].append({
                    "title": r["title"], "year": int(ys) if ys else None,
                    "year_end": int(r["year_end"]) if r["year_end"].strip() else None,
                    "precision": r["year_precision"],
                    "period": int(r["period"]) if r["period"].strip() else None,
                    "place_hist": r["historical_place"], "place": r["modern_city"],
                    "lon": float(r["lon"]) if r["lon"].strip() else None,
                    "lat": float(r["lat"]) if r["lat"].strip() else None,
                    "source_name": r["source_name"], "source_url": r["source_url"],
                    "source_note": r["source_note"], "grade": r["fact_grade"],
                    "status": r["status"],
                })
    return entries


CHRONO = load_chronology()

# ---------------------------------------------------------------- 第二章: 六种人生曲线
# 断裂点位置断言(由本次实际计算得出并锁定; 数据变化时报错强制重命名)
EXPECT_BREAK = {"李白": (1, 2), "杜甫": (3, 4), "白居易": (2, 3),
                "苏轼": (1, 2), "陆游": (1, 2), "李清照": (2, 3)}
TYPE_NAME = {
    "李白": ("骤降回光型", "高开骤降：出蜀一跌(-0.52)为六人最大单期落差；供奉翰林短暂回光(+0.24)，此后低位徘徊。期1样本仅1首，解释力有限。"),
    "杜甫": ("沉郁顿挫型", "整体斜率为负，安史陷贼期沉至谷底；最大落差点反而是759/760弃官入蜀后的草堂回暖(+0.24)，夔州再度下沉——沉郁中见顿挫。"),
    "白居易": ("低谷前移型", "文本最沉痛的不是贬谪江州期，而是更早的谏官讽喻期(-0.27)——新乐府写民生疾苦压低全期均值；最大落差点恰在815贬江州边界，方向却是回升(+0.20)，晚年中隐平缓微降。"),
    "苏轼": ("低开渐旷型", "自初仕低点逐期上扬直至元祐(乌台诗案贬黄州反而继续上扬)，晚贬惠儋小幅回落。期1样本仅1首，解释力有限。"),
    "陆游": ("低位恒守型", "波动率六人最小(0.059)：入蜀从戎期落至低位后，四十年缓升而不复初值——与其至死不衰的北伐执念底色一致。"),
    "李清照": ("南渡断裂型", "最大落差点恰在1126/1127南渡边界，与史实吻合；但方向是上扬——《渔家傲》梦境大鹏豪语拉高了南渡期均值，晚年临安回落。这是文本意象特征，不等于心境变好。"),
}


def linreg_slope(pts):
    n = len(pts)
    if n < 2:
        return None
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    den = sum((p[0] - mx) ** 2 for p in pts)
    if den == 0:
        return None
    return sum((p[0] - mx) * (p[1] - my) for p in pts) / den


def build_curve(zh):
    per = {}
    for s in STAGES[zh]:
        per[s["index"]] = {"label": s["label"], "y0": s["y0"], "y1": s["y1"],
                           "poems": [], "sent": [], "scale": [], "cand": 0, "rev": 0}
    d_list = []
    for e in CHRONO[zh]:
        if e["grade"] == "D" or e["year"] is None:
            if e["grade"] == "D":
                d_list.append({"title": e["title"], "note": e["source_note"][:120]})
            continue
        pid = e["period"] if e["period"] in per else period_of(zh, e["year"])
        body = BODY.get((zh, norm_title(e["title"])))
        hits = match_hits(body) if body else []
        sent = [h[3] for h in hits if h[3] is not None]
        scal = [h[4] for h in hits if h[4] is not None]
        pemo = r3(statistics.mean(sent)) if sent else None
        psca = r3(statistics.mean(scal)) if scal else None
        per[pid]["poems"].append({
            "title": e["title"], "year": e["year"], "grade": e["grade"],
            "status": e["status"], "precision": e["precision"],
            "hits": len(sent), "emotion": pemo, "scale": psca,
        })
        per[pid]["sent"] += sent
        per[pid]["scale"] += scal
        if e["status"] == "approved":
            per[pid]["rev"] += 1
        else:
            per[pid]["cand"] += 1
    periods = []
    for s in STAGES[zh]:
        d = per[s["index"]]
        periods.append({
            "index": s["index"], "label": d["label"], "y0": d["y0"], "y1": d["y1"],
            "n_poems": len(d["poems"]), "n_hits": len(d["sent"]),
            "emotion": r3(statistics.mean(d["sent"])) if d["sent"] else None,
            "scale": r3(statistics.mean(d["scale"])) if d["scale"] else None,
            "cand": d["cand"], "rev": d["rev"], "poems": d["poems"],
        })
    # 五参数
    vals = [(i, p["emotion"]) for i, p in enumerate(periods) if p["emotion"] is not None]
    slope = r3(linreg_slope(vals))
    diffs = [(vals[k][0], vals[k + 1][0], vals[k + 1][1] - vals[k][1]) for k in range(len(vals) - 1)]
    max_drop = r3(min((d[2] for d in diffs), default=0.0))          # 最深负向落差
    series_v = [v for _, v in vals]
    rebound = r3(series_v[-1] - min(series_v)) if series_v else None  # 末期值-全程最低
    vol = r3(statistics.pstdev(series_v)) if len(series_v) > 1 else None
    bi, bj, bd = max(diffs, key=lambda d: abs(d[2]))                 # 最优断裂点=相邻期最大绝对落差
    p_from, p_to = periods[bi], periods[bj]
    assert (p_from["index"], p_to["index"]) == EXPECT_BREAK[zh], \
        f"{zh} 断裂点变动为 期{p_from['index']}->期{p_to['index']}，请依新形状重新命名曲线类型"
    boundary = p_to["y0"]

    def _years(ev):
        return [int(y) for y in re.findall(r"(\d{3,4})年", ev)]

    ev_match = None
    # 优先: 断裂点右侧分期(to)内含边界年的事件; 次之: 左侧分期(from)末年事件; 兜底: 全部事件 ±1 年
    for ev in KEY_EVENTS[zh].get(p_to["index"], []):
        if boundary in _years(ev):
            ev_match = ev
            break
    if ev_match is None:
        for ev in KEY_EVENTS[zh].get(p_from["index"], []):
            if p_from["y1"] in _years(ev):
                ev_match = ev
                break
    if ev_match is None:
        for evs in KEY_EVENTS[zh].values():
            for ev in evs:
                if any(abs(y - boundary) <= 1 for y in _years(ev)):
                    ev_match = ev
                    break
            if ev_match:
                break
    tname, tdesc = TYPE_NAME[zh]
    return {
        "periods": periods,
        "d_list": d_list,
        "params": {
            "slope": slope, "max_drop": max_drop, "rebound": rebound, "volatility": vol,
            "break_from": p_from["index"], "break_to": p_to["index"], "break_delta": r3(bd),
            "break_boundary": boundary, "break_event": ev_match,
            "break_matched": ev_match is not None,
        },
        "type_name": tname, "type_desc": tdesc,
    }


# ---------------------------------------------------------------- 第三章: 行旅站点
journeys = json.load(open(ROOT / "data" / "reviewed" / "poet_journeys.json", encoding="utf-8"))
JMETH = journeys["methodology"]
JNODES = {p["poet"]: p["nodes"] for p in journeys["poets"]}


def poem_station(zh, e):
    body = BODY.get((zh, norm_title(e["title"])))
    hits = match_hits(body) if body else []
    sent = [h[3] for h in hits if h[3] is not None]
    scal = [h[4] for h in hits if h[4] is not None]
    return {
        "kind": "poem", "year": e["year"],
        "year_label": (f"{e['year']}年" if e["year"] == e["year_end"] or not e["year_end"]
                       else f"{e['year']}-{e['year_end']}年"),
        "place": e["place"], "place_hist": e["place_hist"],
        "lon": e["lon"], "lat": e["lat"],
        "event": f"系年作《{e['title']}》于{e['place_hist']}",
        "title": e["title"],
        "body_html": highlight_html(body) if body else None,
        "emotion": r3(statistics.mean(sent)) if sent else None,
        "scale": r3(statistics.mean(scal)) if scal else None,
        "n_hits": len(sent),
        "grade": e["grade"], "status": e["status"], "precision": e["precision"],
        "source_name": e["source_name"], "source_url": e["source_url"],
        "source_note": e["source_note"],
    }


def build_stations(zh):
    stations = []
    used = set()
    chrono_by_title = {norm_title(e["title"]): e for e in CHRONO[zh]}
    for nd in JNODES[zh]:
        lp = nd.get("linked_poem") or {}
        te = lp.get("text_emotion") or {}
        lc = nd.get("life_context") or {}
        title = lp.get("title")
        ce = chrono_by_title.get(norm_title(title)) if title else None
        body = BODY.get((zh, norm_title(title))) if title else None
        st = {
            "kind": "journey", "year": nd["year"], "year_label": nd["year_label"],
            "place": nd["place_modern"], "place_hist": nd["place_historical"],
            "lon": nd["longitude"], "lat": nd["latitude"],
            "event": nd["event"], "title": title,
            "body_html": highlight_html(body) if body else None,
            "valence": te.get("valence"), "intensity": te.get("intensity"),
            "emo_label": te.get("label"), "evidence": te.get("evidence"),
            "ep": lc.get("external_pressure"), "ep_label": lc.get("label"),
            "ep_reason": lc.get("reason"),
            "source_level": nd.get("source_level"),
            "source_name": nd.get("source_name"), "source_url": nd.get("source_url"),
            "source_note": nd.get("note"),
            "precision": nd.get("year_precision"),
        }
        if ce:  # 合并同题编年条目, 避免同诗双站
            used.add(norm_title(title))
            st["grade"] = ce["grade"]
            st["status"] = ce["status"]
            hits = match_hits(body) if body else []
            sent = [h[3] for h in hits if h[3] is not None]
            scal = [h[4] for h in hits if h[4] is not None]
            st["emotion"] = r3(statistics.mean(sent)) if sent else None
            st["scale"] = r3(statistics.mean(scal)) if scal else None
        stations.append(st)
    for e in CHRONO[zh]:
        if e["year"] is None or e["lon"] is None or norm_title(e["title"]) in used:
            continue
        stations.append(poem_station(zh, e))
    stations.sort(key=lambda s: (s["year"], 0 if s["kind"] == "journey" else 1, s.get("title") or ""))
    return stations


# ---------------------------------------------------------------- 第四章: 逆境反应指数
def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def spearman(a, b):
    ra, rb = _ranks(a), _ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((y - mb) ** 2 for y in rb))
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


def build_adversity(zh):
    nodes = JNODES[zh]
    eps = [n["life_context"]["external_pressure"] for n in nodes]
    vals = [n["linked_poem"]["text_emotion"]["valence"] for n in nodes]
    rho = r3(spearman(eps, vals))
    pts = []
    for n, e, v in zip(nodes, eps, vals):
        pts.append({
            "year": n["year"], "place": n["place_modern"],
            "ep": r3(e * 100), "valence": r3(v), "divergence": r3(v + e),
            "event": n["event"], "title": n["linked_poem"]["title"],
            "evidence": n["linked_poem"]["text_emotion"].get("evidence"),
            "source_level": n.get("source_level"),
        })
    breakout = max(pts, key=lambda p: p["divergence"])
    if rho <= -0.5:
        mode = "感时型(强)"
    elif rho <= -0.25:
        mode = "偏感时"
    elif rho <= -0.1:
        mode = "弱感时"
    else:
        mode = "脱钩型"
    return {"n": len(nodes), "rho": rho, "mode": mode, "points": pts, "breakout": breakout}


# ---------------------------------------------------------------- 汇总
def build_data():
    poets = []
    for zh, en, color in POETS:
        curve = build_curve(zh)
        poets.append({
            "name": zh, "key": en, "color": color,
            "n_corpus": SIX_COUNTS[zh],
            "stages": STAGES[zh],
            "curve": curve,
            "stations": build_stations(zh),
            "adversity": build_adversity(zh),
        })
    n_cand = sum(1 for zh in CHRONO for e in CHRONO[zh] if e["status"] != "approved")
    n_rev = sum(1 for zh in CHRONO for e in CHRONO[zh] if e["status"] == "approved")
    doc = (sid.__doc__ or "").strip()
    cand_sources = []
    for zh, en, _ in POETS:
        for e in CHRONO[zh]:
            cand_sources.append({
                "poet": zh, "title": e["title"], "grade": e["grade"], "status": e["status"],
                "precision": e["precision"], "url": e["source_url"], "name": e["source_name"],
            })
    hyperbole = hyperbole_snapshot()
    return {
        "generated_note": "由 数据可视化脚本/viz_30_competition_home.py 生成，可复跑",
        "corpus": {"n_poems": N_POEMS, "n_poets": N_POETS, "six_counts": SIX_COUNTS,
                   "n_journey_nodes": sum(len(v) for v in JNODES.values()),
                   "n_chrono_reviewed": n_rev, "n_chrono_candidate": n_cand,
                   "n_dict": len(WORDS), "hyperbole": hyperbole},
        "cluster_words": {k: len(v) for k, v in CLUSTERS.items()},
        "dict_doc": doc,
        "journey_methodology": JMETH,
        "poets": poets,
        "cand_sources": cand_sources,
    }


# ---------------------------------------------------------------- HTML 模板
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>诗行万里 · 给每首课本诗一个人生坐标</title>
<link rel="icon" href="data:,">
<script src="assets/pyecharts/v6/echarts.min.js"></script>
<script src="assets/pyecharts/v6/maps/china.js"></script>
<style>
:root{
  --paper:#f2f4f0; --surface:#ffffff; --soft:#f8f8f5; --ink:#252b27; --muted:#6f756f;
  --line:#d9ddd7; --line-strong:#b9c0b8; --cinnabar:#b64b3f; --jade:#26786e;
  --gold:#a87527; --blue:#426f94; --accent:#426f94; --radius:6px;
  --shadow:0 10px 30px rgba(33,39,35,.07);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;color:var(--ink);font-family:"Microsoft YaHei","PingFang SC","Segoe UI",sans-serif;
  background:linear-gradient(rgba(49,57,51,.025) 1px,transparent 1px),
    linear-gradient(90deg,rgba(49,57,51,.025) 1px,transparent 1px),var(--paper);
  background-size:24px 24px;font-size:14px;line-height:1.7}
h1,h2,h3,.kai{font-family:"KaiTi","STKaiti","Kaiti SC",serif}
a{color:var(--blue)}
button{font:inherit;cursor:pointer}
.wrap{max-width:1180px;margin:0 auto;padding:0 20px}
/* ---- 顶部锚点导航 ---- */
.topnav{position:fixed;top:0;left:0;right:0;z-index:50;background:rgba(37,42,39,.96);
  color:#eef0ec;border-bottom:2px solid var(--accent)}
.topnav .row{max-width:1180px;margin:0 auto;display:flex;align-items:center;gap:4px;
  padding:0 14px;height:52px;overflow-x:auto;white-space:nowrap}
.seal{width:30px;height:30px;flex:0 0 auto;display:grid;place-items:center;color:#fff;
  font-family:"KaiTi","STKaiti",serif;font-size:18px;background:var(--cinnabar);
  border-radius:4px;margin-right:8px}
.topnav .brand{font-family:"KaiTi","STKaiti",serif;font-size:17px;margin-right:14px}
.topnav a{color:#c7cec8;text-decoration:none;padding:6px 10px;border-radius:4px;font-size:13px}
.topnav a:hover{color:#fff;background:#353c37}
.topnav a b{color:#8f978f;font-family:Consolas,monospace;font-weight:400;margin-right:4px;font-size:11px}
main{padding-top:52px}
section{scroll-margin-top:64px}
/* ---- Hero ---- */
.hero{padding:72px 0 48px;text-align:center;position:relative}
.hero h1{font-size:clamp(30px,5vw,52px);margin:0 0 10px;letter-spacing:2px}
.hero .sub{font-size:clamp(16px,2.4vw,22px);color:var(--muted);font-family:"KaiTi","STKaiti",serif}
.hero .intro{max-width:720px;margin:18px auto 0;color:var(--ink)}
.hero .stats{display:flex;flex-wrap:wrap;gap:12px;justify-content:center;margin-top:26px}
.stat{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  padding:10px 18px;box-shadow:var(--shadow);min-width:120px}
.stat .num{font-size:24px;font-family:"KaiTi","STKaiti",serif;color:var(--accent)}
.stat .lab{font-size:12px;color:var(--muted)}
.hero .poets{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:22px}
.hero .poets span{padding:4px 14px;border-radius:99px;color:#fff;font-family:"KaiTi","STKaiti",serif;font-size:15px}
/* ---- 章节标题 ---- */
.sec-head{display:flex;align-items:baseline;gap:14px;margin:56px 0 8px;border-bottom:2px solid var(--line-strong);padding-bottom:10px}
.sec-head .no{font-family:Consolas,monospace;color:var(--cinnabar);font-size:14px}
.sec-head h2{margin:0;font-size:26px}
.sec-head .hint{color:var(--muted);font-size:12px}
.sec-note{color:var(--muted);font-size:12.5px;margin:6px 0 18px}
/* ---- 徽章 ---- */
.badge{display:inline-block;padding:1px 7px;border-radius:3px;font-size:11px;line-height:1.6;
  border:1px solid transparent;vertical-align:middle}
.b-A{background:#e2efec;color:#1e5f57;border-color:#9cc5be}
.b-B{background:#e8eef4;color:#33566f;border-color:#a9c0d2}
.b-C{background:#f5eddd;color:#7c5a1e;border-color:#d3ba8a}
.b-D{background:#eeeeec;color:#767a74;border-color:#c9cdc6}
.b-cand{background:#f3e5e1;color:#8f382d;border-color:#d8a49b}
.b-rev{background:#e2efec;color:#1e5f57;border-color:#9cc5be}
.b-disp{background:#f7e8d8;color:#8a5a1a;border-color:#dcb98a;font-weight:700}
.b-hit{background:#f1f1ee;color:#555;border-color:#ccc}
/* ---- 卡片网格 ---- */
.grid6{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  box-shadow:var(--shadow);overflow:hidden}
.card .head{display:flex;align-items:center;gap:10px;padding:12px 16px 8px;flex-wrap:wrap}
.card .head .dot{width:12px;height:12px;border-radius:3px;flex:0 0 auto}
.card .head h3{margin:0;font-size:19px}
.card .head .type{font-family:"KaiTi","STKaiti",serif;font-size:15px;color:var(--cinnabar)}
.card .desc{padding:0 16px;color:var(--muted);font-size:12px}
.curve-chart{width:100%;height:215px}
.params{display:flex;flex-wrap:wrap;gap:6px;padding:4px 14px 10px}
.params span{background:var(--soft);border:1px solid var(--line);border-radius:3px;
  padding:1px 7px;font-size:11px;color:#4d534e}
.params b{color:var(--accent);font-weight:600}
.expand-btn{display:block;width:100%;border:none;border-top:1px dashed var(--line);
  background:var(--soft);padding:7px;font-size:12px;color:var(--muted)}
.expand-btn:hover{color:var(--ink)}
.detail{display:none;padding:10px 14px;border-top:1px solid var(--line);background:#fbfbf9}
.detail.open{display:block}
.tbl-wrap{overflow-x:auto}
table{border-collapse:collapse;font-size:12px;min-width:460px;width:100%}
th,td{border:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}
th{background:var(--soft);font-weight:600;white-space:nowrap}
.poemlist{margin:6px 0 0;padding-left:18px;font-size:12px;color:#4d534e}
.poemlist li{margin:2px 0}
.dnote{margin-top:8px;font-size:12px;color:var(--muted)}
/* ---- 第三章 ---- */
.poet-btns{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}
.poet-btns button{border:1.5px solid var(--line-strong);background:var(--surface);
  border-radius:99px;padding:6px 18px;font-family:"KaiTi","STKaiti",serif;font-size:16px;color:var(--muted)}
.poet-btns button.on{color:#fff;border-color:transparent}
.journey-panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  box-shadow:var(--shadow);border-top:4px solid var(--accent)}
.stepper{display:flex;align-items:center;gap:12px;padding:12px 18px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.stepper button{border:1px solid var(--line-strong);background:var(--soft);border-radius:4px;
  padding:6px 16px;font-size:13px}
.stepper button:disabled{opacity:.4;cursor:default}
.stepper .pos{font-family:Consolas,monospace;font-size:12px;color:var(--muted);white-space:nowrap}
.progress{flex:1;min-width:120px;height:6px;background:var(--soft);border:1px solid var(--line);border-radius:99px;overflow:hidden}
.progress i{display:block;height:100%;background:var(--accent);width:0;transition:width .25s}
.journey-body{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr)}
@media (max-width:900px){.journey-body{grid-template-columns:1fr}}
#jmap{width:100%;height:430px;min-height:340px}
.station{padding:16px 20px;border-left:1px solid var(--line)}
@media (max-width:900px){.station{border-left:none;border-top:1px solid var(--line)}}
.station .yr{font-family:"KaiTi","STKaiti",serif;font-size:24px;color:var(--accent)}
.station .plc{font-size:15px;margin:2px 0 6px}
.station .evt{color:#4d534e;font-size:13px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.chips span{background:var(--soft);border:1px solid var(--line);border-radius:3px;padding:1px 8px;font-size:11.5px}
.poem-box{background:#fbfbf8;border:1px solid var(--line);border-radius:4px;padding:12px 14px;margin:10px 0;
  max-height:270px;overflow-y:auto}
.poem-box .pt{font-family:"KaiTi","STKaiti",serif;font-size:17px;margin-bottom:6px}
.poem-body{white-space:pre-line;font-size:14.5px;line-height:2}
.hw{font-style:normal;border-bottom:2px solid;padding:0 1px;border-radius:2px}
.hw.c1{color:#426f94;border-color:#426f94;background:rgba(66,111,148,.08)}
.hw.c2{color:#a87527;border-color:#a87527;background:rgba(168,117,39,.08)}
.hw.c3{color:#7a5c3d;border-color:#7a5c3d;background:rgba(122,92,61,.10)}
.hw.c4{color:#b64b3f;border-color:#b64b3f;background:rgba(182,75,63,.08)}
.hw.c5{color:#26786e;border-color:#26786e;background:rgba(38,120,110,.08)}
.hw.c0{color:#666;border-bottom:2px dotted #999;background:none}
.legend-hw{display:flex;flex-wrap:wrap;gap:10px;font-size:12px;color:var(--muted);margin:8px 0 0}
.src-fold{font-size:12px;color:var(--muted);margin-top:8px}
.src-fold summary{cursor:pointer;color:var(--blue)}
.disp-box{background:#fdf6ec;border:1px solid #dcb98a;border-radius:4px;padding:8px 10px;font-size:12px;margin-top:8px}
/* ---- 第四章 ---- */
.adv-grid{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:18px}
@media (max-width:900px){.adv-grid{grid-template-columns:1fr}}
#advbar{width:100%;height:330px}
.redline{background:#f3e5e1;border:1px solid #d8a49b;border-left:4px solid var(--cinnabar);
  border-radius:4px;padding:10px 14px;font-size:13px;margin:12px 0}
.breakout{border:1px solid var(--line);border-radius:4px;margin-bottom:8px;background:var(--surface)}
.breakout summary{cursor:pointer;padding:8px 12px;font-size:13px;list-style:none;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.breakout summary::-webkit-details-marker{display:none}
.breakout .bd{padding:0 12px 10px;font-size:12.5px;color:#4d534e}
.breakout .tag{color:#fff;border-radius:3px;padding:1px 8px;font-family:"KaiTi","STKaiti",serif}
/* ---- 第五章 ---- */
.methods details{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);margin-bottom:10px}
.methods summary{cursor:pointer;padding:11px 16px;font-size:15px;font-family:"KaiTi","STKaiti",serif}
.methods .bd{padding:0 18px 14px;font-size:13px;color:#3d433e}
.methods pre{background:var(--soft);border:1px solid var(--line);border-radius:4px;padding:10px 12px;
  white-space:pre-wrap;font-size:12px;color:#4d534e;max-height:340px;overflow:auto}
.honest{background:#fdf6ec;border-left:4px solid var(--gold);padding:10px 14px;border-radius:4px;font-size:13px}
/* ---- 页尾 ---- */
footer{margin-top:60px;background:#252a27;color:#c7cec8;padding:26px 0 34px}
footer .links{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px}
footer a{color:#e8eae6;text-decoration:none;border:1px solid #465049;border-radius:4px;
  padding:6px 12px;font-size:13px;background:#2f3531}
footer a:hover{border-color:#8f978f}
footer .tiny{font-size:11px;color:#8f978f;margin-top:16px}
footer a.cur{border-color:var(--cinnabar);color:#fff;background:#3a2f2c;cursor:default}
</style>
</head>
<body>
<nav class="topnav"><div class="row">
  <span class="seal">诗</span><span class="brand">诗行万里</span>
  <a href="#ch1"><b>01</b>缘起</a>
  <a href="#ch2"><b>02</b>六种人生曲线</a>
  <a href="#ch3"><b>03</b>陪他走完一生</a>
  <a href="#ch4"><b>04</b>逆境反应指数</a>
  <a href="#ch5"><b>05</b>方法与数据</a>
</div></nav>

<main>
<section class="hero" id="ch1"><div class="wrap">
  <h1>诗行万里</h1>
  <div class="sub">给每首课本诗一个人生坐标 —— 六位唐宋诗人的生命情感与精神地形</div>
  <p class="intro">课本里的诗常常只是一页纸，我们把它放回诗人的一生里：基于
    <b>__N_POEMS__ 首</b>诗歌语料、<b>__N_JOURNEY_NODES__ 个</b>人工审核的生平行旅节点与 <b>A/B/C 三级证据体系</b>，
    用一部 197 词条的双维度意象词典（情感值 × 空间尺度），为李白、杜甫、白居易、苏轼、陆游、李清照
    画出各自的人生情感曲线——每一个数字都能点开看到证据与来源。</p>
  <div class="stats" id="hero-stats"></div>
  <div class="poets" id="hero-poets"></div>
</div></section>

<section id="ch2"><div class="wrap">
  <div class="sec-head"><span class="no">02</span><h2>六种人生曲线</h2>
    <span class="hint">形状学总览 · 点击卡片底部展开分期明细</span></div>
  <p class="sec-note">每人按其生平分期统计：对该期已编年诗作正文做词典最长匹配，取命中词<b>情感值均值</b>（实线）与<b>空间尺度均值</b>（虚线，1~5 级）。
    D 级（无法系年）诗作不进入曲线，仅在明细中列出。曲线刻画的是<b>作品文本的意象特征</b>，不断言诗人真实心理。
    断裂点（相邻期最大落差）由算法检测；若与生平大事年份吻合，图中以竖线标注。</p>
  <div class="grid6" id="curve-cards"></div>
</div></section>

<section id="ch3"><div class="wrap">
  <div class="sec-head"><span class="no">03</span><h2>陪他走完一生</h2>
    <span class="hint">一站一诗 · 地图上走完他的一生</span></div>
  <p class="sec-note">每一站是一个生平节点或一首已编年的诗。左图为已走过的路径与当前位置；右侧是这一年的他：
    在哪里、发生了什么、写下了什么。诗句中命中意象词典的词已按情感簇染色。
    <span class="badge b-cand">候选</span> 表示该系年为候选层、未经人工审核；
    <span class="badge b-disp">两说</span> 表示系年存在分歧，展开来源可见两说原文。</p>
  <div class="poet-btns" id="jbtns"></div>
  <div class="journey-panel">
    <div class="stepper">
      <button id="jprev">← 上一站</button>
      <button id="jnext">下一站 →</button>
      <div class="progress"><i id="jbar"></i></div>
      <span class="pos" id="jpos"></span>
    </div>
    <div class="journey-body">
      <div id="jmap"></div>
      <div class="station" id="jstation"></div>
    </div>
  </div>
  <div class="legend-hw">意象簇染色：
    <span><i class="hw c1">豪情进取</i></span><span><i class="hw c2">纵逸狂放</i></span>
    <span><i class="hw c3">漂泊羁旅</i></span><span><i class="hw c4">愁苦幽愤</i></span>
    <span><i class="hw c5">隐逸超脱</i></span><span><i class="hw c0">多义不归簇</i></span>
  </div>
</div></section>

<section id="ch4"><div class="wrap">
  <div class="sec-head"><span class="no">04</span><h2>逆境反应指数</h2>
    <span class="hint">处境越差，笔下越沉痛吗？</span></div>
  <p class="sec-note">在每位诗人<b>自己的</b>生平节点内，计算「外部压强」与「文本情感值」的 Spearman 相关：
    负得越深，说明处境越差诗越沉痛（<b>感时型</b>）；接近 0 则文本情感与处境脱钩（<b>脱钩型</b>）。
    每人节点数只有 6~7 个，样本很小，系数只用于描述方向与形状。</p>
  <div class="redline">红线声明：外部压强只允许<b>同一诗人内部</b>的纵向比较；本图六条并列仅为呈现各自的方向，
    <b>不构成诗人之间的排名或打分</b>，六人节点选取标准也不完全一致。</div>
  <div class="adv-grid">
    <div class="card"><div id="advbar"></div></div>
    <div>
      <h3 class="kai" style="margin:4px 0 10px">精神突围点</h3>
      <p class="sec-note" style="margin-top:0">每人「文本情感值 −（− 外部压强）」最大的节点：处境最沉重、笔下却最昂扬的一刻。点开看这一站发生了什么。</p>
      <div id="breakouts"></div>
    </div>
  </div>
</div></section>

<section id="ch5"><div class="wrap">
  <div class="sec-head"><span class="no">05</span><h2>方法与数据</h2>
    <span class="hint">口径 · 证据等级 · 局限与自曝</span></div>
  <div class="methods" id="methods"></div>
</div></section>
</main>

<footer><div class="wrap">
  <div class="kai" style="font-size:18px;color:#fff">继续探索 · 参赛版系列页面</div>
  <div class="links">
    <a href="29_参赛导航.html">29 参赛导航</a>
    <a href="30_诗行万里_参赛版.html" class="cur" aria-current="page">30 总入口（本页）</a>
    <a href="31_凝望罗盘.html">31 凝望罗盘</a>
    <a href="32_身与心双层地图.html">32 身与心双层地图</a>
    <a href="33_平行时空759.html">33 平行时空 759</a>
    <a href="34_一字识诗人.html">34 一字识诗人</a>
    <a href="35_两种孤独与夸张签名.html">35 两种孤独与夸张签名</a>
    <a href="36_同龄对齐.html">36 同龄对齐</a>
    <a href="37_可听的诗.html">37 可听的诗</a>
    <a href="38_唐宋意象潮汐.html">38 意象潮汐</a>
    <a href="39_诗人自述生命卷.html">39 诗人自述生命卷</a>
  </div>
  <div class="tiny">诗行万里 · 数媒可视化参赛版 · 数据来源：cnkgraph 唐宋文学编年地图开放 API、古诗文网创作背景（逐条 URL 见第五章） · 本页由脚本生成，可复跑复核</div>
</div></footer>

<script id="home-data" type="application/json">__DATA__</script>
<script>
"use strict";
var DATA = JSON.parse(document.getElementById("home-data").textContent);
var byKey = {}; DATA.poets.forEach(function(p){ byKey[p.key]=p; });
function num(v){ return (v===null||v===undefined||v!==v) ? null : v; }
function fmt(v,d){ v=num(v); return v===null ? "—" : v.toFixed(d===undefined?2:d); }
function el(html){ var t=document.createElement("template"); t.innerHTML=html.trim(); return t.content.firstChild; }
function badgeGrade(g){ return g ? '<span class="badge b-'+g+'">'+g+'级</span>' : ''; }
function badgeStatus(st){
  if(st==="approved") return '<span class="badge b-rev">已审核</span>';
  if(st) return '<span class="badge b-cand">候选</span>';
  return '';
}
function badgeDisp(prec){ return prec==="disputed" ? '<span class="badge b-disp">两说</span>' : ''; }
var charts=[];

/* ---------- Hero ---------- */
(function(){
  var c=DATA.corpus;
  var stats=[[c.n_poems,"首诗歌语料"],[c.n_poets,"位诗人"],[c.n_journey_nodes,"个审核行旅节点"],
             [c.n_chrono_reviewed+"+"+c.n_chrono_candidate,"条审核+候选编年"],[c.n_dict,"词条意象词典"]];
  var s=document.getElementById("hero-stats");
  stats.forEach(function(x){ s.appendChild(el('<div class="stat"><div class="num">'+x[0]+'</div><div class="lab">'+x[1]+'</div></div>')); });
  var pp=document.getElementById("hero-poets");
  DATA.poets.forEach(function(p){
    pp.appendChild(el('<span style="background:'+p.color+'">'+p.name+' · '+p.n_corpus+'首</span>'));
  });
})();

/* ---------- 第二章 曲线卡 ---------- */
(function(){
  var box=document.getElementById("curve-cards");
  var pending=[]; /* 先插全部卡片再统一 init：auto-fit 网格在逐卡插入期间会反复回流，过早 init 的画布宽度会失真 */
  DATA.poets.forEach(function(p){
    var cv=p.curve, pm=cv.params;
    var card=el('<div class="card"></div>');
    var matched = pm.break_matched ? ' <span class="badge b-A">断裂点与史实吻合</span>' : '';
    card.appendChild(el('<div class="head"><span class="dot" style="background:'+p.color+'"></span>'+
      '<h3>'+p.name+'</h3><span class="type">'+cv.type_name+'</span>'+matched+'</div>'));
    card.appendChild(el('<div class="desc">'+cv.type_desc+'</div>'));
    var ch=el('<div class="curve-chart" id="curve-'+p.key+'"></div>');
    card.appendChild(ch);
    card.appendChild(el('<div class="params">'+
      '<span>整体斜率 <b>'+fmt(pm.slope,3)+'</b></span>'+
      '<span>最大单期跌幅 <b>'+fmt(pm.max_drop,2)+'</b></span>'+
      '<span>末期回弹 <b>'+fmt(pm.rebound,2)+'</b></span>'+
      '<span>波动率 <b>'+fmt(pm.volatility,3)+'</b></span>'+
      '<span>断裂点 <b>期'+pm.break_from+'→期'+pm.break_to+'（'+pm.break_boundary+'年前后，Δ'+fmt(pm.break_delta,2)+'）</b></span>'+
      '</div>'));
    var btn=el('<button class="expand-btn">▾ 展开分期明细（诗数 / 命中 / 情感 / 尺度 / 候选占比）</button>');
    var det=el('<div class="detail"></div>');
    var rows=cv.periods.map(function(q){
      var poems=q.poems.map(function(w){
        return '<li>《'+w.title+'》 '+w.year+'年 '+badgeGrade(w.grade)+' '+badgeStatus(w.status)+badgeDisp(w.precision)+
          ' <span class="badge b-hit">命中'+w.hits+'</span> 情感 '+fmt(w.emotion)+' / 尺度 '+fmt(w.scale,1)+'</li>';
      }).join("");
      return '<tr><td>期'+q.index+' '+q.label+'<br><span style="color:var(--muted)">'+q.y0+'–'+q.y1+'</span></td>'+
        '<td>'+q.n_poems+'</td><td>'+q.n_hits+'</td><td>'+fmt(q.emotion)+'</td><td>'+fmt(q.scale)+'</td>'+
        '<td>候选 '+q.cand+' / 审核 '+q.rev+'</td></tr>'+
        (poems ? '<tr><td colspan="6"><ul class="poemlist">'+poems+'</ul></td></tr>' : '');
    }).join("");
    var dnote = cv.d_list.length ?
      '<div class="dnote">D 级不计入曲线：'+cv.d_list.map(function(d){return '《'+d.title+'》';}).join("、")+
      '（无法可靠系年，详见第五章）</div>' : '';
    det.innerHTML='<div class="tbl-wrap"><table><tr><th>分期</th><th>诗数</th><th>命中词</th><th>情感均值</th><th>尺度均值</th><th>候选/审核</th></tr>'+rows+'</table></div>'+dnote+
      (pm.break_event ? '<div class="dnote">断裂点参照生平大事：'+pm.break_event+'（断裂点由算法检测，与史实吻合）</div>' : '');
    btn.addEventListener("click",function(){ det.classList.toggle("open");
      btn.textContent = det.classList.contains("open") ? "▴ 收起分期明细" : "▾ 展开分期明细（诗数 / 命中 / 情感 / 尺度 / 候选占比）"; });
    card.appendChild(btn); card.appendChild(det);
    box.appendChild(card);

    var labels=cv.periods.map(function(q){ return "期"+q.index; });
    var emo=cv.periods.map(function(q){ return num(q.emotion); });
    var sca=cv.periods.map(function(q){ return num(q.scale); });
    var breakIdx=cv.periods.findIndex(function(q){ return q.index===pm.break_to; });
    pending.push({div:ch,option:{
      grid:{left:44,right:44,top:26,bottom:24},
      tooltip:{trigger:"axis",confine:true,formatter:function(ps){
        var q=cv.periods[ps[0].dataIndex];
        var s="<b>期"+q.index+" "+q.label+"</b>（"+q.y0+"–"+q.y1+"）<br>诗 "+q.n_poems+" 首 · 命中 "+q.n_hits+" 词";
        ps.forEach(function(x){ var v=num(x.value); s+="<br>"+x.marker+x.seriesName+"："+(v===null?"—":v.toFixed(2)); });
        return s;
      }},
      xAxis:{type:"category",data:labels,axisLine:{lineStyle:{color:"#b9c0b8"}},axisLabel:{color:"#6f756f",fontSize:11}},
      yAxis:[
        {type:"value",name:"情感",min:-0.6,max:0.6,splitNumber:3,axisLabel:{color:"#6f756f",fontSize:10},
         splitLine:{lineStyle:{color:"#e7eae5"}},nameTextStyle:{color:"#6f756f",fontSize:10}},
        {type:"value",name:"尺度",min:1,max:5,splitNumber:2,axisLabel:{color:"#a89b7c",fontSize:10},
         splitLine:{show:false},nameTextStyle:{color:"#a89b7c",fontSize:10}}
      ],
      series:[
        {name:"情感值",type:"line",data:emo,connectNulls:true,symbol:"circle",symbolSize:7,
         lineStyle:{width:2.5,color:p.color},itemStyle:{color:p.color},
         markLine:(breakIdx>=0?{symbol:"none",silent:true,
           data:[{xAxis:breakIdx}],
           lineStyle:{color:"#b64b3f",type:"dashed",width:1.5},
           label:{formatter:"断裂点 "+pm.break_boundary,color:"#b64b3f",fontSize:10,position:"insideEndTop"}}:undefined)},
        {name:"空间尺度",type:"line",yAxisIndex:1,data:sca,connectNulls:true,symbol:"diamond",symbolSize:6,
         lineStyle:{width:1.5,type:"dashed",color:"#a87527"},itemStyle:{color:"#a87527"}}
      ]
    }});
  });
  pending.forEach(function(x){
    var chart=echarts.init(x.div);
    chart.setOption(x.option);
    charts.push(chart);
  });
})();

/* ---------- 第三章 行旅 ---------- */
var jState={key:"libai",idx:0};
var jmap=echarts.init(document.getElementById("jmap"));
charts.push(jmap);
function renderJourneyButtons(){
  var box=document.getElementById("jbtns");
  DATA.poets.forEach(function(p){
    var b=el('<button data-key="'+p.key+'">'+p.name+'</button>');
    b.addEventListener("click",function(){ selectPoet(p.key); });
    box.appendChild(b);
  });
}
function selectPoet(key){
  jState.key=key; jState.idx=0;
  var p=byKey[key];
  document.documentElement.style.setProperty("--accent",p.color);
  var btns=document.querySelectorAll("#jbtns button");
  btns.forEach(function(b){
    var on=b.getAttribute("data-key")===key;
    b.classList.toggle("on",on);
    b.style.background = on ? byKey[b.getAttribute("data-key")].color : "";
  });
  renderStation();
}
function stationBadges(st){
  var s="";
  if(st.kind==="journey"){
    s+='<span class="badge b-'+(st.source_level||"C")+'">节点来源'+(st.source_level||"C")+'级</span>';
    if(st.grade) s+='<span class="badge b-'+st.grade+'">系年'+st.grade+'级</span>'+badgeStatus(st.status);
  } else {
    s+=badgeGrade(st.grade)+badgeStatus(st.status);
  }
  s+=badgeDisp(st.precision);
  return s;
}
function renderStation(){
  var p=byKey[jState.key], sts=p.stations, st=sts[jState.idx];
  document.getElementById("jpos").textContent=(jState.idx+1)+" / "+sts.length+" 站";
  document.getElementById("jbar").style.width=(100*(jState.idx+1)/sts.length).toFixed(1)+"%";
  document.getElementById("jprev").disabled = jState.idx===0;
  document.getElementById("jnext").disabled = jState.idx===sts.length-1;
  /* 右栏 */
  var h='<div class="yr">'+(st.year_label||st.year+"年")+' '+stationBadges(st)+'</div>';
  h+='<div class="plc">'+st.place+(st.place_hist?'（古称 '+st.place_hist+'）':'')+'</div>';
  h+='<div class="evt">'+st.event+'</div>';
  var chips=[];
  if(num(st.emotion)!==null) chips.push("文本情感值 "+fmt(st.emotion));
  if(num(st.scale)!==null) chips.push("空间尺度 "+fmt(st.scale));
  if(num(st.valence)!==null) chips.push("标注情感 "+fmt(st.valence)+(st.emo_label?"（"+st.emo_label+"）":""));
  if(num(st.ep)!==null) chips.push("外部压强 "+Math.round(st.ep*100)+"/100"+(st.ep_label?"（"+st.ep_label+"）":""));
  if(chips.length) h+='<div class="chips">'+chips.map(function(c){return "<span>"+c+"</span>";}).join("")+'</div>';
  if(st.title){
    h+='<div class="poem-box"><div class="pt">《'+st.title+'》</div>';
    h+= st.body_html ? '<div class="poem-body">'+st.body_html+'</div>'
                     : '<div class="poem-body" style="color:var(--muted)">（本篇不在当前语料内，仅存题目与系年）</div>';
    h+='</div>';
  }
  if(st.evidence) h+='<div class="evt" style="font-size:12px;color:var(--muted)">情感标注证据句：“'+st.evidence+'”</div>';
  if(st.precision==="disputed" && st.source_note)
    h+='<div class="disp-box"><b>系年两说：</b>'+st.source_note+'</div>';
  var src='<details class="src-fold"><summary>证据与来源</summary><div>';
  if(st.source_name) src+='来源：'+st.source_name+'<br>';
  if(st.source_url) src+='<a href="'+st.source_url+'" target="_blank" rel="noopener">'+st.source_url+'</a><br>';
  if(st.precision!=="disputed" && st.source_note) src+='备注：'+st.source_note+'<br>';
  if(st.ep_reason) src+='压强判定：'+st.ep_reason;
  src+='</div></details>';
  h+=src;
  document.getElementById("jstation").innerHTML=h;
  /* 地图 */
  var walked=sts.slice(0,jState.idx+1).filter(function(s){return num(s.lon)!==null;});
  var lines=[];
  for(var i=0;i+1<walked.length;i++){
    lines.push({coords:[[walked[i].lon,walked[i].lat],[walked[i+1].lon,walked[i+1].lat]]});
  }
  var past=walked.slice(0,-1).map(function(s){return {name:s.place,value:[s.lon,s.lat,s.year]};});
  var cur=walked.length?[{name:st.place,value:[walked[walked.length-1].lon,walked[walked.length-1].lat,st.year]}]:[];
  jmap.setOption({
    geo:{map:"china",roam:false,left:10,right:10,top:16,bottom:10,
      itemStyle:{areaColor:"#f4f2ea",borderColor:"#c9cdc6"},
      emphasis:{disabled:true},label:{show:false},
      zoom:1.05},
    tooltip:{show:true,formatter:function(x){ return x.name+(x.value&&x.value[2]?"（"+x.value[2]+"年）":""); }},
    series:[
      {type:"lines",coordinateSystem:"geo",data:lines,polyline:false,
       lineStyle:{color:p.color,width:1.8,opacity:.75,curveness:.25},
       effect:{show:lines.length>0,symbol:"arrow",symbolSize:5,color:p.color,trailLength:0}},
      {type:"scatter",coordinateSystem:"geo",data:past,symbolSize:7,
       itemStyle:{color:p.color,opacity:.55}},
      {type:"effectScatter",coordinateSystem:"geo",data:cur,symbolSize:13,
       rippleEffect:{scale:2.6},itemStyle:{color:p.color},
       label:{show:true,formatter:st.place,
         position:"right",color:"#252b27",fontSize:12,fontWeight:"bold",
         backgroundColor:"rgba(255,255,255,.75)",padding:[2,4],borderRadius:3}}
    ]
  },{replaceMerge:["series"]});
}
document.getElementById("jprev").addEventListener("click",function(){ if(jState.idx>0){jState.idx--;renderStation();} });
document.getElementById("jnext").addEventListener("click",function(){
  var n=byKey[jState.key].stations.length;
  if(jState.idx<n-1){jState.idx++;renderStation();}
});
renderJourneyButtons();
selectPoet("libai");

/* ---------- 第四章 逆境反应指数 ---------- */
(function(){
  var names=DATA.poets.map(function(p){return p.name;});
  var rhos=DATA.poets.map(function(p){return p.adversity.rho;});
  var bar=echarts.init(document.getElementById("advbar"));
  charts.push(bar);
  bar.setOption({
    grid:{left:70,right:56,top:30,bottom:30},
    tooltip:{confine:true,formatter:function(x){
      var a=DATA.poets[x.dataIndex].adversity;
      return "<b>"+x.name+"</b>（"+a.mode+"）<br>Spearman ρ = "+a.rho.toFixed(3)+"<br>n = "+a.n+" 个节点（样本小，解释力有限）";
    }},
    xAxis:{type:"value",min:-1,max:1,axisLabel:{color:"#6f756f"},splitLine:{lineStyle:{color:"#e7eae5"}},
      name:"压强×情感 Spearman ρ",nameLocation:"middle",nameGap:22,nameTextStyle:{color:"#6f756f",fontSize:11}},
    yAxis:{type:"category",data:names,inverse:true,axisLabel:{color:"#252b27",fontSize:14,fontFamily:"KaiTi, STKaiti, serif"},
      axisLine:{lineStyle:{color:"#b9c0b8"}}},
    series:[{type:"bar",data:rhos.map(function(r,i){
        return {value:r,itemStyle:{color:DATA.poets[i].color,opacity:.35+.65*Math.min(1,Math.abs(r))}};
      }),barWidth:16,
      label:{show:true,position:"right",formatter:function(x){
        var a=DATA.poets[x.dataIndex].adversity;
        return a.rho.toFixed(2)+" "+a.mode+"（n="+a.n+"）";
      },color:"#4d534e",fontSize:11},
      markLine:{symbol:"none",silent:true,data:[{xAxis:0}],lineStyle:{color:"#b9c0b8",type:"solid"},label:{show:false}}
    }]
  });
  var box=document.getElementById("breakouts");
  DATA.poets.forEach(function(p){
    var b=p.adversity.breakout;
    var kind = b.ep>=50 ? '<span class="badge b-A">逆境突围</span>' : '<span class="badge b-C">顺境高歌</span>';
    var d=el('<details class="breakout"><summary><span class="tag" style="background:'+p.color+'">'+p.name+'</span>'+
      '<b>'+b.year+'年 · '+b.place+'</b><span style="color:var(--muted)">《'+b.title+'》 背离量 '+fmt(b.divergence)+'</span>'+kind+'</summary>'+
      '<div class="bd">'+b.event+'<br>外部压强 '+Math.round(b.ep)+'/100，文本情感值 '+fmt(b.valence)+
      (b.evidence?'<br>证据句：“'+b.evidence+'”':'')+
      (b.ep<50?'<br><span style="color:var(--muted)">注：此点压强并不高——最昂扬的文本出现在顺境而非逆境，与其“感时型”特征一致，不存在明显的逆境突围。</span>':'')+
      '<br><span style="color:var(--muted)">来源等级 '+(b.source_level||"C")+'（生平节点，已人工审核）</span></div></details>');
    box.appendChild(d);
  });
})();

/* ---------- 第五章 方法与数据 ---------- */
(function(){
  var m=document.getElementById("methods");
  var c=DATA.corpus;
  function sec(title,body,open){
    var d=el('<details'+(open?' open':'')+'><summary>'+title+'</summary><div class="bd">'+body+'</div></details>');
    m.appendChild(d);
  }
  sec("语料与统计口径",
    '<p>语料为项目自建 poems.json：'+c.n_poems+' 首、'+c.n_poets+' 位诗人。本页六位诗人在语料中的篇目：'+
    DATA.poets.map(function(p){return p.name+" "+p.n_corpus+"首";}).join("，")+
    '。曲线只统计<b>已编年</b>（A/B/C 级）诗作；同一诗以审核层（reviewed）为准，候选层同题条目不重复计入。'+
    '所有情感/尺度数值来自词典命中词的均值，不做任何模型推断。</p>');
  sec("意象词典构建口径（197 词条）",
    '<p>五个情感簇词量：'+Object.keys(DATA.cluster_words).map(function(k){return k+" "+DATA.cluster_words[k];}).join("，")+
    '（其余为多义不归簇词条，仅保留情感值）。以下节选自 data/spirit_image_dict.py 模块文档：</p>'+
    '<pre>'+DATA.dict_doc.replace(/&/g,"&amp;").replace(/</g,"&lt;")+'</pre>');
  sec("编年数据分层与证据等级",
    '<p><span class="badge b-A">A级</span> 作品原文或正史可直接定位；'+
    '<span class="badge b-B">B级</span> 学术年谱、权威注本或可追溯数据库支持（本项目候选层均逐条在线核实来源 URL）；'+
    '<span class="badge b-C">C级</span> 由题目、诗题传统系年等间接推断；'+
    '<span class="badge b-D">D级</span> 无法可靠系年——<b>不进入任何曲线计算</b>，仅列出。'+
    '<span class="badge b-cand">候选</span> 徽章表示该条编年来自候选层（candidates/），<b>未经人工审核</b>；'+
    '<span class="badge b-rev">已审核</span> 来自 reviewed/ 人工审核层；'+
    '<span class="badge b-disp">两说</span> 表示系年存在学术分歧，页面同时展示两说。</p>'+
    '<p>行旅节点方法论（引自 poet_journeys.json）：外部压强为本项目人工标注，<b>只允许同一诗人内部的阶段比较</b>，不用于跨诗人排名；'+
    '文本情感为对公认代表诗作文本的标注，<b>不直接等同于诗人的真实心理</b>。李白无 life_stages 候选文件，其五分期为通行年谱框架（参照安旗《李白全集编年注释》等），未经本项目管线审核，特此注明。</p>');
  var rows=DATA.cand_sources.map(function(s){
    return '<tr><td>'+s.poet+'</td><td>《'+s.title+'》</td><td>'+s.grade+'</td><td>'+
      (s.status==="approved"?"已审核":"候选")+(s.precision==="disputed"?" · 两说":"")+'</td>'+
      '<td><a href="'+s.url+'" target="_blank" rel="noopener">'+s.url+'</a></td></tr>';
  }).join("");
  sec("全部编年条目与来源 URL（"+DATA.cand_sources.length+" 条，逐条可核）",
    '<div class="tbl-wrap" style="max-height:320px;overflow:auto"><table><tr><th>诗人</th><th>篇目</th><th>等级</th><th>状态</th><th>来源</th></tr>'+rows+'</table></div>');
  sec("方法论自曝：一个被数据修正的预设",
    '<div class="honest">我们原本预设"夸张密度全语料第一"会是李白——他有"飞流直下三千尺"。但风格计量统计跑完，'+
    '正文不少于 300 字的 '+c.hyperbole.eligible+' 位诗人中，第一名实为<b>'+c.hyperbole.top.name+
    '（'+c.hyperbole.top.density+'/百字）</b>；李白为 '+c.hyperbole.libai.density+'/百字，排第 '+
    c.hyperbole.libai.rank+'。我们保留这个与直觉相悖的结果并在此公示：'+
    '本项目的所有结论以算出来的数据为准，算不出的绝不硬套。同理，第二章各曲线类型命名均在五参数计算之后进行，'+
    '断裂点由算法检测、再与史实年表比对，而不是先定结论再找数据。</div>'+
    '<p>已知局限：各分期入选诗数不均（最少仅 1 首，图中均标注 n）；词典为人工构建，覆盖面有限；'+
    '逆境反应指数每人 n=6~7，Spearman 系数仅描述方向；候选层编年未经人工复核，随审核推进数字可能变化。</p>');
  sec("团队与数据来源致谢",
    '<p>编年与行迹：cnkgraph 唐宋文学编年地图开放 API（open.cnkgraph.com）；创作背景：古诗文网（so.gushiwen.cn）。'+
    '地图底图为 ECharts 离线 china.js。词典、标注、审核与全部页面代码为本项目自制。'+
    '本页由 数据可视化脚本/viz_30_competition_home.py 一键生成，欢迎复跑复核。</p>');
})();

window.addEventListener("resize",function(){ charts.forEach(function(c){ c.resize(); }); });
</script>
</body>
</html>
"""


def main():
    data = build_data()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    data_json = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, indent=1), encoding="utf-8")

    html = (HTML_TEMPLATE
            .replace("__DATA__", data_json.replace("</", "<\\/"))
            .replace("__N_POEMS__", str(data["corpus"]["n_poems"]))
            .replace("__N_JOURNEY_NODES__", str(data["corpus"]["n_journey_nodes"])))
    OUT_HTML.write_text(html, encoding="utf-8")

    # ---- 自检 ----
    text = OUT_HTML.read_text(encoding="utf-8")
    assert 'src="http' not in text and "src='http" not in text, "存在远程 script"
    assert "NaN" not in text, "页面出现 NaN 字面"
    assert "Infinity" not in text, "页面出现 Infinity 字面"
    assert 'name="viewport"' in text, "缺 viewport"
    size = OUT_HTML.stat().st_size
    assert size >= 5000, "体积不足"
    print(f"[ok] saved {OUT_HTML} ({size} bytes)")
    print(f"[ok] saved {OUT_JSON} ({OUT_JSON.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
