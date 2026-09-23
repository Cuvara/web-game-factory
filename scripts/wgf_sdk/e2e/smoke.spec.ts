// Browser e2e for the sdk module: the built game on each platform, against the template's
// own SDK mocks.
//
// Copied into tests/wgf-sdk-e2e/ of a scratch copy of web-game-template by
// scripts/wgf_sdk/e2e.py, which builds the bundle once per platform and engine and sets:
//   WGF_E2E_PLATFORM  the build's target platform id
//   WGF_E2E_ENGINE    pixijs | threejs
//   WGF_E2E_EXPECT    "boot" (default) or "boot-failure" for a platform with no adapter
//
// No test reaches a portal: every portal SDK URL is fulfilled from a mock the template
// ships (and which checks the portal's own sequencing rules), or aborted to play the part
// of an ad blocker.

import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const PLATFORM = process.env["WGF_E2E_PLATFORM"] ?? "generic-web";
const ENGINE = process.env["WGF_E2E_ENGINE"] ?? "pixijs";
const EXPECT = process.env["WGF_E2E_EXPECT"] ?? "boot";

type Mode = "available" | "closed-early" | "ad-unavailable" | "sdk-unavailable" | "init-failure";

interface Wiring {
  /** The adapter id the probe reports. */
  readonly adapter: string;
  readonly rewarded: boolean;
  install(page: Page, mode: Mode): Promise<string>;
}

const YANDEX_MOCK = "examples/yandex-compliance-demo/tests/e2e/mock-sdk.js";
const POKI_MOCK = "tests/poki/mock-poki-sdk.js";
const POKI_URL = "https://game-cdn.poki.com/scripts/v2/poki-sdk.js";
const CRAZYGAMES_URL = "https://sdk.crazygames.com/crazygames-sdk-v3.js";

const pick = (mode: Mode, table: Partial<Record<Mode, string>>, fallback: string): string =>
  table[mode] ?? fallback;

const WIRING: Record<string, Wiring> = {
  yandex: {
    adapter: "yandex",
    rewarded: true,
    async install(page, mode) {
      const rewarded = pick(
        mode,
        { "closed-early": "skip", "ad-unavailable": "error" },
        "complete",
      );
      await page.addInitScript(
        (config) => {
          (window as unknown as { __ysdkMockConfig: unknown }).__ysdkMockConfig = config;
        },
        { rewarded, fullscreen: "show", adMs: 50 },
      );
      await page.route("**/sdk.js", (route) => {
        if (mode === "sdk-unavailable") return route.abort();
        const body =
          mode === "init-failure"
            ? "window.YaGames = { init: () => Promise.reject(new Error('mock init failure')) };"
            : readFileSync(YANDEX_MOCK, "utf8");
        return route.fulfill({ contentType: "application/javascript", body });
      });
      return "/";
    },
  },
  poki: {
    adapter: "poki",
    rewarded: true,
    async install(page, mode) {
      // A rejected init() is how Poki's SDK reports an ad blocker; breaks then play nothing.
      const rewarded = pick(
        mode,
        { "closed-early": "no-reward", "ad-unavailable": "none", "init-failure": "none" },
        "reward",
      );
      await page.addInitScript(
        (config) => {
          (window as unknown as { __pokiMock: unknown }).__pokiMock = config;
        },
        { init: mode === "init-failure" ? "reject" : "resolve", rewarded, adMs: 50 },
      );
      await page.route(POKI_URL, (route) =>
        mode === "sdk-unavailable"
          ? route.abort()
          : route.fulfill({
              contentType: "application/javascript",
              body: readFileSync(POKI_MOCK, "utf8"),
            }),
      );
      return "/";
    },
  },
  crazygames: {
    adapter: "crazygames",
    rewarded: true,
    async install(page, mode) {
      // Only template revisions with the CrazyGames adapter carry its mock.
      const mockModule = "../crazygames/mock-sdk.js";
      const { MOCK_SDK_SOURCE } = (await import(/* @vite-ignore */ mockModule)) as {
        MOCK_SDK_SOURCE: string;
      };
      await page.route(CRAZYGAMES_URL, (route) =>
        mode === "sdk-unavailable"
          ? route.abort()
          : route.fulfill({ contentType: "application/javascript", body: MOCK_SDK_SOURCE }),
      );
      const query = pick(
        mode,
        {
          "closed-early": "cgAd=unfilled",
          "ad-unavailable": "cgAd=unfilled",
          "init-failure": "cgEnv=disabled",
        },
        "",
      );
      return `/?cgAdMs=50&cgAdDelayMs=10${query ? `&${query}` : ""}`;
    },
  },
  gamevui: {
    adapter: "generic-web",
    rewarded: false,
    async install() {
      return "/";
    },
  },
};

const wiring = WIRING[PLATFORM];

async function boot(page: Page, mode: Mode): Promise<string[]> {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const path = wiring ? await wiring.install(page, mode) : "/";
  await page.goto(path);
  await expect(page.locator("#hud")).toHaveAttribute("data-ready", "true", { timeout: 30_000 });
  return errors;
}

/** Read the template's release-validation probe, window.__wgf__. */
const probe = <T = unknown>(page: Page, expression: string): Promise<T> =>
  page.evaluate(`window.__wgf__.${expression}`) as Promise<T>;

