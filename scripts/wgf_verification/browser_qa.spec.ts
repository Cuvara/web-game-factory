// Browser QA: the built game in a real browser at every viewport a player brings.
//
// Copied by the Factory's verify step (scripts/wgf_verification/browser_qa.py) into the game
// checkout's git-ignored build/ directory and run there with the repository's own Playwright,
// against its production build (`pnpm preview`), behind the Factory's refusing network proxy.
// One Playwright project per viewport of core/reference/browser-qa.yaml.
//
// It judges nothing. Per viewport it records to <WGF_BQA_OUT>/<viewport>/<test>.json what
// happened: load and readiness timings, the menus it walked, the DOM UI measured on each
// screen, what the play probe (window.__wgf__.play.snapshot(), wgf-probe=1) reported, page
// errors, console errors, WebGL context loss, the context menu, the sounds the page started
// (Web Audio buffer sources, oscillators and media elements, hooked before the bundle runs and
// named by the URL they were fetched from), its frame times and JS heap, and the host's own
// health. The step's Python side holds every number to the bars and decides.
//
// It acts only through real pointer, touch and key input - never through the probe - except
// to hide the page: headless Chromium has no window to cover, so `document.hidden` and
// `visibilityState` are overridden and `visibilitychange` dispatched, which is what a game's
// own handler reads.
// Factory tooling: it contains no game, and is not part of one.

import { test, type Page, type TestInfo } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

interface Move {
  action: string;
  input: { type: "pointer"; x: number; y: number; hold_ms?: number } | { type: "key"; key: string; hold_ms?: number };
}
interface Entity { id: string; kind?: string; role: string; x: number; y: number; w: number; h: number; visible: boolean }
interface Snapshot {
  state: string;
  metrics: Record<string, number>;
  entities: Entity[];
  inputs: Move[];
  audio?: { music: string | null; playing: boolean; level: number; muted?: boolean };
  oracle?: Move | null;
}
interface Viewport { id: string; width: number; height: number; touch: boolean; kind: string }
interface Config {
  viewports: Viewport[];
  audio_viewport: string;
  perf_viewport: string;
  outcome_viewports: string[];
  start_timeout_ms: number;
  ready_max_ms: number;
  win_ms: number;
  lose_ms: number;
  restart_ms: number;
  has_win: boolean;
  frames: { sample_ms: number; long_frame_ms: number };
  memory: { session_ms: number };
  layout: { critical_roles: string[]; cover_samples: number; cover_interval_ms: number };
  states: { properties: string[] };
  environment?: { tick_ms: number; stall_ms: number; max_stall_ms: number; max_stalled_share: number;
                  max_server_wait_ms: number; max_attempts: number };
  retry_records?: string[];
}

const OUT = process.env.WGF_BQA_OUT as string;
const CFG = JSON.parse(fs.readFileSync(process.env.WGF_BQA_CONFIG as string, "utf8")) as Config;
const URL = "/?wgf-probe=1";

const BEGIN = /^(play|start|begin|tap-to-start|continue)$/i;
const UTILITY = /pause|resume|menu|settings|sound|mute|music|fullscreen|volume|audio/i;
const RETRY = /retry|restart|again|replay/i;
const UNDO = /retry|restart|again|replay|reset|undo|rewind/i;
const MUTE = /mute|sound|audio|music|volume/i;
const LOCAL = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?\//i;

function viewportOf(info: TestInfo): Viewport {
  const found = CFG.viewports.find((v) => v.id === info.project.name);
  if (!found) throw new Error(`no viewport ${info.project.name} in the browser-qa config`);
  return found;
}

function write(viewport: string, name: string, data: unknown): void {
  const dir = path.join(OUT, viewport);
  fs.mkdirSync(path.join(dir, "frames"), { recursive: true });
  fs.writeFileSync(path.join(dir, `${name}.json`), JSON.stringify(data, null, 1));
}

async function frame(page: Page, viewport: string, id: string, frames: string[]): Promise<void> {
  try {
    fs.mkdirSync(path.join(OUT, viewport, "frames"), { recursive: true });
    await page.screenshot({ path: path.join(OUT, viewport, "frames", `${id}.png`) });
    frames.push(id);
  } catch {
    // a frame that cannot be taken is simply not listed
  }
}

// -- instrumentation, installed before the bundle runs ---------------------------------------

