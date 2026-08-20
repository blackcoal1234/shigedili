# -*- coding: utf-8 -*-
"""viz_41 意象地理 · Playwright 验收：热力图渲染、证据钻取、控制台零错误。"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PAGE_URL = (ROOT / "output" / "41_意象地理.html").as_uri()
SHOT_DIR = ROOT / "output" / "playwright" / "viz41"
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
        page.wait_for_timeout(1500)

        # 1. 分区卡
        cards = page.locator(".rcard")
        assert cards.count() == 9, f"分区卡数量 {cards.count()} != 9"
        first_card = cards.first.inner_text()
        assert "首" in first_card and "位诗人" in first_card, f"分区卡内容异常：{first_card[:60]}"
        ok(f"9 张分区卡渲染（首张：{first_card.splitlines()[0]}）")

        # 2. 热力图 canvas
        assert page.locator("#heat canvas").count() >= 1, "热力图画布未渲染"
        div = page.evaluate(
            "() => document.querySelector('#heat canvas') &&"
            "([document.querySelector('#heat canvas').width, document.querySelector('#heat canvas').height])"
        )
        assert div and div[0] > 300, f"画布尺寸异常：{div}"
        ok(f"热力图渲染（canvas {div[0]}×{div[1]}）")

        page.screenshot(path=str(SHOT_DIR / "01_矩阵总览.png"))

        # 3. 点击第一个分区卡 → 分区档案弹窗
        cards.first.click()
        page.wait_for_timeout(400)
        assert page.locator("#evMask").evaluate("el => el.classList.contains('on')"), "分区档案未弹出"
        arch = page.locator("#evBox").inner_text()
        assert "意象地理档案" in arch and ("×" in arch), f"分区档案内容异常：{arch[:80]}"
        ok("分区档案弹窗（lift 倍率 + 证据）")
        page.screenshot(path=str(SHOT_DIR / "02_分区档案.png"))
        page.evaluate("() => document.getElementById('evMask').classList.remove('on')")
        page.wait_for_timeout(200)

        # 4. 点击热力图中央格点 → 格点证据
        box = page.locator("#heat canvas").first.bounding_box()
        page.mouse.click(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.35)
        page.wait_for_timeout(400)
        if page.locator("#evMask").evaluate("el => el.classList.contains('on')"):
            cell = page.locator("#evBox").inner_text()
            assert "lift" in cell, f"格点弹窗缺 lift：{cell[:80]}"
            ok(f"格点证据钻取：{cell.splitlines()[0][:40]}")
            page.screenshot(path=str(SHOT_DIR / "03_格点证据.png"))
        else:
            # 点击可能落在空格点，重试一次偏左位置
            page.mouse.click(box["x"] + box["width"] * 0.35, box["y"] + box["height"] * 0.5)
            page.wait_for_timeout(400)
            assert page.locator("#evMask").evaluate("el => el.classList.contains('on')"), "格点点击无响应"
            ok("格点证据钻取（二次命中）")

        # 5. 映射表
        tab = page.locator("#regionMapTab").inner_text()
        assert "两京" in tab and "、".__len__() >= 0, "分区映射表缺失"
        ok("分区省级映射表公开可复核")

        # 6. 布局与控制台
        overflow = page.evaluate("() => document.body.scrollWidth - document.body.clientWidth")
        assert overflow <= 0, f"横向溢出 {overflow}px"
        assert not errors, f"控制台错误：{errors[:3]}"
        ok("无横向溢出 · 控制台零错误")

        browser.close()

    print(f"\n[passed] {len(CHECKS)} 项验收全部通过，截图见 {SHOT_DIR}")


if __name__ == "__main__":
    main()
