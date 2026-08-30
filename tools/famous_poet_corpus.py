"""Build and validate the full-text corpus for the canonical famous-poet roster.

Canonical text is already the normalized display authority. Its stable work
identity therefore hashes that exact NFC/line-ending-normalized text; OpenCC is
used only to match and deduplicate upstream variants, never to rewrite a
canonical identity.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import subprocess
import tempfile
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Protocol
from urllib.parse import quote


SCHEMA_VERSION = "1.1"
MANIFEST_VERSION = 2
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CANONICAL = Path("data/poems.json")
DEFAULT_SOURCE_ROOT = Path(".cache/chinese-poetry")
DEFAULT_OUTPUT = Path("data/analysis/famous_poets_full.jsonl.gz")
DEFAULT_MANIFEST = Path("data/analysis/famous_poets_full_manifest.json")
UPSTREAM_REPO_URL = "https://github.com/chinese-poetry/chinese-poetry"
UPSTREAM_LICENSE = "MIT"

HASH_DEFINITION = {
    "canonical_sha256": "SHA-256 of the canonical file bytes",
    "output_sha256": "SHA-256 of the deterministic gzip file bytes",
    "normalized_body_hash": (
        "SHA-256 of normalized canonical display body for canonical-matched records; "
        "SHA-256 of normalized OpenCC t2s analysis body for upstream-only records"
    ),
    "dedupe_body_hash": (
        "SHA-256 of normalized OpenCC t2s body; used only as a candidate key, "
        "and never to merge distinct canonical records"
    ),
    "work_id": (
        "fw_ plus the first 24 hex characters of SHA-256(poet + NUL + "
        "normalized_body_hash)"
    ),
}

REQUIRED_FIELDS = {
    "schema_version",
    "work_id",
    "poet",
    "author",
    "person_period",
    "work_dynasty",
    "source_dynasty_raw",
    "title",
    "body",
    "title_original",
    "body_original",
    "body_hash",
    "normalized_body_hash",
    "dedupe_body_hash",
    "body_original_hash",
    "source_site",
    "source_url",
    "source_dataset",
    "source_file",
    "source_revision",
    "source_work_id",
    "corpus_tier",
    "preferred_display",
    "canonical_match",
    "canonical_gushiwen_id",
    "variant_group_id",
    "sources",
}

PERIOD_OVERRIDES = {
    "李煜": "五代·南唐",
    "欧阳炯": "五代·前后蜀",
    "韦庄": "唐末·前蜀",
}
TRANSITION_PERIODS = frozenset(PERIOD_OVERRIDES.values())


class Converter(Protocol):
    def convert(self, text: str, config: str) -> str: ...


class _OpenCCConverter:
    def __init__(self) -> None:
        try:
            from opencc import OpenCC
        except ImportError as exc:
            raise RuntimeError(
                "构建全集需要 opencc-python-reimplemented==0.1.7；"
                "请先安装 requirements.txt。"
            ) from exc
        self._converters = {"s2t": OpenCC("s2t"), "t2s": OpenCC("t2s")}

    def convert(self, text: str, config: str) -> str:
        return self._converters[config].convert(text)


@dataclass(frozen=True)
class SourceFile:
    path: Path
    relative_path: str
    dataset: str
    work_dynasty: str
    source_dynasty_raw: str


_SOURCE_PATTERNS = (
    ("全唐诗", re.compile(r"^poet\.tang\.\d+\.json$"), "poet.tang", "唐"),
    ("全唐诗", re.compile(r"^poet\.song\.\d+\.json$"), "poet.song", "宋"),
    ("宋词", re.compile(r"^ci\.song\.\d+\.json$"), "ci.song", "宋"),
)


def normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", text).strip()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _work_id(poet: str, normalized_body_hash: str) -> str:
    return "fw_" + _sha256_text(f"{poet}\0{normalized_body_hash}")[:24]


def _variant_group_id(poet: str, simplified_title: str) -> str:
    return "vg_" + _sha256_text(f"{poet}\0{normalize_text(simplified_title)}")[:24]


def _path_label(path: Path | str) -> str:
    """Use stable repo-relative labels for paths inside this checkout."""
    path = Path(path)
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _json_bytes(value: Any, *, newline: bool = False) -> bytes:
    suffix = "\n" if newline else ""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + suffix).encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def atomic_dump_json(path: Path | str, value: Any) -> None:
    """Atomically stream compact UTF-8 JSON to ``path`` with a final newline."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                value,
                handle,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _gzip_jsonl(rows: Iterable[dict[str, Any]]) -> bytes:
    import io

    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as handle:
        for row in rows:
            handle.write(_json_bytes(row, newline=True))
    return buffer.getvalue()


def discover_source_files(source_root: Path | str) -> list[SourceFile]:
    root = Path(source_root)
    found: list[SourceFile] = []
    for directory, pattern, dataset, dynasty in _SOURCE_PATTERNS:
        parent = root / directory
        if not parent.is_dir():
            continue
        for path in parent.iterdir():
            if path.is_file() and pattern.fullmatch(path.name):
                relative = path.relative_to(root).as_posix()
                found.append(SourceFile(path, relative, dataset, dynasty, dataset.rsplit(".", 1)[-1]))
    return sorted(found, key=lambda item: item.relative_path)


def _valid_matched_file(relative_path: Any) -> bool:
    if not isinstance(relative_path, str) or "\\" in relative_path:
        return False
    for directory, pattern, _dataset, _dynasty in _SOURCE_PATTERNS:
        prefix = f"{directory}/"
        if relative_path.startswith(prefix) and "/" not in relative_path[len(prefix):]:
            if pattern.fullmatch(relative_path[len(prefix):]) is not None:
                return True
    return False