function instrument(cfg: { tick: number; stall: number; health: boolean }): void {
  const w = window as unknown as Record<string, unknown>;
  if (w.__wgfQA) return;
  const qa: Record<string, unknown> = {
    sounds: [] as Record<string, unknown>[], contextLost: [] as number[], contextMenus: [] as Record<string, unknown>[],
    rejections: [] as string[], framesOn: false, frameDeltas: [] as number[],
  };
  w.__wgfQA = qa;
  const nodes: { loop: boolean }[] = [];
  qa.nodes = nodes;
  // What each audio buffer was fetched from: a fetched or XHR'd ArrayBuffer, then the
  // AudioBuffer decoded from it.
  const tags = new WeakMap<object, string>();
  try {
    const arrayBuffer = Response.prototype.arrayBuffer;
    Response.prototype.arrayBuffer = async function (this: Response) {
      const data = await arrayBuffer.call(this);
      try { tags.set(data, this.url); } catch { /* not taggable */ }
      return data;
    };
    // A game that decodes a copy (`bytes.slice(0)`, so the original can be decoded again)
    // keeps the copy's name.
    const slice = ArrayBuffer.prototype.slice;
    ArrayBuffer.prototype.slice = function (this: ArrayBuffer, ...args: unknown[]) {
      const copy = (slice as (...a: unknown[]) => ArrayBuffer).apply(this, args);
      const url = tags.get(this);
      if (url) tags.set(copy, url);
      return copy;
    } as typeof ArrayBuffer.prototype.slice;
    const open = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (this: XMLHttpRequest, ...args: unknown[]) {
      const url = String(args[1]);
      this.addEventListener("load", () => {
        try {
          if (this.response && typeof this.response === "object") tags.set(this.response, new globalThis.URL(url, location.href).href);
        } catch { /* not taggable */ }
      });
      return (open as (...a: unknown[]) => void).apply(this, args);
    } as typeof XMLHttpRequest.prototype.open;
    const proto = (globalThis.BaseAudioContext ?? globalThis.AudioContext)?.prototype as unknown as Record<string, unknown> | undefined;
    if (proto && typeof proto.decodeAudioData === "function") {
      const decode = proto.decodeAudioData as (...a: unknown[]) => Promise<AudioBuffer> | undefined;
      proto.decodeAudioData = function (this: BaseAudioContext, data: ArrayBuffer, ok?: (b: AudioBuffer) => void, err?: (e: unknown) => void) {
        const url = tags.get(data) ?? null;
        const done = (buffer: AudioBuffer) => { if (url && buffer) tags.set(buffer, url); };
        const result = decode.call(this, data, ok ? (b: AudioBuffer) => { done(b); ok(b); } : undefined, err);
        return result && typeof (result as Promise<AudioBuffer>).then === "function"
          ? (result as Promise<AudioBuffer>).then((b) => { done(b); return b; }) : result;
      };
    }
    const record = (entry: Record<string, unknown>, node: { loop: boolean } | null) => {
      const sounds = qa.sounds as Record<string, unknown>[];
      if (sounds.length >= 4000) return;
      sounds.push({ t: Math.round(performance.now()), ...entry });
      nodes.push(node ?? { loop: Boolean(entry.loop) });
    };
    if (globalThis.AudioBufferSourceNode) {
      const start = AudioBufferSourceNode.prototype.start;
      AudioBufferSourceNode.prototype.start = function (this: AudioBufferSourceNode, ...args: unknown[]) {
        const buffer = this.buffer;
        record({ kind: "buffer", url: buffer ? tags.get(buffer) ?? null : null, loop: this.loop,
                 duration: buffer ? Math.round(buffer.duration * 1000) / 1000 : null,
                 context: this.context.state }, this);
        return (start as (...a: unknown[]) => void).apply(this, args);
      } as typeof AudioBufferSourceNode.prototype.start;
    }
    if (globalThis.OscillatorNode) {
      const start = OscillatorNode.prototype.start;
      OscillatorNode.prototype.start = function (this: OscillatorNode, ...args: unknown[]) {
        record({ kind: "oscillator", url: null, loop: false, duration: null, context: this.context.state }, null);
        return (start as (...a: unknown[]) => void).apply(this, args);
      } as typeof OscillatorNode.prototype.start;
    }
    const play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function (this: HTMLMediaElement) {
      record({ kind: "media", url: this.currentSrc || this.src || null, loop: this.loop,
               duration: Number.isFinite(this.duration) ? Math.round(this.duration * 1000) / 1000 : null }, this);
      return play.call(this);
    };
  } catch (error) {
    qa.hookError = String(error).slice(0, 200);
  }
  // WebGL context loss on any canvas the game asks a context of.
  try {
    const getContext = HTMLCanvasElement.prototype.getContext;
    const watched = new WeakSet<HTMLCanvasElement>();
    // A context the page releases itself (WEBGL_lose_context.loseContext(): PixiJS probing
    // WebGL support, three.js forceContextLoss on dispose) is not a loss: only the others count.
    const released = new WeakSet<HTMLCanvasElement>();
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, ...args: unknown[]) {
      const canvas = this;
      if (!watched.has(canvas)) {
        watched.add(canvas);
        canvas.addEventListener("webglcontextlost", () => {
          if (!released.has(canvas)) (qa.contextLost as number[]).push(Math.round(performance.now()));
        });
      }
      const context = (getContext as (...a: unknown[]) => unknown).apply(canvas, args) as
        { getExtension?: (name: string) => unknown; __wgfQA?: boolean } | null;
      if (context && typeof context.getExtension === "function" && !context.__wgfQA) {
        context.__wgfQA = true;
        const getExtension = context.getExtension.bind(context);
        context.getExtension = (name: string) => {
          const ext = getExtension(name) as { loseContext?: () => void } | null;
          if (ext && name === "WEBGL_lose_context" && typeof ext.loseContext === "function") {
            const lose = ext.loseContext.bind(ext);
            ext.loseContext = () => {
              released.add(canvas);
              lose();
            };
          }
          return ext;
        };
      }
      return context;
    } as typeof HTMLCanvasElement.prototype.getContext;
  } catch { /* nothing to watch */ }
  // A context menu: read after every handler has run, so a handler added after this one counts.
  window.addEventListener("contextmenu", (event) => {
    const target = event.target as Element | null;
    setTimeout(() => (qa.contextMenus as Record<string, unknown>[]).push({
      t: Math.round(performance.now()), prevented: event.defaultPrevented,
      target: target ? target.tagName.toLowerCase() : null }), 0);
  });
  window.addEventListener("unhandledrejection", (event) => {
    (qa.rejections as string[]).push(String((event as PromiseRejectionEvent).reason).slice(0, 300));
  });
  // Frame times, when asked for (perf), and the page's own frame gaps for health.
  let last: number | null = null;
  const loop = (t: number): void => {
    if (last !== null && qa.framesOn) (qa.frameDeltas as number[]).push(Math.round((t - last) * 100) / 100);
    last = t;
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
  // Hiding the page, as a tab switch does: what the game's visibilitychange handler reads.
  qa.setHidden = (hidden: boolean) => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => (hidden ? "hidden" : "visible") });
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event(hidden ? "blur" : "focus"));
  };
  if (cfg.health) {
    try {
      const source = `const t0=performance.now();let last=t0,max=0,stalled=0,ticks=0;
setInterval(()=>{const now=performance.now();const lag=now-last-${cfg.tick};if(lag>max)max=lag;
if(lag>=${cfg.stall})stalled+=lag;ticks++;last=now},${cfg.tick});
onmessage=()=>postMessage({max_lag_ms:Math.round(max),stalled_ms:Math.round(stalled),ticks,
elapsed_ms:Math.round(performance.now()-t0)})`;
      qa.worker = new Worker(globalThis.URL.createObjectURL(new Blob([source], { type: "text/javascript" })));
    } catch (error) {
      qa.workerError = String(error).slice(0, 200);
    }
  }
}

// -- the host's health (core/reference/visual-quality.yaml `environment`) ---------------------

type Beat = { max_lag_ms: number; stalled_ms: number; ticks: number; elapsed_ms: number };

class Heartbeat {
  private last = performance.now();
  private readonly t0 = performance.now();
  private max = 0;
  private stalled = 0;
  private ticks = 0;
  private readonly timer: ReturnType<typeof setInterval>;

  constructor(private readonly tick: number, private readonly stall: number) {
    this.timer = setInterval(() => {
      const now = performance.now();
      const lag = now - this.last - this.tick;
      if (lag > this.max) this.max = lag;
      if (lag >= this.stall) this.stalled += lag;
      this.ticks += 1;
      this.last = now;
    }, tick);
  }

  stop(): Beat {
    clearInterval(this.timer);
    return { max_lag_ms: Math.round(this.max), stalled_ms: Math.round(this.stalled), ticks: this.ticks,
             elapsed_ms: Math.round(performance.now() - this.t0) };
  }
}

async function pageHealth(page: Page): Promise<Record<string, unknown> | null> {
  const read = page.evaluate(async () => {
    const qa = (window as unknown as { __wgfQA?: Record<string, unknown> }).__wgfQA;
    if (!qa) return null;
    const nav = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
    const waits = (performance.getEntriesByType("resource") as PerformanceResourceTiming[])
      .concat(nav ? [nav] : [])
      .filter((e) => e.responseStart > 0 && e.requestStart > 0)
      .map((e) => e.responseStart - e.requestStart);
    const worker = qa.worker as Worker | undefined;
    const beat = worker ? await new Promise((resolve) => {
      const timer = setTimeout(() => resolve(null), 2000);
      worker.onmessage = (event) => { clearTimeout(timer); resolve(event.data); };
      worker.postMessage(0);
    }) : null;
    return {
      nav: nav ? { ttfb_ms: Math.round(nav.responseStart - nav.startTime),
                   dom_content_loaded_ms: Math.round(nav.domContentLoadedEventEnd),
                   load_ms: Math.round(nav.loadEventEnd),
                   server_wait_max_ms: waits.length ? Math.round(Math.max(...waits)) : null,
                   requests: waits.length } : null,
      worker: beat, worker_error: qa.workerError ?? null,
    };
  });
  return Promise.race([read.catch(() => null), new Promise<null>((resolve) => setTimeout(() => resolve(null), 5000))]);
}

