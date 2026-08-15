"""Build the DeepAgent graph or a startup-safe degraded graph."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph

from .config import Settings
from .prompts import SYSTEM_PROMPT


AGENT_NAME = "poetry_evidence_agent"
AGENT_DESCRIPTION = "以项目生成数据和版本化知识库为事实源的诗词、意象、情感与行旅助手"


def _build_degraded_graph(settings: Settings) -> Any:
    missing = "、".join(settings.missing_model_settings)

    def report_degraded(_: MessagesState) -> dict[str, list[AIMessage]]:
        return {
            "messages": [
                AIMessage(
                    content=(
                        "Agent模型配置不完整，当前仅数据工具与目录接口可用。"
                        f"缺少：{missing}。"
                    )
                )
            ]
        }

    builder = StateGraph(MessagesState)
    builder.add_node("degraded", report_degraded)
    builder.add_edge(START, "degraded")
    builder.add_edge("degraded", END)
    return builder.compile(checkpointer=InMemorySaver())


def _build_deep_agent(settings: Settings, tools: list[BaseTool]) -> Any:
    from deepagents import (
        GeneralPurposeSubagentProfile,
        HarnessProfile,
        create_deep_agent,
        register_harness_profile,
    )
    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=0,
        streaming=True,
    )
    # DeepAgents adds filesystem and shell helpers by default. This profile removes
    # every built-in fact path so the model sees only the six project tools.
    register_harness_profile(
        "openai",
        HarnessProfile(
            excluded_tools=frozenset(
                {
                    "ls",
                    "read_file",
                    "write_file",
                    "edit_file",
                    "delete",
                    "glob",
                    "grep",
                    "execute",
                }
            ),
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )
    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=InMemorySaver(),
        name=AGENT_NAME,
    )


def build_agent_graph(
    settings: Settings, tools: list[BaseTool]
) -> tuple[Any, str]:
    if not settings.model_configured:
        return _build_degraded_graph(settings), "degraded_langgraph"
    return _build_deep_agent(settings, tools), "deepagents"
