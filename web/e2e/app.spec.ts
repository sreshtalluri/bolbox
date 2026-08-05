/**
 * Three flows, in a real browser with a real AudioContext.
 *
 * The Python server is not running in this suite, so the page boots off the
 * bundled `sample-pattern.json`. That is deliberate: it keeps the browser half
 * testable on its own, and the parse path against a live server belongs in an
 * integration suite that owns both processes.
 *
 * HONESTY NOTE. Some of what a sequencer does is not observable from the
 * outside: nothing here can prove a stroke was audible, or that a sample was
 * the right one. Where an assertion is really "this did not throw", it says so
 * in a comment instead of being dressed up as a stronger claim. The properties
 * that matter -- exactly-once, no drift, correct re-anchoring -- are asserted
 * directly in src/scheduler.test.ts, where the clock can be driven by hand.
 */

import { expect, test, type Page } from "@playwright/test";

// The page exposes `window.bolbox` (see the bottom of src/main.ts) because the
// audio clock and the scheduler's position have no DOM representation, and they
// are the only honest evidence that playback is actually running.

test.beforeEach(({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.message));
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    // Chromium logs a console error for any non-2xx response, including the
    // /api/kits probe that is EXPECTED to fail in this suite -- the Python
    // server is not running, and the app is supposed to fall back quietly. That
    // is the browser narrating a network status, not the app misbehaving, so it
    // is filtered out; a thrown exception still arrives via `pageerror`.
    if (msg.text().startsWith("Failed to load resource")) return;
    errors.push(msg.text());
  });
  (page as Page & { __errors?: string[] }).__errors = errors;
});

/** Uncaught exceptions and app-logged errors. Not network status noise. */
function pageErrors(page: Page): string[] {
  return (page as Page & { __errors?: string[] }).__errors ?? [];
}

/**
 * Navigate and wait for the app to finish booting.
 *
 * `goto` resolves on the load event, but the pattern arrives from an async
 * fetch after that. Clicking Play in the gap is a race, and it is a race that
 * fails intermittently rather than every time -- so every test goes through
 * here rather than calling goto directly.
 */
async function gotoApp(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.locator("body")).toHaveAttribute("data-ready", "true");
}

// -- 1. loads and renders ---------------------------------------------------

test("page loads and renders the bundled pattern", async ({ page }) => {
  await gotoApp(page);

  await expect(page.getByTestId("tal-display")).toContainText("tintal");
  await expect(page.getByTestId("tal-display")).toContainText("16 matras");

  // Sixteen matras of tintal, grouped 4+4+4+4.
  const cells = page.locator("#grid .matra");
  await expect(cells).toHaveCount(16);
  await expect(page.locator("#grid .vibhag")).toHaveCount(4);

  // Sam is marked, and the composite `dha` shows as one syllable rather than
  // as the two strokes it decomposes to.
  await expect(cells.nth(0)).toHaveClass(/sam/);
  await expect(cells.nth(0)).toContainText("dha");
  await expect(cells.nth(8)).toHaveClass(/khali/);

  // The khali vibhag has no bayan, which is the point of it.
  await expect(cells.nth(9)).toContainText("tin");

  await expect(page.getByTestId("errors")).not.toBeVisible();
  expect(pageErrors(page)).toEqual([]);
});

test("the pattern the page holds matches the fixture", async ({ page }) => {
  await gotoApp(page);
  const summary = await page.evaluate(() => {
    const p = window.bolbox.pattern();
    return p ? { tal: p.tal, matras: p.cycle_matras, events: p.events.length } : null;
  });
  expect(summary).toEqual({ tal: "tintal", matras: 16, events: 27 });
});

// -- 2. play ----------------------------------------------------------------

test("play starts the audio clock and the scheduler advances", async ({ page }) => {
  await gotoApp(page);
  await page.locator("#play").click();

  await expect(page.locator("#stop")).toBeEnabled();
  await expect(page.locator("body")).toHaveAttribute("data-playing", "true");

  const t0 = await page.evaluate(() => window.bolbox.ctxTime());
  await page.waitForTimeout(600);
  const t1 = await page.evaluate(() => window.bolbox.ctxTime());

  // The observable claim: AudioContext.currentTime moved. A suspended context
  // -- the usual failure when autoplay policy blocks playback -- would leave
  // this flat, and the scheduler would anchor to a clock that never ticks.
  expect(t1).toBeGreaterThan(t0);
  expect(t1 - t0).toBeGreaterThan(0.3);

  // And the scheduler's position moved with it, i.e. the loop is running and
  // not just the clock. At lay 120 that is 2 matras per second.
  const pos = await page.evaluate(() => window.bolbox.positionMatras());
  expect(pos).toBeGreaterThan(0);
  expect(pos).toBeLessThan(16);

  // A cell is lit. This is the closest the DOM gets to "something is playing".
  await expect(page.locator("#grid .matra.on")).toHaveCount(1);

  // NOT ASSERTED: that anything was audible. Headless Chromium renders to a
  // null device, so "a sample played" is not observable here. The graph is
  // covered by src/graph.test.ts instead.
  expect(pageErrors(page)).toEqual([]);

  await page.locator("#stop").click();
  await expect(page.locator("#play")).toBeEnabled();
  expect(await page.evaluate(() => window.bolbox.playing())).toBe(false);
});

