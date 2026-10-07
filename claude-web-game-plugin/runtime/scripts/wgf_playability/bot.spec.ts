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
// assets drawn too. It is never used to play or to judge play. When the design's time ramp is
// promised by a mode it includes (an endless mode beside authored units), one test enters that
// mode through the probe's optional play.mode and plays it, so the ramp is read on its run.
// The recordings the timing-sensitive checks read carry their host's health, and one made on a
// degraded host is made again (Health, finish; core/reference/visual-quality.yaml
// `environment`).
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
  // The time ramp (analysis.time_ramp): the play it is read on - `session` (the endless play
  // itself), or `mode`: ramp_mode, entered through the probe's optional play.mode - or null.
  // The ramp test plays ramp_samples fresh runs of it, ramp_ms each, and further whole
  // samples within ramp_extend_ms while the pooled counts are undecided (fewer than
  // ramp_min_inputs in the first thirds, or a difference within ramp_noise_z x sqrt(n)).
  // ramp_stall_ms: the stall bar (depth.stall), past which a sample is decided as stalled.
  ramp_run?: string | null;
  ramp_mode?: string | null;
  ramp_ms?: number;
  ramp_samples?: number;
  ramp_noise_z?: number;
  ramp_min_inputs?: number;
  ramp_extend_ms?: number;
  ramp_stall_ms?: number;
  axes: string[];
  advance_actions: string[];
  // The family says a unit can be restarted from inside it (genre-models qa.reset_in_unit).
  reset_in_unit: boolean;
  // The showcase test's whole window, when the game's probe offers to stage states.
  showcase_ms: number;
  // The survey (core/reference/content-sufficiency.yaml `survey`): the unit ids entered one
  // by one through the probe's unit link, on these projects only, each for at most
  // survey_unit_ms and all of them within survey_ms; the roles whose entities carry a kind,
  // and the roles that are the player or the interface. Empty survey_units: no survey.
  survey_units?: string[];
  survey_projects?: string[];
  survey_unit_ms?: number;
  survey_ms?: number;
  kind_roles?: string[];
  not_content_roles?: string[];
  // Whether the host could measure anything (core/reference/visual-quality.yaml
  // `environment`): the bars a recording's health is judged degraded by, and how many
  // attempts the recordings in retry_records may take. The step's analysis re-judges every
  // attempt from the numbers; the bot only decides whether to make a recording again.
  environment?: { tick_ms: number; stall_ms: number; max_stall_ms: number; max_stalled_share: number;
                  max_server_wait_ms: number; max_attempts: number };
  retry_records?: string[];
  // The traverse plays on in the unit it stops inside while that unit has shown fewer than
  // min_new_kinds kinds no earlier unit showed, for at most variety_extend_ms
  // (visual-quality.yaml `sample`). 0: never.
  min_new_kinds?: number;
  variety_extend_ms?: number;
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

// -- the measurement's own validity ---------------------------------------------------------
//
// A recording is only as good as the host it was made on. Each attempt of a recording carries
// its `health`, measured on what the game cannot cause: a timer in the bot's own process and
// one in a worker thread inside the page, each expected every tick_ms (how late it fired, the
// longest lag and the time lost to lags of stall_ms or more), and how long the local preview
// server - a static file server - took to start answering the page's requests. Beside them,
// as evidence only, the navigation breakdown (time to first byte, DOMContentLoaded, load, the
// page's first frame, the first probe answer, play) and the page's requestAnimationFrame
// gaps: those are the game's own, and a game that blocks its main thread is a defect the
// checks fail, never a degraded host.

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

