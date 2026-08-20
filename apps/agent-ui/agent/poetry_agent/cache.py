"""Locked, validated cache of the root project's generated data."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator


SCHEMA_VERSION = "1.0"


class SourceDataError(RuntimeError):
    """The project data or a generated snapshot failed validation."""


class CacheLockTimeout(SourceDataError):
    """Another process held the cache refresh lock for too long."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise SourceDataError(f"文件哈希读取失败: {path}: {exc}") from exc
    return digest.hexdigest()


def sha256_source_file(path: Path) -> str:
    """Hash a text source consistently across LF and CRLF checkouts."""
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise SourceDataError(f"文件哈希读取失败: {path}: {exc}") from exc
    return hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()


def _normalized_source_sha256(path: Path) -> str:
    """Hash text dependencies after normalizing LF and CRLF line endings."""
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise SourceDataError(f"文件哈希读取失败: {path}: {exc}") from exc
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return hashlib.sha256(content).hexdigest()
    # Preserve standalone CR characters used inside some CSV fields while
    # making LF and CRLF line endings equivalent.
    normalized = text.replace("\r\n", "\n").replace("\n", "\r\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceDataError(f"JSON读取失败: {path}: {exc}") from exc


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _atomic_copy(source: Path, destination: Path) -> None:
    _atomic_write_bytes(destination, source.read_bytes())


_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock(path: Path) -> threading.Lock:
    key = str(path.resolve()).casefold()
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


@contextmanager
def interprocess_file_lock(path: Path, timeout: float = 60.0) -> Iterator[None]:
    """Small stdlib-only lock that works on Windows and POSIX."""

    path.parent.mkdir(parents=True, exist_ok=True)
    local_lock = _thread_lock(path)
    if not local_lock.acquire(timeout=timeout):
        raise CacheLockTimeout(f"缓存线程锁等待超时: {path}")
    handle = None
    try:
        handle = path.open("a+b")
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise CacheLockTimeout(f"缓存进程锁等待超时: {path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        if handle is not None:
            handle.close()
        local_lock.release()


Validator = Callable[[Any], None]


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    generated_json: str
    generator: str
    dependencies: tuple[str, ...]
    validator: Validator
    embedded_hash_path: tuple[str, ...]
    dependency_hash_keys: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class DatasetSnapshot:
    data: dict[str, Any]
    source_hashes: dict[str, str]
    cache_path: Path
    refreshed: bool


def validate_poems(data: Any) -> None:
    if not isinstance(data, list) or not data:
        raise SourceDataError("poems.json 必须是非空数组")
    poets: set[str] = set()
    for index, row in enumerate(data):
        if not isinstance(row, dict):
            raise SourceDataError(f"poems.json 第{index}项不是对象")
        poet = str(row.get("poet") or row.get("author") or "").strip()
        if not poet or not str(row.get("title") or "").strip():
            raise SourceDataError(f"poems.json 第{index}项缺少诗人或标题")
        poets.add(poet)
    if len(poets) != 88:
        raise SourceDataError(f"poems.json 诗人数应为88，实际为{len(poets)}")


def validate_year_data(data: Any) -> None:
    if not isinstance(data, dict):
        raise SourceDataError("year759_data 顶层必须是对象")
    meta = data.get("meta")
    stories = data.get("stories")
    if not isinstance(meta, dict) or not isinstance(meta.get("input_sha256"), dict):
        raise SourceDataError("year759_data.meta/input_sha256 缺失")
    if not isinstance(stories, list) or len(stories) != 6:
        raise SourceDataError("year759_data.stories 必须包含六位诗人")
    seen: set[str] = set()
    scene_ids: set[str] = set()
    total_scenes = 0
    required_scene = {
        "id",
        "poet",
        "year_start",
        "year_end",
        "year_precision",
        "poem_title",
        "source_grade",
        "map_eligible",
    }
    for story in stories:
        if not isinstance(story, dict) or not story.get("poet"):
            raise SourceDataError("year759_data story 缺少 poet")
        poet = str(story["poet"])
        if poet in seen:
            raise SourceDataError(f"year759_data 重复诗人: {poet}")
        seen.add(poet)
        scenes = story.get("scenes")
        if not isinstance(scenes, list):
            raise SourceDataError(f"{poet} scenes 不是数组")
        if story.get("scene_count") != len(scenes):
            raise SourceDataError(f"{poet} scene_count 与 scenes 长度不一致")
        if not isinstance(story.get("segments"), list):
            raise SourceDataError(f"{poet} segments 不是数组")
        for scene in scenes:
            if not isinstance(scene, dict) or not required_scene.issubset(scene):
                raise SourceDataError(f"{poet} 存在字段不完整的镜头")
            scene_id = str(scene["id"])
            if scene_id in scene_ids:
                raise SourceDataError(f"year759_data 重复镜头id: {scene_id}")
            scene_ids.add(scene_id)
        total_scenes += len(scenes)
    if seen != {"李白", "杜甫", "白居易", "苏轼", "陆游", "李清照"}:
        raise SourceDataError("year759_data 六位诗人集合不符合契约")
    if meta.get("scene_count") != total_scenes:
        raise SourceDataError("year759_data.meta.scene_count 与实际镜头数不一致")
    if not isinstance(data.get("unresolved"), list):
        raise SourceDataError("year759_data.unresolved 缺失")
    if meta.get("unresolved_count") != len(data["unresolved"]):
        raise SourceDataError("year759_data.meta.unresolved_count 不一致")


def validate_imagery_data(data: Any) -> None:
    if not isinstance(data, dict):
        raise SourceDataError("imagery_tide_data 顶层必须是对象")
    meta = data.get("meta")
    words = data.get("wordStats")
    if not isinstance(meta, dict) or meta.get("schemaVersion") != SCHEMA_VERSION:
        raise SourceDataError("imagery_tide_data schemaVersion 不受支持")
    if not isinstance(meta.get("sourceHashes"), dict):
        raise SourceDataError("imagery_tide_data.meta.sourceHashes 缺失")
    if not isinstance(words, list) or len(words) != 160:
        raise SourceDataError("imagery_tide_data.wordStats 必须包含160词")
    terms = [row.get("word") for row in words if isinstance(row, dict)]
    if len(terms) != 160 or len(set(terms)) != 160:
        raise SourceDataError("imagery_tide_data 词表字段缺失或重复")
    if not isinstance(data.get("topContrasts"), list):
        raise SourceDataError("imagery_tide_data.topContrasts 缺失")
    evidence = data.get("evidence")
    if not isinstance(evidence, dict):
        raise SourceDataError("imagery_tide_data.evidence 缺失")
    if not set(terms).issubset(evidence):
        raise SourceDataError("imagery_tide_data 未覆盖全部160词证据")
    for row in words:
        for dynasty_key in ("tang", "song"):
            dynasty = row.get(dynasty_key)
            if not isinstance(dynasty, dict) or "ratePer10k" not in dynasty:
                raise SourceDataError(f"意象词 {row.get('word')} 缺少唐宋每万字率")
    if any(row.get("word") not in set(terms) for row in data["topContrasts"]):
        raise SourceDataError("topContrasts 含有160词表外条目")
    lens = data.get("historicalLens")
    if (
        not isinstance(lens, dict)
        or not isinstance(lens.get("chapters"), list)
        or not isinstance(lens.get("playbackNodes"), list)
    ):
        raise SourceDataError("imagery_tide_data.historicalLens.chapters 缺失")


YEAR_SPEC = DatasetSpec(
    key="year759",
    generated_json="output/assets/competition/year759_data.json",
    generator="数据可视化脚本/viz_33_year759.py",
    dependencies=(
        "data/poems.json",
        "data/reviewed/verified_poem_contexts.csv",
        "data/candidates/libai_spirit_chronology.csv",
        "data/candidates/dufu_spirit_chronology.csv",
        "data/candidates/baijuyi_spirit_chronology.csv",
        "data/candidates/sushi_spirit_chronology.csv",
        "data/candidates/luyou_spirit_chronology.csv",
        "data/candidates/liqingzhao_spirit_chronology.csv",
        "data/stylometry/emotion_profiles.json",
    ),
    validator=validate_year_data,
    embedded_hash_path=("meta", "input_sha256"),
    dependency_hash_keys=(
        ("data/poems.json", "poems.json"),
        (
            "data/reviewed/verified_poem_contexts.csv",
            "verified_poem_contexts.csv",
        ),
        (
            "data/candidates/libai_spirit_chronology.csv",
            "libai_spirit_chronology.csv",
        ),
        (
            "data/candidates/dufu_spirit_chronology.csv",
            "dufu_spirit_chronology.csv",
        ),
        (
            "data/candidates/baijuyi_spirit_chronology.csv",
            "baijuyi_spirit_chronology.csv",
        ),
        (
            "data/candidates/sushi_spirit_chronology.csv",
            "sushi_spirit_chronology.csv",
        ),
        (
            "data/candidates/luyou_spirit_chronology.csv",
            "luyou_spirit_chronology.csv",
        ),
        (
            "data/candidates/liqingzhao_spirit_chronology.csv",
            "liqingzhao_spirit_chronology.csv",
        ),
        ("data/stylometry/emotion_profiles.json", "emotion_profiles.json"),
    ),
)

IMAGERY_SPEC = DatasetSpec(
    key="imagery_tide",
    generated_json="output/assets/competition/imagery_tide_data.json",
    generator="数据可视化脚本/viz_38_imagery_tide.py",
    dependencies=(
        "data/poems.json",
        "data/imagery_tide_lexicon.py",
        "data/reviewed/poet_journeys.json",
    ),
    validator=validate_imagery_data,
    embedded_hash_path=("meta", "sourceHashes"),
    dependency_hash_keys=(
        ("data/poems.json", "poemsJsonSha256"),
        # 字段名保持兼容；来源已切换为38号冻结160词资产。
        ("data/imagery_tide_lexicon.py", "spiritImageDictSha256"),
        ("data/reviewed/poet_journeys.json", "poetJourneysSha256"),
    ),
)


class SnapshotRepository:
    """Validate offline outputs and serve immutable cached snapshots."""

    def __init__(
        self,
        project_root: Path,
        cache_dir: Path,
        *,
        lock_timeout: float = 120.0,
    ) -> None:
        self.project_root = project_root.resolve()
        self.cache_dir = cache_dir.resolve()
        self.lock_timeout = lock_timeout
        self._memory: dict[str, tuple[str, Any]] = {}

    def _dependency_hashes(self, spec: DatasetSpec) -> dict[str, str]:
        result: dict[str, str] = {}
        for relative in spec.dependencies:
            path = self.project_root / relative
            if not path.is_file():
                raise SourceDataError(
                    f"数据依赖不存在: {relative}；请先运行离线生成器: {spec.generator}"
                )
            result[relative] = sha256_file(path)
        return result

    def _authoritative_path(self, spec: DatasetSpec) -> Path:
        assets_dir = (
            self.project_root / "output" / "assets" / "competition"
        ).resolve()
        source = (self.project_root / spec.generated_json).resolve()
        if source.parent != assets_dir or source.suffix.casefold() != ".json":
            raise SourceDataError(
                "数据集路径必须是 output/assets/competition/*.json"
            )
        return source

    @staticmethod
    def _offline_generator_error(spec: DatasetSpec, reason: str) -> SourceDataError:
        return SourceDataError(
            f"{reason}；请先运行离线生成器: {spec.generator}"
        )

    def _read_authoritative(
        self, spec: DatasetSpec, source: Path
    ) -> tuple[bytes, dict[str, Any]]:
        if not source.is_file():
            raise self._offline_generator_error(
                spec, f"生成快照缺失: {spec.generated_json}"
            )
        try:
            content = source.read_bytes()
            data = json.loads(content.decode("utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise self._offline_generator_error(
                spec, f"生成快照读取失败: {spec.generated_json}: {exc}"
            ) from exc
        try:
            spec.validator(data)
        except SourceDataError as exc:
            raise self._offline_generator_error(spec, str(exc)) from exc
        except Exception as exc:
            raise self._offline_generator_error(
                spec, f"生成快照结构校验失败: {exc}"
            ) from exc
        return content, data

    def _validate_embedded_hashes(
        self,
        spec: DatasetSpec,
        data: dict[str, Any],
        dependencies: dict[str, str],
    ) -> None:
        configured_dependencies = {relative for relative, _ in spec.dependency_hash_keys}
        if configured_dependencies != set(spec.dependencies):
            raise SourceDataError(f"数据集依赖哈希映射不完整: {spec.key}")
        embedded: Any = data
        for key in spec.embedded_hash_path:
            if not isinstance(embedded, dict) or key not in embedded:
                raise self._offline_generator_error(
                    spec, f"生成快照缺少内置源哈希: {'.'.join(spec.embedded_hash_path)}"
                )
            embedded = embedded[key]
        if not isinstance(embedded, dict):
            raise self._offline_generator_error(spec, "生成快照内置源哈希不是对象")
        mismatches = []
        for relative, embedded_key in spec.dependency_hash_keys:
            expected = embedded.get(embedded_key)
            if expected == dependencies[relative]:
                continue
            if expected == _normalized_source_sha256(self.project_root / relative):
                continue
            if expected == sha256_source_file(self.project_root / relative):
                continue
            mismatches.append(relative)
        if mismatches:
            raise self._offline_generator_error(
                spec,
                "生成快照内置源哈希与当前依赖不一致: " + ", ".join(mismatches),
            )

    def _cache_paths(self, spec: DatasetSpec) -> tuple[Path, Path]:
        data_path = self.cache_dir / Path(spec.generated_json).name
        manifest_path = self.cache_dir / f"{spec.key}.manifest.json"
        return data_path, manifest_path

    def _valid_cached_snapshot(
        self,
        spec: DatasetSpec,
        dependencies: dict[str, str],
        authoritative_hash: str,
        data_path: Path,
        manifest_path: Path,
    ) -> dict[str, Any] | None:
        if not data_path.is_file() or not manifest_path.is_file():
            return None
        try:
            manifest = _read_json(manifest_path)
            if not isinstance(manifest, dict):
                return None
            if manifest.get("dependencyHashes") != dependencies:
                return None
            cached_hash = sha256_file(data_path)
            if manifest.get("cachedJsonSha256") != cached_hash:
                return None
            if manifest.get("authoritativeJsonSha256") != authoritative_hash:
                return None
            if authoritative_hash != cached_hash:
                return None
            return manifest
        except SourceDataError:
            return None

    def ensure_dataset(self, spec: DatasetSpec) -> DatasetSnapshot:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        source = self._authoritative_path(spec)
        data_path, manifest_path = self._cache_paths(spec)
        with interprocess_file_lock(
            self.cache_dir / ".refresh.lock", timeout=self.lock_timeout
        ):
            dependencies = self._dependency_hashes(spec)
            content, data = self._read_authoritative(spec, source)
            authoritative_hash = hashlib.sha256(content).hexdigest()
            self._validate_embedded_hashes(spec, data, dependencies)
            if self._dependency_hashes(spec) != dependencies:
                raise self._offline_generator_error(
                    spec, "校验期间数据依赖发生变化"
                )
            if not source.is_file() or sha256_file(source) != authoritative_hash:
                raise self._offline_generator_error(
                    spec, "校验期间生成快照发生变化"
                )

            manifest = self._valid_cached_snapshot(
                spec,
                dependencies,
                authoritative_hash,
                data_path,
                manifest_path,
            )
            if manifest is not None:
                cache_key = f"{spec.key}:{authoritative_hash}"
                remembered = self._memory.get(spec.key)
                if remembered and remembered[0] == cache_key:
                    data = remembered[1]
                else:
                    self._memory[spec.key] = (cache_key, data)
                hashes = dict(manifest["dependencyHashes"])
                hashes[spec.generated_json] = manifest["cachedJsonSha256"]
                return DatasetSnapshot(data, hashes, data_path, False)

            _atomic_write_bytes(data_path, content)
            cached_hash = authoritative_hash
            manifest = {
                "schemaVersion": SCHEMA_VERSION,
                "dataset": spec.key,
                "generator": spec.generator,
                "generatedJson": spec.generated_json,
                "dependencyHashes": dependencies,
                "authoritativeJsonSha256": authoritative_hash,
                "cachedJsonSha256": cached_hash,
                "refreshedAt": datetime.now(timezone.utc).isoformat(),
            }
            _atomic_write_bytes(
                manifest_path,
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            self._memory[spec.key] = (f"{spec.key}:{cached_hash}", data)
            hashes = dict(dependencies)
            hashes[spec.generated_json] = cached_hash
            return DatasetSnapshot(data, hashes, data_path, True)

    def load_generated_dataset(self, spec: DatasetSpec) -> DatasetSnapshot:
        """Read a packaged snapshot without re-hashing its large dependencies."""

        source = self._authoritative_path(spec)
        content, data = self._read_authoritative(spec, source)
        embedded: Any = data
        for key in spec.embedded_hash_path:
            if not isinstance(embedded, dict):
                raise self._offline_generator_error(spec, "生成快照内置源哈希路径无效")
            embedded = embedded.get(key)
        if not isinstance(embedded, dict):
            raise self._offline_generator_error(spec, "生成快照内置源哈希不是对象")
        hashes = {
            relative: embedded_value
            for relative, embedded_key in spec.dependency_hash_keys
            if isinstance((embedded_value := embedded.get(embedded_key)), str)
        }
        hashes[spec.generated_json] = hashlib.sha256(content).hexdigest()
        return DatasetSnapshot(data, hashes, source, False)

    def load_poems(self) -> tuple[list[dict[str, Any]], dict[str, str]]:
        source = self.project_root / "data" / "poems.json"
        if not source.is_file():
            raise SourceDataError("数据依赖不存在: data/poems.json")
        source_hash = sha256_file(source)
        destination = self.cache_dir / "poems.json"
        with interprocess_file_lock(
            self.cache_dir / ".refresh.lock", timeout=self.lock_timeout
        ):
            if not destination.is_file() or sha256_file(destination) != source_hash:
                _atomic_copy(source, destination)
            cache_key = f"poems:{source_hash}"
            remembered = self._memory.get("poems")
            if remembered and remembered[0] == cache_key:
                data = remembered[1]
            else:
                data = _read_json(destination)
                validate_poems(data)
                self._memory["poems"] = (cache_key, data)
        return data, {
            "data/poems.json": source_hash,
            "apps/agent-ui/.cache/poems.json": sha256_file(destination),
        }

    def cache_status(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for spec in (YEAR_SPEC, IMAGERY_SPEC):
            data_path, manifest_path = self._cache_paths(spec)
            result[spec.key] = {
                "cached": data_path.is_file() and manifest_path.is_file(),
                "cacheFile": str(data_path),
            }
        poems = self.cache_dir / "poems.json"
        result["poems"] = {"cached": poems.is_file(), "cacheFile": str(poems)}
        return result
