"""Dependency-free health contract used by FastAPI and unit tests."""

from __future__ import annotations

from typing import Any

from .cache import SnapshotRepository
from .config import Settings


def _required_sources(settings: Settings) -> dict[str, Any]:
    return {
        "poems": settings.project_root / "data" / "poems.json",
        "yearGenerator": settings.project_root
        / "数据可视化脚本"
        / "viz_33_year759.py",
        "imageryGenerator": settings.project_root
        / "数据可视化脚本"
        / "viz_38_imagery_tide.py",
    }


def readiness_payload(
    settings: Settings,
    knowledge_repository: Any | None = None,
) -> dict[str, Any]:
    """Return a deployment-safe readiness check without deep artifact scans."""

    required_sources = _required_sources(settings)
    missing_sources = [name for name, path in required_sources.items() if not path.is_file()]
    knowledge_path = settings.resolved_knowledge_base_path
    if knowledge_repository is None:
        manifest_path = knowledge_path.with_suffix(".manifest.json")
        knowledge_status: dict[str, Any] = {
            "available": knowledge_path.is_file() and manifest_path.is_file(),
            "path": str(knowledge_path),
            "manifestPath": str(manifest_path),
        }
    else:
        try:
            knowledge_status = knowledge_repository.quick_status()
        except Exception as exc:
            knowledge_status = {
                "available": False,
                "path": str(knowledge_path),
                "error": str(exc),
            }
    available = bool(knowledge_status.get("available"))
    return {
        "status": "ok" if not missing_sources and available else "degraded",
        "service": "poetry-agent-backend",
        "port": settings.port,
        "sources": {
            "projectRoot": str(settings.project_root),
            "missing": missing_sources,
            "knowledgeBase": knowledge_status,
        },
    }


def health_payload(
    settings: Settings,
    repository: SnapshotRepository,
    agent_engine: str,
    knowledge_repository: Any | None = None,
    embedding_repository: Any | None = None,
) -> dict[str, Any]:
    required_sources = _required_sources(settings)
    missing_sources = [name for name, path in required_sources.items() if not path.is_file()]
    if knowledge_repository is None:
        knowledge_status: dict[str, Any] = {
            "available": settings.resolved_knowledge_base_path.is_file(),
            "path": str(settings.resolved_knowledge_base_path),
        }
    else:
        try:
            knowledge_status = knowledge_repository.quick_status()
        except Exception as exc:  # health must remain available for repair guidance
            knowledge_status = {
                "available": False,
                "path": str(settings.resolved_knowledge_base_path),
                "error": str(exc),
                "buildCommand": "python tools/build_poetry_knowledge_base.py --rebuild",
            }
    knowledge_available = bool(knowledge_status.get("available", True))
    if embedding_repository is None or not settings.embedding_configured:
        vector_status: dict[str, Any] = {
            "available": False,
            "configured": settings.embedding_configured,
            "path": str(settings.resolved_vector_root_path),
            "ready": False,
            "state": "disabled",
        }
    else:
        try:
            vector_status = embedding_repository.status()
            vector_status["configured"] = settings.embedding_configured
            vector_status["ready"] = bool(
                settings.embedding_configured and vector_status.get("available")
            )
            vector_status["state"] = (
                "ready"
                if vector_status["ready"]
                else "disabled"
                if not settings.embedding_configured
                else "error"
            )
        except Exception as exc:
            vector_status = {
                "available": False,
                "configured": settings.embedding_configured,
                "path": str(settings.resolved_vector_root_path),
                "error": str(exc),
                "buildCommand": "python tools/build_poetry_embeddings.py --scope both",
            }
    status = (
        "ok"
        if settings.model_configured and not missing_sources and knowledge_available
        else "degraded"
    )
    return {
        "status": status,
        "service": "poetry-agent-backend",
        "port": settings.port,
        "agent": {
            "name": "poetry_evidence_agent",
            "engine": agent_engine,
            "modelConfigured": settings.model_configured,
            "model": settings.llm_model or None,
            "missingModelSettings": settings.missing_model_settings,
            "embeddingConfigured": settings.embedding_configured,
            "embeddingModel": settings.embedding_model or None,
            "missingEmbeddingSettings": settings.missing_embedding_settings,
        },
        "sources": {
            "projectRoot": str(settings.project_root),
            "missing": missing_sources,
            "cache": repository.cache_status(),
            "knowledgeBase": knowledge_status,
            "vectorIndex": vector_status,
        },
        "endpoints": {
            "agUi": "/",
            "copilotKit": "/copilotkit/",
            "catalog": "/catalog/poets",
            "knowledgeStatus": "/knowledge/status",
            "knowledgeSearch": "/knowledge/search",
        },
    }
