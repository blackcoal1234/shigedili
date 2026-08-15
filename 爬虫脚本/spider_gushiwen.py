
import argparse
from collections import Counter
import json
import hashlib
import random
import re
import shutil
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

_save_lock = threading.Lock()

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "poems.json"
PARTIAL_OUT = OUT.with_name("poems.partial.json")
BACKUP_OUT = OUT.with_name("poems_backup.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Referer": "https://www.gushiwen.cn/",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

POETS = [
    # 唐
    ("李白",   "唐", "浪漫派"), ("杜甫",   "唐", "现实派"),
    ("白居易", "唐", "新乐府"), ("王维",   "唐", "山水田园"),
    ("孟浩然", "唐", "山水田园"), ("王昌龄", "唐", "边塞派"),
    ("高适",   "唐", "边塞派"), ("岑参",   "唐", "边塞派"),
    ("李商隐", "唐", "晚唐"),   ("杜牧",   "唐", "晚唐"),
    ("刘禹锡", "唐", "中唐"),   ("柳宗元", "唐", "中唐"),
    ("韩愈",   "唐", "古文"),   ("王勃",   "唐", "初唐"),
    ("王之涣", "唐", "边塞派"), ("李贺",   "唐", "中唐"),
    ("贺知章", "唐", "初唐"),   ("骆宾王", "唐", "初唐"),
    ("陈子昂", "唐", "初唐"),   ("张九龄", "唐", "盛唐"),
    ("元稹",   "唐", "新乐府"), ("韦应物", "唐", "山水田园"),
    ("常建",   "唐", "山水田园"), ("祖咏",   "唐", "山水田园"),
    ("张继",   "唐", "中唐"),   ("张志和", "唐", "中唐"),
    ("温庭筠", "唐", "晚唐"),   ("韦庄",   "唐", "晚唐"),
    ("李煜",   "唐", "晚唐"),   ("许浑",   "唐", "晚唐"),
    ("罗隐",   "唐", "晚唐"),   ("皮日休", "唐", "晚唐"),
    ("聂夷中", "唐", "晚唐"),   ("杜荀鹤", "唐", "晚唐"),
    ("司空曙", "唐", "中唐"),   ("卢纶",   "唐", "中唐"),
    ("钱起",   "唐", "中唐"),   ("李益",   "唐", "中唐"),
    ("贾岛",   "唐", "中唐"),   ("孟郊",   "唐", "中唐"),
    ("张籍",   "唐", "中唐"),   ("王建",   "唐", "中唐"),
    ("沈佺期", "唐", "初唐"),   ("宋之问", "唐", "初唐"),
    ("上官仪", "唐", "初唐"),
    # 宋
    ("苏轼",   "宋", "豪放派"), ("辛弃疾", "宋", "豪放派"),
    ("陆游",   "宋", "爱国派"), ("李清照", "宋", "婉约派"),
    ("欧阳修", "宋", "古文"),   ("王安石", "宋", "改革派"),
    ("黄庭坚", "宋", "江西诗派"), ("范成大", "宋", "中兴四大家"),
    ("杨万里", "宋", "中兴四大家"), ("尤袤",   "宋", "中兴四大家"),
    ("柳永",   "宋", "婉约派"), ("晏殊",   "宋", "婉约派"),
    ("晏几道", "宋", "婉约派"), ("秦观",   "宋", "婉约派"),
    ("周邦彦", "宋", "婉约派"), ("姜夔",   "宋", "格律派"),
    ("吴文英", "宋", "格律派"), ("张炎",   "宋", "格律派"),
    ("陈与义", "宋", "江西诗派"), ("文天祥", "宋", "爱国派"),
    ("范仲淹", "宋", "豪放派"), ("司马光", "宋", "古文"),
    ("朱熹",   "宋", "理学"),   ("林逋",   "宋", "隐逸"),
    ("梅尧臣", "宋", "古文"),   ("苏辙",   "宋", "古文"),
    ("苏洵",   "宋", "古文"),   ("曾巩",   "宋", "古文"),
    ("张孝祥", "宋", "豪放派"), ("张元干", "宋", "豪放派"),
    ("陈亮",   "宋", "豪放派"), ("刘克庄", "宋", "豪放派"),
    ("叶梦得", "宋", "豪放派"), ("贺铸",   "宋", "婉约派"),
    ("张先",   "宋", "婉约派"), ("欧阳炯", "宋", "婉约派"),
    ("朱淑真", "宋", "婉约派"), ("程颢",   "宋", "理学"),
    ("陆九渊", "宋", "理学"),   ("吕本中", "宋", "江西诗派"),
    ("杨亿",   "宋", "西昆体"), ("钱惟演", "宋", "西昆体"),
    ("石延年", "宋", "古文"),
]


def fetch(url: str, retries: int = 3) -> str:
    """带重试与礼貌延迟的 GET。"""
    last_exc = None
    for attempt in range(retries):
        try:
            time.sleep(random.uniform(0.4, 0.9))
            r = requests.get(url, headers=HEADERS, timeout=10)
            r.encoding = "utf-8"
            if r.status_code == 200 and len(r.text) > 1000:
                return r.text
            raise RuntimeError(f"bad status {r.status_code} len {len(r.text)}")
        except Exception as e:
            last_exc = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"fetch failed after {retries}: {url}: {last_exc}")


