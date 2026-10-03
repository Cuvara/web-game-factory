// The store-listing capture: screenshots, a gameplay recording and the branding composition,
// taken from a built game served locally, through its play probe.
//
// Run by the Factory's store-listing step (scripts/wgf_listing/capture.py) with the GAME
// REPOSITORY as its working directory - Playwright is resolved from the game's own
// node_modules through createRequire, so nothing is copied into the checkout - and one JSON
// job file as its only argument. It drives the game exactly as the playability bot does
// (scripts/wgf_playability/bot.spec.ts): the probe `window.__wgf__.play.snapshot()` is read,
// never acted through; every input is a real pointer, touch or key event; the oracle (only
// with `?wgf-probe=1`) plays well. It judges nothing: it writes what it saw to <out>/
// capture.json - per viewport the frame of each scene with the probe state at that moment,
// the recording with how many milliseconds precede play, the branding images - and the
// Python side decides what is a screenshot.
//
// Factory tooling: it contains no game, and is not part of one.

import { createRequire } from "node:module";
import * as fs from "node:fs";
import * as path from "node:path";
import { spawnSync } from "node:child_process";

const jobPath = process.argv[2];
if (!jobPath) {
  console.error("usage: node capture.mjs <job.json>");
  process.exit(2);
}
const job = JSON.parse(fs.readFileSync(jobPath, "utf8"));
const require = createRequire(path.join(process.cwd(), "package.json"));
let pw;
try {
  pw = require("@playwright/test");
} catch (error) {
  fs.mkdirSync(job.out, { recursive: true });
  fs.writeFileSync(path.join(job.out, "capture.json"), JSON.stringify({
    error: `no-playwright: ${String(error.message).slice(0, 200)}`,
  }, null, 1));
  console.error(`[capture] @playwright/test is not resolvable from ${process.cwd()}`);
  process.exit(3);
}
const { chromium, devices } = pw;

const GL = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"];
// The Factory's refusing proxy, handed to the browser itself: Chromium ignores the proxy
// environment variables everywhere but Linux (wgflib.netguard). capture.py reads `proxied`.
const PROXY_SERVER = process.env.WGF_BROWSER_PROXY;
const PROXY = PROXY_SERVER ? { proxy: { server: PROXY_SERVER, bypass: "localhost,127.0.0.1,[::1]" } } : {};
const PROBE_URL = "/?wgf-probe=1";
const BEGIN = /^(play|start|begin|tap-to-start|continue)$/i;
const UTILITY = /pause|resume|menu|settings|sound|mute|music|fullscreen/i;
const settings = Object.assign({
  start_timeout_ms: 30000, play_ms: 20000, input_pause_ms: 120, settle_ms: 400,
  excluded_states: ["loading", "other"],
}, job.settings ?? {});

fs.mkdirSync(job.out, { recursive: true });
const result = { browser: null, proxied: Boolean(PROXY_SERVER), viewports: [], trailer: null, branding: [], derived: [], ffmpeg: null, errors: [] };
const log = (line) => process.stdout.write(`[capture] ${line}\n`);

function snap(page) {
  return page.evaluate(() => {
    const play = window.__wgf__?.play;
    try {
      return play && typeof play.snapshot === "function" ? play.snapshot() : null;
    } catch (error) {
      return { error: String(error) };
    }
  });
}

