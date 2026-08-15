"""Environment configuration and project-root discovery."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


LLM_ENV_KEYS = (
    "AGENT_LLM_BASE_URL",
    "AGENT_LLM_API_KEY",
    "AGENT_LLM_MODEL",
)

EMBEDDING_ENV_KEYS = (
    "AGENT_EMBEDDING_BASE_URL",
    "AGENT_EMBEDDING_API_KEY",
    "AGENT_EMBEDDING_MODEL",
)


def _is_same_or_descendant(path: Path, parent: Path) -> bool:
    candidate_key = os.path.normcase(str(path.resolve()))
    parent_key = os.path.normcase(str(parent.resolve()))
    try:
        return os.path.commonpath((candidate_key, parent_key)) == parent_key
    except ValueError:
        return False


def discover_project_root(start: Path | None = None) -> Path:
    """Find the repository root without depending on the current directory."""

    origins = [start.resolve()] if start is not None else [Path.cwd().resolve(), Path(__file__).resolve()]
    checked: set[Path] = set()
    for origin in origins:
        candidates = (origin, *origin.parents) if origin.is_dir() else origin.parents
        for candidate in candidates:
            if candidate in checked:
                continue
            checked.add(candidate)
            if (
                (candidate / "data" / "poems.json").is_file()
                and (candidate / "数据可视化脚本" / "viz_33_year759.py").is_file()
                and (candidate / "数据可视化脚本" / "viz_38_imagery_tide.py").is_file()
            ):
                return candidate
    raise RuntimeError("未找到项目根目录：缺少 data/poems.json 或 33/38 生成器")


@dataclass(frozen=True)
class Settings:
    project_root: Path
    cache_dir: Path
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_api_key: str = ""
    embedding_model: str = "BAAI/bge-m3"
    embedding_batch_size: int = 16
    embedding_concurrency: int = 8
    embedding_timeout: float = 8.0
    embedding_retries: int = 1
    vector_root_path: Path | None = None
    host: str = "127.0.0.1"
    port: int = 8123
    allowed_origins: tuple[str, ...] = ()
    knowledge_base_path: Path | None = None

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        project_root: Path | None = None,
    ) -> "Settings":
        values = os.environ if env is None else env
        root = (project_root or discover_project_root()).resolve()
        cache_value = values.get("AGENT_CACHE_DIR", "").strip()
        cache_dir = (
            Path(cache_value).expanduser().resolve()
            if cache_value
            else root / "apps" / "agent-ui" / ".cache"
        )
        restricted_roots = (root / "data", root / "output")
        if any(_is_same_or_descendant(cache_dir, path) for path in restricted_roots):
            raise ValueError("AGENT_CACHE_DIR 不得等于或位于项目 data/output 目录内")
        origins = tuple(
            item.strip()
            for item in values.get(
                "AGENT_ALLOWED_ORIGINS",
                "http://127.0.0.1:3000,http://localhost:3000,"
                "http://127.0.0.1:5173,http://localhost:5173",
            ).split(",")
            if item.strip()
        )
        try:
            port = int(values.get("AGENT_PORT", "8123"))
        except ValueError as exc:
            raise ValueError("AGENT_PORT 必须是整数") from exc
        if not 1 <= port <= 65535:
            raise ValueError("AGENT_PORT 必须位于 1..65535")
        knowledge_value = values.get("AGENT_KB_PATH", "").strip()
        knowledge_base_path = (
            Path(knowledge_value).expanduser().resolve()
            if knowledge_value
            else root / "output" / "assets" / "knowledge" / "poetry_knowledge.sqlite3"
        )
        vector_value = values.get("AGENT_VECTOR_ROOT", "").strip()
        vector_root_path = (
            Path(vector_value).expanduser().resolve()
            if vector_value
            else root / "output" / "assets" / "knowledge" / "embeddings"
        )
        try:
            embedding_batch_size = int(
                values.get("AGENT_EMBEDDING_BATCH_SIZE", "16")
            )
            embedding_concurrency = int(
                values.get("AGENT_EMBEDDING_CONCURRENCY", "8")
            )
            embedding_timeout = float(
                values.get("AGENT_EMBEDDING_TIMEOUT", "8")
            )
            embedding_retries = int(
                values.get("AGENT_EMBEDDING_RETRIES", "1")
            )
        except ValueError as exc:
            raise ValueError("AGENT_EMBEDDING_* 数值配置无效") from exc
        if not 1 <= embedding_batch_size <= 32:
            raise ValueError("AGENT_EMBEDDING_BATCH_SIZE 必须位于 1..32")
        if not 1 <= embedding_concurrency <= 64:
            raise ValueError("AGENT_EMBEDDING_CONCURRENCY 必须位于 1..64")
        if embedding_timeout <= 0:
            raise ValueError("AGENT_EMBEDDING_TIMEOUT 必须大于 0")
        if not 0 <= embedding_retries <= 10:
            raise ValueError("AGENT_EMBEDDING_RETRIES 必须位于 0..10")
        return cls(
            project_root=root,
            cache_dir=cache_dir,
            llm_base_url=values.get("AGENT_LLM_BASE_URL", "").strip(),
            llm_api_key=values.get("AGENT_LLM_API_KEY", "").strip(),
            llm_model=values.get("AGENT_LLM_MODEL", "").strip(),
            embedding_base_url=values.get(
                "AGENT_EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1"
            ).strip(),
            embedding_api_key=values.get("AGENT_EMBEDDING_API_KEY", "").strip(),
            embedding_model=values.get(
                "AGENT_EMBEDDING_MODEL", "BAAI/bge-m3"
            ).strip(),
            embedding_batch_size=embedding_batch_size,
            embedding_concurrency=embedding_concurrency,
            embedding_timeout=embedding_timeout,
            embedding_retries=embedding_retries,
            vector_root_path=vector_root_path,
            host=values.get("AGENT_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=port,
            allowed_origins=origins,
            knowledge_base_path=knowledge_base_path,
        )

    @property
    def model_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    @property
    def missing_model_settings(self) -> list[str]:
        values = {
            "AGENT_LLM_BASE_URL": self.llm_base_url,
            "AGENT_LLM_API_KEY": self.llm_api_key,
            "AGENT_LLM_MODEL": self.llm_model,
        }
        return [key for key in LLM_ENV_KEYS if not values[key]]

    @property
    def resolved_knowledge_base_path(self) -> Path:
        if self.knowledge_base_path is not None:
            return self.knowledge_base_path.expanduser().resolve()
        return (
            self.project_root
            / "output"
            / "assets"
            / "knowledge"
            / "poetry_knowledge.sqlite3"
        ).resolve()

    @property
    def embedding_configured(self) -> bool:
        return bool(
            self.embedding_base_url.strip()
            and self.embedding_api_key.strip()
            and self.embedding_model.strip()
        )

    @property
    def missing_embedding_settings(self) -> list[str]:
        values = {
            "AGENT_EMBEDDING_BASE_URL": self.embedding_base_url,
            "AGENT_EMBEDDING_API_KEY": self.embedding_api_key,
            "AGENT_EMBEDDING_MODEL": self.embedding_model,
        }
        return [key for key in EMBEDDING_ENV_KEYS if not values[key]]

    @property
    def resolved_vector_root_path(self) -> Path:
        if self.vector_root_path is not None:
            return self.vector_root_path.expanduser().resolve()
        return (
            self.project_root
            / "output"
            / "assets"
            / "knowledge"
            / "embeddings"
        ).resolve()
