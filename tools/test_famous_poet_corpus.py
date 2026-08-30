from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import famous_poet_corpus as corpus


class FakeConverter:
    _s2t = str.maketrans(
        {
            "\u540e": "\u5f8c",
            "\u5e84": "\u838a",
            "\u6b27": "\u6b50",
            "\u9633": "\u967d",
            "\u97e6": "\u97cb",
            "\u89c1": "\u898b",
            "\u6b22": "\u6b61",
            "\u8c22": "\u8b1d",
            "\u7ea2": "\u7d05",
        }
    )
    _t2s = str.maketrans({value: key for key, value in _s2t.items()})

    def convert(self, text: str, config: str) -> str:
        return text.translate(self._s2t if config == "s2t" else self._t2s)


class LossyConverter(FakeConverter):
    """Model OpenCC lexical substitutions that are unsafe for identity."""

    def convert(self, text: str, config: str) -> str:
        converted = super().convert(text, config)
        return converted.replace("射覆", "射复") if config == "t2s" else converted


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _canonical(path: Path, rows=None) -> Path:
    rows = rows or [
        {
            "author": "李煜",
            "poet": "李煜",
            "dynasty": "宋",
            "title": "相见欢",
            "body": "林花谢了春红。\n太匆匆。",
            "source_site": "古诗文网",
            "source_url": "https://example.test/c1",
            "source_poem_id": "c1",
            "body_hash": "canonical-hash-verbatim",
        },
        {
            "author": "韦庄",
            "poet": "韦庄",
            "dynasty": "唐",
            "title": "台城",
            "body": "江雨霏霏江草齐。",
            "source_site": "古诗文网",
            "source_url": "https://example.test/c2",
            "source_poem_id": "c2",
        },
    ]
    _write_json(path, rows)
    return path


def _source(root: Path, relative: str, rows) -> Path:
    path = root / relative
    _write_json(path, rows)
    return path


def _build(tmp_path: Path, canonical_rows=None):
    canonical = _canonical(tmp_path / "canonical.json", canonical_rows)
    source = tmp_path / "source"
    output = tmp_path / "full.jsonl.gz"
    manifest = tmp_path / "manifest.json"
    return canonical, source, output, manifest


