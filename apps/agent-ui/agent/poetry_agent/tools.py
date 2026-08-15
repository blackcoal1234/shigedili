"""LangChain tools and matching CopilotKit action adapters."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, tool

from .schemas import (
    CompareImageryInput,
    GeneratePoetRouteInput,
    GetLineKnowledgeInput,
    GetPoemKnowledgeInput,
    PlayPoemScenesInput,
    SearchPoetryKnowledgeInput,
)
from .service import PoetryDataService


def build_langchain_tools(service: PoetryDataService) -> list[BaseTool]:
    @tool("generate_poet_route", args_schema=GeneratePoetRouteInput)
    def generate_poet_route(
        poet: str,
        include_approximate: bool = True,
        include_disputed: bool = True,
    ) -> dict[str, Any]:
        """读取审核/候选编年快照，返回诗人的可渲染路线；不得自行推断地点。"""

        return service.generate_poet_route(
            poet,
            include_approximate=include_approximate,
            include_disputed=include_disputed,
        )

    @tool("play_poem_scenes", args_schema=PlayPoemScenesInput)
    def play_poem_scenes(
        poet: str,
        start_scene_id: str | None = None,
        autoplay: bool = False,
    ) -> dict[str, Any]:
        """返回按史料系年排序的逐诗篇镜头；默认逐幕手动停驻。"""

        return service.play_poem_scenes(
            poet, start_scene_id=start_scene_id, autoplay=autoplay
        )

    @tool("compare_imagery", args_schema=CompareImageryInput)
    def compare_imagery(
        terms: list[str] | None = None,
        limit: int = 8,
        chapter_id: str | None = None,
    ) -> dict[str, Any]:
        """读取38号统计，比较160词白名单中的唐宋每万字率并返回证据。"""

        return service.compare_imagery(terms=terms, limit=limit, chapter_id=chapter_id)

    @tool("search_poetry_knowledge", args_schema=SearchPoetryKnowledgeInput)
    def search_poetry_knowledge(
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
        """搜索离线诗词知识库，可按诗人、朝代、意象和情感组合过滤。"""

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

    @tool("get_poem_knowledge", args_schema=GetPoemKnowledgeInput)
    def get_poem_knowledge(poem_id: str) -> dict[str, Any]:
        """按稳定 poemId 返回全诗、有序诗句以及意象/情感分析。"""

        return service.get_poem_knowledge(poem_id)

    @tool("get_line_knowledge", args_schema=GetLineKnowledgeInput)
    def get_line_knowledge(line_id: str) -> dict[str, Any]:
        """按稳定 lineId 返回原句偏移、诗篇归属与结构化分析。"""

        return service.get_line_knowledge(line_id)

    return [
        generate_poet_route,
        play_poem_scenes,
        compare_imagery,
        search_poetry_knowledge,
        get_poem_knowledge,
        get_line_knowledge,
    ]


def build_copilot_actions(service: PoetryDataService) -> list[Any]:
    """Expose the same deterministic handlers to CopilotKit direct actions."""

    from copilotkit import Action

    return [
        Action(
            name="generate_poet_route",
            description="从项目Python生成数据返回诗人编年路线，绝不从文本推测地点。",
            handler=service.generate_poet_route,
            parameters=[
                {"name": "poet", "type": "string", "description": "诗人姓名"},
                {
                    "name": "include_approximate",
                    "type": "boolean",
                    "required": False,
                    "description": "保留约年/年份范围，默认true",
                },
                {
                    "name": "include_disputed",
                    "type": "boolean",
                    "required": False,
                    "description": "保留争议系年，默认true",
                },
            ],
        ),
        Action(
            name="play_poem_scenes",
            description="返回逐诗篇镜头和播放状态；默认手动停驻。",
            handler=service.play_poem_scenes,
            parameters=[
                {"name": "poet", "type": "string", "description": "诗人姓名"},
                {
                    "name": "start_scene_id",
                    "type": "string",
                    "required": False,
                    "description": "可选起始镜头id",
                },
                {
                    "name": "autoplay",
                    "type": "boolean",
                    "required": False,
                    "description": "默认false",
                },
            ],
        ),
        Action(
            name="compare_imagery",
            description="比较160词白名单内的唐宋每万字率并返回原文证据。",
            handler=service.compare_imagery,
            parameters=[
                {
                    "name": "terms",
                    "type": "string[]",
                    "required": False,
                    "description": "可选意象词列表",
                },
                {
                    "name": "limit",
                    "type": "number",
                    "required": False,
                    "description": "1..20，默认8",
                },
                {
                    "name": "chapter_id",
                    "type": "string",
                    "required": False,
                    "description": "可选历史章节id",
                },
            ],
        ),
        Action(
            name="search_poetry_knowledge",
            description="检索离线诗篇/诗句知识库，返回稳定ID、意象、情感和方法标记。",
            handler=service.search_poetry_knowledge,
            parameters=[
                {"name": "query", "type": "string", "required": False, "description": "搜索词"},
                {"name": "poet", "type": "string", "required": False, "description": "诗人"},
                {"name": "dynasty", "type": "string", "required": False, "description": "朝代"},
                {"name": "imagery", "type": "string", "required": False, "description": "意象"},
                {"name": "emotion", "type": "string", "required": False, "description": "情感"},
                {"name": "mode", "type": "string", "required": False, "description": "lexical/semantic/hybrid"},
                {"name": "scope", "type": "string", "required": False, "description": "poem/line/all"},
                {"name": "limit", "type": "number", "required": False, "description": "1..50"},
                {"name": "offset", "type": "number", "required": False, "description": "分页偏移"},
            ],
        ),
        Action(
            name="get_poem_knowledge",
            description="按稳定 poemId 取得全诗、诗句与分析。",
            handler=service.get_poem_knowledge,
            parameters=[
                {"name": "poem_id", "type": "string", "description": "稳定诗篇ID"},
            ],
        ),
        Action(
            name="get_line_knowledge",
            description="按稳定 lineId 取得诗句与分析。",
            handler=service.get_line_knowledge,
            parameters=[
                {"name": "line_id", "type": "string", "description": "稳定诗句ID"},
            ],
        ),
    ]
