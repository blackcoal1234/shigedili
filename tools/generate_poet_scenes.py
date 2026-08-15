"""Generate optional per-poem scene assets through the configured Codex provider.

The default command and --dry-run only validate and print a local plan. Pass
--execute explicitly to invoke the api-image skill helper.

Examples:
    python tools/generate_poet_scenes.py --dry-run --limit 2
    python tools/generate_poet_scenes.py --only libai-SCENE_ID --execute
    python tools/generate_poet_scenes.py --only KEY_A --only KEY_B --execute
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "output" / "assets" / "competition" / "scene_prompt_manifest.json"
ASSET_DIR = ROOT / "output" / "assets" / "competition" / "generated_scenes"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gpt-image-2", choices=["gpt-image-2"])
    parser.add_argument("--only", action="append", default=[], help="Select this manifest key; repeatable")
    parser.add_argument("--limit", type=int, help="Limit selected jobs after --only filtering")
    parser.add_argument("--force", action="store_true", help="Replace an existing valid PNG")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print planned jobs without network calls")
    parser.add_argument("--execute", action="store_true", help="Explicitly invoke the configured image provider")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--codex-home", help="Override the Codex root used by the api-image helper")
    return parser.parse_args()


def resolve_codex_home(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".codex").resolve()


def resolve_skill_helper(codex_home: Path) -> Path:
    helper = codex_home / "skills" / "api-image" / "scripts" / "generate_image.py"
    if not helper.is_file():
        raise FileNotFoundError(f"api-image helper not found: {helper}")
    return helper


def configured_provider_name(codex_home: Path) -> str:
    config_path = codex_home / "config.toml"
    if not config_path.is_file():
        raise FileNotFoundError(f"Codex provider config not found: {config_path}")
    with config_path.open("rb") as handle:
        config = tomllib.load(handle)
    provider = config.get("image_provider") or config.get("model_provider")
    if not isinstance(provider, str) or not provider.strip():
        raise RuntimeError(f"image_provider/model_provider is missing in {config_path}")
    providers = config.get("model_providers") or {}
    if not isinstance(providers.get(provider), dict):
        raise RuntimeError(f"configured provider '{provider}' is missing from {config_path}")
    return provider


def validate_png(path: Path) -> tuple[bool, str, dict[str, int] | None]:
    if not path.is_file():
        return False, "file does not exist", None
    try:
        payload = path.read_bytes()
    except OSError as exc:
        return False, f"read failed: {exc}", None
    if len(payload) < 45:
        return False, "file is too small", None
    if not payload.startswith(PNG_SIGNATURE):
        return False, "invalid PNG signature", None

    offset = len(PNG_SIGNATURE)
    dimensions: dict[str, int] | None = None
    saw_iend = False
    while offset + 12 <= len(payload):
        length = int.from_bytes(payload[offset:offset + 4], "big")
        chunk_type = payload[offset + 4:offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        chunk_end = data_end + 4
        if chunk_end > len(payload):
            return False, "truncated PNG chunk", None
        expected_crc = int.from_bytes(payload[data_end:chunk_end], "big")
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(payload[data_start:data_end], actual_crc) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            return False, f"invalid {chunk_type.decode('ascii', errors='replace')} CRC", None
        if dimensions is None:
            if chunk_type != b"IHDR" or length != 13:
                return False, "first chunk is not a valid IHDR", None
            width = int.from_bytes(payload[data_start:data_start + 4], "big")
            height = int.from_bytes(payload[data_start + 4:data_start + 8], "big")
            if width <= 0 or height <= 0:
                return False, "invalid IHDR dimensions", None
            dimensions = {"width": width, "height": height}
        if chunk_type == b"IEND":
            if length != 0:
                return False, "invalid IEND length", None
            if chunk_end != len(payload):
                return False, "data found after IEND", None
            saw_iend = True
            break
        offset = chunk_end
    if dimensions is None:
        return False, "IHDR is missing", None
    if not saw_iend:
        return False, "IEND is missing", None
    return True, "valid PNG", dimensions


def load_selected_items(args: argparse.Namespace) -> list[dict]:
    if not MANIFEST.is_file():
        raise FileNotFoundError(f"missing prompt manifest: {MANIFEST}; run viz_33_year759.py first")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    items = manifest.get("items") or []
    if len(items) != 122:
        raise RuntimeError(f"prompt manifest should contain 122 scene jobs, found {len(items)}")
    keys = [item.get("key") for item in items]
    if any(not isinstance(key, str) or not key for key in keys) or len(set(keys)) != len(keys):
        raise RuntimeError("prompt manifest keys must be non-empty and unique")
    for item in items:
        key = item["key"]
        expected_output = f"generated_scenes/{key}.png"
        if item.get("output") != expected_output:
            raise RuntimeError(f"manifest output mismatch for {key}: {item.get('output')}")
        if item.get("model") != "gpt-image-2":
            raise RuntimeError(f"manifest model mismatch for {key}: {item.get('model')}")
        if not item.get("prompt"):
            raise RuntimeError(f"manifest prompt is empty for {key}")

    if args.only:
        wanted = set(args.only)
        items = [item for item in items if item["key"] in wanted]
        missing = wanted - {item["key"] for item in items}
        if missing:
            raise ValueError(f"unknown manifest keys: {sorted(missing)}")
    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("--limit must be a positive integer")
        items = items[:args.limit]
    if not items:
        raise RuntimeError("prompt manifest contains no selected jobs")
    return items


def planned_jobs(items: list[dict], force: bool) -> list[dict]:
    jobs = []
    for item in items:
        out = ASSET_DIR / f"{item['key']}.png"
        valid, note, dimensions = validate_png(out)
        action = "replace" if force and valid else ("skip_valid" if valid else "generate")
        jobs.append({
            "key": item["key"],
            "poet": item["poet"],
            "poem_title": item["poem_title"],
            "output": str(out),
            "action": action,
            "existing_validation": note,
            "existing_dimensions": dimensions,
        })
    return jobs


def generate_one(
    *, item: dict, out: Path, helper: Path, codex_home: Path, args: argparse.Namespace
) -> dict:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{item['key']}.", suffix=".png", dir=ASSET_DIR)
    os.close(handle)
    temp_path = Path(temp_name)
    temp_path.unlink()
    command = [
        sys.executable, str(helper),
        "--prompt", item["prompt"],
        "--model", args.model,
        "--size", item.get("size") or "1536x1024",
        "--quality", item.get("quality") or "medium",
        "--background", "opaque",
        "--timeout", str(args.timeout),
        "--codex-home", str(codex_home),
        "--out", str(temp_path),
    ]
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=None, check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "provider helper exited without details").strip()
            raise RuntimeError(f"provider does not support this job or returned an error: {detail[-1200:]}")
        valid, note, dimensions = validate_png(temp_path)
        if not valid:
            raise RuntimeError(f"provider output failed PNG validation: {note}")
        payload = temp_path.read_bytes()
        os.replace(temp_path, out)
        return {
            "key": item["key"],
            "path": str(out),
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "dimensions": dimensions,
        }
    finally:
        if temp_path.exists():
            temp_path.unlink()


def main() -> None:
    args = parse_args()
    if args.dry_run and args.execute:
        raise ValueError("--dry-run and --execute are mutually exclusive")
    if args.timeout < 0:
        raise ValueError("--timeout must be zero or greater")

    codex_home = resolve_codex_home(args.codex_home)
    helper = resolve_skill_helper(codex_home)
    provider = configured_provider_name(codex_home)
    items = load_selected_items(args)
    jobs = planned_jobs(items, args.force)
    mode = "execute" if args.execute else ("dry_run" if args.dry_run else "plan")
    report: dict = {
        "mode": mode,
        "provider": provider,
        "model": args.model,
        "helper": str(helper),
        "selected_count": len(items),
        "jobs": jobs,
        "generated": [],
        "skipped": [],
    }
    if not args.execute:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    for item, job in zip(items, jobs, strict=True):
        out = ASSET_DIR / f"{item['key']}.png"
        if job["action"] == "skip_valid":
            report["skipped"].append({"key": item["key"], "reason": "existing valid PNG"})
            continue
        try:
            report["generated"].append(
                generate_one(item=item, out=out, helper=helper, codex_home=codex_home, args=args)
            )
        except Exception as exc:
            report["failed"] = {"key": item["key"], "error": str(exc)}
            print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
            raise

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("[next] rerun viz_33_year759.py so the page revalidates per-scene assets")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(1)