class Health {
  private readonly beat: Heartbeat | null;
  private readonly earlier: Record<string, unknown>[] = [];

  constructor() {
    const env = CFG.environment;
    this.beat = env ? new Heartbeat(env.tick_ms, env.stall_ms) : null;
  }

  async keep(page: Page): Promise<void> {
    const inPage = await pageHealth(page);
    if (inPage) this.earlier.push(inPage);
  }

  async read(page: Page): Promise<{ health: Record<string, unknown>; degraded: boolean; reasons: string[] }> {
    const inPage = await pageHealth(page);
    const bot = this.beat ? this.beat.stop() : null;
    const pages = [...this.earlier, ...(inPage ? [inPage] : [])];
    const beats = pages.map((p) => p.worker as Beat | null | undefined)
      .filter((b): b is Beat => Boolean(b) && typeof (b as Beat).max_lag_ms === "number");
    const sum = (key: keyof Beat): number => beats.reduce((total, b) => total + (b[key] ?? 0), 0);
    const worker: Beat | null = beats.length
      ? { max_lag_ms: Math.max(...beats.map((b) => b.max_lag_ms)), stalled_ms: sum("stalled_ms"),
          ticks: sum("ticks"), elapsed_ms: sum("elapsed_ms") }
      : null;
    const navs = pages.map((p) => p.nav as Record<string, unknown> | null | undefined)
      .filter((n): n is Record<string, unknown> => Boolean(n));
    const waits = navs.map((n) => n.server_wait_max_ms).filter((v): v is number => typeof v === "number");
    const last = navs.length ? navs[navs.length - 1] : null;
    const nav = last ? { ...last, server_wait_max_ms: waits.length ? Math.max(...waits) : null, pages: pages.length } : null;
    const health: Record<string, unknown> = { bot, worker, worker_error: inPage?.worker_error ?? null, nav };
    const env = CFG.environment;
    const reasons: string[] = [];
    if (env) {
      for (const [name, beat] of [["bot", bot], ["worker", worker]] as [string, Beat | null | undefined][]) {
        if (!beat) continue;
        if (beat.max_lag_ms >= env.max_stall_ms) reasons.push(`the ${name} timer stalled ${beat.max_lag_ms} ms at once`);
        if (beat.elapsed_ms > 0 && beat.stalled_ms / beat.elapsed_ms >= env.max_stalled_share) {
          reasons.push(`the ${name} timer lost ${beat.stalled_ms} ms of ${beat.elapsed_ms} ms to stalls`);
        }
      }
      const wait = nav?.server_wait_max_ms;
      if (typeof wait === "number" && wait >= env.max_server_wait_ms) {
        reasons.push(`the local server took ${wait} ms to start answering a request`);
      }
    }
    return { health, degraded: reasons.length > 0, reasons };
  }
}

function pending(viewport: string, name: string): string {
  return path.join(OUT, viewport, `.${name}.attempts.json`);
}

// A timing recording made on a degraded host is made again (a Playwright retry) while
// attempts remain; the record written is the last attempt's, with every attempt's health.
async function finish(page: Page, info: TestInfo, name: string, data: Record<string, unknown>,
                      health: Health): Promise<void> {
  const viewport = info.project.name;
  const now = await health.read(page);
  const marker = pending(viewport, name);
  const before = fs.existsSync(marker) ? JSON.parse(fs.readFileSync(marker, "utf8")) as unknown[] : [];
  const attempts = [...before, { attempt: before.length + 1, degraded: now.degraded, reasons: now.reasons, health: now.health }];
  write(viewport, name, { ...data, health: now.health, attempts });
  const allowed = CFG.environment?.max_attempts ?? 1;
  if (now.degraded && attempts.length < allowed && (CFG.retry_records ?? []).includes(name)) {
    fs.mkdirSync(path.dirname(marker), { recursive: true });
    fs.writeFileSync(marker, JSON.stringify(attempts));
    throw new Error(`the host was degraded while the ${name} recording was made (${now.reasons.join("; ")}); it is made again`);
  }
  if (fs.existsSync(marker)) fs.rmSync(marker);
}

const RECORD_OF: Record<string, string> = {
  "viewport: load, menus, layout, controls": "viewport",
  "performance: load, frames, memory": "perf",
};

test.beforeEach(async ({ page }, info) => {
  const name = RECORD_OF[info.title];
  const asked = name !== undefined && fs.existsSync(pending(info.project.name, name));
  test.skip(info.retry > 0 && !asked, "made again only when its host was degraded");
  // Nothing leaves the machine: a request for anything but the local build is refused at
  // once, as an ad blocker would (the Factory's proxy refuses it too, but slowly enough for a
  // portal SDK <script> in the page head to hold up loading - the environment's delay, not
  // the game's).
  await page.route((url) => !LOCAL.test(url.href), (route) => route.abort("blockedbyclient"));
  const env = CFG.environment;
  await page.addInitScript(instrument, { tick: env?.tick_ms ?? 50, stall: env?.stall_ms ?? 100, health: Boolean(env) });
});

// -- what one test saw beside play ----------------------------------------------------------

class Watch {
  pageErrors: string[] = [];
  console: { type: string; text: string; url: string | null }[] = [];
  failed: { url: string; status: number | null; error: string | null }[] = [];

  constructor(readonly page: Page) {
    page.on("pageerror", (e) => this.pageErrors.push(String(e.message || e).slice(0, 300)));
    page.on("console", (msg) => {
      if (msg.type() !== "error" && msg.type() !== "warning") return;
      if (this.console.length >= 200) return;
      const location = msg.location();
      this.console.push({ type: msg.type(), text: msg.text().slice(0, 300), url: location?.url || null });
    });
    page.on("requestfailed", (request) => {
      if (this.failed.length < 200) this.failed.push({ url: request.url(), status: null, error: request.failure()?.errorText ?? null });
    });
    page.on("response", (response) => {
      if (response.status() >= 400 && this.failed.length < 200) {
        this.failed.push({ url: response.url(), status: response.status(), error: null });
      }
    });
  }

  readonly runs: Record<string, unknown> = {};

  // What the page itself recorded - sounds, context losses, context menus, rejections - is
  // lost with the page: kept under `label` before every navigation away from it.
  async keep(label: string): Promise<void> {
    const inPage = await this.page.evaluate(() => {
      const qa = (window as unknown as { __wgfQA?: Record<string, unknown> }).__wgfQA;
      if (!qa) return null;
      const nodes = qa.nodes as { loop: boolean }[];
      const sounds = (qa.sounds as Record<string, unknown>[]).map((s, i) => ({ ...s, loop_now: Boolean(nodes[i]?.loop) }));
      return { sounds, context_lost: qa.contextLost, context_menus: qa.contextMenus, rejections: qa.rejections,
               hook_error: qa.hookError ?? null, origin: location.origin };
    }).catch(() => null);
    this.runs[label] = inPage ?? { instrumented: false };
  }

