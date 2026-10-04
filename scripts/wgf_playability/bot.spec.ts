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
// When the probe declares the optional showcase capability (play.showcase), a last test asks
// it to stage, one by one, the real states where each asset it names is drawn - later levels a
// fresh save never reaches - and keeps a frame of each, so the production gate can see those
// assets drawn too. It is never used to play or to judge play.
// Factory tooling: it contains no game, and is not part of one.

import { test, type Page } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

interface Move {
  action: string;
  input: { type: "pointer"; x: number; y: number; hold_ms?: number } | { type: "key"; key: string; hold_ms?: number };
}
interface Progress {
  metric: string;
  value: number;
  target: number;
}
interface Content {
  unit_id: string | null;
  unit_index: number;
  unit_count: number;
  unit_kind: string;
  objective?: string;
  progress?: Progress;
}
interface Snapshot {
  state: string;
  metrics: Record<string, number>;
  content?: Content;
  entities: { id: string; kind?: string; role: string; x: number; y: number; w: number; h: number; visible: boolean; asset?: string | null; render?: string }[];
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
  // The content contract (game-design 1.9.0 build_spec.content), when the design states one:
  // what the traverse test plays through, and the axes a difficulty value is read from.
  content_applies: boolean;
  // The depth contract (build_spec.depth): what the persist and session tests measure.
  depth_applies: boolean;
  unit_count: number;
  max_units: number;
  traverse_ms: number;
  persist_ms: number;
  session_target_ms: number;
  session_max_ms: number;
  window_ms: number;
  axes: string[];
  advance_actions: string[];
  // The family says a unit can be restarted from inside it (genre-models qa.reset_in_unit).
  reset_in_unit: boolean;
  // The showcase test's whole window, when the game's probe offers to stage states.
  showcase_ms: number;
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

// The roles a glimpse is taken for, and how many a test takes.
const GLIMPSE_ROLES = new Set(["player", "threat", "goal", "target", "projectile", "collectible", "hazard"]);
const GLIMPSES = 6;
// The showcase (Watch.showcase): at most this many staged states per test, and how long one
// may take to stage and to report its asset drawn.
const SHOWCASE_MAX = 16;
const SHOWCASE_STAGE_MS = 6000;

// What one test saw beside play itself: page errors, every response for a file under
// /assets/ (and the runtime manifest's body), the runtime asset ids the probe reported
// loaded, and the UI measured per screen state. Spread into the test's record.
class Watch {
  errors: string[] = [];
  requests: { url: string; status: number | null }[] = [];
  runtimeAssets: unknown = null;
  loaded = new Set<string>();
  ui: Record<string, unknown> = {};
  glimpsed = new Set<string>();
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

  // The first moment of play that draws an entity with a runtime asset no measured screen
  // has shown yet (a falling pickup, a shot): its frame and where the snapshots around it
  // put it, kept as screen `glimpse-<asset>`. A transient thing is otherwise never in a state
  // frame, and the production gate could not see it drawn. Only the roles the player must
  // read; at most GLIMPSES per test.
  async glimpse(s: Snapshot | null): Promise<void> {
    if (!s || s.state !== "playing" || this.glimpsed.size >= GLIMPSES) return;
    const shown = new Set<string>();
    for (const ui of Object.values(this.ui) as { entities?: Snapshot["entities"] }[]) {
      for (const e of ui.entities ?? []) if (e.asset && e.visible) shown.add(e.asset);
    }
    const fresh = s.entities.find((e) => e.asset && e.visible && GLIMPSE_ROLES.has(e.role)
      && !shown.has(e.asset) && !this.glimpsed.has(e.asset));
    if (!fresh?.asset) return;
    const name = `glimpse-${fresh.asset}`;
    // An entity gone by the end of the shot (caught) is looked for again at its next appearance.
    const shot = await this.capture(name);
    if (!shot || !shot.entities.some((e) => e.id === fresh.id)) return;
    this.glimpsed.add(fresh.asset);
    this.frames.push(`state-${name}`);
    this.ui[name] = { probe_state: shot.state, frame: `state-${name}`, viewport: shot.viewport,
                      elements: [], texts: [], overlaps: [], probe_ui: [], glimpse: true,
                      entities: shot.entities };
  }

