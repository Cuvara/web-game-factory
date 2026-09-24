// Neon Drift Arena, played in a browser against the built bundle.
//
// GOLDEN-RUN REPLAY. Ported from examples/neon-drift-arena/tests/e2e/smoke.spec.ts by the
// Factory's golden-run replay developer; not agent-written. Each test carries @aspect tags
// the verify step maps to gameplay aspects. Requests to anything but the preview server are
// aborted, so a portal SDK script is never fetched: the game must cope without it, and the
// suite never touches the network. It never reads pixels: the deterministic probe exposes
// score, state and the pure-sim hooks, so play is scripted and asserted exactly.

import { expect, test, type Page } from "@playwright/test";

interface GameProbe {
  score: number;
  best: number;
  state: string;
  phase: string;
  playerX: number;
  runId: number;
  steps: number;
  gameplayActive(): boolean;
  play(): void;
  tick(dt: number): void;
  steer(dir: number): void;
  spawnObstacleAt(x: number, z: number, halfWidth?: number): unknown;
  restart(): Promise<void>;
  revive(): Promise<boolean>;
  pause(): void;
  resume(): void;
  paused(): boolean;
}

/** window, as the game's main.ts extends it. Local, so no global declaration
 * collides with the template examples' own suites in one typecheck. */
type W = { __game: GameProbe };

const STEP = 1000 / 60;

async function boot(page: Page): Promise<{ errors: string[] }> {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  await page.route(/^https?:\/\/(?!localhost[:/]|127\.0\.0\.1[:/])/, (route) => route.abort());
  await page.goto("/");
  await expect(page.locator("#hud")).toHaveAttribute("data-ready", "true", { timeout: 60_000 });
  await page.waitForFunction(() => typeof (window as unknown as W).__game !== "undefined");
  return { errors };
}

async function crash(page: Page): Promise<void> {
  await page.evaluate((step) => {
    (window as unknown as W).__game.steer(0);
    (window as unknown as W).__game.spawnObstacleAt(0, 1, 0.8);
    for (let i = 0; i < 60 && (window as unknown as W).__game.phase === "playing"; i++) (window as unknown as W).__game.tick(step);
  }, STEP);
}

test("boots with a WebGL canvas and loads the menu @boot @loading", async ({ page }) => {
  const { errors } = await boot(page);
  const canvas = page.locator("#game canvas");
  await expect(canvas).toHaveCount(1);
  const hasWebGl = await page.evaluate(() => {
    const c = document.querySelector("#game canvas") as HTMLCanvasElement | null;
    if (!c) return false;
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  });
  expect(hasWebGl).toBe(true);
  await expect(page.locator("#hud")).toHaveAttribute("data-scene", "neon-drift-arena");
  expect(await page.evaluate(() => (window as unknown as W).__game.phase)).toBe("menu");
  expect(errors).toEqual([]);
});

test("the drive button starts a run and gameplay on first input @start @input", async ({
  page,
}) => {
  await boot(page);
  expect(await page.evaluate(() => (window as unknown as W).__game.gameplayActive())).toBe(false);
  await page.locator("#play").click();
  expect(await page.evaluate(() => (window as unknown as W).__game.phase)).toBe("playing");
  expect(await page.evaluate(() => (window as unknown as W).__game.gameplayActive())).toBe(true);
});

test("keyboard input starts a run and steers @input", async ({ page }) => {
  await boot(page);
  await page.locator("body").press("Space");
  expect(await page.evaluate(() => (window as unknown as W).__game.phase)).toBe("playing");
  await page.keyboard.down("ArrowRight");
  await page.evaluate((step) => {
    for (let i = 0; i < 30; i++) (window as unknown as W).__game.tick(step);
  }, STEP);
  await page.keyboard.up("ArrowRight");
  expect(await page.evaluate(() => (window as unknown as W).__game.playerX)).toBeGreaterThan(0);
});

