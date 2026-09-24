// Tower Merge Rush, played in a browser against the built bundle.
//
// GOLDEN-RUN REPLAY. Ported from examples/tower-merge-rush/tests/e2e/smoke.spec.ts by the
// Factory's golden-run replay developer; not agent-written. Each test carries @aspect tags
// the verify step maps to gameplay aspects. Requests to anything but the preview server are
// aborted, so a portal SDK script is never fetched: the game must cope without it, and the
// suite never touches the network.
//
// Math.random is pinned to 0 before load so the first drop is deterministically level 1,
// which makes the scripted merge below reproducible.

import { expect, test, type Page } from "@playwright/test";

interface GameHooks {
  state: "start" | "playing" | "over";
  score: number;
  best: number;
  merges: number;
  steps: number;
  levelAt(col: number): number | null;
  dropAt(col: number): void;
  dropAnywhere(): void;
  continue(): Promise<boolean>;
  restart(): Promise<unknown>;
  pause(): void;
  resume(): void;
  paused(): boolean;
  gameplayActive(): boolean;
}

/** window, as the game's main.ts extends it. Local, so no global declaration
 * collides with the template examples' own suites in one typecheck. */
type W = { __game: GameHooks };

async function open(page: Page): Promise<{ errors: string[] }> {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  await page.route(/^https?:\/\/(?!localhost[:/]|127\.0\.0\.1[:/])/, (route) => route.abort());
  await page.addInitScript(() => {
    Math.random = () => 0;
  });
  await page.goto("/");
  await expect(page.locator("#hud")).toHaveAttribute("data-ready", "true", { timeout: 60_000 });
  return { errors };
}

async function state(page: Page): Promise<string> {
  return page.evaluate(() => (window as unknown as W).__game.state);
}

async function fillUntilOver(page: Page): Promise<void> {
  await page.evaluate(() => {
    for (let i = 0; i < 500 && (window as unknown as W).__game.state !== "over"; i++) (window as unknown as W).__game.dropAnywhere();
  });
}

test("boots with a canvas, loads, and shows the title @boot @loading", async ({ page }) => {
  const { errors } = await open(page);
  await expect(page.locator("#game canvas")).toBeVisible();
  await expect(page.locator("#hud")).toHaveAttribute("data-scene", "tower-merge-rush");
  await expect(page.locator('section[data-screen="start"]')).toBeVisible();
  expect(await state(page)).toBe("start");
  expect(errors).toEqual([]);
});

test("the play button starts a run and gameplay on first input @start @input", async ({
  page,
}) => {
  await open(page);
  expect(await page.evaluate(() => (window as unknown as W).__game.gameplayActive())).toBe(false);
  await page.locator('[data-action="play"]').click();
  expect(await state(page)).toBe("playing");
  await expect.poll(() => page.evaluate(() => (window as unknown as W).__game.gameplayActive())).toBe(true);
});

test("a tap on the board drops a piece @input @core-loop", async ({ page }) => {
  await open(page);
  await page.locator('[data-action="play"]').click();
  const box = await page.locator("#game").boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.click(box!.x + box!.width * 0.5, box!.y + box!.height * 0.5);
  const filled = await page.evaluate(
    () => [0, 1, 2, 3, 4, 5, 6].filter((c) => (window as unknown as W).__game.levelAt(c) !== null).length,
  );
  expect(filled).toBeGreaterThanOrEqual(2);
});

test("a scripted merge increases the score @core-loop @progression", async ({ page }) => {
  await open(page);
  await page.evaluate(() => (window as unknown as W).__game.dropAt(0));
  const before = await page.evaluate(() => (window as unknown as W).__game.score);
  await page.evaluate(() => (window as unknown as W).__game.dropAt(1));
  expect(await page.evaluate(() => (window as unknown as W).__game.score)).toBeGreaterThan(before);
  expect(await page.evaluate(() => (window as unknown as W).__game.levelAt(0))).toBe(2);
  expect(await page.evaluate(() => (window as unknown as W).__game.merges)).toBe(1);
});

test("game over is reachable and records the personal best @game-over @progression", async ({
  page,
}) => {
  await open(page);
  await fillUntilOver(page);
  expect(await state(page)).toBe("over");
  await expect(page.locator('section[data-screen="over"]')).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => (window as unknown as W).__game.best))
    .toBe(await page.evaluate(() => (window as unknown as W).__game.score));
});

test("restart after game over resets the score @restart", async ({ page }) => {
  await open(page);
  await fillUntilOver(page);
  expect(await page.evaluate(() => (window as unknown as W).__game.score)).toBeGreaterThan(0);
  await page.evaluate(() => (window as unknown as W).__game.restart());
  await expect.poll(() => state(page)).toBe("start");
  expect(await page.evaluate(() => (window as unknown as W).__game.score)).toBe(0);
});

test("pausing stops the loop and resuming restarts it @pause-resume", async ({ page }) => {
  await open(page);
  await page.evaluate(() => (window as unknown as W).__game.dropAt(0));
  await page.evaluate(() => (window as unknown as W).__game.pause());
  expect(await page.evaluate(() => (window as unknown as W).__game.paused())).toBe(true);
  await expect(page.locator('section[data-screen="pause"]')).toBeVisible();
  const frozen = await page.evaluate(() => (window as unknown as W).__game.steps);
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => (window as unknown as W).__game.steps)).toBe(frozen);
  await page.evaluate(() => (window as unknown as W).__game.resume());
  expect(await page.evaluate(() => (window as unknown as W).__game.paused())).toBe(false);
  await expect.poll(() => page.evaluate(() => (window as unknown as W).__game.steps)).toBeGreaterThan(frozen);
});

test("a rewarded continue without an ad is refused gracefully @game-over", async ({ page }) => {
  await open(page);
  await fillUntilOver(page);
  const granted = await page.evaluate(() => (window as unknown as W).__game.continue());
  expect(granted).toBe(false);
  expect(await state(page)).toBe("over");
  await expect(page.locator('[data-role="note"]')).not.toBeEmpty();
});

// The hooks drive the game identically on both projects; the mobile project is the phone.
test("drives through the hooks on every viewport @responsive", async ({ page }, info) => {
  await open(page);
  await page.evaluate(() => (window as unknown as W).__game.dropAt(2));
  expect(await state(page)).toBe("playing");
  expect(await page.evaluate(() => (window as unknown as W).__game.levelAt(2))).toBe(1);
  expect(info.project.name).toBeTruthy();
});