def parse_poem_links(html: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r'href="(/shiwenv_[^"]+)"', html)))


def parse_poem_detail(html: str) -> dict | None:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:
        if "Couldn't find a tree builder" not in str(exc):
            raise
        soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("div.cont h1")
    src_el = soup.select_one("div.cont p.source")
    body_el = soup.select_one("div.cont div.contson")
    if not (title_el and body_el):
        return None
    title = title_el.get_text(strip=True)
    src = src_el.get_text(" ", strip=True) if src_el else ""
    dyn = ""
    author = ""
    m = re.search(r"\[\s*(\S+?)\s*\]", src) or re.match(r"^\s*(\S+?)\s+", src)
    if m:
        author = m.group(1)
    if "唐" in src:
        dyn = "唐"
    elif "宋" in src:
        dyn = "宋"
    elif "魏" in src or "晋" in src:
        dyn = "魏晋"
    body = body_el.get_text("\n", strip=True)
    body = re.sub(r"[（(].*?[)）]", "", body)
    return dict(title=title, author=author, dynasty=dyn, body=body)


def fetch_poem_detail(url: str, max_samples: int = 5) -> dict:
    """Require two matching source responses to defeat intermittent character substitution."""
    samples: list[dict] = []
    for _ in range(max_samples):
        detail = parse_poem_detail(fetch(url))
        if not detail or not detail.get("body"):
            continue
        samples.append(detail)
        body_counts = Counter(str(item["body"]) for item in samples)
        body, count = body_counts.most_common(1)[0]
        if count >= 2:
            return next(item for item in reversed(samples) if item["body"] == body)
    raise RuntimeError(f"detail body did not reach consensus after {max_samples} samples: {url}")


def crawl_poet(
    name: str,
    max_poems: int | None = 30,
    max_pages: int | None = 4,
    known_source_ids: set[str] | None = None,
) -> tuple[list[dict], dict]:
    """跨多页抓取某诗人作品，并返回可审计的分页完成状态。"""
    known_source_ids = known_source_ids or set()
    all_links: list[str] = []
    seen_links = set()
    pages_scanned = 0
    natural_end = False
    list_error = ""
    page = 1
    while max_pages is None or page <= max_pages:
        list_url = (f"https://www.gushiwen.cn/shiwens/default.aspx"
                    f"?astr={quote(name)}&page={page}")
        try:
            html = fetch(list_url)
        except Exception as e:
            print(f"  list page {page} fail: {e}")
            list_error = str(e)
            break
        pages_scanned += 1
        page_links = parse_poem_links(html)
        new_links = [h for h in page_links if h not in seen_links]
        if not new_links:
            natural_end = True
            break  # 翻不出新内容了，已到作者列表自然末页
        for h in new_links:
            seen_links.add(h)
            all_links.append(h)
        if max_poems is not None and len(all_links) >= max_poems * 2:
            break
        page += 1

    poems: list[dict] = []
    seen_poems = set()
    known_skipped = 0
    wrong_author_skipped = 0
    short_body_skipped = 0
    failed_detail_urls: list[str] = []
    for href in all_links:
        if max_poems is not None and len(poems) >= max_poems:
            break
        url = "https://www.gushiwen.cn" + href
        source_match = re.search(r"/shiwenv_([^./?]+)", href)
        source_id = source_match.group(1) if source_match else ""
        if source_id and source_id in known_source_ids:
            known_skipped += 1
            continue
        try:
            detail = fetch_poem_detail(url)
        except Exception as e:
            print(f"  skip {url}: {e}")
            failed_detail_urls.append(url)
            continue
        if not detail:
            failed_detail_urls.append(url)
            continue
        # 过滤掉非本人作品（古诗文网搜索可能返回相关诗人）
        if detail["author"] and detail["author"] != name:
            wrong_author_skipped += 1
            continue
        if not detail["author"]:
            detail["author"] = name
        # 太短的容易是片段错抓
        if len(detail["body"]) < 16:
            short_body_skipped += 1
            continue
        body_hash = hashlib.sha256(detail["body"].encode("utf-8")).hexdigest()
        dedup_key = (detail["author"], body_hash)
        if dedup_key in seen_poems:
            continue
        seen_poems.add(dedup_key)
        detail["source_site"] = "古诗文网"
        detail["source_url"] = url
        detail["source_poem_id"] = source_id
        detail["body_hash"] = body_hash
        detail["crawled_at"] = datetime.now(timezone.utc).isoformat()
        poems.append(detail)
    stopped_by_poem_limit = max_poems is not None and len(poems) >= max_poems
    scan = {
        "complete": natural_end and not list_error and not failed_detail_urls and not stopped_by_poem_limit,
        "natural_end": natural_end,
        "pages_scanned": pages_scanned,
        "links_discovered": len(all_links),
        "known_source_ids_skipped": known_skipped,
        "new_records_fetched": len(poems),
        "wrong_author_skipped": wrong_author_skipped,
        "short_body_skipped": short_body_skipped,
        "failed_detail_urls": failed_detail_urls,
        "list_error": list_error,
        "stopped_by_poem_limit": stopped_by_poem_limit,
    }
    return poems, scan


