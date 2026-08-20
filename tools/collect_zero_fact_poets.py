# -*- coding: utf-8 -*-
"""零事实诗人补采集：搜韵编年索引重抓（换源重试）。

背景：15 位零事实诗人中 13 位 CNKGraph 无传记（HTTP 204），但
data/candidates/souyun_identity_probe_88.json 的身份探测已给出其搜韵
author_id（消歧早已完成），当时未抓编年。本工具按探测结果逐页抓取
搜韵开放 Poem API（scope=Author），只保留带 AuthorDate 的行，
按既有 work_chronology 候选 schema 独立落盘，供晋级管线读取。

礼貌与可复现：
  - 请求间隔 ≥1.2s；原始响应逐页缓存至 data/candidates/zero_fact_recovery_raw/，
    重跑优先用缓存（离线可复现），--refresh 强制重抓；
  - 只解析数字年份（「794年」「794-795年」）， Era 纪年（如「宝历中」）跳过并计数；
  - 语料匹配按（诗人, 诗题）精确与去空格匹配，匹配上才带 body_hash 与 linked=true。

产出：
  data/candidates/work_chronology_zero_fact_recovery.jsonl（候选，schema 同主候选）
  data/candidates/zero_fact_recovery_summary.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBE = ROOT / "data" / "candidates" / "souyun_identity_probe_88.json"
POEMS_PATH = ROOT / "data" / "poems.json"
RAW_DIR = ROOT / "data" / "candidates" / "zero_fact_recovery_raw"
OUT_JSONL = ROOT / "data" / "candidates" / "work_chronology_zero_fact_recovery.jsonl"
OUT_SUMMARY = ROOT / "data" / "candidates" / "zero_fact_recovery_summary.json"

ZERO_POETS = [
    "上官仪", "卢纶", "司空曙", "司马光", "常建", "张志和", "张继",
    "晏几道", "晏殊", "朱淑真", "李益", "欧阳炯", "祖咏", "聂夷中", "钱惟演",
]
API = "https://api.sou-yun.cn/open/Poem"
PAGE_SIZE = 20
SLEEP_S = 1.2
YEAR_RANGE_RE = re.compile(r"(\d{3,4})\s*[-—～]\s*(\d{3,4})")
YEAR_SINGLE_RE = re.compile(r"(\d{3,4})")


def fetch_page(poet: str, dynasty: str, page: int, refresh: bool) -> dict | None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = RAW_DIR / f"{poet}_p{page}.json"
    if cache.exists() and not refresh:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            pass
    url = (
        f"{API}?key={urllib.parse.quote(poet)}&scope=Author"
        f"&dynasty={dynasty}&jsonType=true&pageNo={page}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "shixing-wanli-research/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                text = r.read().decode("utf-8")
            data = json.loads(text) if text.strip() else None
            cache.write_text(text, encoding="utf-8")
            time.sleep(SLEEP_S)
            return data
        except Exception as e:  # 网络重试
            if attempt == 2:
                print(f"  [warn] {poet} p{page} 抓取失败：{e}")
                return None
            time.sleep(2.0 + attempt)
    return None


def parse_year(author_date: str):
    """「794年」「794-795年」→ (start, end)；Era 纪年返回 None。"""
    if not author_date:
        return None
    m = YEAR_RANGE_RE.search(author_date)
    if m:
        y1, y2 = int(m.group(1)), int(m.group(2))
        if y1 <= y2 and 500 <= y1 <= 2000:
            return y1, y2
    m = YEAR_SINGLE_RE.search(author_date)
    if m and 500 <= int(m.group(1)) <= 2000:
        y = int(m.group(1))
        return y, y
    return None


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--refresh", action="store_true", help="忽略缓存强制重抓")
    args = args.parse_args()

    probe = json.loads(PROBE.read_text(encoding="utf-8"))
    probe_by_poet = {r["poet"]: r for r in probe["rows"] if r.get("poet")}

    poems = json.loads(POEMS_PATH.read_text(encoding="utf-8"))
    corpus = {}
    for p in poems:
        poet = p.get("poet") or p.get("author") or ""
        title = (p.get("title") or "").strip()
        corpus.setdefault((poet, title), p)
        corpus.setdefault((poet, title.replace(" ", "")), p)

    out_rows = []
    per_poet = {}
    era_skipped = 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for poet in ZERO_POETS:
        pr = probe_by_poet.get(poet)
        if not pr or not pr.get("author_ids"):
            per_poet[poet] = {"status": "no_identity", "pages": 0, "dated": 0, "in_corpus": 0}
            continue
        dynasty = (pr.get("source_dynasties") or [pr.get("dynasty")])[0]
        dated = in_corpus = total = 0
        page = 0
        while True:
            data = fetch_page(poet, dynasty, page, args.refresh)
            if data is None:
                break
            rows = data.get("ShiData") or []
            total += len(rows)
            for r in rows:
                if (r.get("Author") or "") != poet:
                    continue
                ad = r.get("AuthorDate") or ""
                ys = parse_year(ad)
                if not ys:
                    if ad:
                        era_skipped += 1
                    continue
                title = ((r.get("Title") or {}).get("Content") or "").strip()
                if not title:
                    continue
                dated += 1
                pm = corpus.get((poet, title)) or corpus.get((poet, title.replace(" ", "")))
                body = (pm or {}).get("body") or ""
                body_hash = hashlib.sha256(body.encode()).hexdigest() if isinstance(body, str) and body else ""
                url = (
                    f"{API}?key={urllib.parse.quote(poet)}&scope=Author"
                    f"&dynasty={dynasty}&jsonType=true&pageNo={page}"
                )
                cid = hashlib.md5(f"{poet}|{title}|{ys[0]}|recovery".encode("utf-8")).hexdigest()
                if any(o.get("candidate_id") == cid for o in out_rows):
                    continue
                if pm:
                    in_corpus += 1
                out_rows.append(
                    {
                        "access_level": "public_web",
                        "body_hash": body_hash,
                        "candidate_id": cid,
                        "collected_at": now,
                        "event_type": "work_chronology",
                        "extraction_method": "souyun_open_poem_api_v1_recovery",
                        "historical_place": "",
                        "license": "",
                        "license_note": "搜韵无机器复用的明确开放许可；仅保存结构化字段与必要短引，年份需人工复核",
                        "linked": pm is not None,
                        "poem_title": title,
                        "poet": poet,
                        "precision": "year",
                        "review_note": "",
                        "reviewed_at": "",
                        "reviewer": "",
                        "source": "souyun",
                        "source_grade": "C",
                        "source_name": "搜韵开放API·作品编年索引（零事实诗人补采）",
                        "source_note": f"搜韵开放API AuthorDate 将《{title}》系于 {ad}（补采自身份探测 {pr['author_ids'][0]}）",
                        "source_pages": url,
                        "source_title": title,
                        "source_title_ambiguous": False,
                        "source_url": url,
                        "souyun_author_date": ad,
                        "souyun_author_id": pr["author_ids"][0],
                        "souyun_dynasty": r.get("Dynasty") or "",
                        "souyun_work_id": r.get("Id"),
                        "status": "needs_review",
                        "year_end": ys[1],
                        "year_precision": "approximate",
                        "year_start": ys[0],
                    }
                )
            count = data.get("Count") or 0
            page += 1
            if page * PAGE_SIZE >= count or page > 30:
                break
        per_poet[poet] = {
            "status": "collected", "author_id": pr["author_ids"][0],
            "pages": page, "works_seen": total, "dated": dated, "in_corpus": in_corpus,
        }
        print(f"{poet:<4} 页{page:>2} 见{total:>3} 编年{dated:>3} 入语料{in_corpus:>3}")

    OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    out_rows.sort(key=lambda r: (r["poet"], r["poem_title"]))
    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")

    summary = {
        "n_candidates": len(out_rows),
        "n_in_corpus": sum(1 for r in out_rows if r["linked"]),
        "poets_requested": ZERO_POETS,
        "per_poet": per_poet,
        "era_dates_skipped": era_skipped,
        "policy": (
            "补采仅覆盖零事实诗人；来源为搜韵开放API AuthorDate（C 级，年份需人工复核）；"
            "只解析数字年份；候选独立落盘，晋级仍须经严格/放宽门。"
        ),
        "generated_by": "tools/collect_zero_fact_poets.py",
    }
    with open(OUT_SUMMARY, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, allow_nan=False)

    print("OK  ->", OUT_JSONL, f"({OUT_JSONL.stat().st_size} bytes)")
    print(f"候选 {len(out_rows)} 条（入语料 {summary['n_in_corpus']}） | Era 纪年跳过 {era_skipped}")


if __name__ == "__main__":
    main()
