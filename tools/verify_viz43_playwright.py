# -*- coding: utf-8 -*-
"""viz_43 飞花令加行卷 · Playwright 验收：三题型全流程通关 + 终局 + 诗签复读。"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PAGE_URL = (ROOT / "output" / "43_飞花令加行.html").as_uri()
SHOT_DIR = ROOT / "output" / "playwright" / "viz43"
SHOT_DIR.mkdir(parents=True, exist_ok=True)
CHROMIUM = Path.home() / "AppData" / "Local" / "ms-playwright" / "chromium-1232" / "chrome-win64" / "chrome.exe"

CHECKS: list[str] = []


def ok(msg: str) -> None:
    CHECKS.append(msg)
    print("  [ok]", msg)


def solve_link(page) -> int:
    """暴力求解一轮连线：返回错选次数。"""
    wrong = 0
    for _ in range(4):
        lefts = page.locator('.litem[data-side="L"]:not(.lock)')
        if lefts.count() == 0:
            break
        lefts.first.click()
        page.wait_for_timeout(150)
        rights = page.locator('.litem[data-side="R"]:not(.lock)')
        n = rights.count()
        for i in range(n):
            before = page.locator('.litem.lock').count()
            rights.nth(i).click()
            page.wait_for_timeout(200)
            after = page.locator('.litem.lock').count()
            if after > before:
                break
            wrong += 1
        page.wait_for_timeout(150)
    return wrong


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    with sync_playwright() as pw:
        launch_kwargs = {"executable_path": str(CHROMIUM)} if CHROMIUM.exists() else {}
        browser = pw.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": 1100, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        page.goto(PAGE_URL, wait_until="load")
        page.wait_for_timeout(800)

        # 1. 首题（飞花令）
        t = page.locator("#qType").inner_text()
        assert "飞花令" in t, f"首题类型异常：{t}"
        p = page.locator("#qPrompt").inner_text()
        assert "真的含有" in p, f"飞花令题干异常：{p[:40]}"
        ok(f"首题飞花令渲染：{p[:26]}…")

        # 2. 提示
        page.click("#btnHint")
        page.wait_for_timeout(200)
        assert page.locator("#hintText").is_visible() and "【提示】" in page.locator("#hintText").inner_text(), "提示未显示"
        assert page.locator("#btnHint").is_disabled(), "提示按钮未禁用"
        ok("提示 ×0.5 可用并禁用按钮")
        page.screenshot(path=str(SHOT_DIR / "01_飞花令.png"))

        # 3. 全卷通关（上限 80 步保险）
        links_done = 0
        for _step in range(80):
            if page.locator("#endArea").is_visible():
                break
            qt = page.locator("#qType").inner_text()
            if "连线" in qt:
                solve_link(page)
                links_done += 1
                page.wait_for_timeout(300)
            else:
                page.locator(".opt").first.click()
                page.wait_for_timeout(200)
            nx = page.locator("#btnNext")
            if nx.count():
                nx.click()
                page.wait_for_timeout(250)
        assert page.locator("#endArea").is_visible(), "终局未出现"
        assert links_done >= 1, "未遇到连线题"
        rank = page.locator("#endRank").inner_text()
        assert rank and rank in {"酒中仙", "飞花手", "行令人", "投壶手"}, f"段位异常：{rank}"
        acc = page.locator("#endAcc").inner_text()
        assert "/" in acc, f"答对统计异常：{acc}"
        ok(f"全卷通关：段位「{rank}」，答对 {acc}，连线 {links_done} 轮")
        page.screenshot(path=str(SHOT_DIR / "02_终局.png"))

        # 4. 诗签复读（若有错题）
        qian = page.locator("#qianList span")
        if qian.count():
            qian.first.click()
            page.wait_for_timeout(300)
            assert page.locator("#evCard").is_visible(), "诗签复读未弹证据卡"
            assert "诗签复读" in page.locator("#qNo").inner_text(), "复读标记缺失"
            ok(f"诗签复读（{qian.count()} 枚）证据卡可回看")
            page.screenshot(path=str(SHOT_DIR / "03_诗签复读.png"))
            page.locator("#evCard .act.ghost").click()
            page.wait_for_timeout(300)
            assert page.locator("#endArea").is_visible(), "返回终局失败"
        else:
            ok("全对——无诗签，跳过复读")

        # 5. 存档 + 再来一轮
        saved = page.evaluate("() => JSON.parse(localStorage.getItem('shxw43_v1') || 'null')")
        assert saved and saved.get("done"), f"存档异常：{saved}"
        page.click("#btnAgain")
        page.wait_for_timeout(400)
        assert page.locator("#gameArea").is_visible() and "第 1" in page.locator("#qNo").inner_text(), "再来一轮未重置"
        assert not errors, f"控制台错误：{errors[:3]}"
        ok("localStorage 存档 done=true · 再来一轮重置正常 · 控制台零错误")

        browser.close()

    print(f"\n[passed] {len(CHECKS)} 项验收全部通过，截图见 {SHOT_DIR}")


if __name__ == "__main__":
    main()