async function settle(page, maxMs) {
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

async function act(page, move, touch) {
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

// Open the game as a first session; press its begin input when the title screen offers one.
// `onTitle` is called once with the page on the title screen, before anything is pressed.
async function start(page, touch, onTitle) {
  const t0 = Date.now();
  await page.goto(PROBE_URL, { waitUntil: "domcontentloaded" });
  let pressedAt = 0;
  let began = null;
  let titleSeen = false;
  let firstSnapshotMs = null;
  while (Date.now() - t0 < settings.start_timeout_ms) {
    const s = await snap(page);
    if (s && firstSnapshotMs === null) firstSnapshotMs = Date.now() - t0;
    if (s?.state === "playing") return { playingMs: Date.now() - t0, began, firstSnapshotMs, probe: Boolean(s) };
    if (s?.state === "title" && !titleSeen && onTitle) {
      titleSeen = true;
      await onTitle(page, s);
    }
    const begin = s && s.state !== "loading" ? s.inputs?.find((m) => BEGIN.test(m.action)) : undefined;
    if (begin && Date.now() - pressedAt > 1000) {
      await act(page, begin, touch);
      began = begin.action;
      pressedAt = Date.now();
    }
    await page.waitForTimeout(50);
  }
  return { playingMs: null, began, firstSnapshotMs, probe: firstSnapshotMs !== null };
}

async function frame(page, dir, id) {
  const file = path.join(dir, `${id}.png`);
  await page.screenshot({ path: file });
  return file;
}

// Oracle-driven play for `ms`, calling `onTick(elapsedMs, inputs, snapshot)` between moves.
async function play(page, touch, ms, onTick) {
  const t0 = Date.now();
  let inputs = 0;
  let reached = null;
  while (Date.now() - t0 < ms) {
    const s = await snap(page);
    if (!s) break;
    if (s.state === "won" || s.state === "lost") {
      reached = s.state;
      break;
    }
    if (onTick) await onTick(Date.now() - t0, inputs, s);
    if (s.oracle) {
      await act(page, s.oracle, touch);
      inputs += 1;
      await page.waitForTimeout(settings.input_pause_ms);
    } else {
      await page.waitForTimeout(40);
    }
  }
  return { reached, inputs, playedMs: Date.now() - t0 };
}

async function captureViewport(browser, viewport) {
  const dir = path.join(job.out, viewport.id);
  fs.mkdirSync(dir, { recursive: true });
  const options = viewport.mobile
    ? { ...devices["Pixel 5"], viewport: { width: viewport.width, height: viewport.height }, deviceScaleFactor: 1, baseURL: job.base_url }
    : { ...devices["Desktop Chrome"], viewport: { width: viewport.width, height: viewport.height }, deviceScaleFactor: 1, baseURL: job.base_url };
  const context = await browser.newContext(options);
  const page = await context.newPage();
  const record = { id: viewport.id, width: viewport.width, height: viewport.height, mobile: Boolean(viewport.mobile),
                   ran: false, errors: [], shots: [], start: null, play: null };
  page.on("pageerror", (e) => record.errors.push(String(e.message).slice(0, 300)));
  const touch = Boolean(viewport.mobile);
  const shots = record.shots;
  const scenes = job.scenes ?? [];
  const taken = new Set();
  const shoot = async (scene, s, extra = {}) => {
    if (taken.has(scene.id)) return;
    const states = Array.isArray(scene.state) ? scene.state : [scene.state];
    const state = s?.state ?? null;
    if (!states.includes(state)) return;
    taken.add(scene.id);
    await settle(page, settings.settle_ms);
    const after = await snap(page);
    const file = await frame(page, dir, scene.id);
    shots.push({ scene: scene.id, file, state: after?.state ?? state, probe_state_before: state,
                 excluded: settings.excluded_states.includes(after?.state ?? state), ...extra });
  };
  try {
    const titleScene = scenes.find((sc) => (Array.isArray(sc.state) ? sc.state : [sc.state]).includes("title"));
    record.start = await start(page, touch, titleScene ? (p, s) => shoot(titleScene, s) : null);
    record.ran = record.start.probe;
    if (record.start.playingMs !== null) {
      // A play scene is due once every condition it states holds: after_ms, after_inputs.
      const during = scenes.filter((sc) => !Array.isArray(sc.state)
        && (sc.after_ms !== undefined || sc.after_inputs !== undefined));
      record.play = await play(page, touch, settings.play_ms, async (elapsed, inputs, s) => {
        for (const sc of during) {
          const due = (sc.after_ms === undefined || elapsed >= sc.after_ms)
            && (sc.after_inputs === undefined || inputs >= sc.after_inputs);
          if (due) await shoot(sc, s, { elapsed_ms: elapsed, inputs });
        }
      });
      const resultScene = scenes.find((sc) => Array.isArray(sc.state));
      if (record.play.reached && resultScene) {
        await page.waitForTimeout(settings.settle_ms);
        await shoot(resultScene, await snap(page), { elapsed_ms: record.play.playedMs, inputs: record.play.inputs });
      }
    }
  } catch (error) {
    record.errors.push(`capture: ${String(error.message).slice(0, 300)}`);
  } finally {
    await context.close();
  }
  result.viewports.push(record);
  log(`${viewport.id}: ${shots.length} frame(s), play ${record.play ? record.play.playedMs + "ms" : "not started"}`);
}

function findFfmpeg() {
  try {
    const { registry } = require("playwright-core/lib/server/registry/index");
    const executable = registry.findExecutable("ffmpeg")?.executablePath();
    if (executable && fs.existsSync(executable)) return executable;
  } catch { /* not exported by this version: fall through */ }
  const roots = [process.env.PLAYWRIGHT_BROWSERS_PATH];
  if (process.platform === "win32") roots.push(path.join(process.env.LOCALAPPDATA ?? "", "ms-playwright"));
  else if (process.platform === "darwin") roots.push(path.join(process.env.HOME ?? "", "Library", "Caches", "ms-playwright"));
  else roots.push(path.join(process.env.HOME ?? "", ".cache", "ms-playwright"));
  for (const root of roots.filter(Boolean)) {
    if (!fs.existsSync(root)) continue;
    for (const entry of fs.readdirSync(root).filter((n) => n.startsWith("ffmpeg-")).sort().reverse()) {
      const dir = path.join(root, entry);
      const bin = fs.readdirSync(dir).find((n) => n.startsWith("ffmpeg"));
      if (bin) return path.join(dir, bin);
    }
  }
  return null;
}

function ffmpegEncoders(ffmpeg) {
  const done = spawnSync(ffmpeg, ["-hide_banner", "-encoders"], { encoding: "utf8", timeout: 20000 });
  return done.status === 0 ? done.stdout : "";
}

async function recordTrailer(browser, spec) {
  const dir = path.join(job.out, "trailer");
  fs.mkdirSync(dir, { recursive: true });
  const size = { width: spec.width, height: spec.height };
  const context = await browser.newContext({
    ...devices["Desktop Chrome"], viewport: size, deviceScaleFactor: 1, baseURL: job.base_url,
    recordVideo: { dir, size },
  });
  const page = await context.newPage();
  const record = { enabled: true, raw: null, file: null, leading_ms: null, played_ms: null, reached: null,
                   inputs: 0, trimmed: false, derived: [], errors: [], width: spec.width, height: spec.height };
  page.on("pageerror", (e) => record.errors.push(String(e.message).slice(0, 300)));
  const opened = Date.now();
  let videoPath = null;
  try {
    const started = await start(page, false, null);
    if (started.playingMs !== null) {
      record.leading_ms = Date.now() - opened;
      const played = await play(page, false, spec.seconds * 1000, null);
      record.played_ms = played.playedMs;
      record.reached = played.reached;
      record.inputs = played.inputs;
      // Hold the result screen a moment so the recording ends on it, not mid-fade.
      if (played.reached) await page.waitForTimeout(1200);
    } else {
      record.errors.push("play never began: nothing to record");
    }
    videoPath = await page.video()?.path();
  } catch (error) {
    record.errors.push(`trailer: ${String(error.message).slice(0, 300)}`);
  } finally {
    await context.close(); // the video is finalised on close
  }
  if (videoPath && fs.existsSync(videoPath)) {
    const raw = path.join(dir, "raw.webm");
    fs.renameSync(videoPath, raw);
    record.raw = raw;
    const ffmpeg = findFfmpeg();
    result.ffmpeg = ffmpeg;
    if (ffmpeg && record.leading_ms !== null) {
      const out = path.join(dir, "trailer.webm");
      const lead = Math.max(0, record.leading_ms - 200) / 1000;
      const duration = Math.max(1, (record.played_ms ?? spec.seconds * 1000) / 1000 + (record.reached ? 1.2 : 0));
      const args = ["-y", "-hide_banner", "-loglevel", "error", "-ss", lead.toFixed(3), "-i", raw,
                    "-t", duration.toFixed(3), "-c:v", "libvpx", "-b:v", "2M", "-crf", "10", "-an", out];
      const done = spawnSync(ffmpeg, args, { encoding: "utf8", timeout: 300000 });
      if (done.status === 0 && fs.existsSync(out)) {
        record.file = out;
        record.trimmed = true;
        const encoders = ffmpegEncoders(ffmpeg);
        if (/\blibx264\b/.test(encoders)) {
          const mp4 = path.join(dir, "trailer.mp4");
          const conv = spawnSync(ffmpeg, ["-y", "-hide_banner", "-loglevel", "error", "-i", out, "-c:v", "libx264",
                                          "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", mp4],
                                 { encoding: "utf8", timeout: 300000 });
          if (conv.status === 0 && fs.existsSync(mp4)) record.derived.push({ format: "mp4", file: mp4 });
          else record.errors.push(`mp4 encode failed: ${(conv.stderr || "").slice(0, 200)}`);
        } else {
          record.errors.push("no mp4 encoder (libx264) in the bundled ffmpeg");
        }
      } else {
        record.errors.push(`ffmpeg trim failed: ${(done.stderr || done.error?.message || "").slice(0, 200)}`);
        record.file = raw;
      }
    } else {
      record.file = raw;
      if (!ffmpeg) record.errors.push("no ffmpeg: the recording is kept untrimmed");
    }
  }
  result.trailer = record;
  log(`trailer: ${record.file ? path.basename(record.file) : "none"}${record.trimmed ? " (trimmed)" : ""}`);
}

async function composeBranding(browser, spec) {
  const dir = path.join(job.out, "branding");
  fs.mkdirSync(dir, { recursive: true });
  const context = await browser.newContext({ viewport: { width: spec.page_width, height: spec.page_height }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e.message).slice(0, 300)));
  try {
    await page.goto(spec.url, { waitUntil: "load" });
    await page.evaluate(() => document.fonts ? document.fonts.ready : null);
    await page.waitForTimeout(300);
    for (const shot of spec.shots) {
      const box = await page.locator(shot.selector).boundingBox();
      if (!box) {
        errors.push(`branding: ${shot.selector} not found`);
        continue;
      }
      const file = path.join(dir, `${shot.id}.png`);
      await page.screenshot({ path: file, clip: { x: box.x, y: box.y, width: shot.width, height: shot.height },
                              omitBackground: Boolean(shot.transparent) });
      result.branding.push({ id: shot.id, file, width: shot.width, height: shot.height, source: shot.source ?? null });
    }
  } catch (error) {
    errors.push(`branding: ${String(error.message).slice(0, 300)}`);
  } finally {
    await context.close();
  }
  if (errors.length) result.errors.push(...errors);
  log(`branding: ${result.branding.length} image(s)`);
}

// Re-encode PNGs as JPEG or WebP with the browser's encoder (nothing in the Factory's own
// Python writes those formats).
async function derive(browser, jobs) {
  const context = await browser.newContext({ viewport: { width: 64, height: 64 } });
  const page = await context.newPage();
  try {
    await page.setContent("<!doctype html><canvas id=c></canvas>");
    for (const d of jobs) {
      try {
        const data = fs.readFileSync(d.source).toString("base64");
        const url = await page.evaluate(async ({ b64, width, height, format, quality }) => {
          const img = new Image();
          await new Promise((resolve, reject) => { img.onload = resolve; img.onerror = reject; img.src = "data:image/png;base64," + b64; });
          const canvas = document.getElementById("c");
          canvas.width = width; canvas.height = height;
          const ctx = canvas.getContext("2d");
          ctx.drawImage(img, 0, 0, width, height);
          return canvas.toDataURL(format === "jpg" ? "image/jpeg" : "image/webp", quality);
        }, { b64: data, width: d.width, height: d.height, format: d.format, quality: d.quality ?? 0.9 });
        const bytes = Buffer.from(url.split(",")[1], "base64");
        fs.mkdirSync(path.dirname(d.out), { recursive: true });
        fs.writeFileSync(d.out, bytes);
        result.derived.push({ id: d.id, out: d.out, format: d.format, bytes: bytes.length });
      } catch (error) {
        result.errors.push(`derive ${d.id}: ${String(error.message).slice(0, 200)}`);
      }
    }
  } finally {
    await context.close();
  }
}

async function main() {
  const browser = await chromium.launch({ args: GL, ...PROXY });
  result.browser = `chromium ${browser.version()}`;
  try {
    for (const viewport of job.viewports ?? []) await captureViewport(browser, viewport);
    if (job.trailer?.enabled) await recordTrailer(browser, job.trailer);
    if (job.branding) await composeBranding(browser, job.branding);
    if (job.derive?.length) await derive(browser, job.derive);
  } finally {
    await browser.close();
  }
}

main()
  .catch((error) => {
    result.errors.push(`fatal: ${String(error.stack || error.message).slice(0, 600)}`);
    process.exitCode = 1;
  })
  .finally(() => {
    fs.writeFileSync(path.join(job.out, "capture.json"), JSON.stringify(result, null, 1));
  });
