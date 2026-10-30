import { expect, test, type Page } from "@playwright/test";

// The site's promises, tested in a real browser against the production build.

async function noConsoleErrors(page: Page) {
  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  return errors;
}

test("first screen says what Atithi is and offers a real pilot request", async ({ page }) => {
  const errors = await noConsoleErrors(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("A booking that lands");
  const cta = page.locator(".hero").getByRole("link", { name: "Request an early-access pilot" });
  await expect(cta).toBeVisible();
  const href = await cta.getAttribute("href");
  expect(href).toMatch(/^mailto:atithi\.support@gmail\.com\?subject=/);
  expect(decodeURIComponent(href!)).toContain("A recent time a missed call cost you a booking");
  expect(errors).toEqual([]);
});

test("every in-page link points at a section that exists", async ({ page }) => {
  await page.goto("/");
  const targets = await page.locator('a[href^="#"]').evaluateAll((as) =>
    [...new Set(as.map((a) => a.getAttribute("href")!.slice(1)))]);
  for (const id of targets) expect(await page.locator(`[id="${id}"]`).count(), `#${id}`).toBe(1);
});

test("the pilot section says what happens next and links the privacy notice", async ({ page }) => {
  await page.goto("/#pilot");
  const pilot = page.locator("#pilot");
  for (const step of ["You email us", "We reply by email", "A free two-week pilot, if it fits", "No payment, no contract"])
    await expect(pilot.getByRole("heading", { name: step })).toBeVisible();
  await expect(pilot.getByText("Phone calls aren't part of the pilot")).toBeVisible();
  await pilot.getByRole("link", { name: "privacy notice" }).click();
  await expect(page.getByRole("heading", { name: "What we collect, and for how long" })).toBeInViewport();
  const privacy = page.locator("#privacy");
  for (const t of ["No cookies", "90 days", "180 days", "30 days", "not stored by Atithi", "Gemini", "Twilio", "deletes the rest automatically"])
    await expect(privacy).toContainText(t);
});

test.describe("sample booking", () => {
  test("never says booked unless the record is saved", async ({ page }) => {
    // Stepped by hand, so every state is checked, not just the ones a timer happens to catch.
    await page.goto("/#sample");
    for (const [tab, record, booked] of [
      ["The slot is free", "Confirmed", true],
      ["The slot is taken", "Confirmed", true],
      ["The save fails", "Not saved", false],
    ] as const) {
      await page.getByRole("button", { name: tab }).click();
      await page.getByRole("button", { name: "Pause" }).click();
      await expect(page.getByRole("button", { name: "Play" })).toBeVisible();
      const next = page.getByRole("button", { name: "Next step" });
      while (await next.isEnabled()) {
        await next.click();
        const said = (await page.locator(".say-agent").allTextContents()).join(" ");
        const status = await page.locator(".stage-side .status-pill").allTextContents();
        if (/You're booked/.test(said)) expect(status, `${tab}: booked beside ${status}`).toContain("Confirmed");
      }
      await expect(page.locator(".stage-side .status-pill")).toHaveText(record);
      const said = (await page.locator(".say-agent").allTextContents()).join(" ");
      expect(/You're booked/.test(said)).toBe(booked);
    }
  });

  test("can be paused and stepped by hand", async ({ page }) => {
    await page.goto("/#sample");
    await page.getByRole("button", { name: "The save fails" }).click();
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.getByRole("button", { name: "Play" })).toBeVisible();   // really paused
    const before = await page.locator(".talk > li").count();
    await page.getByRole("button", { name: "Next step" }).click();
    await expect(page.locator(".talk > li")).toHaveCount(before + 1);
  });

  test("is labelled as a scripted sample", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#sample")).toContainText("Scripted in your browser: no AI is running and nothing is saved");
  });
});

test("the walkthrough video downloads only when played, and has a fallback link", async ({ page }) => {
  const mp4: string[] = [];
  page.on("request", (r) => { if (r.url().endsWith(".mp4")) mp4.push(r.url()); });
  await page.goto("/");
  await page.locator("#walkthrough").scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);
  expect(mp4).toEqual([]);
  await expect(page.locator("#walkthrough video")).toHaveAttribute("preload", "none");
  await expect(page.locator("#walkthrough video")).toHaveAttribute("poster", /walkthrough-poster/);
});

