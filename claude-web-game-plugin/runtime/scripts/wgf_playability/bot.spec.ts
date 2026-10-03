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
// For the production gate (scripts/wgf_production) every record also carries what the page
// fetched under /assets/ (and the runtime manifest it fetched), every runtime asset id the
// probe reported loaded, and the DOM UI measured on each screen state it saw - title,
// playing, paused, won/lost and after a retry - each with its own frame `state-<name>.png`.
// When the probe reports `audio`, every record carries the samples it saw (state, music,
// playing, measured level), and the first session also records the level while the page has
// lost focus - the platform rule every portal shares: no sound when the player looks away.
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
  entities: { id: string; role: string; x: number; y: number; w: number; h: number; visible: boolean; asset?: string | null; render?: string }[];
  inputs: Move[];
  assets_loaded?: string[];
  audio?: { music: string | null; playing: boolean; level: number; muted?: boolean };
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

// What one test saw beside play itself: page errors, every response for a file under
// /assets/ (and the runtime manifest's body), the runtime asset ids the probe reported
// loaded, and the UI measured per screen state. Spread into the test's record.
class Watch {
  errors: string[] = [];
  requests: { url: string; status: number | null }[] = [];
  runtimeAssets: unknown = null;
  loaded = new Set<string>();
  ui: Record<string, unknown> = {};
  audio: { ms: number; state: string; music: string | null; playing: boolean; level: number; muted: boolean | null }[] = [];
  readonly t0 = Date.now();

  constructor(readonly page: Page, readonly project: string, readonly frames: string[]) {
    page.on("pageerror", (e) => this.errors.push(e.message.slice(0, 300)));
    page.on("response", async (response) => {
      const url = new globalThis.URL(response.url());
      if (!url.pathname.includes("/assets/")) return;
      this.requests.push({ url: url.pathname, status: response.status() });
      if (url.pathname.endsWith("/assets/assets.json") && response.ok() && this.runtimeAssets === null) {
        try {
          this.runtimeAssets = await response.json();
        } catch {
          this.runtimeAssets = { unreadable: true };
        }
      }
    });
    page.on("requestfailed", (request) => {
      const url = new globalThis.URL(request.url());
      if (url.pathname.includes("/assets/")) this.requests.push({ url: url.pathname, status: null });
    });
  }

  saw(s: Snapshot | null): Snapshot | null {
    for (const id of s?.assets_loaded ?? []) this.loaded.add(id);
    if (s?.audio && this.audio.length < 600) {
      this.audio.push({ ms: Date.now() - this.t0, state: s.state, music: s.audio.music, playing: s.audio.playing,
                        level: s.audio.level, muted: s.audio.muted ?? null });
    }
    return s;
  }

  // The UI of the screen state now: measured once per name, with its frame.
  async screen(name: string): Promise<void> {
    if (name in this.ui) return;
    // A screen's entrance (a fade, a stamp) is not what it shows: measured mid-fade, text is
    // drawn at a fraction of its colour and fails a contrast it meets a moment later.
    await settle(this.page);
    const snapshot = await snap(this.page);
    this.saw(snapshot);
    const measured = await measureUI(this.page);
    await frame(this.page, this.project, `state-${name}`, this.frames);
    this.ui[name] = { probe_state: snapshot?.state ?? null, frame: `state-${name}`, ...(measured as object),
                      probe_ui: (snapshot?.entities ?? []).filter((e) => e.role === "ui"),
                      entities: snapshot?.entities ?? [] };
  }

  record(): Record<string, unknown> {
    return { errors: this.errors, asset_requests: this.requests, runtime_assets: this.runtimeAssets,
             assets_loaded: [...this.loaded].sort(), ui: this.ui, audio: this.audio };
  }
}

