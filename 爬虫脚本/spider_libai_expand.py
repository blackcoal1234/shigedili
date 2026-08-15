# -*- coding: utf-8 -*-
"""扩充李白语料到 >=55 首。

策略（so.gushiwen.cn 站内搜索现已跳转 guwendao.net 且要求登录，匿名不可用）：
1. 翻李白作者列表页（www.gushiwen.cn/shiwens/default.aspx?astr=李白&page=N，
   按热度排序，翻到没有新链接为止，约 30 页 / 300 首），建立 标题 -> 详情页 索引。
2. 必须命中的诗先按标题（含别名：客中行=客中作、临路歌=临终歌、
   秋浦歌·其十五=秋浦歌十七首·十五）从索引定位详情页抓取。
   《永王东巡歌·其一》站内只有十一首合刊页，从合刊页切出前两行（即其一）。
3. 再按列表顺序补足其余，直到李白总数 >= 55。合刊组诗页（标题以"首"结尾）
   不作为补充候选，避免与已有单首内容重复。
4. 复用 spider_gushiwen 的 fetch（礼貌延迟 0.4-0.9s + 重试）与
   parse_poem_detail、body_hash 去重逻辑。
5. 写入前把 data/poems.json 备份为 data/poems_backup_pre_libai.json，
   只追加李白的记录，绝不改动其他诗人的数据。
"""

import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from spider_gushiwen import fetch, parse_poem_detail, write_json_atomic  # noqa: E402

ROOT = SCRIPT_DIR.parent
OUT = ROOT / "data" / "poems.json"
BACKUP = ROOT / "data" / "poems_backup_pre_libai.json"

POET = "李白"
SCHOOL = "浪漫派"
TARGET_TOTAL = 55
MAX_LIST_PAGES = 40

# (报告用标题, 可接受的页面标题变体)
MUST_TITLES: list[tuple[str, list[str]]] = [
    ("访戴天山道士不遇", ["访戴天山道士不遇"]),
    ("登锦城散花楼", ["登锦城散花楼"]),
    ("上李邕", ["上李邕"]),
    ("峨眉山月歌", ["峨眉山月歌"]),
    ("渡荆门送别", ["渡荆门送别"]),
    ("望天门山", ["望天门山"]),
    ("静夜思", ["静夜思"]),
    ("金陵酒肆留别", ["金陵酒肆留别"]),
    ("长干行·其一", ["长干行·其一", "长干行二首·其一"]),
    ("蜀道难", ["蜀道难"]),
    ("客中行", ["客中行", "客中作"]),
    ("南陵别儿童入京", ["南陵别儿童入京"]),
    ("清平调·其一", ["清平调·其一", "清平调词三首·其一"]),
    ("月下独酌·其一", ["月下独酌·其一", "月下独酌四首·其一"]),
    ("行路难·其一", ["行路难·其一", "行路难三首·其一"]),
    ("梁园吟", ["梁园吟"]),
    ("梦游天姥吟留别", ["梦游天姥吟留别"]),
    ("将进酒", ["将进酒"]),
    ("北风行", ["北风行"]),
    ("独坐敬亭山", ["独坐敬亭山"]),
    ("秋浦歌·其十五", ["秋浦歌·其十五", "秋浦歌十七首·其十五", "秋浦歌十七首·十五"]),
    ("闻王昌龄左迁龙标遥有此寄", ["闻王昌龄左迁龙标遥有此寄"]),
    ("赠汪伦", ["赠汪伦"]),
    ("永王东巡歌·其一", ["永王东巡歌·其一", "永王东巡歌十一首·其一"]),
    ("流夜郎赠辛判官", ["流夜郎赠辛判官"]),
    ("上三峡", ["上三峡"]),
    ("与夏十二登岳阳楼", ["与夏十二登岳阳楼"]),
    ("宿五松山下荀媪家", ["宿五松山下荀媪家"]),
    ("临路歌", ["临路歌", "临终歌"]),
]


def norm_title(t: str) -> str:
    return re.sub(r"[\s·，,。.：:（）()〔〕\[\]、/－\-]", "", t)


def build_index() -> dict[str, str]:
    """翻作者列表页，返回 {标题: /shiwenv_xxx.aspx}（保持列表顺序）。"""
    index: dict[str, str] = {}
    seen_links: set[str] = set()
    for page in range(1, MAX_LIST_PAGES + 1):
        url = (f"https://www.gushiwen.cn/shiwens/default.aspx"
               f"?astr={quote(POET)}&page={page}")
        try:
            html = fetch(url)
        except Exception as e:
            print(f"  [index] page {page} fail: {e}")
            continue
        pairs = re.findall(r'href="(/shiwenv_[^"]+)"[^>]*><b>(.*?)</b>', html)
        new = [(h, t) for h, t in pairs if h not in seen_links]
        if not new:
            print(f"  [index] page {page}: no new links, stop")
            break
        for h, t in new:
            seen_links.add(h)
            index.setdefault(t.strip(), h)
    print(f"  [index] {len(index)} titles collected")
    return index