test("a video that can't load says so and offers the file", async ({ page }) => {
  await page.route("**/*.mp4", (r) => r.fulfill({ status: 404, body: "" }));
  await page.goto("/");
  const video = page.locator("#walkthrough video");
  await video.scrollIntoViewIfNeeded();
  await video.evaluate((v: HTMLVideoElement) => { v.play().catch(() => {}); });
  await expect(page.getByRole("status")).toContainText("couldn't load");
  await expect(page.getByRole("link", { name: "Open it directly (MP4, 3.8 MB)" })).toHaveAttribute("href", /atithi-walkthrough\.mp4$/);
});

test("the pilot section's own button is the real email link too", async ({ page }) => {
  await page.goto("/#pilot");
  const href = await page.locator("#pilot").getByRole("link", { name: "Request a pilot by email" }).getAttribute("href");
  expect(href).toMatch(/^mailto:atithi\.support@gmail\.com\?subject=Atithi%20early-access%20pilot%20request&body=/);
});

test("no request on the page fails", async ({ page }) => {
  const failed: string[] = [];
  page.on("response", (r) => { if (r.status() >= 400) failed.push(`${r.status()} ${r.url()}`); });
  page.on("requestfailed", (r) => failed.push(`failed ${r.url()}`));
  await page.goto("/", { waitUntil: "networkidle" });
  for (const y of [0.25, 0.5, 0.75, 1]) {
    await page.evaluate((f) => window.scrollTo(0, document.documentElement.scrollHeight * f), y);
    await page.waitForLoadState("networkidle");
  }
  expect(failed).toEqual([]);
  const broken = await page.locator("img").evaluateAll((imgs) =>
    (imgs as HTMLImageElement[]).filter((i) => i.complete && i.naturalWidth === 0).map((i) => i.src));
  expect(broken).toEqual([]);
});

for (const width of [1440, 1280, 768, 390, 320]) {
  test(`no sideways scrolling at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBe(0);
  });
}

test("keyboard: skip link first, visible focus on every control", async ({ page, isMobile }) => {
  test.skip(isMobile, "keyboard flow is a desktop check");
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).toHaveText("Skip to content");
  for (let i = 0; i < 10; i++) {
    await page.keyboard.press("Tab");
    const outline = await page.evaluate(() => getComputedStyle(document.activeElement!).outlineStyle);
    expect(outline).not.toBe("none");
  }
});

test("mobile menu opens, closes with Escape and returns focus", async ({ page, isMobile }) => {
  test.skip(!isMobile, "menu button only exists on small screens");
  await page.goto("/");
  const button = page.getByRole("button", { name: "Open menu" });
  await button.click();
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Request a pilot" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Open menu" })).toBeFocused();
});

test.describe("reduced motion", () => {
  test.use({ reducedMotion: "reduce" });
  test("the signal is drawn and still", async ({ page }) => {
    await page.goto("/");
    const anim = await page.locator(".hero .signal path").first().evaluate((p) => getComputedStyle(p).animationName);
    expect(anim).toBe("none");
  });
});

test.describe("without JavaScript", () => {
  test.use({ javaScriptEnabled: false });
  test("the story, the sample and the pilot request are still there", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator("#sample")).toContainText("Priya Sharma, 98765 43210.");
    await expect(page.locator(".hero").getByRole("link", { name: "Request an early-access pilot" })).toHaveAttribute("href", /^mailto:/);
    await expect(page.locator(".player")).toBeHidden();
  });
});