const run = (page: Page, script: string): Promise<unknown> =>
  page.evaluate(`(async () => { const run = window.__run; return ${script}; })()`);

async function pokiViolations(page: Page): Promise<string[]> {
  return (await page.evaluate("window.__pokiViolations ?? []")) as string[];
}

test.describe(`${PLATFORM} on ${ENGINE}`, () => {
  test.skip(EXPECT !== "boot", "this build targets a platform with no adapter");
  test.skip(!wiring, `no wiring for ${PLATFORM}`);

  test("SDK available: boots on the adapter and signals ready", async ({ page }) => {
    const errors = await boot(page, "available");
    expect(await probe(page, "platformId")).toBe(wiring!.adapter);
    expect(await probe(page, "engine")).toBe(ENGINE);
    expect(await probe(page, "usage().signalReadyCalls")).toBe(1);
    expect(errors).toEqual([]);
  });

  test("reward callback: game over, rewarded ad, continue", async ({ page }) => {
    test.skip(!wiring!.rewarded, `${PLATFORM} offers no rewarded ads`);
    await boot(page, "available");
    await run(page, "run.start()");
    expect(await run(page, "run.miss(true)")).toBe("continued");
    expect(await probe(page, "usage().adsRequested.rewarded")).toBe(1);
    expect(await pokiViolations(page)).toEqual([]);
  });

  test("user closes the ad: no reward, the run restarts", async ({ page }) => {
    test.skip(!wiring!.rewarded, `${PLATFORM} offers no rewarded ads`);
    await boot(page, "closed-early");
    await run(page, "run.start()");
    expect(await run(page, "run.miss(true)")).toBe("restarted");
    expect(await run(page, "run.lastReason")).not.toBeNull();
    expect(await pokiViolations(page)).toEqual([]);
  });

  test("ad unavailable: no reward, the run restarts", async ({ page }) => {
    await boot(page, "ad-unavailable");
    await run(page, "run.start()");
    expect(await run(page, "run.miss(true)")).toBe("restarted");
    expect(await pokiViolations(page)).toEqual([]);
  });

  test("a level transition takes its planned break and play continues", async ({ page }) => {
    await boot(page, "available");
    await run(page, "run.start()");
    expect(await run(page, "run.clearLevel()")).toBe("running");
    expect(await pokiViolations(page)).toEqual([]);
  });

  test("SDK unavailable: playable, and no rewarded offer shown", async ({ page }) => {
    await boot(page, "sdk-unavailable");
    await run(page, "run.start()");
    expect(await run(page, "run.miss(true)")).toBe("restarted");
    expect(await run(page, "run.offered")).toBe(false);
    expect(await run(page, "run.best()")).toBe(10);
  });

  test("SDK initialization failure: still playable, and no reward granted", async ({ page }) => {
    await boot(page, "init-failure");
    await run(page, "run.start()");
    expect(await run(page, "run.miss(true)")).toBe("restarted");
    // Poki documents a rejected init() as an ad blocker and keeps the SDK in use ("load your
    // game anyway"; ad-blocker messaging "is handled on Poki's side"), so its offer may stay
    // visible - but nothing may be granted. Everywhere else the offer must be hidden.
    if (PLATFORM !== "poki") expect(await run(page, "run.offered")).toBe(false);
    expect(await pokiViolations(page)).toEqual([]);
  });

  test("pause and resume stop and restart the simulation", async ({ page }) => {
    await boot(page, "available");
    await run(page, "run.start()");
    await run(page, "run.pause()");
    const frozen = await probe<number>(page, "elapsedMs()");
    await page.waitForTimeout(300);
    expect(await probe(page, "elapsedMs()")).toBe(frozen);
    await run(page, "run.resume()");
    await page.waitForTimeout(300);
    expect(await probe(page, "elapsedMs()")).toBeGreaterThan(frozen);
    expect(await pokiViolations(page)).toEqual([]);
  });

  test("the portal's own pause holds the game until it resumes", async ({ page }) => {
    test.skip(PLATFORM !== "yandex", "only Yandex raises a portal pause (game_api_pause)");
    await boot(page, "available");
    await run(page, "run.start()");
    await page.evaluate("window.__ysdk.fire('game_api_pause')");
    const frozen = await probe<number>(page, "elapsedMs()");
    await page.waitForTimeout(300);
    expect(await probe(page, "elapsedMs()")).toBe(frozen);
    await page.evaluate("window.__ysdk.fire('game_api_resume')");
    await page.waitForTimeout(300);
    expect(await probe(page, "elapsedMs()")).toBeGreaterThan(frozen);
  });

  test("a portal without an SDK never requests an ad", async ({ page }) => {
    test.skip(wiring!.rewarded, "only for platforms without ads");
    await boot(page, "available");
    await run(page, "run.start()");
    await run(page, "run.miss(true)");
    expect(await probe(page, "usage().adsRequested")).toEqual({
      interstitial: 0,
      rewarded: 0,
      banner: 0,
    });
  });
});

test.describe(`${PLATFORM} not configured`, () => {
  test.skip(EXPECT !== "boot-failure", "this build's platform has an adapter");

  test("platform not configured: boot fails visibly, not silently", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#hud")).toHaveAttribute("data-ready", "false", {
      timeout: 30_000,
    });
    await expect(page.locator("#hud")).toContainText("boot failed");
  });
});
