# -*- coding: utf-8 -*-
"""意象 × 地域矩阵（R2）：量化「意象的地域归属」。

方法（全量语料确定性统计，无模型、无随机）：
  1. 逐诗扫描古地名别名词典（>=2 字），按出现次数给每首诗定一个「主写区域」
     （次数并列时取更早出现者）——这是「被写入」口径，含亲历与遥想，不作区分；
  2. 逐诗判定意象词典命中（image_dict，课程人工词典）；
  3. 指标 lift = P(区域|含意象w) / P(区域|提及任意地名)，
     即「含该意象的诗落在该区域」的倍率：>1 过表征，<1 低表征；
  4. 只收录 n_w（含 w 的诗数）>= MIN_W 的意象；每区域取 lift 最高且
     n_wr >= MIN_CELL 的前 TOP_K 个词；每个格点附最多 SAMPLE_N 条原句证据。

区域划分为文化地理分区（今省级行政区归并，映射在 REGION_BY_PROVINCE，
页面上须整体展示，可复核）。区域仅用于聚合展示，不主张历史政区还原。

产出：output/assets/competition/imagery_region_matrix.json
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

POEMS_PATH = ROOT / "data" / "poems.json"
OUT_JSON = ROOT / "output" / "assets" / "competition" / "imagery_region_matrix.json"

MIN_ALIAS_LEN = 2
MIN_W = 50        # 意象至少出现在多少首「提及地名」的诗里才入矩阵
MIN_CELL = 5      # 格点至少 n_wr
TOP_K = 10        # 每区域取前 K 个过表征意象
SAMPLE_N = 3      # 每格点原句证据条数

REGIONS = [
    ("liangjing", "两京·中原", ["陕西", "河南"]),
    ("yanzhao", "燕赵·朔方", ["北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江"]),
    ("qilu", "齐鲁", ["山东"]),
    ("biansai", "西北边塞", ["甘肃", "宁夏", "青海", "新疆"]),
    ("bashu", "巴蜀", ["四川", "重庆"]),
    ("jiangnan", "江南", ["江苏", "浙江", "上海", "安徽"]),
    ("jingchu", "荆楚·湖湘", ["湖北", "湖南", "江西"]),
    ("lingnan", "岭南·闽海", ["广东", "广西", "福建", "海南", "台湾", "香港", "澳门"]),
    ("xinan", "西南·黔滇", ["贵州", "云南", "西藏"]),
]
REGION_BY_PROVINCE: dict[str, tuple[str, str]] = {}
for rid, rname, provs in REGIONS:
    for p in provs:
        REGION_BY_PROVINCE[p] = (rid, rname)

SENT_SPLIT = re.compile(r"(?<=[。！？；])|\n")


def build_alias_index() -> dict[str, dict]:
    index = {}
    for alias, modern, province, lon, lat, _note in PLACE_DICT:
        if len(alias) < MIN_ALIAS_LEN:
            continue
        index[alias] = {"province": province}
    return index


def region_of_poem(body: str, alias_index: dict[str, dict]) -> tuple[str, str] | None:
    """主写区域：别名出现次数最多的区域；并列取更早出现。"""
    counts: Counter = Counter()
    first_pos: dict[str, int] = {}
    for alias, info in alias_index.items():
        pos = body.find(alias)
        if pos < 0:
            continue
        rg = REGION_BY_PROVINCE.get(info["province"])
        if not rg:
            continue
        counts[rg[0]] += body.count(alias)
        if rg[0] not in first_pos or pos < first_pos[rg[0]]:
            first_pos[rg[0]] = pos
    if not counts:
        return None
    best = sorted(counts.items(), key=lambda kv: (-kv[1], first_pos[kv[0]]))[0][0]
    rid_to_name = {rid: name for rid, name, _p in REGIONS}
    return best, rid_to_name[best]


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # 词典完整性：PLACE_DICT 中出现过的省份必须全部映射到区域
    unmapped = sorted({p for _a, _m, p, _lo, _la, _n in PLACE_DICT if p not in REGION_BY_PROVINCE})
    assert not unmapped, f"区域映射缺少省份：{unmapped}"

    poems = json.loads(POEMS_PATH.read_text(encoding="utf-8"))
    alias_index = build_alias_index()
    image_words = sorted({w for w, _c, _e in IMAGE_DICT}, key=len, reverse=True)
    image_cat = {w: cat for w, cat, _e in IMAGE_DICT}
    image_emo = {w: emo for w, _c, emo in IMAGE_DICT}

    region_poem_n: Counter = Counter()                     # 每区域诗数（分母基准）
    word_region_n: dict[str, Counter] = defaultdict(Counter)  # w × 区域 计数
    word_n: Counter = Counter()                            # w 在「提及地名」诗中的总数
    samples: dict[tuple[str, str], list[dict]] = defaultdict(list)  # (word, rid) -> 原句

    rid_to_name = {rid: name for rid, name, _p in REGIONS}
    region_words_poets: dict[str, set] = defaultdict(set)

    for poem in poems:
        body = poem.get("body") or ""
        if not isinstance(body, str) or len(body) < 8:
            continue
        rg = region_of_poem(body, alias_index)
        if not rg:
            continue
        rid = rg[0]
        region_poem_n[rid] += 1
        poet = poem.get("poet") or poem.get("author") or "佚名"
        region_words_poets[rid].add(poet)
        for w in image_words:
            if w not in body:
                continue
            word_n[w] += 1
            word_region_n[w][rid] += 1
            if len(samples[(w, rid)]) < SAMPLE_N:
                for seg in SENT_SPLIT.split(body):
                    seg = seg.strip()
                    if w in seg and 4 <= len(seg) <= 30:
                        samples[(w, rid)].append(
                            {"poet": poet, "title": poem.get("title") or "", "line": seg[:30]}
                        )
                        break

    total_located = sum(region_poem_n.values())
    assert total_located > 1000, f"定位诗数过少：{total_located}"

    def lift(w: str, rid: str) -> float | None:
        base = region_poem_n[rid] / total_located
        if not base or word_n[w] == 0:
            return None
        return (word_region_n[w][rid] / word_n[w]) / base

    regions_out = []
    matrix_words: set = set()
    for rid, rname, _provs in REGIONS:
        rows = []
        for w in word_n:
            if word_n[w] < MIN_W:
                continue
            n_wr = word_region_n[w].get(rid, 0)
            if n_wr < MIN_CELL:
                continue
            lv = lift(w, rid)
            if lv is None or lv <= 1.0:  # 只看过表征
                continue
            rows.append({"word": w, "lift": round(lv, 3), "n_wr": n_wr, "n_w": word_n[w]})
        rows.sort(key=lambda r: (-r["lift"], -r["n_wr"], r["word"]))
        rows = rows[:TOP_K]
        for r in rows:
            r["samples"] = samples.get((r["word"], rid), [])
            matrix_words.add(r["word"])
        regions_out.append(
            {
                "id": rid,
                "name": rname,
                "n_poems": region_poem_n[rid],
                "n_poets": len(region_words_poets[rid]),
                "base_rate": round(region_poem_n[rid] / total_located, 4),
                "top_words": rows,
            }
        )

    words_sorted = sorted(matrix_words)
    words_index = {
        w: {
            "cat": image_cat.get(w, ""),
            "emotion": image_emo.get(w, 0.0),
            "n_w": word_n[w],
            "regions": {
                rid: {
                    "lift": round(lift(w, rid), 3) if lift(w, rid) is not None else None,
                    "n_wr": word_region_n[w].get(rid, 0),
                }
                for rid, _n, _p in REGIONS
                if word_region_n[w].get(rid, 0) >= MIN_CELL
            },
        }
        for w in words_sorted
    }

    meta = {
        "n_poems_corpus": len(poems),
        "n_located_poems": total_located,
        "regions": [{"id": rid, "name": name, "provinces": provs} for rid, name, provs in REGIONS],
        "thresholds": {"min_word_poems": MIN_W, "min_cell": MIN_CELL, "top_k": TOP_K},
        "policy": (
            "口径：全量语料古地名扫描定主写区域（含亲历与遥想，不作区分）；"
            "lift＝P(区域|含意象)/P(区域|提及地名)；只展示 n_w≥MIN_W 且 n_wr≥MIN_CELL 的过表征格点；"
            "意象为课程人工词典规则命中，非模型输出；区域为今省级行政区归并的文化地理分区，"
            "仅用于聚合展示，不主张历史政区还原。"
        ),
        "generated_by": "tools/build_imagery_region_matrix.py",
    }

    data = {"meta": meta, "regions": regions_out, "words": words_index}
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    print("OK  ->", OUT_JSON, f"({OUT_JSON.stat().st_size} bytes)")
    print(f"定位诗 {total_located} | 入矩阵意象 {len(words_sorted)} 个 | 区域 {len(regions_out)} 个")
    for r in regions_out:
        tops = "、".join(f"{t['word']}({t['lift']}×)" for t in r["top_words"][:5]) or "-"
        print(f"  {r['name']:<6} {r['n_poems']:>5} 首  top: {tops}")


if __name__ == "__main__":
    main()
