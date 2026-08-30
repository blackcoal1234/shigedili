# -*- coding: utf-8 -*-
"""viz_35 两种孤独 × 夸张签名（数媒可视化比赛参赛版 35 号页）。

零参数复跑：python 数据可视化脚本/viz_35_solitude_hyperbole.py

输入（只读）：
  data/stylometry/solitude_stats.json   人称孤独统计（88人 per_poet）
  data/stylometry/number_stats.json     数字夸张统计（88人 per_poet + headline）
  data/stylometry/number_dict.py        数字词典（核实"度量组合式"量级冠军）
  data/analysis/famous_poets_full.jsonl.gz  全作品语料（万里例句 + 情感均值）
  data/poems.json                       canonical 诗页与可点证据层
  data/spirit_image_dict.py             当前词条情感词典（散点Y轴）

输出：
  output/35_两种孤独与夸张签名.html
  output/assets/competition/solhyp_data.json

口径与诚实性：
  - 孤独密度用 solitude_per_100_chars（未加权口径，加权版一并写入数据文件）；
  - 夸张密度榜设正文≥300字样本门槛（与 number_stats headline 一致）；
  - 榜首、排名、样本量与象限均从本次统计动态生成，不沿用旧语料结论；
  - 「九万里」只宣称"数×度量单位组合式"量级冠军，虚指大数（亿/千万）更高
    的事实在页面如实注明。
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data"))
sys.path.insert(0, str(ROOT / "data" / "stylometry"))
sys.path.insert(0, str(ROOT))

import spirit_image_dict as sd  # noqa: E402
import number_dict as nd        # noqa: E402
from tools.famous_poet_corpus import load_analysis_poems  # noqa: E402

OUT_HTML = ROOT / "output" / "35_两种孤独与夸张签名.html"
OUT_JSON = ROOT / "output" / "assets" / "competition" / "solhyp_data.json"

SIX = ["李白", "杜甫", "白居易", "苏轼", "陆游", "李清照"]
SIX_COLOR = {
    "李白": "#426f94", "杜甫": "#7a5c3d", "白居易": "#26786e",
    "苏轼": "#b64b3f", "陆游": "#8a3b2f", "李清照": "#9c5d8f",
}
MIN_CHARS = 300  # 密度类榜单样本门槛（与 number_stats headline 口径一致）

# ---------------------------------------------------------------- 数据读取

def load_json(p: Path):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


sol_stats = load_json(ROOT / "data" / "stylometry" / "solitude_stats.json")
num_stats = load_json(ROOT / "data" / "stylometry" / "number_stats.json")
poems, CORPUS_SOURCE = load_analysis_poems(fallback=False)
N_POEMS = len(poems)
N_POETS = len({p.get("poet") or p.get("author") for p in poems})
SPIRIT_COUNT = len(sd.SPIRIT_DICT)
CORPUS_PATH = "data/analysis/famous_poets_full.jsonl.gz"
CANONICAL_PATH = "data/poems.json"

for stats_name, stats in (("solitude_stats", sol_stats), ("number_stats", num_stats)):
    if stats.get("corpus_source") != CORPUS_SOURCE:
        raise RuntimeError(f"{stats_name} corpus_source 与 loader 不一致")
    if int(stats.get("generated_from_poems", -1)) != N_POEMS:
        raise RuntimeError(f"{stats_name} 诗作数与 loader 不一致")

# ------------------------------------------------ 情感均值（spirit_image_dict）

WORDS = sd.words()  # 按长度降序
SENT = {row[0]: row[3] for row in sd.SPIRIT_DICT}
BY_FIRST: dict[str, list[str]] = defaultdict(list)
for w in WORDS:
    BY_FIRST[w[0]].append(w)  # 保持长度降序


def scan_sentiment(text: str) -> tuple[float, int]:
    """最长优先不重叠贪心匹配，返回 (情感值之和, 命中次数)。"""
    total, hits, i, n = 0.0, 0, 0, len(text)
    while i < n:
        matched = None
        for w in BY_FIRST.get(text[i], ()):
            if text.startswith(w, i):
                matched = w
                break
        if matched:
            total += SENT[matched]
            hits += 1
            i += len(matched)
        else:
            i += 1
    return total, hits


emo = defaultdict(lambda: [0.0, 0])
for p in poems:
    poet = p.get("poet") or p.get("author")
    s, c = scan_sentiment(p["body"])
    emo[poet][0] += s
    emo[poet][1] += c

# ------------------------------------------------------------ 四象限散点数据

scatter = []
for poet, d in sol_stats["per_poet"].items():
    s, c = emo.get(poet, [0.0, 0])
    if c == 0:
        continue  # 无词典命中的诗人不绘点（实测88人均有命中）
    scatter.append({
        "name": poet,
        "x": d["solitude_per_100_chars"],
        "xw": d["solitude_weighted_per_100_chars"],
        "y": round(s / c, 4),
        "hits": c,
        "poems": d["poem_count"],
        "chars": d["chars_total"],
        "core": poet in SIX,
        "color": SIX_COLOR.get(poet),
    })

pool = [r for r in scatter if r["chars"] >= MIN_CHARS]
med_x = round(statistics.median(r["x"] for r in pool), 3)
med_y = round(statistics.median(r["y"] for r in pool), 4)


def quadrant(r) -> str:
    a = "高孤独" if r["x"] >= med_x else "低孤独"
    b = "昂扬" if r["y"] >= med_y else "低回"
    return f"{a}·{b}"


six_land = {p: quadrant(next(r for r in scatter if r["name"] == p)) for p in SIX}

# 孤独密度排名（正文达到门槛的诗人内，降序）
dens_rank_pool = sorted(pool, key=lambda r: -r["x"])
dens_rank = {r["name"]: i + 1 for i, r in enumerate(dens_rank_pool)}

six_sol = {}
for p in SIX:
    d = sol_stats["per_poet"][p]
    six_sol[p] = {
        "density": d["solitude_per_100_chars"],
        "weighted": d["solitude_weighted_per_100_chars"],
        "ratio": d["self_other_ratio"],
        "cats": d["category_counts"],
        "poems": d["poem_count"],
        "chars": d["chars_total"],
        "rank": dens_rank[p],
        "lines": d["top_solitude_lines"][:4],
    }
six_density_order = sorted(SIX, key=lambda p: -six_sol[p]["density"])
six_density_rank = {p: i + 1 for i, p in enumerate(six_density_order)}
ratio_order = sorted(SIX, key=lambda p: -six_sol[p]["ratio"])

# ------------------------------------------------------------ 夸张密度 Top10

hyp_rows = []
for poet, d in num_stats["per_poet"].items():
    if d["chars_total"] < MIN_CHARS:
        continue
    ex = d["max_expressions"][0] if d["max_expressions"] else None
    hyp_rows.append({
        "name": poet,
        "density": d["hyperbole_per_100_chars"],
        "hits": d["hyperbole_hits"],
        "chars": d["chars_total"],
        "poems": d["poem_count"],
        "mag": d["avg_magnitude"],
        "example": {"word": ex["word"], "line": ex["line"], "title": ex["title"]} if ex else None,
    })
hyp_rows.sort(key=lambda r: -r["density"])
hyp_top10 = hyp_rows[:10]
hyp_median = round(statistics.median(r["density"] for r in hyp_rows), 3)
libai_rank = next(i + 1 for i, r in enumerate(hyp_rows) if r["name"] == "李白")
libai_num = num_stats["per_poet"]["李白"]
libai_mag_rank = next(
    i + 1 for i, r in enumerate(sorted(hyp_rows, key=lambda r: -r["mag"]))
    if r["name"] == "李白"
)

# 小样本附注（王之涣）
small = [(p, d) for p, d in num_stats["per_poet"].items() if d["chars_total"] < MIN_CHARS]
small.sort(key=lambda t: -t[1]["hyperbole_per_100_chars"])
small_note = {
    "name": small[0][0],
    "density": small[0][1]["hyperbole_per_100_chars"],
    "poems": small[0][1]["poem_count"],
    "chars": small[0][1]["chars_total"],
} if small else None

# 「九万里」= 词典内 measure（数×度量单位）类量级最高词条 —— 程序核实
measure_max = max((row for row in nd.NUMBER_DICT
                   if row[2] is not None and row[3] == "measure"), key=lambda r: r[2])
assert measure_max[0] == "九万里" and abs(measure_max[2] - 4.95) < 0.01, measure_max
vague_max = max((row for row in nd.NUMBER_DICT
                 if row[2] is not None and row[3] == "cardinal"), key=lambda r: r[2])

# --------------------------------------------------------------- 两种万里

WANLI_NOTE = {
    # 李白：句 → (万里修饰/所属, 语境判读)
    "扶摇直上九万里": ("大鹏扶摇的高度", "天"),
    "长风万里送秋雁": ("长风的跨度", "天"),
    "长风几万里": ("天风越关山的跨度", "天"),
    "黄云万里动风色": ("黄云铺展的广度", "天"),
    "送此万里目": ("登高目力所及", "望"),
    "万里送行舟": ("故乡水相送的水程", "旅"),
    "孤蓬万里征": ("孤蓬漂泊的行程", "旅"),
    "夜郎万里道": ("流放夜郎的路途", "旅"),
    # 陆游
    "当年万里觅封侯": ("从军觅封侯的征途", "国"),
    "孤臣万里客江干": ("孤臣去国之远", "国"),
    "三万里河东入海": ("中原山河的长度", "国"),
}
TAG_LABEL = {"天": "天空·仙界", "望": "登览", "旅": "江湖·行旅", "国": "家国·报国"}


def infer_wanli_note(poet: str, line: str):
    """为扩容后新增句提供可复核的粗粒度分类；核心旧句仍优先用人工标注。"""
    if poet == "李白":
        sky_markers = "风云霄天海河山龙门霜枝叶"
        if any(ch in line for ch in sky_markers):
            return "天宇、自然或山河尺度", "天"
        return "行旅、人事或历史距离", "旅"
    state_markers = ("封侯", "关河", "烟尘", "孤臣", "皋兰", "吴京", "春耕", "壮心", "丈夫")
    if any(word in line for word in state_markers):
        return "家国、边疆或报国尺度", "国"
    return "羁旅、身世或江湖距离", "旅"


def extract_wanli(poet: str) -> list[dict]:
    import re
    seen, out = set(), []
    for p in poems:
        if (p.get("poet") or p.get("author")) != poet:
            continue
        for ln in re.split(r"[，。！？；、\n]", p["body"]):
            ln = ln.strip()
            if "万里" in ln and ln not in seen:
                seen.add(ln)
                note = WANLI_NOTE.get(ln) or infer_wanli_note(poet, ln)
                out.append({
                    "line": ln, "title": p["title"],
                    "work_id": p.get("work_id"),
                    "body_hash": p.get("body_hash", ""),
                    "canonical_gushiwen_id": p.get("canonical_gushiwen_id"),
                    "canonical_match": bool(p.get("canonical_match")),
                    "source_url": p.get("source_url", ""),
                    "object": note[0],
                    "tag": TAG_LABEL[note[1]],
                })
    return out


wanli_lb = extract_wanli("李白")
wanli_ly = extract_wanli("陆游")
lb_sky = sum(1 for r in wanli_lb if r["tag"] in ("天空·仙界", "登览"))
ly_state = sum(1 for r in wanli_ly if r["tag"] == "家国·报国")

# --------------------------------------------------------------- 放大器常数

CHI_TANG_M = 0.307          # 唐大尺≈30.7cm（另有小尺≈24.6cm口径，见方法区）
FALL_REAL_M = 155           # 庐山秀峰瀑布常见实测口径（约值）
CHI3000_M = round(3000 * CHI_TANG_M)          # 921 m
AMP_RATIO = round(CHI3000_M / FALL_REAL_M, 2)  # 5.94
LI_TANG_KM = 0.531          # 唐里≈531m
WAN9_KM = round(90000 * LI_TANG_KM)            # 47790 km
EARTH_KM = 40075
WAN9_EARTH = round(WAN9_KM / EARTH_KM, 2)

# --------------------------------------------------------------- 汇总 DATA

DATA = {
    "generated_at": date.today().isoformat(),
    "corpus_source": CORPUS_SOURCE,
    "corpus_path": CORPUS_PATH if CORPUS_SOURCE == "analysis_full" else CANONICAL_PATH,
    "analysis_count": N_POEMS,
    "canonical_evidence_count": sum(
        1 for row in wanli_lb + wanli_ly if row["canonical_match"]
    ),
    "note": (f"viz_35 两种孤独×夸张签名。孤独密度/夸张密度均为人工词典口径的保守"
             f"统计；密度榜设正文≥300字门槛；情感均值为 spirit_image_dict {SPIRIT_COUNT}词条"
             "命中情感值的次数加权平均，全体均值整体偏负，'昂扬/低回'相对中位线。"),
    "sources": [
        "data/stylometry/solitude_stats.json（73词条人称孤独词典扫描）",
        "data/stylometry/number_stats.json（137词条数字词典扫描，夸张从严=保守下界）",
        f"data/spirit_image_dict.py（{SPIRIT_COUNT}词条，情感值[-1,1]，人工整理非权威词库）",
        f"{CORPUS_PATH}（{N_POEMS}首/{N_POETS}人，状态聚合层）",
        f"{CANONICAL_PATH}（规范诗页/证据层，本页 canonical 例证 {sum(1 for row in wanli_lb + wanli_ly if row['canonical_match'])} 条）",
    ],
    "median_x": med_x, "median_y": med_y, "min_chars": MIN_CHARS,
    "pool_size": len(pool),
    "scatter": scatter,
    "six_landing": six_land,
    "six_solitude": six_sol,
    "hyperbole": {
        "top10": hyp_top10,
        "median": hyp_median,
        "libai_rank": libai_rank,
        "libai_mag_rank": libai_mag_rank,
        "libai_density": libai_num["hyperbole_per_100_chars"],
        "libai_mag": libai_num["avg_magnitude"],
        "headline": num_stats.get("headline", ""),
        "small_note": small_note,
        "measure_champion": {"word": "九万里", "mag": 4.95, "line": "大鹏一日同风起，扶摇直上九万里", "title": "上李邕",
                             "km": WAN9_KM, "earth_ratio": WAN9_EARTH},
        "vague_max": {"word": vague_max[0], "mag": vague_max[2],
                      "example": "何方可化身千亿（陆游《梅花绝句二首·其一》）"},
    },
    "wanli": {"libai": wanli_lb, "luyou": wanli_ly, "lb_sky": lb_sky, "ly_state": ly_state},
    "amplifier": {"real_m": FALL_REAL_M, "chi3000_m": CHI3000_M, "ratio": AMP_RATIO,
                  "chi_m": CHI_TANG_M,
                  "refs": [{"name": "庐山瀑布实测(约)", "h": FALL_REAL_M},
                           {"name": "埃菲尔铁塔", "h": 330},
                           {"name": "哈利法塔", "h": 828},
                           {"name": "「三千尺」", "h": CHI3000_M}]},
}

OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(DATA, f, ensure_ascii=False, indent=1)

# ================================================================ HTML

data_js = json.dumps(DATA, ensure_ascii=False, separators=(",", ":"))

lq = six_sol["李清照"]
ly = six_sol["陆游"]
lb = six_sol["李白"]

wanli_rows_lb = "\n".join(
    f'<tr><td class="kai vline">{r["line"]}</td><td class="src">'
    f'<a href="{r["source_url"]}" target="_blank" rel="noopener">《{r["title"]}》</a></td>'
    f'<td>{r["object"]}</td><td><span class="tag t-{"sky" if r["tag"] in ("天空·仙界", "登览") else "road"}">{r["tag"]}</span></td></tr>'
    for r in wanli_lb)
wanli_rows_ly = "\n".join(
    f'<tr><td class="kai vline">{r["line"]}</td><td class="src">'
    f'<a href="{r["source_url"]}" target="_blank" rel="noopener">《{r["title"]}》</a></td>'
    f'<td>{r["object"]}</td><td><span class="tag t-{"state" if r["tag"] == "家国·报国" else "road"}">{r["tag"]}</span></td></tr>'
    for r in wanli_ly)

lq_lines = "".join(
    f'<li><span class="kai">{x["line"]}</span> <span class="src">《{x["title"]}》 行内密度 {x["density"]}</span></li>'
    for x in lq["lines"])
ly_lines = "".join(
    f'<li><span class="kai">{x["line"]}</span> <span class="src">《{x["title"]}》 行内密度 {x["density"]}</span></li>'
    for x in ly["lines"][:3])

land_chips = "".join(
    f'<span class="chip" style="border-color:{SIX_COLOR[p]};color:{SIX_COLOR[p]}">{p} → {six_land[p]}</span>'
    for p in SIX)
ratio_note = "；".join(f"<b>{p}</b> {six_sol[p]['ratio']}" for p in ratio_order)
ratio_over_one = "、".join(p for p in ratio_order if six_sol[p]["ratio"] > 1) or "无"
top_hyp = hyp_top10[0]

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>两种孤独 × 夸张签名 · 诗行万里</title>
<script src="assets/pyecharts/v6/echarts.min.js"></script>
<style>
:root{--paper:#f2f4f0;--ink:#252b27;--cinnabar:#b64b3f;--jade:#26786e;--gold:#a87527;--blue:#426f94;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--paper);color:var(--ink);font-family:"Microsoft YaHei",sans-serif;line-height:1.7;}
h1,h2,h3,.kai{font-family:KaiTi,STKaiti,"Microsoft YaHei",serif;}
.wrap{max-width:1280px;margin:0 auto;padding:24px 16px 40px;}
header.top{text-align:center;padding:26px 12px 6px;}
header.top h1{font-size:34px;letter-spacing:6px;}
header.top .sub{color:#5a615c;margin-top:6px;font-size:14px;}
.badge{display:inline-block;font-size:11px;padding:1px 8px;border-radius:9px;border:1px solid var(--gold);color:var(--gold);vertical-align:4px;margin-left:8px;}
.panel{background:#fbfcfa;border:1px solid #dfe4de;border-radius:10px;padding:16px 18px;margin-top:18px;box-shadow:0 1px 3px rgba(37,43,39,.05);}
.panel h2{font-size:22px;letter-spacing:2px;margin-bottom:4px;}
.panel h3{font-size:17px;margin-bottom:4px;}
.panel .cap{font-size:13px;color:#5a615c;margin-bottom:8px;}
.sect{margin-top:34px;}
.sect>.head{display:flex;align-items:baseline;gap:12px;border-bottom:2px solid var(--ink);padding-bottom:6px;}
.sect>.head h2{font-size:26px;letter-spacing:4px;}
.sect>.head .en{color:#8a918b;font-size:12px;letter-spacing:1px;}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px;}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:16px;}
.grid2>*,.grid3>*,.amp>*{min-width:0;}
@media(max-width:900px){.grid2,.grid3{grid-template-columns:1fr;}}
.chart{width:100%;}
#quadChart{height:530px;}
#ratioChart{height:330px;}
#hypChart{height:430px;}
.chips{margin-top:10px;display:flex;flex-wrap:wrap;gap:8px;}
.chip{font-size:12.5px;border:1px solid #999;border-radius:14px;padding:2px 11px;background:#fff;}
.card{border-left:4px solid var(--gold);background:#fbfcfa;border-radius:0 10px 10px 0;border-top:1px solid #dfe4de;border-right:1px solid #dfe4de;border-bottom:1px solid #dfe4de;padding:13px 15px;}
.card h3{font-size:16px;}
.card .num{font-family:KaiTi,STKaiti,serif;font-size:30px;line-height:1.2;}
.card p{font-size:13.5px;margin-top:5px;}
.card.rev{border-left-color:var(--cinnabar);}
.card.jade{border-left-color:var(--jade);}
.card.blue{border-left-color:var(--blue);}
details.ev{margin-top:8px;font-size:13px;}
details.ev summary{cursor:pointer;color:var(--blue);font-size:12.5px;}
details.ev ul{list-style:none;margin-top:6px;}
details.ev li{padding:3px 0;border-bottom:1px dashed #e2e6e0;}
.src{color:#8a918b;font-size:12px;}
.scrollx{overflow-x:auto;}
table.wl{border-collapse:collapse;width:100%;min-width:560px;font-size:13.5px;}
table.wl th{font-family:KaiTi,STKaiti,serif;font-size:15px;text-align:left;padding:7px 10px;border-bottom:2px solid var(--ink);}
table.wl td{padding:7px 10px;border-bottom:1px solid #e2e6e0;vertical-align:top;}
table.wl .vline{font-size:15.5px;white-space:nowrap;}
.tag{display:inline-block;font-size:11.5px;border-radius:10px;padding:1px 9px;color:#fff;white-space:nowrap;}
.t-sky{background:var(--blue);}
.t-road{background:#8a918b;}
.t-state{background:#8a3b2f;}
.wl-head{display:flex;align-items:baseline;gap:10px;margin-bottom:6px;}
.wl-head .who{font-family:KaiTi,STKaiti,serif;font-size:19px;}
.wl-sum{font-size:13px;color:#5a615c;margin-top:8px;}
/* ---------- 三千尺放大器 ---------- */
.amp{display:grid;grid-template-columns:minmax(300px,1.25fr) 1fr;gap:20px;}
@media(max-width:900px){.amp{grid-template-columns:1fr;}}
.amp-stage{position:relative;height:500px;border:1px solid #dfe4de;border-radius:10px;background:linear-gradient(180deg,#eef3f2 0%,#f7f9f6 70%,#eceee9 100%);overflow:hidden;}
.amp-grid{position:absolute;left:0;right:0;border-top:1px dashed #c8cfc9;font-size:10.5px;color:#8a918b;padding-left:6px;line-height:1.1;}
.amp-ref{position:absolute;left:0;right:0;border-top:1px solid #b9a06a;}
.amp-ref span{position:absolute;right:6px;top:-17px;font-size:11px;color:var(--gold);background:rgba(251,252,250,.85);padding:0 4px;border-radius:4px;}
.bar{position:absolute;bottom:0;width:74px;border-radius:6px 6px 0 0;}
.bar .lab{position:absolute;top:-40px;left:50%;transform:translateX(-50%);text-align:center;font-size:11.5px;line-height:1.25;white-space:nowrap;color:var(--ink);}
.bar .hval{font-family:KaiTi,STKaiti,serif;font-size:15px;}
#barReal{left:16%;background:linear-gradient(180deg,#3d9187,#26786e);}
#barPoem{left:58%;background:linear-gradient(180deg,#d4776a,#b64b3f);transition:height .45s cubic-bezier(.2,.7,.3,1);}
#poemVerse{position:absolute;left:6%;top:12px;font-family:KaiTi,STKaiti,serif;font-size:19px;color:var(--cinnabar);letter-spacing:2px;opacity:0;transition:opacity .5s;writing-mode:vertical-rl;}
.amp-ctrl .read{font-family:KaiTi,STKaiti,serif;font-size:25px;color:var(--cinnabar);margin:4px 0 2px;}
.amp-ctrl input[type=range]{width:100%;accent-color:var(--cinnabar);height:28px;}
.amp-ctrl .btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px;}
.amp-ctrl .btn{border:1px solid var(--blue);color:var(--blue);background:transparent;border-radius:16px;padding:3px 14px;font-size:13px;cursor:pointer;}
.amp-ctrl .btn:hover{background:var(--blue);color:#fff;}
.mini{margin-top:14px;font-size:13px;background:#f4f1e9;border:1px solid #e0d9c6;border-radius:8px;padding:10px 12px;}
.mini b{color:var(--gold);}
footer.nav{margin-top:40px;padding-top:14px;border-top:1px solid #cfd5cf;display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;}
footer.nav a{color:var(--blue);text-decoration:none;}
footer.nav a:hover{text-decoration:underline;}
details.method{margin-top:26px;font-size:13px;color:#414843;}
details.method summary{cursor:pointer;font-family:KaiTi,STKaiti,serif;font-size:16px;color:var(--ink);}
details.method ul{margin:8px 0 0 18px;}
details.method li{margin-bottom:5px;}
.note{font-size:12.5px;color:#5a615c;margin-top:8px;}
/* ---- 固定主题背景：孤独签名 ---- */
html{background:#e8e7df;}
body{position:relative;isolation:isolate;background:transparent;}
body::before{content:"";position:fixed;inset:0;z-index:-2;pointer-events:none;
 background:url("assets/generated/remaining_pages_20260830/35_solitude_signature_v1.png") center center/cover no-repeat;}
body::after{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;background:rgba(248,247,241,.28);}
.wrap{position:relative;z-index:1;}
.panel,.card{background:rgba(251,252,250,.89);}
.chip{background:rgba(255,255,252,.91);}
</style>
</head>
<body>
<div class="wrap">

<header class="top">
  <h1>两种孤独 × 夸张签名<span class="badge">词典口径 · 全语料实测</span></h1>
  <div class="sub">__N_POETS__ 位诗人 · __N_POEMS__ 首 —— 孤独不是一种，夸张也不归李白独有：每次重算都让结论跟着语料更新</div>
</header>

<!-- ==================== 上半：两种孤独 ==================== -->
<section class="sect">
  <div class="head"><h2>上半 · 两种孤独</h2><span class="en">TWO KINDS OF SOLITUDE</span></div>

  <div class="panel">
    <h2>四象限：孤独密度 × 情感均值</h2>
    <div class="cap">X＝每百字孤独词密度（73词条人称孤独词典）｜Y＝全部诗作意象情感均值（__SPIRIT_COUNT__词条 spirit_image_dict，[-1,1]）｜虚线＝正文≥300字的 __POOL_N__ 人中位线，「昂扬/低回」相对中位线而言（词典整体偏负）。六位核心诗人为彩色大点，其余 __BG_N__ 人为灰色背景分布。</div>
    <div id="quadChart" class="chart"></div>
    <div class="chips">__LAND_CHIPS__</div>
    <div class="note">六人的实际象限已列在上方彩色标签中；中位线、排名与落点均由当前全语料重算。象限描述的是词典命中的文本相对位置，不是对诗人心理的诊断。</div>
  </div>

  <div class="grid3">
    <div class="card rev">
      <h3>李清照：尖峰，不是弥漫</h3>
      <div class="num">__LQ_DENS__<span style="font-size:14px;"> /百字</span></div>
      <p>以孤独著称的李清照，孤独词密度在六人中排<b>第 __LQ_SIX_RANK__/6</b>，在正文充分样本中排第 __LQ_RANK__/__POOL_N__。这说明她的文本未必靠孤独词弥漫铺陈，更多信息集中在少数<b>尖峰句</b>上。</p>
      <details class="ev"><summary>展开她的尖峰证据句 ▾</summary><ul>__LQ_LINES__</ul></details>
    </div>
    <div class="card jade">
      <h3>陆游：弥漫型孤独</h3>
      <div class="num">__LY_DENS__<span style="font-size:14px;"> /百字</span></div>
      <p>当前六人中排第 __LY_SIX_RANK__/6，正文充分样本总榜第 __LY_RANK__/__POOL_N__。他的高频孤独词反复落在孤村、孤臣、寂寞与独自等处境里，呈现出更接近<b>弥漫型</b>的文本签名。</p>
      <details class="ev"><summary>展开他的证据句 ▾</summary><ul>__LY_LINES__</ul></details>
    </div>
    <div class="card blue">
      <h3>李白：孤独不是最高频签名</h3>
      <div class="num">__LB_DENS__<span style="font-size:14px;"> /百字</span></div>
      <p>当前六人中排第 __LB_SIX_RANK__/6（充分样本总榜第 __LB_RANK__/__POOL_N__）。「举杯邀明月」等名句很醒目，但扩容后的整体密度显示：孤独并非他最频繁的词汇签名。</p>
    </div>
  </div>

  <div class="panel">
    <h2>独白型还是对话型：自称 / 他称之比</h2>
    <div class="cap">自称（我/吾/余/此身…）÷ 他称（君/汝/故人/客…）。比值＞1＝独白倾向（说给自己听），＜1＝对话倾向（呼唤他者）。悬停看原始词数。</div>
    <div id="ratioChart" class="chart"></div>
    <div class="note">当前六人自称/他称比：__RATIO_NOTE__。比值高于 1 的诗人：<b>__RATIO_OVER_ONE__</b>。该指标只统计词表中的人称表达，不等同于叙事学意义上的独白或对话。</div>
  </div>
</section>

<!-- ==================== 下半：夸张签名 ==================== -->
<section class="sect">
  <div class="head"><h2>下半 · 夸张签名</h2><span class="en">SIGNATURES OF HYPERBOLE</span></div>

  <div class="grid2">
    <div class="panel">
      <h2>夸张密度 Top10（正文≥300字的 __POOL_HYP_N__ 人）</h2>
      <div class="cap">每百字夸张数词数。夸张标记从严（只标「大数×度量/时间/景物」经典组合与虚指大数），因此是<b>保守下界</b>。悬停看各家量级冠军句。</div>
      <div id="hypChart" class="chart"></div>
    </div>
    <div class="panel">
      <h2>数据修正了我们的预设</h2>
      <div class="cap">这一格是方法论诚实的展示位。</div>
      <div class="card rev" style="margin-top:6px;">
        <h3>「李白是夸张之王」？——密度上不是</h3>
        <p>正文不少于 300 字的 __POOL_HYP_N__ 位诗人中，夸张密度第一是<b>__HYP_TOP_NAME__（__HYP_TOP_DENS__/百字）</b>，全体中位数为 __HYP_MEDIAN__；<b>李白 __LB_HYP_DENS__/百字，排第 __LB_HYP_RANK__</b>，平均数量级排第 __LB_MAG_RANK__。数据没有配合传说，我们如实呈现。</p>
        <p style="margin-top:6px;">小样本附注：__SMALL_NAME__ 密度 __SMALL_DENS__，但仅 __SMALL_POEMS__ 首/__SMALL_CHARS__ 字，样本不足不入榜。</p>
      </div>
      <div class="card blue" style="margin-top:12px;">
        <h3>李白神话的真实所在：量级</h3>
        <p>「扶摇直上<b>九万里</b>」（《上李邕》）量级 log₁₀≈4.95，是全语料<b>「数字×度量单位」组合式夸张的量级冠军</b>（第二名正是他自己的「四万八千丈/岁」4.68，陆游「三万里河」4.48 居后）。李白的签名不是「夸张得频繁」，而是<b>一出手就把尺度拉到极限</b>——密度不第一，量级第一。</p>
        <p class="src" style="margin-top:5px;">诚实注明：若把「亿/千万」这类<b>虚指大数</b>也算入，陆游「化身千亿」（log₁₀=8.0）等更高；「九万里」的冠军只在「数×度量单位」口径内成立。</p>
      </div>
    </div>
  </div>

  <div class="panel">
    <h2>两种「万里」：李白偏天宇，陆游偏家国</h2>
    <div class="cap">从语料逐句抽取两人全部含「万里」诗句（李白 __LB_WL__ 句、陆游 __LY_WL__ 句），标注「万里」量的是什么。</div>
    <div class="grid2">
      <div>
        <div class="wl-head"><span class="who" style="color:#426f94;">李白的万里</span><span class="src">仙界与行旅</span></div>
        <div class="scrollx"><table class="wl">
          <tr><th>诗句</th><th>出处</th><th>「万里」量的是</th><th>语境</th></tr>
          __WANLI_LB__
        </table></div>
        <div class="wl-sum">__LB_WL__ 句中 <b>__LB_SKY__ 句归入天宇/登览</b>，__LB_ROAD__ 句归入江湖行旅或人事距离。扩容后的全部命中均列出，李白的万里并非全是仙界。</div>
      </div>
      <div>
        <div class="wl-head"><span class="who" style="color:#8a3b2f;">陆游的万里</span><span class="src">报国与山河</span></div>
        <div class="scrollx"><table class="wl">
          <tr><th>诗句</th><th>出处</th><th>「万里」量的是</th><th>语境</th></tr>
          __WANLI_LY__
        </table></div>
        <div class="wl-sum">__LY_WL__ 句中 <b>__LY_STATE__ 句归入家国/边疆</b>，__LY_OTHER__ 句归入羁旅、身世或江湖距离。同一个「万里」，两位诗人的高频语境并不相同。</div>
      </div>
    </div>
  </div>

  <div class="panel">
    <h2>「三千尺」有多高：夸张放大器</h2>
    <div class="cap">庐山瀑布实测约 155 米；「飞流直下三千尺」按唐大尺（1尺≈30.7cm）合约 921 米。拖动滑块，把实测瀑布拉伸到诗里的高度。</div>
    <div class="amp">
      <div class="amp-stage" id="ampStage">
        <div id="poemVerse">飞流直下三千尺，疑是银河落九天</div>
        <div class="bar" id="barReal"><div class="lab">庐山瀑布·实测<br><span class="hval">155 米</span></div></div>
        <div class="bar" id="barPoem"><div class="lab">诗中瀑布<br><span class="hval" id="poemH">155 米</span></div></div>
      </div>
      <div class="amp-ctrl">
        <h3>诗意放大倍率</h3>
        <div class="read" id="ampRead">1.00 ×</div>
        <input type="range" id="ampSlider" min="100" max="594" value="100" step="2" aria-label="诗意放大倍率">
        <div class="btns">
          <button class="btn" data-k="100">实测 1×</button>
          <button class="btn" data-k="300">半程 3×</button>
          <button class="btn" data-k="594">三千尺 5.94×</button>
        </div>
        <p style="font-size:13.5px;margin-top:10px;" id="ampMsg">这是瀑布本来的样子——155 米，已近 50 层楼。</p>
        <div class="mini"><b>补充叙事 · 密度不第一，量级第一：</b>同一支笔写「扶摇直上九万里」——九万唐里≈ 4.78 万公里，约为地球赤道周长（40075 公里）的 <b>1.19 倍</b>。大鹏一次爬升，绕地球一圈还有余。（唐里≈531米口径，量级冠军仅限「数×度量单位」类，见方法区）</div>
      </div>
    </div>
  </div>
</section>

<details class="method">
  <summary>方法与数据（口径与局限，点开查看）</summary>
  <ul>
    <li><b>数据来源</b>：孤独维度 data/stylometry/solitude_stats.json（73词条人称孤独词典）；夸张维度 number_stats.json（137词条数字词典）；情感均值按 data/spirit_image_dict.py（__SPIRIT_COUNT__词条）对每位诗人全部诗作做最长优先贪心匹配后取命中情感值的次数加权平均。三套词典均为本项目<b>人工整理的分析工具，不是权威词库</b>，一切结论只在各自口径内成立。</li>
    <li><b>孤独密度口径</b>：solitude_per_100_chars 含低权重多义字（「空」0.25、「自」0.15），会略高于真值；按强度加权的 solitude_weighted_per_100_chars 一并写入本页数据文件（李清照 __LQ_WEIGHTED__ / 李白 __LB_WEIGHTED__ / 陆游 __LY_WEIGHTED__）。六人样本为 __SIX_SAMPLE_COUNTS__，密度仍是<b>本库统计而非全集断言</b>。</li>
    <li><b>四象限</b>：中位线取正文≥300字的 __POOL_N__ 位诗人中位数（X=__MED_X__，Y=__MED_Y__）。故Y轴「昂扬/低回」是<b>相对中位线的相对说法</b>，不是绝对褒贬。</li>
    <li><b>夸张密度</b>：夸张标记从严——只标「大数×度量/时间/景物」经典组合与虚指大数，裸数词不标，故密度是<b>保守下界</b>；榜单设正文≥300字门槛（__POOL_HYP_N__/__N_POETS__人），小样本最高者另行附注，不混入主榜。</li>
    <li><b>「九万里」量级冠军的边界</b>：仅在「数字×度量单位」（measure）类内成立（程序核实词典内该类最高即 4.95）；虚指大数「亿」（log₁₀=8.0，如陆游「化身千亿」）、「千万」（7.0）量级更高，页面已如实注明。</li>
    <li><b>换算口径</b>：唐大尺≈30.7cm，三千尺≈921米（若按小尺24.6cm则≈738米，同样远超实测）；唐里≈531米，九万里≈4.78万公里。庐山瀑布「约155米」取秀峰瀑布常见实测口径，为约值。换算只为直观感受量级，不是考据结论。</li>
    <li><b>万里例句</b>：由脚本从 analysis_full 全作品逐句抽取（含「万里」即收，重复句去重），旧核心句沿用人工标注，新增句按关键词规则做粗分类；链接优先指向 canonical 诗页，其余回退到上游来源。</li>
    <li><b>双层口径</b>：状态、情感与万里聚合使用 <code>data/analysis/famous_poets_full.jsonl.gz</code>；规范诗页与可点证据仍以 <code>data/poems.json</code> 的 exact canonical match 为准，两层数量分开标注。</li>
    <li><b>本页数据文件</b>：output/assets/competition/solhyp_data.json，脚本 数据可视化脚本/viz_35_solitude_hyperbole.py 零参数可复跑。</li>
  </ul>
</details>

<footer class="nav">
    <a href="29_参赛导航.html">29 作品目录</a><a href="30_诗行万里_参赛版.html">30 总入口</a><a href="31_凝望罗盘.html">31 凝望罗盘</a><a href="32_身与心双层地图.html">32 身与心双层地图</a><a href="33_平行时空759.html">33 平行时空759</a><a href="34_一字识诗人.html">34 一字识诗人</a><a href="35_两种孤独与夸张签名.html" style="color:var(--cinnabar);">35 两种孤独与夸张签名</a><a href="36_同龄对齐.html">36 同龄对齐</a><a href="37_可听的诗.html">37 可听的诗</a><a href="38_唐宋意象潮汐.html">38 意象潮汐</a><a href="39_诗人自述生命卷.html">39 诗人自述生命卷</a>
</footer>
</div>

<script>
var DATA = __DATA_JSON__;

/* ---------------- 图1：四象限散点 ---------------- */
(function(){
  var el = document.getElementById('quadChart');
  var ch = echarts.init(el);
  var MX = DATA.median_x, MY = DATA.median_y;
  var XMAX = 2.6, YMIN = -0.32, YMAX = 0.09;
  var bg = [], core = [];
  DATA.scatter.forEach(function(r){
    var item = {name:r.name, value:[r.x, r.y], meta:r};
    if(r.core){ item.itemStyle = {color:r.color, borderColor:'#fbfcfa', borderWidth:1.5}; core.push(item); }
    else bg.push(item);
  });
  function quad(r){
    return (r.value[0] >= MX ? '高孤独' : '低孤独') + '·' + (r.value[1] >= MY ? '昂扬' : '低回');
  }
  var areaLab = function(txt, x0, x1, y0, y1, color){
    return [{xAxis:x0, yAxis:y0, itemStyle:{color:'rgba(0,0,0,0)'},
             label:{show:true, position:'inside', color:color, fontSize:13,
                    fontFamily:'KaiTi,STKaiti,serif', formatter:txt, opacity:0.75}},
            {xAxis:x1, yAxis:y1}];
  };
  ch.setOption({
    grid:{left:52, right:24, top:34, bottom:46},
    xAxis:{name:'孤独密度 / 百字', nameLocation:'middle', nameGap:28, min:0, max:XMAX,
           axisLine:{lineStyle:{color:'#5a615c'}}, splitLine:{show:false}},
    yAxis:{name:'情感均值', nameGap:36, nameLocation:'middle', min:YMIN, max:YMAX,
           axisLine:{lineStyle:{color:'#5a615c'}}, splitLine:{show:false}},
    tooltip:{trigger:'item', backgroundColor:'#fbfcfa', borderColor:'#dfe4de',
      textStyle:{color:'#252b27', fontSize:12.5},
      formatter:function(p){
        var m = p.data.meta;
        return '<b>' + m.name + '</b>　' + quad(p.data) +
          '<br>孤独密度 ' + m.x + '/百字（加权 ' + m.xw + '）' +
          '<br>情感均值 ' + m.y + '（意象命中 ' + m.hits + ' 次）' +
          '<br>样本 ' + m.poems + ' 首 / ' + m.chars + ' 字';
      }},
    series:[
      {type:'scatter', data:bg, symbolSize:6.5, z:2,
       itemStyle:{color:'#b9c0ba', opacity:0.75},
       markLine:{silent:true, symbol:'none',
         lineStyle:{type:'dashed', color:'#8a918b'},
         label:{color:'#5a615c', fontSize:11},
         data:[{xAxis:MX, label:{formatter:'中位 ' + MX}},
               {yAxis:MY, label:{formatter:'中位 ' + MY, position:'insideEndTop'}}]},
       markArea:{silent:true, data:[
         areaLab('低孤独 · 昂扬', 0, MX, MY, YMAX, '#26786e'),
         areaLab('高孤独 · 昂扬', MX, XMAX, MY, YMAX, '#a87527'),
         areaLab('低孤独 · 低回', 0, MX, YMIN, MY, '#8a918b'),
         areaLab('高孤独 · 低回', MX, XMAX, YMIN, MY, '#b64b3f')]}},
      {type:'scatter', data:core, symbolSize:17, z:5,
       label:{show:true, position:'top', fontSize:12.5, color:'#252b27',
              fontFamily:'KaiTi,STKaiti,serif',
              formatter:function(p){return p.data.name;}}}
    ]
  });
  window.addEventListener('resize', function(){ ch.resize(); });
})();

/* ---------------- 图2：自称/他称比 ---------------- */
(function(){
  var ch = echarts.init(document.getElementById('ratioChart'));
  var poets = Object.keys(DATA.six_solitude);
  var rows = poets.map(function(p){
    var d = DATA.six_solitude[p];
    return {name:p, ratio:d.ratio, cats:d.cats,
            color:(DATA.scatter.filter(function(r){return r.name===p;})[0]||{}).color || '#5a615c'};
  }).sort(function(a,b){return a.ratio-b.ratio;});
  ch.setOption({
    grid:{left:70, right:56, top:14, bottom:34},
    xAxis:{max:1.35, name:'自称 ÷ 他称', nameLocation:'middle', nameGap:24,
           axisLine:{lineStyle:{color:'#5a615c'}}, splitLine:{lineStyle:{color:'#e6eae4'}}},
    yAxis:{type:'category', data:rows.map(function(r){return r.name;}),
           axisLine:{lineStyle:{color:'#5a615c'}},
           axisLabel:{fontFamily:'KaiTi,STKaiti,serif', fontSize:14}},
    tooltip:{trigger:'item', backgroundColor:'#fbfcfa', borderColor:'#dfe4de',
      textStyle:{color:'#252b27', fontSize:12.5},
      formatter:function(p){
        var r = rows[p.dataIndex];
        return '<b>' + r.name + '</b><br>自称 ' + r.cats['自称'] + ' 次 ÷ 他称 ' +
               r.cats['他称'] + ' 次 = ' + r.ratio +
               '<br>' + (r.ratio >= 1 ? '独白倾向：说给自己听' : '对话倾向：呼唤他者');
      }},
    series:[{type:'bar', barWidth:17,
      data:rows.map(function(r){return {value:r.ratio, itemStyle:{color:r.color, borderRadius:[0,4,4,0]}};}),
      label:{show:true, position:'right', fontSize:12, color:'#414843',
             formatter:function(p){return p.value.toFixed(2);}},
      markLine:{silent:true, symbol:'none',
        lineStyle:{type:'dashed', color:'#b64b3f'},
        label:{formatter:'自称=他称', color:'#b64b3f', fontSize:11},
        data:[{xAxis:1}]}}]
  });
  window.addEventListener('resize', function(){ ch.resize(); });
})();

/* ---------------- 图3：夸张密度Top10 ---------------- */
(function(){
  var ch = echarts.init(document.getElementById('hypChart'));
  var rows = DATA.hyperbole.top10.slice().reverse();
  ch.setOption({
    grid:{left:70, right:60, top:14, bottom:34},
    xAxis:{max:1.3, name:'夸张数词 / 百字', nameLocation:'middle', nameGap:24,
           axisLine:{lineStyle:{color:'#5a615c'}}, splitLine:{lineStyle:{color:'#e6eae4'}}},
    yAxis:{type:'category', data:rows.map(function(r){return r.name;}),
           axisLine:{lineStyle:{color:'#5a615c'}},
           axisLabel:{fontFamily:'KaiTi,STKaiti,serif', fontSize:13.5}},
    tooltip:{trigger:'item', backgroundColor:'#fbfcfa', borderColor:'#dfe4de',
      textStyle:{color:'#252b27', fontSize:12.5}, confine:true,
      formatter:function(p){
        var r = rows[p.dataIndex];
        var s = '<b>' + r.name + '</b>　' + r.density + '/百字' +
                '<br>夸张命中 ' + r.hits + ' 次 / ' + r.chars + ' 字（' + r.poems + ' 首）' +
                '<br>平均数量级 ' + r.mag;
        if(r.example){ s += '<br>量级冠军句：' + r.example.word + '——「' + r.example.line +
                            '」《' + r.example.title + '》'; }
        return s;
      }},
    series:[{type:'bar', barWidth:17,
      data:rows.map(function(r, i){
        var isLB = r.name === '李白';
        var top = i === rows.length - 1;
        return {value:r.density,
          itemStyle:{color:isLB ? '#426f94' : (top ? '#b64b3f' : '#c9b083'),
                     borderRadius:[0,4,4,0]}};
      }),
      label:{show:true, position:'right', fontSize:12, color:'#414843',
             formatter:function(p){
               var r = rows[p.dataIndex];
               return r.density + (r.name === '李白' ? '（第' + DATA.hyperbole.libai_rank + '）' : '');
             }},
      markLine:{silent:true, symbol:'none',
        lineStyle:{type:'dashed', color:'#8a918b'},
        label:{formatter:DATA.pool_size + '人中位数 ' + DATA.hyperbole.median, color:'#5a615c', fontSize:11},
        data:[{xAxis:DATA.hyperbole.median}]}}]
  });
  window.addEventListener('resize', function(){ ch.resize(); });
})();

/* ---------------- 三千尺放大器 ---------------- */
(function(){
  var A = DATA.amplifier;
  var stage = document.getElementById('ampStage');
  var MAXM = 1000;                       // 舞台顶 = 1000米
  function px(h){ return (h / MAXM * (stage.clientHeight - 56)); }
  // 网格线每200米 + 参照线
  [200, 400, 600, 800].forEach(function(m){
    var g = document.createElement('div');
    g.className = 'amp-grid';
    g.style.bottom = px(m) + 'px';
    g.textContent = m + ' 米';
    stage.appendChild(g);
  });
  A.refs.forEach(function(r){
    if(r.name.indexOf('三千尺') >= 0 || r.name.indexOf('实测') >= 0) return;
    var g = document.createElement('div');
    g.className = 'amp-ref';
    g.style.bottom = px(r.h) + 'px';
    var s = document.createElement('span');
    s.textContent = r.name + ' ' + r.h + '米';
    g.appendChild(s);
    stage.appendChild(g);
  });
  var barReal = document.getElementById('barReal');
  var barPoem = document.getElementById('barPoem');
  var poemH = document.getElementById('poemH');
  var read = document.getElementById('ampRead');
  var msg = document.getElementById('ampMsg');
  var verse = document.getElementById('poemVerse');
  var slider = document.getElementById('ampSlider');
  function render(){
    var k = slider.value / 100;
    var h = Math.round(A.real_m * k);
    if(k >= 5.9) h = A.chi3000_m;        // 顶格对齐 921
    barReal.style.height = px(A.real_m) + 'px';
    barPoem.style.height = px(h) + 'px';
    poemH.textContent = h + ' 米';
    read.textContent = k.toFixed(2) + ' ×';
    verse.style.opacity = (k >= 5.9) ? 1 : 0;
    if(k < 1.2){ msg.textContent = '这是瀑布本来的样子——155 米，已近 50 层楼。'; }
    else if(k < 3){ msg.textContent = '继续拉伸——夸张不是撒谎，是把感受的强度画成高度。'; }
    else if(k < 5.9){ msg.textContent = '已超过埃菲尔铁塔（330米），还在往「银河」的方向长。'; }
    else { msg.textContent = '「三千尺」≈ ' + A.chi3000_m + ' 米：比哈利法塔（828米）还高近百米，是实测的 ' + A.ratio + ' 倍——李白把一条瀑布写成了从九天垂下的银河。'; }
  }
  slider.addEventListener('input', render);
  document.querySelectorAll('.amp-ctrl .btn').forEach(function(b){
    b.addEventListener('click', function(){ slider.value = b.dataset.k; render(); });
  });
  window.addEventListener('resize', render);
  render();
})();
</script>
</body>
</html>
"""

