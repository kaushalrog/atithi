"""Interaction QA for the Atithi site (headless Chrome via Playwright).

    python qa/interact.py http://localhost:4173 qa/raw/<pass-name>

Checks keyboard order and focus visibility, the mobile menu, the sample
booking's failure path, reduced motion, that the video is not fetched on
load, and what a visitor without JavaScript gets. Prints PASS/FAIL lines.
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE, OUT = sys.argv[1], Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", headless=True)

        # --- keyboard order + visible focus (desktop) ---
        ctx = await b.new_context(viewport={"width": 1280, "height": 800})
        page = await ctx.new_page()
        media = []
        page.on("request", lambda r: media.append(r.url) if r.url.endswith(".mp4") else None)
        await page.goto(BASE + "/", wait_until="networkidle")
        order = []
        for _ in range(9):
            await page.keyboard.press("Tab")
            order.append(await page.evaluate("""() => { const e = document.activeElement;
                const s = getComputedStyle(e); return [e.textContent.trim().slice(0, 28) || e.getAttribute('aria-label'),
                s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0] }"""))
        print("   tab order:", [o[0] for o in order])
        check("first Tab reaches the skip link", order[0][0] == "Skip to content")
        check("every focused control shows an outline", all(o[1] for o in order[1:]), str([o[0] for o in order if not o[1]]))
        check("video not downloaded on page load", not media, str(media))

        # Enter on the hero CTA plays the sample
        await page.goto(BASE + "/", wait_until="networkidle")
        await page.focus("a.btn-ink[href='#sample']")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2500)
        step = await page.text_content(".stage-step")
        check("hero CTA (keyboard) starts the sample", step and not step.startswith("8"), step)

        # failure scenario screenshot, end state
        await page.click("button.chip:has-text('The save fails')")
        await page.wait_for_function("document.querySelector('.player .btn-ink')?.textContent === 'Replay'", timeout=20000)
        await page.locator(".stage").screenshot(path=str(OUT / "sample-failure-end.png"))
        said = " ".join(await page.locator(".say-agent").all_text_contents())
        check("failure path never says 'booked' as done", "You're booked" not in said and "haven't booked" in said)
        await page.click("button.chip:has-text('The slot is taken')")
        await page.wait_for_timeout(5000)
        await page.locator(".stage").screenshot(path=str(OUT / "sample-taken-mid.png"))
        await ctx.close()

        # --- mobile menu ---
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page = await ctx.new_page()
        await page.goto(BASE + "/", wait_until="networkidle")
        btn = page.locator(".menu-btn")
        check("menu button visible on mobile", await btn.is_visible())
        await btn.click()
        check("menu opens (aria-expanded)", await btn.get_attribute("aria-expanded") == "true"
              and await page.locator("#nav-links a:has-text('How it works')").is_visible())
        await page.screenshot(path=str(OUT / "390-menu-open.png"))
        await page.keyboard.press("Escape")
        focused = await page.evaluate("document.activeElement.classList.contains('menu-btn')")
        check("Escape closes the menu and returns focus", await btn.get_attribute("aria-expanded") == "false" and focused)
        await btn.click()
        await page.click("#nav-links a:has-text('Businesses')")
        await page.wait_for_timeout(900)
        check("a menu link navigates and closes the menu", await btn.get_attribute("aria-expanded") == "false"
              and page.url.endswith("#businesses"))
        await ctx.close()

        # --- reduced motion ---
        ctx = await b.new_context(viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
        page = await ctx.new_page()
        await page.goto(BASE + "/", wait_until="networkidle")
        anim = await page.evaluate("getComputedStyle(document.querySelector('.hero .signal path')).animationName")
        dash = await page.evaluate("getComputedStyle(document.querySelector('.hero .signal path')).strokeDashoffset")
        check("reduced motion: signal is static and fully drawn", anim == "none" and dash in ("0", "0px"), f"{anim} {dash}")
        await ctx.close()

        # --- no JavaScript ---
        ctx = await b.new_context(viewport={"width": 1280, "height": 800}, java_script_enabled=False)
        page = await ctx.new_page()
        await page.goto(BASE + "/")
        text = await page.inner_text("body")
        check("no JS: hero, sample transcript and trust table are in the HTML",
              all(t in text for t in ("A booking that lands", "Priya Sharma, 98765 43210", "Where Atithi is today")))
        check("no JS: playback controls hidden", not await page.locator(".player").is_visible())
        await page.locator("#sample").screenshot(path=str(OUT / "1280-nojs-sample.png"))
        await ctx.close()
        await b.close()
    print(f"\n{sum(results)}/{len(results)} checks passed")


asyncio.run(main())