  async collect(label: string): Promise<Record<string, unknown>> {
    if (!(label in this.runs)) await this.keep(label);
    return { page_errors: this.pageErrors, console: this.console, failed_requests: this.failed, runs: this.runs };
  }
}

async function snap(page: Page): Promise<{ s: Snapshot | null; now: number }> {
  return page.evaluate(() => {
    const play = (window as unknown as { __wgf__?: { play?: { snapshot(): unknown } } }).__wgf__?.play;
    let s: Snapshot | null = null;
    try {
      s = play && typeof play.snapshot === "function" ? (play.snapshot() as Snapshot) : null;
    } catch (error) {
      s = { error: String(error) } as unknown as Snapshot;
    }
    return { s, now: Math.round(performance.now()) };
  }).catch(() => ({ s: null, now: -1 }));
}

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

interface Started {
  probe: boolean;
  first_snapshot_ms: number | null;
  ready_ms: number | null;
  interactive_ms: number | null;
  playing_ms: number | null;
  tti_ms: number | null;
  states: string[];
  began: string[];
  error?: string;
}

// The way into play the screen offers: its begin input, else the oracle's, else its first
// input that is not a utility (pause, sound, settings).
function beginOf(s: Snapshot): Move | null {
  const inputs = s.inputs ?? [];
  return inputs.find((m) => BEGIN.test(m.action)) ?? s.oracle ?? inputs.find((m) => !UTILITY.test(m.action)) ?? null;
}

// Opens the game as a first session and walks its menus into play, as a player would. Times
// are the page's own clock (performance.now(), from navigation start).
async function start(page: Page, touch: boolean, onTitle?: () => Promise<void>): Promise<Started> {
  const out: Started = { probe: false, first_snapshot_ms: null, ready_ms: null, interactive_ms: null, playing_ms: null,
                         tti_ms: null, states: [], began: [] };
  try {
    await page.goto(URL, { waitUntil: "domcontentloaded", timeout: CFG.start_timeout_ms });
  } catch (error) {
    out.error = `navigation: ${String(error).slice(0, 200)}`;
    return out;
  }
  const t0 = Date.now();
  let pressedAt = 0;
  let titleSeen = false;
  while (Date.now() - t0 < Math.max(CFG.start_timeout_ms, CFG.ready_max_ms)) {
    const { s, now } = await snap(page);
    if (s && !(s as unknown as { error?: string }).error) {
      out.probe = true;
      if (out.first_snapshot_ms === null) out.first_snapshot_ms = now;
      if (out.states[out.states.length - 1] !== s.state) out.states.push(s.state);
      if (s.state !== "loading" && out.ready_ms === null) out.ready_ms = now;
      if (s.state !== "loading" && out.interactive_ms === null && ((s.inputs ?? []).length > 0 || s.state === "playing")) {
        out.interactive_ms = now;
      }
      if (s.state === "playing") {
        out.playing_ms = now;
        break;
      }
      if (s.state === "title" && !titleSeen) {
        titleSeen = true;
        if (onTitle) await onTitle();
      }
      const begin = s.state !== "loading" ? beginOf(s) : null;
      if (begin && Date.now() - pressedAt > 1000) {
        await act(page, begin, touch);
        out.began.push(begin.action);
        pressedAt = Date.now();
      }
    }
    await page.waitForTimeout(50);
  }
  out.tti_ms = await page.evaluate(() => {
    const value = (window as unknown as { __wgf__?: { timeToInteractiveMs?: number } }).__wgf__?.timeToInteractiveMs;
    return typeof value === "number" ? Math.round(value) : null;
  }).catch(() => null);
  return out;
}

// -- layout ---------------------------------------------------------------------------------

// The DOM UI on screen now: the page's scroll extent, every visible control and text with its
// box, the canvases, and disabled controls. Overlap, clipping and margins are computed by the
// step from these boxes.
async function measureLayout(page: Page, state: string): Promise<Record<string, unknown>> {
  const measured = await page.evaluate(() => {
    const visible = (el: Element, r: DOMRect): boolean => {
      if (r.width <= 0 || r.height <= 0) return false;
      if (r.right <= 0 || r.bottom <= 0 || r.left >= innerWidth || r.top >= innerHeight) return false;
      const check = (el as Element & { checkVisibility?: (o: unknown) => boolean }).checkVisibility;
      if (check) return check.call(el, { opacityProperty: true, visibilityProperty: true });
      const s = getComputedStyle(el);
      return s.visibility !== "hidden" && s.display !== "none" && Number(s.opacity) > 0;
    };
    const box = (r: DOMRect) => [Math.round(r.left * 10) / 10, Math.round(r.top * 10) / 10,
                                 Math.round(r.width * 10) / 10, Math.round(r.height * 10) / 10];
    const SELECTOR = "button, [role=button], a[href], input, select";
    const controls: Record<string, unknown>[] = [];
    const elements: Element[] = [];
    for (const el of Array.from(document.querySelectorAll(SELECTOR))) {
      const r = el.getBoundingClientRect();
      if (!visible(el, r)) continue;
      if (elements.some((e) => e.contains(el))) continue;
      elements.push(el);
      controls.push({ tag: el.tagName.toLowerCase(),
                      text: ((el as HTMLElement).innerText || el.getAttribute("aria-label") || "").trim().slice(0, 40),
                      box: box(r),
                      disabled: (el as HTMLButtonElement).disabled === true || el.getAttribute("aria-disabled") === "true" });
    }
    const texts: Record<string, unknown>[] = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const seen = new Set<Element>();
    for (let n = walker.nextNode(); n && texts.length < 80; n = walker.nextNode()) {
      const parent = n.parentElement;
      if (!parent || seen.has(parent) || !(n.textContent || "").trim()) continue;
      if (parent.closest(SELECTOR) || parent.closest("script, style, noscript, iframe")) continue;
      seen.add(parent);
      const range = document.createRange();
      range.selectNodeContents(n);
      const r = range.getBoundingClientRect();
      if (!visible(parent, r)) continue;
      texts.push({ text: (n.textContent || "").trim().slice(0, 40), box: box(r) });
    }
    const canvases = Array.from(document.querySelectorAll("canvas"))
      .map((c) => ({ el: c, r: c.getBoundingClientRect() }))
      .filter(({ el, r }) => visible(el, r))
      .map(({ r }) => {
        const w = Math.max(0, Math.min(innerWidth, r.right) - Math.max(0, r.left));
        const h = Math.max(0, Math.min(innerHeight, r.bottom) - Math.max(0, r.top));
        return { box: box(r), share: Math.round((w * h) / (innerWidth * innerHeight) * 1000) / 1000 };
      });
    const root = document.scrollingElement || document.documentElement;
    return { viewport: [innerWidth, innerHeight], scroll: [root.scrollWidth, root.scrollHeight],
             body_scroll: [document.body.scrollWidth, document.body.scrollHeight], controls, texts, canvases };
  }).catch((error) => ({ error: String(error).slice(0, 200) }));
  return { state, ...measured };
}

