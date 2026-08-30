from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from poetry_agent.rich_guide import (
    RichGuideError,
    RichGuideService,
    _exclusive_poem_lock,
)


POEMS = {
    "poem-1": {
        "poem_id": "poem-1",
        "title": "测试诗一",
        "poet": "测试诗人",
        "dynasty": "唐",
        "body": "白日依山尽，黄河入海流。",
        "body_hash": "hash-1",
    },
    "poem-2": {
        "poem_id": "poem-2",
        "title": "测试诗二",
        "poet": "测试诗人",
        "dynasty": "宋",
        "body": "山重水复疑无路，柳暗花明又一村。",
        "body_hash": "hash-2",
    },
}


def _result(prompt: str) -> dict[str, Any]:
    return {
        "story": f"并发测试赏析：{prompt}",
        "line_notes": [],
        "appreciation_points": ["并发测试赏析"],
    }


def _service(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_llm: Callable[[dict[str, Any], str], dict[str, Any]],
) -> RichGuideService:
    service = RichGuideService(
        project_root,
        base_url="https://llm.invalid",
        api_key="test-key",
        model="test-model",
    )
    tool = SimpleNamespace(
        load_references=lambda _path, _body_hash: [],
        build_prompt=lambda title, poet, dynasty, body, fact, references: title,
        request_llm=request_llm,
        validate_item=lambda result, body, fact, references: [],
        package_generated_item=lambda result, poem, fact, references, model, audit: {
            "poem_id": poem["poem_id"],
            "title": poem["title"],
            "poet": poem["poet"],
            "story": result["story"],
            "line_notes": result["line_notes"],
            "appreciation_points": result["appreciation_points"],
            "facts_anchor": {"tier": "none"},
            "audit": {
                "model": model,
                "prompt_version": "rich_guide_v2_evidence",
                "reference_mode": "poem_only",
                **audit,
            },
        },
    )
    monkeypatch.setattr(
        service,
        "load_poem",
        lambda poem_id: dict(POEMS[poem_id]) if poem_id in POEMS else None,
    )
    monkeypatch.setattr(service, "_resolve_fact", lambda _poem: None)
    monkeypatch.setattr(service, "_tool_module", lambda: tool)
    return service


def test_same_poem_across_service_instances_generates_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    call_count = 0
    count_lock = threading.Lock()
    generation_started = threading.Event()
    release_generation = threading.Event()

    def request_llm(_config: dict[str, Any], prompt: str) -> dict[str, Any]:
        nonlocal call_count
        with count_lock:
            call_count += 1
        generation_started.set()
        assert release_generation.wait(5), "测试未释放首个生成请求"
        return _result(prompt)

    services = [
        _service(tmp_path, monkeypatch, request_llm)
        for _ in range(8)
    ]
    with ThreadPoolExecutor(max_workers=len(services)) as executor:
        futures = [executor.submit(service.generate, "poem-1") for service in services]
        assert generation_started.wait(5), "没有请求进入生成阶段"
        release_generation.set()
        results = [future.result(timeout=5) for future in futures]

    assert call_count == 1
    assert [result["status"] for result in results].count("generated") == 1
    assert [result["status"] for result in results].count("exists") == 7
    archive = json.loads(
        (
            tmp_path
            / "data"
            / "llm_rich_backgrounds"
            / "batch_auto_001.json"
        ).read_text(encoding="utf-8")
    )
    assert [item["poem_id"] for item in archive["items"]] == ["poem-1"]


