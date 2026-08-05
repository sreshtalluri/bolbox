/**
 * Integration against the real Python server and the real kits in `kits/`.
 *
 * Skipped unless RUN_LIVE is set, because it needs a second process:
 *
 *   python -m bolbox.server            # in the repo root
 *   RUN_LIVE=1 npx playwright test live
 *
 * app.spec.ts deliberately stays server-free so the browser half can be tested
 * on its own. This file is where the two contracts actually meet -- the wire
 * shape of `Pattern.to_dict()`, the kit manifest, and the error payload -- and
 * it is the one that catches a schema drift.
 */

import { expect, test } from "@playwright/test";

test.skip(!process.env["RUN_LIVE"], "needs `python -m bolbox.server` on :8000");

test("parses real bol text into a playable pattern", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });

  await page.goto("/");
  await expect(page.locator("body")).toHaveAttribute("data-ready", "true");

  // The kit picker is populated from GET /api/kits.
  await expect(page.locator("#kit option")).toContainText([
    "placeholder-tabla",
    "sparse-demo",
    "synth (built-in placeholder)",
  ]);

  await page.locator("#parse").click();
  await expect(page.getByTestId("errors")).not.toBeVisible();
  await expect(page.locator("#pattern-title")).toHaveText("tintal theka");

  // 16 matras of theka, with `dha`/`dhin` each contributing two strokes.
  const parsed = await page.evaluate(() => window.bolbox.pattern());
  expect(parsed?.tal).toBe("tintal");
  expect(parsed?.cycle_matras).toBe(16);
  expect(parsed?.events.length).toBe(27);
  // Positions must arrive as exact integer pairs, not seconds.
  expect(parsed?.events[0]?.pos).toEqual([0, 1]);

  expect(errors).toEqual([]);
});

test("loads a real kit, aliases and composites included", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("body")).toHaveAttribute("data-ready", "true");

  await page.selectOption("#kit", "placeholder-tabla");
  await page.locator("#play").click();
  await page.waitForTimeout(400);

  const full = await page.evaluate(() => window.bolbox.kit());
  expect(full?.id).toBe("placeholder-tabla");
  // Every stroke in data/strokes.yaml, plus the recorded composites that make
  // `dha` one sample instead of ge+na.
  expect(full?.strokes).toEqual(
    expect.arrayContaining(["ge", "ka", "ki", "na", "tin", "tun", "ta", "te", "ti", "re"]),
  );
  expect(full?.composites).toEqual(expect.arrayContaining(["dha", "dhin", "dhun"]));
  await page.locator("#stop").click();

  // sparse-demo covers the whole vocabulary through `alias_of` chains off a
  // handful of samples. If chain resolution were broken it would load short.
  await page.selectOption("#kit", "sparse-demo");
  await page.locator("#play").click();
  await page.waitForTimeout(400);

  const sparse = await page.evaluate(() => window.bolbox.kit());
  expect(sparse?.id).toBe("sparse-demo");
  expect(sparse?.strokes.length).toBe(full?.strokes.length);
  await expect(page.getByTestId("errors")).not.toBeVisible();
  await page.locator("#stop").click();
});

test("renders .wav here and fetches .mid from the server", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("body")).toHaveAttribute("data-ready", "true");
  await page.selectOption("#kit", "placeholder-tabla");
  await page.locator("#parse").click();
  await expect(page.locator("#pattern-title")).toHaveText("tintal theka");

  const [wav] = await Promise.all([
    page.waitForEvent("download"),
    page.locator("#download-wav").click(),
  ]);
  expect(wav.suggestedFilename()).toBe("tintal-theka.wav");

  // MIDI is rendered by bolbox/midi.py, not here: it rounds to ticks at a PPQ
  // and emits two note-ons for a composite. Two implementations of that
  // rounding is one too many.
  const [mid] = await Promise.all([
    page.waitForEvent("download"),
    page.locator("#download-mid").click(),
  ]);
  expect(mid.suggestedFilename()).toBe("tintal-theka.mid");

  const stream = await mid.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(chunk as Buffer);
  expect(Buffer.concat(chunks).subarray(0, 4).toString("ascii")).toBe("MThd");
});

test("a real parse error arrives with its line and column", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("body")).toHaveAttribute("data-ready", "true");

  await page.locator("#bol-text").fill("tal: tintal\nlay: 120\n\ndha dhaka dhin dha");
  await page.locator("#parse").click();

  const errors = page.getByTestId("errors");
  await expect(errors).toBeVisible();
  // Whatever the message turns out to be, the POSITION is the part that has to
  // survive the trip -- that is the coupling worth asserting.
  await expect(errors).toContainText(/line \d+, column \d+/);
  await expect(errors).toContainText("dha dhaka dhin dha");
});
