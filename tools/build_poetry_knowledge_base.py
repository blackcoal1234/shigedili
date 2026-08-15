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
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--poet")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--llm", action="store_true", help="使用AGENT_LLM_*批量增强")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=64,
        help="LLM并发上限（1..64）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
