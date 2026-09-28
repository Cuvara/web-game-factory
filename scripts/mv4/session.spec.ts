// MV-4's browser session harness: plays a built game in a real browser and records what the
// browser actually did.
//
// It belongs to the Factory's MV-4 evidence harness (scripts/mv4/), not to any game:
// session.py copies it into a scratch clone of a game repository next to a generated Playwright
// config, so the game repository is never touched. It contains no game — it drives whatever
// game is there through the template's own window hooks.
//
// What it measures, and the class of each measurement, is in docs/mv-4-plan.md. The class is
// derived from the Playwright project name, never passed in: a project running a device
// descriptor is `emulated-mobile` and can never be reported as a device result.
//
// Every request to anything but the preview server is aborted and recorded, so this never
// contacts a portal.

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type CDPSession, type Page } from "@playwright/test";

const OUT = process.env["MV4_OUT"] ?? "mv4-session";
const ARTIFACT = process.env["MV4_ARTIFACT"] ?? "";
const ARTIFACT_SHA = process.env["MV4_ARTIFACT_SHA"] ?? "";
/** Seconds of continuous play sampled for the frame-rate statistics. */
const SAMPLE_S = Number(process.env["MV4_SAMPLE_S"] ?? "20");

type Hooks = Record<string, unknown> & {
  score?: number | (() => number);
  state?: string;
  drop?: (col: number) => void;
  dropAnywhere?: () => void;
  forceGameOver?: () => void;
  isGameOver?: () => boolean;
  isPaused?: () => boolean;
  restart: () => unknown;
};

type Probe = {
  gameId: string;
  gameVersion: string;
  platformId: string;
  engine: string;
  timeToInteractiveMs: number;
  framesRendered(): number;
  elapsedMs(): number;
  usage(): Record<string, unknown>;
};

type Sampler = {
  deltas: number[];
  audio: { created: number; states: string[] };
  stop?: () => void;
};

type W = { __game?: Hooks; __wgf__?: Probe; __mv4__?: Sampler };

/** `emulated-mobile` for any project carrying a device descriptor; a desktop run is real. */
function measurementClass(project: string): string {
  return project.startsWith("mobile") ? "emulated-mobile" : "real-browser-desktop";
}

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  const index = Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length));
  return sorted[index] as number;
}

/** Frame statistics from raw frame-to-frame deltas in milliseconds. */
function frameStats(deltas: number[]): Record<string, number> {
  const sorted = [...deltas].sort((a, b) => a - b);
  const median = percentile(sorted, 50);
  // The worst one-second window: the lowest frame count in any 1000 ms of the sample.
  let worst = Number.POSITIVE_INFINITY;
  let start = 0;
  let sum = 0;
  for (let end = 0; end < deltas.length; end++) {
    sum += deltas[end] as number;
    while (sum > 1000 && start < end) {
      worst = Math.min(worst, end - start);
      sum -= deltas[start] as number;
      start++;
    }
  }
  return {
    frames: deltas.length,
    median_fps: median > 0 ? Number((1000 / median).toFixed(2)) : 0,
    mean_fps:
      deltas.length > 0
        ? Number((1000 / (deltas.reduce((a, b) => a + b, 0) / deltas.length)).toFixed(2))
        : 0,
    p50_frame_ms: Number(median.toFixed(2)),
    p95_frame_ms: Number(percentile(sorted, 95).toFixed(2)),
    p99_frame_ms: Number(percentile(sorted, 99).toFixed(2)),
    worst_frame_ms: Number((sorted[sorted.length - 1] ?? 0).toFixed(2)),
    worst_1s_fps: Number.isFinite(worst) ? worst : deltas.length,
  };
}

async function heapBytes(cdp: CDPSession, page: Page): Promise<number | null> {
  // Collect first: a heap read without a collection measures garbage, not retention.
  await cdp.send("HeapProfiler.collectGarbage");
  return page.evaluate(() => {
    const memory = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory;
    return memory ? memory.usedJSHeapSize : null;
  });
}

const steps = (page: Page): Promise<number> =>
  page.locator("#hud").getAttribute("data-steps").then((value) => Number(value ?? "0"));

/** A real pointer gesture in the middle of the canvas: the input a player would give. */
async function tapCanvas(page: Page): Promise<void> {
  const box = await page.locator("#game canvas").boundingBox();
  if (!box) return;
  await page.mouse.click(box.x + box.width / 2, box.y + box.height * 0.8);
}