test("scripted play increases the score @core-loop @progression", async ({ page }) => {
  await boot(page);
  await page.evaluate(() => (window as unknown as W).__game.play());
  const start = await page.evaluate(() => (window as unknown as W).__game.score);
  await page.evaluate((step) => {
    (window as unknown as W).__game.steer(0);
    for (let i = 0; i < 240; i++) (window as unknown as W).__game.tick(step);
  }, STEP);
  expect(await page.evaluate(() => (window as unknown as W).__game.score)).toBeGreaterThan(start);
});

test("a collision reaches game over and records the best @game-over @progression", async ({
  page,
}) => {
  await boot(page);
  await page.evaluate(() => (window as unknown as W).__game.play());
  await page.evaluate((step) => {
    for (let i = 0; i < 120; i++) (window as unknown as W).__game.tick(step);
  }, STEP);
  await crash(page);
  expect(await page.evaluate(() => (window as unknown as W).__game.phase)).toBe("over");
  await expect(page.locator("#over")).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => (window as unknown as W).__game.best))
    .toBeGreaterThanOrEqual(await page.evaluate(() => (window as unknown as W).__game.score));
});

test("restart after game over begins a new run @restart", async ({ page }) => {
  await boot(page);
  await page.evaluate(() => (window as unknown as W).__game.play());
  const firstRunId = await page.evaluate(() => (window as unknown as W).__game.runId);
  await page.evaluate((step) => {
    (window as unknown as W).__game.steer(0);
    for (let i = 0; i < 600; i++) (window as unknown as W).__game.tick(step);
  }, STEP);
  await crash(page);
  const crashScore = await page.evaluate(() => (window as unknown as W).__game.score);
  expect(await page.evaluate(() => (window as unknown as W).__game.phase)).toBe("over");
  expect(crashScore).toBeGreaterThan(50);

  await page.evaluate(() => (window as unknown as W).__game.restart());
  await page.waitForFunction(() => (window as unknown as W).__game.phase === "playing");
  expect(await page.evaluate(() => (window as unknown as W).__game.runId)).toBe(firstRunId + 1);
  expect(await page.evaluate(() => (window as unknown as W).__game.score)).toBeLessThan(crashScore);
});

test("pausing stops the loop and resuming restarts it @pause-resume", async ({ page }) => {
  await boot(page);
  await page.evaluate(() => (window as unknown as W).__game.play());
  await page.evaluate(() => (window as unknown as W).__game.pause());
  expect(await page.evaluate(() => (window as unknown as W).__game.paused())).toBe(true);
  expect(await page.evaluate(() => (window as unknown as W).__game.gameplayActive())).toBe(false);
  await expect(page.locator("#paused")).toBeVisible();
  const frozen = await page.evaluate(() => (window as unknown as W).__game.steps);
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => (window as unknown as W).__game.steps)).toBe(frozen);
  await page.evaluate(() => (window as unknown as W).__game.resume());
  expect(await page.evaluate(() => (window as unknown as W).__game.paused())).toBe(false);
  await expect.poll(() => page.evaluate(() => (window as unknown as W).__game.steps)).toBeGreaterThan(frozen);
});

test("a rewarded revive without an ad is declined gracefully @game-over", async ({ page }) => {
  await boot(page);
  await page.evaluate(() => (window as unknown as W).__game.play());
  await crash(page);
  expect(await page.evaluate(() => (window as unknown as W).__game.phase)).toBe("over");
  expect(await page.evaluate(() => (window as unknown as W).__game.revive())).toBe(false);
  expect(await page.evaluate(() => (window as unknown as W).__game.phase)).toBe("over");
});

test("plays on every viewport @responsive", async ({ page }, info) => {
  await boot(page);
  await page.evaluate(() => (window as unknown as W).__game.play());
  await page.evaluate((step) => {
    for (let i = 0; i < 60; i++) (window as unknown as W).__game.tick(step);
  }, STEP);
  expect(await page.evaluate(() => (window as unknown as W).__game.phase)).toBe("playing");
  expect(info.project.name).toBeTruthy();
});
