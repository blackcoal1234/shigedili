# -*- coding: utf-8 -*-
"""poem_page 质量门：数据资产完整性、诚实口径与确定性重建。

校验 output/assets/poem_page/poem_page_data.js 与 output/44_诗页.html：
  1. 数据可解析，规模与知识库、三层事实、审核背景逐项一致；
  2. 每首诗必填字段（id / 题名 / 诗人 / 朝代 / 正文）非空且 id 唯一；
  3. 诚实门禁：富背景只挂人工核验层且全部来自 approved 记录、来源等级 A/B；
     作年作地 tier 只允许 verified / rule / ai 三层；rule / ai 只经 body_hash
     精确匹配（hash_ok=false 不得出现在页面数据中）；
  4. 导读卡：助手 / 模型拆分与知识库 model 字段一致，二者均为非人工考据口径；
  5. 页面标记：本地数据资产引用、hash 深链、非人工考据徽章、无远程脚本；
  6. 确定性：重跑构建器后 md5 逐字节一致。
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

DATA_JS = ROOT / "output" / "assets" / "poem_page" / "poem_page_data.js"
PAGE_HTML = ROOT / "output" / "44_诗页.html"
KB_SQLITE = ROOT / "output" / "assets" / "knowledge" / "poetry_knowledge.sqlite3"
VERIFIED_JSONL = ROOT / "data" / "reviewed" / "verified_poem_backgrounds.jsonl"
RULE_JSONL = ROOT / "data" / "promoted" / "rule_promoted_facts.jsonl"
AI_JSONL = ROOT / "data" / "promoted" / "ai_assisted_facts.jsonl"
ASSISTANT_RICH_DIR = ROOT / "data" / "assistant_rich_backgrounds"
LLM_RICH_DIR = ROOT / "data" / "llm_rich_backgrounds"


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def load_asset() -> dict:
    text = DATA_JS.read_text(encoding="utf-8")
    m = re.fullmatch(r"window\.POEM_PAGE_DATA=(.*);\n?", text, flags=re.S)
    require(m is not None, "poem_page_data.js 不是合法的 window.POEM_PAGE_DATA 资产")
    return json.loads(m.group(1))


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def kb_facts() -> tuple[dict, dict]:
    db = sqlite3.connect(f"file:{KB_SQLITE}?mode=ro", uri=True, timeout=60)
    poems = db.execute("SELECT count(*) FROM poems").fetchone()[0]
    guides = {}
    for pid, model in db.execute(
        "SELECT poem_id, model FROM analyses WHERE kind='poem_guide'"
    ):
        guides[pid] = str(model or "").startswith("zcode-assistant")
    db.close()
    return poems, guides


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    for p in (DATA_JS, PAGE_HTML, KB_SQLITE):
        if not p.exists():
            raise SystemExit(f"[failed] 缺少 {p}，先运行 tools/build_poem_page_data.py 与 数据可视化脚本/viz_44_poem_page.py")

    data = load_asset()
    meta = data["meta"]
    poems = data["poems"]
    kb_poem_count, kb_guides = kb_facts()

    # 1. 规模与知识库一致
    require(meta["poems"] == kb_poem_count, f"诗数不一致：资产 {meta['poems']} vs 知识库 {kb_poem_count}")
    require(meta["guides"] == len(kb_guides), f"导读卡数不一致：资产 {meta['guides']} vs 知识库 {len(kb_guides)}")
    hw = sum(1 for g in kb_guides.values() if g)
    require(meta["guides_assistant"] == hw, f"助手卡数不一致：{meta['guides_assistant']} vs {hw}")
    require(meta["guides_model"] == len(kb_guides) - hw, "模型卡数不一致")

    # 2. 必填字段与唯一性
    ids = set()
    for p in poems:
        for field, name in (("id", "id"), ("t", "题名"), ("p", "诗人"), ("d", "朝代"), ("b", "正文")):
            require(str(p.get(field) or "").strip(), f"诗作 {p.get('id')} 缺少{name}")
        require(p["id"] not in ids, f"诗 id 重复：{p['id']}")
        ids.add(p["id"])
        if p.get("f"):
            require(p["f"].get("tier") in {"verified", "rule", "ai"}, f"非法事实层级：{p['id']} {p['f'].get('tier')}")
        if p.get("em"):
            require(len(p["em"]) <= 4, f"情感标签超过 4 条：{p['id']}")
            for e in p["em"]:
                require(0 <= float(e.get("sh", 0)) <= 1, f"情感占比越界：{p['id']}")
        if p.get("im"):
            for i in p["im"]:
                require(int(i.get("c", 0)) >= 1, f"意象计数异常：{p['id']}")

    # 3. 富背景诚实门禁：只挂 verified，数量与 approved 记录按 body_hash 可匹配数一致
    approved_hashes = set()
    for row in read_jsonl(VERIFIED_JSONL):
        if row.get("review_status") == "approved":
            key = row.get("poem_key") or {}
            if key.get("body_hash"):
                approved_hashes.add(key["body_hash"])
    bg_poems = [p for p in poems if p.get("bg")]
    require(all(p["f"] and p["f"]["tier"] == "verified" for p in bg_poems), "存在挂在非人工核验层的富背景")
    require(len(bg_poems) == meta["facts_verified"], "verified 计数与富背景条数不一致")
    require(len(bg_poems) <= len(approved_hashes), "富背景数超过 approved 记录数")
    for p in bg_poems:
        for s in p["bg"].get("src", []):
            require(s.get("grade") in {"A", "B"}, f"富背景来源等级非 A/B：{p['id']} {s.get('name')}")
        story = p["bg"].get("story") or ""
        notes = p["bg"].get("notes") or []
        ap = p["bg"].get("ap") or []
        src = p["bg"].get("src") or []
        require(bool(story or notes or ap or src), f"富背景完全为空：{p['id']}")

    # rule / ai 只能经 hash_ok 匹配：核对各层计数不超过源文件 hash_ok 且在语料内的数量
    kb_hashes = set()
    db = sqlite3.connect(f"file:{KB_SQLITE}?mode=ro", uri=True, timeout=60)
    for (h,) in db.execute("SELECT body_hash FROM poems"):
        kb_hashes.add(h)
    db.close()
    for path, tier in ((RULE_JSONL, "rule"), (AI_JSONL, "ai")):
        eligible = sum(
            1
            for row in read_jsonl(path)
            if (row.get("poem_key") or {}).get("hash_ok")
            and (row.get("poem_key") or {}).get("body_hash") in kb_hashes
        )
        require(meta[f"facts_{tier}"] <= eligible, f"{tier} 层计数 {meta[f'facts_{tier}']} 超过可匹配上限 {eligible}")

    # 3.5 助手续写层：内容门槛（story 长度、逐句必有译文、注释与赏析要点足量）与诚实口径
    html = PAGE_HTML.read_text(encoding="utf-8")
    bodies = {p["id"]: p["b"] for p in poems}
    ag_poems = [p for p in poems if p.get("ag")]
    ag_by_id = {p["id"]: p["ag"] for p in ag_poems}
    require(meta.get("assistant_rich") == len(ag_poems), "assistant_rich 计数与 ag 条数不一致")
    for pid, ag in ag_by_id.items():
        require(
            ag.get("at") in {"verified", "rule", "ai", "none"},
            f"诗页 ag anchor 层级非法：{pid} {ag.get('at')}",
        )
        require(
            ag.get("rm")
            in {
                "assistant_authored",
                "reviewed_references",
                "poem_only",
                "legacy_unconstrained",
            },
            f"诗页 ag 参考模式非法：{pid} {ag.get('rm')}",
        )
        sources = ag.get("src") or []
        require(isinstance(sources, list), f"诗页 ag 来源不是列表：{pid}")
        for source in sources:
            require(
                isinstance(source, dict)
                and str(source.get("id") or "").startswith("R")
                and str(source.get("n") or "").strip()
                and str(source.get("u") or "").startswith("https://"),
                f"诗页 ag 来源字段非法：{pid}",
            )
        if ag.get("rm") == "reviewed_references":
            require(sources, f"诗页 ag 标记经审核参考但没有来源：{pid}")
        else:
            require(not sources, f"诗页 ag 非审核参考模式却携带来源：{pid}")
    batch_files = [(p, "hand") for p in (sorted(ASSISTANT_RICH_DIR.glob("batch_*.json")) if ASSISTANT_RICH_DIR.exists() else [])]
    batch_files += [(p, "llm") for p in (sorted(LLM_RICH_DIR.glob("batch_*.json")) if LLM_RICH_DIR.exists() else [])]
    source_hand_ids: set[str] = set()
    source_llm_ids: set[str] = set()
    for bf, layer in batch_files:
        payload = json.loads(bf.read_text(encoding="utf-8"))
        for item in payload.get("items") or []:
            pid = str(item.get("poem_id") or "")
            title = str(item.get("title") or "")
            story = str(item.get("story") or "")
            notes = item.get("line_notes") or []
            annotations = [a for n in notes for a in (n.get("annotations") or [])]
            ap = [x for x in (item.get("appreciation_points") or []) if x]
            require(pid in ids, f"{bf.name} {title} poem_id 不在页面数据：{pid}")
            (source_hand_ids if layer == "hand" else source_llm_ids).add(pid)
            if layer == "llm":
                require(pid not in source_hand_ids, f"{bf.name} {title} 与手写层重复（手写层应优先，不应生成）")
            for n in notes:
                original = str(n.get("original") or "").strip()
                require(
                    original and original in bodies.get(pid, ""),
                    f"{bf.name} {title} 逐句原句与正文不一致：{original[:18]}…",
                )
            require(len(story) >= 100, f"{bf.name} {title} story 长度不足 100 字：{len(story)}")
            require(len(story) <= 260, f"{bf.name} {title} story 超长：{len(story)}")
            require(len(notes) >= 2, f"{bf.name} {title} 逐句条目不足 2 组")
            for n in notes:
                require(str(n.get("translation") or "").strip(), f"{bf.name} {title} 逐句缺译文：{n.get('original')}")
            require(len(annotations) >= 2, f"{bf.name} {title} 注释不足 2 条")
            require(len(ap) >= 1, f"{bf.name} {title} 赏析要点不足 1 条")
            anchor = item.get("facts_anchor") or {}
            require(
                anchor.get("tier") in {"verified", "rule", "ai", "none"},
                f"{bf.name} {title} anchor 层级非法：{anchor.get('tier')}",
            )
    require(meta.get("rich_hand") == len(source_hand_ids), "rich_hand 计数与手写批次不一致")
    require(meta.get("rich_llm") == len(source_llm_ids), "rich_llm 计数与 LLM 批次不一致")
    require(len(ag_poems) == len(source_hand_ids | source_llm_ids), "ag 条数与批次并集不一致")
    # ag 必须带批次与待复核口径
    require("助手续写" in html and "待人工复核" in html, "44_诗页.html 缺少助手续写层的诚实标注")
    require(
        "经审核摘要约束" in html and "未使用核验作年作地" in html,
        "44_诗页.html 缺少动态证据边界说明",
    )

    # 4. 页面标记
    for marker, msg in (
        ('src="assets/poem_page/poem_page_data.js"', "页面未引用本地数据资产"),
        ("poem=", "页面缺少 hash 深链路由"),
        ("非人工考据", "页面缺少非人工考据徽章"),
        ("人工核验 A/B", "页面缺少层级徽章文案"),
        ("规则晋级", "页面缺少推定层级文案"),
        ("localStorage", "页面诗签应只存本机"),
    ):
        require(marker in html, f"44_诗页.html {msg}")
    remote = re.findall(r"<script[^>]+src=[\"']https?://", html)
    require(not remote, f"44_诗页.html 引用远程脚本：{remote[:1]}")
    require("NaN" not in html and "Infinity" not in html, "44_诗页.html 含非法数值")

    # 5. 确定性重建
    before = hashlib.md5(DATA_JS.read_bytes()).hexdigest()
    subprocess.run(
        [sys.executable, "tools/build_poem_page_data.py"],
        cwd=ROOT, check=True, capture_output=True,
    )
    after = hashlib.md5(DATA_JS.read_bytes()).hexdigest()
    require(before == after, "poem_page_data.js 重建不一致（非确定性）")

    print(
        f"[ok] 诗页数据检查通过：{meta['poems']} 首 / 导读卡 {meta['guides']}"
        f"（助手 {meta['guides_assistant']} / 模型 {meta['guides_model']}）；"
        f"事实 人工核验 {meta['facts_verified']} / 规则晋级 {meta['facts_rule']} / AI 辅助 {meta['facts_ai']}"
    )


if __name__ == "__main__":
    main()
