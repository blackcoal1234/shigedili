"""Build the versioned SiliconFlow vector sidecar for the poetry knowledge base."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = PROJECT_ROOT / "apps" / "agent-ui" / "agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from poetry_agent.config import Settings  # noqa: E402
from poetry_agent.embedding_builder import (  # noqa: E402
    EmbeddingBuildError,
    build_poetry_embeddings,
)
from poetry_agent.embeddings import (  # noqa: E402
    EmbeddingProviderConfig,
    SiliconFlowEmbeddingClient,
)


def parse_args() -> argparse.Namespace:
    settings = Settings.from_env(project_root=PROJECT_ROOT)
    parser = argparse.ArgumentParser(
        description="使用 SiliconFlow embeddings 构建诗词向量 sidecar"
    )
    parser.add_argument(
        "--knowledge",
        type=Path,
        default=settings.resolved_knowledge_base_path,
        help="主知识库 SQLite 路径",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=settings.resolved_vector_root_path,
        help="版本化向量 artifact 根目录",
    )
    parser.add_argument(
        "--scope",
        choices=("line", "poem", "both"),
        default="both",
        help="生成诗句、整诗或两种向量",
    )
    parser.add_argument(
        "--batch-size", type=int, default=settings.embedding_batch_size
    )
    parser.add_argument(
        "--concurrency", type=int, default=settings.embedding_concurrency
    )
    parser.add_argument("--timeout", type=float, default=settings.embedding_timeout)
    parser.add_argument("--retries", type=int, default=settings.embedding_retries)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="保留含失败项的 partial artifact（服务不会激活）；默认失败并保留断点",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.from_env(project_root=PROJECT_ROOT)
    if not settings.embedding_configured:
        print(
            "缺少向量配置: " + ", ".join(settings.missing_embedding_settings),
            file=sys.stderr,
        )
        return 2
    try:
        config = EmbeddingProviderConfig(
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            batch_size=args.batch_size,
            concurrency=args.concurrency,
            timeout=args.timeout,
            retries=args.retries,
        )
        scopes = ("poem", "line") if args.scope == "both" else (args.scope,)
        with SiliconFlowEmbeddingClient(config) as client:
            manifest = build_poetry_embeddings(
                knowledge_path=args.knowledge,
                output_root=args.output_root,
                client=client,
                config=config,
                scopes=scopes,
                rebuild=args.rebuild,
                allow_partial=args.allow_partial,
            )
    except (ValueError, EmbeddingBuildError, RuntimeError) as exc:
        print(f"向量构建失败: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