// How much of each gameplay-critical entity painted DOM UI covers now: a grid of points over
// its box, each covered when it lies inside an element that paints there (an opaque-enough
// fill, an image, an image fill, or the glyphs of a text) and is not the canvas or a parent
// of it. pointer-events play no part: a HUD that lets clicks through still hides what is under it.
async function coverNow(page: Page, roles: string[]): Promise<Record<string, unknown>[]> {
  return page.evaluate((roles: string[]) => {
    const play = (window as unknown as { __wgf__?: { play?: { snapshot(): Snapshot } } }).__wgf__?.play;
    const s = play?.snapshot();
    if (!s) return [];
    const parse = (value: string): number => {
      const m = value.match(/rgba?\(([^)]+)\)/);
      if (!m) return 0;
      const p = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
      return p.length > 3 ? p[3] : 1;
    };
    const canvases = Array.from(document.querySelectorAll("canvas"));
    const painters: { r: DOMRect; label: string }[] = [];
    for (const el of Array.from(document.body.querySelectorAll("*"))) {
      if (canvases.some((c) => c === el || el.contains(c))) continue;
      const tag = el.tagName.toLowerCase();
      if (tag === "script" || tag === "style") continue;
      const st = getComputedStyle(el);
      if (st.display === "none" || st.visibility === "hidden" || Number(st.opacity) <= 0.05) continue;
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      const label = `${tag}${el.id ? "#" + el.id : ""}${typeof el.className === "string" && el.className ? "." + el.className.split(/\s+/)[0] : ""}`;
      const image = st.backgroundImage !== "none" || ["img", "svg", "video", "picture"].includes(tag);
      if (image || parse(st.backgroundColor) >= 0.5) painters.push({ r, label });
      for (const c of Array.from(el.childNodes)) {
        if (c.nodeType !== Node.TEXT_NODE || !(c.textContent || "").trim()) continue;
        const range = document.createRange();
        range.selectNodeContents(c);
        for (const q of Array.from(range.getClientRects())) painters.push({ r: q, label: `text:${(c.textContent || "").trim().slice(0, 20)}` });
      }
    }
    const out: Record<string, unknown>[] = [];
    for (const e of s.entities ?? []) {
      if (!e.visible || !roles.includes(e.role) || e.w <= 0 || e.h <= 0) continue;
      let covered = 0, total = 0;
      const by = new Map<string, number>();
      for (let i = 0; i < 5; i++) {
        for (let j = 0; j < 5; j++) {
          const x = e.x + (e.w * (i + 0.5)) / 5, y = e.y + (e.h * (j + 0.5)) / 5;
          if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue;
          total += 1;
          const hit = painters.find((p) => x >= p.r.left && x <= p.r.right && y >= p.r.top && y <= p.r.bottom);
          if (hit) {
            covered += 1;
            by.set(hit.label, (by.get(hit.label) ?? 0) + 1);
          }
        }
      }
      if (!total) continue;
      const top = [...by.entries()].sort((a, b) => b[1] - a[1])[0];
      out.push({ id: e.id, role: e.role, kind: e.kind ?? null, box: [e.x, e.y, e.w, e.h],
                 share: Math.round((covered / total) * 100) / 100, by: top ? top[0] : null });
    }
    return out;
  }, roles).catch(() => []);
}

// Hover, pressed and disabled looks of the controls on screen, read as computed styles.
async function controlStates(page: Page, touch: boolean): Promise<Record<string, unknown>> {
  const props = CFG.states.properties;
  const styleOf = (index: number) => page.evaluate(({ index, props }) => {
    const all = Array.from(document.querySelectorAll("button, [role=button]")).filter((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && r.right > 0 && r.bottom > 0 && r.left < innerWidth && r.top < innerHeight;
    });
    const el = all[index];
    if (!el) return null;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return { center: [r.left + r.width / 2, r.top + r.height / 2],
             text: ((el as HTMLElement).innerText || el.getAttribute("aria-label") || "").trim().slice(0, 40),
             disabled: (el as HTMLButtonElement).disabled === true || el.getAttribute("aria-disabled") === "true",
             style: Object.fromEntries(props.map((p: string) => [p, s.getPropertyValue(p)])) };
  }, { index, props });
  const count = await page.evaluate(() => Array.from(document.querySelectorAll("button, [role=button]")).filter((el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.right > 0 && r.bottom > 0 && r.left < innerWidth && r.top < innerHeight;
  }).length).catch(() => 0);
  const controls: Record<string, unknown>[] = [];
  for (let i = 0; i < Math.min(count, 6); i++) {
    const rest = await styleOf(i);
    if (!rest) continue;
    const entry: Record<string, unknown> = { text: rest.text, disabled: rest.disabled, rest: rest.style };
    if (!touch && !rest.disabled) {
      await page.mouse.move(rest.center[0], rest.center[1]);
      await page.waitForTimeout(250);
      entry.hover = (await styleOf(i))?.style ?? null;
      await page.mouse.down();
      await page.waitForTimeout(150);
      entry.pressed = (await styleOf(i))?.style ?? null;
      // Released away from the control: a press that is never a click.
      await page.mouse.move(1, 1);
      await page.mouse.up();
      await page.waitForTimeout(250);
    }
    controls.push(entry);
  }
  return { controls };
}

async function contextMenuProbe(page: Page, touch: boolean): Promise<Record<string, unknown>> {
  const target = await page.evaluate(() => {
    const canvases = Array.from(document.querySelectorAll("canvas")).map((c) => c.getBoundingClientRect())
      .filter((r) => r.width > 0 && r.height > 0).sort((a, b) => b.width * b.height - a.width * a.height);
    const r = canvases[0];
    const style = r ? getComputedStyle(document.querySelector("canvas") as Element) : null;
    return r ? { x: r.left + r.width / 2, y: r.top + r.height / 2,
                 callout: style?.getPropertyValue("-webkit-touch-callout") ?? null,
                 user_select: style?.getPropertyValue("user-select") ?? null } : null;
  }).catch(() => null);
  if (!target) return { probed: false, reason: "no canvas to probe" };
  const before = await page.evaluate(() => ((window as unknown as { __wgfQA?: { contextMenus: unknown[] } }).__wgfQA?.contextMenus.length ?? 0));
  if (touch) {
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: target.x, y: target.y }] });
    await page.waitForTimeout(1200);
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await cdp.detach();
  } else {
    await page.mouse.click(target.x, target.y, { button: "right" });
  }
  await page.waitForTimeout(200);
  const read = () => page.evaluate((from: number) =>
    ((window as unknown as { __wgfQA?: { contextMenus: unknown[] } }).__wgfQA?.contextMenus ?? []).slice(from), before);
  let events = await read();
  let how = touch ? "long-press" : "right-click";
  if (touch && !events.length) {
    // An emulated long press need not raise contextmenu, where a device's does: the event a
    // device would raise is dispatched on the game instead, and whether the game prevents
    // it is what is read.
    await page.evaluate(({ x, y }) => {
      const at = document.elementFromPoint(x, y) ?? document.body;
      at.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: x, clientY: y }));
    }, { x: target.x, y: target.y });
    await page.waitForTimeout(100);
    events = await read();
    how = "long-press (contextmenu dispatched: the emulated press raised none)";
  }
  return { probed: true, how, at: [target.x, target.y], events,
           callout: target.callout, user_select: target.user_select };
}

// -- play -----------------------------------------------------------------------------------

interface Played {
  inputs: { t: number; action: string }[];
  transitions: { t: number; state: string }[];
}