  // A frame `state-<name>.png` of the screen now, with the entities the probe reports in it.
  // A screenshot takes up to a second here, and the frame it keeps is somewhere inside that
  // second: a falling pickup moves past its own box meanwhile. So each entity's box is the one
  // it swept between the snapshots just before and just after the shot, `own` is its drawn
  // size [w, h] (the larger of the two snapshots), and an entity gone by then is left out.
  // Null when the probe did not answer.
  async capture(name: string): Promise<{ state: string; viewport: number[] | null; entities: Snapshot["entities"] } | null> {
    const before = this.saw(await snap(this.page));
    await this.page.screenshot({ path: path.join(dir(this.project), "frames", `state-${name}.png`) });
    const after = this.saw(await snap(this.page));
    if (!before || !after) return null;
    const later = new Map((after.entities ?? []).map((e) => [e.id, e]));
    const entities = before.entities.filter((e) => later.has(e.id)).map((e) => {
      const a = later.get(e.id)!;
      const x = Math.min(e.x, a.x), y = Math.min(e.y, a.y);
      return { ...e, x, y, w: Math.max(e.x + e.w, a.x + a.w) - x, h: Math.max(e.y + e.h, a.y + a.h) - y,
               own: [Math.max(e.w, a.w), Math.max(e.h, a.h)], visible: e.visible && a.visible };
    });
    const viewport = this.page.viewportSize();
    return { state: before.state, viewport: viewport ? [viewport.width, viewport.height] : null, entities };
  }

