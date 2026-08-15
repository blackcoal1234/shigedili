"""Input schemas shared by LangChain tools and CopilotKit actions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictToolInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class GeneratePoetRouteInput(StrictToolInput):
    poet: str = Field(description="诗人姓名，必须来自 /catalog/poets")
    include_approximate: bool = Field(
        default=True, description="是否保留 approximate/range 约年记录"
    )
    include_disputed: bool = Field(default=True, description="是否保留 disputed 争议系年")

    @field_validator("poet")
    @classmethod
    def normalize_poet(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("poet 不能为空")
        return value


class PlayPoemScenesInput(StrictToolInput):
    poet: str = Field(description="诗人姓名，必须来自 /catalog/poets")
    start_scene_id: str | None = Field(
        default=None, description="可选的起始镜头 id；省略则从第一幕开始"
    )
    autoplay: bool = Field(default=False, description="默认 false，逐幕手动停驻")

    @field_validator("poet")
    @classmethod
    def normalize_poet(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("poet 不能为空")
        return value

    @field_validator("start_scene_id")
    @classmethod
    def normalize_start_scene_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("start_scene_id 传入时不能为空")
        return value


class CompareImageryInput(StrictToolInput):
    terms: list[str] | None = Field(
        default=None, description="可选意象词列表；每项必须属于审核后的160词表"
    )
    limit: int = Field(default=8, ge=1, le=20, description="返回词数，范围1..20")
    chapter_id: str | None = Field(
        default=None, description="可选历史章节 id，用于追加该章节点与证据"
    )

    @field_validator("terms")
    @classmethod
    def normalize_terms(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        result: list[str] = []
        for term in value:
            normalized = term.strip()
            if not normalized:
                raise ValueError("terms 中的词不能为空")
            if normalized not in result:
                result.append(normalized)
        if not result:
            raise ValueError("terms 传入时至少包含一个非空词")
        return result

    @field_validator("chapter_id")
    @classmethod
    def normalize_chapter_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("chapter_id 传入时不能为空")
        return value


def _normalize_optional_filter(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} 传入时不能为空")
    return normalized


class SearchPoetryKnowledgeInput(StrictToolInput):
    """搜索诗词知识库。

    query 可为空，便于页面只按诗人、朝代、意象或情感浏览。
    """

    query: str = Field(default="", max_length=160, description="题名、诗人、原文或分析文本")
    poet: str | None = Field(default=None, max_length=32, description="可选诗人过滤")
    dynasty: str | None = Field(default=None, max_length=16, description="可选朝代过滤")
    imagery: str | None = Field(default=None, max_length=32, description="可选规范意象过滤")
    emotion: str | None = Field(default=None, max_length=32, description="可选情感标签过滤")
    mode: Literal["lexical", "semantic", "hybrid"] = Field(
        default="lexical", description="关键词、向量语义或混合检索"
    )
    scope: Literal["poem", "line", "all"] = Field(
        default="all", description="检索诗篇、诗句或两者"
    )
    limit: int = Field(default=20, ge=1, le=50, description="本页结果数，1..50")
    offset: int = Field(default=0, ge=0, le=100_000, description="翻页偏移量")

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return " ".join(value.strip().split())

    @field_validator("poet", "dynasty", "imagery", "emotion")
    @classmethod
    def normalize_filters(cls, value: str | None, info) -> str | None:
        return _normalize_optional_filter(value, field=info.field_name)


class GetPoemKnowledgeInput(StrictToolInput):
    poem_id: str = Field(min_length=1, max_length=160, description="知识库稳定诗篇 ID")

    @field_validator("poem_id")
    @classmethod
    def normalize_poem_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("poem_id 不能为空")
        return value


class GetLineKnowledgeInput(StrictToolInput):
    line_id: str = Field(min_length=1, max_length=200, description="知识库稳定诗句 ID")

    @field_validator("line_id")
    @classmethod
    def normalize_line_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("line_id 不能为空")
        return value