// The oracle plays (well) until a state in `until` or the window ends; with `bad`, it plays
// badly instead: any input but the oracle's, never a utility or an undo, else nothing.
async function play(page: Page, touch: boolean, windowMs: number, until: string[], bad: boolean, log: Played,
                    onSnapshot?: (s: Snapshot) => Promise<void>): Promise<string | null> {
  const t0 = Date.now();
  let lastState: string | null = null;
  let turn = 0;
  while (Date.now() - t0 < windowMs) {
    const { s, now } = await snap(page);
    if (!s || (s as unknown as { error?: string }).error) break;
    if (s.state !== lastState) {
      log.transitions.push({ t: now, state: s.state });
      lastState = s.state;
    }
    if (until.includes(s.state)) return s.state;
    if (onSnapshot) await onSnapshot(s);
    let move: Move | null = null;
    if (s.state !== "playing") {
      move = beginOf(s);
    } else if (!bad) {
      move = s.oracle ?? null;
    } else {
      const choices = (s.inputs ?? []).filter((m) => !UTILITY.test(m.action) && !UNDO.test(m.action)
        && !(s.oracle && m.action === s.oracle.action && JSON.stringify(m.input) === JSON.stringify(s.oracle.input)));
      move = choices.length ? choices[turn % choices.length] : null;
      turn += 1;
    }
    if (move) {
      const at = await page.evaluate(() => Math.round(performance.now())).catch(() => -1);
      await act(page, move, touch);
      log.inputs.push({ t: at, action: move.action });
      await page.waitForTimeout(bad ? 250 : 120);
    } else {
      await page.waitForTimeout(40);
    }
  }
  return null;
}

async function retryFrom(page: Page, touch: boolean, log: Played): Promise<string | null> {
  const { s } = await snap(page);
  const move = s?.inputs?.find((m) => RETRY.test(m.action)) ?? s?.oracle ?? s?.inputs?.find((m) => !UTILITY.test(m.action));
  if (move) {
    const at = await page.evaluate(() => Math.round(performance.now())).catch(() => -1);
    await act(page, move, touch);
    log.inputs.push({ t: at, action: move.action });
    return `input:${move.action}`;
  }
  const button = page.getByRole("button", { name: /retry|restart|play again|try again|replay/i }).first();
  if (await button.count()) {
    await button.click();
    return "button";
  }
  return null;
}

async function audioNow(page: Page): Promise<Snapshot["audio"] | null> {
  const { s } = await snap(page);
  return s?.audio ?? null;
}

// The pause control the game offers: its probe input, else a visible pause button, else Escape.
async function pauseResume(page: Page, touch: boolean, log: Played): Promise<Record<string, unknown>> {
  const { s } = await snap(page);
  if (s?.state !== "playing") return { tried: false, reason: `not playing (${s?.state ?? "no probe"})` };
  const move = s.inputs?.find((m) => /pause/i.test(m.action));
  const button = page.getByRole("button", { name: /pause/i }).first();
  const how = move ? `input:${move.action}` : (await button.count()) ? "button" : "key:Escape";
  const press = async (): Promise<void> => {
    const at = await page.evaluate(() => Math.round(performance.now())).catch(() => -1);
    if (move) {
      await act(page, move, touch);
      log.inputs.push({ t: at, action: move.action });
    } else if (how === "button") await button.click();
    else await page.keyboard.press("Escape");
  };
  await press();
  const paused = await until(page, ["paused"], 2000);
  let resumedBy: string | null = null;
  let layout: Record<string, unknown> | null = null;
  if (paused) {
    await page.waitForTimeout(300);
    layout = await measureLayout(page, "paused");
    resumedBy = await resume(page, touch, press);
  }
  return { tried: true, how, declared: Boolean(move), paused, resumed: resumedBy !== null,
           resumed_by: resumedBy, layout };
}

// Polls the probe until its state is one of `states`, for at most `ms`.
async function until(page: Page, states: string[], ms: number): Promise<boolean> {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const { s } = await snap(page);
    if (s && states.includes(s.state)) return true;
    await page.waitForTimeout(100);
  }
  return false;
}

// Back from a pause screen into play, as a player would: the screen's resume input, else the
// way the oracle names out of it, else its first input that is not a utility, else the pause
// control again. Tried twice, a card's entrance being allowed to finish in between.
async function resume(page: Page, touch: boolean, again?: () => Promise<void>): Promise<string | null> {
  for (let attempt = 0; attempt < 2; attempt++) {
    const { s } = await snap(page);
    if (s?.state === "playing") return "itself";
    const inputs = s?.inputs ?? [];
    const move = inputs.find((m) => /resume|continue|unpause|^play$/i.test(m.action)) ?? s?.oracle
      ?? inputs.find((m) => !UTILITY.test(m.action));
    let how: string;
    if (move) {
      await act(page, move, touch);
      how = `input:${move.action}`;
    } else if (again) {
      await again();
      how = "pause control";
    } else {
      await page.keyboard.press("Escape");
      how = "key:Escape";
    }
    if (await until(page, ["playing"], 2000)) return how;
  }
  return null;
}

function signature(s: Snapshot | null): string {
  if (!s) return "";
  const entities = (s.entities ?? []).map((e) => `${e.id}:${Math.round(e.x)}:${Math.round(e.y)}`).sort().join("|");
  return `${s.state}#${JSON.stringify(s.metrics ?? {})}#${entities}`;
}

// Back into play after the probes before this one left the game out of it, as a player would:
// a game the context-menu and pause probes left unsteered may have ended (a dodge game is lost
// within seconds) or still be paused. Retry from an end, resume a pause, begin from the title;
// null when it was already playing, else how it got back (or "failed: <state>").
async function backToPlay(page: Page, touch: boolean): Promise<string | null> {
  const log: Played = { inputs: [], transitions: [] };
  for (let attempt = 0; attempt < 3; attempt++) {
    const { s } = await snap(page);
    if (s?.state === "playing") return attempt === 0 ? null : `re-entered (${attempt})`;
    if (s?.state === "paused") await resume(page, touch);
    else if (s?.state === "lost" || s?.state === "won") await retryFrom(page, touch, log);
    else if (s) {
      const move = beginOf(s);
      if (move) await act(page, move, touch);
    }
    await until(page, ["playing"], 3000);
  }
  const { s } = await snap(page);
  return s?.state === "playing" ? "re-entered (3)" : `failed: ${s?.state ?? "no probe"}`;
}

// The page hidden for two seconds while playing: does play hold, is it silent, does it resume.
async function hiddenProbe(page: Page, touch: boolean): Promise<Record<string, unknown>> {
  const reentered = await backToPlay(page, touch);
  const before = (await snap(page)).s;
  if (before?.state !== "playing") {
    return { tried: false, reason: `not playing (${before?.state ?? "no probe"})`, reentered };
  }
  const audioBefore = before.audio ?? null;
  await page.evaluate(() => ((window as unknown as { __wgfQA: { setHidden(h: boolean): void } }).__wgfQA.setHidden(true)));
  await page.waitForTimeout(700);
  const a = (await snap(page)).s;
  await page.waitForTimeout(1300);
  const b = (await snap(page)).s;
  await page.evaluate(() => ((window as unknown as { __wgfQA: { setHidden(h: boolean): void } }).__wgfQA.setHidden(false)));
  await page.waitForTimeout(600);
  const shown = (await snap(page)).s;
  const resumedBy = shown?.state === "playing" ? "itself" : await resume(page, touch);
  const after = (await snap(page)).s;
  return { tried: true, state_hidden: [a?.state ?? null, b?.state ?? null], still: signature(a) === signature(b),
           audio_before: audioBefore, audio_hidden: b?.audio ?? null, state_after: after?.state ?? null, resumed_by: resumedBy,
           reentered };
}

