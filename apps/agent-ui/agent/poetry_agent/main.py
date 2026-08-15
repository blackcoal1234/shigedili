"""FastAPI application exposing AG-UI, CopilotKit, health and catalog routes."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from ag_ui_langgraph import add_langgraph_fastapi_endpoint
from copilotkit import CopilotKitRemoteEndpoint, LangGraphAGUIAgent
from copilotkit.integrations.fastapi import add_fastapi_endpoint
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .agent import AGENT_DESCRIPTION, AGENT_NAME, build_agent_graph
from .cache import SnapshotRepository, sha256_file
from .config import Settings
from .health import health_payload
from .knowledge import PoetryKnowledgeRepository
from .embeddings import (
    EmbeddingProviderConfig,
    PoetryEmbeddingRepository,
    SiliconFlowEmbeddingClient,
)
from .schemas import (
    CompareImageryInput,
    GeneratePoetRouteInput,
    GetLineKnowledgeInput,
    GetPoemKnowledgeInput,
    PlayPoemScenesInput,
    SearchPoetryKnowledgeInput,
)
from .service import PoetryDataService
from .tools import build_copilot_actions, build_langchain_tools


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    repository = SnapshotRepository(settings.project_root, settings.cache_dir)
    knowledge_source_paths = (
        "data/poems.json",
        "data/spirit_image_dict.py",
        "data/classical_emotion_model.py",
        "data/classical_emotion_lexicon.py",
        "apps/agent-ui/agent/poetry_agent/knowledge.py",
        "apps/agent-ui/agent/poetry_agent/knowledge_builder.py",
    )
    expected_knowledge_sources = {
        relative: sha256_file(settings.project_root / relative)
        for relative in knowledge_source_paths
        if (settings.project_root / relative).is_file()
    }
    knowledge_repository = PoetryKnowledgeRepository(
        settings.resolved_knowledge_base_path,
        expected_sources=expected_knowledge_sources,
    )
    embedding_client = None
    if settings.embedding_configured:
        embedding_client = SiliconFlowEmbeddingClient(
            EmbeddingProviderConfig(
                base_url=settings.embedding_base_url,
                api_key=settings.embedding_api_key,
                model=settings.embedding_model,
                batch_size=settings.embedding_batch_size,
                concurrency=settings.embedding_concurrency,
                timeout=settings.embedding_timeout,
                retries=settings.embedding_retries,
            )
        )
    embedding_repository = PoetryEmbeddingRepository(
        settings.resolved_vector_root_path,
        settings.resolved_knowledge_base_path,
        client=embedding_client,
    )
    service = PoetryDataService(
        repository, knowledge_repository, embedding_repository
    )
    langchain_tools = build_langchain_tools(service)
    graph, agent_engine = build_agent_graph(settings, langchain_tools)
    agui_agent = LangGraphAGUIAgent(
        name=AGENT_NAME,
        description=AGENT_DESCRIPTION,
        graph=graph,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            if embedding_client is not None:
                embedding_client.close()

    app = FastAPI(
        title="诗行万里 Agent API",
        version="0.2.0",
        description="AG-UI backend whose facts come only from project Python generators.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.repository = repository
    app.state.knowledge_repository = knowledge_repository
    app.state.embedding_repository = embedding_repository
    app.state.embedding_client = embedding_client
    app.state.service = service
    app.state.agent_engine = agent_engine

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        response = service.invalid_request_from_errors(exc.errors())
        return JSONResponse(status_code=422, content=response)

    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.allowed_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return health_payload(
            settings,
            repository,
            agent_engine,
            knowledge_repository,
            embedding_repository,
        )

    @app.get("/catalog/poets")
    def catalog_poets() -> dict[str, Any]:
        return service.catalog_poets()

    @app.post("/tools/generate_poet_route")
    def generate_poet_route(payload: GeneratePoetRouteInput) -> dict[str, Any]:
        return service.generate_poet_route(**payload.model_dump())

    @app.post("/tools/play_poem_scenes")
    def play_poem_scenes(payload: PlayPoemScenesInput) -> dict[str, Any]:
        return service.play_poem_scenes(**payload.model_dump())

    @app.post("/tools/compare_imagery")
    def compare_imagery(payload: CompareImageryInput) -> dict[str, Any]:
        return service.compare_imagery(**payload.model_dump())

    @app.post("/tools/search_poetry_knowledge")
    def search_poetry_knowledge(
        payload: SearchPoetryKnowledgeInput,
    ) -> dict[str, Any]:
        return service.search_poetry_knowledge(**payload.model_dump())

    @app.post("/tools/get_poem_knowledge")
    def get_poem_knowledge(payload: GetPoemKnowledgeInput) -> dict[str, Any]:
        return service.get_poem_knowledge(payload.poem_id)

    @app.post("/tools/get_line_knowledge")
    def get_line_knowledge(payload: GetLineKnowledgeInput) -> dict[str, Any]:
        return service.get_line_knowledge(payload.line_id)

    @app.get("/knowledge/status")
    def knowledge_status() -> dict[str, Any]:
        return service.knowledge_status()

    @app.get("/knowledge/search")
    def knowledge_search(
        query: str = "",
        poet: str | None = None,
        dynasty: str | None = None,
        imagery: str | None = None,
        emotion: str | None = None,
        mode: str = "lexical",
        scope: str = "all",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        return service.search_poetry_knowledge(
            query=query,
            poet=poet,
            dynasty=dynasty,
            imagery=imagery,
            emotion=emotion,
            mode=mode,
            scope=scope,
            limit=limit,
            offset=offset,
        )

    @app.get("/knowledge/poems/{poem_id}")
    def knowledge_poem(poem_id: str) -> dict[str, Any]:
        return service.get_poem_knowledge(poem_id)

    @app.get("/knowledge/lines/{line_id}")
    def knowledge_line(line_id: str) -> dict[str, Any]:
        return service.get_line_knowledge(line_id)

    @app.get("/")
    def root_info() -> dict[str, Any]:
        return {
            "service": "poetry-agent-backend",
            "agUi": "POST /",
            "copilotKit": "/copilotkit/",
            "health": "/health",
            "catalog": "/catalog/poets",
            "tools": [
                "/tools/generate_poet_route",
                "/tools/play_poem_scenes",
                "/tools/compare_imagery",
                "/tools/search_poetry_knowledge",
                "/tools/get_poem_knowledge",
                "/tools/get_line_knowledge",
            ],
            "knowledge": {
                "status": "/knowledge/status",
                "search": "/knowledge/search",
                "poem": "/knowledge/poems/{poem_id}",
                "line": "/knowledge/lines/{line_id}",
            },
        }

    # Native AG-UI endpoint used by remote-agent clients.
    add_langgraph_fastapi_endpoint(app, agui_agent, "/")

    # CopilotKit discovery/action compatibility endpoint. The agent and direct
    # actions share the same deterministic service handlers.
    sdk = CopilotKitRemoteEndpoint(
        actions=build_copilot_actions(service), agents=[agui_agent]
    )
    add_fastapi_endpoint(app, sdk, "/copilotkit")
    return app


app = create_app()


def run() -> None:
    settings = app.state.settings
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()
