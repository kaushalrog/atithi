"""Visual QA captures for the Atithi site (headless Chrome via Playwright).

    python qa/shots.py http://localhost:4173 qa/raw/<pass-name>

For each viewport: the first screen, a full-page capture, and console errors.
Also: reduced motion, JavaScript disabled, and horizontal-overflow checks.
"""
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE, OUT = sys.argv[1], Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
VIEWPORTS = [("1440", 1440, 900), ("1280", 1280, 800), ("768", 768, 1024), ("390", 390, 844), ("320", 320, 640)]


async def capture(browser, name, w, h, *, js=True, motion="no-preference", full=True):
    ctx = await browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1,
                                    java_script_enabled=js, reduced_motion=motion)
    page = await ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    await page.goto(BASE + "/", wait_until="networkidle")
    await page.wait_for_timeout(2800)                      # let the one-time drawing finish
    await page.screenshot(path=str(OUT / f"{name}-first.png"))
    if full:
        # Scroll through once so lazy images load and scroll-drawn lines run.
        height = await page.evaluate("document.documentElement.scrollHeight")
        for y in range(0, height, h // 2):
            await page.evaluate(f"window.scrollTo(0, {y})")
            await page.wait_for_timeout(120)
        await page.wait_for_timeout(1500)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(300)
        await page.screenshot(path=str(OUT / f"{name}-full.png"), full_page=True)
    overflow = await page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    wide = await page.evaluate("""() => [...document.querySelectorAll('body *')]
        .filter(e => e.getBoundingClientRect().right > document.documentElement.clientWidth + 1)
        .slice(0, 5).map(e => e.tagName + '.' + (e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className))""")
    await ctx.close()
    return {"name": name, "overflow_px": overflow, "too_wide": wide, "errors": errors}


async def main():
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        for name, w, h in VIEWPORTS:
            results.append(await capture(browser, name, w, h))
        results.append(await capture(browser, "390-reduced", 390, 844, motion="reduce", full=False))
        results.append(await capture(browser, "1280-nojs", 1280, 800, js=False))
        await browser.close()
    print(json.dumps(results, indent=1))
    bad = [r["name"] for r in results if r["overflow_px"] > 0 or r["errors"]]
    if bad:
        raise SystemExit(f"FAIL: horizontal overflow or console errors at {bad}")


asyncio.run(main())
