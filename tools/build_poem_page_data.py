# -*- coding: utf-8 -*-
"""统一赏析诗页数据层：知识库 + 三层事实 + 审核背景 → poem_page_data.js。

为「一首诗 = 一个可深链的赏析页」（output/44_诗页.html）聚合全部已有数据：

  poems（知识库 SQLite）
    + analyses.poem_guide（导读卡：summary / interpretation / origin）
    + emotion_mentions（诗级多标签情感）
    + imagery_mentions（意象命中：标签聚合计数 + 高亮原文串）
  三层作年作地事实（按 body_hash 精确匹配，hash_ok=false 一律不挂）
    verified：data/reviewed/verified_poem_backgrounds.jsonl（仅 approved，
              同时携带富背景：背景故事 / 逐句译注 / 赏析要点 / 证据来源）
    rule    ：data/promoted/rule_promoted_facts.jsonl（promoted_by_rule）
    ai      ：data/promoted/ai_assisted_facts.jsonl（promoted_ai_assisted）

诚实口径与项目门禁一致：
  - 导读卡一律标记「非人工考据」，助手撰写与模型生成分徽章；
  - 作年作地按三层层级标注，rule / ai 以「推定」样式区分，不冒充人工核验；
  - 富背景只读 approved 记录，候选与 hold 不进入页面；
  - 确定性输出：不含时间戳，重建逐字节一致（md5 可复核）。

前置：output/assets/knowledge/poetry_knowledge.sqlite3
      （缺失时先运行 tools/build_poetry_knowledge_base.py）。
产出：output/assets/poem_page/poem_page_data.js（经典 script，file:// 可用）。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

KB_SQLITE = ROOT / "output" / "assets" / "knowledge" / "poetry_knowledge.sqlite3"
VERIFIED_JSONL = ROOT / "data" / "reviewed" / "verified_poem_backgrounds.jsonl"
RULE_JSONL = ROOT / "data" / "promoted" / "rule_promoted_facts.jsonl"
AI_JSONL = ROOT / "data" / "promoted" / "ai_assisted_facts.jsonl"
ASSISTANT_RICH_DIR = ROOT / "data" / "assistant_rich_backgrounds"
LLM_RICH_DIR = ROOT / "data" / "llm_rich_backgrounds"
OUT_JS = ROOT / "output" / "assets" / "poem_page" / "poem_page_data.js"

TIER_LABELS = {
    "verified": "人工核验 A/B",
    "rule": "规则晋级·推定",
    "ai": "AI 辅助·推定",
}


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def load_approved_backgrounds() -> dict[str, dict]:
    """approved 富背景按 body_hash 索引；候选与 hold 不进入。"""
    out: dict[str, dict] = {}
    for row in read_jsonl(VERIFIED_JSONL):
        if row.get("review_status") != "approved":
            continue
        key = row.get("poem_key") if isinstance(row.get("poem_key"), dict) else {}
        digest = str(key.get("body_hash") or "")
        if not digest:
            continue
        composition = row.get("composition") if isinstance(row.get("composition"), dict) else {}
        date = composition.get("date") if isinstance(composition.get("date"), dict) else {}
        place = composition.get("place") if isinstance(composition.get("place"), dict) else {}
        sources = []
        for source in row.get("sources") or []:
            if not isinstance(source, dict):
                continue
            sources.append(
                {
                    "name": str(source.get("name") or ""),
                    "url": str(source.get("url") or ""),
                    "citation": str(source.get("citation") or ""),
                    "locator": str(source.get("locator") or ""),
                    "grade": str(source.get("grade") or ""),
                    "excerpt": str(source.get("excerpt") or "")[:160],
                }
            )
        line_notes = []
        for note in row.get("line_notes") or []:
            if not isinstance(note, dict):
                continue
            annotations = [str(a) for a in (note.get("annotations") or []) if a]
            line_notes.append(
                {
                    "original": str(note.get("original") or ""),
                    "translation": str(note.get("translation") or ""),
                    "annotations": annotations,
                }
            )
        appreciations = []
        for item in row.get("appreciation_points") or []:
            if isinstance(item, dict) and item.get("point"):
                appreciations.append(str(item["point"]))
            elif isinstance(item, str) and item.strip():
                appreciations.append(item.strip())
        out[digest] = {
            "tier": "verified",
            "ys": date.get("year_start"),
            "ye": date.get("year_end"),
            "prec": str(date.get("precision") or "year"),
            "hp": str(place.get("historical_place") or ""),
            "mp": str(place.get("modern_place") or ""),
            "prov": str(place.get("province") or ""),
            "lat": place.get("lat"),
            "lon": place.get("lon"),
            "story": str(row.get("story_summary") or row.get("background_summary") or ""),
            "controversy": str(row.get("controversy_note") or ""),
            "notes": line_notes,
            "ap": appreciations,
            "src": sources,
        }
    return out


def load_promoted_facts(path: Path, tier: str) -> dict[str, dict]:
    """规则晋级 / AI 辅助事实：hash_ok 且 body_hash 非空才可挂到具体诗作。"""
    out: dict[str, dict] = {}
    for row in read_jsonl(path):
        key = row.get("poem_key") if isinstance(row.get("poem_key"), dict) else {}
        digest = str(key.get("body_hash") or "")
        if not digest or not key.get("hash_ok"):
            continue
        chrono = row.get("chronology") if isinstance(row.get("chronology"), dict) else {}
        if chrono.get("year_start") is None and not chrono.get("modern_place"):
            continue
        out[digest] = {
            "tier": tier,
            "ys": chrono.get("year_start"),
            "ye": chrono.get("year_end"),
            "prec": str(chrono.get("year_precision") or "year"),
            "hp": str(chrono.get("historical_place") or ""),
            "mp": str(chrono.get("modern_place") or ""),
            "prov": str(chrono.get("province") or ""),
            "lat": chrono.get("lat"),
            "lon": chrono.get("lon"),
        }
    return out


def _load_rich_dir(rich_dir: Path, layer: str) -> dict[str, dict]:
    """加载译注赏析批次目录（手写层 / LLM 层共用解析）。

    手写层（assistant_rich_backgrounds）：助手逐首撰写；
    LLM 层（llm_rich_backgrounds）：OpenAI 兼容接口批量生成，原句经逐字校验。
    两层同一纪律：待人工复核、非人工考据、story 只锚定输入事实。
    """
    out: dict[str, dict] = {}
    ranks: dict[str, tuple[int, str, int, int]] = {}
    if not rich_dir.exists():
        return out
    for path_index, path in enumerate(sorted(rich_dir.glob("batch_*.json"))):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"[failed] {path.name} 不是合法 JSON：{exc}")
        for item_index, item in enumerate(payload.get("items") or []):
            if not isinstance(item, dict):
                continue
            pid = str(item.get("poem_id") or "")
            if not pid:
                continue
            if pid in out and layer == "hand":
                raise SystemExit(f"[failed] {rich_dir.name} 诗 id 重复：{pid}（{path.name}）")
            audit = item.get("audit") if isinstance(item.get("audit"), dict) else {}
            raw_reference_mode = str(audit.get("reference_mode") or "")
            prompt_version = str(audit.get("prompt_version") or "")
            if layer == "hand":
                reference_mode = "assistant_authored"
            elif prompt_version == "rich_guide_v2_evidence" and raw_reference_mode in {
                "reviewed_references",
                "poem_only",
            }:
                reference_mode = raw_reference_mode
            else:
                reference_mode = "legacy_unconstrained"
            if layer == "llm":
                constraint_rank = {
                    "reviewed_references": 3,
                    "poem_only": 2,
                    "legacy_unconstrained": 1,
                }[reference_mode]
                rank = (
                    constraint_rank,
                    str(audit.get("generated_at") or ""),
                    path_index,
                    item_index,
                )
                if pid in out and rank <= ranks[pid]:
                    continue
                ranks[pid] = rank
            notes = []
            for note in item.get("line_notes") or []:
                if not isinstance(note, dict):
                    continue
                notes.append(
                    {
                        "original": str(note.get("original") or ""),
                        "translation": str(note.get("translation") or ""),
                        "annotations": [str(a) for a in (note.get("annotations") or []) if a],
                    }
                )
            facts_anchor = (
                item.get("facts_anchor")
                if isinstance(item.get("facts_anchor"), dict)
                else {}
            )
            anchor_tier = str(facts_anchor.get("tier") or "none")
            if anchor_tier not in {"verified", "rule", "ai", "none"}:
                anchor_tier = "none"
            sources = []
            if reference_mode == "reviewed_references":
                for source in item.get("sources") or []:
                    if not isinstance(source, dict):
                        continue
                    name = str(source.get("name") or "").strip()
                    url = str(source.get("url") or "").strip()
                    reference_id = str(source.get("reference_id") or "").strip()
                    if name and reference_id and url.startswith("https://"):
                        sources.append({"id": reference_id, "n": name, "u": url})
            entry = {
                "story": str(item.get("story") or ""),
                "notes": notes,
                "ap": [str(x) for x in (item.get("appreciation_points") or []) if x],
                "batch": str(payload.get("batch") or path.stem),
                "hw": layer == "hand",
                "at": anchor_tier,
                "rm": reference_mode,
            }
            if sources:
                entry["src"] = sources
            out[pid] = entry
    return out


def load_assistant_rich() -> dict[str, dict]:
    """助手续写层 + LLM 批量层：手写优先，LLM 只补手写未覆盖的诗。"""
    out = _load_rich_dir(ASSISTANT_RICH_DIR, "hand")
    hand_count = len(out)
    for pid, entry in _load_rich_dir(LLM_RICH_DIR, "llm").items():
        if pid not in out:
            out[pid] = entry
    return out


def build() -> dict:
    if not KB_SQLITE.exists():
        raise SystemExit(
            f"[failed] 缺少知识库：{KB_SQLITE}\n"
            "  先运行 python tools/build_poetry_knowledge_base.py 生成知识库，再构建诗页数据。"
        )
    db = sqlite3.connect(f"file:{KB_SQLITE}?mode=ro", uri=True, timeout=60)
    db.row_factory = sqlite3.Row

    guides: dict[str, dict] = {}
    for row in db.execute(
        "SELECT poem_id, summary, interpretation, model, payload_json"
        "  FROM analyses WHERE kind='poem_guide'"
    ):
        payload = {}
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        model = str(row["model"] or "")
        guides[str(row["poem_id"])] = {
            "s": str(row["summary"] or ""),
            "i": str(row["interpretation"] or ""),
            "o": str(payload.get("origin") or ""),
            "hw": model.startswith("zcode-assistant"),
        }

    emotions: dict[str, list[dict]] = {}
    for row in db.execute(
        "SELECT poem_id, label, family, score, share FROM emotion_mentions"
        "  WHERE target_scope='poem' ORDER BY poem_id, score DESC, label"
    ):
        pid = str(row["poem_id"])
        bucket = emotions.setdefault(pid, [])
        if len(bucket) < 4:
            bucket.append(
                {
                    "l": str(row["label"] or ""),
                    "f": str(row["family"] or ""),
                    "s": round(float(row["score"] or 0), 2),
                    "sh": round(float(row["share"] or 0), 2),
                }
            )

    imagery: dict[str, dict] = {}
    for row in db.execute(
        "SELECT poem_id, label, category, matched_text FROM imagery_mentions"
        "  ORDER BY poem_id, label"
    ):
        pid = str(row["poem_id"])
        label = str(row["label"] or "")
        if not label:
            continue
        entry = imagery.setdefault(pid, {"labels": {}, "texts": []})
        info = entry["labels"].setdefault(label, {"l": label, "c": 0, "cat": str(row["category"] or "")})
        info["c"] += 1
        text = str(row["matched_text"] or "")
        if len(text) >= 2 and text not in entry["texts"] and len(entry["texts"]) < 8:
            entry["texts"].append(text)
    db.close()

    verified = load_approved_backgrounds()
    rule = load_promoted_facts(RULE_JSONL, "rule")
    ai = load_promoted_facts(AI_JSONL, "ai")
    assistant_rich = load_assistant_rich()

    poems_out: list[dict] = []
    tier_counts = {"verified": 0, "rule": 0, "ai": 0}
    rows = []
    db = sqlite3.connect(f"file:{KB_SQLITE}?mode=ro", uri=True, timeout=60)
    db.row_factory = sqlite3.Row
    for row in db.execute(
        "SELECT poem_id, title, poet, dynasty, school, genre, body, body_hash FROM poems"
    ):
        rows.append(dict(row))
    db.close()
    rows.sort(key=lambda r: (r["dynasty"] or "", r["poet"] or "", r["title"] or "", r["poem_id"]))

    dangling = sorted(set(assistant_rich) - {str(r["poem_id"]) for r in rows})
    if dangling:
        raise SystemExit(
            f"[failed] 助手续写层 poem_id 不在知识库：{dangling[:3]}（共 {len(dangling)} 个）"
        )

    for row in rows:
        digest = str(row["body_hash"] or "")
        fact: dict | None = None
        bg: dict | None = None
        if digest and digest in verified:
            bg = verified[digest]
            fact = {k: v for k, v in bg.items() if k in ("tier", "ys", "ye", "prec", "hp", "mp", "prov", "lat", "lon")}
            tier_counts["verified"] += 1
        elif digest and digest in rule:
            fact = dict(rule[digest])
            tier_counts["rule"] += 1
        elif digest and digest in ai:
            fact = dict(ai[digest])
            tier_counts["ai"] += 1

        pid = str(row["poem_id"])
        entry: dict = {
            "id": pid,
            "t": str(row["title"] or ""),
            "p": str(row["poet"] or ""),
            "d": str(row["dynasty"] or ""),
            "sc": str(row["school"] or ""),
            "b": str(row["body"] or ""),
        }
        if pid in emotions:
            entry["em"] = emotions[pid]
        im = imagery.get(pid)
        if im:
            entry["im"] = sorted(im["labels"].values(), key=lambda x: (-x["c"], x["l"]))[:12]
            if im["texts"]:
                entry["imt"] = im["texts"]
        if pid in guides:
            entry["gd"] = guides[pid]
        if fact:
            entry["f"] = fact
        if bg:
            entry["bg"] = bg
        if pid in assistant_rich:
            entry["ag"] = assistant_rich[pid]
        poems_out.append(entry)

    hand = sum(1 for g in guides.values() if g["hw"])
    poets = sorted({p["p"] for p in poems_out if p["p"]})
    rich_hand = sum(1 for entry in assistant_rich.values() if entry.get("hw"))
    return {
        "meta": {
            "poems": len(poems_out),
            "poets": len(poets),
            "guides": len(guides),
            "guides_assistant": hand,
            "guides_model": len(guides) - hand,
            "facts_verified": tier_counts["verified"],
            "facts_rule": tier_counts["rule"],
            "facts_ai": tier_counts["ai"],
            "assistant_rich": len(assistant_rich),
            "rich_hand": rich_hand,
            "rich_llm": len(assistant_rich) - rich_hand,
            "tier_labels": TIER_LABELS,
        },
        "poets": poets,
        "poems": poems_out,
    }


def main() -> None:
    data = build()
    OUT_JS.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    OUT_JS.write_text(
        f"window.POEM_PAGE_DATA={payload};\n",
        encoding="utf-8",
        newline="\n",
    )
    digest = hashlib.md5(OUT_JS.read_bytes()).hexdigest()
    meta = data["meta"]
    print(
        f"[ok] {OUT_JS.relative_to(ROOT)}  "
        f"{meta['poems']} 首 / {meta['poets']} 位诗人；"
        f"导读卡 {meta['guides']}（助手 {meta['guides_assistant']} / 模型 {meta['guides_model']}）；"
        f"事实：人工核验 {meta['facts_verified']} / 规则晋级 {meta['facts_rule']} / AI辅助 {meta['facts_ai']}；"
        f"译注赏析 {meta['assistant_rich']} 首（手写 {meta['rich_hand']} / LLM {meta['rich_llm']}）；"
        f"md5 {digest}"
    )


if __name__ == "__main__":
    main()
