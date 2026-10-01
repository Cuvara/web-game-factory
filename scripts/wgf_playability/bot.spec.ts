// The playability bot: plays a built game from outside, as a first-time player's device would.
//
// Copied by the Factory's playability step (scripts/wgf_playability/step.py) into a scratch
// clone of the game repository, and run there with the repository's own Playwright against
// its production build (`pnpm preview`). It reads the game's play probe
// (window.__wgf__.play.snapshot(), core/artifacts/shared/play-probe.schema.json) and acts ONLY
// through real pointer, touch and key input - never through the probe. Each test is a fresh
// browser context, so each starts as a first session.
//
// It judges nothing. It records what happened - snapshots, timings, frames, per-frame entity
// samples - to <WGF_PLAY_OUT>/<project>/<test>.json and frames/*.png, and the step's Python
// side holds that to the design's experience contract and core/reference/visual-quality.yaml.
// Factory tooling: it contains no game, and is not part of one.

import { test, type Page } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

interface Move {
  action: string;
  input: { type: "pointer"; x: number; y: number; hold_ms?: number } | { type: "key"; key: string; hold_ms?: number };
}
interface Snapshot {
  state: string;
  metrics: Record<string, number>;
  entities: { id: string; role: string; x: number; y: number; w: number; h: number; visible: boolean }[];
  inputs: Move[];
  oracle?: Move | null;
}

const OUT = process.env.WGF_PLAY_OUT as string;
const CFG = JSON.parse(fs.readFileSync(process.env.WGF_PLAY_CONFIG as string, "utf8")) as {
  idle_ms: number;
  ack_ms: number;
  win_ms: number;
  lose_ms: number;
  start_timeout_ms: number;
  goal_metric: string;
  has_win: boolean;
};
const URL = "/?wgf-probe=1";

function dir(project: string): string {
  const d = path.join(OUT, project, "frames");
  fs.mkdirSync(d, { recursive: true });
  return path.join(OUT, project);
}

function write(project: string, name: string, data: unknown): void {
  fs.writeFileSync(path.join(dir(project), `${name}.json`), JSON.stringify(data, null, 1));
}

async function snap(page: Page): Promise<Snapshot | null> {
  return page.evaluate(() => {
    const play = (window as unknown as { __wgf__?: { play?: { snapshot(): unknown } } }).__wgf__?.play;
    try {
      return play && typeof play.snapshot === "function" ? (play.snapshot() as Snapshot) : null;
    } catch (error) {
      return { error: String(error) } as unknown as Snapshot;
    }
  });
}

async function frame(page: Page, project: string, id: string, frames: string[]): Promise<void> {
  await page.screenshot({ path: path.join(dir(project), "frames", `${id}.png`) });
  frames.push(id);
}

// One input, as a player's device makes it: a tap, click or key press, or - with hold_ms -
// held down that long (a touch held through the DevTools protocol: Playwright's touchscreen
// only taps).
async function act(page: Page, move: Move, touch: boolean): Promise<void> {
  const hold = move.input.hold_ms ?? 0;
  if (move.input.type === "key") {
    if (!hold) return page.keyboard.press(move.input.key);
    await page.keyboard.down(move.input.key);
    await page.waitForTimeout(hold);
    await page.keyboard.up(move.input.key);
  } else if (touch && hold) {
    const cdp = await page.context().newCDPSession(page);
    const point = { x: move.input.x, y: move.input.y };
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [point] });
    await page.waitForTimeout(hold);
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await cdp.detach();
  } else if (touch) {
    await page.touchscreen.tap(move.input.x, move.input.y);
  } else if (hold) {
    await page.mouse.move(move.input.x, move.input.y);
    await page.mouse.down();
    await page.waitForTimeout(hold);
    await page.mouse.up();
  } else {
    await page.mouse.click(move.input.x, move.input.y);
  }
}

// The input a title screen offers to begin play ("play", "start", ...), if it lists one.
const BEGIN = /^(play|start|begin|tap-to-start|continue)$/i;
// Inputs that are not moves in the game.
const UTILITY = /pause|resume|menu|settings|sound|mute|music|fullscreen/i;

