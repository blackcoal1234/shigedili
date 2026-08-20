"""Deterministic tool service built exclusively from generated project data."""

from __future__ import annotations

from collections import Counter, defaultdict
import re
from typing import Any, Mapping

from pydantic import BaseModel, ValidationError

from .cache import (
    IMAGERY_SPEC,
    SCHEMA_VERSION,
    YEAR_SPEC,
    DatasetSnapshot,
    SnapshotRepository,
    SourceDataError,
)
from .knowledge import (
    KnowledgeUnavailableError,
    KnowledgeValidationError,
    PoetryKnowledgeRepository,
)
from .glossary import PoetryGlossary
from .embeddings import (
    EmbeddingError,
    EmbeddingProviderError,
    EmbeddingUnavailableError,
    PoetryEmbeddingRepository,
)
from .schemas import (
    CompareImageryInput,
    GeneratePoetRouteInput,
    GetLineKnowledgeInput,
    GetPoemKnowledgeInput,
    PlayPoemScenesInput,
    SearchPoetryKnowledgeInput,
)


EXACT_PRECISIONS = {"exact", "year"}
APPROXIMATE_PRECISIONS = {"approximate", "range"}
DISPUTED_PRECISIONS = {"disputed"}
MISSING_ROUTE_FACTS = [
    "year_start",
    "year_end",
    "year_precision",
    "place_historical",
    "place_modern",
    "longitude",
    "latitude",
    "source_grade",
    "source_url",
]

TRANSPORT_RULES = (
    (
        "carriage",
        "车乘",
        re.compile(r"乘马车|乘车|马车|驿车|车驾"),
    ),
    (
        "horse",
        "骑马",
        re.compile(r"骑马|乘马|驿马|策马"),
    ),
    (
        "boat",
        "舟船",
        re.compile(
            r"乘舟(?:东下|西上|南下|北上)?|舟经|舟行|泛舟|海上航行|"
            r"海道(?:到|至|经)|水师东下|溯流而上|溯江|乘船"
        ),
    ),
    (
        "walk",
        "步行",
        re.compile(r"徒步|步行|徒行|步入|步至"),
    ),
)


def classify_transport(
    from_scene: dict[str, Any], to_scene: dict[str, Any]
) -> dict[str, str]:
    """Classify transport only from explicit prose in the two source records."""
    evidence = "\n".join(
        str(scene.get(field) or "")
        for scene in (from_scene, to_scene)
        for field in ("source_note", "event")
    )
    for mode, label, pattern in TRANSPORT_RULES:
        match = pattern.search(evidence)
        if match:
            return {
                "transport_mode": mode,
                "transport_label": label,
                "transport_basis": f"来源文字：{match.group(0)}",
                "transport_certainty": "documented",
            }
    return {
        "transport_mode": "journey",
        "transport_label": "行旅",
        "transport_basis": "来源未注明交通方式，使用通用行旅标记",
        "transport_certainty": "unspecified",
    }


