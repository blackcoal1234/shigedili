# -*- coding: utf-8 -*-
"""viz_32 身与心双层地图

生成：
  output/32_身与心双层地图.html
  output/assets/competition/dualmap_data.json

口径（与页面"方法与数据"折叠区一致）：
- 身层：data/reviewed/poet_journeys.json 人工审核节点按年连线。
- 心层：扫描 poems.json 中该诗人全部诗正文，用 data/place_dict.py（仅取
  两字及以上古名，剔除单字古称防误匹配）做最长匹配，提取"诗中提及地"；
  与创作地同城（县级归一后比较）的提及不入心层，单独计数。
- 弧线：有编年创作地（reviewed 已审核优先，candidates 候选次之，D 级剔除）
  的诗，画 创作地→提及地 弧；宽=频次，色=提及句情感值（红愁绿豪，句情感
  值 = 句内命中 spirit_image_dict 意象词情感值均值，无命中记 0）。
- 频次按"句"计：同句内同一地名重复、以及完全相同的句子重复收录（同题
  异文、组诗重出）只计一次。
- 排除规则（方法区如实列出）：阳关出现在演唱语境（叠/遍/唱/曲）按乐曲
  《阳关三叠》处理不作地名；另有人工复核排除表 STOPLIST 处理明确用典
  （塞上长城自比、蓬莱文章）与词典坐标错位（苏轼黄州"赤壁"即创作地）。
- 凸包与想象扩张系数：两层凸包用 Andrew 单调链在经纬度平面求得；面积把
  凸包顶点按正弦等积投影（R=6371km）展开后用鞋带公式计算（球面近似）；
  系数 = 心层凸包面积 / 身层凸包面积。
- 天界带：虚构/仙界地名不参与坐标与凸包，只计频次并给证据句。

零参数可复跑：python 数据可视化脚本/viz_32_dual_map.py
"""

import csv
import glob
import importlib.util
import json
import math
import os
import re
from collections import OrderedDict
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

POETS = OrderedDict([
    ("李白", "#426f94"),
    ("杜甫", "#7a5c3d"),
    ("白居易", "#26786e"),
    ("苏轼", "#b64b3f"),
    ("陆游", "#8a3b2f"),
    ("李清照", "#9c5d8f"),
])

# candidates CSV 里个别李白诗题与 poems.json 用了异题，人工核对为同一首
TITLE_ALIASES = {
    ("李白", "客中行"): "客中作",
    ("李白", "秋浦歌·其十五"): "秋浦歌十七首·十五",
    ("李白", "临路歌"): "临终歌",
}

# 天界带词表：虚构海上仙山 / 天界 / 神话地名（天姥为传说中"越人语天姥"的
# 仙化名山，按任务口径列入天界带，不入地图坐标）
CELESTIAL = [
    ("蓬莱", "海上仙山"), ("瀛洲", "海上仙山"), ("方壶", "海上仙山"),
    ("蓬壶", "海上仙山"), ("瑶台", "仙人居所"), ("天姥", "仙化名山"),
    ("银河", "天象天界"), ("银汉", "天象天界"), ("九天", "天之极高处"),
    ("九霄", "天之极高处"), ("月宫", "月中宫阙"), ("广寒", "月中宫阙"),
    ("玉京", "天帝之都"), ("天宫", "天上宫阙"), ("阆苑", "昆仑仙苑"),
    ("昆仑", "神话神山"), ("碧落", "天界"), ("紫府", "仙人居所"),
]

# 演唱语境规则：地名出现在演唱语境时按乐曲名处理，不作地理提及
SONG_CONTEXT = {
    "阳关": ("[叠遍唱曲]", "演唱语境（叠/遍/唱/曲），按乐曲《阳关三叠》处理，非指敦煌阳关"),
}

# 人工复核排除表：(诗人, 诗题, 词) -> 排除原因；方法区逐条如实列出
STOPLIST = {
    ("陆游", "书愤", "长城"):
        "“塞上长城空自许”用檀道济“万里长城”典自比，非地理提及；且词典把长城定位于北京一点，会严重扭曲心层凸包",
    ("苏轼", "赤壁赋", "赤壁"):
        "苏轼谪居黄州所游为赤鼻矶，笔下“赤壁”即创作地；词典坐标落在蒲圻赤壁，使同城排除失效，人工归入同城排除",
    ("苏轼", "念奴娇·赤壁怀古", "赤壁"):
        "同上：黄州赤鼻矶即创作地，人工归入同城排除",
    ("李白", "宣州谢朓楼饯别校书叔云", "蓬莱"):
        "“蓬莱文章建安骨”用东汉东观藏书（道家蓬莱山）典，赞文章风骨，非海上仙山",
}