// Opens the game as a first session and waits for play, pressing the title screen's own
// begin input (as the probe lists it) as a player would. Returns the timings it measured.
async function start(page: Page, touch: boolean): Promise<{ firstSnapshotMs: number | null; playingMs: number | null; samples: Snapshot[]; began: string | null }> {
  const t0 = Date.now();
  await page.goto(URL, { waitUntil: "domcontentloaded" });
  let firstSnapshotMs: number | null = null;
  let began: string | null = null;
  let pressedAt = 0;
  const samples: Snapshot[] = [];
  while (Date.now() - t0 < CFG.start_timeout_ms) {
    const s = await snap(page);
    if (s && firstSnapshotMs === null) firstSnapshotMs = Date.now() - t0;
    if (s && samples.length < 3) samples.push(s);
    if (s?.state === "playing") return { firstSnapshotMs, playingMs: Date.now() - t0, samples, began };
    const begin = s && s.state !== "loading" ? s.inputs?.find((m) => BEGIN.test(m.action)) : undefined;
    if (begin && Date.now() - pressedAt > 1000) {
      await act(page, begin, touch);
      began = begin.action;
      pressedAt = Date.now();
    }
    await page.waitForTimeout(50);
  }
  return { firstSnapshotMs, playingMs: null, samples, began };
}

function errorsOf(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message.slice(0, 300)));
  return errors;
}

test("first session: objective, and no failure before the grace", async ({ page }, info) => {
  const project = info.project.name;
  const errors = errorsOf(page);
  const frames: string[] = [];
  const started = await start(page, Boolean(info.project.use.hasTouch));
  const texts: string[] = [];
  const states: { ms: number; state: string }[] = [];
  let lostAtMs: number | null = null;
  if (started.playingMs !== null) {
    const t0 = Date.now();
    let shot = false;
    // No input at all, for the idle window: a first-time player still reading the screen.
    while (Date.now() - t0 < CFG.idle_ms) {
      const s = await snap(page);
      if (s && (states.length === 0 || states[states.length - 1].state !== s.state)) {
        states.push({ ms: Date.now() - t0, state: s.state });
      }
      if (s?.state === "lost" && lostAtMs === null) lostAtMs = Date.now() - t0;
      if (Date.now() - t0 < 3000) texts.push(await page.evaluate(() => document.body.innerText));
      if (!shot && Date.now() - t0 > 1000) {
        await frame(page, project, "first-session-1s", frames);
        shot = true;
      }
      await page.waitForTimeout(200);
    }
    await frame(page, project, "first-session-idle-end", frames);
  }
  write(project, "first-session", { ...started, texts: [...new Set(texts)], states, lostAtMs, errors, frames });
});

test("act: every action is acknowledged on screen", async ({ page }, info) => {
  const project = info.project.name;
  const errors = errorsOf(page);
  const frames: string[] = [];
  const touch = Boolean(info.project.use.hasTouch);
  const started = await start(page, touch);
  const acted: unknown[] = [];
  if (started.playingMs !== null) {
    const s0 = await snap(page);
    const seen = new Set<string>();
    for (const move of s0?.inputs ?? []) {
      if (seen.has(move.action) || seen.size >= 4) continue;
      seen.add(move.action);
      const before = await snap(page);
      const id = `act-${move.action}`;
      await frame(page, project, `${id}-before`, frames);
      await act(page, move, touch);
      await page.waitForTimeout(CFG.ack_ms);
      await frame(page, project, `${id}-after`, frames);
      acted.push({ action: move.action, input: move.input, before, after: await snap(page) });
      await page.waitForTimeout(400);
    }
  }
  write(project, "act", { ...started, acted, errors, frames });
});

