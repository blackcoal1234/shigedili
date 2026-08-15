"""Revalidate crawled poem bodies against their canonical source pages.

The source occasionally substitutes a small number of characters under load.
This tool fetches each unique source page once, requests extra samples only
when the first response does not match a stored version, and checkpoints the
work so a long validation run can be resumed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "poems.json"
DEFAULT_CHECKPOINT = ROOT / "data" / "poems_body_validation.partial.json"
DEFAULT_STATS = ROOT / "data" / "poems_body_validation_stats.json"


def load_spider():
    path = ROOT / "爬虫脚本" / "spider_gushiwen.py"
    spec = importlib.util.spec_from_file_location("spider_gushiwen", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load crawler: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def record_key(record: dict) -> tuple[str, str]:
    poet = str(record.get("poet") or record.get("author") or "")
    source_id = str(record.get("source_poem_id") or "")
    if source_id:
        return poet, source_id
    return poet, "body:" + str(record.get("body_hash") or sha256_text(str(record.get("body") or "")))


def fetch_body(spider, row: dict) -> tuple[str, str, str]:
    detail = spider.parse_poem_detail(spider.fetch(str(row["source_url"])))
    if not detail or not detail.get("body"):
        raise RuntimeError("source page has no parseable body")
    expected_author = str(row.get("poet") or row.get("author") or "")
    observed_author = str(detail.get("author") or expected_author)
    if expected_author and observed_author != expected_author:
        raise RuntimeError(f"author mismatch: expected {expected_author}, got {observed_author}")
    return str(detail["body"]), str(detail.get("title") or ""), observed_author


def per_character_consensus(samples: list[str]) -> str | None:
    if not samples or len({len(item) for item in samples}) != 1:
        return None
    threshold = len(samples) // 2 + 1
    output: list[str] = []
    for chars in zip(*samples):
        winner, count = Counter(chars).most_common(1)[0]
        if count < threshold:
            return None
        output.append(winner)
    return "".join(output)


def validate_group(spider, rows: list[dict], max_samples: int) -> tuple[dict, dict]:
    base = max(rows, key=lambda row: str(row.get("crawled_at") or ""))
    if not base.get("source_poem_id") or not base.get("source_url"):
        result = dict(base)
        result["content_validation"] = "no_source_id"
        return result, {
            "requests": 0,
            "changed": False,
            "versions_seen": len({str(row.get("body") or "") for row in rows}),
            "collapsed": len(rows) - 1,
            "mode": "no_source_id",
        }

    stored_bodies = {str(row.get("body") or "") for row in rows}
    samples: list[str] = []
    observed_title = ""
    observed_author = ""
    mode = ""
    canonical = ""

    first, observed_title, observed_author = fetch_body(spider, base)
    samples.append(first)
    if first in stored_bodies:
        canonical = first
        mode = "matched_stored_version"
    else:
        while len(samples) < max_samples:
            body, observed_title, observed_author = fetch_body(spider, base)
            samples.append(body)
            common, count = Counter(samples).most_common(1)[0]
            if count >= 2:
                canonical = common
                mode = "repeated_fresh_version"
                break
        if not canonical:
            canonical = per_character_consensus(samples) or ""
            mode = "per_character_consensus" if canonical else "unresolved"
    if not canonical:
        raise RuntimeError(
            f"no body consensus after {len(samples)} samples for {base.get('source_url')}"
        )

    matching_rows = [row for row in rows if str(row.get("body") or "") == canonical]
    selected = max(matching_rows, key=lambda row: str(row.get("crawled_at") or "")) if matching_rows else base
    result = dict(selected)
    result["body"] = canonical
    result["body_hash"] = sha256_text(canonical)
    result["content_validated_at"] = datetime.now(timezone.utc).isoformat()
    result["content_validation"] = mode
    result["content_validation_samples"] = len(samples)
    result["source_versions_seen"] = len(stored_bodies | set(samples))
    result["source_records_collapsed"] = len(rows) - 1
    if observed_title and observed_title != str(result.get("title") or ""):
        result["source_title_observed"] = observed_title
    if observed_author:
        result["author"] = observed_author
        result["poet"] = observed_author

    return result, {
        "requests": len(samples),
        "changed": canonical not in stored_bodies,
        "selected_nonlatest_version": canonical != str(base.get("body") or ""),
        "versions_seen": len(stored_bodies | set(samples)),
        "collapsed": len(rows) - 1,
        "mode": mode,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Revalidate poem bodies with source-page consensus")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--stats", type=Path, default=DEFAULT_STATS)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--max-samples", type=int, default=5)
    parser.add_argument("--checkpoint-every", type=int, default=250)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Validation-only limit; 0 processes all")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.workers < 1 or args.max_samples < 2 or args.checkpoint_every < 1 or args.limit < 0:
        raise SystemExit("invalid numeric argument")

    input_path = args.input.resolve()
    output_path = (args.output or input_path).resolve()
    checkpoint_path = args.checkpoint.resolve()
    stats_path = args.stats.resolve()
    input_digest = file_sha256(input_path)
    records = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("poems input must be a JSON array")

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    order: list[tuple[str, str]] = []
    for record in records:
        key = record_key(record)
        if key not in groups:
            order.append(key)
        groups[key].append(record)
    if args.limit:
        order = order[: args.limit]

    validated: dict[tuple[str, str], dict] = {}
    metrics: dict[tuple[str, str], dict] = {}
    if args.resume and checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("input_sha256") != input_digest:
            raise RuntimeError("checkpoint does not match current input file")
        for item in checkpoint.get("items", []):
            key = record_key(item["record"])
            if key in groups:
                validated[key] = item["record"]
                metrics[key] = item.get("metrics", {})
        print(f"[resume] {len(validated)}/{len(order)} source pages already validated")

    pending = [key for key in order if key not in validated]
    spider = load_spider()
    errors: dict[tuple[str, str], str] = {}

    def save_checkpoint() -> None:
        items = [
            {"record": validated[key], "metrics": metrics.get(key, {})}
            for key in order
            if key in validated
        ]
        write_json_atomic(
            checkpoint_path,
            {
                "schema_version": 1,
                "input": str(input_path),
                "input_sha256": input_digest,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "items": items,
            },
        )

    with ThreadPoolExecutor(max_workers=min(12, args.workers)) as pool:
        futures = {
            pool.submit(validate_group, spider, groups[key], args.max_samples): key
            for key in pending
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                record, result_metrics = future.result()
            except Exception as exc:
                errors[key] = str(exc)
            else:
                validated[key] = record
                metrics[key] = result_metrics
            done = len(validated) + len(errors)
            if done % 100 == 0 or done == len(order):
                print(
                    f"[{done}/{len(order)}] validated={len(validated)} errors={len(errors)} "
                    f"changed={sum(bool(v.get('changed')) for v in metrics.values())}"
                )
            if len(validated) % args.checkpoint_every == 0 or done == len(order):
                save_checkpoint()

    total_requests = sum(int(item.get("requests") or 0) for item in metrics.values())
    summary = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "input": str(input_path),
        "input_sha256": input_digest,
        "input_records": len(records),
        "unique_source_records": len(groups),
        "processed_source_records": len(order),
        "validated_source_records": len(validated),
        "errors": [
            {"poet": key[0], "source_id": key[1], "error": message}
            for key, message in sorted(errors.items())
        ],
        "requests": total_requests,
        "bodies_changed_to_new_version": sum(bool(v.get("changed")) for v in metrics.values()),
        "selected_nonlatest_stored_version": sum(
            bool(v.get("selected_nonlatest_version")) for v in metrics.values()
        ),
        "duplicate_source_records_collapsed": sum(int(v.get("collapsed") or 0) for v in metrics.values()),
        "validation_modes": dict(Counter(str(v.get("mode") or "") for v in metrics.values())),
        "complete": len(validated) == len(order) and not errors,
        "dry_run": args.dry_run,
    }
    write_json_atomic(stats_path, summary)

    if errors:
        save_checkpoint()
        raise SystemExit(f"validation has {len(errors)} unresolved source pages; rerun with --resume")
    if args.dry_run or args.limit:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    canonical = [validated[key] for key in order]
    backup = output_path.with_name(
        output_path.stem + "_backup_pre_body_validation_" + datetime.now().strftime("%Y%m%d_%H%M%S") + output_path.suffix
    )
    if output_path.exists():
        shutil.copy2(output_path, backup)
    write_json_atomic(output_path, canonical)
    checkpoint_path.unlink(missing_ok=True)
    summary["output"] = str(output_path)
    summary["output_records"] = len(canonical)
    summary["backup"] = str(backup)
    summary["output_sha256"] = file_sha256(output_path)
    write_json_atomic(stats_path, summary)
    print(f"[done] {len(records)} -> {len(canonical)} records; backup={backup.name}")


if __name__ == "__main__":
    main()