repl = {
    "__DATA_JSON__": data_js,
    "__LAND_CHIPS__": land_chips,
    "__LQ_DENS__": f'{lq["density"]}',
    "__LQ_RANK__": f'{lq["rank"]}',
    "__LQ_LINES__": lq_lines,
    "__LY_DENS__": f'{ly["density"]}',
    "__LY_RANK__": f'{ly["rank"]}',
    "__LY_LINES__": ly_lines,
    "__LB_DENS__": f'{lb["density"]}',
    "__LB_RANK__": f'{lb["rank"]}',
    "__WANLI_LB__": wanli_rows_lb,
    "__WANLI_LY__": wanli_rows_ly,
    "__LB_WL__": str(len(wanli_lb)),
    "__LY_WL__": str(len(wanli_ly)),
    "__LB_SKY__": str(lb_sky),
    "__LY_STATE__": str(ly_state),
    "__LB_ROAD__": str(len(wanli_lb) - lb_sky),
    "__LY_OTHER__": str(len(wanli_ly) - ly_state),
    "__N_POEMS__": str(N_POEMS),
    "__N_POETS__": str(N_POETS),
    "__SPIRIT_COUNT__": str(SPIRIT_COUNT),
    "__POOL_N__": str(len(pool)),
    "__BG_N__": str(max(0, len(scatter) - len(SIX))),
    "__POOL_HYP_N__": str(len(hyp_rows)),
    "__LQ_SIX_RANK__": str(six_density_rank["李清照"]),
    "__LY_SIX_RANK__": str(six_density_rank["陆游"]),
    "__LB_SIX_RANK__": str(six_density_rank["李白"]),
    "__RATIO_NOTE__": ratio_note,
    "__RATIO_OVER_ONE__": ratio_over_one,
    "__HYP_TOP_NAME__": top_hyp["name"],
    "__HYP_TOP_DENS__": str(top_hyp["density"]),
    "__HYP_MEDIAN__": str(hyp_median),
    "__LB_HYP_DENS__": str(libai_num["hyperbole_per_100_chars"]),
    "__LB_HYP_RANK__": str(libai_rank),
    "__LB_MAG_RANK__": str(libai_mag_rank),
    "__SMALL_NAME__": small_note["name"] if small_note else "无",
    "__SMALL_DENS__": str(small_note["density"]) if small_note else "—",
    "__SMALL_POEMS__": str(small_note["poems"]) if small_note else "0",
    "__SMALL_CHARS__": str(small_note["chars"]) if small_note else "0",
    "__LQ_WEIGHTED__": str(lq["weighted"]),
    "__LB_WEIGHTED__": str(lb["weighted"]),
    "__LY_WEIGHTED__": str(ly["weighted"]),
    "__MED_X__": str(med_x),
    "__MED_Y__": str(med_y),
    "__SIX_SAMPLE_COUNTS__": "、".join(f"{p}{six_sol[p]['poems']}首" for p in SIX),
}
for k, v in repl.items():
    HTML = HTML.replace(k, v)
