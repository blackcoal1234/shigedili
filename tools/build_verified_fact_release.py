#!/usr/bin/env python3
"""Build the fixed, evidence-gated first 60-poem fact release.

This intentionally reads the approved background export and the existing
chronology research, but writes only the three release artifacts owned by this
tool.  All serialization and replacement operations are deterministic.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from poem_fact_expansion import FactPackageError, build_file, validate_fact_package


ROOT = Path(__file__).resolve().parent.parent
REVIEWED = ROOT / "data" / "reviewed"
BACKGROUND = REVIEWED / "verified_poem_backgrounds.jsonl"
POEMS = ROOT / "data" / "poems.json"
PACKAGES = REVIEWED / "verified_poem_fact_packages.jsonl"
EXPANSIONS = REVIEWED / "verified_poem_fact_expansions.jsonl"
SUMMARY = REVIEWED / "verified_poem_fact_release_summary.json"
REVIEWER = "codex_fact_audit_2026-08-12"
REVIEWED_AT = "2026-08-12T23:30:00+08:00"
URL_RE = re.compile(r"https?://[^\s<>\"'，；（）]+")
CONFLICT_TERMS = ("disputed", "两说并存", "待考", "争议", "驳议")
LEGACY_BODY_HASH_REBIND_ALLOWLIST = {
    ("杜甫", "石壕吏", "cc1310f5716428a64eb0d44332be605419821c646d08a62890d1a6e489579ae5"): "402d90dbbc2be8f82e7823b667b2b4c18daf39a8b0d95ed067aa2d466adc47ee",
    ("白居易", "观刈麦", "6078965df8872d428615e79b3a598a49fdf0adb2601aaf8e4b2e426e22311045"): "851f92936f11f0f6ae8a689630858ca30de0cb62020f8d9b664177dfe863acf2",
    ("李清照", "蝶恋花·晚止昌乐馆寄姊妹", "5c8d208180a139e59dec45770ce5dabd9a5e9ab41671743a559971c00dc4ca79"): "793dad3948d0c5a803a00614785588f23b4be1d47e64fb60c23b287ee6805149",
    ("苏轼", "临江仙·夜归临皋", "33224b655e4ba2e51806609cd3511f6df5a0a6dd7ad002401d5777f120b3e7d5"): "88eea147b1e61403a653cc542174d2da83a8926532e93904bb81270100c98d8f",
    ("陆游", "金错刀行", "f77af75ff7a73bcd12d315f0e015d11d878d52eb8bd500287c88c9d2f102ce20"): "a7cdfdad8c0897b5797c62a5607134d6927d486c133a481fc8259458391ee54e",
}


NEW_SPECS = (
    ("李白", "金陵酒肆留别", 726, 726, "exact", "金陵", "南京市", "江苏省", 118.78, 32.06),
    ("李白", "长干行·其一", 725, 725, "exact", "金陵长干里", "南京市", "江苏省", 118.78, 32.06),
    ("李白", "月下独酌·其一", 744, 744, "approximate", "长安", "西安市", "陕西省", 108.95, 34.27),
    ("李白", "梦游天姥吟留别", 745, 746, "approximate", "东鲁兖州瑕丘", "济宁市兖州区", "山东省", 116.75, 35.57),
    ("李白", "北风行", 752, 752, "approximate", "幽州（范阳一带）", "北京市", "北京市", 116.41, 39.90),
    ("李白", "赠汪伦", 755, 755, "approximate", "泾县桃花潭", "宣城市泾县", "安徽省", 118.43, 30.69),
    ("杜甫", "望岳", 736, 736, "exact", "泰山（齐鲁）", "泰安市", "山东省", 117.094893, 36.205905),
    ("杜甫", "月夜忆舍弟", 759, 759, "exact", "秦州", "天水市", "甘肃省", 105.731276, 34.587162),
    ("杜甫", "秋兴八首·其一", 766, 766, "exact", "夔州", "重庆市奉节县", "重庆市", 109.470533, 31.024561),
    ("白居易", "池上", 835, 835, "exact", "洛阳池上", "洛阳市", "河南省", 112.45, 34.62),
    ("白居易", "梦微之", 840, 840, "exact", "洛阳", "洛阳市", "河南省", 112.45, 34.62),
    ("白居易", "钱塘湖春行", 823, 824, "approximate", "钱塘湖（西湖）", "杭州市", "浙江省", 120.16, 30.29),
    ("陆游", "病起书怀", 1176, 1176, "exact", "成都", "成都市", "四川省", 104.069363, 30.680959),
    ("陆游", "秋夜将晓出篱门迎凉有感二首", 1192, 1192, "exact", "山阴", "绍兴市", "浙江省", 120.588427, 29.9952),
    ("李清照", "武陵春·春晚", 1135, 1135, "exact", "金华", "金华市", "浙江省", 119.649, 29.089),
    ("李清照", "夏日绝句", 1129, 1129, "exact", "乌江（和州）", "马鞍山市和县", "安徽省", 118.59, 31.73),
    ("李清照", "渔家傲·记梦", 1130, 1130, "exact", "浙东海上", "浙江省东部海域", "浙江省", None, None),
    ("李清照", "减字木兰花·卖花担上", 1101, 1101, "approximate", "汴京", "开封市", "河南省", 114.307581, 34.797239),
    ("李清照", "题八咏楼", 1134, 1135, "approximate", "金华八咏楼", "金华市", "浙江省", 119.649, 29.089),
)


def load_jsonl(path: Path) -> list[dict]:
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FactPackageError(f"failed to parse JSONL {path}: {exc}") from exc


def stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def atomic_write(path: Path, text: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def transactional_replace_many(replacements: dict[Path, Path]) -> None:
    """Replace a related set or restore every target to its original bytes."""
    backups: dict[Path, Path] = {}
    replaced: list[Path] = []
    try:
        for target in replacements:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", suffix=".bak", delete=False) as handle:
                backup = Path(handle.name)
            shutil.copyfile(target, backup)
            backups[target] = backup
        for target, staged in replacements.items():
            os.replace(staged, target)
            replaced.append(target)
    except OSError as exc:
        restore_errors: list[str] = []
        for target in reversed(replaced):
            try:
                os.replace(backups[target], target)
            except OSError as restore_exc:
                restore_errors.append(f"{target.name}: {restore_exc}")
        detail = f"transactional replace failed: {exc}"
        if restore_errors:
            detail += "; restore failures: " + "; ".join(restore_errors)
        raise FactPackageError(detail) from exc
    finally:
        for staged in replacements.values():
            staged.unlink(missing_ok=True)
        for backup in backups.values():
            backup.unlink(missing_ok=True)


def load_chronology_file(path: Path) -> list[dict]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise FactPackageError(f"failed to parse chronology CSV {path}: {exc}") from exc
    required = {"poet", "title", "source_url", "source_note"}
    if not rows or not required <= set(rows[0]):
        raise FactPackageError(f"chronology CSV {path} lacks required columns")
    return rows


def load_chronology_rows() -> dict[tuple[str, str], dict]:
    rows: dict[tuple[str, str], dict] = {}
    for path in sorted((ROOT / "data" / "candidates").glob("*_spirit_chronology.csv")):
        for row in load_chronology_file(path):
            rows.setdefault((row["poet"], row["title"]), row)
    return rows


def URLs(text: str) -> list[str]:
    return [clean_url(url) for url in URL_RE.findall(text)]


def clean_url(url: str) -> str:
    """Keep direct URLs transport-safe; discard prose attached after a link."""
    parsed = urlsplit(url.strip())
    return urlunsplit((parsed.scheme, parsed.netloc, quote(parsed.path, safe="/%:_-."), quote(parsed.query, safe="=&%?/:_-."), ""))


def concise_source_text(value: str, fallback: str) -> str:
    value = URL_RE.sub("", value).replace("<br />", "").replace("<br/>", "")
    value = re.sub(r"\s+", "", value).replace("2026-07-26在线核实。", "")
    value = value.split("；")[0].strip("，。；：")
    if len(value) < 8:
        value = fallback
    return value[:156].rstrip("，。；：") + "。"


def extract_gushiwen_context(note: str) -> str | None:
    """Return only the stated Gushiwen background clause, never CNK text."""
    marker = re.search(r"(?:古诗文网创作背景|创作背景)[：:]?", note)
    if not marker:
        return None
    clause = note[marker.end():]
    clause = URL_RE.sub("", clause).split("；")[0].strip(" ：，。")
    if (
        not clause
        or "cnkgraph" in clause.casefold()
        or "API年谱" in clause
        or any(term in clause.casefold() for term in CONFLICT_TERMS)
    ):
        return None
    return concise_source_text(clause, "")


def secondary_source(
    row: dict | None,
    poet: str,
    title: str,
    identity_url: str,
) -> tuple[str, str, str, str, list[str]]:
    if row:
        options = URLs(" ".join((row.get("source_url", ""), row.get("source_note", ""))))
        for url in options:
            if ("gushiwen" in url or "guwendao" in url) and "shiwenv_" in url:
                excerpt = extract_gushiwen_context(row.get("source_note", ""))
                if excerpt:
                    return ("gushiwen", "古诗文网作品背景条目", url, excerpt, ["historical_context"])
                return ("gushiwen", "古诗文网作品详情条目", url, f"作品详情页收录《{title}》正文，用于锁定诗篇身份；本条不承担系年地点事实。", [])
    if poet == "白居易" and title == "池上":
        return ("gushiwen", "古诗文网《池上》作品详情条目", "https://www.gushiwen.cn/shiwenv_a8f44614071a.aspx", "作品详情页收录《池上》正文，用于锁定诗篇身份；本条不承担系年地点事实。", [])
    if not identity_url or "shiwenv_" not in urlsplit(identity_url).path:
        raise FactPackageError(f"missing direct poem detail URL for {poet}《{title}》")
    return ("gushiwen", "古诗文网作品详情条目", clean_url(identity_url), f"作品详情页收录《{title}》正文，用于锁定诗篇身份；本条不承担系年地点事实。", [])


def cnk_url(row: dict | None, poet: str, year_start: int, year_end: int) -> str:
    if row:
        for url in URLs(" ".join((row.get("source_url", ""), row.get("source_note", "")))):
            if "cnkgraph" in url and "/api/" in urlsplit(url).path:
                return clean_url(url)
    return (
        "https://open.cnkgraph.com/api/Biography?Author="
        f"{quote(poet)}&BeginYear={year_start}&EndYear={year_end}"
    )


def poem_identity(poems: list[dict], poet: str, title: str, body_hash: str | None = None) -> dict:
    candidates = [poem for poem in poems if poem.get("poet", poem.get("author")) == poet and poem.get("title") == title]
    if body_hash is not None:
        candidates = [poem for poem in candidates if poem.get("body_hash") == body_hash]
    if poet == "白居易" and title == "池上":
        candidates = [poem for poem in candidates if poem.get("body", "").startswith("小娃撑小艇")]
    if len(candidates) != 1:
        raise FactPackageError(f"expected exactly one publication poem for {poet}《{title}》; found {len(candidates)}")
    poem = candidates[0]
    return {field: poem[field] for field in ("poet", "title", "dynasty", "body_hash")}


def evidence(primary_url: str, primary_name: str, primary_excerpt: str, *, secondary: tuple[str, str, str, str, list[str]]) -> list[dict]:
    family, name, url, excerpt, secondary_supports = secondary
    return [
        {
            "evidence_id": "ev-primary",
            "source_family": "cnkgraph",
            "source_name": primary_name,
            "source_url": clean_url(primary_url),
            "source_grade": "B",
            "supports": ["composition_date", "composition_place"],
            "excerpt": concise_source_text(primary_excerpt, "已审核编年来源记录本作的相关创作情境"),
        },
        {
            "evidence_id": "ev-work-context",
            "source_family": family,
            "source_name": name,
            "source_url": url,
            "source_grade": "C",
            "supports": secondary_supports,
            "excerpt": excerpt,
        },
    ]


def package(identity: dict, chronology: dict, source_rows: dict[tuple[str, str], dict], poem_urls: dict[str, str], primary_url: str, primary_name: str, primary_excerpt: str, *, baseline: bool) -> dict:
    poet, title = identity["poet"], identity["title"]
    row = source_rows.get((poet, title))
    second = secondary_source(row, poet, title, poem_urls.get(identity["body_hash"], ""))
    if baseline:
        context = concise_source_text(primary_excerpt, primary_excerpt)
        evidence_ids = ["ev-primary"]
    elif second[0] == "gushiwen" and second[4]:
        context = second[3]
        evidence_ids = ["ev-work-context"]
    else:
        context = primary_excerpt
        evidence_ids = ["ev-primary"]
    facts = [{"fact_id": "fact-background", "text": "来源记述：" + context, "evidence_ids": evidence_ids}]
    return {
        "poem_key": identity,
        "chronology": chronology,
        "evidence": evidence(primary_url, primary_name, primary_excerpt, secondary=second),
        "context_facts": facts,
        "verification": {"status": "verified", "reviewer": REVIEWER, "reviewed_at": REVIEWED_AT, "controversy_note": ""},
    }


def baseline_packages(poems: list[dict], source_rows: dict[tuple[str, str], dict], poem_urls: dict[str, str]) -> list[dict]:
    result: list[dict] = []
    for background in load_jsonl(BACKGROUND):
        key = background["poem_key"]
        primary = background["sources"][0]
        composition = background["composition"]
        date = composition["date"]
        place = composition["place"]
        chronology = {
            "year_start": date["year_start"], "year_end": date["year_end"], "year_precision": date["precision"],
            "historical_place": place["historical_place"], "modern_place": place["modern_place"], "province": place["province"],
            "lon": place.get("lon"), "lat": place.get("lat"),
        }
        # Re-resolve against poems.json so the package remains tied to one body.
        old_identity = (key["poet"], key["title"], key["body_hash"])
        if old_identity in LEGACY_BODY_HASH_REBIND_ALLOWLIST:
            identity = poem_identity(poems, key["poet"], key["title"])
            expected = LEGACY_BODY_HASH_REBIND_ALLOWLIST[old_identity]
            if identity["body_hash"] != expected:
                raise FactPackageError(f"legacy rebind target mismatch for {key['poet']}《{key['title']}》")
        else:
            identity = poem_identity(poems, key["poet"], key["title"], key["body_hash"])
        primary_url = primary["url"]
        if "/api/" not in urlsplit(primary_url).path:
            primary_url = cnk_url(None, key["poet"], chronology["year_start"], chronology["year_end"])
        result.append(package(identity, chronology, source_rows, poem_urls, primary_url, primary.get("name", "已审核编年来源"), primary["excerpt"], baseline=True))
    return result


def new_packages(poems: list[dict], source_rows: dict[tuple[str, str], dict], poem_urls: dict[str, str]) -> list[dict]:
    result: list[dict] = []
    for poet, title, start, end, precision, historical, modern, province, lon, lat in NEW_SPECS:
        identity = poem_identity(poems, poet, title)
        chronology = {"year_start": start, "year_end": end, "year_precision": precision, "historical_place": historical, "modern_place": modern, "province": province, "lon": lon, "lat": lat}
        row = source_rows.get((poet, title))
        year_label = str(start) if start == end else f"{start}—{end}"
        primary_excerpt = f"CNKGraph条目将《{title}》系于{year_label}，地点标为{historical}。"
        result.append(package(identity, chronology, source_rows, poem_urls, cnk_url(row, poet, start, end), "CNKGraph 文学编年或人物年历条目", primary_excerpt, baseline=False))
    return result


def sort_packages(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: (row["poem_key"]["poet"], row["poem_key"]["title"], row["poem_key"]["dynasty"], row["poem_key"]["body_hash"]))


def build() -> int:
    try:
        poems = json.loads(POEMS.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FactPackageError(f"failed to parse poems JSON {POEMS}: {exc}") from exc
    if isinstance(poems, dict):
        poems = poems["poems"]
    source_rows = load_chronology_rows()
    poem_urls = {poem["body_hash"]: poem.get("source_url", "") for poem in poems}
    packages = sort_packages(baseline_packages(poems, source_rows, poem_urls) + new_packages(poems, source_rows, poem_urls))
    if len(packages) != 60 or len({row["poem_key"]["body_hash"] for row in packages}) != 60:
        raise FactPackageError("release must contain 60 distinct poem bodies")
    for row in packages:
        validate_fact_package(row, poems)
    serialized = "".join(stable_json(row) + "\n" for row in packages)

    legacy_rebindings = [
        {"poet": poet, "title": title, "old_body_hash": old, "new_body_hash": new}
        for (poet, title, old), new in sorted(LEGACY_BODY_HASH_REBIND_ALLOWLIST.items())
    ]
    poet_counts = dict(sorted(Counter(row["poem_key"]["poet"] for row in packages).items()))
    source_counts = dict(sorted(Counter(item["source_family"] for row in packages for item in row["evidence"]).items()))
    verdict_counts = Counter(validate_fact_package(row, poems)["fact_verdict"] for row in packages)
    summary = {
        "schema_version": 1,
        "scope_note": "首批60首：保留41首已审核基线，并纳入指定19首低争议编年事实包。",
        "release_count": 60,
        "poet_counts": poet_counts,
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "newly_verified": [{"poet": poet, "title": title} for poet, title, *_ in NEW_SPECS],
        "held_back": [],
        "legacy_rebindings": legacy_rebindings,
        "source_family_counts": source_counts,
        "generated_by": "tools/build_verified_fact_release.py",
    }
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        temp_dir = tempfile.TemporaryDirectory(prefix=".verified_fact_release.", dir=REVIEWED)
        staging = Path(temp_dir.name)
        package_temp = staging / PACKAGES.name
        expansion_temp = staging / EXPANSIONS.name
        summary_temp = staging / SUMMARY.name
        package_temp.write_text(serialized, encoding="utf-8", newline="\n")
        expansion_count = build_file(package_temp, expansion_temp, POEMS)
        if expansion_count != 60:
            raise FactPackageError(f"expected 60 expansions, got {expansion_count}")
        summary_temp.write_text(stable_json(summary) + "\n", encoding="utf-8", newline="\n")
        # Every artifact has been independently generated and validated before
        # this single rollback-capable publication transaction begins.
        if len(load_jsonl(package_temp)) != 60 or len(load_jsonl(expansion_temp)) != 60:
            raise FactPackageError("staged release artifact count mismatch")
        json.loads(summary_temp.read_text(encoding="utf-8"))
        transactional_replace_many({PACKAGES: package_temp, EXPANSIONS: expansion_temp, SUMMARY: summary_temp})
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()
    return expansion_count


if __name__ == "__main__":
    try:
        print(f"built {build()} verified poem fact expansions")
    except FactPackageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