// The game's mute control: its probe input, else a visible control named for sound.
async function muteProbe(page: Page, touch: boolean): Promise<Record<string, unknown>> {
  const { s } = await snap(page);
  if (!s?.audio) return { tried: false, reason: "the play probe reports no audio" };
  const move = s.inputs?.find((m) => MUTE.test(m.action) && !/pause/i.test(m.action));
  const button = page.getByRole("button", { name: MUTE }).first();
  const how = move ? `input:${move.action}` : (await button.count()) ? "button" : null;
  if (how) {
    const press = async (): Promise<void> => {
      if (move) await act(page, move, touch);
      else await button.click();
    };
    await page.waitForTimeout(300);
    const before = await audioNow(page);
    await press();
    await page.waitForTimeout(500);
    const muted = await audioNow(page);
    await press();
    await page.waitForTimeout(700);
    const unmuted = await audioNow(page);
    return { tried: true, how, before, muted, unmuted };
  }
  // No control on the play screen: the pause screen's, as most games put it there. Play is
  // silent while paused, so the level is read back in play after each press.
  const pauseMove = s.inputs?.find((m) => /pause/i.test(m.action));
  const pauseKey = async (): Promise<void> => {
    if (pauseMove) await act(page, pauseMove, touch);
    else await page.keyboard.press("Escape");
  };
  const toggleInPause = async (): Promise<string | null> => {
    await pauseKey();
    if (!(await until(page, ["paused"], 2000))) return null;
    await page.waitForTimeout(400);
    const paused = (await snap(page)).s;
    const inPause = paused?.inputs?.find((m) => MUTE.test(m.action) && !/pause/i.test(m.action));
    const control = page.getByRole("button", { name: MUTE }).first();
    let found: string | null = null;
    if (inPause) {
      await act(page, inPause, touch);
      found = `pause screen input:${inPause.action}`;
    } else if (await control.count()) {
      await control.click();
      found = "pause screen button";
    }
    await page.waitForTimeout(300);
    await resume(page, touch, pauseKey);
    return found;
  };
  await page.waitForTimeout(300);
  const before = await audioNow(page);
  const found = await toggleInPause();
  if (!found) {
    return { tried: false, reason: "no mute control on the play screen or the pause screen (probe inputs or a button named for sound)" };
  }
  await page.waitForTimeout(700);
  const muted = await audioNow(page);
  await toggleInPause();
  await page.waitForTimeout(900);
  const unmuted = await audioNow(page);
  return { tried: true, how: found, before, muted, unmuted };
}

// -- the tests --------------------------------------------------------------------------------

test("viewport: load, menus, layout, controls", async ({ page }, info) => {
  const viewport = viewportOf(info);
  const health = new Health();
  const watch = new Watch(page);
  const frames: string[] = [];
  const layouts: Record<string, unknown>[] = [];
  const log: Played = { inputs: [], transitions: [] };
  const record: Record<string, unknown> = { viewport };
  try {
    const started = await start(page, viewport.touch, async () => {
      layouts.push(await measureLayout(page, "title"));
      await frame(page, viewport.id, "title", frames);
    });
    record.started = started;
    if (started.playing_ms !== null) {
      await page.waitForTimeout(800);
      layouts.push(await measureLayout(page, "playing"));
      await frame(page, viewport.id, "playing", frames);
      const cover: Record<string, unknown>[][] = [];
      for (let i = 0; i < CFG.layout.cover_samples; i++) {
        // The oracle keeps play going while entities are sampled.
        const { s } = await snap(page);
        if (s?.state === "playing" && s.oracle) await act(page, s.oracle, viewport.touch);
        cover.push(await coverNow(page, CFG.layout.critical_roles));
        await page.waitForTimeout(CFG.layout.cover_interval_ms);
      }
      record.cover = cover;
      record.context_menu = await contextMenuProbe(page, viewport.touch);
      record.pause = await pauseResume(page, viewport.touch, log);
      record.hidden = await hiddenProbe(page, viewport.touch);
      if (viewport.id === CFG.audio_viewport) record.mute = await muteProbe(page, viewport.touch);
    }
    record.layouts = layouts;
    record.played = log;
    await watch.keep("main");
    // Control states on a fresh title screen: a press is never released on the control.
    const states: Record<string, unknown> = { measured: false };
    try {
      await page.goto(URL, { waitUntil: "domcontentloaded" });
      const t0 = Date.now();
      while (Date.now() - t0 < CFG.start_timeout_ms) {
        const { s } = await snap(page);
        if (s && s.state !== "loading") break;
        await page.waitForTimeout(100);
      }
      await page.waitForTimeout(500);
      Object.assign(states, await controlStates(page, viewport.touch), { measured: true });
    } catch (error) {
      states.error = String(error).slice(0, 200);
    }
    record.control_states = states;
  } catch (error) {
    record.error = String(error).slice(0, 300);
    record.layouts = layouts;
    record.played = log;
  }
  record.watch = await watch.collect("main");
  record.frames = frames;
  await finish(page, info, "viewport", record, health);
});

test("outcomes: win, lose, restart", async ({ page }, info) => {
  const viewport = viewportOf(info);
  test.skip(!CFG.outcome_viewports.includes(viewport.id), "end states are not played on this viewport");
  const health = new Health();
  const watch = new Watch(page);
  const frames: string[] = [];
  const record: Record<string, unknown> = { viewport };
  const win: Played = { inputs: [], transitions: [] };
  const lose: Played = { inputs: [], transitions: [] };
  const layouts: Record<string, unknown>[] = [];
  try {
    if (CFG.has_win) {
      const started = await start(page, viewport.touch);
      record.win_started = started;
      if (started.playing_ms !== null) {
        const reached = await play(page, viewport.touch, CFG.win_ms, ["won", "lost"], false, win);
        record.win = { reached, window_ms: CFG.win_ms };
        if (reached) {
          await page.waitForTimeout(600);
          layouts.push(await measureLayout(page, reached));
          await frame(page, viewport.id, `end-${reached}-win-run`, frames);
        }
      }
    }
    if (CFG.has_win) await watch.keep("win");
    const started = await start(page, viewport.touch);
    record.lose_started = started;
    if (started.playing_ms !== null) {
      const reached = await play(page, viewport.touch, CFG.lose_ms, ["lost", "won"], true, lose);
      record.lose = { reached, window_ms: CFG.lose_ms };
      if (reached === "lost") {
        await page.waitForTimeout(600);
        layouts.push(await measureLayout(page, "lost"));
        await frame(page, viewport.id, "end-lost", frames);
        const how = await retryFrom(page, viewport.touch, lose);
        const t0 = Date.now();
        let back: string | null = null;
        while (how && Date.now() - t0 < CFG.restart_ms) {
          const { s, now } = await snap(page);
          if (s?.state && lose.transitions[lose.transitions.length - 1]?.state !== s.state) lose.transitions.push({ t: now, state: s.state });
          if (s?.state === "playing") {
            back = "playing";
            break;
          }
          // A retry that lands on a title or a level map is walked back into play.
          if (s && s.state !== "lost" && s.state !== "loading") {
            const begin = beginOf(s);
            if (begin) await act(page, begin, viewport.touch);
          }
          await page.waitForTimeout(200);
        }
        record.restart = { how, reached: back, window_ms: CFG.restart_ms, took_ms: back ? Date.now() - t0 : null };
      }
    }
  } catch (error) {
    record.error = String(error).slice(0, 300);
  }
  record.played = { win, lose };
  record.layouts = layouts;
  record.watch = await watch.collect("lose");
  record.frames = frames;
  const host = await health.read(page);
  write(viewport.id, "outcomes", { ...record, health: host.health,
                                   attempts: [{ attempt: 1, degraded: host.degraded, reasons: host.reasons, health: host.health }] });
});

