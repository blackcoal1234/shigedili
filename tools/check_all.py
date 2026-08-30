"""一键运行主题版 Python、数据与输出质量检查。"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Check:
    name: str
    command: tuple[str, ...]


def py(*args: str) -> tuple[str, ...]:
    return (sys.executable, *args)


CHECKS = (
    Check(
        "Python语法",
        py(
            "-m",
            "compileall",
            "-q",
            "run_all.py",
            "config.py",
            "data",
            "tools",
            "爬虫脚本",
            "数据可视化脚本",
            "数据库操作脚本及数据库SQL",
        ),
    ),
    Check("背景采集审核", py("tools/check_background_pipeline.py")),
    Check("CBDB identity audit", py("tools/check_cbdb_identity_audit.py")),
    Check("88人行旅史料采集", py("tools/check_journey_source_pipeline.py")),
    Check("诗人参考语料", py("tools/check_poet_reference_corpus.py")),
    Check("来源注册表元数据", py("tools/check_poet_source_registry_metadata.py")),
    Check("DILA人名规范资料", py("tools/check_dila_person_reference_pipeline.py")),
    Check("CBDB事件坐标回填", py("tools/check_cbdb_coordinate_backfill.py")),
    Check("史料缺口与人工补证", py("tools/check_manual_source_evidence.py")),
    Check("88人史料候选汇总", py("tools/check_poet_history_collection_summary.py")),
    Check("赏析诗页", py("tools/check_poem_page_data.py")),
    Check("主题数据", py("tools/check_theme_data.py")),
    Check("诗人行旅", py("tools/check_journey_emotion.py")),
    Check("创作活动中心", py("tools/check_literary_centers.py")),
    Check("同意象异情", py("tools/check_imagery_emotion_compare.py")),
    Check("88位诗人第一人称生命卷", py("tools/check_first_person_lives.py")),
    Check("主题输出", py("tools/check_theme_outputs.py")),
    Check("诗篇事实扩展发布集", py("tools/check_verified_fact_release.py")),
    Check("88人诗篇事实扩展发布集", py("tools/check_all_poet_fact_release.py")),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--keep-going", action="store_true")
    parser.add_argument("--offline", action="store_true", help="全部检查默认离线；保留课程命令兼容")
    parser.add_argument("--match", help="按检查名称筛选")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    checks = tuple(
        check
        for check in CHECKS
        if not args.match or args.match.casefold() in check.name.casefold()
    )
    if not checks:
        raise SystemExit(f"没有匹配的检查：{args.match}")
    if args.list:
        for index, check in enumerate(checks, start=1):
            print(f"{index}. {check.name}: {' '.join(check.command)}")
        return

    failures: list[tuple[str, int]] = []
    for index, check in enumerate(checks, start=1):
        print(f"\n[{index}/{len(checks)}] {check.name}")
        result = subprocess.run(check.command, cwd=ROOT, check=False)
        if result.returncode:
            failures.append((check.name, result.returncode))
            if not args.keep_going:
                break
    if failures:
        for name, code in failures:
            print(f"[failed] {name}: exit {code}")
        raise SystemExit(failures[0][1] or 1)
    print(f"\n[ok] {len(checks)} 项主题检查全部通过")


if __name__ == "__main__":
    main()
