"""Build the local poetry/line/imagery/emotion knowledge base."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "apps" / "agent-ui" / "agent"
sys.path.insert(0, str(AGENT_DIR))

from poetry_agent.knowledge_builder import (  # noqa: E402
    DEFAULT_OUTPUT,
    DEFAULT_SOURCE,
    KnowledgeBuildError,
    build_knowledge_base,
    enrich_guides_with_llm,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--poet")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--llm", action="store_true", help="使用AGENT_LLM_*批量增强（逐句释义/意象/情感）")
    parser.add_argument(
        "--guide",
        action="store_true",
        help="为每首诗生成讲解/来源/故事导读卡（method=llm，需 AGENT_LLM_*）",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="跳过规则重建，直接续跑 LLM 增强（仅与 --guide/--llm 组合；依赖库已构建）",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=64,
        help="LLM并发上限（1..64）",
    )
    return parser.parse_args(argv)


def load_fact_texts() -> dict[tuple[str, str], str]:
    """(诗人, 诗题) -> 已核验事实描述（三层口径逐层标注；无事实的诗不进表）。"""
    tiers = [
        ("data/reviewed/verified_all_poet_fact_packages.jsonl", "人工核验"),
        ("data/promoted/rule_promoted_facts.jsonl", "规则晋级"),
        ("data/promoted/ai_assisted_facts.jsonl", "AI辅助放宽"),
    ]
    facts: dict[tuple[str, str], str] = {}
    for rel, tier in tiers:
        path = ROOT / rel
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            key = (rec["poem_key"]["poet"], rec["poem_key"]["title"])
            if key in facts:
                continue
            chron = rec.get("chronology") or {}
            year = chron.get("year_start")
            place = chron.get("modern_place") or chron.get("historical_place") or ""
            grade = chron.get("grade") or ("A/B" if tier == "人工核验" else "")
            parts = []
            if year:
                parts.append(f"约{year}年")
            if place:
                parts.append(f"作于{place}")
            note = "、".join(parts)
            if not note:
                continue
            facts[key] = f"{note}（{tier}{grade}）"
    return facts


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.skip_build and not (args.guide or args.llm):
        print("[error] --skip-build 仅与 --guide/--llm 组合使用", file=sys.stderr)
        return 2
    if args.skip_build:
        result = {"skipped": True, "output": str(Path(args.output).expanduser().resolve())}
    else:
        try:
            result = build_knowledge_base(
                source=args.source,
                output=args.output,
                limit=args.limit,
                poet=args.poet.strip() if args.poet else None,
                rebuild=args.rebuild,
                use_llm=args.llm,
                concurrency=args.concurrency,
            )
        except KnowledgeBuildError as exc:
            print(f"[error] {exc}", file=sys.stderr)
            return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.guide:
        guide = enrich_guides_with_llm(
            Path(args.output).expanduser().resolve(),
            concurrency=args.concurrency,
            facts=load_fact_texts(),
        )
        print(json.dumps(guide, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