test("performance: load, frames, memory", async ({ page }, info) => {
  const viewport = viewportOf(info);
  test.skip(viewport.id !== CFG.perf_viewport, "performance is measured on one viewport");
  const health = new Health();
  const watch = new Watch(page);
  const record: Record<string, unknown> = { viewport };
  const log: Played = { inputs: [], transitions: [] };
  try {
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Performance.enable");
    const heap = async (): Promise<number | null> => {
      try {
        await cdp.send("HeapProfiler.collectGarbage");
        const { metrics } = await cdp.send("Performance.getMetrics") as { metrics: { name: string; value: number }[] };
        const used = metrics.find((m) => m.name === "JSHeapUsedSize");
        return used ? Math.round((used.value / 1048576) * 100) / 100 : null;
      } catch {
        return null;
      }
    };
    const started = await start(page, viewport.touch);
    record.started = started;
    record.renderer = await page.evaluate(() => {
      try {
        const gl = document.createElement("canvas").getContext("webgl");
        const ext = gl?.getExtension("WEBGL_debug_renderer_info");
        return gl && ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)) : null;
      } catch {
        return null;
      }
    });
    if (started.playing_ms !== null) {
      await page.waitForTimeout(1000);
      const heapStart = await heap();
      await page.evaluate(() => { const qa = (window as unknown as { __wgfQA: Record<string, unknown> }).__wgfQA; qa.frameDeltas = []; qa.framesOn = true; });
      const keepPlaying = async (ms: number): Promise<void> => {
        const t0 = Date.now();
        while (Date.now() - t0 < ms) {
          const reached = await play(page, viewport.touch, ms - (Date.now() - t0), ["won", "lost"], false, log);
          if (!reached) break;
          await page.waitForTimeout(400);
          await retryFrom(page, viewport.touch, log);
          await page.waitForTimeout(600);
        }
      };
      await keepPlaying(CFG.frames.sample_ms);
      const deltas = await page.evaluate(() => { const qa = (window as unknown as { __wgfQA: Record<string, unknown> }).__wgfQA; qa.framesOn = false; return qa.frameDeltas as number[]; });
      record.frames = { sample_ms: CFG.frames.sample_ms, deltas };
      // The rest of the session: play, end, restart, as long sessions do.
      const series: { ms: number; mb: number | null }[] = [{ ms: 0, mb: heapStart }];
      const t0 = Date.now();
      while (Date.now() - t0 < CFG.memory.session_ms) {
        await keepPlaying(Math.min(15000, CFG.memory.session_ms - (Date.now() - t0)));
        series.push({ ms: Date.now() - t0, mb: await heap() });
      }
      record.memory = { session_ms: CFG.memory.session_ms, series };
    }
  } catch (error) {
    record.error = String(error).slice(0, 300);
  }
  record.played = log;
  record.watch = await watch.collect("perf");
  await finish(page, info, "perf", record, health);
});

test("clips: every shipped audio clip, decoded and measured", async ({ page }, info) => {
  const viewport = viewportOf(info);
  test.skip(viewport.id !== CFG.audio_viewport, "the clips are measured once");
  const record: Record<string, unknown> = { viewport };
  try {
    await page.goto(URL, { waitUntil: "domcontentloaded" });
    record.clips = await page.evaluate(async () => {
      const base = new globalThis.URL("assets/", location.href);
      const response = await fetch(new globalThis.URL("assets.json", base).href);
      if (!response.ok) return { manifest: response.status, clips: [] };
      const manifest = await response.json() as { assets?: Record<string, { type?: string; url?: string; role?: string; audio?: { loop?: boolean } }> };
      const AUDIO = /\.(ogg|mp3|wav|m4a|aac|opus|webm|flac)$/i;
      const clips: Record<string, unknown>[] = [];
      for (const [id, entry] of Object.entries(manifest.assets ?? {})) {
        const url = entry.url ?? "";
        if (!(entry.audio || ["music", "sfx", "ambience", "voice"].includes(String(entry.type)) && AUDIO.test(url))) continue;
        const out: Record<string, unknown> = { id, url, type: entry.type ?? null, role: entry.role ?? null, loop: entry.audio?.loop ?? null };
        try {
          const file = await fetch(new globalThis.URL(url, base).href);
          out.status = file.status;
          if (!file.ok) { clips.push(out); continue; }
          const data = await file.arrayBuffer();
          out.bytes = data.byteLength;
          const ctx = new OfflineAudioContext(1, 1, 44100);
          const buffer = await ctx.decodeAudioData(data);
          out.duration_s = Math.round(buffer.duration * 1000) / 1000;
          out.channels = buffer.numberOfChannels;
          out.sample_rate = buffer.sampleRate;
          let peak = 0, sum = 0, n = 0;
          const block = Math.max(1, Math.round(buffer.sampleRate * 0.05));
          const blocks: number[] = [];
          const channels = Array.from({ length: buffer.numberOfChannels }, (_, c) => buffer.getChannelData(c));
          for (let start = 0; start < buffer.length; start += block) {
            let bsum = 0, bn = 0;
            for (const data of channels) {
              const end = Math.min(buffer.length, start + block);
              for (let i = start; i < end; i++) {
                const v = data[i];
                const a = Math.abs(v);
                if (a > peak) peak = a;
                bsum += v * v;
                bn += 1;
              }
            }
            sum += bsum;
            n += bn;
            if (bn) blocks.push(bsum / bn);
          }
          const db = (power: number) => (power > 0 ? Math.round(10 * Math.log10(power) * 10) / 10 : null);
          out.peak_dbfs = peak > 0 ? Math.round(20 * Math.log10(peak) * 100) / 100 : null;
          out.rms_dbfs = n ? db(sum / n) : null;
          out.blocks_db = blocks.map(db);
        } catch (error) {
          out.error = String(error).slice(0, 200);
        }
        clips.push(out);
      }
      return { manifest: 200, clips };
    });
  } catch (error) {
    record.error = String(error).slice(0, 300);
  }
  write(viewport.id, "clips", record);
});