def _iter_json_array(path: Path, chunk_size: int = 65536) -> Iterator[Any]:
    """Incrementally decode a top-level JSON array without loading the file."""
    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8-sig") as handle:
        buffer = ""
        eof = False

        def fill() -> None:
            nonlocal buffer, eof
            chunk = handle.read(chunk_size)
            if chunk:
                buffer += chunk
            else:
                eof = True

        fill()
        while not buffer.strip() and not eof:
            fill()
        buffer = buffer.lstrip()
        if not buffer.startswith("["):
            raise ValueError(f"上游文件不是 JSON 数组: {path}")
        buffer = buffer[1:]
        expecting_value = True
        has_values = False
        while True:
            buffer = buffer.lstrip()
            while not buffer and not eof:
                fill()
                buffer = buffer.lstrip()
            if not buffer:
                raise ValueError(f"上游 JSON 数组未闭合: {path}")
            if buffer.startswith("]"):
                if expecting_value and has_values:
                    raise ValueError(f"上游 JSON 数组不允许尾逗号: {path}")
                buffer = buffer[1:]
                while not eof:
                    fill()
                if buffer.strip():
                    raise ValueError(f"上游 JSON 数组后存在尾随内容: {path}")
                return
            if not expecting_value:
                if not buffer.startswith(","):
                    raise ValueError(f"上游 JSON 数组缺少逗号: {path}")
                buffer = buffer[1:]
                expecting_value = True
                continue
            while True:
                try:
                    value, end = decoder.raw_decode(buffer)
                    token_may_continue = end == len(buffer) or (
                        end < len(buffer) and buffer[end] not in " \t\r\n,]"
                    )
                    if token_may_continue and not eof:
                        fill()
                        continue
                    break
                except json.JSONDecodeError:
                    if eof:
                        raise ValueError(f"无法解析上游 JSON: {path}") from None
                    fill()
            yield value
            buffer = buffer[end:]
            expecting_value = False
            has_values = True
            buffer = buffer.lstrip()
            while not buffer and not eof:
                fill()
                buffer = buffer.lstrip()
            if buffer.startswith("]"):
                buffer = buffer[1:]
                while not eof:
                    fill()
                if buffer.strip():
                    raise ValueError(f"上游 JSON 数组后存在尾随内容: {path}")
                return


def _load_canonical(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, list):
        raise ValueError(f"canonical 必须是 JSON 数组: {path}")
    return [row for row in value if isinstance(row, dict)]


def _canonical_author(row: dict[str, Any]) -> str:
    return normalize_text(row.get("author") or row.get("poet"))


def _build_aliases(roster: set[str], converter: Converter) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for poet in sorted(roster):
        for alias in {poet, converter.convert(poet, "s2t"), converter.convert(poet, "t2s")}:
            alias = normalize_text(alias)
            existing = aliases.get(alias)
            if existing is not None and existing != poet:
                raise ValueError(f"作者别名冲突: {alias!r} 同时对应 {existing!r} 与 {poet!r}")
            aliases[alias] = poet
    return aliases


def _derive_periods(rows: list[dict[str, Any]], roster: set[str]) -> dict[str, str]:
    dynasty_counts: dict[str, Counter[str]] = {poet: Counter() for poet in roster}
    for row in rows:
        poet = _canonical_author(row)
        dynasty = normalize_text(row.get("dynasty"))
        if poet in roster and dynasty in {"唐", "宋"}:
            dynasty_counts[poet][dynasty] += 1
    result: dict[str, str] = {}
    for poet in sorted(roster):
        if poet in PERIOD_OVERRIDES:
            result[poet] = PERIOD_OVERRIDES[poet]
        elif dynasty_counts[poet]:
            result[poet] = sorted(dynasty_counts[poet].items(), key=lambda pair: (-pair[1], pair[0]))[0][0]
        else:
            result[poet] = "未知"
    return result


def _dataset_allowed(person_period: str, dataset: str) -> bool:
    if person_period == "唐" or person_period in TRANSITION_PERIODS:
        return dataset in {"poet.tang", "ci.song"}
    if person_period == "宋":
        return dataset in {"poet.song", "ci.song"}
    return True


def _source_entry(
    *,
    site: str,
    url: str,
    dataset: str,
    source_file: str,
    revision: str,
    work_id: str,
    title_original: str,
    body_original: str,
    body_hash: Any,
    dynasty_raw: str,
) -> dict[str, Any]:
    return {
        "body_hash": body_hash,
        "body_original": body_original,
        "body_original_hash": _sha256_text(body_original),
        "source_dataset": dataset,
        "source_dynasty_raw": dynasty_raw,
        "source_file": source_file,
        "source_revision": revision,
        "source_site": site,
        "source_url": url,
        "source_work_id": work_id,
        "title_original": title_original,
    }


def _source_signature(poet: str, source: dict[str, Any]) -> tuple[Any, ...]:
    return (
        poet,
        source.get("source_dataset"),
        source.get("source_file"),
        source.get("source_work_id"),
        source.get("title_original"),
        source.get("body_original"),
        source.get("body_original_hash"),
        source.get("body_hash"),
        source.get("source_revision"),
        source.get("source_site"),
        source.get("source_url"),
        source.get("source_dynasty_raw"),
    )


def _make_row(
    *,
    poet: str,
    person_period: str,
    work_dynasty: str,
    source_dynasty_raw: str,
    title_original: str,
    body_original: str,
    source_site: str,
    source_url: str,
    source_dataset: str,
    source_file: str,
    source_revision: str,
    source_work_id: str,
    canonical_id: str | None,
    body_hash_value: Any,
    converter: Converter,
) -> dict[str, Any]:
    analysis_title = normalize_text(converter.convert(title_original, "t2s"))
    analysis_body = normalize_text(converter.convert(body_original, "t2s"))
    is_canonical = source_dataset == "canonical"
    # OpenCC can make lossy lexical substitutions (for example 射覆 -> 射复).
    # Canonical display text therefore remains the identity input; the OpenCC
    # form is kept as a separate candidate key for upstream deduplication.
    title = title_original if is_canonical else analysis_title
    body = body_original if is_canonical else analysis_body
    identity_body_hash = _sha256_text(body)
    dedupe_body_hash = _sha256_text(analysis_body)
    source = _source_entry(
        site=source_site,
        url=source_url,
        dataset=source_dataset,
        source_file=source_file,
        revision=source_revision,
        work_id=source_work_id,
        title_original=title_original,
        body_original=body_original,
        body_hash=body_hash_value,
        dynasty_raw=source_dynasty_raw,
    )
    return {
        "author": poet,
        "body": body,
        "body_hash": body_hash_value,
        "body_original": body_original,
        "body_original_hash": _sha256_text(body_original),
        "canonical_gushiwen_id": canonical_id,
        "canonical_match": is_canonical,
        "corpus_tier": "canonical" if is_canonical else "upstream_full",
        "dedupe_body_hash": dedupe_body_hash,
        "normalized_body_hash": identity_body_hash,
        "person_period": person_period,
        "poet": poet,
        "preferred_display": True,
        "schema_version": SCHEMA_VERSION,
        "source_dataset": source_dataset,
        "source_dynasty_raw": source_dynasty_raw,
        "source_file": source_file,
        "source_revision": source_revision,
        "source_site": source_site,
        "source_url": source_url,
        "source_work_id": source_work_id,
        "sources": [source],
        "title": title,
        "title_original": title_original,
        "variant_group_id": _variant_group_id(poet, title),
        "work_dynasty": work_dynasty,
        "work_id": _work_id(poet, identity_body_hash),
    }


