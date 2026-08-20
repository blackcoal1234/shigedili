# -*- coding: utf-8 -*-
"""零事实诗人补采（第二路）：古诗文网创作背景条目。

语料本身爬自古诗文网，每首诗页面多有「创作背景」段（常含公历年与作地）。
本工具复用项目 background_adapters 的 HttpCacheClient（缓存/robots/限速）
与 collect_gushiwen 解析器，对 15 位零事实诗人各取语料中排序最前的
MAX_PER_POET 首（爬取序≈站内热度序）抓取背景段，抽取：

  年份：优先「公元YYYY年」「（YYYY年）」，全文唯一年份时兜底；
  作地：背景段文本中的古地名（place_dict 别名词典命中，取最长者），
        仅作「背景条目提及」（composition_place_prose），不作直接主张。

候选并入 work_chronology_zero_fact_recovery.jsonl（source=gushiwen，C 级），
晋级仍须过严格/放宽门。重跑优先用缓存，--refresh 强制重抓。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))
sys.path.insert(0, str(ROOT / "tools"))

from bs4 import BeautifulSoup  # noqa: E402

from background_adapters import HttpCacheClient  # noqa: E402
from data.place_dict import PLACE_DICT  # noqa: E402

POEMS_PATH = ROOT / "data" / "poems.json"
RECOVERY = ROOT / "data" / "candidates" / "work_chronology_zero_fact_recovery.jsonl"
SUMMARY = ROOT / "data" / "candidates" / "zero_fact_recovery_summary.json"

ZERO_POETS = [
    "上官仪", "卢纶", "司空曙", "司马光", "常建", "张志和", "张继",
    "晏几道", "晏殊", "朱淑真", "李益", "欧阳炯", "祖咏", "聂夷中", "钱惟演",
]
MAX_PER_POET = 15

YEAR_PATTERNS = (
    re.compile(r"公元\s*(\d{3,4})\s*年"),
    re.compile(r"[（(]\s*(\d{3,4})\s*年\s*[）)]"),
    re.compile(r"作于\s*(\d{3,4})"),
    re.compile(r"写于\s*(\d{3,4})"),
)
ANY_YEAR = re.compile(r"(\d{3,4})\s*年")

# ---- 年号→公元对照（隋·唐·武周·五代·宋；硬编码可审计；边界年 ±1 属正常）----
ERA_TABLE = {
    "开皇": (581, 600), "仁寿": (601, 604), "大业": (605, 618),
    "武德": (618, 626), "贞观": (627, 649), "永徽": (650, 655), "显庆": (656, 660),
    "龙朔": (661, 663), "麟德": (664, 665), "乾封": (666, 667), "总章": (668, 669),
    "咸亨": (670, 673), "上元": (674, 675), "仪凤": (676, 678), "调露": (679, 679),
    "永隆": (680, 681), "开耀": (681, 681), "永淳": (682, 682), "弘道": (683, 683),
    "嗣圣": (684, 684), "文明": (684, 684), "光宅": (684, 684), "垂拱": (685, 688),
    "永昌": (689, 689), "载初": (690, 690),
    "天授": (690, 692), "如意": (692, 692), "长寿": (692, 694), "延载": (694, 694),
    "证圣": (695, 695), "天册万岁": (695, 696), "万岁登封": (696, 696),
    "万岁通天": (696, 697), "神功": (697, 697), "圣历": (698, 700), "久视": (700, 700),
    "大足": (701, 701), "长安": (701, 704),
    "神龙": (705, 707), "景龙": (707, 710), "唐隆": (710, 710), "景云": (710, 712),
    "太极": (712, 712), "延和": (712, 712), "先天": (712, 713),
    "开元": (713, 741), "天宝": (742, 756), "至德": (756, 757), "乾元": (758, 759),
    "宝应": (762, 763), "广德": (763, 764), "永泰": (765, 765), "大历": (766, 779),
    "建中": (780, 783), "兴元": (784, 784), "贞元": (785, 805), "永贞": (805, 805),
    "元和": (806, 820), "长庆": (821, 824), "宝历": (825, 827), "大和": (827, 835),
    "太和": (827, 835), "开成": (836, 840), "会昌": (841, 846), "大中": (847, 859),
    "咸通": (860, 873), "乾符": (874, 879), "广明": (880, 880), "中和": (881, 885),
    "光启": (885, 888), "文德": (888, 888), "龙纪": (889, 889), "大顺": (890, 891),
    "景福": (892, 893), "乾宁": (894, 897), "光化": (898, 900), "天复": (901, 904),
    "天祐": (904, 906),
    "开平": (907, 910), "乾化": (911, 914), "贞明": (915, 920), "龙德": (921, 923),
    "同光": (923, 926), "天成": (926, 929), "长兴": (930, 933), "应顺": (934, 934),
    "清泰": (934, 936), "天福": (936, 943), "开运": (944, 945), "乾祐": (948, 950),
    "显德": (954, 959),
    "建隆": (960, 962), "乾德": (963, 967), "开宝": (968, 975), "太平兴国": (976, 983),
    "雍熙": (984, 987), "端拱": (988, 989), "淳化": (990, 994), "至道": (995, 997),
    "咸平": (998, 1003), "景德": (1004, 1007), "大中祥符": (1008, 1016), "天禧": (1017, 1021),
    "乾兴": (1022, 1022), "天圣": (1023, 1031), "明道": (1032, 1033), "景祐": (1034, 1037),
    "宝元": (1038, 1039), "康定": (1040, 1040), "庆历": (1041, 1048), "皇祐": (1049, 1053),
    "至和": (1054, 1055), "嘉祐": (1056, 1063), "治平": (1064, 1067), "熙宁": (1068, 1077),
    "元丰": (1078, 1085), "元祐": (1086, 1093), "绍圣": (1095, 1097), "元符": (1098, 1100),
    "建中靖国": (1101, 1101), "崇宁": (1102, 1106), "大观": (1107, 1110), "政和": (1111, 1117),
    "重和": (1118, 1118), "宣和": (1119, 1125), "靖康": (1126, 1126), "建炎": (1127, 1129),
    "绍兴": (1131, 1161), "隆兴": (1163, 1164), "乾道": (1165, 1172), "淳熙": (1174, 1188),
    "绍熙": (1190, 1194), "庆元": (1195, 1200), "嘉泰": (1201, 1204), "开禧": (1205, 1207),
    "嘉定": (1208, 1223), "宝庆": (1225, 1227), "绍定": (1228, 1233), "端平": (1234, 1235),
    "嘉熙": (1237, 1240), "淳祐": (1241, 1252), "宝祐": (1253, 1258), "开庆": (1259, 1259),
    "景定": (1260, 1264), "咸淳": (1265, 1274),
}
_ERA_KEYS = sorted(ERA_TABLE, key=len, reverse=True)
_ERA_ALT = "|".join(_ERA_KEYS)
CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
ERA_NUM_FULL = re.compile(r"(" + _ERA_ALT + r")\s*(元|[一二三四五六七八九十廿]{1,3})\s*[载年]")
ERA_EDGE_RE = re.compile(r"(" + _ERA_ALT + r")\s*年?\s*(初|末)")
ERA_SPAN_RE = re.compile(r"(" + _ERA_ALT + r")\s*年?间")


def _cn_year(token: str):
    if token == "元":
        return 1
    if token == "十":
        return 10
    if token.startswith("廿"):
        rest = token[1:]
        return 20 + (CN_DIGITS.get(rest, 0) if rest else 0)
    if "十" in token:
        a, _, b = token.partition("十")
        tens = CN_DIGITS.get(a, 1) if a else 1
        ones = CN_DIGITS.get(b, 0) if b else 0
        return tens * 10 + ones
    return CN_DIGITS.get(token)


def extract_year_era(text: str):
    """年号纪年 → (start, end, precision)；无命中返回 None。"""
    m = ERA_NUM_FULL.search(text)
    if m:
        n = _cn_year(m.group(2))
        if n and 1 <= n <= 40:
            s = ERA_TABLE[m.group(1)][0] + (n - 1)
            if s <= ERA_TABLE[m.group(1)][1] + 1:
                return s, s, "era_year"
    m = ERA_EDGE_RE.search(text)
    if m:
        s, e = ERA_TABLE[m.group(1)]
        return (s, s + 2, "era_early") if m.group(2) == "初" else (e - 2, e, "era_late")
    m = ERA_SPAN_RE.search(text)
    if m:
        s, e = ERA_TABLE[m.group(1)]
        if e - s <= 15:
            return s, e, "era_range"
    return None



ALIASES = sorted((a for a, _m, _p, _lo, _la, _n in PLACE_DICT if len(a) >= 2), key=len, reverse=True)
ALIAS_INFO = {a: (m, p) for a, m, p, _lo, _la, _n in PLACE_DICT}


def extract_year(text: str):
    """公元纪年优先，其次年号纪年；返回 (start, end, precision) 或 None。"""
    for pat in YEAR_PATTERNS:
        m = pat.search(text)
        if m and 500 <= int(m.group(1)) <= 2000:
            y = int(m.group(1))
            return y, y, "approximate"
    years = {int(m.group(1)) for m in ANY_YEAR.finditer(text) if 500 <= int(m.group(1)) <= 2000}
    if len(years) == 1:
        y = next(iter(years))
        return y, y, "approximate"
    return extract_year_era(text)


def extract_place(text: str):
    for alias in ALIASES:
        if alias in text:
            modern, prov = ALIAS_INFO[alias]
            return alias, modern, prov
    return None


def parse_bg_v2(html: str, want_title: str) -> list[dict]:
    """v2 解析：直接取 div.contyishang 块（v1 的 find_parent 落在标题内层 div 上，
    导致正文不足 8 字被整体丢弃）；以页面标题含诗题做轻校验。"""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    page_title = (soup.title.get_text(" ", strip=True) if soup.title else "")
    h1 = soup.find("h1")
    h1_title = h1.get_text(" ", strip=True) if h1 else ""
    if want_title and want_title not in page_title and want_title not in h1_title:
        return []
    out = []
    for box in soup.select("div.contyishang"):
        head = box.find(["h2", "h3", "h4"])
        heading = head.get_text(" ", strip=True) if head else ""
        paras = [p.get_text(" ", strip=True) for p in box.find_all("p")]
        text = re.sub(r"\s+", " ", " ".join(paras)).strip()
        if heading in ("创作背景", "背景") and len(text) >= 8:
            out.append({"heading": heading, "excerpt": text})
    return out


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    poems = json.loads(POEMS_PATH.read_text(encoding="utf-8"))
    per_poet: dict[str, list] = {}
    seen_titles: set[tuple[str, str]] = set()
    for p in poems:
        poet = p.get("poet") or p.get("author")
        if poet not in ZERO_POETS or not p.get("source_url"):
            continue
        key = (poet, p.get("title") or "")
        if key in seen_titles:
            continue
        seen_titles.add(key)
        per_poet.setdefault(poet, []).append(p)
        if len(per_poet[poet]) >= MAX_PER_POET:
            continue

    client = HttpCacheClient()
    existing = []
    if RECOVERY.exists():
        existing = [json.loads(l) for l in RECOVERY.read_text(encoding="utf-8").splitlines() if l.strip()]
    have_ids = {r.get("candidate_id") for r in existing}

    new_rows = []
    per_stat = {}
    for poet in ZERO_POETS:
        batch = per_poet.get(poet, [])[:MAX_PER_POET]
        fetched = bg = dated = with_place = 0
        for pm in batch:
            url = pm.get("source_url")
            try:
                result = client.request("GET", url, respect_robots=True)
            except Exception as e:
                print(f"  [warn] {poet}《{pm.get('title')}》采集异常：{e}")
                continue
            if result.status != "ok":
                continue
            fetched += 1
            sections = parse_bg_v2(result.text, pm.get("title") or "")
            for sec in sections:
                excerpt = sec["excerpt"].strip()
                if not excerpt:
                    continue
                bg += 1
                year = extract_year(excerpt)  # (lo, hi, precision) 或 None
                place = extract_place(excerpt)
                if year is None and place is None:
                    continue
                if year is not None:
                    dated += 1
                if place is not None:
                    with_place += 1
                title = pm.get("title") or ""
                body = pm.get("body") or ""
                cid = hashlib.md5(
                    f"{poet}|{title}|gushiwen_bg|{year[0] if year else ''}|{place[0] if place else ''}".encode("utf-8")
                ).hexdigest()
                if cid in have_ids:
                    continue
                have_ids.add(cid)
                alias, modern, prov = place if place else ("", "", "")
                new_rows.append(
                    {
                        "access_level": "public_web",
                        "body_hash": hashlib.sha256(body.encode()).hexdigest() if isinstance(body, str) and body else "",
                        "candidate_id": cid,
                        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "event_type": "work_chronology",
                        "extraction_method": "gushiwen_background_recovery_v1",
                        "historical_place": alias,
                        "historical_place_modern": modern,
                        "historical_place_province": prov,
                        "place_claim": "composition_place_prose" if alias else "",
                        "license": "",
                        "license_note": "仅保存必要短引；不发布第三方全文",
                        "linked": True,
                        "poem_title": title,
                        "poet": poet,
                        "precision": "year" if year is not None else "unknown",
                        "era_year": year[2].startswith("era") if year else False,
                        "review_note": "",
                        "reviewed_at": "",
                        "reviewer": "",
                        "source": "gushiwen",
                        "source_grade": "C",
                        "source_name": "古诗文网·创作背景条目（零事实诗人补采）",
                        "source_note": ("背景摘引：" + excerpt[:80] + ("…" if len(excerpt) > 80 else "")),
                        "source_pages": url,
                        "source_title": title,
                        "source_title_ambiguous": False,
                        "source_url": url,
                        "status": "needs_review",
                        "year_end": year[1] if year else None,
                        "year_precision": year[2] if year else "unknown",
                        "year_start": year[0] if year else None,
                    }
                )
        per_stat[poet] = {
            "poems_tried": len(batch), "pages_ok": fetched,
            "backgrounds": bg, "with_year": dated, "with_place": with_place,
        }
        print(
            f"{poet:<4} 尝试{len(batch):>2} 成功{fetched:>2} 背景{bg:>2} "
            f"带年{dated:>2} 带地{with_place:>2}"
        )

    all_rows = existing + new_rows
    all_rows.sort(key=lambda r: (r.get("poet") or "", r.get("poem_title") or ""))
    with open(RECOVERY, "w", encoding="utf-8") as f:
        for r in all_rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")

    summary = json.loads(SUMMARY.read_text(encoding="utf-8")) if SUMMARY.exists() else {}
    summary["gushiwen_recovery"] = {
        "n_new_candidates": len(new_rows),
        "n_recovery_total": len(all_rows),
        "per_poet": per_stat,
        "policy": (
            "古诗文网创作背景条目补采：每诗人取语料序前 15 首；年份取公元/括注纪年，"
            "作地仅作「背景条目提及」（composition_place_prose）；C 级，短引保存；"
            "晋级仍须过严格/放宽门。"
        ),
    }
    with open(SUMMARY, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, allow_nan=False)

    print("OK  ->", RECOVERY, f"（新增 {len(new_rows)}，合计 {len(all_rows)}）")
    print("OK  ->", SUMMARY)


if __name__ == "__main__":
    main()