def fetch_detail(href: str, attempts: int = 2) -> dict | None:
    """抓详情页并解析（fetch 内部已带 3 次重试，外层再兜 2 次）。"""
    url = "https://www.gushiwen.cn" + href
    last = None
    for _ in range(attempts):
        try:
            detail = parse_poem_detail(fetch(url))
            if detail:
                detail["_href"] = href
                return detail
            return None
        except Exception as e:
            last = e
    print(f"  [detail] give up {url}: {last}")
    return None


def make_record(detail: dict) -> dict:
    href = detail["_href"]
    m = re.search(r"/shiwenv_([^./?]+)", href)
    body = detail["body"]
    return {
        "title": detail["title"],
        "author": POET,
        "dynasty": detail.get("dynasty") or "唐",
        "body": body,
        "source_site": "古诗文网",
        "source_url": "https://www.gushiwen.cn" + href,
        "source_poem_id": m.group(1) if m else "",
        "body_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "school": SCHOOL,
        "poet": POET,
    }


def main() -> None:
    all_records: list[dict] = json.loads(OUT.read_text(encoding="utf-8"))
    libai = [p for p in all_records if p.get("poet") == POET]
    libai_hashes = {p["body_hash"] for p in libai}
    libai_titles_norm = {norm_title(p["title"]) for p in libai}
    print(f"[start] 李白 {len(libai)} 首，目标 {TARGET_TOTAL}")

    index = build_index()
    index_norm = {norm_title(t): (t, h) for t, h in index.items()}

    new_records: list[dict] = []
    missing: list[str] = []

    def add_detail(detail: dict) -> bool:
        """校验 + 去重 + 追加，成功返回 True。"""
        if detail.get("author") and detail["author"] != POET:
            return False
        if len(detail["body"]) < 16:
            return False
        rec = make_record(detail)
        if rec["body_hash"] in libai_hashes:
            return False
        libai_hashes.add(rec["body_hash"])
        libai_titles_norm.add(norm_title(rec["title"]))
        new_records.append(rec)
        return True

    # ---- 第一步：定向补齐必须命中的诗 ----
    for report_title, variants in MUST_TITLES:
        variant_norms = [norm_title(v) for v in variants]
        if any(v in libai_titles_norm for v in variant_norms):
            print(f"  [must] 已有：{report_title}")
            continue
        hit = next((index_norm[v] for v in variant_norms if v in index_norm), None)
        if hit is None and report_title == "永王东巡歌·其一":
            # 站内只有《永王东巡歌十一首》合刊页；每首恰为两行，切出前两行即其一
            combo = index_norm.get(norm_title("永王东巡歌十一首"))
            if combo:
                detail = fetch_detail(combo[1])
                if detail:
                    lines = [ln for ln in detail["body"].split("\n") if ln.strip()]
                    if len(lines) >= 2:
                        detail["title"] = "永王东巡歌·其一"
                        detail["body"] = "\n".join(lines[:2])
                        if add_detail(detail):
                            print(f"  [must] 抓到（合刊切其一）：{report_title}")
                            continue
            missing.append(report_title)
            print(f"  [must] MISS：{report_title}")
            continue
        if hit is None:
            missing.append(report_title)
            print(f"  [must] MISS（索引未找到）：{report_title}")
            continue
        page_title, href = hit
        detail = fetch_detail(href)
        if detail and add_detail(detail):
            print(f"  [must] 抓到：{report_title}（页面题为《{detail['title']}》）")
        elif detail is None:
            missing.append(report_title)
            print(f"  [must] MISS（网络失败）：{report_title}")
        else:
            # 详情页存在但被去重/校验拦下——视为已覆盖
            print(f"  [must] 已覆盖（去重）：{report_title}")

    # ---- 第二步：按列表顺序补足到 TARGET_TOTAL ----
    for title, href in index.items():
        if len(libai) + len(new_records) >= TARGET_TOTAL:
            break
        if title.endswith("首"):
            continue  # 合刊组诗页，避免与单首重复
        if "节选" in title:
            continue  # 节选页与全篇内容重复
        if norm_title(title) in libai_titles_norm:
            continue
        detail = fetch_detail(href)
        if detail and add_detail(detail):
            print(f"  [fill] {detail['title']}  (累计 {len(libai) + len(new_records)})")

    total_libai = len(libai) + len(new_records)
    if new_records:
        shutil.copy2(OUT, BACKUP)
        print(f"[backup] {OUT.name} -> {BACKUP.name}")
        all_records.extend(new_records)
        write_json_atomic(OUT, all_records)
        print(f"[write] 追加 {len(new_records)} 条 -> {OUT}")

    print(f"\n[done] 李白总数 {total_libai}，新增 {len(new_records)}，"
          f"仍缺 {len(missing)}：{missing if missing else '无'}")
    summary = {
        "total_libai": total_libai,
        "added": len(new_records),
        "missing_titles": missing,
        "backup_path": str(BACKUP) if new_records else "",
    }
    print("SUMMARY_JSON=" + json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