def _merge_source(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    existing["sources"].extend(incoming["sources"])
    existing["sources"].sort(key=lambda source: _json_bytes(source))
    if incoming["canonical_match"]:
        existing["canonical_match"] = True
        if not existing.get("canonical_gushiwen_id"):
            existing["canonical_gushiwen_id"] = incoming["canonical_gushiwen_id"]


def _select_canonical_dedupe_target(
    candidates: list[dict[str, Any]], incoming: dict[str, Any]
) -> dict[str, Any] | None:
    """Return a canonical target only when OpenCC matching is unambiguous."""
    if not candidates:
        return None
    for field in ("body_original_hash", "normalized_body_hash", "variant_group_id"):
        matches = [row for row in candidates if row.get(field) == incoming.get(field)]
        if len(matches) == 1:
            return matches[0]
    return candidates[0] if len(candidates) == 1 else None


def _record_counts(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    dimensions = {
        "dataset": "source_dataset",
        "poet": "poet",
        "person_period": "person_period",
        "work_dynasty": "work_dynasty",
    }
    return {
        name: dict(sorted(Counter(str(row.get(field, "")) for row in rows).items()))
        for name, field in dimensions.items()
    }


def _git_checkout_revision(source_root: Path, *, required: bool) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "--show-toplevel", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        if required:
            raise RuntimeError(f"无法读取上游 Git checkout revision: {source_root}") from exc
        return None
    lines = result.stdout.splitlines()
    if len(lines) != 2 or Path(lines[0]).resolve() != source_root.resolve():
        if required:
            raise RuntimeError(f"source_root 必须精确等于 Git checkout root: {source_root}")
        return None
    return lines[1].strip() or None


def _git_revision(source_root: Path) -> str:
    revision = _git_checkout_revision(source_root, required=True)
    if revision is None:
        raise RuntimeError(f"无法读取上游 Git checkout revision: {source_root}")
    return revision


def _try_git_revision(source_root: Path) -> str | None:
    return _git_checkout_revision(source_root, required=False)


def _git_target_state_errors(
    source_root: Path,
    source_files: list[SourceFile],
    revision: str,
) -> list[str]:
    errors: list[str] = []
    try:
        tree = subprocess.run(
            [
                "git",
                "-c",
                "core.quotepath=false",
                "-C",
                str(source_root),
                "ls-tree",
                "-r",
                "--name-only",
                revision,
                "--",
                "全唐诗",
                "宋词",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return [f"无法检查 Git HEAD numeric source files: {exc}"]
    head_files = sorted(path for path in tree.stdout.splitlines() if _valid_matched_file(path))
    worktree_files = [source_file.relative_path for source_file in source_files]
    if head_files != worktree_files:
        errors.append("Git HEAD 与工作树 numeric source files 列表不一致")
    targets = sorted(set(head_files) | set(worktree_files))
    if targets:
        try:
            status = subprocess.run(
                [
                    "git",
                    "-c",
                    "core.quotepath=false",
                    "-C",
                    str(source_root),
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                    "--",
                    *targets,
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"无法检查工作树 numeric source files: {exc}")
        else:
            if status.stdout.strip():
                errors.append("工作树 numeric source files 存在修改或未跟踪文件")
    return errors


def build_corpus(
    canonical_path: Path | str = DEFAULT_CANONICAL,
    source_root: Path | str = DEFAULT_SOURCE_ROOT,
    output_path: Path | str = DEFAULT_OUTPUT,
    manifest_path: Path | str = DEFAULT_MANIFEST,
    source_revision: str | None = None,
    *,
    converter: Converter | None = None,
) -> dict[str, Any]:
    canonical_path = Path(canonical_path)
    source_root = Path(source_root)
    output_path = Path(output_path)
    manifest_path = Path(manifest_path)
    converter = converter or _OpenCCConverter()
    source_files = discover_source_files(source_root)
    requested_revision = normalize_text(source_revision) if source_revision is not None else None
    checkout_revision = _try_git_revision(source_root)
    if checkout_revision is not None:
        if requested_revision is not None and requested_revision != checkout_revision:
            raise RuntimeError(
                f"显式 source revision 与 source_root Git HEAD 不一致: "
                f"{requested_revision} != {checkout_revision}"
            )
        revision = checkout_revision
        git_errors = _git_target_state_errors(source_root, source_files, revision)
        if git_errors:
            raise RuntimeError("; ".join(git_errors))
    elif requested_revision is None:
        revision = _git_revision(source_root)
    else:
        if (source_root / ".git").exists():
            raise RuntimeError(f"无法严格验证 source_root Git checkout: {source_root}")
        revision = requested_revision
    if not revision:
        raise ValueError("source revision 不能为空")

    canonical_bytes = canonical_path.read_bytes()
    canonical_rows = _load_canonical(canonical_path)
    roster = {_canonical_author(row) for row in canonical_rows}
    roster.discard("")
    if not roster:
        raise ValueError("canonical 中没有有效作者")
    aliases = _build_aliases(roster, converter)
    periods = _derive_periods(canonical_rows, roster)

    records: dict[str, dict[str, Any]] = {}
    canonical_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    canonical_by_dedupe: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    upstream_by_dedupe: dict[tuple[str, str], dict[str, Any]] = {}
    canonical_count = 0
    empty_skipped = 0
    accepted_inputs = 0
    upstream_raw_matched = 0
    upstream_by_dataset: Counter[str] = Counter()
    upstream_by_poet: Counter[str] = Counter()
    period_rejected_by_dataset: Counter[str] = Counter()
    period_rejected_by_poet: Counter[str] = Counter()
    empty_by_dataset: Counter[str] = Counter()
    empty_by_poet: Counter[str] = Counter()
    upstream_empty_by_poet: Counter[str] = Counter()
    upstream_seen_poets: set[str] = set()

    for index, raw in enumerate(canonical_rows):
        poet = _canonical_author(raw)
        if poet not in roster:
            continue
        body_original = normalize_text(raw.get("body"))
        if not body_original:
            empty_skipped += 1
            empty_by_dataset["canonical"] += 1
            empty_by_poet[poet] += 1
            continue
        canonical_count += 1
        accepted_inputs += 1
        title_original = normalize_text(raw.get("title"))
        canonical_id = normalize_text(raw.get("source_poem_id")) or None
        source_work_id = canonical_id or f"canonical-{index}"
        dynasty = normalize_text(raw.get("dynasty"))
        row = _make_row(
            poet=poet,
            person_period=periods[poet],
            work_dynasty=dynasty,
            source_dynasty_raw=dynasty,
            title_original=title_original,
            body_original=body_original,
            source_site=normalize_text(raw.get("source_site")) or "canonical",
            source_url=normalize_text(raw.get("source_url")),
            source_dataset="canonical",
            source_file=_path_label(canonical_path),
            source_revision=_sha256_bytes(canonical_bytes),
            source_work_id=source_work_id,
            canonical_id=canonical_id,
            body_hash_value=raw["body_hash"] if "body_hash" in raw else _sha256_text(body_original),
            converter=converter,
        )
        work_id = row["work_id"]
        if work_id in records:
            raise ValueError(
                f"canonical 稳定身份重复，拒绝合并: {poet} {title_original} {work_id}"
            )
        records[work_id] = row
        canonical_by_identity[(poet, row["normalized_body_hash"])] = row
        canonical_by_dedupe[(poet, row["dedupe_body_hash"])].append(row)

    for source_file in source_files:
        github_path = quote(source_file.relative_path, safe="/")
        source_url = f"{UPSTREAM_REPO_URL}/blob/{revision}/{github_path}"
        for index, raw in enumerate(_iter_json_array(source_file.path)):
            if not isinstance(raw, dict):
                continue
            poet = aliases.get(normalize_text(raw.get("author")))
            if poet is None:
                continue
            upstream_raw_matched += 1
            upstream_by_dataset[source_file.dataset] += 1
            upstream_by_poet[poet] += 1
            upstream_seen_poets.add(poet)
            if not _dataset_allowed(periods[poet], source_file.dataset):
                period_rejected_by_dataset[source_file.dataset] += 1
                period_rejected_by_poet[poet] += 1
                continue
            paragraphs = raw.get("paragraphs")
            if not isinstance(paragraphs, list):
                paragraphs = []
            body_original = normalize_text("\n".join("" if value is None else str(value) for value in paragraphs))
            if not body_original:
                empty_skipped += 1
                empty_by_dataset[source_file.dataset] += 1
                empty_by_poet[poet] += 1
                upstream_empty_by_poet[poet] += 1
                continue
            accepted_inputs += 1
            title_original = normalize_text(raw.get("title") or raw.get("rhythmic"))
            source_work_id = normalize_text(raw.get("id")) or f"{source_file.relative_path}#{index}"
            row = _make_row(
                poet=poet,
                person_period=periods[poet],
                work_dynasty=source_file.work_dynasty,
                source_dynasty_raw=source_file.source_dynasty_raw,
                title_original=title_original,
                body_original=body_original,
                source_site="chinese-poetry",
                source_url=source_url,
                source_dataset=source_file.dataset,
                source_file=source_file.relative_path,
                source_revision=revision,
                source_work_id=source_work_id,
                canonical_id=None,
                body_hash_value=_sha256_text(normalize_text(converter.convert(body_original, "t2s"))),
                converter=converter,
            )
            key = (poet, row["dedupe_body_hash"])
            identity_target = canonical_by_identity.get(
                (poet, row["normalized_body_hash"])
            )
            if identity_target is not None:
                _merge_source(identity_target, row)
                continue
            canonical_target = _select_canonical_dedupe_target(
                canonical_by_dedupe.get(key, []), row
            )
            if canonical_target is not None:
                _merge_source(canonical_target, row)
                continue
            upstream_target = upstream_by_dedupe.get(key)
            if upstream_target is not None:
                _merge_source(upstream_target, row)
                continue
            work_id = row["work_id"]
            if work_id in records:
                raise ValueError(
                    f"上游 work_id 与既有身份冲突，拒绝覆盖: {poet} {title_original} {work_id}"
                )
            records[work_id] = row
            upstream_by_dedupe[key] = row

    rows = sorted(records.values(), key=lambda row: (row["poet"], row["normalized_body_hash"], row["work_id"]))
    output_bytes = _gzip_jsonl(rows)
    _atomic_write(output_path, output_bytes)
    output_hash = _sha256_bytes(output_bytes)
    manifest: dict[str, Any] = {
        "build_parameters": {
            "canonical": _path_label(canonical_path),
            "manifest": _path_label(manifest_path),
            "output": _path_label(output_path),
            "source_root": _path_label(source_root),
            "source_revision": revision,
        },
        "canonical_count": canonical_count,
        "accepted_input_count": accepted_inputs,
        "canonical_sha256": _sha256_bytes(canonical_bytes),
        "counts": _record_counts(rows),
        "deduplicated_count": accepted_inputs - len(rows),
        "empty_skipped": empty_skipped,
        "empty_skipped_by_dataset": dict(sorted(empty_by_dataset.items())),
        "empty_skipped_by_poet": dict(sorted(empty_by_poet.items())),
        "canonical_opencc_collision_groups": sum(
            len(candidates) > 1 for candidates in canonical_by_dedupe.values()
        ),
        "canonical_opencc_collision_records": sum(
            len(candidates) - 1
            for candidates in canonical_by_dedupe.values()
            if len(candidates) > 1
        ),
        "hash_definition": HASH_DEFINITION,
        "matched_files": [item.relative_path for item in source_files],
        "output_sha256": output_hash,
        "period_rejected": sum(period_rejected_by_dataset.values()),
        "period_rejected_by_dataset": dict(sorted(period_rejected_by_dataset.items())),
        "period_rejected_by_poet": dict(sorted(period_rejected_by_poet.items())),
        "poet_count": len({row["poet"] for row in rows}),
        "record_count": len(rows),
        "schema_version": SCHEMA_VERSION,
        "upstream": {
            "commit": revision,
            "license": UPSTREAM_LICENSE,
            "repo": "chinese-poetry/chinese-poetry",
            "url": UPSTREAM_REPO_URL,
        },
        "upstream_raw_matched": upstream_raw_matched,
        "upstream_raw_matched_by_dataset": dict(sorted(upstream_by_dataset.items())),
        "upstream_raw_matched_by_poet": dict(sorted(upstream_by_poet.items())),
        "upstream_empty_skipped_by_poet": dict(sorted(upstream_empty_by_poet.items())),
        "unknown_period_poets": sorted(poet for poet, period in periods.items() if period == "未知"),
        "version": MANIFEST_VERSION,
        "zero_upstream_poets": sorted(roster - upstream_seen_poets),
    }
    _atomic_write(manifest_path, _json_bytes(manifest, newline=True))
    return manifest


def _read_jsonl_gzip(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"第 {line_number} 行不是 JSON object")
            yield value


def check_corpus(
    canonical_path: Path | str = DEFAULT_CANONICAL,
    output_path: Path | str = DEFAULT_OUTPUT,
    manifest_path: Path | str = DEFAULT_MANIFEST,
    source_root: Path | str | None = None,
    *,
    converter: Converter | None = None,
) -> list[str]:
    canonical_path = Path(canonical_path)
    output_path = Path(output_path)
    manifest_path = Path(manifest_path)
    errors: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"manifest 无法读取: {exc}"]
    if not isinstance(manifest, dict):
        return ["manifest 顶层必须是 JSON object"]
    try:
        canonical_bytes = canonical_path.read_bytes()
        canonical_rows = _load_canonical(canonical_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"canonical 无法读取: {exc}"]
    expected_roster = {_canonical_author(row) for row in canonical_rows}
    expected_roster.discard("")
    periods = _derive_periods(canonical_rows, expected_roster)
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("version") != MANIFEST_VERSION
    ):
        errors.append("manifest schema/version 不匹配")
    if manifest.get("hash_definition") != HASH_DEFINITION:
        errors.append("manifest hash_definition 不匹配")
    for field in (
        "canonical_opencc_collision_groups",
        "canonical_opencc_collision_records",
    ):
        value = manifest.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            errors.append(f"manifest {field} 必须是非负整数")
    upstream = manifest.get("upstream")
    build_parameters = manifest.get("build_parameters")
    if not isinstance(build_parameters, dict):
        errors.append("manifest build_parameters 必须是 JSON object")
        build_parameters = {}
    expected_paths = {
        "canonical": _path_label(canonical_path),
        "manifest": _path_label(manifest_path),
        "output": _path_label(output_path),
    }
    if source_root is not None:
        expected_paths["source_root"] = _path_label(source_root)
    for field, expected in expected_paths.items():
        if build_parameters.get(field) != expected:
            errors.append(f"manifest build_parameters.{field} 不匹配")
    if not isinstance(upstream, dict) or (
        upstream.get("repo") != "chinese-poetry/chinese-poetry"
        or upstream.get("url") != UPSTREAM_REPO_URL
        or upstream.get("license") != UPSTREAM_LICENSE
    ):
        errors.append("manifest upstream repo/url/license 不匹配")
    revision = build_parameters.get("source_revision")
    if not isinstance(upstream, dict) or upstream.get("commit") != revision or not revision:
        errors.append("manifest upstream.commit/source_revision 不匹配")
    matched_files = manifest.get("matched_files")
    if (
        not isinstance(matched_files, list)
        or any(not isinstance(path, str) for path in matched_files)
        or matched_files != sorted(set(matched_files))
    ):
        errors.append("manifest matched_files 必须已排序且唯一")
        matched_files = matched_files if isinstance(matched_files, list) and all(isinstance(path, str) for path in matched_files) else []
    if any(not _valid_matched_file(path) for path in matched_files):
        errors.append("manifest matched_files 含非 numeric 数据文件")
    if manifest.get("canonical_sha256") != _sha256_bytes(canonical_bytes):
        errors.append("canonical_sha256 不匹配")
    try:
        output_bytes = output_path.read_bytes()
    except OSError as exc:
        return errors + [f"语料文件无法读取: {exc}"]
    if manifest.get("output_sha256") != _sha256_bytes(output_bytes):
        errors.append("output_sha256 不匹配")
    try:
        rows = list(_read_jsonl_gzip(output_path))
    except (OSError, EOFError, gzip.BadGzipFile, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return errors + [f"gzip JSONL 无法读取: {exc}"]

    canonical_revision = _sha256_bytes(canonical_bytes)
    expected_canonical_sources: Counter[tuple[Any, ...]] = Counter()
    expected_canonical_identities: dict[str, dict[str, str]] = {}
    for canonical_index, raw in enumerate(canonical_rows):
        poet = _canonical_author(raw)
        body_original = normalize_text(raw.get("body"))
        if poet not in expected_roster or not body_original:
            continue
        canonical_id = normalize_text(raw.get("source_poem_id")) or None
        canonical_body_hash = raw["body_hash"] if "body_hash" in raw else _sha256_text(body_original)
        expected_source = _source_entry(
            site=normalize_text(raw.get("source_site")) or "canonical",
            url=normalize_text(raw.get("source_url")),
            dataset="canonical",
            source_file=_path_label(canonical_path),
            revision=canonical_revision,
            work_id=canonical_id or f"canonical-{canonical_index}",
            title_original=normalize_text(raw.get("title")),
            body_original=body_original,
            body_hash=canonical_body_hash,
            dynasty_raw=normalize_text(raw.get("dynasty")),
        )
        expected_canonical_sources[_source_signature(poet, expected_source)] += 1
        if canonical_id is not None:
            if canonical_id in expected_canonical_identities:
                errors.append(f"canonical source_poem_id 重复: {canonical_id}")
            expected_canonical_identities[canonical_id] = {
                "body": body_original,
                "normalized_body_hash": _sha256_text(body_original),
                "poet": poet,
                "title": normalize_text(raw.get("title")),
                "work_id": _work_id(poet, _sha256_text(body_original)),
            }

    artifact_canonical_sources: Counter[tuple[Any, ...]] = Counter()
    artifact_upstream_sources: Counter[tuple[Any, ...]] = Counter()
    artifact_canonical_ids: set[str] = set()
    work_ids: set[str] = set()
    body_keys: set[tuple[str, str]] = set()
    for index, row in enumerate(rows, 1):
        missing = sorted(REQUIRED_FIELDS - row.keys())
        if missing:
            errors.append(f"第 {index} 行缺少字段: {', '.join(missing)}")
        if row.get("schema_version") != SCHEMA_VERSION:
            errors.append(f"第 {index} 行 schema_version 错误")
        stored_body = row.get("body")
        stored_body_original = row.get("body_original")
        body = normalize_text(stored_body)
        body_original = normalize_text(stored_body_original)
        if not isinstance(stored_body, str) or stored_body != body or not body:
            errors.append(f"第 {index} 行 body 为空或未规范化存储")
        if not isinstance(stored_body_original, str) or stored_body_original != body_original or not body_original:
            errors.append(f"第 {index} 行 body_original 为空或未规范化存储")
        if row.get("author") != row.get("poet"):
            errors.append(f"第 {index} 行 author 与 poet 不一致")
        work_id = row.get("work_id")
        if work_id in work_ids:
            errors.append(f"work_id 重复: {work_id}")
        work_ids.add(work_id)
        key = (str(row.get("poet")), str(row.get("normalized_body_hash")))
        if key in body_keys:
            errors.append(f"作者/正文 hash 重复: {key[0]} {key[1]}")
        body_keys.add(key)
        if row.get("normalized_body_hash") != _sha256_text(body):
            errors.append(f"第 {index} 行 normalized_body_hash 错误")
        dedupe_body_hash = row.get("dedupe_body_hash")
        if not isinstance(dedupe_body_hash, str) or len(dedupe_body_hash) != 64:
            errors.append(f"第 {index} 行 dedupe_body_hash 错误")
        expected_original_hash = _sha256_text(stored_body_original) if isinstance(stored_body_original, str) else None
        if row.get("body_original_hash") != expected_original_hash:
            errors.append(f"第 {index} 行 body_original_hash 错误")
        if row.get("work_id") != _work_id(str(row.get("poet")), str(row.get("normalized_body_hash"))):
            errors.append(f"第 {index} 行 work_id 派生错误")
        if row.get("variant_group_id") != _variant_group_id(str(row.get("poet")), str(row.get("title", ""))):
            errors.append(f"第 {index} 行 variant_group_id 派生错误")
        if row.get("source_dataset") != "canonical" and row.get("body_hash") != row.get("normalized_body_hash"):
            errors.append(f"第 {index} 行 upstream body_hash 错误")
        canonical_id = normalize_text(row.get("canonical_gushiwen_id")) or None
        if canonical_id is not None:
            if canonical_id in artifact_canonical_ids:
                errors.append(f"canonical_gushiwen_id 重复: {canonical_id}")
            artifact_canonical_ids.add(canonical_id)
            expected_identity = expected_canonical_identities.get(canonical_id)
            if expected_identity is None:
                errors.append(f"未知 canonical_gushiwen_id: {canonical_id}")
            else:
                actual_identity = {
                    "body": body,
                    "normalized_body_hash": row.get("normalized_body_hash"),
                    "poet": str(row.get("poet")),
                    "title": normalize_text(row.get("title")),
                    "work_id": str(row.get("work_id")),
                }
                if actual_identity != expected_identity:
                    errors.append(f"canonical 身份与 fallback 不一致: {canonical_id}")
        sources = row.get("sources")
        if not isinstance(sources, list) or not sources or any(not isinstance(source, dict) for source in sources):
            errors.append(f"第 {index} 行 sources 为空或类型错误")
            sources = []
        primary_fields = (
            "source_dataset",
            "source_file",
            "source_work_id",
            "source_revision",
            "source_site",
            "source_url",
            "title_original",
            "body_original_hash",
            "body_hash",
        )
        primary_found = False
        canonical_sources_in_row: list[dict[str, Any]] = []
        for source in sources:
            stored_source_body = source.get("body_original")
            source_body = normalize_text(stored_source_body)
            if (
                not isinstance(stored_source_body, str)
                or stored_source_body != source_body
                or not source_body
                or source.get("body_original_hash") != _sha256_text(stored_source_body)
            ):
                errors.append(f"第 {index} 行 source body_original_hash 错误")
            dataset = source.get("source_dataset")
            if dataset == "canonical":
                canonical_sources_in_row.append(source)
                artifact_canonical_sources[_source_signature(str(row.get("poet")), source)] += 1
                if source.get("source_revision") != canonical_revision:
                    errors.append(f"第 {index} 行 canonical source_revision 错误")
            else:
                artifact_upstream_sources[_source_signature(str(row.get("poet")), source)] += 1
                expected_upstream_revision = upstream.get("commit") if isinstance(upstream, dict) else None
                if source.get("source_revision") != expected_upstream_revision:
                    errors.append(f"第 {index} 行 upstream source_revision 错误")
                if source.get("body_hash") not in {
                    row.get("dedupe_body_hash"),
                    row.get("normalized_body_hash"),
                }:
                    errors.append(f"第 {index} 行 upstream source body_hash 错误")
            if all(source.get(field) == row.get(field) for field in primary_fields):
                primary_found = True
        if sources and not primary_found:
            errors.append(f"第 {index} 行没有与顶层主来源对应的 source")
        if len(canonical_sources_in_row) > 1:
            errors.append(f"第 {index} 行合并了多个 canonical 身份")
        if bool(canonical_sources_in_row) != (row.get("canonical_match") is True):
            errors.append(f"第 {index} 行 canonical_match 与 sources 不一致")
        if canonical_sources_in_row:
            canonical_source = canonical_sources_in_row[0]
            canonical_body = normalize_text(canonical_source.get("body_original"))
            canonical_title = normalize_text(canonical_source.get("title_original"))
            expected_work_id = _work_id(str(row.get("poet")), _sha256_text(canonical_body))
            if (
                body != canonical_body
                or normalize_text(row.get("title")) != canonical_title
                or row.get("normalized_body_hash") != _sha256_text(canonical_body)
                or row.get("work_id") != expected_work_id
            ):
                errors.append(f"第 {index} 行 canonical 展示正文/稳定身份错误")

    if artifact_canonical_sources != expected_canonical_sources:
        errors.append("canonical sources 与 canonical JSON 身份回配不一致")
    if artifact_canonical_ids != set(expected_canonical_identities):
        errors.append("canonical_gushiwen_id 未逐条唯一回配")

    actual_poets = {str(row.get("poet")) for row in rows}
    if actual_poets != expected_roster:
        errors.append("语料作者集合与 canonical roster 不一致")
    expected_values = {
        "record_count": len(rows),
        "poet_count": len(actual_poets),
        "counts": _record_counts(rows),
        "canonical_count": sum(1 for row in canonical_rows if _canonical_author(row) in expected_roster and normalize_text(row.get("body"))),
    }
    for field, actual in expected_values.items():
        if manifest.get(field) != actual:
            errors.append(f"manifest {field} 不匹配")

    accepted_by_dataset: Counter[str] = Counter()
    accepted_upstream_by_poet: Counter[str] = Counter()
    source_count = 0
    for row in rows:
        for source in row.get("sources") or []:
            if not isinstance(source, dict):
                continue
            dataset = str(source.get("source_dataset", ""))
            accepted_by_dataset[dataset] += 1
            source_count += 1
            if dataset != "canonical":
                accepted_upstream_by_poet[str(row.get("poet", ""))] += 1
    empty_by_dataset = Counter(manifest.get("empty_skipped_by_dataset") or {})
    empty_by_poet = Counter(manifest.get("empty_skipped_by_poet") or {})
    if manifest.get("empty_skipped") != sum(empty_by_dataset.values()):
        errors.append("manifest empty_skipped 计数不一致")
    if manifest.get("empty_skipped") != sum(empty_by_poet.values()):
        errors.append("manifest empty_skipped_by_poet 计数不一致")
    if manifest.get("accepted_input_count") != source_count:
        errors.append("manifest accepted_input_count 不匹配")
    if manifest.get("deduplicated_count") != source_count - len(rows):
        errors.append("manifest deduplicated_count 不匹配")
    rejected_by_dataset = Counter(manifest.get("period_rejected_by_dataset") or {})
    rejected_by_poet = Counter(manifest.get("period_rejected_by_poet") or {})
    if manifest.get("period_rejected") != sum(rejected_by_dataset.values()) or manifest.get("period_rejected") != sum(rejected_by_poet.values()):
        errors.append("manifest period_rejected 计数不一致")
    upstream_by_dataset = {
        dataset: accepted_by_dataset[dataset] + empty_by_dataset[dataset] + rejected_by_dataset[dataset]
        for dataset in sorted((set(accepted_by_dataset) | set(empty_by_dataset) | set(rejected_by_dataset)) - {"canonical"})
        if accepted_by_dataset[dataset] + empty_by_dataset[dataset] + rejected_by_dataset[dataset]
    }
    if manifest.get("upstream_raw_matched_by_dataset") != upstream_by_dataset:
        errors.append("manifest upstream_raw_matched_by_dataset 不匹配")
    upstream_empty_by_poet = Counter(manifest.get("upstream_empty_skipped_by_poet") or {})
    upstream_by_poet = {
        poet: accepted_upstream_by_poet[poet] + upstream_empty_by_poet[poet] + rejected_by_poet[poet]
        for poet in sorted(set(accepted_upstream_by_poet) | set(upstream_empty_by_poet) | set(rejected_by_poet))
        if accepted_upstream_by_poet[poet] + upstream_empty_by_poet[poet] + rejected_by_poet[poet]
    }
    if manifest.get("upstream_raw_matched_by_poet") != upstream_by_poet:
        errors.append("manifest upstream_raw_matched_by_poet 不匹配")
    if manifest.get("upstream_raw_matched") != sum(upstream_by_dataset.values()):
        errors.append("manifest upstream_raw_matched 不匹配")
    if manifest.get("zero_upstream_poets") != sorted(expected_roster - set(upstream_by_poet)):
        errors.append("manifest zero_upstream_poets 不匹配")
    if manifest.get("unknown_period_poets") != sorted(poet for poet, period in periods.items() if period == "未知"):
        errors.append("manifest unknown_period_poets 不匹配")

    if source_root is not None:
        if not Path(source_root).is_dir():
            errors.append("source_root 不存在或不是目录")
        converter = converter or _OpenCCConverter()
        canonical_dedupe_counts: Counter[tuple[str, str]] = Counter()
        for raw in canonical_rows:
            poet = _canonical_author(raw)
            canonical_body = normalize_text(raw.get("body"))
            if poet not in expected_roster or not canonical_body:
                continue
            canonical_dedupe_counts[
                (
                    poet,
                    _sha256_text(
                        normalize_text(converter.convert(canonical_body, "t2s"))
                    ),
                )
            ] += 1
        expected_collision_groups = sum(
            count > 1 for count in canonical_dedupe_counts.values()
        )
        expected_collision_records = sum(
            count - 1 for count in canonical_dedupe_counts.values() if count > 1
        )
        if manifest.get("canonical_opencc_collision_groups") != expected_collision_groups:
            errors.append("manifest canonical_opencc_collision_groups 不匹配")
        if manifest.get("canonical_opencc_collision_records") != expected_collision_records:
            errors.append("manifest canonical_opencc_collision_records 不匹配")
        for index, row in enumerate(rows, 1):
            expected_dedupe_hash = _sha256_text(
                normalize_text(
                    converter.convert(normalize_text(row.get("body_original")), "t2s")
                )
            )
            if row.get("dedupe_body_hash") != expected_dedupe_hash:
                errors.append(f"第 {index} 行 dedupe_body_hash 派生错误")
        aliases = _build_aliases(expected_roster, converter)
        discovered = discover_source_files(source_root)
        discovered_paths = [item.relative_path for item in discovered]
        if matched_files != discovered_paths:
            errors.append("manifest matched_files 与 source_root 不匹配")
        scan_raw_dataset: Counter[str] = Counter()
        scan_raw_poet: Counter[str] = Counter()
        scan_rejected_dataset: Counter[str] = Counter()
        scan_rejected_poet: Counter[str] = Counter()
        scan_empty_dataset: Counter[str] = Counter()
        scan_empty_poet: Counter[str] = Counter()
        scan_accepted_dataset: Counter[str] = Counter()
        scan_accepted_poet: Counter[str] = Counter()
        expected_upstream_sources: Counter[tuple[Any, ...]] = Counter()
        for source_file in discovered:
            github_path = quote(source_file.relative_path, safe="/")
            source_url = f"{UPSTREAM_REPO_URL}/blob/{revision}/{github_path}"
            for source_index, raw in enumerate(_iter_json_array(source_file.path)):
                if not isinstance(raw, dict):
                    continue
                poet = aliases.get(normalize_text(raw.get("author")))
                if poet is None:
                    continue
                scan_raw_dataset[source_file.dataset] += 1
                scan_raw_poet[poet] += 1
                if not _dataset_allowed(periods[poet], source_file.dataset):
                    scan_rejected_dataset[source_file.dataset] += 1
                    scan_rejected_poet[poet] += 1
                    continue
                paragraphs = raw.get("paragraphs")
                if not isinstance(paragraphs, list):
                    paragraphs = []
                source_body = normalize_text("\n".join("" if value is None else str(value) for value in paragraphs))
                if not source_body:
                    scan_empty_dataset[source_file.dataset] += 1
                    scan_empty_poet[poet] += 1
                    continue
                scan_accepted_dataset[source_file.dataset] += 1
                scan_accepted_poet[poet] += 1
                title_original = normalize_text(raw.get("title") or raw.get("rhythmic"))
                source_work_id = normalize_text(raw.get("id")) or f"{source_file.relative_path}#{source_index}"
                simplified_body_hash = _sha256_text(normalize_text(converter.convert(source_body, "t2s")))
                expected_source = _source_entry(
                    site="chinese-poetry",
                    url=source_url,
                    dataset=source_file.dataset,
                    source_file=source_file.relative_path,
                    revision=str(revision),
                    work_id=source_work_id,
                    title_original=title_original,
                    body_original=source_body,
                    body_hash=simplified_body_hash,
                    dynasty_raw=source_file.source_dynasty_raw,
                )
                expected_upstream_sources[_source_signature(poet, expected_source)] += 1
        canonical_empty_by_poet = Counter(
            _canonical_author(raw)
            for raw in canonical_rows
            if _canonical_author(raw) in expected_roster and not normalize_text(raw.get("body"))
        )
        canonical_empty = sum(canonical_empty_by_poet.values())
        expected_empty_dataset = dict(sorted(scan_empty_dataset.items()))
        if canonical_empty:
            expected_empty_dataset["canonical"] = canonical_empty
            expected_empty_dataset = dict(sorted(expected_empty_dataset.items()))
        source_expectations = {
            "upstream_raw_matched": sum(scan_raw_dataset.values()),
            "upstream_raw_matched_by_dataset": dict(sorted(scan_raw_dataset.items())),
            "upstream_raw_matched_by_poet": dict(sorted(scan_raw_poet.items())),
            "period_rejected": sum(scan_rejected_dataset.values()),
            "period_rejected_by_dataset": dict(sorted(scan_rejected_dataset.items())),
            "period_rejected_by_poet": dict(sorted(scan_rejected_poet.items())),
            "empty_skipped": canonical_empty + sum(scan_empty_dataset.values()),
            "empty_skipped_by_dataset": expected_empty_dataset,
            "empty_skipped_by_poet": dict(sorted((canonical_empty_by_poet + scan_empty_poet).items())),
            "upstream_empty_skipped_by_poet": dict(sorted(scan_empty_poet.items())),
            "zero_upstream_poets": sorted(expected_roster - set(scan_raw_poet)),
        }
        for field, expected in source_expectations.items():
            if manifest.get(field) != expected:
                errors.append(f"manifest {field} 与 source_root 重扫不匹配")
        artifact_upstream_dataset = Counter({key: value for key, value in accepted_by_dataset.items() if key != "canonical"})
        if artifact_upstream_dataset != scan_accepted_dataset or accepted_upstream_by_poet != scan_accepted_poet:
            errors.append("产物 accepted upstream 来源与 source_root 重扫不匹配")
        if artifact_upstream_sources != expected_upstream_sources:
            errors.append("upstream sources 与 source_root 记录签名不一致")
        source_root_path = Path(source_root)
        actual_git_revision = _try_git_revision(source_root_path)
        if actual_git_revision is None:
            if (source_root_path / ".git").exists():
                errors.append("无法严格验证 source_root Git checkout")
        else:
            if actual_git_revision != revision:
                errors.append("source_root Git HEAD 与 manifest commit 不匹配")
            errors.extend(_git_target_state_errors(source_root_path, discovered, actual_git_revision))
    return errors


def load_analysis_poems(
    full_path: Path | str | None = None,
    canonical_path: Path | str | None = None,
    fallback: bool = True,
    *,
    manifest_path: Path | str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Return a validated, materialized list; streaming is intentionally deferred."""
    default_full_path = REPO_ROOT / DEFAULT_OUTPUT
    explicit_full_path = full_path is not None
    full_path = Path(full_path) if explicit_full_path else default_full_path
    canonical_path = (
        Path(canonical_path)
        if canonical_path is not None
        else REPO_ROOT / DEFAULT_CANONICAL
    )
    if full_path.is_file():
        if (
            manifest_path is None
            and explicit_full_path
            and full_path.resolve() != default_full_path.resolve()
        ):
            raise ValueError(
                "自定义 full_path 存在时必须显式提供 manifest_path，"
                "拒绝绑定仓库默认 manifest"
            )
        manifest_path = (
            Path(manifest_path)
            if manifest_path is not None
            else REPO_ROOT / DEFAULT_MANIFEST
        )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"analysis_full manifest 缺失，拒绝读取旧全集: {manifest_path}"
            ) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"analysis_full manifest 无法读取，拒绝读取全集: {manifest_path}: {exc}"
            ) from exc
        if not isinstance(manifest, dict):
            raise RuntimeError(
                f"analysis_full manifest 顶层必须是 JSON object: {manifest_path}"
            )
        if (
            manifest.get("schema_version") != SCHEMA_VERSION
            or manifest.get("version") != MANIFEST_VERSION
            or manifest.get("hash_definition") != HASH_DEFINITION
        ):
            raise RuntimeError("analysis_full manifest schema/hash_definition 已过期")

        def file_sha256(path: Path) -> str:
            digest = hashlib.sha256()
            try:
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError as exc:
                raise RuntimeError(f"analysis_full 校验文件无法读取: {path}: {exc}") from exc
            return digest.hexdigest()

        canonical_sha256 = manifest.get("canonical_sha256")
        if not isinstance(canonical_sha256, str):
            raise RuntimeError("analysis_full manifest 缺少 canonical_sha256")
        if file_sha256(canonical_path) != canonical_sha256:
            raise RuntimeError(
                "analysis_full canonical_sha256 不匹配；canonical 已更新，请重建全集"
            )

        output_sha256 = manifest.get("output_sha256")
        if not isinstance(output_sha256, str):
            raise RuntimeError("analysis_full manifest 缺少 output_sha256")
        if file_sha256(full_path) != output_sha256:
            raise RuntimeError(
                "analysis_full output_sha256 不匹配；全集已损坏或 manifest 已过期"
            )

        expected_count = manifest.get("record_count")
        if isinstance(expected_count, bool) or not isinstance(expected_count, int):
            raise RuntimeError("analysis_full manifest record_count 必须是整数")
        rows = []
        try:
            for row in _read_jsonl_gzip(full_path):
                compatible = dict(row)
                compatible["author"] = row["poet"]
                compatible["dynasty"] = row["work_dynasty"]
                rows.append(compatible)
        except Exception as exc:
            raise RuntimeError(f"analysis_full 内容损坏或字段不完整: {full_path}: {exc}") from exc
        if len(rows) != expected_count:
            raise RuntimeError(
                "analysis_full record_count 不匹配: "
                f"manifest={expected_count}, actual={len(rows)}"
            )
        return rows, "analysis_full"
    if not fallback:
        raise FileNotFoundError(full_path)
    rows = []
    for row in _load_canonical(canonical_path):
        compatible = dict(row)
        poet = normalize_text(row.get("author") or row.get("poet"))
        body = normalize_text(row.get("body"))
        canonical_id = normalize_text(row.get("source_poem_id")) or None
        compatible["author"] = poet
        compatible["poet"] = poet
        compatible["work_id"] = _work_id(poet, _sha256_text(body))
        compatible["canonical_gushiwen_id"] = canonical_id
        rows.append(compatible)
    return rows, "canonical"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="构建确定性的全集语料")
    build.add_argument("--canonical", type=Path, default=REPO_ROOT / DEFAULT_CANONICAL)
    build.add_argument("--source-root", type=Path, default=REPO_ROOT / DEFAULT_SOURCE_ROOT)
    build.add_argument("--output", type=Path, default=REPO_ROOT / DEFAULT_OUTPUT)
    build.add_argument("--manifest", type=Path, default=REPO_ROOT / DEFAULT_MANIFEST)
    build.add_argument("--source-revision")
    check = subparsers.add_parser("check", help="校验全集语料和 manifest")
    check.add_argument("--canonical", type=Path, default=REPO_ROOT / DEFAULT_CANONICAL)
    check.add_argument("--source-root", type=Path, default=REPO_ROOT / DEFAULT_SOURCE_ROOT)
    check.add_argument("--output", type=Path, default=REPO_ROOT / DEFAULT_OUTPUT)
    check.add_argument("--manifest", type=Path, default=REPO_ROOT / DEFAULT_MANIFEST)
    check.add_argument("--no-source-verify", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "build":
        try:
            manifest = build_corpus(
                args.canonical,
                args.source_root,
                args.output,
                args.manifest,
                args.source_revision,
            )
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            print(f"ERROR: {exc}")
            return 1
        print(f"built {manifest['record_count']} records for {manifest['poet_count']} poets")
        return 0
    try:
        errors = check_corpus(
            args.canonical,
            args.output,
            args.manifest,
            None if args.no_source_verify else args.source_root,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 1
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
