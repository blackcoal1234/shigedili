# -*- coding: utf-8 -*-
"""viz_40 山河证道（章节版）· Playwright 验收。

链路：章节中枢 → 启程第一章 → 答完全章（落子×确认×学习卡×下一题循环）→
章末档案卡（诗印/地方诗格/考据馆解锁/错题诗签）→ 返回中枢（诗印点亮、
次章解锁、考据馆开链、玩家行旅地图）→ 暂离续玩。截图输出 output/playwright/viz40/。
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PAGE_URL = (ROOT / "output" / "40_山河证道.html").as_uri()
SHOT_DIR = ROOT / "output" / "playwright" / "viz40"
SHOT_DIR.mkdir(parents=True, exist_ok=True)
CHROMIUM = Path.home() / "AppData" / "Local" / "ms-playwright" / "chromium-1232" / "chrome-win64" / "chrome.exe"

CHECKS: list[str] = []


def ok(msg: str) -> None:
    CHECKS.append(msg)
    print("  [ok]", msg)


def dismiss_intro(page) -> None:
    """每章首次启程都会弹章题开卷卡——有则关掉。"""
    if page.locator("#introOv").evaluate("el => el.classList.contains('on')"):
        page.click("#introGo")
        page.wait_for_timeout(300)


def answer_one(page) -> None:
    """落子 → 确认 → 学习卡 → 下一题。"""
    box = page.locator("#map").bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.55, box["y"] + box["height"] * 0.42)
    page.wait_for_timeout(300)
    page.click("#btnConfirm")
    page.wait_for_timeout(500)
    assert page.locator("#lcMask").evaluate("el => el.classList.contains('on')"), "学习卡未弹出"
    page.click("#lcNext")
    page.wait_for_timeout(400)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    with sync_playwright() as pw:
        launch_kwargs = {"executable_path": str(CHROMIUM)} if CHROMIUM.exists() else {}
        browser = pw.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": 1280, "height": 950})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        page.goto(PAGE_URL, wait_until="load")
        page.wait_for_timeout(1500)

        # 1. 章节中枢
        assert page.locator("#hubArea").is_visible(), "中枢页未显示"
        assert page.locator(".seal").count() == 4, "诗印位不是 4 枚"
        cards = page.locator(".chcard")
        assert cards.count() == 4, f"章节卡 {cards.count()} != 4"
        kao_items = page.locator(".kitem")
        assert kao_items.count() == 9, f"考据馆条目 {kao_items.count()} != 9"
        assert page.locator(".kitem.lock").count() == 9, "初始考据馆应全部上锁"
        ok("中枢页：4 章 / 4 诗印位 / 考据馆 9 链全锁")
        page.screenshot(path=str(SHOT_DIR / "01_章节中枢.png"))

        # 2. 锁与启程
        locked_btns = page.locator("[disabled]")
        assert locked_btns.count() >= 3, "未解锁章节按钮应禁用"
        page.locator("[data-go='0']").click()
        page.wait_for_timeout(600)
        # 2a. 章题开卷卡（Seedance 槽位；无视频时水墨底降级）
        assert page.locator("#introOv").evaluate("el => el.classList.contains('on')"), "开卷卡未弹出"
        intro_txt = page.locator("#introBox").inner_text()
        for needle in ("两京·朔方", "启程"):
            assert needle in intro_txt, f"开卷卡缺少 {needle}"
        assert "Seedance" in intro_txt and "待生成" in intro_txt, "开卷卡场景占位说明缺失"
        page.screenshot(path=str(SHOT_DIR / "02_开卷卡.png"))
        page.click("#introGo")
        page.wait_for_timeout(400)
        assert page.locator("#gameArea").is_visible(), "答题区未出现"
        assert "两京" in page.locator("#chName").inner_text(), "章名未显示"
        assert "教学关" in page.locator("#qDiff").inner_text(), "首章教学关标记缺失"
        ok("第一章启程：开卷卡（Seedance 槽位·降级态）→ 章名/教学关标记正确")

        # 3. 提示免费 + 落子
        page.click("#hProv")
        page.wait_for_timeout(200)
        assert page.locator("#htProv").is_visible() and page.locator("#htProv").inner_text().startswith("【省份圈定】"), "一级提示异常"
        ok("教学关一级提示可用")

        # 4. 答完全章 5 题
        for i in range(10):
            if page.locator("#chEnd").is_visible():
                break
            answer_one(page)
        assert page.locator("#chEnd").is_visible(), "章末档案卡未出现"
        end_text = page.locator("#chEnd").inner_text()
        for needle in ("章末档案", "本章到访", "地方诗格", "解锁考据馆"):
            assert needle in end_text, f"章末卡缺少 {needle}"
        assert page.locator("#chEnd .bigseal").inner_text().strip() == "京", "诗印「京」未盖"
        ok("第一章通关：章末档案卡（诗印京/地方诗格/考据馆解锁/诗签）")
        page.screenshot(path=str(SHOT_DIR / "03_章末档案.png"))

        # 5. 返回中枢：诗印点亮、次章解锁、考据馆开链、行旅地图
        page.click("#btnBackHub2")
        page.wait_for_timeout(600)
        lit = page.locator(".seal.on")
        assert lit.count() == 1 and lit.inner_text().strip().startswith("京"), "诗印未点亮"
        ch2_btn = page.locator("[data-go='1']")
        assert ch2_btn.count() == 1, "第二章未解锁"
        assert page.locator(".kitem.lock").count() == 7, "考据馆解锁数不对"
        assert page.locator(".kitem:not(.lock) a").count() == 2, "第一章考据馆链接未开放"
        assert page.locator("#jmap canvas").count() >= 1, "玩家行旅地图未渲染"
        ok("中枢刷新：诗印点亮 / 第二章解锁 / 考据馆开 2 链 / 行旅地图渲染")
        page.screenshot(path=str(SHOT_DIR / "04_通关后中枢.png"))

        # 6. 暂离与续玩
        ch2_btn.click()
        page.wait_for_timeout(500)
        dismiss_intro(page)
        answer_one(page)
        page.click("#btnBackHub")
        page.wait_for_timeout(500)
        st = page.locator(".chcard").nth(1).inner_text()
        assert "行至第 2" in st, f"中断进度未保存：{st[:60]}"
        page.locator("[data-go='1']").click()
        page.wait_for_timeout(500)
        assert "/2" in page.locator("#chName").inner_text() or "2" in page.locator("#qNo").inner_text(), "续玩未恢复进度"
        ok("暂离→续玩：第二章进度正确恢复（第 2 题）")
        page.screenshot(path=str(SHOT_DIR / "05_续玩.png"))

        # 7. 存档结构 + 控制台
        saved = page.evaluate("() => JSON.parse(localStorage.getItem('shxw40_v2') || 'null')")
        assert saved and saved["ch"]["ch1"]["done"] and saved["ch"]["ch2"]["qi"] == 1, f"存档结构异常：{saved and list(saved['ch'].keys())}"
        assert saved["visited"] and len(saved["visited"]) >= 6, "行旅记录不足"
        assert not errors, f"控制台错误：{errors[:3]}"
        ok("localStorage v2 存档结构正确 · 控制台零错误")

        browser.close()

    print(f"\n[passed] {len(CHECKS)} 项验收全部通过，截图见 {SHOT_DIR}")


if __name__ == "__main__":
    main()