assert "__" not in HTML.replace("__proto__", ""), "存在未替换的占位符"

with open(OUT_HTML, "w", encoding="utf-8") as f:
    f.write(HTML)

# ---------------------------------------------------------------- 自检

html_bytes = OUT_HTML.read_bytes()
text = html_bytes.decode("utf-8")
checks = {
    "bytes>=5000": len(html_bytes) >= 5000,
    "viewport": 'name="viewport"' in text,
    "no_remote_script": ("src=\"http" not in text and "src='http" not in text),
    "no_nan_literal": ("NaN" not in text and "Infinity" not in text),
    "local_echarts": 'src="assets/pyecharts/v6/echarts.min.js"' in text,
    "nav_29_39_links": all(name in text for name in (
        "29_参赛导航.html", "30_诗行万里_参赛版.html", "31_凝望罗盘.html",
        "32_身与心双层地图.html", "33_平行时空759.html", "34_一字识诗人.html",
        "35_两种孤独与夸张签名.html", "36_同龄对齐.html", "37_可听的诗.html",
        "38_唐宋意象潮汐.html", "39_诗人自述生命卷.html",
    )),
}
print(f"HTML  -> {OUT_HTML}  ({len(html_bytes)} bytes)")
print(f"JSON  -> {OUT_JSON}  ({OUT_JSON.stat().st_size} bytes)")
for k, v in checks.items():
    print(f"  [{'PASS' if v else 'FAIL'}] {k}")
assert all(checks.values()), "自检未通过"
print("六人落点：", "；".join(f"{p}({six_land[p]})" for p in SIX))
print(f"孤独密度：六人第1 {six_density_order[0]} {six_sol[six_density_order[0]]['density']}；李清照 {lq['density']}（第{lq['rank']}/{len(pool)}）；李白 {lb['density']}（第{lb['rank']}/{len(pool)}）")
print(f"夸张密度：{hyp_top10[0]['name']} {hyp_top10[0]['density']} 第1；李白 {libai_num['hyperbole_per_100_chars']} 第{libai_rank}")