def load_module(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def norm_city(s):
    """行政名归一：取最后一级（'重庆市奉节县'→'奉节'，'西安市'→'西安'）。"""
    if not s:
        return ""
    parts = re.findall(r"[^省市县区]+", s)
    return parts[-1] if parts else s


def same_city(a, b):
    na, nb = norm_city(a), norm_city(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def val_color(v):
    """情感值→颜色：负=朱红（愁），正=石绿（豪），0=灰。"""
    v = max(-1.0, min(1.0, v))
    grey = (150, 156, 150)
    tgt = (38, 120, 110) if v >= 0 else (182, 75, 63)
    t = abs(v)
    rgb = tuple(round(g + (c - g) * t) for g, c in zip(grey, tgt))
    return "#%02x%02x%02x" % rgb


def convex_hull(points):
    """Andrew 单调链，points=[(lon,lat)]，返回逆时针凸包顶点。"""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def sphere_area_km2(poly):
    """凸包顶点按正弦等积投影展开后的鞋带面积（km²，球面近似）。"""
    if len(poly) < 3:
        return 0.0
    R = 6371.0
    lam0 = sum(p[0] for p in poly) / len(poly)
    xy = [(R * math.radians(lon - lam0) * math.cos(math.radians(lat)),
           R * math.radians(lat)) for lon, lat in poly]
    s = 0.0
    for i in range(len(xy)):
        x1, y1 = xy[i]
        x2, y2 = xy[(i + 1) % len(xy)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def split_sentences(body):
    return [s.strip() for s in re.split(r"[。！？；\n]+", body) if s.strip()]


def main():
    place_mod = load_module("pd32", "data/place_dict.py")
    spirit_mod = load_module("sd32", "data/spirit_image_dict.py")

    celestial_names = {c[0] for c in CELESTIAL}

    # ---- 地名匹配表：仅两字及以上，剔除天界词 ----
    place_entries = [e for e in place_mod.PLACE_DICT
                     if len(e[0]) >= 2 and e[0] not in celestial_names]
    place_entries.sort(key=lambda e: -len(e[0]))
    place_info = {e[0]: {"modern": e[1], "prov": e[2], "lon": e[3], "lat": e[4]}
                  for e in place_entries}
    place_re = re.compile("|".join(re.escape(e[0]) for e in place_entries))
    n_single_dropped = len([e for e in place_mod.PLACE_DICT if len(e[0]) == 1])

    # 每个归一城市取首个词条坐标，保证同城多古名落同一点
    city_coord = {}
    for e in place_mod.PLACE_DICT:
        key = norm_city(e[1])
        if key and key not in city_coord:
            city_coord[key] = (e[1], float(e[3]), float(e[4]))

    # ---- 情感词典 ----
    sp_entries = sorted(spirit_mod.SPIRIT_DICT, key=lambda e: -len(e[0]))
    sp_val = {e[0]: float(e[3]) for e in sp_entries}
    sp_re = re.compile("|".join(re.escape(e[0]) for e in sp_entries))

    def sentence_valence(sent):
        vals = [sp_val[m.group(0)] for m in sp_re.finditer(sent)]
        if not vals:
            return 0.0
        return sum(vals) / len(vals)

    # ---- 诗集 ----
    poems = json.load(open(os.path.join(ROOT, "data/poems.json"), encoding="utf-8"))
    poems_by_poet = {p: [] for p in POETS}
    for pm in poems:
        if pm["author"] in poems_by_poet:
            poems_by_poet[pm["author"]].append(pm)

    # ---- 编年创作地：reviewed 优先，candidates 兜底，D 级剔除 ----
    comp = {}           # (poet, title) -> dict
    d_dropped = {p: 0 for p in POETS}

    def year_label(r):
        y1 = (r.get("year_start") or "").strip()
        y2 = (r.get("year_end") or "").strip()
        lab = y1 if (not y2 or y2 == y1) else (y1 + "-" + y2)
        if (r.get("year_precision") or "").strip() == "approximate":
            lab = "约" + lab
        return lab

    def add_comp(r, badge):
        poet = r["poet"].strip()
        if poet not in POETS:
            return
        title = TITLE_ALIASES.get((poet, r["title"].strip()), r["title"].strip())
        key = (poet, title)
        if key in comp:
            return
        try:
            lon, lat = float(r["lon"]), float(r["lat"])
        except (ValueError, TypeError, KeyError):
            return
        comp[key] = {
            "city": r.get("modern_city", "").strip(),
            "hist": r.get("historical_place", "").strip(),
            "lon": lon, "lat": lat,
            "year": year_label(r),
            "badge": badge + "·" + (r.get("fact_grade") or "?").strip(),
        }

    with open(os.path.join(ROOT, "data/reviewed/verified_poem_contexts.csv"),
              encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if (r.get("fact_grade") or "").strip() == "D":
                if r["poet"].strip() in d_dropped:
                    d_dropped[r["poet"].strip()] += 1
                continue
            add_comp(r, "已审核")

    cand_files = sorted(glob.glob(os.path.join(ROOT, "data/candidates/*_spirit_chronology*.csv")))
    for path in cand_files:
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if (r.get("status") or "").strip() != "candidate":
                    continue  # superseded_by_verified 由 reviewed 覆盖
                if (r.get("fact_grade") or "").strip() == "D":
                    if r["poet"].strip() in d_dropped:
                        d_dropped[r["poet"].strip()] += 1
                    continue
                add_comp(r, "候选")

    # ---- 身层 ----
    journeys = json.load(open(os.path.join(ROOT, "data/reviewed/poet_journeys.json"),
                              encoding="utf-8"))
    journey_by_poet = {}
    for p in journeys["poets"]:
        nodes = sorted(p["nodes"], key=lambda n: n["route_order"])
        journey_by_poet[p["poet"]] = [{
            "year": n["year"], "label": n["year_label"],
            "place": n["place_modern"], "hist": n["place_historical"],
            "lon": round(float(n["longitude"]), 4),
            "lat": round(float(n["latitude"]), 4),
            "event": n["event"], "level": n.get("source_level", "?"),
        } for n in nodes]

    # ---- 逐诗人构建 ----
    song_res = {k: (re.compile(v[0]), v[1]) for k, v in SONG_CONTEXT.items()}
    stop_applied = []       # 全部规则/人工排除的实际命中，进方法区逐条展示
    out_poets = []
    for poet, color in POETS.items():
        plist = poems_by_poet[poet]
        mentions = {}          # norm_city -> record
        arcs = {}              # (from_norm, to_norm) -> record
        excluded = 0
        kept = 0
        stopped = 0
        seen_sent = set()      # (地名, 句) 句级去重：同句重复与异文重出只计一次
        for pm in plist:
            key = (poet, pm["title"])
            cp = comp.get(key)
            for sent in split_sentences(pm["body"]):
                hits = list(place_re.finditer(sent))
                if not hits:
                    continue
                v = None
                for m in hits:
                    name = m.group(0)
                    reason = STOPLIST.get((poet, pm["title"], name))
                    if reason is None and name in song_res and song_res[name][0].search(sent):
                        reason = song_res[name][1]
                    if reason is not None:
                        stopped += 1
                        stop_applied.append({"poet": poet, "t": pm["title"],
                                             "m": name, "s": sent, "r": reason})
                        continue
                    if (name, sent) in seen_sent:
                        continue
                    seen_sent.add((name, sent))
                    info = place_info[name]
                    tgt_norm = norm_city(info["modern"])
                    if cp and same_city(info["modern"], cp["city"]):
                        excluded += 1
                        continue
                    kept += 1
                    if v is None:
                        v = round(sentence_valence(sent), 3)
                    city_disp, clon, clat = city_coord.get(
                        tgt_norm, (info["modern"], float(info["lon"]), float(info["lat"])))
                    rec = mentions.setdefault(tgt_norm, {
                        "city": city_disp, "lon": round(clon, 3), "lat": round(clat, 3),
                        "count": 0, "old": [], "ev": []})
                    rec["count"] += 1
                    if name not in rec["old"]:
                        rec["old"].append(name)
                    rec["ev"].append({
                        "t": pm["title"], "m": name, "s": sent, "v": v,
                        "b": cp["badge"] if cp else "", "y": cp["year"] if cp else ""})
                    if cp:
                        akey = (norm_city(cp["city"]), tgt_norm)
                        arec = arcs.setdefault(akey, {
                            "fc": cp["city"], "tc": city_disp,
                            "fl": [round(cp["lon"], 3), round(cp["lat"], 3)],
                            "tl": [round(clon, 3), round(clat, 3)],
                            "count": 0, "vals": [], "ev": []})
                        arec["count"] += 1
                        arec["vals"].append(v)
                        arec["ev"].append({
                            "t": pm["title"], "m": name, "s": sent, "v": v,
                            "b": cp["badge"], "y": cp["year"]})

        mention_list = sorted(mentions.values(), key=lambda r: -r["count"])
        for r in mention_list:
            r["ss"] = round(min(26.0, 7.0 + 3.4 * math.sqrt(r["count"])), 1)

        arc_list = []
        for a in sorted(arcs.values(), key=lambda r: -r["count"]):
            mv = sum(a["vals"]) / len(a["vals"])
            a["v"] = round(mv, 3)
            a["color"] = val_color(mv)
            a["w"] = round(min(6.0, 1.1 + 0.85 * a["count"]), 2)
            del a["vals"]
            arc_list.append(a)

        # 天界带（同样按句计频、句级去重、走排除表）
        sky = []
        sky_seen = set()
        for name, note in CELESTIAL:
            cnt = 0
            ev = []
            for pm in plist:
                if name not in pm["body"]:
                    continue
                for sent in split_sentences(pm["body"]):
                    if name not in sent:
                        continue
                    reason = STOPLIST.get((poet, pm["title"], name))
                    if reason is not None:
                        stopped += 1
                        stop_applied.append({"poet": poet, "t": pm["title"],
                                             "m": name, "s": sent, "r": reason})
                        continue
                    if (name, sent) in sky_seen:
                        continue
                    sky_seen.add((name, sent))
                    cnt += 1
                    if len(ev) < 30:
                        ev.append({"t": pm["title"], "s": sent})
            if cnt:
                sky.append({"name": name, "note": note, "count": cnt, "ev": ev})
        sky.sort(key=lambda s: -s["count"])

        # 凸包与系数：任一层凸包退化（不足三点/面积过小）则系数不可计算
        jpts = [(n["lon"], n["lat"]) for n in journey_by_poet.get(poet, [])]
        hpts = [(r["lon"], r["lat"]) for r in mention_list]
        hull_b = convex_hull(jpts)
        hull_h = convex_hull(hpts)
        area_b = round(sphere_area_km2(hull_b), 1)
        area_h = round(sphere_area_km2(hull_h), 1)
        coef = None
        coef_note = ""
        if len(hull_h) < 3 or area_h <= 100.0:
            coef_note = "心层可定位提及地不足（凸包退化），系数不可计算"
        elif len(hull_b) < 3 or area_b <= 100.0:
            coef_note = "身层节点凸包退化，系数不可计算"
        else:
            coef = round(area_h / area_b, 2)

        dated = sum(1 for pm in plist if (poet, pm["title"]) in comp)
        out_poets.append({
            "name": poet, "color": color,
            "journey": journey_by_poet.get(poet, []),
            "mentions": mention_list,
            "arcs": arc_list,
            "sky": sky,
            "hullBody": [[round(x, 3), round(y, 3)] for x, y in hull_b],
            "hullHeart": [[round(x, 3), round(y, 3)] for x, y in hull_h],
            "areaBody": area_b, "areaHeart": area_h,
            "coef": coef, "coefNote": coef_note,
            "stats": {
                "poems": len(plist), "dated": dated,
                "kept": kept, "excluded": excluded, "stopped": stopped,
                "places": len(mention_list), "arcs": len(arc_list),
                "skyTotal": sum(s["count"] for s in sky),
                "dDropped": d_dropped[poet],
            },
        })

    data = {
        "generated_at": date.today().isoformat(),
        "method_brief": ("身层=审核行旅节点连线；心层=诗中地名最长匹配散点（排除与创作地同城提及）；"
                         "弧=编年创作地→提及地，宽为频次、色为句情感值；系数=心层凸包面积/身层凸包面积"
                         "（正弦等积投影+鞋带公式，球面近似）。"),
        "dict_note": ("place_dict 共 %d 条，本页仅用两字及以上古名 %d 条（剔除单字古称 %d 条防误匹配），"
                      "并把天界词表 %d 词排除出坐标匹配。")
                     % (len(place_mod.PLACE_DICT), len(place_entries), n_single_dropped, len(CELESTIAL)),
        "exclusions": stop_applied,
        "poets": out_poets,
    }

    comp_dir = os.path.join(ROOT, "output", "assets", "competition")
    os.makedirs(comp_dir, exist_ok=True)
    json_path = os.path.join(comp_dir, "dualmap_data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, allow_nan=False, separators=(",", ":"))

    # ---- 方法区统计表 ----
    rows_html = []
    for p in out_poets:
        coef_disp = ("%.2f" % p["coef"]) if p["coef"] is not None else "—"
        rows_html.append(
            "<tr><td style='color:%s;font-weight:700'>%s</td><td>%d</td><td>%d</td>"
            "<td>%d</td><td>%d</td><td>%d</td><td>%.1f</td><td>%.1f</td><td>%s</td><td>%d</td><td>%d</td></tr>"
            % (p["color"], p["name"], p["stats"]["poems"], p["stats"]["dated"],
               p["stats"]["kept"], p["stats"]["excluded"], p["stats"]["stopped"],
               p["areaBody"] / 10000.0, p["areaHeart"] / 10000.0, coef_disp,
               p["stats"]["skyTotal"], p["stats"]["dDropped"]))
    stats_table = (
        "<div class='tblwrap'><table><thead><tr><th>诗人</th><th>入库诗数</th><th>有编年创作地</th>"
        "<th>心层提及句次</th><th>同城排除</th><th>规则/人工排除</th><th>身层凸包(万km²)</th><th>心层凸包(万km²)</th>"
        "<th>想象扩张系数</th><th>天界带句次</th><th>D级剔除</th></tr></thead><tbody>"
        + "".join(rows_html) + "</tbody></table></div>")

    # ---- 排除明细表（逐条如实展示） ----
    if stop_applied:
        ex_rows = "".join(
            "<tr><td>%s</td><td>《%s》</td><td>%s</td>"
            "<td style='text-align:left;white-space:normal;min-width:200px'>%s</td>"
            "<td style='text-align:left;white-space:normal;min-width:240px'>%s</td></tr>"
            % (e["poet"], e["t"], e["m"], e["s"], e["r"]) for e in stop_applied)
        excl_table = (
            "<div class='tblwrap'><table><thead><tr><th>诗人</th><th>诗题</th><th>词</th>"
            "<th>原句</th><th>排除原因</th></tr></thead><tbody>" + ex_rows + "</tbody></table></div>")
    else:
        excl_table = "<p>本次运行没有触发任何规则/人工排除。</p>"

    html = HTML_TEMPLATE
    html = html.replace("__STATS_TABLE__", stats_table)
    html = html.replace("__EXCL_TABLE__", excl_table)
    html = html.replace("__GENERATED_AT__", data["generated_at"])
    html = html.replace("__DICT_NOTE__", data["dict_note"])
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")).replace("</", "<\\/")
    html = html.replace("__DATA_JSON__", payload)

    html_path = os.path.join(ROOT, "output", "32_身与心双层地图.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print("written:", json_path, os.path.getsize(json_path), "bytes")
    print("written:", html_path, os.path.getsize(html_path), "bytes")
    for p in out_poets:
        print("%s coef=%s bodyArea=%.0f heartArea=%.0f sky=%d excluded=%d stopped=%d places=%d"
              % (p["name"], p["coef"], p["areaBody"], p["areaHeart"],
                 p["stats"]["skyTotal"], p["stats"]["excluded"],
                 p["stats"]["stopped"], p["stats"]["places"]))
    print("rule/manual exclusions:", len(stop_applied))


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>身与心的双层地图 · 诗行万里参赛版</title>
<script src="assets/pyecharts/v6/echarts.min.js"></script>
<script src="assets/pyecharts/v6/maps/china.js"></script>
<style>
:root{--paper:#f2f4f0;--ink:#252b27;--cinnabar:#b64b3f;--jade:#26786e;--gold:#a87527;--blue:#426f94;--line:#d7ddd4;--muted:#6b7370;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--paper);color:var(--ink);font-family:"Microsoft YaHei","PingFang SC",sans-serif;line-height:1.6;}
h1,h2,h3,.kai{font-family:KaiTi,STKaiti,"Kaiti SC",serif;}
.wrap{max-width:1380px;margin:0 auto;padding:18px 20px 30px;}
header.top{border-bottom:2px solid var(--ink);padding:14px 4px 12px;margin-bottom:14px;}
header.top h1{font-size:30px;letter-spacing:2px;}
header.top .sub{color:var(--muted);font-size:13.5px;margin-top:4px;}
.badge{display:inline-block;font-size:11.5px;border:1px solid var(--gold);color:var(--gold);border-radius:3px;padding:0 6px;margin-left:8px;vertical-align:2px;}
.tabs{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 14px;}
.tabs button{font-family:KaiTi,STKaiti,serif;font-size:17px;letter-spacing:2px;padding:5px 16px;border-radius:3px;cursor:pointer;background:transparent;border:1.5px solid var(--pc,#888);color:var(--pc,#555);transition:all .15s;}
.tabs button.on{background:var(--pc);color:#f7f8f5;}
.grid{display:grid;grid-template-columns:minmax(0,1fr) 372px;gap:14px;align-items:start;}
.card{background:#fbfcfa;border:1px solid var(--line);border-radius:6px;box-shadow:0 1px 3px rgba(37,43,39,.06);}
.mapcard{position:relative;overflow:hidden;}
.sky{border-bottom:1px dashed #b9c2ba;background:linear-gradient(180deg,#e8ecf2 0%,#f2f4f0 100%);padding:7px 12px 8px;min-height:44px;}
.sky .skytitle{font-family:KaiTi,STKaiti,serif;font-size:13px;color:var(--blue);margin-right:8px;white-space:nowrap;}
.sky .chips{display:inline;}
.sky .chip{display:inline-block;border:1px solid var(--blue);color:var(--blue);background:rgba(66,111,148,.08);border-radius:12px;padding:0 9px;margin:2px 4px 2px 0;cursor:pointer;line-height:1.75;}
.sky .chip b{font-family:KaiTi,STKaiti,serif;}
.sky .chip small{opacity:.75;margin-left:3px;}
.sky .none{color:var(--muted);font-size:12.5px;}
#map{width:100%;height:600px;}
.coefchip{position:absolute;right:12px;top:58px;background:rgba(251,252,250,.92);border:1px solid var(--line);border-left:3px solid var(--gold);border-radius:4px;padding:6px 12px;font-size:12.5px;box-shadow:0 1px 4px rgba(37,43,39,.08);z-index:5;}
.coefchip .num{font-size:23px;font-family:KaiTi,STKaiti,serif;color:var(--gold);line-height:1.15;}
.layers{display:flex;flex-wrap:wrap;gap:8px;padding:9px 12px;border-top:1px solid var(--line);font-size:12.5px;}
.layers button{border:1px solid var(--line);background:#fff;border-radius:3px;padding:2px 10px;cursor:pointer;color:var(--muted);font-size:12.5px;}
.layers button.on{border-color:var(--ink);color:var(--ink);background:#eef1ec;}
.legend{margin-left:auto;color:var(--muted);display:flex;gap:12px;flex-wrap:wrap;align-items:center;}
.lg{display:inline-flex;align-items:center;gap:4px;}
.lg i{display:inline-block;width:16px;height:0;border-top:3px solid;}
.lg .dot{width:9px;height:9px;border-radius:50%;border:none;}
aside .card{margin-bottom:14px;padding:13px 15px;}
aside h3{font-size:17px;letter-spacing:1px;border-left:4px solid var(--pc,#888);padding-left:8px;margin-bottom:8px;}
.coefline{font-size:13px;color:var(--muted);}
.coefline b{color:var(--ink);}
#bar{width:100%;height:224px;}
.evbox{max-height:380px;overflow-y:auto;font-size:13px;}
.evbox .hint{color:var(--muted);font-size:12.5px;}
.ev{border-bottom:1px dashed var(--line);padding:7px 2px;}
.ev .t{font-weight:700;}
.ev .s{color:#3d4642;margin-top:1px;}
.ev mark{background:rgba(168,117,39,.22);color:inherit;padding:0 1px;border-radius:2px;}
.vchip{display:inline-block;font-size:11px;border-radius:3px;padding:0 5px;color:#fff;margin-left:6px;vertical-align:1px;}
.bchip{display:inline-block;font-size:11px;border:1px solid var(--gold);color:var(--gold);border-radius:3px;padding:0 5px;margin-left:6px;vertical-align:1px;}
details.method{margin-top:16px;background:#fbfcfa;border:1px solid var(--line);border-radius:6px;padding:12px 16px;font-size:13px;}
details.method summary{font-family:KaiTi,STKaiti,serif;font-size:16px;cursor:pointer;letter-spacing:1px;}
details.method h4{margin:10px 0 4px;font-size:14px;color:var(--jade);}
details.method li{margin-left:20px;margin-top:2px;}
.tblwrap{overflow-x:auto;margin-top:8px;}
table{border-collapse:collapse;font-size:12.5px;white-space:nowrap;}
th,td{border:1px solid var(--line);padding:4px 9px;text-align:center;}
th{background:#eef1ec;font-weight:600;}
footer.navbar{margin-top:20px;border-top:2px solid var(--ink);padding:12px 4px 4px;font-size:13px;display:flex;flex-wrap:wrap;gap:6px 14px;}
footer.navbar a{color:var(--blue);text-decoration:none;}
footer.navbar a:hover{text-decoration:underline;}
footer.navbar .cur{color:var(--cinnabar);font-weight:700;}
footer.navbar .home{font-weight:700;}
@media (max-width:980px){
 .grid{grid-template-columns:minmax(0,1fr);}
 #map{height:430px;}
 header.top h1{font-size:24px;}
 .coefchip{position:static;border-left-width:3px;border-radius:0;box-shadow:none;border-top:1px solid var(--line);border-right:none;border-bottom:none;}
 .evbox{max-height:300px;}
}
</style>
</head>
<body>
<div class="wrap">
<header class="top">
 <h1>身与心的双层地图<span class="badge">编年多为候选/推定</span></h1>
 <div class="sub">身层：诗人亲历的行旅节点（审核数据，实线）。心层：他们在诗里"想去/想到"的地名（半透明散点与弧线）。两层凸包之比，即"想象扩张系数"——脚走了多远，心又走了多远。</div>
</header>

<div class="tabs" id="tabs"></div>

<div class="grid">
 <section class="card mapcard">
  <div class="sky"><span class="skytitle">天界带 · 不入坐标</span><span class="chips" id="skychips"></span></div>
  <div id="map"></div>
  <div class="coefchip">想象扩张系数<div class="num" id="coefnum">—</div><span id="coefsub" style="color:var(--muted)"></span></div>
  <div class="layers">
   <button id="ly-body" class="on">身层·行旅</button>
   <button id="ly-heart" class="on">心层·提及</button>
   <button id="ly-arcs" class="on">创作地→提及地弧</button>
   <button id="ly-hull" class="on">双凸包</button>
   <span class="legend">
    <span class="lg"><i style="border-color:#7d8580"></i>身层实边凸包</span>
    <span class="lg"><i style="border-top-style:dashed;border-color:#7d8580"></i>心层虚边凸包</span>
    <span class="lg"><i style="border-color:#b64b3f"></i>愁</span>
    <span class="lg"><i style="border-color:#26786e"></i>豪</span>
   </span>
  </div>
 </section>

 <aside>
  <div class="card" id="coefcard">
   <h3 id="asideTitle">想象扩张系数</h3>
   <div class="coefline" id="coefline"></div>
  </div>
  <div class="card">
   <h3>六人系数对比</h3>
   <div id="bar"></div>
  </div>
  <div class="card">
   <h3>证据句</h3>
   <div class="evbox" id="evbox"><div class="hint">点击地图上的散点、弧线、行旅节点，或天界带芯片，这里会列出对应的证据句。统计数字都可以追溯到具体诗句。</div></div>
  </div>
 </aside>
</div>

<details class="method">
 <summary>方法与数据（口径与局限）</summary>
 <h4>数据来源</h4>
 <ul>
  <li>身层：data/reviewed/poet_journeys.json 六诗人 38 个人工审核行旅节点（A/B/C 分级），连线只表示节点时间先后，不代表实际路线。</li>
  <li>心层：data/poems.json 六诗人全部入库诗作正文；地名匹配用 data/place_dict.py 最长匹配。__DICT_NOTE__</li>
  <li>编年创作地：data/reviewed/verified_poem_contexts.csv（已审核）优先，data/candidates/ 六人编年候选表（候选/推定，页面弧线证据带徽章）兜底；<b>D 级一律不入计算</b>。</li>
  <li>句情感值：data/spirit_image_dict.py 197 词条（人工整理词典，非模型输出），句内命中意象词情感值取均值，无命中记 0（灰）。</li>
 </ul>
 <h4>心层与弧线口径</h4>
 <ul>
  <li>频次按"句"计：同一句内同一地名重复出现、以及完全相同的句子被重复收录（同题异文、组诗与选本重出，如《忆江南》与《忆江南词三首》首句）只计一次。</li>
  <li>与创作地同城（行政名取县级归一后比较）的提及不入心层——写当地不算"心的远行"；排除次数见下表。</li>
  <li>只有具备编年创作地的诗才画 创作地→提及地 弧线；弧宽=该城市对的提及频次，弧色=提及句情感值（红=愁、绿=豪、灰=中性）。</li>
  <li>无编年创作地的诗，其提及地仍画半透明散点（无法画弧）。</li>
 </ul>
 <h4>规则与人工复核排除（逐条明细）</h4>
 <ul>
  <li>演唱语境规则："阳关"与 叠/遍/唱/曲 同句时按乐曲《阳关三叠》处理，不作地名（否则李清照的"千万遍阳关"会被错标到敦煌）。</li>
  <li>人工复核排除表：仅限明确用典或词典坐标错位的个案，逐条列出原句与理由，接受复核；本页不做任何未记录的手工删改。</li>
 </ul>
 __EXCL_TABLE__
 <h4>想象扩张系数算法（球面近似）</h4>
 <ul>
  <li>身层凸包：行旅节点经纬度用 Andrew 单调链求凸包；心层凸包：心层散点同法。</li>
  <li>面积：把凸包顶点按正弦等积投影（中央经线取顶点均值，地球半径 6371km）展开为平面坐标，再用鞋带公式求多边形面积。正弦投影严格等积，中国尺度下与球面多边形面积的偏差远小于坐标本身的近似误差。</li>
  <li>系数 = 心层凸包面积 ÷ 身层凸包面积。<b>任一层</b>凸包退化（顶点不足三个或面积≤100km²）时系数记"—"，不记 0——两处提及地围不出面积，不代表想象为零，只代表可定位样本不足。</li>
 </ul>
 <h4>天界带</h4>
 <ul>
  <li>蓬莱、瀛洲、瑶台、天姥、银河、九天、月宫、广寒、玉京、昆仑等 18 个虚构或天界地名不赋坐标、不入凸包，只在地图上缘计频展示；点击芯片可看证据句。天姥山今虽有实景，诗中多作仙化名山使用，按任务口径归入天界带。</li>
 </ul>
 <h4>局限（如实呈现）</h4>
 <ul>
  <li>编年创作地大多为 B 级候选/推定，弧线位置随考订可能变化；证据句均带来源徽章。</li>
  <li>字典匹配无法完全排除借代与用典：明确个案已入上方排除表，但边界仍存——如李清照"念武陵人远"之"武陵"用桃源典指远行之人，本页仍按地名保留并可点开原句复核；"江南"等泛称按词典折算为代表城市（苏州），粒度较粗。提及≠亲往，也≠向往，只表示"该地名进入了诗人的文字世界"。</li>
  <li>句情感值来自人工词典，粒度粗，只用于弧线着色的相对比较，不构成对诗句的权威解读。</li>
  <li>各诗人入库诗数不同（实时篇数见下方“六人计算明细”），系数横向对比时应注意样本差异；系数反映"提及地理范围/亲历地理范围"，不是心理测量。</li>
 </ul>
 <h4>六人计算明细</h4>
 __STATS_TABLE__
 <div style="color:var(--muted);margin-top:8px;">数据快照生成于 __GENERATED_AT__；同源数据文件：assets/competition/dualmap_data.json。</div>
</details>

<footer class="navbar">
 <a href="29_参赛导航.html">29 参赛导航</a>
 <a class="home" href="30_诗行万里_参赛版.html">30 总入口</a>
 <a href="31_凝望罗盘.html">31 凝望罗盘</a>
 <span class="cur">32 身与心双层地图</span>
 <a href="33_平行时空759.html">33 平行时空759</a>
 <a href="34_一字识诗人.html">34 一字识诗人</a>
 <a href="35_两种孤独与夸张签名.html">35 两种孤独与夸张签名</a>
 <a href="36_同龄对齐.html">36 同龄对齐</a>
 <a href="37_可听的诗.html">37 可听的诗</a>
 <a href="38_唐宋意象潮汐.html">38 意象潮汐</a>
 <a href="39_诗人自述生命卷.html">39 诗人自述生命卷</a>
</footer>
</div>

<script>
var DATA = __DATA_JSON__;
</script>
<script>
(function(){
"use strict";
var byName = {};
DATA.poets.forEach(function(p){ byName[p.name] = p; });
var state = { poet: "李白", layers: { body:true, heart:true, arcs:true, hull:true } };

function esc(s){
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function fmt(x, d){
  if (x === null || x === undefined || x !== x) return "—";
  return Number(x).toFixed(d === undefined ? 2 : d);
}
function rgba(hex, a){
  var r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
  return "rgba(" + r + "," + g + "," + b + "," + a + ")";
}
function wan(km2){ return fmt(km2/10000, 1); }

/* ---------- 诗人切换标签 ---------- */
var tabsEl = document.getElementById("tabs");
DATA.poets.forEach(function(p){
  var b = document.createElement("button");
  b.textContent = p.name;
  b.style.setProperty("--pc", p.color);
  b.onclick = function(){ switchPoet(p.name); };
  b.id = "tab-" + p.name;
  tabsEl.appendChild(b);
});

/* ---------- 地图 ---------- */
var chart = echarts.init(document.getElementById("map"));

function hullSeries(name, pts, dashed){
  return {
    name: name, type: "custom", coordinateSystem: "geo",
    silent: true, z: 1, data: [0],
    renderItem: function(params, api){
      if (!pts || pts.length < 3) return null;
      var poly = pts.map(function(pt){ return api.coord(pt); });
      return { type: "polygon", shape: { points: poly },
        style: { fill: "rgba(125,133,128,0.09)", stroke: "#7d8580", lineWidth: 1.6,
                 lineDash: dashed ? [6,5] : null } };
    }
  };
}

function buildOption(p){
  var series = [];
  if (state.layers.hull){
    series.push(hullSeries("身层凸包", p.hullBody, false));
    series.push(hullSeries("心层凸包", p.hullHeart, true));
  }
  if (state.layers.arcs){
    series.push({
      name: "arc", type: "lines", coordinateSystem: "geo", zlevel: 2,
      lineStyle: { curveness: 0.26 },
      emphasis: { lineStyle: { width: 6, opacity: 1 } },
      data: p.arcs.map(function(a){
        return { coords: [a.fl, a.tl],
          lineStyle: { width: a.w, color: a.color, opacity: 0.62, curveness: 0.26 },
          _arc: a };
      })
    });
  }
  if (state.layers.body){
    series.push({
      name: "route", type: "lines", coordinateSystem: "geo", polyline: true,
      zlevel: 3, silent: true,
      lineStyle: { width: 2.6, color: p.color, opacity: 0.95 },
      data: [{ coords: p.journey.map(function(n){ return [n.lon, n.lat]; }) }]
    });
    series.push({
      name: "jnode", type: "scatter", coordinateSystem: "geo", zlevel: 3,
      symbolSize: 11,
      itemStyle: { color: p.color, borderColor: "#f7f8f5", borderWidth: 1.5 },
      label: { show: true, position: "top", fontSize: 10, color: "#252b27",
               formatter: function(d){ return d.data._j.year; } },
      data: p.journey.map(function(n){ return { value: [n.lon, n.lat], _j: n }; })
    });
  }
  if (state.layers.heart){
    series.push({
      name: "mention", type: "scatter", coordinateSystem: "geo", zlevel: 2,
      itemStyle: { color: rgba(p.color, 0.42), borderColor: rgba(p.color, 0.85), borderWidth: 1 },
      emphasis: { itemStyle: { color: rgba(p.color, 0.8) } },
      data: p.mentions.map(function(m){
        return { value: [m.lon, m.lat], symbolSize: m.ss, _m: m };
      })
    });
  }
  return {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item", confine: true,
      backgroundColor: "rgba(251,252,250,.96)", borderColor: "#d7ddd4",
      textStyle: { color: "#252b27", fontSize: 12 },
      formatter: function(params){
        var d = params.data || {};
        if (d._j){
          return "<b>" + esc(d._j.year) + " · " + esc(d._j.place) + "</b><br>" +
                 esc(d._j.event) + "<br><span style='color:#6b7370'>来源分级 " +
                 esc(d._j.level) + " · 点击看详情</span>";
        }
        if (d._m){
          return "<b>" + esc(d._m.city) + "</b>（诗中作 " + esc(d._m.old.join("、")) + "）<br>提及 " +
                 d._m.count + " 次 · 点击看证据句";
        }
        if (d._arc){
          return "<b>" + esc(d._arc.fc) + " → " + esc(d._arc.tc) + "</b><br>频次 " + d._arc.count +
                 " · 句情感均值 " + fmt(d._arc.v) + "<br><span style='color:#6b7370'>点击看证据句</span>";
        }
        return "";
      }
    },
    geo: {
      map: "china", roam: true, zoom: 1.06, center: [105.5, 34.8],
      itemStyle: { areaColor: "#e9ede7", borderColor: "#b9c2ba", borderWidth: 0.6 },
      emphasis: { disabled: true },
      label: { show: false },
      select: { disabled: true }
    },
    series: series
  };
}

/* ---------- 证据面板 ---------- */
var evbox = document.getElementById("evbox");
function vchip(v){
  if (v === null || v === undefined || v !== v) return "";
  var c = v > 0.05 ? "#26786e" : (v < -0.05 ? "#b64b3f" : "#969c96");
  return "<span class='vchip' style='background:" + c + "'>" + fmt(v, 2) + "</span>";
}
function bchip(b){ return b ? "<span class='bchip'>" + esc(b) + "</span>" : ""; }
function evLine(e){
  var s = esc(e.s).split(esc(e.m)).join("<mark>" + esc(e.m) + "</mark>");
  return "<div class='ev'><div class='t'>《" + esc(e.t) + "》" +
         (e.y ? "<span style='color:#6b7370;font-weight:400'> · " + esc(e.y) + "年</span>" : "") +
         bchip(e.b) + vchip(e.v) + "</div><div class='s'>" + s + "</div></div>";
}
function showMention(m){
  var h = "<div class='hint'>心层提及地 <b>" + esc(m.city) + "</b>（诗中作 " +
          esc(m.old.join("、")) + "）· 共 " + m.count + " 次</div>";
  m.ev.forEach(function(e){ h += evLine(e); });
  evbox.innerHTML = h;
}
function showArc(a){
  var h = "<div class='hint'>弧线 <b>" + esc(a.fc) + " → " + esc(a.tc) + "</b> · 频次 " + a.count +
          " · 句情感均值 " + fmt(a.v) + "（红愁绿豪）</div>";
  a.ev.forEach(function(e){ h += evLine(e); });
  evbox.innerHTML = h;
}
function showJourney(n){
  evbox.innerHTML = "<div class='hint'>身层行旅节点（审核数据）</div>" +
    "<div class='ev'><div class='t'>" + esc(n.label) + " · " + esc(n.hist) +
    "（今" + esc(n.place) + "）<span class='bchip'>来源 " + esc(n.level) + " 级</span></div>" +
    "<div class='s'>" + esc(n.event) + "</div></div>";
}
function showSky(s){
  var h = "<div class='hint'>天界带 <b>" + esc(s.name) + "</b>（" + esc(s.note) + "）· 出现 " +
          s.count + " 次 · 不入地图坐标与凸包</div>";
  s.ev.forEach(function(e){
    var line = esc(e.s).split(esc(s.name)).join("<mark>" + esc(s.name) + "</mark>");
    h += "<div class='ev'><div class='t'>《" + esc(e.t) + "》</div><div class='s'>" + line + "</div></div>";
  });
  evbox.innerHTML = h;
}
chart.on("click", function(params){
  var d = params.data || {};
  if (d._m) showMention(d._m);
  else if (d._arc) showArc(d._arc);
  else if (d._j) showJourney(d._j);
});

/* ---------- 天界带 ---------- */
function renderSky(p){
  var el = document.getElementById("skychips");
  if (!p.sky.length){
    el.innerHTML = "<span class='none'>该诗人入库诗中未出现天界地名</span>";
    return;
  }
  var h = "";
  p.sky.forEach(function(s){
    var fs = Math.min(17, 12 + s.count * 0.5);
    h += "<span class='chip' data-name='" + esc(s.name) + "' style='font-size:" + fs +
         "px'><b>" + esc(s.name) + "</b><small>×" + s.count + "</small></span>";
  });
  el.innerHTML = h;
  Array.prototype.forEach.call(el.querySelectorAll(".chip"), function(c){
    c.onclick = function(){
      var name = c.getAttribute("data-name");
      var s = null;
      p.sky.forEach(function(x){ if (x.name === name) s = x; });
      if (s) showSky(s);
    };
  });
}

/* ---------- 系数展示 ---------- */
function renderCoef(p){
  var noCoef = (p.coef === null || p.coef === undefined);
  document.getElementById("coefnum").textContent = noCoef ? "—" : "×" + fmt(p.coef);
  document.getElementById("coefsub").textContent = noCoef && p.coefNote ? p.coefNote :
    "心 " + wan(p.areaHeart) + " / 身 " + wan(p.areaBody) + " 万km²";
  document.getElementById("asideTitle").textContent = p.name + " · 想象扩张系数";
  document.getElementById("asideTitle").style.setProperty("--pc", p.color);
  document.getElementById("coefline").innerHTML =
    "身层凸包（亲历）<b>" + wan(p.areaBody) + "</b> 万km² · 心层凸包（提及）<b>" + wan(p.areaHeart) +
    "</b> 万km²<br>系数 = 心/身 = <b>" + (noCoef ? "—" : fmt(p.coef)) + "</b>" +
    (noCoef && p.coefNote ? "<br><span style='color:var(--cinnabar)'>" + esc(p.coefNote) + "</span>" : "") +
    "<br>入库 " + p.stats.poems + " 首 · 编年 " + p.stats.dated + " 首 · 提及地 " + p.stats.places +
    " 处 " + p.stats.kept + " 句次（另排除：同城 " + p.stats.excluded + " · 规则/人工 " + p.stats.stopped +
    "）· 弧 " + p.stats.arcs + " 组 · 天界带 " + p.stats.skyTotal + " 句次";
}

/* ---------- 六人系数条形图 ---------- */
var bar = echarts.init(document.getElementById("bar"));
function renderBar(){
  var names = DATA.poets.map(function(p){ return p.name; });
  bar.setOption({
    grid: { left: 8, right: 44, top: 8, bottom: 4, containLabel: true },
    xAxis: { type: "value", axisLabel: { color: "#6b7370", fontSize: 11 },
             splitLine: { lineStyle: { color: "#e3e8e0" } } },
    yAxis: { type: "category", inverse: true, data: names,
             axisLabel: { color: "#252b27", fontSize: 13, fontFamily: "KaiTi,STKaiti,serif" },
             axisLine: { lineStyle: { color: "#b9c2ba" } }, axisTick: { show: false } },
    tooltip: { trigger: "item", formatter: function(pr){
      var p = byName[pr.name];
      return pr.name + "：系数 " + (p.coef === null ? "—" : fmt(p.coef)) +
             "<br>心 " + wan(p.areaHeart) + " / 身 " + wan(p.areaBody) + " 万km²";
    }},
    series: [{
      type: "bar", barWidth: 15,
      label: { show: true, position: "right", fontSize: 11, color: "#252b27",
        formatter: function(pr){ var p = byName[pr.name]; return p.coef === null ? "—" : fmt(p.coef); } },
      data: DATA.poets.map(function(p){
        return { value: p.coef === null ? 0 : p.coef,
          itemStyle: { color: p.color, opacity: p.name === state.poet ? 1 : 0.4,
                       borderRadius: [0,2,2,0] } };
      })
    }]
  });
}
bar.on("click", function(params){ switchPoet(params.name); });

/* ---------- 图层开关 ---------- */
[["ly-body","body"],["ly-heart","heart"],["ly-arcs","arcs"],["ly-hull","hull"]].forEach(function(pair){
  var el = document.getElementById(pair[0]);
  el.onclick = function(){
    state.layers[pair[1]] = !state.layers[pair[1]];
    el.classList.toggle("on", state.layers[pair[1]]);
    chart.setOption(buildOption(byName[state.poet]), true);
  };
});

/* ---------- 切换 ---------- */
function switchPoet(name){
  state.poet = name;
  var p = byName[name];
  DATA.poets.forEach(function(q){
    document.getElementById("tab-" + q.name).classList.toggle("on", q.name === name);
  });
  chart.setOption(buildOption(p), true);
  renderSky(p);
  renderCoef(p);
  renderBar();
  evbox.innerHTML = "<div class='hint'>点击地图上的散点、弧线、行旅节点，或天界带芯片，这里会列出对应的证据句。</div>";
}

window.addEventListener("resize", function(){ chart.resize(); bar.resize(); });
switchPoet("李白");
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