  // One state the game stages on request through its probe's optional showcase capability
  // (play.showcase.show(asset): a real state of the built game in which that runtime asset is
  // drawn - the level it first appears in, its boss, its pickup). The bot waits until the
  // probe reports play with an entity drawn from the asset (or one of its variants), lets the
  // screen settle, and keeps the frame `state-showcase-<asset>` with the entities in it,
  // exactly as a glimpse of play. It credits nothing itself: the production gate reads the
  // frame, and counts an entity only where its box in the frame is not the background.
  async showcase(target: string): Promise<Record<string, unknown>> {
    const t0 = Date.now();
    const staged = await this.page.evaluate(async ({ id, ms }) => {
      const sc = (window as unknown as { __wgf__?: { play?: { showcase?: { show?(a: string): unknown } } } })
        .__wgf__?.play?.showcase;
      if (!sc || typeof sc.show !== "function") return "no show()";
      try {
        const answer = await Promise.race([Promise.resolve(sc.show(id)),
                                           new Promise((resolve) => setTimeout(() => resolve("timeout"), ms))]);
        return answer === "timeout" ? "timeout" : answer === false ? "refused" : "staged";
      } catch (error) {
        return `error: ${String(error).slice(0, 200)}`;
      }
    }, { id: target, ms: SHOWCASE_STAGE_MS });
    if (staged !== "staged") return { target, staged: false, reason: staged, ms: Date.now() - t0 };
    const entry = (this.runtimeAssets as { assets?: Record<string, { variants?: unknown }> } | null)?.assets?.[target];
    const drawings = new Set<string>([target, ...(Array.isArray(entry?.variants) ? entry.variants as string[] : [])]);
    const drawn = (s: Snapshot | null): boolean => s?.state === "playing"
      && (s.entities ?? []).some((e) => e.visible && e.asset && drawings.has(e.asset));
    let s: Snapshot | null = null;
    while (Date.now() - t0 < SHOWCASE_STAGE_MS) {
      s = this.saw(await snap(this.page));
      if (drawn(s)) break;
      await this.page.waitForTimeout(100);
    }
    if (!drawn(s)) {
      return { target, staged: true, reported_drawn: false, state: s?.state ?? null, ms: Date.now() - t0 };
    }
    // An entrance (a fade, a drop-in) is not what the state shows: let it finish.
    await settle(this.page);
    await this.page.waitForTimeout(300);
    const name = `showcase-${target}`;
    const shot = await this.capture(name);
    if (!shot) return { target, staged: true, reported_drawn: true, captured: false, ms: Date.now() - t0 };
    this.frames.push(`state-${name}`);
    this.ui[name] = { probe_state: shot.state, frame: `state-${name}`, viewport: shot.viewport,
                      elements: [], texts: [], overlaps: [], probe_ui: [], showcase: true, target,
                      entities: shot.entities };
    return { target, staged: true, reported_drawn: true, captured: true, frame: `state-${name}`,
             ms: Date.now() - t0 };
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
        // Whether that text is drawn: an icon-only control is named by its aria-label, which is
        // read to the player but never painted, so it has no colour to measure.
        text_drawn: Boolean(((el as HTMLElement).innerText || (el as HTMLInputElement).value || "").trim()),
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
// The input that goes back into play after an attempt ended.
const RETRY = /retry|restart|again|replay/i;
// Inputs that undo play rather than play it: never "bad play" (the live puzzle offered a
// restart during play, and an anti-oracle that pressed it reset its own moves every third
// press and never lost).
const UNDO = /retry|restart|again|replay|reset|undo|rewind/i;

// The difficulty in force now, on the axes the design declared: the probe reports each as
// `metrics.difficulty.<axis>` (play-probe.schema.json). An axis the build does not report is
// absent here, not zero - a zero would read as "measured, and flat".
function difficultyOf(s: Snapshot | null): Record<string, number> {
  const out: Record<string, number> = {};
  for (const axis of CFG.axes ?? []) {
    const value = s?.metrics?.[`difficulty.${axis}`];
    if (typeof value === "number") out[axis] = value;
  }
  return out;
}

// The distinct entity kinds drawn now, in the game's own vocabulary (entities[].kind).
function kindsOf(s: Snapshot | null): string[] {
  const kinds = new Set<string>();
  for (const entity of s?.entities ?? []) if (entity.kind) kinds.add(entity.kind);
  return [...kinds].sort();
}

// The input the oracle names to leave a finished unit for the next one ("next", "continue",
// "play"), as the design's advance actions list them.
function advanceOf(s: Snapshot | null): Move | null {
  const names: string[] = CFG.advance_actions ?? [];
  const matches = (action: string): boolean =>
    names.some((name) => action.toLowerCase() === name.toLowerCase());
  const oracle = s?.oracle;
  if (oracle && matches(oracle.action)) return oracle;
  return s?.inputs?.find((m) => matches(m.action) || RETRY.test(m.action)) ?? null;
}

/** The unit in play has reached its own target: its progress says so. */
// A unit is done on its own measure when progress has RISEN to its target: value rises
// toward target (gems 2 of 3), so a target of 0, or a value that already met the target when
// the unit began (a count that falls - moves left 12 of 0 - is a lose metric, not progress),
// never counts as done. Only `won` is trusted without that.
const progressAtEntry = new Map<string, number>();
function progressDone(s: Snapshot | null): boolean {
  const progress = s?.content?.progress;
  if (!progress || !(progress.target > 0)) return false;
  const key = `${s?.content?.unit_id ?? ""}#${s?.content?.unit_index ?? 0}`;
  if (!progressAtEntry.has(key)) progressAtEntry.set(key, progress.value);
  const entry = progressAtEntry.get(key) ?? progress.value;
  return progress.value >= progress.target && entry < progress.target;
}

/** Back into play after an attempt ended: the retry the probe lists, else the visible button. */
async function retry(page: Page, s: Snapshot | null, touch: boolean): Promise<string | null> {
  const move = s?.inputs?.find((m) => RETRY.test(m.action)) ?? advanceOf(s);
  if (move) {
    await act(page, move, touch);
    return `input:${move.action}`;
  }
  const button = page.getByRole("button", { name: /retry|restart|play again|try again|replay|next|continue/i }).first();
  if (await button.count()) {
    await button.click();
    return "button";
  }
  return null;
}

// Opens the game as a first session and waits for play, pressing the title screen's own
// begin input (as the probe lists it) as a player would. Returns the timings it measured.
// With `screens`, the title screen's UI is measured before it is pressed; that measurement
// (settling, styles, a frame) is the bot's time, not the game's, and is returned as
// `observerMs` so start.playable can leave it out. `playingMs` stays the wall clock.
async function start(page: Page, touch: boolean, watch: Watch, screens = false): Promise<{ firstSnapshotMs: number | null; playingMs: number | null; observerMs: number; samples: Snapshot[]; began: string | null }> {
  const t0 = Date.now();
  let observerMs = 0;
  await page.goto(URL, { waitUntil: "domcontentloaded" });
  let firstSnapshotMs: number | null = null;
  let began: string | null = null;
  let pressedAt = 0;
  const samples: Snapshot[] = [];
  while (Date.now() - t0 < CFG.start_timeout_ms) {
    const s = watch.saw(await snap(page));
    if (s && firstSnapshotMs === null) firstSnapshotMs = Date.now() - t0;
    if (s && samples.length < 3) samples.push(s);
    if (s?.state === "playing") return { firstSnapshotMs, playingMs: Date.now() - t0, observerMs, samples, began };
    if (screens && s?.state === "title") {
      const observing = Date.now();
      await watch.screen("title");
      observerMs += Date.now() - observing;
    }
    const begin = s && s.state !== "loading" ? s.inputs?.find((m) => BEGIN.test(m.action)) : undefined;
    if (begin && Date.now() - pressedAt > 1000) {
      await act(page, begin, touch);
      began = begin.action;
      pressedAt = Date.now();
    }
    await page.waitForTimeout(50);
  }
  return { firstSnapshotMs, playingMs: null, observerMs, samples, began };
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
      await watch.glimpse(s);
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
  let initialContent: Content | null = null;
  let contentAtEnd: Content | null = null;
  let endedAtMs: number | null = null;
  let resetInUnit: unknown = null;
  let restart: unknown = null;
  // Every few samples, what the metrics said: a resource the design says bad play drains
  // (genre-models qa.resource_metric) is read from here, never from the game's own account.
  const series: { ms: number; state: string; metrics: Record<string, number>; content: Content | null }[] = [];
  // Every press the anti-oracle made, in order: what bad play actually did is evidence.
  const wrongPresses: { ms: number; action: string; picked: number | null; of: number; repeated: boolean }[] = [];
  if (started.playingMs !== null) {
    const first = watch.saw(await snap(page));
    initial = first?.metrics ?? null;
    initialContent = first?.content ?? null;
    // A family whose unit can be restarted from inside it: the restart is pressed while the
    // unit is still in play, and the unit's own progress must go back to the start.
    if (CFG.reset_in_unit) {
      const before = watch.saw(await snap(page));
      if (before?.oracle) await act(page, before.oracle, touch);
      await page.waitForTimeout(300);
      const mid = watch.saw(await snap(page));
      const t = Date.now();
      const clicked = mid?.state === "playing" ? await retry(page, mid, touch) : null;
      let back: Snapshot | null = null;
      let playingMs: number | null = null;
      while (clicked && Date.now() - t < 10000) {
        back = watch.saw(await snap(page));
        if (back?.state === "playing" && Date.now() - t > 200) {
          playingMs = Date.now() - t;
          break;
        }
        const begin = back && back.state !== "lost" ? back.inputs?.find((m) => BEGIN.test(m.action)) : undefined;
        if (begin) await act(page, begin, touch);
        await page.waitForTimeout(50);
      }
      resetInUnit = { clicked, playingMs, before: mid?.content ?? null, after: back?.content ?? null,
                      metrics_before: mid?.metrics ?? null, metrics_after: back?.metrics ?? null };
    }
    const t0 = Date.now();
    // One success first, as a first-time player would: the grace ends at the first success.
    let succeeded = false;
    let samples = 0;
    // The anti-oracle rotates through the moves that are not the oracle's: `k` advances on
    // every press, and again when the press before it moved nothing the probe reports, so a
    // direction a wall blocks (no move spent, nothing changed) is not pressed for the whole
    // window.
    let k = 0;
    let unchanged: string | null = null;
    while (Date.now() - t0 < CFG.lose_ms) {
      const s = watch.saw(await snap(page));
      if (!s) break;
      if (samples++ % 3 === 0 && series.length < 400) {
        series.push({ ms: Date.now() - t0, state: s.state, metrics: s.metrics ?? {},
                      content: s.content ?? null });
      }
      if (s.state === "lost" || s.state === "won") {
        reached = s.state;
        endedAtMs = Date.now() - t0;
        contentAtEnd = s.content ?? null;
        break;
      }
      if (!succeeded && s.oracle) {
        await act(page, s.oracle, touch);
        succeeded = true;
      } else {
        // A move that is not the oracle's, never a pause or settings toggle (bad play, not no
        // play); with no other move, the only one there is. With no oracle at all - the
        // player has slid into a dead end the game cannot solve from - bad play goes on all
        // the same: a puzzle still loses by running out of moves, and a game that never
        // ends from there is what this test exists to show.
        const moves = s.inputs.filter((m) => !UTILITY.test(m.action) && !UNDO.test(m.action));
        const others = s.oracle
          ? moves.filter((m) => JSON.stringify(m) !== JSON.stringify(s.oracle))
          : moves;
        if (!others.length && !s.oracle) {
          await page.waitForTimeout(150);
          continue;
        }
        // What the last press did, as the probe reports it: the metrics and the unit's own
        // progress. The same state again means the press changed nothing.
        const state = JSON.stringify({ m: s.metrics ?? {}, c: s.content ?? null });
        const repeated = unchanged !== null && state === unchanged;
        if (repeated) k += 1;
        unchanged = state;
        const picked = others.length ? k % others.length : null;
        const wrong = picked === null ? (s.oracle as Move) : others[picked];
        k += 1;
        if (wrongPresses.length < 60) {
          wrongPresses.push({ ms: Date.now() - t0, action: wrong.action, picked,
                              of: others.length, repeated });
        }
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
      restart = { clicked, playingMs, metrics: after?.metrics ?? null, endMetrics: at?.metrics ?? null,
                  content: after?.content ?? null, endContent: at?.content ?? null };
      // The screen after the retry, once play is back: measured after the restart's timing.
      if (playingMs !== null) {
        await page.waitForTimeout(500);
        await watch.screen("retry");
      }
    }
  }
  write(project, "lose", { ...started, initial, initialContent, reached, endedAtMs, contentAtEnd,
                           series, wrongPresses, resetInUnit, restart, ...watch.record(), frames });
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

// -- the content contract -------------------------------------------------------------------

interface UnitRecord {
  unit_id: string | null;
  index: number;
  objective_texts: string[];
  kinds: string[];
  difficulty: Record<string, number>;
  metrics: Record<string, number>;
  won: boolean;
  lost: boolean;
  entered_ms: number;
  duration_ms: number;
}

// The units the design claims, played one after another with real input. The oracle names the
// move that succeeds and, at the end of a unit, the move that advances; the bot presses it as
// a player would, and never jumps to a unit it has not finished. Only recorded: which unit was
// in play, what it asked for, what was drawn in it, and the difficulty in force.
test("traverse: the oracle plays unit after unit", async ({ page }, info) => {
  const project = info.project.name;
  const frames: string[] = [];
  const watch = new Watch(page, project, frames);
  if (!CFG.content_applies) {
    write(project, "traverse", { applies: false, reason: "the design states no content units" });
    return;
  }
  const touch = Boolean(info.project.use.hasTouch);
  const started = await start(page, touch, watch);
  const snapshots: { ms: number; unit_id: string | null; unit_index: number; state: string;
                     progress: Progress | null; difficulty: Record<string, number>;
                     kinds: string[] }[] = [];
  const transitions: { from: number; to: number; at_ms: number; how: string; since_end_ms: number | null }[] = [];
  const units: UnitRecord[] = [];
  let stopped = "window";
  let losses = 0;
  if (started.playingMs !== null) {
    const t0 = Date.now();
    let current: number | null = null;
    let ended: { ms: number; how: string } | null = null;
    const shot = new Set<number>();
    while (Date.now() - t0 < CFG.traverse_ms) {
      const s = watch.saw(await snap(page));
      if (!s) break;
      const ms = Date.now() - t0;
      const index = s.content?.unit_index ?? 0;
      const difficulty = difficultyOf(s);
      const kinds = kindsOf(s);
      if (snapshots.length < 1500) {
        snapshots.push({ ms, unit_id: s.content?.unit_id ?? null, unit_index: index,
                         state: s.state, progress: s.content?.progress ?? null, difficulty, kinds });
      }
      if (index !== current) {
        if (current !== null && index > 0) {
          transitions.push({ from: current, to: index, at_ms: ms, how: ended?.how ?? "unknown",
                             since_end_ms: ended ? ms - ended.ms : null });
        }
        current = index;
        ended = null;
      }
      let unit = units.find((u) => u.index === index);
      if (index > 0 && !unit) {
        unit = { unit_id: s.content?.unit_id ?? null, index, objective_texts: [], kinds: [],
                 difficulty: {}, metrics: {}, won: false, lost: false, entered_ms: ms,
                 duration_ms: 0 };
        units.push(unit);
      }
      if (unit) {
        unit.duration_ms = ms - unit.entered_ms;
        unit.metrics = s.metrics ?? {};
        for (const kind of kinds) if (!unit.kinds.includes(kind)) unit.kinds.push(kind);
        Object.assign(unit.difficulty, difficulty);
        // The objective, as the player is shown it: the unit's own text, and the page's.
        if (unit.objective_texts.length < 4) {
          if (s.content?.objective) unit.objective_texts.push(s.content.objective);
          unit.objective_texts.push(await page.evaluate(() => document.body.innerText));
        }
        if (!shot.has(index) && ms - unit.entered_ms > 1000) {
          await frame(page, project, `unit-${index}-1s`, frames);
          shot.add(index);
        }
      }
      if (s.state === "won" || progressDone(s)) {
        if (unit) unit.won = true;
        ended = { ms, how: s.state === "won" ? "won" : "progress" };
        const advance = advanceOf(s);
        if (advance) await act(page, advance, touch);
        else if (s.state === "won") await retry(page, s, touch);
        await page.waitForTimeout(250);
        continue;
      }
      if (s.state === "lost") {
        if (unit) unit.lost = true;
        losses += 1;
        ended = { ms, how: "lost" };
        if (losses >= 2) {
          stopped = "lost twice";
          break;
        }
        await retry(page, s, touch);
        await page.waitForTimeout(250);
        continue;
      }
      if (units.length >= CFG.max_units) {
        stopped = "max units";
        break;
      }
      if (s.oracle) {
        await act(page, s.oracle, touch);
        await page.waitForTimeout(120);
      } else {
        await page.waitForTimeout(40);
      }
    }
  } else {
    stopped = "play never began";
  }
  write(project, "traverse", { ...started, applies: true, snapshots, transitions,
                               per_unit: units, losses, stopped, ...watch.record(), frames });
});

// What the game remembers. The oracle plays until something the design says persists has
// moved - the best, or the unit reached - the page is reloaded, and the probe is read BEFORE
// any input: whatever is gone was not persisted.
test("persist: what survives a reload", async ({ page }, info) => {
  const project = info.project.name;
  const frames: string[] = [];
  const watch = new Watch(page, project, frames);
  if (!CFG.depth_applies) {
    write(project, "persist", { applies: false, reason: "the design states no depth contract" });
    return;
  }
  const touch = Boolean(info.project.use.hasTouch);
  const started = await start(page, touch, watch);
  let before: Snapshot | null = null;
  let after: Snapshot | null = null;
  let afterResumed: Snapshot | null = null;
  let changed: string | null = null;
  if (started.playingMs !== null) {
    const opening = watch.saw(await snap(page));
    const bestAt = opening?.metrics?.best ?? null;
    const indexAt = opening?.content?.unit_index ?? null;
    const t0 = Date.now();
    while (Date.now() - t0 < CFG.persist_ms) {
      const s = watch.saw(await snap(page));
      if (!s) break;
      const best = s.metrics?.best ?? null;
      const index = s.content?.unit_index ?? null;
      if (best !== null && bestAt !== null && best > bestAt) changed = "best";
      else if (index !== null && indexAt !== null && index > indexAt) changed = "unit_index";
      if (changed) break;
      if (s.state === "lost" || s.state === "won") {
        // A best is written at the end of an attempt: go back in and read it.
        await retry(page, s, touch);
        await page.waitForTimeout(400);
        continue;
      }
      if (s.oracle) {
        await act(page, s.oracle, touch);
        await page.waitForTimeout(120);
      } else {
        await page.waitForTimeout(60);
      }
    }
    before = watch.saw(await snap(page));
    await page.reload({ waitUntil: "domcontentloaded" });
    const t1 = Date.now();
    while (Date.now() - t1 < CFG.start_timeout_ms) {
      const s = await snap(page);
      if (s && s.state !== "loading") {
        after = watch.saw(s);
        break;
      }
      await page.waitForTimeout(50);
    }
    await frame(page, project, "persist-after-reload", frames);
    // Back into play without replaying anything, so the unit reached can be compared too.
    const begin = after?.inputs?.find((m) => BEGIN.test(m.action) || RETRY.test(m.action));
    if (begin) {
      await act(page, begin, touch);
      const t2 = Date.now();
      while (Date.now() - t2 < 10000) {
        const s = watch.saw(await snap(page));
        if (s?.state === "playing") {
          afterResumed = s;
          break;
        }
        await page.waitForTimeout(50);
      }
    }
  }
  write(project, "persist", { ...started, applies: true, changed, before, after,
                              after_resumed: afterResumed, ...watch.record(), frames });
});

// One first session, as the design designed it: the oracle plays and retries at once, and the
// session is held open to the design's own first-session length. Recorded: how long play
// lasted, each attempt with the oracle's input rate per third of it (does the game ask more of
// the player as it goes?), when the designed closing beat first arrived, and the difficulty in
// force in each window.
test("session: a first session's length and ramp", async ({ page }, info) => {
  const project = info.project.name;
  const frames: string[] = [];
  const watch = new Watch(page, project, frames);
  if (!CFG.depth_applies) {
    write(project, "session", { applies: false, reason: "the design states no depth contract" });
    return;
  }
  const touch = Boolean(info.project.use.hasTouch);
  const started = await start(page, touch, watch);
  const runs: { duration_ms: number; inputs: number; oracle_inputs_per_third: number[] }[] = [];
  const windows: { at_ms: number; difficulty: Record<string, number> }[] = [];
  let lengthMs = 0;
  let beatAtMs: number | null = null;
  let endedOn = "window";
  if (started.playingMs !== null) {
    const t0 = Date.now();
    const opening = watch.saw(await snap(page));
    let best = opening?.metrics?.best ?? null;
    let index = opening?.content?.unit_index ?? null;
    let runStart = Date.now();
    let inputs: number[] = [];
    let window = 0;
    const close = (): void => {
      const duration = Date.now() - runStart;
      const third = Math.max(1, duration / 3);
      const thirds = [0, 0, 0];
      for (const at of inputs) {
        const slot = Math.min(2, Math.floor(at / third));
        thirds[slot] = (thirds[slot] ?? 0) + 1;
      }
      runs.push({ duration_ms: duration, inputs: inputs.length, oracle_inputs_per_third: thirds });
      inputs = [];
      runStart = Date.now();
    };
    while (Date.now() - t0 < CFG.session_max_ms) {
      const s = watch.saw(await snap(page));
      if (!s) break;
      const ms = Date.now() - t0;
      if (ms >= (window + 1) * CFG.window_ms) {
        window = Math.floor(ms / CFG.window_ms);
        windows.push({ at_ms: ms, difficulty: difficultyOf(s) });
      }
      const nowBest = s.metrics?.best ?? null;
      const nowIndex = s.content?.unit_index ?? null;
      if (beatAtMs === null && ((nowBest !== null && best !== null && nowBest > best)
                               || (nowIndex !== null && index !== null && nowIndex > index))) {
        beatAtMs = ms;
      }
      if (nowBest !== null) best = Math.max(best ?? nowBest, nowBest);
      if (nowIndex !== null) index = Math.max(index ?? nowIndex, nowIndex);
      if (s.state === "lost" || s.state === "won") {
        close();
        // Instant retry: a first session is only as long as the game lets the player stay in.
        const clicked = await retry(page, s, touch);
        if (!clicked) {
          endedOn = "no retry was offered";
          break;
        }
        await page.waitForTimeout(300);
        const back = watch.saw(await snap(page));
        const begin = back?.inputs?.find((m) => BEGIN.test(m.action));
        if (begin) await act(page, begin, touch);
        runStart = Date.now();
        continue;
      }
      if (s.oracle) {
        await act(page, s.oracle, touch);
        inputs.push(Date.now() - runStart);
        await page.waitForTimeout(120);
      } else {
        await page.waitForTimeout(40);
      }
    }
    if (Date.now() - runStart > 500) close();
    lengthMs = Date.now() - t0;
    if (beatAtMs !== null && endedOn === "window") endedOn = "beat reached";
    await frame(page, project, "session-end", frames);
  } else {
    endedOn = "play never began";
  }
  write(project, "session", { ...started, applies: true, length_ms: lengthMs,
                              beat_at_ms: beatAtMs, ended_on: endedOn, runs, windows,
                              target_ms: CFG.session_target_ms, window_ms: CFG.window_ms,
                              ...watch.record(), frames });
});

// -- the showcase ---------------------------------------------------------------------------

// The runtime asset ids the probe offers to stage (play.showcase.targets()), or null when the
// game declares no showcase.
async function showcaseTargets(page: Page): Promise<string[] | null> {
  return page.evaluate(() => {
    const sc = (window as unknown as { __wgf__?: { play?: { showcase?: { targets?(): unknown; show?: unknown } } } })
      .__wgf__?.play?.showcase;
    if (!sc || typeof sc.targets !== "function" || typeof sc.show !== "function") return null;
    try {
      const targets = sc.targets();
      return Array.isArray(targets) ? [...new Set(targets.filter((t): t is string => typeof t === "string"))] : [];
    } catch {
      return [];
    }
  });
}

// After the first-session tests, which all start on a fresh save and so only ever meet the
// opening content: the states where the assets of later content are drawn, when the game
// offers to stage them. Each is a real state of the built game, rendered by it and captured
// like a state frame; the bot never plays through the showcase, and no playability check reads
// it. A game whose probe declares no showcase gets a record that says so and nothing else.
test("showcase: the states where later assets are drawn, if the game stages them", async ({ page }, info) => {
  const project = info.project.name;
  const frames: string[] = [];
  const watch = new Watch(page, project, frames);
  const touch = Boolean(info.project.use.hasTouch);
  const started = await start(page, touch, watch);
  const declared = started.playingMs !== null ? await showcaseTargets(page) : null;
  if (declared === null) {
    write(project, "showcase", { applies: false, reason: started.playingMs === null
      ? "play never began" : "the probe declares no showcase (play.showcase)" });
    return;
  }
  const visits: Record<string, unknown>[] = [];
  const t0 = Date.now();
  for (const target of declared.slice(0, SHOWCASE_MAX)) {
    if (Date.now() - t0 > CFG.showcase_ms) {
      visits.push({ target, staged: false, reason: "showcase window spent" });
      continue;
    }
    visits.push(await watch.showcase(target));
  }
  write(project, "showcase", { ...started, applies: true, declared, visits,
                               skipped: declared.slice(SHOWCASE_MAX), ...watch.record(), frames });
});