test("win: the oracle plays well", async ({ page }, info) => {
  const project = info.project.name;
  const errors = errorsOf(page);
  const frames: string[] = [];
  const touch = Boolean(info.project.use.hasTouch);
  const started = await start(page, touch);
  const series: { ms: number; value: number | null; state: string }[] = [];
  let reached: string | null = null;
  let inputs = 0;
  let sampled: unknown = null;
  if (started.playingMs !== null) {
    // Every frame for 10 s of play: which entities are drawn, and where. Long enough for a
    // threat that spawns on the horizon to reach the player, where it has to be read.
    const sampler = page.evaluate(async (ms: number) => {
      const out: [string, string, number, number, number, number, number][][] = [];
      const end = performance.now() + ms;
      while (performance.now() < end) {
        await new Promise((r) => requestAnimationFrame(r));
        const play = (window as unknown as { __wgf__?: { play?: { snapshot(): Snapshot } } }).__wgf__?.play;
        const s = play?.snapshot();
        if (s) out.push(s.entities.map((e) => [e.id, e.role, e.visible ? 1 : 0, e.x, e.y, e.w, e.h]));
      }
      return { frames: out, viewport: [innerWidth, innerHeight] };
    }, 10000);
    const t0 = Date.now();
    let shot = false;
    while (Date.now() - t0 < CFG.win_ms) {
      const s = await snap(page);
      if (!s) break;
      series.push({ ms: Date.now() - t0, value: s.metrics?.[CFG.goal_metric] ?? null, state: s.state });
      if (s.state === "won" || s.state === "lost") {
        reached = s.state;
        break;
      }
      if (!shot && Date.now() - t0 > 2000) {
        await frame(page, project, "play-2s", frames);
        shot = true;
      }
      if (!CFG.has_win && Date.now() - t0 > 20000) break;
      if (s.oracle) {
        await act(page, s.oracle, touch);
        inputs += 1;
        await page.waitForTimeout(120);
      } else {
        await page.waitForTimeout(30);
      }
    }
    sampled = await sampler;
    if (reached) await frame(page, project, `end-${reached}`, frames);
  }
  write(project, "win", { ...started, reached, inputs, series: series.filter((_, i) => i % 5 === 0 || i === series.length - 1), sampled, errors, frames });
});

test("lose and restart: the anti-oracle plays badly, then retries", async ({ page }, info) => {
  const project = info.project.name;
  const errors = errorsOf(page);
  const frames: string[] = [];
  const touch = Boolean(info.project.use.hasTouch);
  const started = await start(page, touch);
  let reached: string | null = null;
  let initial: Record<string, number> | null = null;
  let restart: unknown = null;
  if (started.playingMs !== null) {
    initial = (await snap(page))?.metrics ?? null;
    const t0 = Date.now();
    // One success first, as a first-time player would: the grace ends at the first success.
    let succeeded = false;
    while (Date.now() - t0 < CFG.lose_ms) {
      const s = await snap(page);
      if (!s) break;
      if (s.state === "lost" || s.state === "won") {
        reached = s.state;
        break;
      }
      if (!succeeded && s.oracle) {
        await act(page, s.oracle, touch);
        succeeded = true;
      } else if (s.oracle) {
        // The first move that is not the oracle's, never a pause or settings toggle (bad
        // play, not no play); with no other move, the only one there is.
        const moves = s.inputs.filter((m) => !UTILITY.test(m.action));
        const wrong = moves.find((m) => JSON.stringify(m) !== JSON.stringify(s.oracle)) ?? s.oracle;
        await act(page, wrong, touch);
      }
      await page.waitForTimeout(150);
    }
    if (reached) {
      await frame(page, project, `end-${reached}`, frames);
      const at = await snap(page);
      // The retry the result screen offers: an input the probe lists, else the visible button.
      const retryMove = at?.inputs.find((m) => /retry|restart|again|replay/i.test(m.action));
      const t1 = Date.now();
      let clicked: string | null = null;
      if (retryMove) {
        await act(page, retryMove, touch);
        clicked = `input:${retryMove.action}`;
      } else {
        const button = page.getByRole("button", { name: /retry|restart|play again|try again|replay/i }).first();
        if (await button.count()) {
          await button.click();
          clicked = "button";
        }
      }
      let playingMs: number | null = null;
      let after: Snapshot | null = null;
      let pressedAt = Date.now();
      while (clicked && Date.now() - t1 < 15000) {
        after = await snap(page);
        if (after?.state === "playing") {
          playingMs = Date.now() - t1;
          break;
        }
        // A retry that lands on a ready screen: the player presses its begin input too, and
        // that time counts.
        const begin = after && after.state !== "lost" ? after.inputs?.find((m) => BEGIN.test(m.action)) : undefined;
        if (begin && Date.now() - pressedAt > 500) {
          await act(page, begin, touch);
          clicked = `${clicked}+${begin.action}`;
          pressedAt = Date.now();
        }
        await page.waitForTimeout(50);
      }
      restart = { clicked, playingMs, metrics: after?.metrics ?? null, endMetrics: at?.metrics ?? null };
    }
  }
  write(project, "lose", { ...started, initial, reached, restart, errors, frames });
});