def test_same_poem_across_release_roots_with_shared_archive_generates_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    call_count = 0
    count_lock = threading.Lock()
    generation_started = threading.Event()
    release_generation = threading.Event()
    persistent_dir = tmp_path / "persistent" / "llm_rich_backgrounds"
    monkeypatch.setenv("AGENT_RICH_GUIDE_DIR", str(persistent_dir))

    def request_llm(_config: dict[str, Any], prompt: str) -> dict[str, Any]:
        nonlocal call_count
        with count_lock:
            call_count += 1
        generation_started.set()
        assert release_generation.wait(5), "测试未释放首个生成请求"
        return _result(prompt)

    services = [
        _service(tmp_path / "releases" / release, monkeypatch, request_llm)
        for release in ("release-1", "release-2")
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(service.generate, "poem-1") for service in services]
        assert generation_started.wait(5), "没有请求进入生成阶段"
        release_generation.set()
        results = [future.result(timeout=5) for future in futures]

    assert call_count == 1
    assert sorted(result["status"] for result in results) == ["exists", "generated"]
    archive = json.loads(
        (persistent_dir / "batch_auto_001.json").read_text(encoding="utf-8")
    )
    assert [item["poem_id"] for item in archive["items"]] == ["poem-1"]


def test_different_poems_generate_in_parallel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    both_generating = threading.Barrier(2)

    def request_llm(_config: dict[str, Any], prompt: str) -> dict[str, Any]:
        both_generating.wait(timeout=5)
        return _result(prompt)

    service = _service(tmp_path, monkeypatch, request_llm)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(service.generate, "poem-1"),
            executor.submit(service.generate, "poem-2"),
        ]
        results = [future.result(timeout=5) for future in futures]

    assert [result["status"] for result in results] == ["generated", "generated"]
    archive = json.loads(
        (
            tmp_path
            / "data"
            / "llm_rich_backgrounds"
            / "batch_auto_001.json"
        ).read_text(encoding="utf-8")
    )
    assert {item["poem_id"] for item in archive["items"]} == {"poem-1", "poem-2"}


def test_failed_leader_releases_lock_and_waiter_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    call_count = 0
    count_lock = threading.Lock()
    first_started = threading.Event()
    release_failure = threading.Event()

    def request_llm(_config: dict[str, Any], prompt: str) -> dict[str, Any]:
        nonlocal call_count
        with count_lock:
            call_count += 1
            attempt = call_count
        if attempt == 1:
            first_started.set()
            assert release_failure.wait(5), "测试未释放失败请求"
            raise RuntimeError("transient upstream failure")
        return _result(prompt)

    first_service = _service(tmp_path, monkeypatch, request_llm)
    second_service = _service(tmp_path, monkeypatch, request_llm)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_service.generate, "poem-1")
        assert first_started.wait(5), "首个请求未进入生成阶段"
        second = executor.submit(second_service.generate, "poem-1")
        release_failure.set()

        with pytest.raises(RichGuideError) as failure:
            first.result(timeout=5)
        recovered = second.result(timeout=5)

    assert failure.value.status_code == 502
    assert recovered["status"] == "generated"
    assert call_count == 2
    assert first_service.generate("poem-1")["status"] == "exists"
    assert call_count == 2


def test_poem_lock_blocks_other_process_until_release(tmp_path: Path) -> None:
    ready_path = tmp_path / "child-ready"
    acquired_path = tmp_path / "child-acquired"
    script = """
import sys
from pathlib import Path
from poetry_agent.rich_guide import _exclusive_poem_lock

project_root = Path(sys.argv[1])
ready_path = Path(sys.argv[2])
acquired_path = Path(sys.argv[3])
ready_path.write_text("ready", encoding="utf-8")
with _exclusive_poem_lock(project_root, "poem-1"):
    acquired_path.write_text("acquired", encoding="utf-8")
"""
    process: subprocess.Popen[str] | None = None
    with _exclusive_poem_lock(tmp_path, "poem-1"):
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(tmp_path),
                str(ready_path),
                str(acquired_path),
            ],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 5
        while not ready_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready_path.exists(), "子进程未进入按诗锁调用"
        time.sleep(0.1)
        assert process.poll() is None, "子进程没有等待跨进程按诗锁"
        assert not acquired_path.exists()

    assert process is not None
    stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 0, stdout + stderr
    assert acquired_path.read_text(encoding="utf-8") == "acquired"