// Installed before every navigation of the page (start() adds it once): the page's frame gaps,
// its first frame, and the worker's timer.
function installHealth(cfg: { tick: number; stall: number }): void {
  const w = window as unknown as { __wgfHealth?: Record<string, unknown> };
  if (w.__wgfHealth) return;
  const h: Record<string, unknown> = { first_frame_ms: null, frames: 0, frame_gap_max_ms: 0, frame_stalls: 0 };
  w.__wgfHealth = h;
  let last: number | null = null;
  const loop = (t: number): void => {
    if (h.first_frame_ms === null) h.first_frame_ms = Math.round(t);
    if (last !== null) {
      const gap = t - last;
      if (gap > (h.frame_gap_max_ms as number)) h.frame_gap_max_ms = Math.round(gap);
      if (gap >= cfg.stall) h.frame_stalls = (h.frame_stalls as number) + 1;
    }
    last = t;
    h.frames = (h.frames as number) + 1;
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
  try {
    const source = `const t0=performance.now();let last=t0,max=0,stalled=0,ticks=0;
setInterval(()=>{const now=performance.now();const lag=now-last-${cfg.tick};if(lag>max)max=lag;
if(lag>=${cfg.stall})stalled+=lag;ticks++;last=now},${cfg.tick});
onmessage=()=>postMessage({max_lag_ms:Math.round(max),stalled_ms:Math.round(stalled),ticks,
elapsed_ms:Math.round(performance.now()-t0)})`;
    h.worker = new Worker(globalThis.URL.createObjectURL(new Blob([source], { type: "text/javascript" })));
  } catch (error) {
    h.worker_error = String(error).slice(0, 200);
  }
}

// What the page measured: the navigation breakdown, its frames, and the worker's timer (null
// when the page does not answer within 5 s, or never had the script).
async function pageHealth(page: Page): Promise<Record<string, unknown> | null> {
  const read = page.evaluate(async () => {
    const h = (window as unknown as { __wgfHealth?: Record<string, unknown> }).__wgfHealth;
    if (!h) return null;
    const nav = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
    const waits = (performance.getEntriesByType("resource") as PerformanceResourceTiming[])
      .concat(nav ? [nav] : [])
      .filter((e) => e.responseStart > 0 && e.requestStart > 0)
      .map((e) => e.responseStart - e.requestStart);
    const worker = h.worker as Worker | undefined;
    const beat = worker ? await new Promise((resolve) => {
      const timer = setTimeout(() => resolve(null), 2000);
      worker.onmessage = (event) => { clearTimeout(timer); resolve(event.data); };
      worker.postMessage(0);
    }) : null;
    return {
      nav: nav ? { ttfb_ms: Math.round(nav.responseStart - nav.startTime),
                   dom_content_loaded_ms: Math.round(nav.domContentLoadedEventEnd),
                   load_ms: Math.round(nav.loadEventEnd), first_frame_ms: h.first_frame_ms,
                   server_wait_max_ms: waits.length ? Math.round(Math.max(...waits)) : null,
                   requests: waits.length } : null,
      frames: { count: h.frames, gap_max_ms: h.frame_gap_max_ms, stalls: h.frame_stalls },
      worker: beat, worker_error: h.worker_error ?? null,
    };
  });
  return Promise.race([read.catch(() => null), new Promise<null>((resolve) => setTimeout(() => resolve(null), 5000))]);
}

// One attempt's health, and whether it is degraded against CFG.environment (the step's
// analysis.environment_health judges the same numbers the same way, and decides).
class Health {
  private readonly beat: Heartbeat | null;

  constructor() {
    const env = CFG.environment;
    this.beat = env ? new Heartbeat(env.tick_ms, env.stall_ms) : null;
  }

  // The pages a recording navigated away from (the ramp starts every sample on a fresh page,
  // and each page has its own worker timer): read before they go, and folded into the
  // attempt's health, so a stall on an earlier sample's page is not lost with the page.
  private readonly earlier: Record<string, unknown>[] = [];

  async keep(page: Page): Promise<void> {
    const inPage = await pageHealth(page);
    if (inPage) this.earlier.push(inPage);
  }

  async read(page: Page, started?: { firstSnapshotMs: number | null; playingMs: number | null }):
    Promise<{ health: Record<string, unknown>; degraded: boolean; reasons: string[] }> {
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
    const waits = navs.map((n) => n.server_wait_max_ms).filter((w): w is number => typeof w === "number");
    const last = navs.length ? navs[navs.length - 1] : null;
    const nav = last ? { ...last, server_wait_max_ms: waits.length ? Math.max(...waits) : null,
                         ...(pages.length > 1 ? { pages: pages.length } : {}) } : null;
    const health: Record<string, unknown> = {
      bot, worker, worker_error: inPage?.worker_error ?? null,
      nav: nav ? { ...nav, first_probe_ms: started?.firstSnapshotMs ?? null, playing_ms: started?.playingMs ?? null } : null,
      frames: inPage?.frames ?? null,
    };
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

// A recording the step's timing-sensitive checks read is made again, in a fresh browser (a
// Playwright retry), while its host was degraded and attempts remain; the record finally
// written is the last attempt's, with every attempt's health in `attempts`. A retry that was
// not asked for here (a test that threw) is skipped: it records nothing, as before.
function pending(project: string, name: string): string {
  return path.join(dir(project), `.${name}.attempts.json`);
}

async function finish(page: Page, info: { project: { name: string }; retry: number }, name: string,
                      data: Record<string, unknown>, health: Health): Promise<void> {
  const project = info.project.name;
  const started = data as { firstSnapshotMs?: number | null; playingMs?: number | null };
  const now = await health.read(page, { firstSnapshotMs: started.firstSnapshotMs ?? null,
                                        playingMs: started.playingMs ?? null });
  const marker = pending(project, name);
  const before = fs.existsSync(marker) ? JSON.parse(fs.readFileSync(marker, "utf8")) as unknown[] : [];
  const attempts = [...before, { attempt: before.length + 1, degraded: now.degraded, reasons: now.reasons,
                                 health: now.health }];
  const allowed = CFG.environment?.max_attempts ?? 1;
  // Written on every attempt: should the attempt made again never finish, the degraded one
  // stands, and is judged as degraded.
  write(project, name, { ...data, health: now.health, attempts });
  if (now.degraded && attempts.length < allowed && (CFG.retry_records ?? []).includes(name)) {
    fs.writeFileSync(marker, JSON.stringify(attempts));
    throw new Error(`the host was degraded while the ${name} recording was made (${now.reasons.join("; ")}); ` +
                    "it is made again");
  }
  if (fs.existsSync(marker)) fs.rmSync(marker);
}

// Every retry Playwright makes is one finish() asked for, or none at all.
test.beforeEach(async ({ page }, info) => {
  const name = RECORD_OF[info.title];
  const asked = name !== undefined && fs.existsSync(pending(info.project.name, name));
  test.skip(info.retry > 0 && !asked, "made again only when its host was degraded");
  if (CFG.environment) {
    await page.addInitScript(installHealth, { tick: CFG.environment.tick_ms, stall: CFG.environment.stall_ms });
  }
});

// The recordings made again on a degraded host, by test title (CFG.retry_records).
const RECORD_OF: Record<string, string> = {
  "first session: objective, and no failure before the grace": "first-session",
  "win: the oracle plays well": "win",
  "lose and restart: the anti-oracle plays badly, then retries": "lose",
  "traverse: the oracle plays unit after unit": "traverse",
  "ramp: samples of the play that promises the time ramp": "ramp",
};

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
// element's own and its ancestors' background colours composited; null when none is opaque, or
// one of them paints an image, a border-image, a mask or a painting pseudo-element, or another
// element paints between the text and that background - the canvas, a picture or art shows
// through and only the frame can tell; a control's colour, font and background are those of
// the element drawing its text), the rectangle of its own text (`glyph_box`, where the
// production gate reads the frame behind it), its text-shadow and stroke colours (`paint`)
// and its text-decoration line, whether the element's computed style equals the user-agent default for its tag
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
    // Paint that is not a plain colour: a background image or gradient, a (nine-slice)
    // border-image, a mask. Any of them can put art behind the text that the background
    // colour does not describe (sky-marble a61a9d7: a card's border-image was the whole
    // UI-kit sheet, its other screens' art drawn behind the text over a sand fill).
    const imagePaint = (s: CSSStyleDeclaration): boolean => {
      const mask = s.maskImage || s.getPropertyValue("-webkit-mask-image");
      return [s.backgroundImage, s.borderImageSource, mask].some((v) => Boolean(v) && v !== "none");
    };
    // A ::before / ::after that is rendered and paints: an image, an image paint, or a fill.
    const pseudoPaints = (n: Element): boolean => {
      for (const which of ["::before", "::after"]) {
        const p = getComputedStyle(n, which);
        if (!p.content || p.content === "none" || p.content === "normal" || p.display === "none") continue;
        if (/url\(|gradient\(/.test(p.content) || imagePaint(p)) return true;
        const fill = parse(p.backgroundColor);
        if (fill && fill[3] > 0) return true;
      }
      return false;
    };
    // An element that draws something of its own where it lies.
    const PAINTED = new Set(["canvas", "img", "video", "svg", "picture", "iframe", "object", "embed"]);
    const paints = (n: Element): boolean => {
      if (PAINTED.has(n.tagName.toLowerCase())) return true;
      const s = getComputedStyle(n);
      const fill = parse(s.backgroundColor);
      return Boolean(fill && fill[3] > 0) || imagePaint(s) || pseudoPaints(n);
    };
    // The opaque background behind the text: the background colours of the element and its
    // ancestors composited, up to the first opaque one (the backdrop). Null - undetermined,
    // for the frame to decide - when any of them up to the backdrop paints other than a plain
    // colour, or when, at the text's centre, an element that is neither one of them nor inside
    // the text paints between the text and the backdrop (a canvas, an image, a sibling tile
    // laid under or over it).
    const background = (el: Element, at: DOMRect | null): number[] | null => {
      const layers: RGBA[] = [];
      const chain: Element[] = [];
      let backdrop: Element | null = null;
      for (let n: Element | null = el; n; n = n.parentElement) {
        const style = getComputedStyle(n);
        chain.push(n);
        if (imagePaint(style) || pseudoPaints(n)) return null;
        const bg = parse(style.backgroundColor);
        if (bg && bg[3] > 0) {
          layers.push(bg);
          if (bg[3] >= 1) {
            backdrop = n;
            break;
          }
        }
      }
      if (!backdrop || !layers.length) return null;
      if (at && at.width > 0 && at.height > 0) {
        const x = at.left + at.width / 2, y = at.top + at.height / 2;
        if (x >= 0 && y >= 0 && x < innerWidth && y < innerHeight) {
          for (const e of document.elementsFromPoint(x, y)) {
            if (e === backdrop || e.contains(backdrop)) break;
            if (chain.includes(e) || el.contains(e)) continue;
            if (paints(e)) return null;
          }
        }
      }
      let out = layers[layers.length - 1];
      for (let i = layers.length - 2; i >= 0; i--) out = over(layers[i], out);
      return out.slice(0, 3).map((v) => Math.round(v));
    };
    // The element that draws a control's text: the parent of its first visible text (a
    // face <span> with its own colour and fill inside a transparent <button>), else the
    // control itself. Its colour, fill and font are what the player reads.
    const holder = (el: Element): Element => {
      const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      for (let t = walk.nextNode(); t; t = walk.nextNode()) {
        const parent = t.parentElement;
        if (parent && (t.textContent || "").trim() && visible(parent, parent.getBoundingClientRect())) return parent;
      }
      return el;
    };
    // The rectangle of the element's own text - its direct text nodes, not its children (an
    // icon, a key hint) - which is what the frame is read on behind the text. Null when none.
    const glyphs = (el: Element): DOMRect | null => {
      let l = Infinity, t = Infinity, r = -Infinity, b = -Infinity;
      for (const c of Array.from(el.childNodes)) {
        if (c.nodeType !== Node.TEXT_NODE || !(c.textContent || "").trim()) continue;
        const range = document.createRange();
        range.selectNodeContents(c);
        const q = range.getBoundingClientRect();
        if (q.width <= 0 || q.height <= 0) continue;
        l = Math.min(l, q.left); t = Math.min(t, q.top);
        r = Math.max(r, q.right); b = Math.max(b, q.bottom);
      }
      return l < r && t < b ? new DOMRect(l, t, r - l, b - t) : null;
    };
    // The text's own paints besides its colour: text-shadow and stroke colours, so an
    // outline or a glow is not taken for art behind the text.
    const paint = (el: Element): number[][] => {
      const s = getComputedStyle(el);
      const out = (s.textShadow.match(/rgba?\([^)]+\)/g) || []).map(parse)
        .filter((c): c is RGBA => Boolean(c && c[3] > 0));
      if (parseFloat(s.getPropertyValue("-webkit-text-stroke-width")) > 0) {
        const stroke = parse(s.getPropertyValue("-webkit-text-stroke-color"));
        if (stroke && stroke[3] > 0) out.push(stroke);
      }
      return out.slice(0, 4);
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
      const face = holder(el);
      const faceStyle = getComputedStyle(face);
      const glyph = glyphs(face);
      interactive.push(el);
      elements.push({
        tag: el.tagName.toLowerCase(), role: el.getAttribute("role"),
        text: ((el as HTMLElement).innerText || (el as HTMLInputElement).value || el.getAttribute("aria-label") || "").trim().slice(0, 60),
        // Whether that text is drawn: an icon-only control is named by its aria-label, which is
        // read to the player but never painted, so it has no colour to measure.
        text_drawn: Boolean(((el as HTMLElement).innerText || (el as HTMLInputElement).value || "").trim()),
        box: box(r), font_px: parseFloat(faceStyle.fontSize),
        font_weight: Number(faceStyle.fontWeight) || 400,
        color: ink(face), background: background(face, glyph ?? r), ua_default: differs.length === 0,
        ua_differs: differs, glyph_box: glyph ? box(glyph) : null, paint: paint(face),
        decoration: faceStyle.textDecorationLine,
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
      const glyph = glyphs(parent);
      textNodes.push(parent);
      texts.push({ text: (parent.innerText || "").trim().slice(0, 60), box: box(r),
                   font_px: parseFloat(s.fontSize), font_weight: Number(s.fontWeight) || 400,
                   color: ink(parent), background: background(parent, glyph ?? r),
                   glyph_box: glyph ? box(glyph) : null, paint: paint(parent),
                   decoration: s.textDecorationLine });
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
async function start(page: Page, touch: boolean, watch: Watch, screens = false, url = URL): Promise<{ firstSnapshotMs: number | null; playingMs: number | null; observerMs: number; samples: Snapshot[]; began: string | null }> {
  const t0 = Date.now();
  let observerMs = 0;
  await page.goto(url, { waitUntil: "domcontentloaded" });
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
  const health = new Health();
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
  await finish(page, info, "first-session", { ...started, texts: [...new Set(texts)], states, lostAtMs,
                                             ...watch.record(), audio_unfocused: unfocused, frames }, health);
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
  const health = new Health();
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
  await finish(page, info, "win", { ...started, reached, inputs, series: series.filter((_, i) => i % 5 === 0 || i === series.length - 1),
                                   sampled, ...watch.record(), frames }, health);
});

test("lose and restart: the anti-oracle plays badly, then retries", async ({ page }, info) => {
  const health = new Health();
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
  await finish(page, info, "lose", { ...started, initial, initialContent, reached, endedAtMs, contentAtEnd,
                                    series, wrongPresses, resetInUnit, restart, ...watch.record(), frames }, health);
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
  // The unit's objective as the probe states it (content.objective), apart from the page's.
  objective: string | null;
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
  const health = new Health();
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
  // Each transition carries the times that separate the game's latency from the bot's
  // (content.units_reachable judges the game's only): every time is the bot's clock from the
  // traverse start; a read's `_ms` is when that snapshot call began or returned, as noted.
  //   since_end_ms   at_ms minus the LAST read that showed the unit ended (raw, bot included)
  //   ended_ms       return of the FIRST read showing the unit ended: `won`, else its
  //                  progress target (a target met before `won` is timed from `won`)
  //   unoffered_ms   start of the last ended read on which no advance was offered yet
  //   offered_ms     return of the first ended read on which an advance was offered
  //   act_started_ms / acted_ms  the bot's first input after the end: began, was delivered
  //   inputs         the inputs the bot sent between the end and the next unit
  //   last_old_ms    start of the last read that still showed the finished unit
  //   at_ms          return of the read that first showed the next unit
  const transitions: { from: number; to: number; at_ms: number; how: string; since_end_ms: number | null;
                       ended_ms: number | null; unoffered_ms: number | null; offered_ms: number | null;
                       act_started_ms: number | null; acted_ms: number | null; inputs: number;
                       last_old_ms: number | null }[] = [];
  const units: UnitRecord[] = [];
  // The largest unit count the build itself reported (content.unit_count): what it ships,
  // beyond the units this window reached (an adopted game's floor, wgf_design/existing.py).
  let unitCountReported = 0;
  let stopped = "window";
  let losses = 0;
  // When the traverse stops (its window, its unit count) inside a unit that has not yet shown
  // the new kinds the family asks of every unit, it plays on in that unit - never into the
  // next - for up to CFG.variety_extend_ms: a kind that arrives later in the unit was
  // otherwise never seen, and the cut, not the build, would decide content.variety.
  let cutAt: number | null = null;
  let cutIndex: number | null = null;
  let extendedMs = 0;
  if (started.playingMs !== null) {
    const t0 = Date.now();
    let current: number | null = null;
    let ended: { ms: number; how: string } | null = null;
    // The game-side timeline of the unit that ended (see `transitions`).
    let end: { how: string; first: number; unoffered: number | null; offered: number | null; actStarted: number | null;
               acted: number | null; inputs: number } | null = null;
    let lastOld: number | null = null;
    // An input sent from the ended unit; `retry` returns null when it found nothing to press.
    const input = async (send: () => Promise<unknown>): Promise<void> => {
      const began = Date.now() - t0;
      const sent = await send();
      if (end && sent !== null) {
        end.inputs += 1;
        if (end.acted === null) {
          end.actStarted = began;
          end.acted = Date.now() - t0;
        }
      }
    };
    const shot = new Set<number>();
    const kindsShort = (): boolean => {
      const unit = units.find((u) => u.index === current);
      if (!CFG.min_new_kinds || !unit || unit.won || units.length < 2) return false;
      const earlier = new Set(units.filter((u) => u.index < unit.index).flatMap((u) => u.kinds));
      return unit.kinds.filter((k) => !earlier.has(k)).length < CFG.min_new_kinds;
    };
    for (;;) {
      const elapsed = Date.now() - t0;
      if (cutAt === null && elapsed >= CFG.traverse_ms) {
        cutAt = elapsed;
        cutIndex = current;
      }
      if (cutAt !== null) {
        // Recorded before the stop: an extension that ran its whole length records at least
        // variety_extend_ms, and the step judges the unit as seen whole (analysis).
        if (!kindsShort()) break;
        extendedMs = elapsed - cutAt;
        if (extendedMs >= (CFG.variety_extend_ms ?? 0)) break;
      }
      const readMs = Date.now() - t0;
      const s = watch.saw(await snap(page));
      if (!s) break;
      const ms = Date.now() - t0;
      const index = s.content?.unit_index ?? 0;
      // Only the unit the traverse stopped inside is played on: never one after it.
      if (cutAt !== null && index > 0 && index !== cutIndex) break;
      unitCountReported = Math.max(unitCountReported, s.content?.unit_count ?? 0);
      const difficulty = difficultyOf(s);
      const kinds = kindsOf(s);
      if (snapshots.length < 1500) {
        snapshots.push({ ms, unit_id: s.content?.unit_id ?? null, unit_index: index,
                         state: s.state, progress: s.content?.progress ?? null, difficulty, kinds });
      }
      if (index !== current) {
        if (current !== null && index > 0) {
          transitions.push({ from: current, to: index, at_ms: ms, how: ended?.how ?? "unknown",
                             since_end_ms: ended ? ms - ended.ms : null,
                             ended_ms: end?.first ?? null, unoffered_ms: end?.unoffered ?? null,
                             offered_ms: end?.offered ?? null, act_started_ms: end?.actStarted ?? null,
                             acted_ms: end?.acted ?? null, inputs: end?.inputs ?? 0,
                             last_old_ms: lastOld });
        }
        current = index;
        ended = null;
        end = null;
      }
      lastOld = readMs;
      let unit = units.find((u) => u.index === index);
      if (index > 0 && !unit) {
        unit = { unit_id: s.content?.unit_id ?? null, index, objective: s.content?.objective ?? null,
                 objective_texts: [], kinds: [],
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
        if (!unit.objective && s.content?.objective) unit.objective = s.content.objective;
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
        // Playing on past the cut: the unit is seen whole now, and the next is not entered.
        if (cutAt !== null) break;
        const advance = advanceOf(s);
        // The end is timed from the first `won` read, else the first at its progress target: a
        // unit whose progress met its target before the game declared it won ended at `won`.
        if (!end || (end.how === "progress" && s.state === "won")) {
          end = { how: ended.how, first: ms, unoffered: null, offered: null, actStarted: null,
                  acted: null, inputs: 0 };
        }
        if (advance && end.offered === null) end.offered = ms;
        else if (end.offered === null) end.unoffered = readMs;
        if (advance) await input(() => act(page, advance, touch));
        else if (s.state === "won") await input(() => retry(page, s, touch));
        await page.waitForTimeout(250);
        continue;
      }
      if (s.state === "lost") {
        if (unit) unit.lost = true;
        losses += 1;
        ended = { ms, how: "lost" };
        end = null;
        if (losses >= 2) {
          stopped = "lost twice";
          break;
        }
        await retry(page, s, touch);
        await page.waitForTimeout(250);
        continue;
      }
      if (cutAt === null && units.length >= CFG.max_units) {
        stopped = "max units";
        cutAt = ms;
        cutIndex = current;
        if (!kindsShort()) break;
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
  await finish(page, info, "traverse", { ...started, applies: true, snapshots, transitions,
                                        per_unit: units, unit_count_reported: unitCountReported, losses,
                                        stopped, ...(extendedMs ? { extended_ms: extendedMs } : {}),
                                        ...watch.record(), frames }, health);
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

// The oracle's inputs per third of one run of `duration` ms, from the input times in it.
function thirdsOf(inputs: number[], duration: number): number[] {
  const third = Math.max(1, duration / 3);
  const thirds = [0, 0, 0];
  for (const at of inputs) {
    const slot = Math.min(2, Math.floor(at / third));
    thirds[slot] = (thirds[slot] ?? 0) + 1;
  }
  return thirds;
}

type Run = { duration_ms: number; inputs: number; oracle_inputs_per_third: number[] };

// The oracle plays and retries at once for `windowMs`, run after run. Recorded: each run with
// the oracle's input rate per third of it, when the designed closing beat first arrived, and
// the difficulty in force in each window. The time ramp is not read here: the ramp test
// samples its own fresh runs (playSample).
async function playRuns(page: Page, watch: Watch, touch: boolean, windowMs: number) {
  const runs: Run[] = [];
  const windows: { at_ms: number; difficulty: Record<string, number> }[] = [];
  let beatAtMs: number | null = null;
  let endedOn = "window";
  const t0 = Date.now();
  const opening = watch.saw(await snap(page));
  let best = opening?.metrics?.best ?? null;
  let index = opening?.content?.unit_index ?? null;
  let runStart = Date.now();
  let inputs: number[] = [];
  let window = 0;
  const close = (): void => {
    const duration = Date.now() - runStart;
    runs.push({ duration_ms: duration, inputs: inputs.length,
                oracle_inputs_per_third: thirdsOf(inputs, duration) });
    inputs = [];
    runStart = Date.now();
  };
  for (;;) {
    if (Date.now() - t0 >= windowMs) break;
    const s = watch.saw(await snap(page));
    if (!s) break;
    const ms = Date.now() - t0;
    if (CFG.window_ms > 0 && ms >= (window + 1) * CFG.window_ms) {
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
  if (beatAtMs !== null && endedOn === "window") endedOn = "beat reached";
  return { runs, windows, lengthMs: Date.now() - t0, beatAtMs, endedOn };
}

type Sample = Run & { input_ms: number[]; longest_idle_ms: number; idle_at_ms: number | null;
                      ended: string };

// What a run has achieved, as far as the probe says: the design's goal metric, the unit's
// progress, the unit reached. A change in it is progress; the time it is read is not.
function achieved(s: Snapshot): string {
  return JSON.stringify([s.metrics?.[CFG.goal_metric] ?? null, s.content?.progress?.value ?? null,
                         s.content?.unit_index ?? null]);
}

// One sample of the time ramp: the run in play now, played by the oracle for `windowMs` or
// until the game ends it (no retry: a sample is one run). Recorded: the oracle's inputs per
// third and their times, and the longest stretch in play (state `playing`) with no oracle
// input and no progress (achieved) - a stall, depth.stall, when over ramp_stall_ms.
async function playSample(page: Page, watch: Watch, touch: boolean, windowMs: number): Promise<Sample> {
  const t0 = Date.now();
  const inputs: number[] = [];
  let active = t0;
  let longestIdle = 0;
  let idleAt: number | null = null;
  let last: string | null = null;
  let ended = "window";
  const idle = (now: number): void => {
    if (now - active > longestIdle) {
      longestIdle = now - active;
      idleAt = active - t0;
    }
  };
  while (Date.now() - t0 < windowMs) {
    const s = watch.saw(await snap(page));
    const now = Date.now();
    if (!s) {
      ended = "no snapshot";
      break;
    }
    if (s.state === "lost" || s.state === "won") {
      ended = s.state;
      break;
    }
    if (s.state !== "playing") {
      // Paused, between waves, an interstitial: not play, so not idle play either.
      active = now;
      await page.waitForTimeout(40);
      continue;
    }
    const mark = achieved(s);
    if (mark !== last) {
      last = mark;
      active = now;
    }
    idle(now);
    if (s.oracle) {
      await act(page, s.oracle, touch);
      inputs.push(Date.now() - t0);
      active = Date.now();
      await page.waitForTimeout(120);
    } else {
      await page.waitForTimeout(40);
    }
  }
  const duration = Date.now() - t0;
  if (ended === "window") idle(Date.now());
  return { duration_ms: duration, inputs: inputs.length,
           oracle_inputs_per_third: thirdsOf(inputs, duration), input_ms: inputs,
           longest_idle_ms: longestIdle, idle_at_ms: idleAt, ended };
}

// Whether the samples so far decide the ramp (analysis.ramp_verdict, which judges; this only
// says whether more samples could change the answer): a stall, a single sample's fall beyond
// its own band, or - with enough inputs - a pooled difference beyond the pooled band.
function rampDecided(samples: Sample[]): boolean {
  const z = CFG.ramp_noise_z ?? 0;
  const minimum = CFG.ramp_min_inputs ?? 0;
  if (samples.some((s) => s.longest_idle_ms > (CFG.ramp_stall_ms ?? Infinity))) return true;
  let first = 0;
  let last = 0;
  for (const s of samples) {
    const [a = 0, , c = 0] = s.oracle_inputs_per_third;
    if (a >= minimum && a - c > z * Math.sqrt(a + c)) return true;
    first += a;
    last += c;
  }
  return first >= minimum && Math.abs(last - first) > z * Math.sqrt(first + last);
}

// One first session, as the design designed it: the oracle plays and retries at once, and the
// session is held open to the design's own first-session length (playRuns).
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
  let played = { runs: [] as Run[], windows: [] as { at_ms: number; difficulty: Record<string, number> }[],
                 lengthMs: 0, beatAtMs: null as number | null, endedOn: "play never began" };
  if (started.playingMs !== null) {
    played = await playRuns(page, watch, touch, CFG.session_max_ms);
    await frame(page, project, "session-end", frames);
  }
  write(project, "session", { ...started, applies: true, length_ms: played.lengthMs,
                              beat_at_ms: played.beatAtMs, ended_on: played.endedOn,
                              runs: played.runs, windows: played.windows,
                              target_ms: CFG.session_target_ms, window_ms: CFG.window_ms,
                              ...watch.record(), frames });
});

// Enters `mode` through the probe's optional play.mode (only with wgf-probe=1): `modes()`
// lists the modes the build can be put in, `enter(mode)` puts the running game into a run
// of that mode, resolving true, or false when it cannot.
async function enterMode(page: Page, mode: string): Promise<{ offered: string[] | null; entered: boolean; reason: string | null }> {
  return await page.evaluate(async (wanted) => {
    const hook = (window as unknown as { __wgf__?: { play?: { mode?: { modes?(): unknown; enter?(m: string): unknown } } } })
      .__wgf__?.play?.mode;
    if (!hook || typeof hook.enter !== "function") {
      return { offered: null, entered: false, reason: "the probe declares no play.mode" };
    }
    let offered: string[] | null = null;
    try {
      const listed = typeof hook.modes === "function" ? hook.modes() : null;
      offered = Array.isArray(listed) ? listed.map(String) : null;
    } catch (e) {
      return { offered: null, entered: false, reason: `play.mode.modes() threw: ${String(e).slice(0, 200)}` };
    }
    if (offered && !offered.includes(wanted)) {
      return { offered, entered: false, reason: `play.mode.modes() does not offer "${wanted}"` };
    }
    try {
      const done = await hook.enter(wanted);
      return { offered, entered: done === true,
               reason: done === true ? null : `play.mode.enter("${wanted}") answered ${String(done)}` };
    } catch (e) {
      return { offered, entered: false, reason: `play.mode.enter threw: ${String(e).slice(0, 200)}` };
    }
  }, mode);
}

// The time ramp's samples (design-depth.yaml playability.ramp 1.4.0), when the design promises
// one (analysis.time_ramp): ramp_samples fresh runs - a fresh page each, and for a ramp read
// on a mode (an endless mode beside authored units) that mode entered through the probe's
// play.mode - each played by the oracle for ramp_ms or until the game ends it. While the
// samples do not decide the ramp (rampDecided), further whole samples are played within
// ramp_extend_ms. One run was a coin toss: the verdict is read on all of them, pooled.
test("ramp: samples of the play that promises the time ramp", async ({ page }, info) => {
  const health = new Health();
  const project = info.project.name;
  const frames: string[] = [];
  const watch = new Watch(page, project, frames);
  const run = CFG.ramp_run ?? null;
  const mode = run === "mode" ? CFG.ramp_mode ?? null : null;
  const planned = CFG.ramp_samples ?? 0;
  const windowMs = CFG.ramp_ms ?? 0;
  if (!run || (run === "mode" && !mode) || planned < 1 || windowMs <= 0) {
    write(project, "ramp", { applies: false, reason: "the design promises no time ramp" });
    return;
  }
  const extendMs = CFG.ramp_extend_ms ?? 0;
  const most = planned + Math.floor(extendMs / windowMs);
  test.setTimeout(most * (windowMs + CFG.start_timeout_ms + 5000) + 60_000);
  const touch = Boolean(info.project.use.hasTouch);
  const samples: Sample[] = [];
  let entry: { offered: string[] | null; entered: boolean; reason: string | null } | null = null;
  let reason: string | null = null;
  let extendedMs = 0;
  let extendFrom = 0;
  let firstStart: Record<string, unknown> | null = null;
  while (samples.length < most) {
    if (samples.length >= planned) {
      if (rampDecided(samples)) break;
      if (!extendFrom) extendFrom = Date.now();
      if (Date.now() - extendFrom + windowMs > extendMs) break;
    }
    // The page a sample played on is left for a fresh one: its health is read first.
    if (samples.length) await health.keep(page);
    const started = await start(page, touch, watch);
    if (firstStart === null) firstStart = started;
    if (started.playingMs === null) {
      reason = `sample ${samples.length + 1}: play never began`;
      break;
    }
    if (mode) {
      entry = await enterMode(page, mode);
      if (!entry.entered) {
        reason = `sample ${samples.length + 1}: ${entry.reason ?? "the mode was not entered"}`;
        break;
      }
      await page.waitForTimeout(300);
    }
    if (!samples.length) await frame(page, project, `ramp-${mode ?? "session"}-start`, frames);
    samples.push(await playSample(page, watch, touch, windowMs));
    if (extendFrom) extendedMs = Date.now() - extendFrom;
  }
  if (samples.length) await frame(page, project, `ramp-${mode ?? "session"}-end`, frames);
  // `entered`: the mode was entered for the samples played (a session ramp enters none); a
  // later entry that failed stops the sampling, with its `reason`.
  const entered = mode ? samples.length > 0 : null;
  // Made again on a degraded host like the other timing-sensitive recordings: a host stall
  // is an idle stretch depth.stall would read as play that stopped.
  await finish(page, info, "ramp", { ...(firstStart ?? {}), applies: true, run, mode,
                                     offered: entry?.offered ?? null, entered, reason,
                                     samples, planned_samples: planned, window_ms: windowMs,
                                     extended_ms: extendedMs, ...watch.record(), frames }, health);
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

// -- the survey -----------------------------------------------------------------------------

// The traverse plays the first units in order and stops; a release carries many more. The
// survey enters every unit the design lists directly, through the probe's unit link
// (`?wgf-probe=1&wgf-unit=<unit id>`, play-probe.schema.json), and lets the oracle play it for
// a bounded window: which unit the probe then reports, the entity kinds and assets drawn in
// it by role, the difficulty in force, and how long the oracle took to complete it. Recorded
// only; the content-sufficiency step counts it. A unit the probe never reports was not
// entered - the build does not honour the link, or does not carry that unit.
interface SurveyVisit {
  asked: string;
  entered: boolean;
  reported: string[];
  index: number | null;
  kinds_by_role: Record<string, string[]>;
  assets_by_role: Record<string, string[]>;
  content_entities: number;
  unkinded: number;
  difficulty: Record<string, number>;
  won: boolean;
  lost: boolean;
  duration_ms: number | null;
  playing_ms: number | null;
  reason?: string;
}

function addTo(map: Record<string, string[]>, key: string, value: string): void {
  const list = (map[key] ??= []);
  if (!list.includes(value)) list.push(value);
}

async function surveyUnit(page: Page, id: string, touch: boolean, watch: Watch, project: string,
                          frames: string[]): Promise<SurveyVisit> {
  const started = await start(page, touch, watch, false, `${URL}&wgf-unit=${encodeURIComponent(id)}`);
  const visit: SurveyVisit = { asked: id, entered: false, reported: [], index: null,
                               kinds_by_role: {}, assets_by_role: {}, content_entities: 0,
                               unkinded: 0, difficulty: {}, won: false, lost: false,
                               duration_ms: null, playing_ms: started.playingMs };
  if (started.playingMs === null) {
    visit.reason = "play never began";
    return visit;
  }
  const kindRoles = new Set(CFG.kind_roles ?? []);
  const u0 = Date.now();
  let shot = false;
  let samples = 0;
  while (Date.now() - u0 < (CFG.survey_unit_ms ?? 0)) {
    const s = watch.saw(await snap(page));
    if (!s) break;
    const uid = s.content?.unit_id ?? null;
    if (uid && !visit.reported.includes(uid)) visit.reported.push(uid);
    if (uid !== id) {
      // Left the unit (it advanced on its own), or never in it.
      if (visit.entered) break;
    } else {
      visit.entered = true;
      visit.index = s.content?.unit_index ?? visit.index;
      Object.assign(visit.difficulty, difficultyOf(s));
      // A bounded number of samples count entities: the kinds and assets are a union.
      const counting = samples < 40;
      samples += 1;
      for (const entity of s.entities ?? []) {
        if (!entity.visible) continue;
        if (entity.kind) addTo(visit.kinds_by_role, entity.role, entity.kind);
        if (entity.asset) addTo(visit.assets_by_role, entity.role, entity.asset);
        if (counting && kindRoles.has(entity.role)) {
          visit.content_entities += 1;
          if (!entity.kind) visit.unkinded += 1;
        }
      }
      if (!shot && Date.now() - u0 > 1000) {
        await frame(page, project, `survey-${id}-1s`, frames);
        shot = true;
      }
    }
    if (s.state === "won" || progressDone(s)) {
      if (uid === id) {
        visit.won = true;
        visit.duration_ms = Date.now() - u0;
      }
      break;
    }
    if (s.state === "lost") {
      visit.lost = true;
      break;
    }
    if (s.oracle) {
      await act(page, s.oracle, touch);
      await page.waitForTimeout(120);
    } else {
      await page.waitForTimeout(40);
    }
  }
  if (!visit.entered) {
    visit.reason = visit.reported.length
      ? `the probe reported ${visit.reported.join(", ")}, not ${id}`
      : "the probe reported no unit";
  }
  return visit;
}

test("survey: every unit the design lists, entered through the probe's unit link", async ({ page }, info) => {
  const project = info.project.name;
  const units = CFG.survey_units ?? [];
  if (!units.length || !(CFG.survey_projects ?? []).includes(project)) {
    write(project, "survey", { applies: false, reason: units.length
      ? `units are surveyed on ${(CFG.survey_projects ?? []).join(", ") || "no project"} only`
      : "no survey was asked for (the step's `with: survey`, a design with authored units)" });
    return;
  }
  // The survey's own window, beside the per-test timeout every other test shares.
  test.setTimeout((CFG.survey_ms ?? 0) + units.length * (CFG.start_timeout_ms + 2000) + 60_000);
  const frames: string[] = [];
  const watch = new Watch(page, project, frames);
  const touch = Boolean(info.project.use.hasTouch);
  const visits: SurveyVisit[] = [];
  const t0 = Date.now();
  for (const id of units) {
    if (Date.now() - t0 > (CFG.survey_ms ?? 0)) {
      visits.push({ asked: id, entered: false, reported: [], index: null, kinds_by_role: {},
                    assets_by_role: {}, content_entities: 0, unkinded: 0, difficulty: {},
                    won: false, lost: false, duration_ms: null, playing_ms: null,
                    reason: "survey window spent" });
      continue;
    }
    visits.push(await surveyUnit(page, id, touch, watch, project, frames));
  }
  write(project, "survey", { applies: true, asked: units, visits, ...watch.record(), frames });
});
