# -*- coding: utf-8 -*-
"""把助手亲笔撰写的导读卡批次插入知识库（model=zcode-assistant，与 API 生成分流）。

输入：data/assistant_guides/batch_*.json（由助手逐首撰写，可人工审阅的源文件）
行为：
  - 按（诗人, 诗题）精确匹配 poem_id（不匹配则跳过并警告，绝不模糊顶替）；
  - 同诗已有 poem_guide 时整体替换（保持一诗一卡）；
  - 审计字段与 API 路径完全同构：method='llm'（schema 约束）、
    model='zcode-assistant-glm5.3'、review_status='llm_candidate'、
    prompt_hash=批次文件哈希、input_hash=正文+事实哈希；
  - 注册 analysis_runs（kind=poem_guide_assistant），刷新 poem_fts，validate。
用法：python tools/insert_assistant_guides.py [--batch data/assistant_guides/batch_001.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "apps" / "agent-ui" / "agent"
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(ROOT / "tools"))

from poetry_agent.knowledge_builder import (  # noqa: E402
    KnowledgeBuildError,
    _analysis_id,
    stable_hash,
    utc_now,
)
from poetry_agent.knowledge import init_schema  # noqa: E402
from poetry_agent.knowledge_builder import validate_database  # noqa: E402
from build_poetry_knowledge_base import load_fact_texts  # noqa: E402
from refresh_poetry_knowledge_snapshot import (  # noqa: E402
    SnapshotPublishError,
    publish_snapshot,
)

import sqlite3  # noqa: E402

MODEL_STAMP = "zcode-assistant-glm5.3"
DEFAULT_DB = ROOT / "output" / "assets" / "knowledge" / "poetry_knowledge.sqlite3"


def _json_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch", type=Path, default=ROOT / "data" / "assistant_guides" / "batch_001.json")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--targets",
        type=Path,
        help="可选 poem_id 映射文件；用于同诗人同题名的重复记录，顺序必须与 batch items 一致",
    )
    args = ap.parse_args()

    data = json.loads(args.batch.read_text(encoding="utf-8"))
    target_items = None
    targets_hash = None
    if args.targets:
        target_bytes = args.targets.read_bytes()
        targets_hash = hashlib.sha256(target_bytes).hexdigest()
        target_data = json.loads(target_bytes)
        if not isinstance(target_data, dict):
            print("[error] targets 顶层必须为对象", file=sys.stderr)
            return 2
        target_items = target_data.get("targets")
        if target_data.get("batch") != data.get("batch"):
            print("[error] targets.batch 与 batch 文件不一致", file=sys.stderr)
            return 2
        if not isinstance(target_items, list) or len(target_items) != len(data.get("items", [])):
            print("[error] targets 数量必须与 batch items 完全一致", file=sys.stderr)
            return 2
        required_target_keys = {"poem_id", "poet", "title", "body_hash", "evidence_hash"}
        if any(
            not isinstance(target, dict) or set(target) != required_target_keys
            for target in target_items
        ):
            print("[error] targets 项字段异常", file=sys.stderr)
            return 2
        target_ids = [target["poem_id"] for target in target_items]
        if any(not isinstance(poem_id, str) or not poem_id for poem_id in target_ids):
            print("[error] targets poem_id 必须全部为非空字符串", file=sys.stderr)
            return 2
        if len(set(target_ids)) != len(target_ids):
            print("[error] targets poem_id 不得重复", file=sys.stderr)
            return 2

    batch_hash = hashlib.sha256(args.batch.read_bytes()).hexdigest()
    run_parts = (MODEL_STAMP, batch_hash, targets_hash) if targets_hash else (
        MODEL_STAMP,
        batch_hash,
    )
    run_id = "guide-assistant-" + stable_hash(*run_parts, length=24)
    facts = load_fact_texts()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    inserted, skipped = 0, []
    try:
        init_schema(conn)
        conn.execute(
            "INSERT OR IGNORE INTO analysis_runs(run_id,kind,method,model,prompt_version,prompt_hash,input_hash,status,started_at,completed_at,config_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id, "poem_guide_assistant", "llm", MODEL_STAMP,
                data.get("batch", "batch"), batch_hash, "per-poem", "completed",
                utc_now(), utc_now(),
                json.dumps(
                    {
                        "author": data.get("author"),
                        "policy": data.get("policy"),
                        "targets_sha256": targets_hash,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        for item_index, item in enumerate(data["items"]):
            poet, title = item["poet"], item["title"]
            evidence_json = None
            if target_items is None:
                row = conn.execute(
                    "SELECT poem_id,body FROM poems WHERE poet=? AND title=?", (poet, title)
                ).fetchone()
            else:
                target = target_items[item_index]
                poem_id = target["poem_id"]
                if (target["poet"], target["title"]) != (poet, title):
                    raise ValueError(f"targets 项与 batch item 身份不匹配: {poem_id}")
                row = conn.execute(
                    "SELECT poem_id,poet,title,body FROM poems WHERE poem_id=?", (poem_id,)
                ).fetchone()
                if row is None:
                    raise ValueError(f"targets 中 poem_id 不在库: {poem_id}")
                if (row["poet"], row["title"]) != (poet, title):
                    raise ValueError(
                        f"targets 身份不匹配: {poem_id} 应为 {poet}《{title}》，"
                        f"实为 {row['poet']}《{row['title']}》"
                    )
                actual_body_hash = hashlib.sha256(
                    (row["body"] or "").encode("utf-8")
                ).hexdigest()
                if target["body_hash"] != actual_body_hash:
                    raise ValueError(f"targets 正文哈希不匹配: {poem_id}")
                existing = conn.execute(
                    "SELECT model,evidence_json,payload_json FROM analyses "
                    "WHERE poem_id=? AND kind='poem_guide'",
                    (poem_id,),
                ).fetchall()
                if len(existing) != 1:
                    raise ValueError(
                        f"targets 中 {poem_id} 当前 poem_guide 数量为 {len(existing)}，必须恰好为 1"
                    )
                current = existing[0]
                current_batch = json.loads(current["payload_json"] or "{}").get("batch")
                if current["model"] == MODEL_STAMP and current_batch == data.get("batch"):
                    pass  # 允许同一目标批次在超时后安全重跑。
                elif current["model"] != "gpt-5.4-mini":
                    raise ValueError(
                        f"targets 中 {poem_id} 当前模型为 {current['model']!r}，拒绝覆盖"
                    )
                evidence_json = current["evidence_json"] or "[]"
                if target["evidence_hash"] != _json_hash(json.loads(evidence_json)):
                    raise ValueError(f"targets evidence 哈希不匹配: {poem_id}")
            if row is None:
                skipped.append(f"{poet}《{title}》不在库")
                continue
            poem_id, body = row["poem_id"], row["body"] or ""
            if evidence_json is None:
                fact_text = facts.get((poet, title), "")
                evidence_json = json.dumps(
                    [{"type": "verified_fact", "text": fact_text}] if fact_text else [],
                    ensure_ascii=False,
                )
            else:
                evidence_items = json.loads(evidence_json)
                fact_text = "\n".join(
                    evidence_item.get("text")
                    or (evidence_item.get("verified_fact") or {}).get("text")
                    or ""
                    for evidence_item in evidence_items
                ).strip()
            input_hash = stable_hash(
                json.dumps({"poemId": poem_id, "body": body, "facts": fact_text}, ensure_ascii=False, sort_keys=True)
            )
            conn.execute("DELETE FROM analyses WHERE poem_id=? AND kind='poem_guide'", (poem_id,))
            conn.execute(
                "INSERT INTO analyses(analysis_id,poem_id,line_id,kind,summary,interpretation,method,confidence,model,prompt_hash,input_hash,review_status,evidence_json,payload_json,run_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    _analysis_id(poem_id, "poem", "guide", "llm", run_id),
                    poem_id, None, "poem_guide",
                    item["summary"], item["guide"], "llm", float(item.get("confidence", 0.85)),
                    MODEL_STAMP, batch_hash, input_hash, "llm_candidate",
                    evidence_json,
                    json.dumps(
                        {
                            "origin": item["origin"],
                            "batch": data.get("batch"),
                            "note": "由 ZCode 助手（GLM）逐首撰写，llm_candidate 待复核，非人工考据",
                        },
                        ensure_ascii=False,
                    ),
                    run_id,
                ),
            )
            inserted += 1
        conn.execute("DELETE FROM poem_fts")
        conn.execute(
            "INSERT INTO poem_fts(poem_id,title,poet,dynasty,body,analysis_text) "
            "SELECT p.poem_id,p.title,p.poet,p.dynasty,p.body,COALESCE((SELECT group_concat(COALESCE(a.summary,'') || ' ' || COALESCE(a.interpretation,''),' ') FROM analyses a WHERE a.poem_id=p.poem_id),'') FROM poems p"
        )
        conn.commit()
        validate_database(conn)
        manifest_path = args.db.with_suffix(".manifest.json")
        if manifest_path.is_file():
            publish_snapshot(args.db)
        print(f"[ok] 插入 {inserted} 张助手导读卡（run={run_id}）")
        if skipped:
            for s in skipped:
                print("  [skip]", s)
        return 0
    except (
        KnowledgeBuildError,
        SnapshotPublishError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