test("mv4 browser session", async ({ page, context, browserName }, info) => {
  test.setTimeout(300_000);
  const dir = join(OUT, info.project.name);
  mkdirSync(dir, { recursive: true });
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const blocked: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  // Everything external is aborted, as in the golden runs - unless the operator named hosts to
  // let through (MV4_ALLOW_HOSTS). That is how the portal SDK's own script can be fetched from
  // the portal's origin for criterion D, deliberately, host by host, and recorded in full.
  const allowedHosts = (process.env["MV4_ALLOW_HOSTS"] ?? "")
    .split(",")
    .map((host) => host.trim())
    .filter(Boolean);
  const allowed: Record<string, unknown>[] = [];
  page.on("response", (response) => {
    const host = new URL(response.url()).hostname;
    if (allowedHosts.some((allow) => host === allow || host.endsWith(`.${allow}`))) {
      allowed.push({ url: response.url(), status: response.status() });
    }
  });
  await page.route(/^https?:\/\/(?!localhost[:/]|127\.0\.0\.1[:/])/, (route) => {
    const host = new URL(route.request().url()).hostname;
    if (allowedHosts.some((allow) => host === allow || host.endsWith(`.${allow}`))) {
      return route.continue();
    }
    blocked.push(route.request().url());
    return route.abort();
  });

  // Installed before any of the bundle runs: a frame sampler of our own, and a wrapper that
  // records whether the game ever creates an AudioContext and what state it is in. Neither
  // changes the bundle — this is the browser's own API, observed from outside.
  await page.addInitScript(() => {
    const sampler = { deltas: [] as number[], audio: { created: 0, states: [] as string[] } };
    (window as unknown as W).__mv4__ = sampler;
    let last = 0;
    let running = false;
    const frame = (now: number): void => {
      if (last > 0 && running) sampler.deltas.push(now - last);
      last = now;
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
    Object.defineProperty(sampler, "stop", { value: () => (running = false) });
    (window as unknown as { __mv4start__: () => void }).__mv4start__ = () => {
      sampler.deltas.length = 0;
      running = true;
    };
    (window as unknown as { __mv4stop__: () => void }).__mv4stop__ = () => (running = false);
    const Original = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (Original) {
      const Wrapped = function (this: unknown, ...args: unknown[]): AudioContext {
        const instance = new (Original as unknown as new (...a: unknown[]) => AudioContext)(...args);
        sampler.audio.created += 1;
        sampler.audio.states.push(instance.state);
        return instance;
      } as unknown as typeof AudioContext;
      Wrapped.prototype = Original.prototype;
      window.AudioContext = Wrapped;
    }
  });

  const result: Record<string, unknown> = {
    project: info.project.name,
    browser: browserName,
    measurement_class: measurementClass(info.project.name),
    artifact: ARTIFACT,
    artifact_sha256: ARTIFACT_SHA,
    viewport: page.viewportSize(),
    sample_seconds: SAMPLE_S,
  };
  const checks: Record<string, unknown> = {};

  try {
    const cdp = await context.newCDPSession(page);
    // The same 4x CPU throttle the template's own facts run uses as a stand-in for a low-end
    // handset. It is a proxy and is labelled one: the project carrying it is `emulated-mobile`.
    if (info.project.name.endsWith("-throttled")) {
      await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
      result["cpu_throttle_rate"] = 4;
    }
    const startedAt = Date.now();
    await page.goto("/");
    await expect(page.locator("#hud")).toHaveAttribute("data-ready", "true", { timeout: 60_000 });
    result["wall_load_ms"] = Date.now() - startedAt;

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
            usage: w.usage(),
          }
        : null;
    });
    result["probe"] = probe;
    result["hooks"] = await page.evaluate(() => {
      const g = (window as unknown as W).__game;
      return g ? Object.keys(g).sort() : null;
    });
    checks["boot"] = { status: "PASS", detail: "hud reported ready" };
    checks["time_to_interactive"] = {
      status: probe && probe.timeToInteractiveMs <= 5000 ? "PASS" : "FAIL",
      value_s: probe ? Number((probe.timeToInteractiveMs / 1000).toFixed(3)) : null,
      threshold_s: 5,
      source: "the game's own probe, navigation start to signalReady",
    };

    // -- audio before any gesture ----------------------------------------------------------
    const audioBefore = await page.evaluate(
      () => (window as unknown as W).__mv4__?.audio ?? null,
    );

    // -- sustained play --------------------------------------------------------------------
    const heapStart = await heapBytes(cdp, page);
    const stepsBeforePlay = await steps(page);
    // A real gesture first (it is what unlocks audio). Then the play loop runs INSIDE the page
    // for the whole sample: a `page.evaluate` every 250 ms from Node would have the harness's
    // own CDP round-trips inside the frame times it is measuring, and the first version of this
    // spec measured exactly that (a suspiciously exact 30.03 fps).
    await tapCanvas(page);
    await page.evaluate(() => {
      const w = window as unknown as W & { __mv4start__: () => void; __mv4drive__?: number;
                                           __mv4moves__?: number };
      w.__mv4start__();
      w.__mv4moves__ = 0;
      w.__mv4drive__ = window.setInterval(() => {
        const g = w.__game;
        if (!g) return;
        w.__mv4moves__ = (w.__mv4moves__ ?? 0) + 1;
        if (g.isGameOver?.() === true || g.state === "over") void g.restart();
        else if (typeof g.drop === "function") g.drop(Math.floor(Math.random() * 7));
        else g.dropAnywhere?.();
      }, 250);
    });
    await page.waitForTimeout(SAMPLE_S * 1000);
    const moves = await page.evaluate(() => {
      const w = window as unknown as W & { __mv4stop__: () => void; __mv4drive__?: number;
                                          __mv4moves__?: number };
      if (w.__mv4drive__ !== undefined) window.clearInterval(w.__mv4drive__);
      w.__mv4stop__();
      return w.__mv4moves__ ?? 0;
    });
    const deltas = await page.evaluate(() => (window as unknown as W).__mv4__?.deltas ?? []);
    const stats = frameStats(deltas);
    result["frame_stats"] = stats;
    result["raw_frame_deltas_ms"] = deltas.map((d) => Number(d.toFixed(2)));
    result["moves_played"] = moves;
    result["steps_during_play"] = (await steps(page)) - stepsBeforePlay;
    checks["sustained_frame_rate"] = {
      status: stats["median_fps"] !== undefined && (stats["median_fps"] as number) >= 30 ? "PASS" : "FAIL",
      median_fps: stats["median_fps"],
      p95_frame_ms: stats["p95_frame_ms"],
      note: "this run's class decides what this may be claimed for; a desktop result is not a device result",
    };

    const audioAfter = await page.evaluate(
      () => (window as unknown as W).__mv4__?.audio ?? null,
    );
    result["audio"] = { before_gesture: audioBefore, after_gesture: audioAfter };
    checks["audio_unlocks_on_gesture"] =
      audioAfter && audioAfter.created > 0
        ? {
            status: (audioBefore?.created ?? 0) === 0 ? "PASS" : "FAIL",
            detail: `no AudioContext before the first gesture, ${audioAfter.created} after; states ${JSON.stringify(audioAfter.states)}`,
          }
        : {
            status: "UNVERIFIED",
            detail: "the build created no AudioContext in this session; nothing to observe",
          };

    // -- hidden tab, and recovery ----------------------------------------------------------
    // A real visibility change: a second page in the same context brought to the front makes
    // this one hidden as far as the browser is concerned.
    const stepsBeforeHidden = await steps(page);
    const framesBeforeHidden = await page.evaluate(
      () => (window as unknown as W).__wgf__?.framesRendered() ?? null,
    );
    // Minimising the window is the one way to make a page genuinely hidden from outside it:
    // a second page brought to the front is a second WINDOW, and both stay visible (headless
    // and headed alike reported "visible" that way, which is why the check said UNVERIFIED
    // rather than passing on a visibility change that never happened).
    let restoreBounds: (() => Promise<void>) | null = null;
    try {
      const { windowId, bounds } = (await cdp.send("Browser.getWindowForTarget")) as {
        windowId: number;
        bounds: Record<string, unknown>;
      };
      await cdp.send("Browser.setWindowBounds", { windowId, bounds: { windowState: "minimized" } });
      restoreBounds = async () => {
        await cdp.send("Browser.setWindowBounds", { windowId, bounds: { windowState: "normal" } });
        await cdp.send("Browser.setWindowBounds", { windowId, bounds });
      };
    } catch {
      restoreBounds = null;
    }
    await page.waitForTimeout(3000);
    const hiddenState = await page.evaluate(() => document.visibilityState);
    const pausedWhileHidden = await page.evaluate(
      () => (window as unknown as W).__game?.isPaused?.() ?? null,
    );
    const stepsAfterHidden = await steps(page);
    if (restoreBounds) await restoreBounds();
    await page.bringToFront();
    await page.waitForTimeout(1000);
    const stepsAfterReturn = await steps(page);
    await tapCanvas(page);
    await page.evaluate(() => {
      const g = (window as unknown as W).__game;
      if (typeof g?.drop === "function") g.drop(3);
      else g?.dropAnywhere?.();
    });
    await page.waitForTimeout(1000);
    const stepsAfterInput = await steps(page);
    const framesAfterReturn = await page.evaluate(
      () => (window as unknown as W).__wgf__?.framesRendered() ?? null,
    );
    result["visibility"] = {
      state_while_hidden: hiddenState,
      paused_while_hidden: pausedWhileHidden,
      steps_before_hidden: stepsBeforeHidden,
      steps_after_hidden: stepsAfterHidden,
      steps_after_return: stepsAfterReturn,
      steps_after_input: stepsAfterInput,
      frames_before_hidden: framesBeforeHidden,
      frames_after_return: framesAfterReturn,
    };
    checks["pauses_when_hidden"] = {
      status:
        hiddenState !== "hidden"
          ? "UNVERIFIED"
          : stepsAfterHidden === stepsBeforeHidden
            ? "PASS"
            : "FAIL",
      detail: `visibilityState ${hiddenState}; simulation steps ${stepsBeforeHidden} -> ${stepsAfterHidden} over 3 s hidden`,
    };
    checks["recovers_after_return"] = {
      status: stepsAfterInput > stepsAfterHidden ? "PASS" : "FAIL",
      detail: `steps ${stepsAfterHidden} -> ${stepsAfterReturn} on return, ${stepsAfterInput} after a real input`,
    };

    // -- resize and orientation ------------------------------------------------------------
    const size = page.viewportSize() ?? { width: 1280, height: 720 };
    await page.setViewportSize({ width: Math.round(size.width * 0.6), height: size.height });
    await page.waitForTimeout(500);
    const afterResize = await steps(page);
    await page.setViewportSize({ width: size.height, height: size.width });
    await page.waitForTimeout(500);
    const afterRotate = await steps(page);
    const canvasAfterRotate = await page.locator("#game canvas").count();
    await page.setViewportSize(size);
    await page.waitForTimeout(500);
    const afterRestore = await steps(page);
    result["layout"] = {
      after_resize_steps: afterResize,
      after_rotate_steps: afterRotate,
      after_restore_steps: afterRestore,
      canvas_after_rotate: canvasAfterRotate,
    };
    checks["survives_resize"] = {
      status: afterResize > stepsAfterInput ? "PASS" : "FAIL",
      detail: `steps advanced ${stepsAfterInput} -> ${afterResize} across a 40% width change`,
    };
    checks["survives_orientation_swap"] = {
      status: afterRotate > afterResize && canvasAfterRotate === 1 ? "PASS" : "FAIL",
      detail:
        `steps advanced ${afterResize} -> ${afterRotate} across a viewport swap, canvas count ${canvasAfterRotate}. ` +
        "A viewport swap in a desktop browser is not a device orientation change; criterion B covers that.",
    };

    // -- game over, restart, and the heap across it ----------------------------------------
    // Like for like: the two heap readings are taken in the same game state - a fresh run with
    // the same number of drops played into it - with one full game-over and restart between
    // them. Comparing "just booted" with "restarted and played" would be comparing two
    // different games, and the first version of this spec did exactly that.
    const playDrops = async (count: number): Promise<void> => {
      for (let i = 0; i < count; i++) {
        await page.evaluate((column: number) => {
          const g = (window as unknown as W).__game;
          if (typeof g?.drop === "function") g.drop(column);
          else g?.dropAnywhere?.();
        }, i % 7);
        await page.waitForTimeout(60);
      }
    };
    const endRun = async (): Promise<boolean> => {
      await page.evaluate(() => {
        const g = (window as unknown as W).__game;
        if (typeof g?.forceGameOver === "function") g.forceGameOver();
        else for (let i = 0; i < 500 && g?.state !== "over"; i++) g?.dropAnywhere?.();
      });
      await page.waitForTimeout(500);
      const reached = await page.evaluate(() => {
        const g = (window as unknown as W).__game;
        return g?.isGameOver?.() ?? g?.state === "over";
      });
      await page.evaluate(() => (window as unknown as W).__game?.restart());
      await page.waitForTimeout(1500);
      return reached === true;
    };

    const over = await endRun();            // end the sampled run, start a clean one
    await playDrops(20);
    const heapRunOne = await heapBytes(cdp, page);
    const overAgain = await endRun();       // a second full run from the same state
    await playDrops(20);
    const heapRunTwo = await heapBytes(cdp, page);
    result["heap"] = {
      at_boot_bytes: heapStart,
      run_one_bytes: heapRunOne,
      run_two_bytes: heapRunTwo,
      method: "20 drops into a fresh run, collected, then one game-over, restart and the same "
        + "20 drops; both readings are the same game state",
    };
    checks["game_over_reached"] = {
      status: over && overAgain ? "PASS" : "UNVERIFIED",
      detail: `game-over reached and restarted twice: ${String(over)}, ${String(overAgain)}`,
    };
    // Chromium rounds performance.memory to a bucket unless --enable-precise-memory-info is
    // on. Two identical round numbers are a bucket, not a measurement, and saying so is the
    // difference between "no leak" and "nothing was measured".
    const bucketed =
      heapRunOne !== null && heapRunTwo !== null && heapRunOne === heapRunTwo
      && heapRunOne % 100_000 === 0;
    checks["no_leak_across_restart"] = !heapRunOne || !heapRunTwo
      ? { status: "UNVERIFIED", detail: "this browser reported no performance.memory" }
      : bucketed
        ? {
            status: "UNVERIFIED",
            detail: `performance.memory reported the same round value twice (${heapRunOne}); the browser bucketed it, so nothing was measured`,
          }
        : {
            status: heapRunTwo <= heapRunOne * 1.5 ? "PASS" : "FAIL",
            detail: `used JS heap ${heapRunOne} -> ${heapRunTwo} bytes between two equivalent runs, one game-over and restart apart (threshold 1.5x)`,
          };

    // -- telemetry, read out of the running build ------------------------------------------
    const usage = await page.evaluate(() => {
      const w = (window as unknown as W).__wgf__;
      return w ? { usage: w.usage(), frames: w.framesRendered(), elapsed_ms: w.elapsedMs() } : null;
    });
    result["telemetry"] = {
      kind: "test-telemetry",
      source: "window.__wgf__, the build's own read-only probe; nothing was added to the bundle",
      collected: usage,
    };
    checks["telemetry_collected"] = {
      status: usage ? "PASS" : "FAIL",
      detail: usage ? "session counters read from the running build" : "no probe on the page",
    };
  } finally {
    // Criterion D, as far as it goes without a portal account: was the portal's own script
    // served, and did the build still reach ready with it in place. Whether the portal accepts
    // the integration, and anything about an ad, needs the portal and stays BLOCKED_EXTERNAL.
    if (allowedHosts.length > 0) {
      const served = allowed.filter((entry) => Number(entry["status"]) < 400);
      checks["portal_sdk_script_served"] = {
        status: served.length > 0 ? "PASS" : "FAIL",
        evidence_status: "PASS",
        detail: `${served.length} of ${allowed.length} request(s) to ${allowedHosts.join(", ")} succeeded`,
      };
      checks["boots_with_the_portal_script_present"] = {
        status: (checks["boot"] as { status?: string } | undefined)?.status === "PASS"
          ? "PASS" : "FAIL",
        evidence_status: "PASS",
        detail: "the build reached ready with the portal's own script served from its origin",
      };
      checks["portal_behaviour"] = {
        status: "BLOCKED_EXTERNAL",
        detail: "no portal account, no registered game: nothing the portal itself does - ad "
          + "fill, lifecycle acceptance, review - can be observed from here, and no ad was "
          + "requested",
      };
    }
    result["allowed_external_requests"] = allowed;
    result["checks"] = checks;
    result["console_errors"] = consoleErrors;
    result["page_errors"] = pageErrors;
    result["blocked_external_requests"] = blocked;
    writeFileSync(join(dir, "session.json"), JSON.stringify(result, null, 2) + "\n");
  }

  // The session is the evidence; a browser that threw is a finding, not a harness error.
  expect(pageErrors).toEqual([]);
});
