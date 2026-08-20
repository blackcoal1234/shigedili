"""Offline compiler for the versioned poetry knowledge database.

The deterministic rules baseline is always built first.  Optional LLM
enrichment is an explicit batch operation; it never runs in an HTTP request and
its candidate output is stored alongside (never over) rule evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import sqlite3
import sys
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping
from urllib import error, request

from .knowledge import (
    SCHEMA_VERSION,
    init_schema,
    manifest_path_for,
    sha256_path,
)


PROJECT_ROOT = Path(__file__).resolve().parents[4]
RUNTIME_DIR = PROJECT_ROOT / "apps" / "agent-ui" / ".run"
DEFAULT_SOURCE = PROJECT_ROOT / "data" / "poems.json"
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "output" / "assets" / "knowledge" / "poetry_knowledge.sqlite3"
)
SPLITTER_VERSION = "sentence-punctuation-newline-v1"
PROMPT_VERSION = "poetry-line-analysis-v1"
PROMPT_TEMPLATE = """你是中国古典诗文分析助手。只分析输入原文，不补写史实或作者心理定论。
请返回严格 JSON 对象：{{"lines":[{{"lineId":"...","interpretation":"逐句释义与表达作用，80字以内","imagery":[{{"label":"规范意象","evidence":"必须是原句子串"}}],"emotions":[{{"label":"情感标签","evidence":"必须是原句子串"}}],"confidence":0.0}}]}}。
所有 evidence 必须逐字出现在对应 text 中；不确定时数组留空并降低 confidence。
作品：{dynasty} {poet}《{title}》
待分析行：
{lines_json}
"""

OBJECTIVE_EXCLUDED_CATEGORIES = {"情志", "人物", "空间", "时序"}
MONTH_NUMBER_PREFIX_RE = re.compile(
    r"(?:闰)?(?:正|元|冬|腊|[一二三四五六七八九十百廿卅〇零0-9]{1,4})$"
)
MONTH_TIME_PREFIX_RE = re.compile(r"(?:本|去|每|当|同|次|翌)$")
MONTH_TIME_SUFFIX_RE = re.compile(
    r"^(?:份|朔|晦|以来|之(?:初|末)|(?:初|末)?[一二三四五六七八九十廿卅〇零0-9]{1,3}(?:日|号))"
)
CLOUD_SPEECH_PREFIX_RE = re.compile(
    r"(?:但|只|仅|又|或|乃|皆|咸|俱|尝|自|相|共|谓|称|答|问|报|告|语|闻|传|僧|客|人|者|俗|谚|诗|书|史|古|儒|师|公|君|翁|叟|吏|帝|王|臣|曰)$"
)
WIND_ABSTRACT_SUFFIXES = (
    "流", "雅", "俗", "教", "化", "气", "尚", "范", "采", "骨", "格", "韵", "致", "情",
    "纪", "操", "节", "标", "神", "度", "貌", "规",
)
WIND_ABSTRACT_PREFIX_RE = re.compile(
    r"(?:文|诗|词|世|士|学|家|门|民|国|乡|儒|政|教|仁|礼|古|遗|棘序之)$"
)


class KnowledgeBuildError(RuntimeError):
    """The compiler could not produce a verified snapshot."""


@dataclass(frozen=True)
class LineUnit:
    line_id: str
    poem_id: str
    line_no: int
    stanza_no: int
    text: str
    start_offset: int
    end_offset: int
    line_hash: str


@dataclass(frozen=True)
class ImageryTerm:
    word: str
    category: str
    cluster: str | None
    valence: float
    scale: int
    description: str


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    api_key: str
    model: str
    concurrency: int
    timeout: float = 90.0
    retries: int = 4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_hash(*parts: object, length: int | None = None) -> str:
    digest = hashlib.sha256(
        "\x1f".join(str(part) for part in parts).encode("utf-8")
    ).hexdigest()
    return digest[:length] if length else digest


def stable_poem_id(record: Mapping[str, Any]) -> str:
    source_id = str(record.get("source_poem_id") or "").strip()
    if source_id:
        return source_id
    body = str(record.get("body") or "")
    body_hash = str(record.get("body_hash") or stable_hash(body))
    return "local-" + stable_hash(
        record.get("source_site") or "local",
        record.get("dynasty") or "",
        record.get("poet") or record.get("author") or "",
        body_hash,
        length=24,
    )


def short_search_tokens(text: str) -> list[str]:
    """Return unique case-folded unigrams/bigrams for literal short search."""

    result: list[str] = []
    seen: set[str] = set()
    for run in re.findall(r"[^\W_]+", (text or "").casefold(), flags=re.UNICODE):
        for width in (1, 2):
            for index in range(0, len(run) - width + 1):
                token = run[index:index + width]
                if token not in seen:
                    seen.add(token)
                    result.append(token)
    return result


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def split_poem_lines(body: str, poem_id: str) -> list[LineUnit]:
    """Split on sentence-ending punctuation/newlines and retain exact offsets."""

    text = body or ""
    result: list[LineUnit] = []
    start = 0
    stanza = 1
    blank_newlines = 0
    punctuation = {"。", "！", "？", "!", "?", "；", ";"}

    def append_span(raw_start: int, raw_end: int) -> None:
        nonlocal stanza, blank_newlines
        span_start, span_end = _trim_span(text, raw_start, raw_end)
        if span_start >= span_end:
            blank_newlines += 1
            return
        if blank_newlines >= 2 and result:
            stanza += 1
        blank_newlines = 0
        line_text = text[span_start:span_end]
        line_no = len(result) + 1
        line_hash = stable_hash(line_text)
        line_id = f"{poem_id}:l{line_no:05d}:{line_hash[:12]}"
        result.append(
            LineUnit(
                line_id=line_id,
                poem_id=poem_id,
                line_no=line_no,
                stanza_no=stanza,
                text=line_text,
                start_offset=span_start,
                end_offset=span_end,
                line_hash=line_hash,
            )
        )

    index = 0
    while index < len(text):
        character = text[index]
        if character in punctuation:
            append_span(start, index + 1)
            start = index + 1
        elif character in {"\r", "\n"}:
            append_span(start, index)
            if character == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
                index += 1
            start = index + 1
        index += 1
    append_span(start, len(text))
    return result


def _load_rule_modules() -> tuple[Any, Any]:
    data_path = PROJECT_ROOT / "data"
    if str(data_path) not in sys.path:
        sys.path.insert(0, str(data_path))
    try:
        import classical_emotion_model  # type: ignore
        import spirit_image_dict  # type: ignore
    except ImportError as exc:
        raise KnowledgeBuildError(f"本地分析模块加载失败: {exc}") from exc
    return classical_emotion_model, spirit_image_dict


def objective_imagery_terms() -> list[ImageryTerm]:
    _, lexicon = _load_rule_modules()
    rows = [
        ImageryTerm(
            word=str(row[0]),
            category=str(row[1]),
            cluster=str(row[2]) if row[2] is not None else None,
            valence=float(row[3]),
            scale=int(row[4]),
            description=str(row[5]),
        )
        for row in lexicon.SPIRIT_DICT
        if row[1] not in OBJECTIVE_EXCLUDED_CATEGORIES
        and row[4] is not None
        and bool(row[5])
    ]
    if not rows:
        raise KnowledgeBuildError("客观意象词表不能为空")
    words = [item.word for item in rows]
    if len(words) != len(set(words)):
        raise KnowledgeBuildError("客观意象词表包含重复词")
    return sorted(rows, key=lambda item: (-len(item.word), item.word))


def _imagery_excluded(text: str, start: int, end: int, word: str) -> bool:
    left = text[max(0, start - 8):start]
    right = text[end:min(len(text), end + 8)]
    if word == "月":
        return bool(
            MONTH_NUMBER_PREFIX_RE.search(left)
            or MONTH_TIME_PREFIX_RE.search(left)
            or MONTH_TIME_SUFFIX_RE.match(right)
        )
    if word == "云":
        return bool(CLOUD_SPEECH_PREFIX_RE.search(left))
    if word == "风":
        return bool(
            right.startswith(WIND_ABSTRACT_SUFFIXES)
            or (WIND_ABSTRACT_PREFIX_RE.search(left) and not right.startswith("霜"))
        )
    return False


def scan_imagery(text: str, terms: Iterable[ImageryTerm]) -> list[tuple[int, int, ImageryTerm]]:
    buckets: dict[str, list[ImageryTerm]] = {}
    for term in terms:
        buckets.setdefault(term.word[0], []).append(term)
    result: list[tuple[int, int, ImageryTerm]] = []
    index = 0
    while index < len(text):
        match = next(
            (
                term
                for term in buckets.get(text[index], [])
                if text.startswith(term.word, index)
            ),
            None,
        )
        if match is None:
            index += 1
            continue
        end = index + len(match.word)
        if not _imagery_excluded(text, index, end, match.word):
            result.append((index, end, match))
        index = end
    return result


def _analysis_id(*parts: object) -> str:
    return "a-" + stable_hash(*parts, length=32)


def _mention_id(prefix: str, *parts: object) -> str:
    return prefix + "-" + stable_hash(*parts, length=32)


def _insert_emotions(
    connection: sqlite3.Connection,
    *,
    poem_id: str,
    line_id: str | None,
    profile: Mapping[str, Any],
    run_id: str,
) -> list[str]:
    labels: list[str] = []
    scope = "line" if line_id else "poem"
    confidence = float(profile.get("confidence") or 0.12)
    for row in profile.get("top_emotions") or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        tag_id = str(row["id"])
        label = str(row.get("label") or tag_id)
        evidence = [str(item) for item in row.get("evidence") or []]
        labels.append(label)
        connection.execute(
            "INSERT INTO emotion_mentions(mention_id,target_scope,poem_id,line_id,tag_id,label,family,score,share,valence,arousal,dominance,confidence,evidence,start_offset,end_offset,method,run_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                _mention_id("em", poem_id, line_id or "poem", tag_id, "rules"),
                scope,
                poem_id,
                line_id,
                tag_id,
                label,
                row.get("family"),
                row.get("score"),
                row.get("share"),
                profile.get("valence"),
                profile.get("arousal"),
                profile.get("dominance"),
                confidence,
                json.dumps(evidence, ensure_ascii=False),
                None,
                None,
                "rules",
                run_id,
            ),
        )
    return labels


def _rule_summary(imagery: list[str], emotions: list[str]) -> str:
    clauses: list[str] = []
    if imagery:
        clauses.append("客观意象：" + "、".join(dict.fromkeys(imagery)))
    if emotions:
        clauses.append("词典情感信号：" + "、".join(dict.fromkeys(emotions)))
    if not clauses:
        clauses.append("本地词典信号不足")
    return "；".join(clauses) + "。该基线便于检索，不替代文义赏析。"


def _source_hashes(source: Path) -> dict[str, str]:
    paths = {
        source.relative_to(PROJECT_ROOT).as_posix()
        if source.is_relative_to(PROJECT_ROOT)
        else str(source): source,
        "data/spirit_image_dict.py": PROJECT_ROOT / "data" / "spirit_image_dict.py",
        "data/image_dict.py": PROJECT_ROOT / "data" / "image_dict.py",
        "data/classical_emotion_model.py": PROJECT_ROOT / "data" / "classical_emotion_model.py",
        "data/classical_emotion_lexicon.py": PROJECT_ROOT / "data" / "classical_emotion_lexicon.py",
        "apps/agent-ui/agent/poetry_agent/knowledge.py": Path(__file__).with_name("knowledge.py"),
        "apps/agent-ui/agent/poetry_agent/knowledge_builder.py": Path(__file__),
    }
    return {name: sha256_path(path) for name, path in paths.items() if path.is_file()}


def _load_records(source: Path, *, poet: str | None, limit: int | None) -> list[dict[str, Any]]:
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise KnowledgeBuildError(f"语料读取失败: {source}: {exc}") from exc
    if not isinstance(payload, list):
        raise KnowledgeBuildError("语料顶层必须是数组")
    result: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        author = str(row.get("poet") or row.get("author") or "").strip()
        if poet and author != poet:
            continue
        if not author or not str(row.get("title") or "").strip() or not str(row.get("body") or "").strip():
            continue
        result.append(dict(row))
        if limit is not None and len(result) >= limit:
            break
    return result


def _build_rules_database(
    source: Path,
    work_path: Path,
    *,
    poet: str | None,
    limit: int | None,
) -> dict[str, Any]:
    records = _load_records(source, poet=poet, limit=limit)
    if not records:
        raise KnowledgeBuildError("筛选后没有可构建的诗文")
    if work_path.exists():
        work_path.unlink()
    work_path.parent.mkdir(parents=True, exist_ok=True)
    emotion_model, _ = _load_rule_modules()
    imagery_terms = objective_imagery_terms()
    source_hashes = _source_hashes(source)
    build_id = stable_hash(
        SCHEMA_VERSION,
        SPLITTER_VERSION,
        json.dumps(source_hashes, sort_keys=True),
        poet or "",
        limit or "all",
        length=24,
    )
    run_id = "rules-" + build_id
    generated_at = utc_now()
    connection = sqlite3.connect(work_path)
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=NORMAL")
        init_schema(connection)
        connection.execute(
            "INSERT INTO analysis_runs(run_id,kind,method,model,prompt_version,prompt_hash,input_hash,status,started_at,completed_at,config_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                "baseline",
                "rules",
                None,
                SPLITTER_VERSION,
                stable_hash(SPLITTER_VERSION),
                source_hashes.get(
                    source.relative_to(PROJECT_ROOT).as_posix()
                    if source.is_relative_to(PROJECT_ROOT)
                    else str(source),
                    "",
                ),
                "completed",
                generated_at,
                generated_at,
                json.dumps({"objectiveImageryTerms": len(imagery_terms)}, ensure_ascii=False),
            ),
        )
        line_count = 0
        imagery_count = 0
        emotion_count = 0
        for record_index, record in enumerate(records, start=1):
            poem_id = stable_poem_id(record)
            title = str(record.get("title") or "").strip()
            author = str(record.get("poet") or record.get("author") or "").strip()
            dynasty = str(record.get("dynasty") or "未知").strip() or "未知"
            # Preserve the source text byte-for-byte.  Trimming here would make
            # stored offsets point at a derived string while body_hash still
            # identifies the original corpus record.
            body = str(record.get("body") or "")
            calculated_body_hash = stable_hash(body)
            body_hash = str(record.get("body_hash") or calculated_body_hash)
            if body_hash != calculated_body_hash:
                raise KnowledgeBuildError(
                    f"正文哈希不匹配: {author}《{title}》({poem_id})"
                )
            connection.execute(
                "INSERT INTO poems(poem_id,source_poem_id,title,poet,dynasty,school,genre,body,body_hash,source_site,source_url) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    poem_id,
                    record.get("source_poem_id"),
                    title,
                    author,
                    dynasty,
                    record.get("school"),
                    record.get("genre") or record.get("work_type"),
                    body,
                    body_hash,
                    record.get("source_site"),
                    record.get("source_url"),
                ),
            )
            connection.executemany(
                "INSERT INTO poem_short_tokens(token,poem_id) VALUES(?,?)",
                (
                    (token, poem_id)
                    for token in short_search_tokens(
                        f"{title} {author} {dynasty}"
                    )
                ),
            )
            lines = split_poem_lines(body, poem_id)
            for line in lines:
                connection.execute(
                    "INSERT INTO lines(line_id,poem_id,line_no,stanza_no,text,start_offset,end_offset,line_hash) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        line.line_id, line.poem_id, line.line_no, line.stanza_no,
                        line.text, line.start_offset, line.end_offset, line.line_hash,
                    ),
                )
                connection.executemany(
                    "INSERT INTO line_short_tokens(token,line_id,poem_id) VALUES(?,?,?)",
                    (
                        (token, line.line_id, poem_id)
                        for token in short_search_tokens(line.text)
                    ),
                )
                imagery_labels: list[str] = []
                for local_start, local_end, term in scan_imagery(line.text, imagery_terms):
                    absolute_start = line.start_offset + local_start
                    absolute_end = line.start_offset + local_end
                    imagery_labels.append(term.word)
                    connection.execute(
                        "INSERT INTO imagery_mentions(mention_id,target_scope,poem_id,line_id,tag_id,label,category,matched_text,confidence,evidence,start_offset,end_offset,method,run_id) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            _mention_id("im", poem_id, line.line_id, term.word, absolute_start),
                            "line", poem_id, line.line_id, term.word, term.word,
                            term.category, line.text[local_start:local_end], 0.96,
                            line.text, absolute_start, absolute_end, "rules", run_id,
                        ),
                    )
                    imagery_count += 1
                line_profile = emotion_model.classify_text(line.text, title="")
                emotion_labels = _insert_emotions(
                    connection,
                    poem_id=poem_id,
                    line_id=line.line_id,
                    profile=line_profile,
                    run_id=run_id,
                )
                emotion_count += len(emotion_labels)
                summary = _rule_summary(imagery_labels, emotion_labels)
                connection.execute(
                    "INSERT INTO analyses(analysis_id,poem_id,line_id,kind,summary,interpretation,method,confidence,model,prompt_hash,input_hash,review_status,evidence_json,payload_json,run_id) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        _analysis_id(poem_id, line.line_id, "baseline", "rules"),
                        poem_id,
                        line.line_id,
                        "line_baseline",
                        summary,
                        None,
                        "rules",
                        float(line_profile.get("confidence") or 0.12),
                        None,
                        stable_hash(SPLITTER_VERSION),
                        line.line_hash,
                        "published_rules",
                        json.dumps(
                            {
                                "imagery": imagery_labels,
                                "emotionTerms": line_profile.get("evidence") or [],
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(line_profile, ensure_ascii=False),
                        run_id,
                    ),
                )
                line_count += 1
            poem_profile = emotion_model.classify_text(body, title=title)
            poem_emotions = _insert_emotions(
                connection,
                poem_id=poem_id,
                line_id=None,
                profile=poem_profile,
                run_id=run_id,
            )
            emotion_count += len(poem_emotions)
            connection.execute(
                "INSERT INTO analyses(analysis_id,poem_id,line_id,kind,summary,interpretation,method,confidence,model,prompt_hash,input_hash,review_status,evidence_json,payload_json,run_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    _analysis_id(poem_id, "poem", "emotion", "rules"),
                    poem_id, None, "poem_emotion", str(poem_profile.get("summary") or ""),
                    None, "rules", float(poem_profile.get("confidence") or 0.12),
                    None, stable_hash(SPLITTER_VERSION), body_hash, "published_rules",
                    json.dumps(poem_profile.get("evidence") or [], ensure_ascii=False),
                    json.dumps(poem_profile, ensure_ascii=False), run_id,
                ),
            )
            if record_index % 250 == 0:
                connection.commit()

        connection.execute("DELETE FROM poem_fts")
        connection.execute(
            "INSERT INTO poem_fts(poem_id,title,poet,dynasty,body,analysis_text) "
            "SELECT p.poem_id,p.title,p.poet,p.dynasty,p.body,"
            "COALESCE((SELECT group_concat(COALESCE(a.summary,'') || ' ' || COALESCE(a.interpretation,''),' ') FROM analyses a WHERE a.poem_id=p.poem_id),'') "
            "FROM poems p"
        )
        connection.execute("DELETE FROM line_fts")
        connection.execute(
            "INSERT INTO line_fts(line_id,poem_id,title,poet,dynasty,text,analysis_text) "
            "SELECT l.line_id,p.poem_id,p.title,p.poet,p.dynasty,l.text,"
            "COALESCE((SELECT group_concat(COALESCE(a.summary,'') || ' ' || COALESCE(a.interpretation,''),' ') FROM analyses a WHERE a.poem_id=p.poem_id AND a.line_id=l.line_id),'') "
            "FROM lines l JOIN poems p ON p.poem_id=l.poem_id"
        )
        meta = {
            "schema_version": SCHEMA_VERSION,
            "build_id": build_id,
            "generated_at": generated_at,
            "splitter_version": SPLITTER_VERSION,
            "source_hashes": json.dumps(source_hashes, ensure_ascii=False, sort_keys=True),
            "llm_status": "not_enriched",
            "objective_imagery_term_count": str(len(imagery_terms)),
            "corpus_scope": "full" if poet is None and limit is None else "partial",
            "build_filters": json.dumps(
                {"poet": poet, "limit": limit}, ensure_ascii=False, sort_keys=True
            ),
            "prompt_version": PROMPT_VERSION,
            "prompt_hash": stable_hash(PROMPT_TEMPLATE),
        }
        connection.executemany(
            "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", meta.items()
        )
        connection.commit()
        counts = {
            "poemCount": len(records),
            "lineCount": line_count,
            "imageryMentionCount": imagery_count,
            "emotionMentionCount": emotion_count,
        }
        validate_database(connection, counts)
        return {
            "schemaVersion": SCHEMA_VERSION,
            "buildId": build_id,
            "generatedAt": generated_at,
            "splitterVersion": SPLITTER_VERSION,
            "sourceHashes": source_hashes,
            "analysis": {"rules": "completed", "llm": "not_enriched"},
            **counts,
        }
    finally:
        connection.close()


def validate_database(connection: sqlite3.Connection, expected: Mapping[str, int] | None = None) -> None:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise KnowledgeBuildError(f"SQLite integrity_check 失败: {integrity}")
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        raise KnowledgeBuildError(f"SQLite foreign_key_check 失败: {foreign_keys[:3]}")
    counts = {
        "poemCount": int(connection.execute("SELECT COUNT(*) FROM poems").fetchone()[0]),
        "lineCount": int(connection.execute("SELECT COUNT(*) FROM lines").fetchone()[0]),
    }
    poem_fts = int(connection.execute("SELECT COUNT(*) FROM poem_fts").fetchone()[0])
    line_fts = int(connection.execute("SELECT COUNT(*) FROM line_fts").fetchone()[0])
    poem_short_count = int(
        connection.execute("SELECT COUNT(*) FROM poem_short_tokens").fetchone()[0]
    )
    line_short_count = int(
        connection.execute("SELECT COUNT(*) FROM line_short_tokens").fetchone()[0]
    )
    if (
        poem_fts != counts["poemCount"]
        or line_fts != counts["lineCount"]
        or poem_short_count < counts["poemCount"]
    ):
        raise KnowledgeBuildError(
            "FTS行数不一致: "
            f"poems={counts['poemCount']}/{poem_fts}/{poem_short_count}, "
            f"lines={counts['lineCount']}/{line_fts}/{line_short_count}"
        )
    missing_poem_fts = connection.execute(
        "SELECT poem_id FROM poems EXCEPT SELECT poem_id FROM poem_fts"
    ).fetchone()
    extra_poem_fts = connection.execute(
        "SELECT poem_id FROM poem_fts EXCEPT SELECT poem_id FROM poems"
    ).fetchone()
    missing_line_fts = connection.execute(
        "SELECT line_id FROM lines EXCEPT SELECT line_id FROM line_fts"
    ).fetchone()
    extra_line_fts = connection.execute(
        "SELECT line_id FROM line_fts EXCEPT SELECT line_id FROM lines"
    ).fetchone()
    missing_poem_short = connection.execute(
        "SELECT poem_id FROM poems EXCEPT SELECT poem_id FROM poem_short_tokens"
    ).fetchone()
    extra_poem_short = connection.execute(
        "SELECT poem_id FROM poem_short_tokens EXCEPT SELECT poem_id FROM poems"
    ).fetchone()
    extra_line_short = connection.execute(
        "SELECT line_id FROM line_short_tokens EXCEPT SELECT line_id FROM lines"
    ).fetchone()
    if any(
        (
            missing_poem_fts, extra_poem_fts, missing_line_fts, extra_line_fts,
            missing_poem_short, extra_poem_short, extra_line_short,
        )
    ):
        raise KnowledgeBuildError("FTS实体集合与主表不一致")
    invalid_span = connection.execute(
        "SELECT l.line_id FROM lines l JOIN poems p ON p.poem_id=l.poem_id "
        "WHERE substr(p.body,l.start_offset+1,l.end_offset-l.start_offset)<>l.text "
        "LIMIT 1"
    ).fetchone()
    if invalid_span:
        raise KnowledgeBuildError(f"诗句偏移无法复现原文: {invalid_span[0]}")
    duplicate_source_id = connection.execute(
        "SELECT source_poem_id FROM poems WHERE source_poem_id IS NOT NULL "
        "GROUP BY source_poem_id HAVING COUNT(*)>1 LIMIT 1"
    ).fetchone()
    if duplicate_source_id:
        raise KnowledgeBuildError(f"source_poem_id重复: {duplicate_source_id[0]}")
    if expected:
        for key in ("poemCount", "lineCount"):
            if key in expected and counts[key] != int(expected[key]):
                raise KnowledgeBuildError(f"{key}应为{expected[key]}，实际{counts[key]}")


def _llm_config(concurrency: int) -> LlmConfig:
    values = {
        "base_url": os.getenv("AGENT_LLM_BASE_URL", "").strip(),
        "api_key": os.getenv("AGENT_LLM_API_KEY", "").strip(),
        "model": os.getenv("AGENT_LLM_MODEL", "").strip(),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise KnowledgeBuildError(
            "--llm 需要 AGENT_LLM_BASE_URL/AGENT_LLM_API_KEY/AGENT_LLM_MODEL"
        )
    if not 1 <= concurrency <= 64:
        raise KnowledgeBuildError("--concurrency 必须位于1..64")
    return LlmConfig(concurrency=concurrency, **values)


def _request_llm(
    config: LlmConfig,
    prompt: str,
) -> dict[str, Any]:
    endpoint = config.base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps(
        {
            "model": config.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "你只输出符合要求的JSON。"},
                {"role": "user", "content": prompt},
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(config.retries + 1):
        http_request = request.Request(
            endpoint,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with request.urlopen(http_request, timeout=config.timeout) as response:
                outer = json.loads(response.read().decode("utf-8"))
            content = outer["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise KnowledgeBuildError("LLM content 不是字符串")
            clean = content.strip()
            if clean.startswith("```"):
                clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean, flags=re.I)
            result = json.loads(clean)
            if not isinstance(result, dict):
                raise KnowledgeBuildError("LLM JSON 顶层不是对象")
            return result
        except error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt >= config.retries:
                break
            retry_after = exc.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt
        except (error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError, KnowledgeBuildError) as exc:
            last_error = exc
            if attempt >= config.retries:
                break
            delay = 2 ** attempt
        time.sleep(delay + random.uniform(0, 0.35))
    raise KnowledgeBuildError(
        f"LLM请求失败（已重试）: {type(last_error).__name__}: {last_error}"
    )


def validate_llm_result(
    result: Mapping[str, Any],
    expected_lines: Mapping[str, str],
) -> list[dict[str, Any]]:
    rows = result.get("lines")
    if not isinstance(rows, list):
        raise KnowledgeBuildError("LLM结果缺少 lines 数组")
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            raise KnowledgeBuildError("LLM lines 项不是对象")
        line_id = str(item.get("lineId") or "")
        if line_id not in expected_lines or line_id in seen:
            raise KnowledgeBuildError(f"LLM返回未知或重复 lineId: {line_id}")
        interpretation = str(item.get("interpretation") or "").strip()
        if not interpretation or len(interpretation) > 800:
            raise KnowledgeBuildError(f"{line_id} interpretation 无效")
        if re.search(r"<\s*/?\s*[a-zA-Z][^>]*>", interpretation) or any(
            ord(character) < 32 and character not in "\n\t"
            for character in interpretation
        ):
            raise KnowledgeBuildError(f"{line_id} interpretation 必须是安全纯文本")
        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError) as exc:
            raise KnowledgeBuildError(f"{line_id} confidence 无效") from exc
        if not 0 <= confidence <= 1:
            raise KnowledgeBuildError(f"{line_id} confidence 越界")
        clean_item = {
            "lineId": line_id,
            "interpretation": interpretation,
            "confidence": confidence,
            "imagery": [],
            "emotions": [],
        }
        source = expected_lines[line_id]
        for key in ("imagery", "emotions"):
            values = item.get(key) or []
            if not isinstance(values, list):
                raise KnowledgeBuildError(f"{line_id} {key} 不是数组")
            for value in values:
                if isinstance(value, str):
                    label, evidence = value.strip(), value.strip()
                elif isinstance(value, dict):
                    label = str(value.get("label") or "").strip()
                    evidence = str(value.get("evidence") or "").strip()
                else:
                    raise KnowledgeBuildError(f"{line_id} {key} 项无效")
                if len(label) > 80 or re.search(r"<\s*/?\s*[a-zA-Z][^>]*>", label):
                    raise KnowledgeBuildError(f"{line_id} {key} label 必须是安全纯文本")
                if not label or not evidence or evidence not in source:
                    raise KnowledgeBuildError(f"{line_id} {key} evidence 不是原句子串")
                clean_item[key].append({"label": label, "evidence": evidence})
        validated.append(clean_item)
        seen.add(line_id)
    if seen != set(expected_lines):
        raise KnowledgeBuildError("LLM未覆盖本批全部 lineId")
    return validated


def _llm_task(
    config: LlmConfig,
    *,
    poem: Mapping[str, Any],
    lines: list[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], str, str]:
    lines_payload = [
        {"lineId": row["line_id"], "text": row["text"]} for row in lines
    ]
    prompt = PROMPT_TEMPLATE.format(
        dynasty=poem["dynasty"],
        poet=poem["poet"],
        title=poem["title"],
        lines_json=json.dumps(lines_payload, ensure_ascii=False),
    )
    input_hash = stable_hash(json.dumps(lines_payload, ensure_ascii=False, sort_keys=True))
    expected = {str(row["line_id"]): str(row["text"]) for row in lines}
    validation_error: KnowledgeBuildError | None = None
    for attempt in range(config.retries + 1):
        result = _request_llm(config, prompt)
        try:
            validated = validate_llm_result(result, expected)
            return validated, stable_hash(PROMPT_TEMPLATE), input_hash
        except KnowledgeBuildError as exc:
            validation_error = exc
            if attempt >= config.retries:
                break
            time.sleep((2 ** attempt) + random.uniform(0, 0.35))
    raise KnowledgeBuildError(
        f"LLM语义校验失败（已重试）: {validation_error}"
    )


def enrich_with_llm(database_path: Path, *, concurrency: int) -> dict[str, Any]:
    config = _llm_config(concurrency)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    run_id = "llm-" + stable_hash(
        config.model, PROMPT_VERSION, stable_hash(PROMPT_TEMPLATE), length=24
    )
    started_at = utc_now()
    try:
        init_schema(connection)
        connection.execute(
            "INSERT OR IGNORE INTO analysis_runs(run_id,kind,method,model,prompt_version,prompt_hash,input_hash,status,started_at,completed_at,config_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id, "line_interpretation", "llm", config.model,
                PROMPT_VERSION, stable_hash(PROMPT_TEMPLATE), "per-job", "running",
                started_at, None, json.dumps({"concurrency": concurrency}),
            ),
        )
        tasks: list[tuple[dict[str, Any], list[dict[str, Any]], str]] = []
        for poem_row in connection.execute("SELECT * FROM poems ORDER BY poem_id"):
            poem = dict(poem_row)
            poem_lines = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM lines WHERE poem_id=? ORDER BY line_no", (poem["poem_id"],)
                )
            ]
            for chunk_start in range(0, len(poem_lines), 24):
                chunk = poem_lines[chunk_start:chunk_start + 24]
                if not chunk:
                    continue
                input_hash = stable_hash(
                    json.dumps(
                        [{"lineId": row["line_id"], "text": row["text"]} for row in chunk],
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                job_id = "job-" + stable_hash(run_id, poem["poem_id"], chunk[0]["line_id"], length=32)
                existing = connection.execute(
                    "SELECT status,input_hash FROM analysis_jobs WHERE job_id=?", (job_id,)
                ).fetchone()
                if existing and existing["status"] == "completed" and existing["input_hash"] == input_hash:
                    continue
                connection.execute(
                    "INSERT INTO analysis_jobs(job_id,run_id,poem_id,line_id,input_hash,status,attempts,error,result_json,updated_at) "
                    "VALUES(?,?,?,?,?,'pending',0,NULL,NULL,?) "
                    "ON CONFLICT(job_id) DO UPDATE SET input_hash=excluded.input_hash,status='pending',error=NULL,updated_at=excluded.updated_at",
                    (job_id, run_id, poem["poem_id"], chunk[0]["line_id"], input_hash, utc_now()),
                )
                tasks.append((poem, chunk, job_id))
        connection.commit()
        completed = 0
        failed = 0
        futures: dict[Future[tuple[list[dict[str, Any]], str, str]], tuple[dict[str, Any], list[dict[str, Any]], str]] = {}
        with ThreadPoolExecutor(max_workers=config.concurrency) as executor:
            for poem, lines, job_id in tasks:
                connection.execute(
                    "UPDATE analysis_jobs SET status='running',attempts=attempts+1,updated_at=? WHERE job_id=?",
                    (utc_now(), job_id),
                )
                future = executor.submit(_llm_task, config, poem=poem, lines=lines)
                futures[future] = (poem, lines, job_id)
            connection.commit()
            for future in as_completed(futures):
                poem, lines, job_id = futures[future]
                try:
                    rows, prompt_hash, input_hash = future.result()
                    connection.execute("SAVEPOINT merge_llm_job")
                    line_map = {str(row["line_id"]): row for row in lines}
                    line_ids = list(line_map)
                    placeholders = ",".join("?" for _ in line_ids)
                    if line_ids:
                        connection.execute(
                            f"DELETE FROM analyses WHERE method='llm' AND line_id IN ({placeholders})",
                            line_ids,
                        )
                        connection.execute(
                            f"DELETE FROM imagery_mentions WHERE method='llm' AND line_id IN ({placeholders})",
                            line_ids,
                        )
                        connection.execute(
                            f"DELETE FROM emotion_mentions WHERE method='llm' AND line_id IN ({placeholders})",
                            line_ids,
                        )
                    for item in rows:
                        line = line_map[item["lineId"]]
                        analysis_id = _analysis_id(
                            poem["poem_id"], item["lineId"], "interpretation", "llm", config.model
                        )
                        connection.execute(
                            "INSERT OR REPLACE INTO analyses(analysis_id,poem_id,line_id,kind,summary,interpretation,method,confidence,model,prompt_hash,input_hash,review_status,evidence_json,payload_json,run_id) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                analysis_id, poem["poem_id"], item["lineId"],
                                "line_interpretation", None, item["interpretation"], "llm",
                                item["confidence"], config.model, prompt_hash, input_hash,
                                "candidate", json.dumps(
                                    [entry["evidence"] for key in ("imagery", "emotions") for entry in item[key]],
                                    ensure_ascii=False,
                                ), json.dumps(item, ensure_ascii=False), run_id,
                            ),
                        )
                        for key, table, prefix in (
                            ("imagery", "imagery_mentions", "im"),
                            ("emotions", "emotion_mentions", "em"),
                        ):
                            for entry in item[key]:
                                local_start = str(line["text"]).find(entry["evidence"])
                                absolute_start = int(line["start_offset"]) + local_start
                                common = (
                                    _mention_id(
                                        prefix,
                                        poem["poem_id"],
                                        item["lineId"],
                                        entry["label"],
                                        entry["evidence"],
                                        local_start,
                                        "llm",
                                        config.model,
                                    ),
                                    "line", poem["poem_id"], item["lineId"], entry["label"], entry["label"],
                                )
                                if table == "imagery_mentions":
                                    connection.execute(
                                        "INSERT OR REPLACE INTO imagery_mentions(mention_id,target_scope,poem_id,line_id,tag_id,label,category,matched_text,confidence,evidence,start_offset,end_offset,method,run_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                        (*common, "llm_candidate", entry["evidence"], item["confidence"], entry["evidence"], absolute_start, absolute_start + len(entry["evidence"]), "llm", run_id),
                                    )
                                else:
                                    connection.execute(
                                        "INSERT OR REPLACE INTO emotion_mentions(mention_id,target_scope,poem_id,line_id,tag_id,label,family,score,share,valence,arousal,dominance,confidence,evidence,start_offset,end_offset,method,run_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                        (*common, "llm_candidate", None, None, None, None, None, item["confidence"], entry["evidence"], absolute_start, absolute_start + len(entry["evidence"]), "llm", run_id),
                                    )
                    connection.execute(
                        "UPDATE analysis_jobs SET status='completed',error=NULL,result_json=?,updated_at=? WHERE job_id=?",
                        (json.dumps(rows, ensure_ascii=False), utc_now(), job_id),
                    )
                    connection.execute("RELEASE SAVEPOINT merge_llm_job")
                    completed += 1
                except Exception as exc:
                    try:
                        connection.execute("ROLLBACK TO SAVEPOINT merge_llm_job")
                        connection.execute("RELEASE SAVEPOINT merge_llm_job")
                    except sqlite3.OperationalError:
                        pass
                    connection.execute(
                        "UPDATE analysis_jobs SET status='failed',error=?,updated_at=? WHERE job_id=?",
                        (f"{type(exc).__name__}: {exc}"[:1000], utc_now(), job_id),
                    )
                    failed += 1
                connection.commit()
        status = "completed" if failed == 0 else "partial"
        connection.execute(
            "UPDATE analysis_runs SET status=?,completed_at=? WHERE run_id=?",
            (status, utc_now(), run_id),
        )
        connection.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('llm_status',?)", (status,)
        )
        # Refresh FTS analysis text after candidates are merged.
        connection.execute("DELETE FROM poem_fts")
        connection.execute(
            "INSERT INTO poem_fts(poem_id,title,poet,dynasty,body,analysis_text) "
            "SELECT p.poem_id,p.title,p.poet,p.dynasty,p.body,COALESCE((SELECT group_concat(COALESCE(a.summary,'') || ' ' || COALESCE(a.interpretation,''),' ') FROM analyses a WHERE a.poem_id=p.poem_id),'') FROM poems p"
        )
        connection.execute("DELETE FROM line_fts")
        connection.execute(
            "INSERT INTO line_fts(line_id,poem_id,title,poet,dynasty,text,analysis_text) "
            "SELECT l.line_id,p.poem_id,p.title,p.poet,p.dynasty,l.text,COALESCE((SELECT group_concat(COALESCE(a.summary,'') || ' ' || COALESCE(a.interpretation,''),' ') FROM analyses a WHERE a.poem_id=p.poem_id AND a.line_id=l.line_id),'') FROM lines l JOIN poems p ON p.poem_id=l.poem_id"
        )
        # Short-token indexes cover source text only, so LLM enrichment does
        # not need to rebuild them.
        connection.commit()
        validate_database(connection)
        return {"runId": run_id, "status": status, "completedJobs": completed, "failedJobs": failed}
    finally:
        connection.close()



GUIDE_PROMPT_VERSION = "guide-v1"
GUIDE_PROMPT_TEMPLATE = """你是「诗行万里」展线的驻场向导，为单首诗写一张导读卡。
讲解只基于诗文本身与给定的已核验事实；「来源与故事」讲通行文学史叙述，
一律用通说口吻（如「一般认为」），不虚构史料出处、页码或具体日期，不写作者心理定论。
只输出 JSON 对象：{{"summary":"一句话讲解，30字以内","guide":"讲解正文150-240字，向导口吻，先给画面再点手法","origin":"创作来源与故事80-160字，开头须注明「通说」","confidence":0.0}}
作品：{dynasty} {poet}《{title}》
已核验事实：{facts}
诗文：
{body}
"""


def _request_guide(config: LlmConfig, poem: dict, facts_text: str) -> dict:
    prompt = GUIDE_PROMPT_TEMPLATE.format(
        dynasty=poem.get("dynasty") or "",
        poet=poem.get("poet") or "",
        title=poem.get("title") or "",
        facts=facts_text or "（无核验作年作地，只讲诗本身）",
        body=poem.get("body") or "",
    )
    result = _request_llm(config, prompt)
    for field, limit in (("summary", 60), ("guide", 400), ("origin", 300)):
        value = result.get(field)
        if not isinstance(value, str) or not value.strip():
            raise KnowledgeBuildError(f"poem_guide 缺少 {field}")
        result[field] = value.strip()[:limit]
    confidence = result.get("confidence")
    try:
        result["confidence"] = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        result["confidence"] = 0.3
    return result


def enrich_guides_with_llm(database_path: Path, *, concurrency: int, facts=None) -> dict:
    """为每首诗生成「讲解/来源/故事」导读卡（method=llm，llm_candidate 待审）。

    facts: (诗人, 诗题) -> 已核验事实描述；缺省视为无核验事实。
    幂等：job 表按 input_hash 跳过已完成；同诗旧 guide 行先删后插。
    """
    config = _llm_config(concurrency)
    facts = facts or {}
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    prompt_hash = stable_hash(GUIDE_PROMPT_TEMPLATE)
    run_id = "guide-" + stable_hash(config.model, GUIDE_PROMPT_VERSION, prompt_hash, length=24)
    started_at = utc_now()
    try:
        init_schema(connection)
        connection.execute(
            "INSERT OR IGNORE INTO analysis_runs(run_id,kind,method,model,prompt_version,prompt_hash,input_hash,status,started_at,completed_at,config_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id, "poem_guide", "llm", config.model,
                GUIDE_PROMPT_VERSION, prompt_hash, "per-poem", "running",
                started_at, None,
                json.dumps({"concurrency": concurrency, "facts": "provided" if facts else "none"}),
            ),
        )
        tasks = []
        preserved = 0
        for poem_row in connection.execute("SELECT * FROM poems ORDER BY poem_id"):
            poem = dict(poem_row)
            # 保护他方卡片：已有其他模型（如助手手写）的导读时不覆盖
            existing_guide = connection.execute(
                "SELECT model FROM analyses WHERE poem_id=? AND kind='poem_guide'",
                (poem["poem_id"],),
            ).fetchone()
            if existing_guide and existing_guide["model"] != config.model:
                preserved += 1
                continue
            facts_text = facts.get((poem.get("poet") or "", poem.get("title") or ""), "")
            input_hash = stable_hash(
                json.dumps(
                    {"poemId": poem["poem_id"], "body": poem.get("body") or "", "facts": facts_text},
                    ensure_ascii=False, sort_keys=True,
                )
            )
            job_id = "guide-job-" + stable_hash(run_id, poem["poem_id"], length=32)
            existing = connection.execute(
                "SELECT status,input_hash FROM analysis_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if existing and existing["status"] == "completed" and existing["input_hash"] == input_hash:
                continue
            connection.execute(
                "INSERT INTO analysis_jobs(job_id,run_id,poem_id,line_id,input_hash,status,attempts,error,result_json,updated_at) "
                "VALUES(?,?,?,?,?,'pending',0,NULL,NULL,?) "
                "ON CONFLICT(job_id) DO UPDATE SET input_hash=excluded.input_hash,status='pending',error=NULL,updated_at=excluded.updated_at",
                (job_id, run_id, poem["poem_id"], None, input_hash, utc_now()),
            )
            tasks.append((poem, facts_text, input_hash, job_id))
        connection.commit()
        completed = 0
        failed = 0
        futures = {}
        with ThreadPoolExecutor(max_workers=config.concurrency) as executor:
            for poem, facts_text, input_hash, job_id in tasks:
                connection.execute(
                    "UPDATE analysis_jobs SET status='running',attempts=attempts+1,updated_at=? WHERE job_id=?",
                    (utc_now(), job_id),
                )
                futures[executor.submit(_request_guide, config, poem, facts_text)] = (
                    poem, facts_text, input_hash, job_id,
                )
            connection.commit()
            for future in as_completed(futures):
                poem, facts_text, input_hash, job_id = futures[future]
                connection.execute("SAVEPOINT merge_guide_job")
                try:
                    result = future.result()
                    analysis_id = _analysis_id(poem["poem_id"], "poem", "guide", "llm", run_id)
                    connection.execute(
                        "DELETE FROM analyses WHERE poem_id=? AND kind='poem_guide'",
                        (poem["poem_id"],),
                    )
                    connection.execute(
                        "INSERT INTO analyses(analysis_id,poem_id,line_id,kind,summary,interpretation,method,confidence,model,prompt_hash,input_hash,review_status,evidence_json,payload_json,run_id) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            analysis_id, poem["poem_id"], None, "poem_guide",
                            result["summary"], result["guide"], "llm", result["confidence"],
                            config.model, prompt_hash, input_hash, "llm_candidate",
                            json.dumps(
                                ([{"type": "verified_fact", "text": facts_text}] if facts_text else []),
                                ensure_ascii=False,
                            ),
                            json.dumps(
                                {
                                    "origin": result["origin"],
                                    "promptVersion": GUIDE_PROMPT_VERSION,
                                    "note": "导读与故事为模型生成的通说叙述（llm_candidate），非人工考据",
                                },
                                ensure_ascii=False,
                            ),
                            run_id,
                        ),
                    )
                    connection.execute(
                        "UPDATE analysis_jobs SET status='completed',error=NULL,result_json=?,updated_at=? WHERE job_id=?",
                        (json.dumps(result, ensure_ascii=False), utc_now(), job_id),
                    )
                    connection.execute("RELEASE SAVEPOINT merge_guide_job")
                    completed += 1
                except Exception as exc:
                    try:
                        connection.execute("ROLLBACK TO SAVEPOINT merge_guide_job")
                        connection.execute("RELEASE SAVEPOINT merge_guide_job")
                    except sqlite3.OperationalError:
                        pass
                    connection.execute(
                        "UPDATE analysis_jobs SET status='failed',error=?,updated_at=? WHERE job_id=?",
                        (f"{type(exc).__name__}: {exc}"[:1000], utc_now(), job_id),
                    )
                    failed += 1
                connection.commit()
        status = "completed" if failed == 0 else "partial"
        connection.execute(
            "UPDATE analysis_runs SET status=?,completed_at=? WHERE run_id=?",
            (status, utc_now(), run_id),
        )
        connection.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('guide_status',?)", (status,)
        )
        connection.execute("DELETE FROM poem_fts")
        connection.execute(
            "INSERT INTO poem_fts(poem_id,title,poet,dynasty,body,analysis_text) "
            "SELECT p.poem_id,p.title,p.poet,p.dynasty,p.body,COALESCE((SELECT group_concat(COALESCE(a.summary,'') || ' ' || COALESCE(a.interpretation,''),' ') FROM analyses a WHERE a.poem_id=p.poem_id),'') FROM poems p"
        )
        connection.commit()
        validate_database(connection)
        return {"runId": run_id, "status": status, "completedJobs": completed, "failedJobs": failed, "preservedForeignGuides": preserved}
    finally:
        connection.close()

def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _database_summary(path: Path, source_hashes: Mapping[str, str]) -> dict[str, Any]:
    connection = sqlite3.connect(path)
    try:
        validate_database(connection)
        meta = dict(connection.execute("SELECT key,value FROM meta"))
        return {
            "schemaVersion": SCHEMA_VERSION,
            "buildId": meta.get("build_id"),
            "generatedAt": meta.get("generated_at"),
            "splitterVersion": meta.get("splitter_version"),
            "sourceHashes": dict(source_hashes),
            "analysis": {
                "rules": "completed",
                "llm": meta.get("llm_status", "not_enriched"),
            },
            "poemCount": connection.execute("SELECT COUNT(*) FROM poems").fetchone()[0],
            "lineCount": connection.execute("SELECT COUNT(*) FROM lines").fetchone()[0],
            "analysisCount": connection.execute("SELECT COUNT(*) FROM analyses").fetchone()[0],
        }
    finally:
        connection.close()


def _work_database_matches(
    path: Path,
    *,
    source_hashes: Mapping[str, str],
    filters: Mapping[str, Any],
) -> bool:
    if not path.is_file():
        return False
    connection = sqlite3.connect(path)
    try:
        meta = dict(connection.execute("SELECT key,value FROM meta"))
        return (
            meta.get("schema_version") == SCHEMA_VERSION
            and json.loads(meta.get("source_hashes", "{}")) == dict(source_hashes)
            and json.loads(meta.get("build_filters", "{}")) == dict(filters)
        )
    except (sqlite3.Error, json.JSONDecodeError, TypeError):
        return False
    finally:
        connection.close()


def _replace_database(source: Path, destination: Path, timeout: float = 8.0) -> None:
    """Publish after every SQLite handle is closed; tolerate brief Windows readers."""

    deadline = time.monotonic() + timeout
    delay = 0.05
    while True:
        try:
            os.replace(source, destination)
            return
        except PermissionError as exc:
            if time.monotonic() >= deadline:
                raise KnowledgeBuildError(
                    "知识库发布被正在读取的进程占用；请停止 Agent 服务后重试"
                ) from exc
            time.sleep(delay)
            delay = min(delay * 1.8, 0.75)


def _build_knowledge_base_unlocked(
    *,
    source: Path = DEFAULT_SOURCE,
    output: Path = DEFAULT_OUTPUT,
    limit: int | None = None,
    poet: str | None = None,
    rebuild: bool = False,
    use_llm: bool = False,
    concurrency: int = 32,
) -> dict[str, Any]:
    source = Path(source).expanduser().resolve()
    output = Path(output).expanduser().resolve()
    if limit is not None and (isinstance(limit, bool) or limit < 1):
        raise KnowledgeBuildError("--limit 必须是正整数")
    if not source.is_file():
        raise KnowledgeBuildError(f"语料不存在: {source}")
    if (limit is not None or poet is not None) and output == DEFAULT_OUTPUT.resolve():
        raise KnowledgeBuildError(
            "局部构建不能覆盖正式知识库；请用 --output 指定独立的 SQLite 文件"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    work_path = output.with_name(f".{output.name}.building")
    if rebuild:
        work_path.unlink(missing_ok=True)

    source_hashes = _source_hashes(source)
    manifest = manifest_path_for(output)
    filters = {"poet": poet, "limit": limit}
    existing_current = False
    old: dict[str, Any] = {}
    if output.is_file() and manifest.is_file() and not rebuild:
        try:
            old = json.loads(manifest.read_text(encoding="utf-8-sig"))
            existing_current = (
                old.get("schemaVersion") == SCHEMA_VERSION
                and old.get("sourceHashes") == source_hashes
                and old.get("filters") == filters
                and old.get("database") == output.name
                and isinstance(old.get("databaseSha256"), str)
                and sha256_path(output) == old.get("databaseSha256")
                and _work_database_matches(
                    output, source_hashes=source_hashes, filters=filters
                )
            )
        except (OSError, json.JSONDecodeError, TypeError):
            existing_current = False

    if existing_current and not use_llm:
        # A verified immutable snapshot with identical inputs needs no rewrite.
        _database_summary(output, source_hashes)
        return old

    resume_work = (
        not rebuild
        and _work_database_matches(
            work_path, source_hashes=source_hashes, filters=filters
        )
    )
    if resume_work:
        summary = _database_summary(work_path, source_hashes)
    elif existing_current:
        work_path.unlink(missing_ok=True)
        shutil.copy2(output, work_path)
        summary = _database_summary(work_path, source_hashes)
    else:
        work_path.unlink(missing_ok=True)
        summary = _build_rules_database(
            source, work_path, poet=poet, limit=limit
        )

    if use_llm:
        llm_summary = enrich_with_llm(work_path, concurrency=concurrency)
        summary["analysis"] = {"rules": "completed", "llm": llm_summary["status"]}
        summary["llmRun"] = llm_summary

    connection = sqlite3.connect(work_path)
    try:
        validate_database(connection)
        summary.update(
            {
                "poemCount": connection.execute("SELECT COUNT(*) FROM poems").fetchone()[0],
                "lineCount": connection.execute("SELECT COUNT(*) FROM lines").fetchone()[0],
                "analysisCount": connection.execute("SELECT COUNT(*) FROM analyses").fetchone()[0],
            }
        )
    finally:
        connection.close()
    _replace_database(work_path, output)
    manifest_payload = {
        **summary,
        "schemaVersion": SCHEMA_VERSION,
        "database": output.name,
        "databaseSha256": sha256_path(output),
        "sourceHashes": source_hashes,
        "filters": filters,
        "generatedAt": utc_now(),
    }
    _atomic_json(manifest, manifest_payload)
    return manifest_payload


def build_knowledge_base(
    *,
    source: Path = DEFAULT_SOURCE,
    output: Path = DEFAULT_OUTPUT,
    limit: int | None = None,
    poet: str | None = None,
    rebuild: bool = False,
    use_llm: bool = False,
    concurrency: int = 32,
) -> dict[str, Any]:
    """Serialize builders per destination while keeping reader queries independent."""

    resolved_output = Path(output).expanduser().resolve()
    lock_path = RUNTIME_DIR / (
        "knowledge-build-" + stable_hash(resolved_output, length=24) + ".lock"
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if not lock_path.exists():
        try:
            lock_path.write_bytes(b"0")
        except FileExistsError:
            pass
    handle = lock_path.open("r+b")
    try:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise KnowledgeBuildError(
                f"已有知识库构建正在运行: {resolved_output}"
            ) from exc
        try:
            return _build_knowledge_base_unlocked(
                source=source,
                output=resolved_output,
                limit=limit,
                poet=poet,
                rebuild=rebuild,
                use_llm=use_llm,
                concurrency=concurrency,
            )
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