def write_json_atomic(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def merge_records(existing: list[dict], fresh: list[dict]) -> tuple[list[dict], int]:
    """按作者+正文哈希增量合并；保留旧记录并补齐旧记录缺失字段。"""
    merged: list[dict] = []
    positions: dict[tuple[str, str], int] = {}
    for record in [*existing, *fresh]:
        author = str(record.get("author") or record.get("poet") or "")
        body = str(record.get("body") or "")
        body_hash = str(record.get("body_hash") or "")
        if not body_hash and body:
            body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
            record = {**record, "body_hash": body_hash}
        key = (author, body_hash)
        if key in positions:
            target = merged[positions[key]]
            for field, value in record.items():
                if value not in (None, "", []) and target.get(field) in (None, "", []):
                    target[field] = value
            continue
        positions[key] = len(merged)
        merged.append(dict(record))
    return merged, len(merged) - len(existing)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="古诗文网作者语料增量采集")
    parser.add_argument(
        "--max-poems-per-poet",
        type=int,
        default=20,
        help="每位诗人本轮新增抓取上限；0 表示不限",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="每位诗人列表页上限；0 表示抓到自然末页",
    )
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--poet", action="append", default=[], help="只抓指定诗人，可重复")
    parser.add_argument(
        "--resume-partial",
        action="store_true",
        help="从同一输出路径的 poems.partial.json 恢复未完成轮次",
    )
    parser.add_argument("--replace", action="store_true", help="用本轮结果替换旧语料；默认增量合并")
    parser.add_argument("--output", type=Path, default=OUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.max_poems_per_poet < 0 or args.max_pages < 0:
        raise SystemExit("--max-poems-per-poet 与 --max-pages 必须大于等于 0")
    output = args.output.resolve()
    partial_out = output.with_name(output.stem + ".partial" + output.suffix)
    backup_out = output.with_name(output.stem + "_backup" + output.suffix)
    stats_out = output.with_name(output.stem + "_crawl_stats.json")

    existing: list[dict] = []
    if output.exists() and not args.replace:
        loaded = json.loads(output.read_text(encoding="utf-8"))
        if not isinstance(loaded, list):
            raise ValueError(f"现有语料不是数组：{output}")
        existing = loaded
    checkpoint_records: list[dict] = []
    if args.resume_partial and partial_out.exists():
        loaded_partial = json.loads(partial_out.read_text(encoding="utf-8"))
        if not isinstance(loaded_partial, list):
            raise ValueError(f"增量检查点不是数组：{partial_out}")
        checkpoint_records = loaded_partial
        print(f"  [resume] 从 {partial_out.name} 恢复 {len(checkpoint_records)} 条详情")
    known_source_ids: dict[str, set[str]] = {}
    for record in [*existing, *checkpoint_records]:
        poet = str(record.get("poet") or record.get("author") or "")
        source_id = str(record.get("source_poem_id") or "")
        if not source_id:
            match = re.search(r"/shiwenv_([^./?]+)", str(record.get("source_url") or ""))
            source_id = match.group(1) if match else ""
        if poet and source_id:
            known_source_ids.setdefault(poet, set()).add(source_id)
    fresh_records: list[dict] = list(checkpoint_records)
    completed = [0]

    def crawl_one(task):
        idx, name, dyn, school = task
        try:
            poems, scan = crawl_poet(
                name,
                max_poems=None if args.max_poems_per_poet == 0 else args.max_poems_per_poet,
                max_pages=None if args.max_pages == 0 else args.max_pages,
                known_source_ids=known_source_ids.get(name, set()),
            )
        except Exception as e:
            print(f"  [{idx}] {name} failed: {e}")
            return [], {
                "complete": False,
                "natural_end": False,
                "pages_scanned": 0,
                "links_discovered": 0,
                "known_source_ids_skipped": 0,
                "new_records_fetched": 0,
                "wrong_author_skipped": 0,
                "short_body_skipped": 0,
                "failed_detail_urls": [],
                "list_error": str(e),
                "stopped_by_poem_limit": False,
            }
        for p in poems:
            # 以种子表里的朝代为准，覆盖详情页解析（古诗文网偶尔标记不全）
            if not p.get("dynasty"):
                p["dynasty"] = dyn
            p["school"] = school
            p["poet"] = name
        return poems, scan

    selected = [row for row in POETS if not args.poet or row[0] in set(args.poet)]
    missing_requested = sorted(set(args.poet) - {row[0] for row in selected})
    if missing_requested:
        raise SystemExit(f"诗人不在种子表：{missing_requested}")
    total = len(selected)
    tasks = [(i, name, dyn, school) for i, (name, dyn, school) in enumerate(selected, 1)]

    # 并发 5 线程，每线程内部已有延迟，不会对服务器造成过大压力
    per_poet_counts: dict[str, int] = {}
    per_poet_scan: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(12, args.workers))) as pool:
        futures = {pool.submit(crawl_one, t): t for t in tasks}
        for fut in as_completed(futures):
            idx, name, dyn, school = futures[fut]
            poems, scan = fut.result()
            with _save_lock:
                fresh_records.extend(poems)
                per_poet_counts[name] = len(poems)
                per_poet_scan[name] = scan
                completed[0] += 1
                state = "完整" if scan["complete"] else "未完整"
                print(
                    f"  [{completed[0]}/{total}] {name}: 新增抓取 {len(poems)} 首, "
                    f"列表 {scan['pages_scanned']} 页/{scan['links_discovered']} 链接, "
                    f"{state}, 本轮累计 {len(fresh_records)}"
                )
                write_json_atomic(partial_out, fresh_records)

    per_poet_counts = {}
    for record in fresh_records:
        poet = str(record.get("poet") or record.get("author") or "")
        if poet:
            per_poet_counts[poet] = per_poet_counts.get(poet, 0) + 1

    merged, added = merge_records(existing, fresh_records)
    if output.exists():
        shutil.copy2(output, backup_out)
        timestamp_backup = output.with_name(
            output.stem + "_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + output.suffix
        )
        shutil.copy2(output, timestamp_backup)
        print(f"  [backup] {output.name} -> {backup_out.name}, {timestamp_backup.name}")
    write_json_atomic(output, merged)
    partial_out.unlink(missing_ok=True)
    incomplete_poets = sorted(name for name, scan in per_poet_scan.items() if not scan["complete"])
    stats = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "source": "https://www.gushiwen.cn/shiwens/default.aspx",
        "poet_scope": [name for name, _dyn, _school in selected],
        "max_poems_per_poet": args.max_poems_per_poet,
        "max_pages": args.max_pages,
        "workers": args.workers,
        "existing_before": len(existing),
        "fresh_fetched": len(fresh_records),
        "new_after_dedup": added,
        "merged_total": len(merged),
        "complete": not incomplete_poets,
        "incomplete_poets": incomplete_poets,
        "per_poet_fetched": dict(sorted(per_poet_counts.items())),
        "per_poet_scan": dict(sorted(per_poet_scan.items())),
    }
    stats_out.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[done] fresh={len(fresh_records)} added={added} total={len(merged)} -> {output}")
    print(f"[stats] {stats_out}")
    if args.max_poems_per_poet == 0 and args.max_pages == 0 and incomplete_poets:
        raise SystemExit(f"完整采集仍有未闭合作者：{', '.join(incomplete_poets)}")


if __name__ == "__main__":
    main()