def build_visual_transitions(
    scenes: list[dict[str, Any]],
    historical_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Connect adjacent mapped scenes without asserting an undocumented route."""
    historical_pairs = {
        (row.get("from_id"), row.get("to_id"))
        for row in historical_segments
    }
    transitions: list[dict[str, Any]] = []
    for start, end in zip(scenes, scenes[1:]):
        pair = (start.get("id"), end.get("id"))
        if pair in historical_pairs:
            continue
        if not start.get("map_eligible") or not end.get("map_eligible"):
            continue
        if not all(
            isinstance(value, (int, float))
            for value in (start.get("lon"), start.get("lat"), end.get("lon"), end.get("lat"))
        ):
            continue
        transitions.append(
            {
                "from_id": start["id"],
                "to_id": end["id"],
                "coords": [
                    [start["lon"], start["lat"]],
                    [end["lon"], end["lat"]],
                ],
                "kind": "visual_transition",
                "certainty": "not_asserted",
                "historical_claim": False,
                "gap_reason": "adjacent_locatable_scene_gap",
                "transport_mode": "journey",
                "transport_label": "山径行旅",
                "transport_basis": (
                    "两幕均有作品节点坐标；实际行路与交通方式未载，仅作镜头转场。"
                ),
                "transport_certainty": "unspecified",
            }
        )
    return transitions


def _base_response(
    *,
    status: str,
    source_hashes: dict[str, str],
    method_note: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": status,
        "schemaVersion": SCHEMA_VERSION,
        "sourceHashes": source_hashes,
        "methodNote": method_note,
        "payload": payload,
    }


class PoetryDataService:
    def __init__(
        self,
        repository: SnapshotRepository,
        knowledge_repository: PoetryKnowledgeRepository | None = None,
        embedding_repository: PoetryEmbeddingRepository | None = None,
        glossary: PoetryGlossary | None = None,
    ) -> None:
        self.repository = repository
        self.knowledge_repository = knowledge_repository
        self.embedding_repository = embedding_repository
        self.glossary = glossary

    def _catalog_rows(self) -> tuple[list[dict[str, Any]], dict[str, str]]:
        if self.knowledge_repository is not None:
            return self.knowledge_repository.catalog_rows()
        poems, hashes = self.repository.load_poems()
        counts: Counter[str] = Counter()
        dynasties: dict[str, Counter[str]] = defaultdict(Counter)
        first_seen: dict[str, int] = {}
        for index, row in enumerate(poems):
            poet = str(row.get("poet") or row.get("author") or "").strip()
            dynasty = str(row.get("dynasty") or "未知").strip() or "未知"
            counts[poet] += 1
            dynasties[poet][dynasty] += 1
            first_seen.setdefault(poet, index)
        rows = [
            {
                "poet": poet,
                "workCount": counts[poet],
                "dynasty": dynasties[poet].most_common(1)[0][0],
                "dynastyCounts": dict(dynasties[poet]),
                "corpusOrder": first_seen[poet],
            }
            for poet in counts
        ]
        return rows, hashes

    def catalog_poets(self) -> dict[str, Any]:
        try:
            rows, poem_hashes = self._catalog_rows()
            year_snapshot = self.repository.ensure_dataset(YEAR_SPEC)
            stories = {
                story["poet"]: story
                for story in year_snapshot.data["stories"]
                if isinstance(story, dict)
            }
            for row in rows:
                story = stories.get(row["poet"])
                row["routeStatus"] = "available" if story else "insufficient_evidence"
                row["sceneCount"] = len(story.get("scenes", [])) if story else 0
                row["mappedSceneCount"] = (
                    sum(1 for scene in story.get("scenes", []) if scene.get("map_eligible"))
                    if story
                    else 0
                )
                row.pop("corpusOrder", None)
            hashes = {**poem_hashes, **year_snapshot.source_hashes}
            return _base_response(
                status="ok",
                source_hashes=hashes,
                method_note=(
                    "目录由 data/poems.json 的88位诗人聚合；路线可用性只由33号生成数据判定。"
                ),
                payload={
                    "poetCount": len(rows),
                    "routeAvailableCount": len(stories),
                    "insufficientEvidenceCount": len(rows) - len(stories),
                    "poets": rows,
                },
            )
        except SourceDataError as exc:
            return self._source_error(exc)

    def knowledge_status(self) -> dict[str, Any]:
        """返回可供页面和运维监测复用的知识库状态。"""

        if self.knowledge_repository is None:
            return self._knowledge_unavailable(RuntimeError("未配置知识库仓库"))
        try:
            payload = self.knowledge_repository.quick_status()
            payload["vector"] = self._vector_status_payload()
            hashes = payload.get("sourceHashes", {}) if isinstance(payload, dict) else {}
            return _base_response(
                status="ok",
                source_hashes=hashes if isinstance(hashes, dict) else {},
                method_note=(
                    "知识库状态来自只读 SQLite manifest；"
                    "分析条目保留 rules/llm方法、模型和输入哈希。"
                ),
                payload=payload,
            )
        except KnowledgeUnavailableError as exc:
            return self._knowledge_unavailable(exc)
        except EmbeddingError as exc:
            return self._knowledge_unavailable(exc)

    def search_poetry_knowledge(
        self,
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
        values = {
            "query": query,
            "poet": poet,
            "dynasty": dynasty,
            "imagery": imagery,
            "emotion": emotion,
            "mode": mode,
            "scope": scope,
            "limit": limit,
            "offset": offset,
        }
        request, invalid = self._validate_input(SearchPoetryKnowledgeInput, values)
        if invalid is not None:
            return invalid
        assert isinstance(request, SearchPoetryKnowledgeInput)
        if self.knowledge_repository is None:
            return self._knowledge_unavailable(RuntimeError("未配置知识库仓库"))
        try:
            lexical_args = request.model_dump(exclude={"mode"})
            requested_mode = request.mode
            if not request.query or requested_mode == "lexical":
                payload = self.knowledge_repository.search(**lexical_args)
                payload.update(
                    {
                        "requestedMode": requested_mode,
                        "retrievalMethod": "lexical",
                        "degraded": False,
                    }
                )
            else:
                payload = self._search_with_vectors(request, lexical_args)
            hashes = payload.get("sourceHashes", {}) if isinstance(payload, dict) else {}
            return _base_response(
                status="ok",
                source_hashes=hashes if isinstance(hashes, dict) else {},
                method_note=(
                    "检索结合只读 SQLite FTS 与版本化 SiliconFlow 向量 sidecar；"
                    "查询向量仅用于召回，不生成或改写诗词事实。"
                ),
                payload=payload,
            )
        except KnowledgeValidationError as exc:
            return self._invalid(str(exc), {})
        except KnowledgeUnavailableError as exc:
            return self._knowledge_unavailable(exc)

    def _vector_status_payload(self) -> dict[str, Any]:
        if self.embedding_repository is None:
            return {
                "configured": False,
                "ready": False,
                "state": "disabled",
            }
        configured = self.embedding_repository.client is not None
        if not configured:
            return {
                "configured": False,
                "ready": False,
                "state": "disabled",
                "queryConfigured": False,
            }
        try:
            status = self.embedding_repository.status()
            counts = status.get("counts", {})
            available = bool(status.get("available"))
            return {
                "configured": configured,
                "ready": configured and available,
                "state": (
                    "ready"
                    if configured and available
                    else "disabled"
                    if not configured
                    else "error"
                ),
                "provider": status.get("provider"),
                "model": status.get("model"),
                "dimension": status.get("dimension"),
                "sourceBuildId": status.get("knowledge", {}).get("buildId"),
                "indexBuildId": status.get("buildId"),
                "indexedPoemCount": counts.get("poem", {}).get("completed", 0),
                "indexedLineCount": counts.get("line", {}).get("completed", 0),
                "queryConfigured": configured,
            }
        except EmbeddingUnavailableError as exc:
            message = str(exc)
            building = self.embedding_repository.root.is_dir() and any(
                self.embedding_repository.root.rglob("*.building")
            )
            stale = any(
                marker in message for marker in ("过期", "哈希", "不同", "源哈希")
            )
            return {
                "configured": configured,
                "ready": False,
                "state": "stale" if stale else "building" if building else "disabled",
                "reason": message,
            }
        except EmbeddingError as exc:
            return {
                "configured": configured,
                "ready": False,
                "state": "error",
                "reason": str(exc),
            }

    @staticmethod
    def _semantic_item(item: Mapping[str, Any]) -> dict[str, Any]:
        score = max(0.0, min(1.0, (float(item.get("score", 0.0)) + 1.0) / 2.0))
        result = {
            "scope": item.get("scope"),
            "poemId": item.get("poemId"),
            "lineId": item.get("lineId"),
            "lineNo": item.get("lineNo"),
            "title": item.get("title"),
            "poet": item.get("poet"),
            "dynasty": item.get("dynasty"),
            "text": item.get("text"),
            "snippet": item.get("text"),
            "score": round(score, 6),
            "retrievalMethod": "semantic",
        }
        for field in ("imagery", "emotions", "analysisMethods"):
            if field in item:
                result[field] = item[field]
        return result

    def _search_with_vectors(
        self,
        request: SearchPoetryKnowledgeInput,
        lexical_args: dict[str, Any],
    ) -> dict[str, Any]:
        assert self.knowledge_repository is not None
        knowledge_status = self.knowledge_repository.status()
        source_hashes = knowledge_status.get("sourceHashes", {})
        fallback_reason = "vector_not_ready"
        try:
            if self.embedding_repository is None:
                raise EmbeddingUnavailableError("未配置向量仓库")
            if self.embedding_repository.client is None:
                raise EmbeddingUnavailableError("未配置 SiliconFlow API Key")
            if request.mode == "semantic":
                semantic = self.embedding_repository.search(
                    request.query,
                    scope=request.scope,
                    poet=request.poet,
                    dynasty=request.dynasty,
                    imagery=request.imagery,
                    emotion=request.emotion,
                    limit=request.limit,
                    offset=request.offset,
                )
                semantic["items"] = [
                    self._semantic_item(item) for item in semantic["items"]
                ]
                semantic.update(
                    {
                        "requestedMode": "semantic",
                        "retrievalMethod": "semantic",
                        "degraded": False,
                        "totalRelation": "eq",
                        "hasMore": semantic["offset"] + len(semantic["items"])
                        < semantic["total"],
                        "vectorIndexBuildId": semantic.get("buildId"),
                        "sourceHashes": source_hashes,
                    }
                )
                return semantic

            candidate_limit = 50
            lexical_query = {**lexical_args, "limit": candidate_limit, "offset": 0}
            lexical = self.knowledge_repository.search(**lexical_query)
            semantic = self.embedding_repository.search(
                request.query,
                scope=request.scope,
                poet=request.poet,
                dynasty=request.dynasty,
                imagery=request.imagery,
                emotion=request.emotion,
                limit=candidate_limit,
                offset=0,
            )
            fused: dict[tuple[str, str], dict[str, Any]] = {}
            methods: dict[tuple[str, str], set[str]] = {}
            raw_scores: dict[tuple[str, str], float] = {}
            for method, items in (
                ("lexical", lexical.get("items", [])),
                ("semantic", semantic.get("items", [])),
            ):
                for rank, raw in enumerate(items, start=1):
                    item = dict(raw)
                    target = str(item.get("lineId") or item.get("poemId") or "")
                    key = (str(item.get("scope") or ""), target)
                    if not target:
                        continue
                    fused.setdefault(
                        key,
                        item if method == "lexical" else self._semantic_item(item),
                    )
                    methods.setdefault(key, set()).add(method)
                    raw_scores[key] = raw_scores.get(key, 0.0) + 1.0 / (60.0 + rank)
            maximum = 2.0 / 61.0
            ranked: list[dict[str, Any]] = []
            for key, item in fused.items():
                item["score"] = round(min(1.0, raw_scores[key] / maximum), 6)
                item["retrievalMethod"] = (
                    "hybrid" if len(methods[key]) == 2 else next(iter(methods[key]))
                )
                ranked.append(item)
            ranked.sort(
                key=lambda item: (
                    -float(item["score"]),
                    str(item.get("scope") or ""),
                    str(item.get("lineId") or item.get("poemId") or ""),
                )
            )
            page = ranked[request.offset : request.offset + request.limit]
            approximate = (
                int(lexical.get("total", 0)) > candidate_limit
                or int(semantic.get("total", 0)) > candidate_limit
            )
            has_more = (
                bool(page)
                and (
                    approximate
                    or request.offset + len(page) < len(ranked)
                )
            )
            return {
                "query": request.query,
                "scope": request.scope,
                "filters": {
                    "poet": request.poet,
                    "dynasty": request.dynasty,
                    "imagery": request.imagery,
                    "emotion": request.emotion,
                },
                "total": len(ranked),
                "limit": request.limit,
                "offset": request.offset,
                "items": page,
                "requestedMode": "hybrid",
                "retrievalMethod": "hybrid",
                "degraded": False,
                "totalRelation": "gte" if approximate else "eq",
                "hasMore": has_more,
                "vectorIndexBuildId": semantic.get("buildId"),
                "elapsedMs": round(
                    float(lexical.get("elapsedMs", 0.0))
                    + float(semantic.get("elapsedMs", 0.0)),
                    3,
                ),
                "sourceHashes": lexical.get("sourceHashes", {}),
            }
        except EmbeddingProviderError:
            fallback_reason = "embedding_provider_unavailable"
        except EmbeddingUnavailableError as exc:
            message = str(exc)
            if any(marker in message for marker in ("过期", "不同", "源哈希", "哈希")):
                fallback_reason = "vector_stale"
        except EmbeddingError:
            fallback_reason = "embedding_provider_unavailable"
        lexical = self.knowledge_repository.search(**lexical_args)
        lexical.update(
            {
                "requestedMode": request.mode,
                "retrievalMethod": "lexical",
                "degraded": True,
                "degradationReason": fallback_reason,
            }
        )
        return lexical

    def get_poem_knowledge(self, poem_id: str) -> dict[str, Any]:
        request, invalid = self._validate_input(
            GetPoemKnowledgeInput, {"poem_id": poem_id}
        )
        if invalid is not None:
            return invalid
        assert isinstance(request, GetPoemKnowledgeInput)
        if self.knowledge_repository is None:
            return self._knowledge_unavailable(RuntimeError("未配置知识库仓库"))
        try:
            payload = self.knowledge_repository.get_poem(request.poem_id)
            if payload is None:
                status_payload = self.knowledge_repository.status()
                hashes = status_payload.get("sourceHashes", {})
                return _base_response(
                    status="insufficient_evidence",
                    source_hashes=hashes if isinstance(hashes, dict) else {},
                    method_note="稳定 poemId 在当前知识库版本中不存在，未按标题模糊替代。",
                    payload={"poemId": request.poem_id, "notFound": True},
                )
            if self.glossary is not None:
                glossary_snapshot = self.glossary.snapshot()
                payload["glossaryVersion"] = glossary_snapshot.version
                payload["glosses"] = self.glossary.match_lines(payload["lines"])
                if glossary_snapshot.error:
                    payload["glossaryError"] = glossary_snapshot.error
            hashes = payload.get("sourceHashes", {}) if isinstance(payload, dict) else {}
            return _base_response(
                status="ok",
                source_hashes=hashes if isinstance(hashes, dict) else {},
                method_note=(
                    "诗篇、有序诗句、意象与情感分析均来自版本化知识库；"
                    "LLM条目与本地规则条目保留独立方法标记。"
                ),
                payload=payload,
            )
        except KnowledgeValidationError as exc:
            return self._invalid(str(exc), {})
        except KnowledgeUnavailableError as exc:
            return self._knowledge_unavailable(exc)

    def get_line_knowledge(self, line_id: str) -> dict[str, Any]:
        request, invalid = self._validate_input(
            GetLineKnowledgeInput, {"line_id": line_id}
        )
        if invalid is not None:
            return invalid
        assert isinstance(request, GetLineKnowledgeInput)
        if self.knowledge_repository is None:
            return self._knowledge_unavailable(RuntimeError("未配置知识库仓库"))
        try:
            payload = self.knowledge_repository.get_line(request.line_id)
            if payload is None:
                status_payload = self.knowledge_repository.status()
                hashes = status_payload.get("sourceHashes", {})
                return _base_response(
                    status="insufficient_evidence",
                    source_hashes=hashes if isinstance(hashes, dict) else {},
                    method_note="稳定 lineId 在当前知识库版本中不存在，未使用相似句替代。",
                    payload={"lineId": request.line_id, "notFound": True},
                )
            hashes = payload.get("sourceHashes", {}) if isinstance(payload, dict) else {}
            return _base_response(
                status="ok",
                source_hashes=hashes if isinstance(hashes, dict) else {},
                method_note="诗句文本、原文偏移和分析条目均由稳定 lineId 只读返回。",
                payload=payload,
            )
        except KnowledgeValidationError as exc:
            return self._invalid(str(exc), {})
        except KnowledgeUnavailableError as exc:
            return self._knowledge_unavailable(exc)

    @staticmethod
    def _source_error(exc: Exception) -> dict[str, Any]:
        return _base_response(
            status="source_error",
            source_hashes={},
            method_note="生成数据读取或结构校验失败；没有使用模型补写事实。",
            payload={"error": str(exc)},
        )

    @staticmethod
    def _knowledge_unavailable(exc: Exception) -> dict[str, Any]:
        return _base_response(
            status="source_error",
            source_hashes={},
            method_note=(
                "诗词知识库尚未生成、已过期或无法只读打开；"
                "没有调用模型临时补写结果。"
            ),
            payload={
                "error": str(exc),
                "available": False,
                "buildCommand": "python tools/build_poetry_knowledge_base.py --rebuild",
            },
        )

    @staticmethod
    def _invalid(
        message: str, source_hashes: dict[str, str], **details: Any
    ) -> dict[str, Any]:
        return _base_response(
            status="invalid_request",
            source_hashes=source_hashes,
            method_note="请求参数未通过确定性校验；没有生成替代事实。",
            payload={"error": message, **details},
        )

    @classmethod
    def invalid_request_from_errors(
        cls, errors: list[dict[str, Any]]
    ) -> dict[str, Any]:
        issues = [
            {
                "field": ".".join(str(part) for part in error.get("loc", ())),
                "message": str(error.get("msg", "参数无效")),
                "type": str(error.get("type", "value_error")),
            }
            for error in errors
        ]
        return cls._invalid("请求参数校验失败", {}, validationErrors=issues)

    @classmethod
    def _validate_input(
        cls, model: type[BaseModel], values: dict[str, Any]
    ) -> tuple[BaseModel | None, dict[str, Any] | None]:
        try:
            return model.model_validate(values), None
        except ValidationError as exc:
            return None, cls.invalid_request_from_errors(exc.errors())

    def _poet_context(
        self, poet: str
    ) -> tuple[
        dict[str, Any] | None,
        dict[str, Any] | None,
        int,
        str,
        dict[str, str],
        dict[str, Any] | None,
    ]:
        catalog, poem_hashes = self._catalog_rows()
        catalog_by_poet = {row["poet"]: row for row in catalog}
        row = catalog_by_poet.get(poet)
        if row is None:
            return None, None, 0, "", poem_hashes, None
        year_snapshot = self.repository.ensure_dataset(YEAR_SPEC)
        story = next(
            (item for item in year_snapshot.data["stories"] if item.get("poet") == poet),
            None,
        )
        return (
            row,
            story,
            int(row["workCount"]),
            str(row["dynasty"]),
            {**poem_hashes, **year_snapshot.source_hashes},
            year_snapshot.data,
        )

    @staticmethod
    def _insufficient_route(
        poet: str,
        work_count: int,
        dynasty: str,
        hashes: dict[str, str],
        *,
        mode: str,
    ) -> dict[str, Any]:
        return _base_response(
            status="insufficient_evidence",
            source_hashes=hashes,
            method_note=(
                "该诗人只有语料作品，没有经33号编年数据验证的年份与地点；"
                "不得从诗题或诗句地名推测行程。"
            ),
            payload={
                "poet": poet,
                "dynasty": dynasty,
                "corpusWorkCount": work_count,
                "mode": mode,
                "sceneCount": 0,
                "mappedSceneCount": 0,
                "scenes": [],
                "routeSegments": [],
                "visualTransitions": [],
                "missingFacts": MISSING_ROUTE_FACTS,
            },
        )

    @staticmethod
    def _select_scenes(
        scenes: list[dict[str, Any]],
        include_approximate: bool,
        include_disputed: bool,
    ) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        for scene in scenes:
            precision = str(scene.get("year_precision") or "unknown")
            if precision in APPROXIMATE_PRECISIONS and not include_approximate:
                continue
            if precision in DISPUTED_PRECISIONS and not include_disputed:
                continue
            if precision not in EXACT_PRECISIONS | APPROXIMATE_PRECISIONS | DISPUTED_PRECISIONS:
                continue
            selected.append(dict(scene))
        return selected

    def generate_poet_route(
        self,
        poet: str,
        include_approximate: bool = True,
        include_disputed: bool = True,
    ) -> dict[str, Any]:
        request, invalid = self._validate_input(
            GeneratePoetRouteInput,
            {
                "poet": poet,
                "include_approximate": include_approximate,
                "include_disputed": include_disputed,
            },
        )
        if invalid is not None:
            return invalid
        assert isinstance(request, GeneratePoetRouteInput)
        poet = request.poet
        include_approximate = request.include_approximate
        include_disputed = request.include_disputed
        try:
            row, story, work_count, dynasty, hashes, year_data = self._poet_context(poet)
            if row is None:
                catalog, _ = self._catalog_rows()
                return self._invalid(
                    f"未知诗人: {poet}",
                    hashes,
                    availablePoets=[item["poet"] for item in catalog],
                )
            if story is None:
                return self._insufficient_route(
                    poet, work_count, dynasty, hashes, mode="route"
                )
            scenes = self._select_scenes(
                story.get("scenes", []), include_approximate, include_disputed
            )
            selected_ids = {scene["id"] for scene in scenes}
            scene_by_id = {scene["id"]: scene for scene in scenes}
            segments = []
            for segment in story.get("segments", []):
                from_id = segment.get("from_id")
                to_id = segment.get("to_id")
                if from_id not in selected_ids or to_id not in selected_ids:
                    continue
                enriched = dict(segment)
                enriched.update(
                    classify_transport(scene_by_id[from_id], scene_by_id[to_id])
                )
                segments.append(enriched)
            visual_transitions = build_visual_transitions(scenes, segments)
            mapped_count = sum(1 for scene in scenes if scene.get("map_eligible"))
            precision_counts = Counter(
                str(scene.get("year_precision") or "unknown") for scene in scenes
            )
            unresolved = [
                dict(item)
                for item in (year_data or {}).get("unresolved", [])
                if item.get("poet") == poet
            ]
            return _base_response(
                status="ok",
                source_hashes=hashes,
                method_note=(
                    "镜头、年份、地点与史料连线均来自33号Python生成数据。"
                    "视觉转场只连接相邻作品节点，不表示真实道路、交通工具或旅行速度。"
                ),
                payload={
                    "poet": poet,
                    "poetKey": story.get("key"),
                    "dynasty": dynasty,
                    "color": story.get("color"),
                    "corpusWorkCount": work_count,
                    "filters": {
                        "includeApproximate": include_approximate,
                        "includeDisputed": include_disputed,
                    },
                    "sceneCount": len(scenes),
                    "mappedSceneCount": mapped_count,
                    "precisionCounts": dict(precision_counts),
                    "scenes": scenes,
                    "routeSegments": segments,
                    "visualTransitions": visual_transitions,
                    "unresolved": unresolved,
                    "renderHint": {
                        "component": "PoetRouteMap",
                        "engine": "echarts",
                        "sceneIdField": "id",
                        "coordinateFields": ["lon", "lat"],
                    },
                },
            )
        except SourceDataError as exc:
            return self._source_error(exc)

    def play_poem_scenes(
        self,
        poet: str,
        start_scene_id: str | None = None,
        autoplay: bool = False,
    ) -> dict[str, Any]:
        request, invalid = self._validate_input(
            PlayPoemScenesInput,
            {
                "poet": poet,
                "start_scene_id": start_scene_id,
                "autoplay": autoplay,
            },
        )
        if invalid is not None:
            return invalid
        assert isinstance(request, PlayPoemScenesInput)
        poet = request.poet
        start_scene_id = request.start_scene_id
        autoplay = request.autoplay
        try:
            row, story, work_count, dynasty, hashes, _ = self._poet_context(poet)
            if row is None:
                catalog, _ = self._catalog_rows()
                return self._invalid(
                    f"未知诗人: {poet}",
                    hashes,
                    availablePoets=[item["poet"] for item in catalog],
                )
            if story is None:
                return self._insufficient_route(
                    poet, work_count, dynasty, hashes, mode="scene_playback"
                )
            scenes = [dict(scene) for scene in story.get("scenes", [])]
            scene_ids = [scene["id"] for scene in scenes]
            if start_scene_id is not None and start_scene_id not in scene_ids:
                return self._invalid(
                    f"start_scene_id 不属于 {poet} 的镜头",
                    hashes,
                    poet=poet,
                    startSceneId=start_scene_id,
                    availableSceneIds=scene_ids,
                )
            start_index = scene_ids.index(start_scene_id) if start_scene_id else 0
            return _base_response(
                status="ok",
                source_hashes=hashes,
                method_note=(
                    "播放顺序、停留秒数、诗句、情感与场景图键均来自33号生成数据；"
                    "默认 manual_step，每幕由用户主动进入下一步。"
                ),
                payload={
                    "poet": poet,
                    "dynasty": dynasty,
                    "corpusWorkCount": work_count,
                    "mode": "autoplay" if autoplay else "manual_step",
                    "autoplay": autoplay,
                    "manualStepDefault": True,
                    "pauseAtEachScene": not autoplay,
                    "startSceneId": scene_ids[start_index] if scene_ids else None,
                    "startIndex": start_index,
                    "sceneCount": len(scenes),
                    "scenes": scenes,
                    "controls": ["previous", "next", "play", "pause", "restart"],
                    "renderHint": {
                        "component": "PoemScenePlayer",
                        "engine": "echarts",
                        "advanceDelayField": "read_seconds",
                    },
                },
            )
        except SourceDataError as exc:
            return self._source_error(exc)

    def compare_imagery(
        self,
        terms: list[str] | None = None,
        limit: int = 8,
        chapter_id: str | None = None,
    ) -> dict[str, Any]:
        request, invalid = self._validate_input(
            CompareImageryInput,
            {"terms": terms, "limit": limit, "chapter_id": chapter_id},
        )
        if invalid is not None:
            return invalid
        assert isinstance(request, CompareImageryInput)
        normalized_terms = request.terms
        limit = request.limit
        chapter_id = request.chapter_id
        try:
            snapshot: DatasetSnapshot = self.repository.ensure_dataset(IMAGERY_SPEC)
            data = snapshot.data
            word_by_term = {row["word"]: row for row in data["wordStats"]}
            allowed_terms = list(word_by_term)
            if normalized_terms is not None:
                unknown = [term for term in normalized_terms if term not in word_by_term]
                if unknown:
                    return self._invalid(
                        "terms 只能使用审核后的160词表",
                        snapshot.source_hashes,
                        unknownTerms=unknown,
                        allowedTerms=allowed_terms,
                    )
            chapters = {
                chapter["id"]: chapter
                for chapter in data["historicalLens"]["chapters"]
            }
            if chapter_id is not None and chapter_id not in chapters:
                return self._invalid(
                    f"未知 chapter_id: {chapter_id}",
                    snapshot.source_hashes,
                    availableChapterIds=list(chapters),
                )
            if normalized_terms is None:
                selected_terms = [
                    row["word"] for row in data["topContrasts"][:limit]
                ]
                selection_rule = "actual_top_contrasts"
            else:
                selected_terms = normalized_terms[:limit]
                selection_rule = "requested_terms"
            chapter = chapters.get(chapter_id) if chapter_id else None
            chapter_rankings = {
                row["word"]: row for row in (chapter or {}).get("ranking", [])
            }
            comparisons: list[dict[str, Any]] = []
            for term in selected_terms:
                stats = word_by_term[term]
                evidence = data["evidence"].get(term, {})
                comparisons.append(
                    {
                        "word": term,
                        "category": stats["category"],
                        "higherIn": stats["higherIn"],
                        "deltaSongMinusTang": stats["deltaSongMinusTang"],
                        "absoluteDelta": stats["absoluteDelta"],
                        "tang": stats["tang"],
                        "song": stats["song"],
                        "corpusEvidence": evidence.get("corpus", []),
                        "chapterStats": chapter_rankings.get(term),
                        "chapterEvidence": (
                            evidence.get("chapters", {}).get(chapter_id, [])
                            if chapter_id
                            else []
                        ),
                    }
                )
            return _base_response(
                status="ok",
                source_hashes=snapshot.source_hashes,
                method_note=(
                    "唐宋每万字率、160词白名单、上下文排除和证据均直接来自38号Python生成数据；"
                    "相关差异不解释为历史因果。"
                ),
                payload={
                    "selectionRule": selection_rule,
                    "requestedLimit": limit,
                    "terms": selected_terms,
                    "allowedTermCount": len(allowed_terms),
                    "normalization": data["meta"].get("normalization"),
                    "dynastyAggregates": data.get("dynastyAggregates"),
                    "comparisons": comparisons,
                    "chapter": chapter,
                    "availableChapters": [
                        {
                            "id": item["id"],
                            "title": item["title"],
                            "startYear": item["startYear"],
                            "endYear": item["endYear"],
                        }
                        for item in chapters.values()
                    ],
                    "renderHint": {
                        "component": "ImageryComparison",
                        "engine": "echarts",
                        "rateFields": ["tang.ratePer10k", "song.ratePer10k"],
                    },
                },
            )
        except SourceDataError as exc:
            return self._source_error(exc)