def _read(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def _git(source: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(source), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _init_git_source(source: Path) -> str:
    _source(source, "全唐诗/poet.tang.0.json", [{"author": "韋莊", "title": "作", "paragraphs": ["正文。"], "id": "git-1"}])
    _git(source, "init")
    _git(source, "config", "user.email", "test@example.test")
    _git(source, "config", "user.name", "Corpus Test")
    _git(source, "add", "全唐诗/poet.tang.0.json")
    _git(source, "commit", "-m", "fixture")
    return _git(source, "rev-parse", "HEAD")


def _rewrite_rows(output: Path, manifest: Path, rows) -> None:
    payload = corpus._gzip_jsonl(rows)
    output.write_bytes(payload)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["output_sha256"] = hashlib.sha256(payload).hexdigest()
    manifest.write_text(json.dumps(data), encoding="utf-8")


def test_full_paragraphs_and_traditional_author_mapping(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    _source(
        source,
        "全唐诗/poet.tang.0.json",
        [{"author": "韋莊", "title": "長篇", "paragraphs": ["第一行。", "  第二行。  ", "末行。"], "id": "u1"}],
    )
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())

    row = next(row for row in _read(output) if row["source_work_id"] == "u1")
    assert row["poet"] == "韦庄"
    assert row["body_original"] == "第一行。\n  第二行。  \n末行。"
    assert row["body"].endswith("末行。")
    assert row["work_dynasty"] == "唐"
    assert row["source_dynasty_raw"] == "tang"


def test_canonical_preferred_and_duplicate_sources_merged(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    _source(
        source,
        "宋词/ci.song.0.json",
        [{"author": "李煜", "rhythmic": "相見歡", "paragraphs": ["林花謝了春紅。", "太匆匆。"]}],
    )
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())

    row = next(row for row in _read(output) if row["canonical_gushiwen_id"] == "c1")
    assert row["body_original"] == "林花谢了春红。\n太匆匆。"
    assert row["source_dataset"] == "canonical"
    assert row["canonical_match"] is True
    assert len(row["sources"]) == 2


def test_canonical_identity_uses_display_body_not_lossy_opencc(tmp_path):
    canonical_rows = [
        {
            "author": "李商隐",
            "dynasty": "唐",
            "title": "无题二首·其一",
            "body": "分曹射覆蜡灯红。",
            "source_poem_id": "05c6c4ccf634",
        }
    ]
    canonical, source, output, manifest = _build(tmp_path, canonical_rows)
    _source(
        source,
        "全唐诗/poet.tang.0.json",
        [
            {
                "author": "李商隐",
                "title": "无题二首·其一",
                "paragraphs": ["分曹射覆蜡灯红。"],
                "id": "upstream-lossy",
            }
        ],
    )
    fallback, source_kind = corpus.load_analysis_poems(
        tmp_path / "missing.gz", canonical
    )
    assert source_kind == "canonical"

    built = corpus.build_corpus(
        canonical, source, output, manifest, "rev-test", converter=LossyConverter()
    )
    row = _read(output)[0]

    assert row["body"] == "分曹射覆蜡灯红。"
    assert row["normalized_body_hash"] == hashlib.sha256(
        row["body"].encode("utf-8")
    ).hexdigest()
    assert row["dedupe_body_hash"] == hashlib.sha256(
        "分曹射复蜡灯红。".encode("utf-8")
    ).hexdigest()
    assert row["work_id"] == fallback[0]["work_id"]
    assert len(row["sources"]) == 2
    assert built["schema_version"] == corpus.SCHEMA_VERSION
    assert built["hash_definition"] == corpus.HASH_DEFINITION
    assert corpus.check_corpus(
        canonical, output, manifest, source, converter=LossyConverter()
    ) == []


def test_opencc_collision_never_merges_distinct_canonical_works(tmp_path):
    canonical_rows = [
        {
            "author": "诗人",
            "dynasty": "唐",
            "title": "同题甲",
            "body": "分曹射覆蜡灯红。",
            "source_poem_id": "canonical-a",
        },
        {
            "author": "诗人",
            "dynasty": "唐",
            "title": "同题乙",
            "body": "分曹射复蜡灯红。",
            "source_poem_id": "canonical-b",
        },
    ]
    canonical, source, output, manifest = _build(tmp_path, canonical_rows)
    source.mkdir()

    built = corpus.build_corpus(
        canonical, source, output, manifest, "rev-test", converter=LossyConverter()
    )
    rows = _read(output)

    assert len(rows) == 2
    assert {row["canonical_gushiwen_id"] for row in rows} == {
        "canonical-a",
        "canonical-b",
    }
    assert len({row["work_id"] for row in rows}) == 2
    assert len({row["dedupe_body_hash"] for row in rows}) == 1
    assert built["canonical_opencc_collision_groups"] == 1
    assert built["canonical_opencc_collision_records"] == 1
    assert corpus.check_corpus(
        canonical, output, manifest, source, converter=LossyConverter()
    ) == []


def test_same_title_different_body_is_not_deduplicated(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    _source(
        source,
        "宋词/ci.song.3.json",
        [
            {"author": "李煜", "rhythmic": "浪淘沙", "paragraphs": ["甲。"]},
            {"author": "李煜", "rhythmic": "浪淘沙", "paragraphs": ["乙。"]},
        ],
    )
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    variants = [row for row in _read(output) if row["title"] == "浪淘沙"]
    assert len(variants) == 2
    assert variants[0]["variant_group_id"] == variants[1]["variant_group_id"]
    assert variants[0]["work_id"] != variants[1]["work_id"]


@pytest.mark.parametrize(
    ("author", "canonical_dynasty", "expected"),
    [("李煜", "宋", "五代·南唐"), ("欧阳炯", "唐", "五代·前后蜀"), ("韦庄", "宋", "唐末·前蜀")],
)
def test_person_period_overrides_bad_canonical_dynasty(tmp_path, author, canonical_dynasty, expected):
    rows = [{"author": author, "dynasty": canonical_dynasty, "title": "题", "body": "正文。", "source_poem_id": "x"}]
    canonical, source, output, manifest = _build(tmp_path, rows)
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    assert _read(output)[0]["person_period"] == expected
    assert _read(output)[0]["work_dynasty"] == canonical_dynasty
    assert _read(output)[0]["source_dynasty_raw"] == canonical_dynasty


def test_numeric_only_source_file_filter(tmp_path):
    root = tmp_path / "source"
    for relative in [
        "全唐诗/poet.tang.0.json",
        "全唐诗/poet.song.1000.json",
        "宋词/ci.song.2.json",
        "宋词/ci.song.2019y.json",
        "全唐诗/poet.tang.a.json",
    ]:
        _source(root, relative, [])
    assert [item.relative_path for item in corpus.discover_source_files(root)] == [
        "全唐诗/poet.song.1000.json",
        "全唐诗/poet.tang.0.json",
        "宋词/ci.song.2.json",
    ]


def test_two_builds_are_byte_deterministic_and_check_passes(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    _source(source, "全唐诗/poet.tang.0.json", [{"author": "韋莊", "title": "新作", "paragraphs": ["全文。"]}])
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    first = (hashlib.sha256(output.read_bytes()).hexdigest(), manifest.read_bytes())
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    second = (hashlib.sha256(output.read_bytes()).hexdigest(), manifest.read_bytes())
    assert first == second
    assert corpus.check_corpus(canonical, output, manifest, source, converter=FakeConverter()) == []
    assert corpus.main(["check", "--canonical", str(canonical), "--output", str(output), "--manifest", str(manifest), "--no-source-verify"]) == 0


def test_check_rejects_tampered_manifest_and_corpus(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["record_count"] += 1
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert corpus.check_corpus(canonical, output, manifest)
    assert corpus.main(["check", "--canonical", str(canonical), "--output", str(output), "--manifest", str(manifest)]) == 1

    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    raw = bytearray(output.read_bytes())
    raw[-5] ^= 1
    output.write_bytes(raw)
    assert corpus.check_corpus(canonical, output, manifest)


def test_loader_full_and_fallback(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    rows, source_kind = corpus.load_analysis_poems(
        output, canonical, manifest_path=manifest
    )
    assert source_kind == "canonical"
    assert rows[0]["author"] == "李煜"
    assert rows[0]["canonical_gushiwen_id"] == "c1"
    assert rows[0]["work_id"].startswith("fw_")
    fallback_work_ids = {row["canonical_gushiwen_id"]: row["work_id"] for row in rows}

    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    rows, source_kind = corpus.load_analysis_poems(
        output, canonical, manifest_path=manifest
    )
    assert source_kind == "analysis_full"
    canonical_row = next(row for row in rows if row["canonical_gushiwen_id"] == "c1")
    assert {"author", "dynasty", "title", "body", "body_hash"} <= canonical_row.keys()
    assert canonical_row["body_hash"] == "canonical-hash-verbatim"
    assert canonical_row["work_id"] == fallback_work_ids["c1"]
    with pytest.raises(FileNotFoundError):
        corpus.load_analysis_poems(tmp_path / "missing.gz", canonical, fallback=False)


def test_repository_full_canonical_ids_exhaustively_match_fallback(tmp_path):
    canonical_path = corpus.REPO_ROOT / corpus.DEFAULT_CANONICAL
    full_path = corpus.REPO_ROOT / corpus.DEFAULT_OUTPUT
    fallback_rows, source_kind = corpus.load_analysis_poems(
        tmp_path / "missing-full.gz", canonical_path
    )
    assert source_kind == "canonical"
    expected: dict[str, str] = {}
    for row in fallback_rows:
        canonical_id = row.get("canonical_gushiwen_id")
        assert canonical_id
        assert canonical_id not in expected
        expected[canonical_id] = row["work_id"]

    actual: dict[str, str] = {}
    for row in corpus._read_jsonl_gzip(full_path):
        canonical_id = row.get("canonical_gushiwen_id")
        if not canonical_id:
            continue
        assert canonical_id not in actual
        actual[canonical_id] = row["work_id"]

    assert len(expected) == 20_437
    assert actual == expected
    assert actual["05c6c4ccf634"] == "fw_f459297a02cdff04d945b4f6"


def test_custom_existing_full_requires_explicit_manifest(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())

    with pytest.raises(ValueError, match="显式提供 manifest_path"):
        corpus.load_analysis_poems(output, canonical)

    rows, source_kind = corpus.load_analysis_poems(
        output, canonical, manifest_path=manifest
    )
    assert source_kind == "analysis_full"
    assert rows


def test_loader_rejects_stale_canonical(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    canonical.write_bytes(canonical.read_bytes() + b"\n")

    with pytest.raises(RuntimeError, match="canonical_sha256"):
        corpus.load_analysis_poems(
            output, canonical, manifest_path=manifest
        )


def test_loader_accepts_equivalent_canonical_line_endings(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    canonical_rows = json.loads(canonical.read_text(encoding="utf-8"))
    canonical.write_text(
        json.dumps(canonical_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\r\n",
    )
    corpus.build_corpus(
        canonical,
        source,
        output,
        manifest,
        "rev-test",
        converter=FakeConverter(),
    )

    canonical.write_bytes(canonical.read_bytes().replace(b"\r\n", b"\n"))

    rows, source_kind = corpus.load_analysis_poems(
        output,
        canonical,
        manifest_path=manifest,
    )
    assert source_kind == "analysis_full"
    assert rows


def test_loader_rejects_damaged_full_corpus(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    damaged = bytearray(output.read_bytes())
    damaged[-5] ^= 1
    output.write_bytes(damaged)

    with pytest.raises(RuntimeError, match="output_sha256"):
        corpus.load_analysis_poems(
            output, canonical, manifest_path=manifest
        )


def test_loader_rejects_wrong_record_count(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["record_count"] += 1
    manifest.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(RuntimeError, match="record_count"):
        corpus.load_analysis_poems(
            output, canonical, manifest_path=manifest
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.update(version=data["version"] - 1),
        lambda data: data["hash_definition"].update(work_id="outdated"),
    ],
)
def test_loader_rejects_outdated_identity_manifest(tmp_path, mutate):
    canonical, source, output, manifest = _build(tmp_path)
    corpus.build_corpus(
        canonical, source, output, manifest, "rev-test", converter=FakeConverter()
    )
    data = json.loads(manifest.read_text(encoding="utf-8"))
    mutate(data)
    manifest.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(RuntimeError, match="schema/hash_definition"):
        corpus.load_analysis_poems(output, canonical, manifest_path=manifest)


def test_loader_rejects_missing_manifest_for_existing_full(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    manifest.unlink()

    with pytest.raises(RuntimeError, match="manifest 缺失"):
        corpus.load_analysis_poems(
            output, canonical, manifest_path=manifest
        )


def test_loader_defaults_are_anchored_to_repo_root(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    canonical = _canonical(repo / corpus.DEFAULT_CANONICAL)
    source = repo / "source"
    output = repo / corpus.DEFAULT_OUTPUT
    manifest = repo / corpus.DEFAULT_MANIFEST
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(corpus, "REPO_ROOT", repo)
    monkeypatch.chdir(elsewhere)

    rows, source_kind = corpus.load_analysis_poems()

    assert source_kind == "analysis_full"
    assert len(rows) == json.loads(manifest.read_text(encoding="utf-8"))["record_count"]


def test_cli_defaults_are_repo_anchored_and_manifest_labels_stable(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    _canonical(repo / corpus.DEFAULT_CANONICAL)
    source = repo / corpus.DEFAULT_SOURCE_ROOT
    _init_git_source(source)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(corpus, "REPO_ROOT", repo)
    monkeypatch.setattr(corpus, "_OpenCCConverter", FakeConverter)
    monkeypatch.chdir(elsewhere)

    assert corpus.main(["build"]) == 0
    manifest_path = repo / corpus.DEFAULT_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["build_parameters"] == {
        "canonical": corpus.DEFAULT_CANONICAL.as_posix(),
        "manifest": corpus.DEFAULT_MANIFEST.as_posix(),
        "output": corpus.DEFAULT_OUTPUT.as_posix(),
        "source_root": corpus.DEFAULT_SOURCE_ROOT.as_posix(),
        "source_revision": manifest["upstream"]["commit"],
    }
    assert corpus.main(["check"]) == 0


def test_atomic_dump_json_is_compact_streamed_and_newline_terminated(tmp_path, monkeypatch):
    target = tmp_path / "stats.json"

    def forbid_dumps(*_args, **_kwargs):
        raise AssertionError("atomic_dump_json must stream through json.dump")

    monkeypatch.setattr(corpus.json, "dumps", forbid_dumps)
    corpus.atomic_dump_json(target, {"汉": "字", "values": [1, 2]})

    assert target.read_bytes() == '{"汉":"字","values":[1,2]}\n'.encode("utf-8")


def test_atomic_dump_json_replace_failure_preserves_old_file(tmp_path, monkeypatch):
    target = tmp_path / "stats.json"
    target.write_text("old\n", encoding="utf-8")

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(corpus.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        corpus.atomic_dump_json(target, {"new": True})

    assert target.read_text(encoding="utf-8") == "old\n"
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []


def test_cli_build_reports_missing_opencc_clearly(tmp_path, monkeypatch, capsys):
    canonical, source, output, manifest = _build(tmp_path)

    def missing_converter():
        raise RuntimeError("opencc-python-reimplemented==0.1.7 is required")

    monkeypatch.setattr(corpus, "_OpenCCConverter", missing_converter)
    result = corpus.main(
        [
            "build",
            "--canonical",
            str(canonical),
            "--source-root",
            str(source),
            "--output",
            str(output),
            "--manifest",
            str(manifest),
            "--source-revision",
            "rev-test",
        ]
    )
    assert result == 1
    assert "opencc-python-reimplemented==0.1.7" in capsys.readouterr().out


def test_period_dataset_gate_rejects_cross_dynasty_names(tmp_path):
    canonical_rows = [
        {"author": "高适", "dynasty": "唐", "title": "甲", "body": "高适规范。"},
        {"author": "杨万里", "dynasty": "宋", "title": "乙", "body": "杨万里规范。"},
        {"author": "韦庄", "dynasty": "宋", "title": "丙", "body": "韦庄规范。"},
    ]
    canonical, source, output, manifest = _build(tmp_path, canonical_rows)
    _source(source, "全唐诗/poet.song.0.json", [{"author": "高适", "title": "误收", "paragraphs": ["不应进入。"]}])
    _source(source, "全唐诗/poet.tang.0.json", [
        {"author": "杨万里", "title": "误收", "paragraphs": ["也不应进入。"]},
        {"author": "韋莊", "title": "正收", "paragraphs": ["唐诗正例。"]},
        {"author": "高适", "title": "空作", "paragraphs": []},
    ])
    _source(source, "宋词/ci.song.0.json", [{"author": "韋莊", "rhythmic": "正收", "paragraphs": ["宋词正例。"]}])
    built = corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    bodies = {row["body"] for row in _read(output)}
    assert "不应进入。" not in bodies
    assert "也不应进入。" not in bodies
    assert {"唐诗正例。", "宋词正例。"} <= bodies
    assert built["upstream_raw_matched"] == 5
    assert built["period_rejected"] == 2
    assert built["period_rejected_by_dataset"] == {"poet.song": 1, "poet.tang": 1}
    assert built["period_rejected_by_poet"] == {"杨万里": 1, "高适": 1}
    assert built["empty_skipped"] == 1
    assert built["empty_skipped_by_dataset"] == {"poet.tang": 1}
    assert built["empty_skipped_by_poet"] == {"高适": 1}
    assert corpus.check_corpus(canonical, output, manifest, source, converter=FakeConverter()) == []


def test_identical_source_occurrences_are_not_collapsed(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    duplicate = {"author": "韋莊", "title": "重复", "paragraphs": ["相同正文。"], "id": "same-id"}
    _source(source, "全唐诗/poet.tang.0.json", [duplicate, duplicate])
    built = corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    row = next(row for row in _read(output) if row["body"] == "相同正文。")
    assert len(row["sources"]) == 2
    assert built["accepted_input_count"] == sum(len(item["sources"]) for item in _read(output))
    assert built["deduplicated_count"] == built["accepted_input_count"] - built["record_count"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["upstream"].update(license="bad"),
        lambda data: data["upstream"].update(commit="wrong"),
        lambda data: data.update(matched_files=["宋词/ci.song.2019y.json"]),
        lambda data: data.update(accepted_input_count=data["accepted_input_count"] + 1),
        lambda data: data["counts"]["poet"].update({"李煜": 999}),
    ],
)
def test_check_rejects_manifest_semantic_tampering(tmp_path, mutate):
    canonical, source, output, manifest = _build(tmp_path)
    _source(source, "全唐诗/poet.tang.0.json", [])
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    data = json.loads(manifest.read_text(encoding="utf-8"))
    mutate(data)
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert corpus.check_corpus(canonical, output, manifest, source, converter=FakeConverter())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: row.update(body=""),
        lambda row: row.update(body_original=""),
        lambda row: row.update(author="错误作者"),
        lambda row: row.update(body_original_hash="bad"),
        lambda row: row["sources"][0].update(body_original_hash="bad"),
        lambda row: row["sources"][0].update(source_url="https://wrong.test"),
        lambda row: row.update(sources=["not-an-object"]),
    ],
)
def test_check_rejects_row_semantic_tampering(tmp_path, mutate):
    canonical, source, output, manifest = _build(tmp_path)
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    rows = _read(output)
    mutate(rows[0])
    _rewrite_rows(output, manifest, rows)
    assert corpus.check_corpus(canonical, output, manifest)


def test_iter_json_array_chunk_one_and_strict_errors(tmp_path):
    valid = tmp_path / "valid.json"
    valid.write_text('[{"a":1},{"b":"二"}]', encoding="utf-8")
    assert list(corpus._iter_json_array(valid, chunk_size=1)) == [{"a": 1}, {"b": "二"}]
    malformed = {
        "trailing-comma.json": '[{"a":1},]',
        "trailing-garbage.json": '[{"a":1}] garbage',
        "missing-comma.json": '[{"a":1} {"b":2}]',
        "unclosed.json": '[{"a":1}',
    }
    for name, text in malformed.items():
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError):
            list(corpus._iter_json_array(path, chunk_size=1))


def test_iter_json_array_numbers_cross_chunk_boundaries(tmp_path):
    path = tmp_path / "numbers.json"
    path.write_text("[12,1.25,1e10,-12]", encoding="utf-8")
    assert list(corpus._iter_json_array(path, chunk_size=1)) == [12, 1.25, 1e10, -12]


def test_upstream_body_hash_tracks_simplified_analysis_body(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    _source(
        source,
        "宋词/ci.song.0.json",
        [{"author": "李煜", "rhythmic": "新詞", "paragraphs": ["花謝春紅。"], "id": "traditional"}],
    )
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    row = next(row for row in _read(output) if row["source_work_id"] == "traditional")
    assert row["body"] == "花谢春红。"
    assert row["body_hash"] == row["normalized_body_hash"]
    assert row["sources"][0]["body_hash"] == row["normalized_body_hash"]
    row["body_hash"] = "forged"
    row["sources"][0]["body_hash"] = "forged"
    rows = _read(output)
    rows = [row if item["source_work_id"] == "traditional" else item for item in rows]
    _rewrite_rows(output, manifest, rows)
    assert corpus.check_corpus(canonical, output, manifest)


@pytest.mark.parametrize("target", ["top", "source"])
def test_check_rejects_normalized_original_whitespace_tampering(tmp_path, target):
    canonical, source, output, manifest = _build(tmp_path)
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    rows = _read(output)
    row = rows[0]
    if target == "top":
        row["body_original"] = " " + row["body_original"]
        row["body_original_hash"] = hashlib.sha256(row["body_original"].encode()).hexdigest()
        row["sources"][0]["body_original"] = row["body_original"]
        row["sources"][0]["body_original_hash"] = row["body_original_hash"]
    else:
        source_item = row["sources"][0]
        source_item["body_original"] += " "
        source_item["body_original_hash"] = hashlib.sha256(source_item["body_original"].encode()).hexdigest()
    _rewrite_rows(output, manifest, rows)
    assert corpus.check_corpus(canonical, output, manifest)


@pytest.mark.parametrize("field", ["work_id", "variant_group_id", "body_hash"])
def test_check_rejects_stable_identity_or_canonical_hash_tampering(tmp_path, field):
    canonical, source, output, manifest = _build(tmp_path)
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    rows = _read(output)
    row = next(item for item in rows if item["canonical_gushiwen_id"] == "c1")
    row[field] = "tampered"
    if field == "body_hash":
        row["sources"][0]["body_hash"] = "tampered"
    _rewrite_rows(output, manifest, rows)
    assert corpus.check_corpus(canonical, output, manifest)


@pytest.mark.parametrize("field", ["body_original", "source_work_id"])
def test_source_verify_rejects_equal_count_source_replacement(tmp_path, field):
    canonical, source, output, manifest = _build(tmp_path)
    duplicate = {"author": "韋莊", "title": "重复", "paragraphs": ["相同正文。"], "id": "same-id"}
    _source(source, "全唐诗/poet.tang.0.json", [duplicate, duplicate])
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    rows = _read(output)
    row = next(item for item in rows if item["body"] == "相同正文。")
    source_item = row["sources"][1]
    source_item[field] = "伪造替换。" if field == "body_original" else "forged-id"
    if field == "body_original":
        source_item["body_original_hash"] = hashlib.sha256(source_item[field].encode()).hexdigest()
    _rewrite_rows(output, manifest, rows)
    assert corpus.check_corpus(canonical, output, manifest, source, converter=FakeConverter())


def test_check_rejects_both_manifest_revisions_tampered(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    _source(source, "全唐诗/poet.tang.0.json", [{"author": "韋莊", "title": "作", "paragraphs": ["正文。"]}])
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["upstream"]["commit"] = "forged-revision"
    data["build_parameters"]["source_revision"] = "forged-revision"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert corpus.check_corpus(canonical, output, manifest, source, converter=FakeConverter())


def test_check_rejects_git_head_revision_mismatch(tmp_path, monkeypatch):
    canonical, source, output, manifest = _build(tmp_path)
    _source(source, "全唐诗/poet.tang.0.json", [])
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    monkeypatch.setattr(corpus, "_try_git_revision", lambda _root: "different-head")
    assert corpus.check_corpus(canonical, output, manifest, source, converter=FakeConverter())


def test_canonical_body_hash_is_checked_against_canonical_identity(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    corpus.build_corpus(canonical, source, output, manifest, "rev-test", converter=FakeConverter())
    rows = _read(output)
    row = next(item for item in rows if item["canonical_gushiwen_id"] == "c1")
    row["body_hash"] = "same-forged-value"
    canonical_source = next(item for item in row["sources"] if item["source_dataset"] == "canonical")
    canonical_source["body_hash"] = "same-forged-value"
    _rewrite_rows(output, manifest, rows)
    assert corpus.check_corpus(canonical, output, manifest)


def test_git_revision_rejects_ordinary_subdirectory_of_parent_repo(tmp_path):
    parent = tmp_path / "parent-repo"
    parent.mkdir()
    _git(parent, "init")
    _git(parent, "config", "user.email", "test@example.test")
    _git(parent, "config", "user.name", "Corpus Test")
    marker = parent / "marker.txt"
    marker.write_text("parent", encoding="utf-8")
    _git(parent, "add", "marker.txt")
    _git(parent, "commit", "-m", "parent fixture")
    source = parent / "ordinary-child"
    source.mkdir()
    with pytest.raises(RuntimeError, match="Git checkout root"):
        corpus._git_revision(source)


def test_clean_independent_git_source_build_and_check(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    revision = _init_git_source(source)
    built = corpus.build_corpus(canonical, source, output, manifest, converter=FakeConverter())
    assert built["upstream"]["commit"] == revision
    assert corpus.check_corpus(canonical, output, manifest, source, converter=FakeConverter()) == []


def test_explicit_revision_on_git_requires_head_and_clean_targets(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    revision = _init_git_source(source)
    built = corpus.build_corpus(
        canonical,
        source,
        output,
        manifest,
        revision,
        converter=FakeConverter(),
    )
    assert built["upstream"]["commit"] == revision

    with pytest.raises(RuntimeError, match="HEAD"):
        corpus.build_corpus(
            canonical,
            source,
            output,
            manifest,
            "wrong-revision",
            converter=FakeConverter(),
        )

    tracked = source / "全唐诗/poet.tang.0.json"
    tracked.write_text(tracked.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="numeric source files"):
        corpus.build_corpus(
            canonical,
            source,
            output,
            manifest,
            revision,
            converter=FakeConverter(),
        )


def test_git_source_dirty_and_untracked_numeric_files_are_rejected(tmp_path):
    canonical, source, output, manifest = _build(tmp_path)
    _init_git_source(source)
    corpus.build_corpus(canonical, source, output, manifest, converter=FakeConverter())

    tracked = source / "全唐诗/poet.tang.0.json"
    tracked.write_text(tracked.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="numeric source files"):
        corpus.build_corpus(canonical, source, output, manifest, converter=FakeConverter())
    assert corpus.check_corpus(canonical, output, manifest, source, converter=FakeConverter())

    _git(source, "checkout", "--", "全唐诗/poet.tang.0.json")
    _source(source, "宋词/ci.song.9.json", [])
    with pytest.raises(RuntimeError, match="numeric source files"):
        corpus.build_corpus(canonical, source, output, manifest, converter=FakeConverter())
    assert corpus.check_corpus(canonical, output, manifest, source, converter=FakeConverter())


def test_non_object_manifest_is_clear_check_and_cli_error(tmp_path, capsys):
    canonical, source, output, manifest = _build(tmp_path)
    output.write_bytes(b"not-used")
    manifest.write_text("[]", encoding="utf-8")
    errors = corpus.check_corpus(canonical, output, manifest)
    assert errors and "JSON object" in errors[0]
    result = corpus.main(
        [
            "check",
            "--canonical",
            str(canonical),
            "--output",
            str(output),
            "--manifest",
            str(manifest),
            "--no-source-verify",
        ]
    )
    assert result == 1
    assert "JSON object" in capsys.readouterr().out
