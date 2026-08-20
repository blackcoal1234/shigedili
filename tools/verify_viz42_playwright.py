# -*- coding: utf-8 -*-
"""viz_42 被想象的地方 · Playwright 验收：排名渲染、证据下钻、口径声明。"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PAGE_URL = (ROOT / "output" / "42_被想象的地方.html").as_uri()
SHOT_DIR = ROOT / "output" / "playwright" / "viz42"
SHOT_DIR.mkdir(parents=True, exist_ok=True)
CHROMIUM = Path.home() / "AppData" / "Local" / "ms-playwright" / "chromium-1232" / "chrome-win64" / "chrome.exe"

CHECKS: list[str] = []


def ok(msg: str) -> None:
    CHECKS.append(msg)
    print("  [ok]", msg)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    with sync_playwright() as pw:
        launch_kwargs = {"executable_path": str(CHROMIUM)} if CHROMIUM.exists() else {}
        browser = pw.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        page.goto(PAGE_URL, wait_until="load")
        page.wait_for_timeout(800)

        rows = page.locator(".rrow")
        assert rows.count() >= 15, f"排名行 {rows.count()} < 15"
        first = rows.first.inner_text()
        assert "亲历" in first and "遥想" in first, f"首行内容异常：{first[:60]}"
        ok(f"排名渲染 {rows.count()} 行（首行：{first.split(chr(10))[0][:20]}…）")

        detail = page.locator("#detail").inner_text()
        assert "被想象率" in detail or "样本不足" in detail, "详情缺率值"
        assert "六家行旅对照" in detail, "详情缺上界口径"
        ok("默认详情：率值 + 六家行旅对照（上界口径）在场")

        page.screenshot(path=str(SHOT_DIR / "01_总览.png"))

        # 点击含遥想证据的行：找「遥想 N」中 N>0 的行
        target = None
        for i in range(rows.count()):
            txt = rows.nth(i).inner_text()
            if "遥想 0" not in txt:
                target = i
                break
        if target is not None:
            rows.nth(target).click()
            page.wait_for_timeout(300)
            d = page.locator("#detail").inner_text()
            assert "身在别处" in d and "实作于" in d, "遥想证据未下钻"
            ok(f"证据下钻：第 {target+1} 行展开「实作于」遥想证据")
            page.screenshot(path=str(SHOT_DIR / "02_遥想证据.png"))

        # 口径
        body = page.locator("body").inner_text()
        assert "上界" in body and "A/B" in body, "口径声明缺失"
        overflow = page.evaluate("() => document.body.scrollWidth - document.body.clientWidth")
        assert overflow <= 0, f"横向溢出 {overflow}px"
        assert not errors, f"控制台错误：{errors[:3]}"
        ok("口径声明完备 · 无溢出 · 控制台零错误")

        browser.close()

    print(f"\n[passed] {len(CHECKS)} 项验收全部通过，截图见 {SHOT_DIR}")


if __name__ == "__main__":
    main()