// Wait - at most `maxMs` - for every finite CSS animation and transition running now to
// finish. Infinite ones (a pulse, a spinner) are the screen's steady state and are not waited
// for.
async function settle(page: Page, maxMs = 1500): Promise<void> {
  await page.evaluate(async (max) => {
    const running = document.getAnimations().filter((a) => {
      const end = a.effect?.getComputedTiming().endTime;
      return a.playState === "running" && typeof end === "number" && Number.isFinite(end);
    });
    await Promise.race([
      Promise.all(running.map((a) => a.finished.catch(() => undefined))),
      new Promise((resolve) => setTimeout(resolve, max)),
    ]);
  }, maxMs);
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

// The DOM UI on screen now, measured as the browser computed it: every visible interactive
// element (button, [role=button], a, input) and every visible text outside one, with its
// bounds, font size and weight, foreground colour and the opaque background behind it (the
// element's own and its ancestors' background colours composited; null when none is opaque or
// an ancestor paints an image, i.e. the canvas or a picture shows through and only the frame
// can tell), whether the element's computed style equals the user-agent default for its tag
// (read from an element of the same tag in a blank frame no page stylesheet reaches), and the
// overlaps between interactive elements and with the text.
async function measureUI(page: Page): Promise<unknown> {
  return page.evaluate(() => {
    type RGBA = [number, number, number, number];
    const parse = (value: string): RGBA | null => {
      const m = value.match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const p = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
      return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
    };
    const over = (top: RGBA, under: RGBA): RGBA => {
      const a = top[3] + under[3] * (1 - top[3]);
      if (!a) return [0, 0, 0, 0];
      const c = (i: number) => (top[i] * top[3] + under[i] * under[3] * (1 - top[3])) / a;
      return [c(0), c(1), c(2), a];
    };
    const background = (el: Element): number[] | null => {
      const layers: RGBA[] = [];
      for (let n: Element | null = el; n; n = n.parentElement) {
        const style = getComputedStyle(n);
        if (style.backgroundImage && style.backgroundImage !== "none") return null;
        const bg = parse(style.backgroundColor);
        if (bg && bg[3] > 0) {
          layers.push(bg);
          if (bg[3] >= 1) break;
        }
      }
      if (!layers.length || layers[layers.length - 1][3] < 1) return null;
      let out = layers[layers.length - 1];
      for (let i = layers.length - 2; i >= 0; i--) out = over(layers[i], out);
      return out.slice(0, 3).map((v) => Math.round(v));
    };
    const visible = (el: Element, r: DOMRect): boolean => {
      if (r.width <= 0 || r.height <= 0) return false;
      if (r.right <= 0 || r.bottom <= 0 || r.left >= innerWidth || r.top >= innerHeight) return false;
      const check = (el as Element & { checkVisibility?: (o: unknown) => boolean }).checkVisibility;
      if (check) return check.call(el, { opacityProperty: true, visibilityProperty: true });
      const s = getComputedStyle(el);
      return s.visibility !== "hidden" && s.display !== "none" && Number(s.opacity) > 0;
    };
    // The colour as drawn: its own alpha times the opacity of the element and its ancestors.
    const ink = (el: Element): RGBA | null => {
      const c = parse(getComputedStyle(el).color);
      if (!c) return null;
      let alpha = c[3];
      for (let n: Element | null = el; n; n = n.parentElement) alpha *= Number(getComputedStyle(n).opacity);
      return [c[0], c[1], c[2], Math.round(alpha * 1000) / 1000];
    };
    const box = (r: DOMRect) => [Math.round(r.left * 10) / 10, Math.round(r.top * 10) / 10,
                                 Math.round(r.width * 10) / 10, Math.round(r.height * 10) / 10];
    // The user-agent defaults: elements of the same tag in a blank frame.
    const blank = document.createElement("iframe");
    blank.style.cssText = "position:absolute;left:-9999px;top:0;width:200px;height:100px;border:0;visibility:hidden";
    document.body.appendChild(blank);
    const doc = blank.contentDocument as Document;
    doc.open();
    doc.write("<!doctype html><html><body></body></html>");
    doc.close();
    const PROPS = ["background-color", "background-image", "border-top-width", "border-top-style",
                   "border-top-color", "border-top-left-radius", "padding-top", "padding-left",
                   "font-family", "font-size", "font-weight", "color", "box-shadow", "text-decoration-line"];
    const uaDiffers = (el: Element): string[] => {
      const twin = doc.createElement(el.tagName.toLowerCase());
      if (el instanceof HTMLInputElement) (twin as HTMLInputElement).type = el.type;
      if (el.getAttribute("role")) twin.setAttribute("role", el.getAttribute("role") as string);
      if (el instanceof HTMLAnchorElement && el.hasAttribute("href")) twin.setAttribute("href", "#");
      twin.textContent = el.textContent;
      doc.body.appendChild(twin);
      const mine = getComputedStyle(el);
      const theirs = (doc.defaultView as Window).getComputedStyle(twin);
      const differs = PROPS.filter((p) => mine.getPropertyValue(p) !== theirs.getPropertyValue(p));
      twin.remove();
      return differs;
    };
    const SELECTOR = "button, [role=button], a, input";
    const interactive: Element[] = [];
    const elements = [] as Record<string, unknown>[];
    for (const el of Array.from(document.querySelectorAll(SELECTOR))) {
      const r = el.getBoundingClientRect();
      if (!visible(el, r)) continue;
      const s = getComputedStyle(el);
      const differs = uaDiffers(el);
      interactive.push(el);
      elements.push({
        tag: el.tagName.toLowerCase(), role: el.getAttribute("role"),
        text: ((el as HTMLElement).innerText || (el as HTMLInputElement).value || el.getAttribute("aria-label") || "").trim().slice(0, 60),
        box: box(r), font_px: parseFloat(s.fontSize), font_weight: Number(s.fontWeight) || 400,
        color: ink(el), background: background(el), ua_default: differs.length === 0,
        ua_differs: differs,
      });
    }
    // Text outside the interactive elements: the HUD, labels, result lines.
    const texts = [] as Record<string, unknown>[];
    const textNodes: Element[] = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const seen = new Set<Element>();
    for (let n = walker.nextNode(); n && texts.length < 80; n = walker.nextNode()) {
      const parent = n.parentElement;
      if (!parent || seen.has(parent) || !(n.textContent || "").trim()) continue;
      if (parent.closest(SELECTOR) || parent.closest("script, style, noscript, iframe")) continue;
      seen.add(parent);
      const range = document.createRange();
      range.selectNodeContents(parent);
      const r = range.getBoundingClientRect();
      if (!visible(parent, r)) continue;
      const s = getComputedStyle(parent);
      textNodes.push(parent);
      texts.push({ text: (parent.innerText || "").trim().slice(0, 60), box: box(r),
                   font_px: parseFloat(s.fontSize), font_weight: Number(s.fontWeight) || 400,
                   color: ink(parent), background: background(parent) });
    }
    blank.remove();
    const overlap = (a: number[], b: number[]): number => {
      const w = Math.min(a[0] + a[2], b[0] + b[2]) - Math.max(a[0], b[0]);
      const h = Math.min(a[1] + a[3], b[1] + b[3]) - Math.max(a[1], b[1]);
      return w > 0 && h > 0 ? Math.round(w * h) : 0;
    };
    const overlaps = [] as Record<string, unknown>[];
    for (let i = 0; i < interactive.length; i++) {
      for (let j = i + 1; j < interactive.length; j++) {
        if (interactive[i].contains(interactive[j]) || interactive[j].contains(interactive[i])) continue;
        const area = overlap(elements[i].box as number[], elements[j].box as number[]);
        if (area) overlaps.push({ kind: "interactive", a: i, b: j, area_px: area });
      }
      for (let j = 0; j < textNodes.length; j++) {
        if (interactive[i].contains(textNodes[j]) || textNodes[j].contains(interactive[i])) continue;
        const area = overlap(elements[i].box as number[], texts[j].box as number[]);
        if (area) overlaps.push({ kind: "text", a: i, text: j, area_px: area });
      }
    }
    return { viewport: [innerWidth, innerHeight], elements, texts, overlaps };
  });
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
// With `screens`, the title screen's UI is measured before it is pressed.
async function start(page: Page, touch: boolean, watch: Watch, screens = false): Promise<{ firstSnapshotMs: number | null; playingMs: number | null; samples: Snapshot[]; began: string | null }> {
  const t0 = Date.now();
  await page.goto(URL, { waitUntil: "domcontentloaded" });
  let firstSnapshotMs: number | null = null;
  let began: string | null = null;
  let pressedAt = 0;
  const samples: Snapshot[] = [];
  while (Date.now() - t0 < CFG.start_timeout_ms) {
    const s = watch.saw(await snap(page));
    if (s && firstSnapshotMs === null) firstSnapshotMs = Date.now() - t0;
    if (s && samples.length < 3) samples.push(s);
    if (s?.state === "playing") return { firstSnapshotMs, playingMs: Date.now() - t0, samples, began };
    if (screens && s?.state === "title") await watch.screen("title");
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

test("first session: objective, and no failure before the grace", async ({ page }, info) => {
  const project = info.project.name;
  const frames: string[] = [];
  const watch = new Watch(page, project, frames);
  const started = await start(page, Boolean(info.project.use.hasTouch), watch, true);
  const texts: string[] = [];
  const states: { ms: number; state: string }[] = [];
  let lostAtMs: number | null = null;
  if (started.playingMs !== null) {
    const t0 = Date.now();
    let shot = false;
    // No input at all, for the idle window: a first-time player still reading the screen.
    while (Date.now() - t0 < CFG.idle_ms) {
      const s = watch.saw(await snap(page));
      if (s && (states.length === 0 || states[states.length - 1].state !== s.state)) {
        states.push({ ms: Date.now() - t0, state: s.state });
      }
      if (s?.state === "lost" && lostAtMs === null) lostAtMs = Date.now() - t0;
      if (Date.now() - t0 < 3000) texts.push(await page.evaluate(() => document.body.innerText));
      if (!shot && Date.now() - t0 > 1000) {
        await frame(page, project, "first-session-1s", frames);
        if (s?.state === "playing") await watch.screen("playing");
        shot = true;
      }
      await page.waitForTimeout(200);
    }
    await frame(page, project, "first-session-idle-end", frames);
  }
  // The page loses focus (another window, the portal's chrome): the game must fall silent.
  // A window blur event is what the template's platform binding listens for.
  const unfocused: { ms: number; level: number | null; muted: boolean | null; playing: boolean | null }[] = [];
  if (started.playingMs !== null && (await snap(page))?.audio) {
    await page.evaluate(() => window.dispatchEvent(new Event("blur")));
    await page.waitForTimeout(700);
    for (let k = 0; k < 4; k++) {
      const s = await snap(page);
      unfocused.push({ ms: 700 + k * 150, level: s?.audio?.level ?? null, muted: s?.audio?.muted ?? null,
                       playing: s?.audio?.playing ?? null });
      await page.waitForTimeout(150);
    }
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  }
  write(project, "first-session", { ...started, texts: [...new Set(texts)], states, lostAtMs, ...watch.record(),
                                    audio_unfocused: unfocused, frames });
});

test("act: every action is acknowledged on screen", async ({ page }, info) => {
  const project = info.project.name;
  const frames: string[] = [];
  const watch = new Watch(page, project, frames);
  const touch = Boolean(info.project.use.hasTouch);
  const started = await start(page, touch, watch);
  const acted: unknown[] = [];
  if (started.playingMs !== null) {
    const s0 = watch.saw(await snap(page));
    // Every action is measured in play. A pause leaves play, so it goes last: measured
    // first, in the probe's own order, it left every later action tapping a paused game
    // (a goalkeeper's dive read as "no visible change" through two development rounds).
    // And each action is taken from the inputs live NOW, not from the first snapshot: a
    // zone, a lane, a piece moves between snapshots.
    const isPause = (move: Move): boolean => /pause/i.test(move.action);
    const isResume = (move: Move): boolean => /resume|continue|unpause|^play$/i.test(move.action);
    const order = [...(s0?.inputs ?? [])].sort((a, b) => Number(isPause(a)) - Number(isPause(b)));
    const seen = new Set<string>();
    for (const first of order) {
      if (seen.has(first.action) || seen.size >= 4) continue;
      seen.add(first.action);
      let before = watch.saw(await snap(page));
      if (before && before.state !== "playing") {
        // Brought back to play the way the game offers, when it does; else measured as is.
        const resume = before.inputs.find(isResume);
        if (resume) {
          await act(page, resume, touch);
          await page.waitForTimeout(300);
          before = watch.saw(await snap(page));
        }
      }
      const move = before?.inputs.find((m) => m.action === first.action) ?? first;
      const id = `act-${move.action}`;
      await frame(page, project, `${id}-before`, frames);
      await act(page, move, touch);
      await page.waitForTimeout(CFG.ack_ms);
      await frame(page, project, `${id}-after`, frames);
      acted.push({ action: move.action, input: move.input, before, after: watch.saw(await snap(page)) });
      await page.waitForTimeout(400);
    }
  }
  write(project, "act", { ...started, acted, ...watch.record(), frames });
});

test("win: the oracle plays well", async ({ page }, info) => {
  const project = info.project.name;
  const frames: string[] = [];
  const watch = new Watch(page, project, frames);
  const touch = Boolean(info.project.use.hasTouch);
  const started = await start(page, touch, watch);
  const series: { ms: number; value: number | null; state: string }[] = [];
  let reached: string | null = null;
  let inputs = 0;
  let sampled: unknown = null;
  if (started.playingMs !== null) {
    // Every frame for 10 s of play: which entities are drawn, where, and with what (the
    // runtime asset and how it is rendered). Long enough for a threat that spawns on the
    // horizon to reach the player, where it has to be read.
    const sampler = page.evaluate(async (ms: number) => {
      const out: [string, string, number, number, number, number, number, string | null, string | null][][] = [];
      const end = performance.now() + ms;
      while (performance.now() < end) {
        await new Promise((r) => requestAnimationFrame(r));
        const play = (window as unknown as { __wgf__?: { play?: { snapshot(): Snapshot } } }).__wgf__?.play;
        const s = play?.snapshot();
        if (s) out.push(s.entities.map((e) => [e.id, e.role, e.visible ? 1 : 0, e.x, e.y, e.w, e.h, e.asset ?? null, e.render ?? null]));
      }
      return { frames: out, viewport: [innerWidth, innerHeight] };
    }, 10000);
    const t0 = Date.now();
    let shot = false;
    while (Date.now() - t0 < CFG.win_ms) {
      const s = watch.saw(await snap(page));
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
    if (reached) {
      await frame(page, project, `end-${reached}`, frames);
      await watch.screen(reached);
    }
  }
  write(project, "win", { ...started, reached, inputs, series: series.filter((_, i) => i % 5 === 0 || i === series.length - 1), sampled, ...watch.record(), frames });
});

test("lose and restart: the anti-oracle plays badly, then retries", async ({ page }, info) => {
  const project = info.project.name;
  const frames: string[] = [];
  const watch = new Watch(page, project, frames);
  const touch = Boolean(info.project.use.hasTouch);
  const started = await start(page, touch, watch);
  let reached: string | null = null;
  let initial: Record<string, number> | null = null;
  let restart: unknown = null;
  if (started.playingMs !== null) {
    initial = watch.saw(await snap(page))?.metrics ?? null;
    const t0 = Date.now();
    // One success first, as a first-time player would: the grace ends at the first success.
    let succeeded = false;
    while (Date.now() - t0 < CFG.lose_ms) {
      const s = watch.saw(await snap(page));
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
      await watch.screen(reached);
      const at = watch.saw(await snap(page));
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
        after = watch.saw(await snap(page));
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
      // The screen after the retry, once play is back: measured after the restart's timing.
      if (playingMs !== null) {
        await page.waitForTimeout(500);
        await watch.screen("retry");
      }
    }
  }
  write(project, "lose", { ...started, initial, reached, restart, ...watch.record(), frames });
});

// The pause screen, when the game offers one: the probe's pause input, else a visible pause
// button, else Escape. Measured only if the probe then reports `paused`; then resumed the
// same way. A game with no pause is recorded as such, not failed here.
test("pause: the pause screen, if there is one", async ({ page }, info) => {
  const project = info.project.name;
  const frames: string[] = [];
  const watch = new Watch(page, project, frames);
  const touch = Boolean(info.project.use.hasTouch);
  const started = await start(page, touch, watch);
  let how: string | null = null;
  let paused = false;
  let resumed = false;
  if (started.playingMs !== null) {
    await page.waitForTimeout(500);
    const s = watch.saw(await snap(page));
    const move = s?.inputs.find((m) => /pause/i.test(m.action));
    const button = page.getByRole("button", { name: /pause/i }).first();
    how = move ? `input:${move.action}` : (await button.count()) ? "button" : "key:Escape";
    const press = async (): Promise<void> => {
      if (move) await act(page, move, touch);
      else if (how === "button") await button.click();
      else await page.keyboard.press("Escape");
    };
    await press();
    await page.waitForTimeout(300);
    paused = watch.saw(await snap(page))?.state === "paused";
    if (paused) {
      await watch.screen("paused");
      const after = watch.saw(await snap(page));
      const resume = after?.inputs.find((m) => /resume|continue|unpause|^play$/i.test(m.action));
      if (resume) await act(page, resume, touch);
      else await press();
      await page.waitForTimeout(300);
      resumed = watch.saw(await snap(page))?.state === "playing";
    }
  }
  write(project, "pause", { ...started, how, paused, resumed, ...watch.record(), frames });
});
