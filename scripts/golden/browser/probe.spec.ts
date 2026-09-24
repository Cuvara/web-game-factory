// The golden harness's own browser probe: plays the built game once per viewport and writes
// what it saw as JSON. It belongs to the Factory's golden-run harness (scripts/golden/), not
// to the game: browser.py copies it into a scratch clone of the game repository, next to a
// generated Playwright config, so the game repository itself is never touched.
//
// Independent of the pipeline: it does not reuse the game's tests or the verify step's
// evidence. Every request to anything but the preview server is aborted and recorded, so it
// never contacts a portal. Console errors and page errors are recorded, not filtered.

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";

const GAME = process.env["GOLDEN_GAME"] ?? "";
const OUT = process.env["GOLDEN_PROBE_OUT"] ?? "golden-probe";

type Hooks = Record<string, unknown> & {
  state: string;
  phase?: string;
  score: number;
  dropAnywhere?: () => void;
  play?: () => void;
  tick?: (dt: number) => void;
  steer?: (dir: number) => void;
  spawnObstacleAt?: (x: number, z: number, halfWidth?: number) => unknown;
  restart: () => Promise<unknown>;
};
type W = {
  __game: Hooks;
  __wgf__?: {
    gameId: string;
    gameVersion: string;
    platformId: string;
    engine: string;
    timeToInteractiveMs: number;
    framesRendered(): number;
  };
};

async function shot(page: Page, dir: string, name: string): Promise<string> {
  const path = join(dir, `${name}.png`);
  await page.screenshot({ path });
  return path;
}

test("golden probe: boot, play, game over, restart", async ({ page }, info) => {
  test.setTimeout(120_000);
  const dir = join(OUT, info.project.name);
  mkdirSync(dir, { recursive: true });
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const blocked: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  });
  page.on("pageerror", (e) => pageErrors.push(e.message));
  await page.route(/^https?:\/\/(?!localhost[:/]|127\.0\.0\.1[:/])/, (route) => {
    blocked.push(route.request().url());
    return route.abort();
  });

  const result: Record<string, unknown> = { game: GAME, project: info.project.name };
  const screenshots: Record<string, string> = {};
  const steps: Record<string, boolean> = {};
  try {
    await page.goto("/");
    await expect(page.locator("#hud")).toHaveAttribute("data-ready", "true", { timeout: 60_000 });
    steps["boot"] = true;
    const probe = await page.evaluate(() => {
      const w = (window as unknown as W).__wgf__;
      return w
        ? {
            gameId: w.gameId,
            gameVersion: w.gameVersion,
            platformId: w.platformId,
            engine: w.engine,
            timeToInteractiveMs: w.timeToInteractiveMs,
            framesRendered: w.framesRendered(),
          }
        : null;
    });
    result["probe"] = probe;
    result["scene"] = await page.locator("#hud").getAttribute("data-scene");
    result["canvas"] = await page.locator("#game canvas").count();
    screenshots["boot"] = await shot(page, dir, "boot");

    if (GAME === "2d") {
      await page.locator('[data-action="play"]').click();
    } else {
      await page.locator("#play").click();
    }
    const phase = (): Promise<string> =>
      page.evaluate(() => {
        const g = (window as unknown as W).__game;
        return String(g.phase ?? g.state);
      });
    steps["start"] = (await phase()) === "playing";
    await page.waitForTimeout(500);
    const frames = await page.evaluate(() => (window as unknown as W).__wgf__?.framesRendered());
    result["frames_after_start"] = frames;
    steps["renders"] = typeof frames === "number" && frames > (probe?.framesRendered ?? 0);
    screenshots["playing"] = await shot(page, dir, "playing");

    if (GAME === "2d") {
      await page.evaluate(() => {
        const g = (window as unknown as W).__game;
        for (let i = 0; i < 500 && g.state !== "over"; i++) g.dropAnywhere?.();
      });
    } else {
      await page.evaluate(() => {
        const g = (window as unknown as W).__game;
        for (let i = 0; i < 120; i++) g.tick?.(1000 / 60);
        g.steer?.(0);
        g.spawnObstacleAt?.(0, 1, 0.8);
        for (let i = 0; i < 60 && g.phase === "playing"; i++) g.tick?.(1000 / 60);
      });
    }
    result["score_at_game_over"] = await page.evaluate(() => (window as unknown as W).__game.score);
    steps["game-over"] = (await phase()) === "over";
    screenshots["over"] = await shot(page, dir, "over");

    await page.evaluate(() => (window as unknown as W).__game.restart());
    await expect.poll(phase, { timeout: 20_000 }).toBe(GAME === "2d" ? "start" : "playing");
    steps["restart"] = true;
    result["score_after_restart"] = await page.evaluate(
      () => (window as unknown as W).__game.score,
    );
  } finally {
    result["steps"] = steps;
    result["screenshots"] = screenshots;
    result["console_errors"] = consoleErrors;
    result["page_errors"] = pageErrors;
    result["blocked_external_requests"] = blocked;
    writeFileSync(join(dir, "probe.json"), JSON.stringify(result, null, 2) + "\n");
  }
  expect(pageErrors).toEqual([]);
  expect(steps).toEqual({ boot: true, start: true, renders: true, "game-over": true, restart: true });
});