test("stop and replay does not throw", async ({ page }) => {
  await gotoApp(page);
  for (let i = 0; i < 3; i++) {
    await page.locator("#play").click();
    await page.waitForTimeout(120);
    await page.locator("#stop").click();
  }
  // "Did not throw" is the whole assertion here -- restarting a Player rebuilds
  // scheduler state and the voice pool, and a leak in either shows up as an
  // exception rather than as anything visible.
  expect(pageErrors(page)).toEqual([]);
  await expect(page.getByTestId("errors")).not.toBeVisible();
});

// -- 3. lay change mid-playback ---------------------------------------------

test("changing the lay mid-playback keeps the scheduler consistent", async ({ page }) => {
  await gotoApp(page);
  await page.locator("#play").click();
  await page.waitForTimeout(300);

  const before = await page.evaluate(() => ({
    pos: window.bolbox.positionMatras(),
    time: window.bolbox.ctxTime(),
  }));

  await page.locator("#lay").fill("300");
  await page.locator("#lay").dispatchEvent("input");

  await expect(page.getByTestId("lay-value")).toHaveText("300 matras/min");
  expect(await page.evaluate(() => window.bolbox.lay())).toBe(300);

  // Sample the position repeatedly across the change. It must stay inside the
  // cycle and keep moving -- a botched re-anchor shows up as a position that
  // freezes, runs backwards past sam, or leaves the cycle entirely.
  const samples: number[] = [];
  for (let i = 0; i < 12; i++) {
    samples.push(await page.evaluate(() => window.bolbox.positionMatras()));
    await page.waitForTimeout(80);
  }
  for (const s of samples) {
    expect(s).toBeGreaterThanOrEqual(0);
    expect(s).toBeLessThan(16);
  }
  expect(new Set(samples.map((s) => Math.floor(s))).size).toBeGreaterThan(1);

  const after = await page.evaluate(() => ({
    time: window.bolbox.ctxTime(),
    playing: window.bolbox.playing(),
  }));
  expect(after.playing).toBe(true);
  expect(after.time).toBeGreaterThan(before.time);
  expect(before.pos).toBeGreaterThanOrEqual(0);

  // No exception from the scheduler or the graph while the tempo moved.
  expect(pageErrors(page)).toEqual([]);
  await expect(page.getByTestId("errors")).not.toBeVisible();

  await page.locator("#stop").click();
});

test("dragging the lay across its whole range mid-playback does not throw", async ({
  page,
}) => {
  await gotoApp(page);
  await page.locator("#play").click();
  for (const lay of ["20", "600", "45", "240", "120"]) {
    await page.locator("#lay").fill(lay);
    await page.locator("#lay").dispatchEvent("input");
    await page.waitForTimeout(90);
    expect(await page.evaluate(() => window.bolbox.playing())).toBe(true);
  }
  // "Did not throw", stated plainly. What a lay sweep can actually break --
  // repeated or dropped events at the seam -- is asserted in scheduler.test.ts,
  // where the clock is under test control.
  expect(pageErrors(page)).toEqual([]);
  await page.locator("#stop").click();
});

// -- export -----------------------------------------------------------------

test("download .wav renders a real file through OfflineAudioContext", async ({ page }) => {
  await gotoApp(page);
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator("#download-wav").click(),
  ]);

  expect(download.suggestedFilename()).toMatch(/\.wav$/);
  const path = await download.path();
  expect(path).toBeTruthy();

  // Two cycles of tintal at lay 120 is 16s, plus a tail. Checking the byte
  // count against the sample rate proves the offline render actually ran and
  // produced audio of the right LENGTH -- not that it is the right audio. That
  // it is the same audio as playback is a property of sharing the graph code,
  // and is asserted structurally in src/graph.test.ts.
  const bytes = await download.createReadStream();
  let total = 0;
  for await (const chunk of bytes) total += (chunk as Buffer).length;
  // 16s stereo 16-bit at >= 44.1k is a couple of megabytes; anything tiny means
  // the render produced silence-length output or an empty buffer.
  expect(total).toBeGreaterThan(2_000_000);
  expect(pageErrors(page)).toEqual([]);
});

// -- parse errors -----------------------------------------------------------

test("a parse error renders with its line and column", async ({ page }) => {
  // The Python server is not running in this suite, so the response is faked at
  // the network layer. This tests THIS side of the contract: that a positioned
  // error reaches the error area intact.
  // This is the literal shape of `_parse_error_payload` in bolbox/server.py:
  // `error` is a string sitting NEXT TO the position fields, not wrapping them.
  await page.route("**/api/pattern", async (route) => {
    await route.fulfill({
      status: 422,
      contentType: "application/json",
      body: JSON.stringify({
        error: "unknown bol 'dhaka'",
        line: 2,
        column: 7,
        text: "dha dhaka dhin",
      }),
    });
  });

  await gotoApp(page);
  await page.locator("#parse").click();

  const errors = page.getByTestId("errors");
  await expect(errors).toBeVisible();
  await expect(errors).toContainText("line 2, column 7");
  await expect(errors).toContainText("unknown bol 'dhaka'");
  await expect(errors).toContainText("dha dhaka dhin");
  await expect(page.getByTestId("status")).toHaveText("parse failed");
});

test("an unreachable server says so instead of failing silently", async ({ page }) => {
  await page.route("**/api/pattern", (route) => route.abort("connectionrefused"));
  await gotoApp(page);
  await page.locator("#parse").click();
  await expect(page.getByTestId("errors")).toBeVisible();
  await expect(page.getByTestId("status")).toHaveText("server unreachable");
});
