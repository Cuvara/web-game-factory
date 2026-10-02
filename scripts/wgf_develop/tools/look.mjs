#!/usr/bin/env node
// Look at the built game: the frames a first-time player sees, for the developer to read.
//
//     node look.mjs --out <directory> [--repo <game repository>] [--actions <list>]
//                   [--viewports desktop,mobile] [--settle-ms 2500]
//
// Run by a developer from the game checkout, after `pnpm build`, with the Playwright the game
// repository itself installs (its e2e tests use it): `pnpm exec node <this file> --out
// /tmp/wgf-look/<name>`. It serves dist/ on a free localhost port with a small static server
// of its own, opens it in headless Chromium (software WebGL, so a 3D scene renders without a
// GPU) and, per viewport, saves:
//
//     <viewport>-1-title.png    after load and the settle time - the first thing seen
//     <viewport>-2-play.png     after the actions (default: a tap in the centre, Space,
//                               Enter - whatever begins play) and the settle time
//     <viewport>-3-play-later.png   three seconds of play later
//
// and look.json: every frame's path, page errors, console errors, failed /assets/ requests,
// and the play probe's snapshot (window.__wgf__.play.snapshot()) after each frame when the
// game exposes one. The frames are images: open them with your file-reading tool and judge
// them against the design's visual identity and the quality bar. Nothing here judges them.
//
// --burst <actions> performs those actions once more during play and saves six frames 80 ms
// apart (<viewport>-burst-0..5.png): what a player sees in the half second after an input.
//
// --actions is a comma list of `wait:<ms>`, `key:<Key>`, `click:<x>x<y>` (fractions of the
// viewport, e.g. click:0.5x0.6) and `hold:<Key>:<ms>`. Exit 2 when the repository has no
// dist/ or no Playwright; the frames are written outside the repository (--out is refused
// inside it), so nothing here changes what the development commit contains.

import { createRequire } from "node:module";
import { createServer } from "node:http";
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { extname, join, resolve, sep } from "node:path";

function args(argv) {
  const out = { repo: process.cwd(), viewports: "desktop,mobile", settle: 2500,
                actions: "click:0.5x0.6,key:Space,key:Enter" };
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    const value = argv[i + 1];
    if (key === "--out") out.out = value;
    else if (key === "--repo") out.repo = value;
    else if (key === "--actions") out.actions = value;
    else if (key === "--viewports") out.viewports = value;
    else if (key === "--settle-ms") out.settle = Number(value);
    else if (key === "--burst") out.burst = value;
    else continue;
    i += 1;
  }
  return out;
}

const MIME = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript",
  ".css": "text/css", ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml", ".gif": "image/gif",
  ".glb": "model/gltf-binary", ".gltf": "model/gltf+json", ".bin": "application/octet-stream",
  ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf",
  ".ogg": "audio/ogg", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav",
  ".wasm": "application/wasm", ".ktx2": "image/ktx2", ".map": "application/json",
};

function serve(root) {
  const server = createServer((request, response) => {
    const url = new URL(request.url, "http://localhost");
    let path = resolve(join(root, decodeURIComponent(url.pathname)));
    if (path !== root && !path.startsWith(root + sep)) {
      response.writeHead(403).end();
      return;
    }
    if (existsSync(path) && statSync(path).isDirectory()) path = join(path, "index.html");
    if (!existsSync(path)) {
      response.writeHead(404).end();
      return;
    }
    response.writeHead(200, { "content-type": MIME[extname(path).toLowerCase()] ||
                                              "application/octet-stream" });
    response.end(readFileSync(path));
  });
  return new Promise((done) => server.listen(0, "127.0.0.1", () => done(server)));
}

async function act(page, viewport, list) {
  for (const raw of list.split(",").map((s) => s.trim()).filter(Boolean)) {
    const [kind, a, b] = raw.split(":");
    if (kind === "wait") await page.waitForTimeout(Number(a));
    else if (kind === "key") await page.keyboard.press(a);
    else if (kind === "hold") {
      await page.keyboard.down(a);
      await page.waitForTimeout(Number(b));
      await page.keyboard.up(a);
    } else if (kind === "click") {
      const [fx, fy] = a.split("x").map(Number);
      const x = Math.round(fx * viewport.width);
      const y = Math.round(fy * viewport.height);
      if (viewport.touch) await page.touchscreen.tap(x, y);
      else await page.mouse.click(x, y);
    }
    await page.waitForTimeout(120);
  }
}

async function snapshot(page) {
  try {
    return await page.evaluate(() => {
      const play = globalThis.__wgf__ && globalThis.__wgf__.play;
      return play && typeof play.snapshot === "function" ? play.snapshot() : null;
    });
  } catch (error) {
    return { error: String(error) };
  }
}

async function main() {
  const opts = args(process.argv.slice(2));
  const repo = resolve(opts.repo);
  const dist = join(repo, "dist");
  if (!opts.out) {
    console.error("look.mjs: --out <directory> is required (outside the repository)");
    process.exit(2);
  }
  const out = resolve(opts.out);
  if (out === repo || out.startsWith(repo + sep)) {
    console.error("look.mjs: --out must be outside the repository: frames are not commit content");
    process.exit(2);
  }
  if (!existsSync(join(dist, "index.html"))) {
    console.error("look.mjs: no dist/index.html - run `pnpm build` first");
    process.exit(2);
  }
  let playwright;
  try {
    playwright = createRequire(join(repo, "package.json"))("@playwright/test");
  } catch (error) {
    console.error(`look.mjs: the repository installs no @playwright/test (${error.message})`);
    process.exit(2);
  }
  mkdirSync(out, { recursive: true });
  const server = await serve(dist);
  const base = `http://127.0.0.1:${server.address().port}/`;
  const browser = await playwright.chromium.launch({
    args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
           "--autoplay-policy=no-user-gesture-required"],
  });
  const VIEWPORTS = {
    desktop: { width: 1280, height: 720, touch: false },
    mobile: { width: 390, height: 844, touch: true },
  };
  const result = { url: base, frames: [], viewports: {} };
  try {
    for (const name of opts.viewports.split(",").map((s) => s.trim()).filter(Boolean)) {
      const viewport = VIEWPORTS[name];
      if (!viewport) continue;
      const context = await browser.newContext({
        viewport: { width: viewport.width, height: viewport.height },
        hasTouch: viewport.touch, isMobile: viewport.touch,
        deviceScaleFactor: viewport.touch ? 2 : 1,
      });
      const page = await context.newPage();
      const record = { page_errors: [], console_errors: [], failed_assets: [], snapshots: {} };
      page.on("pageerror", (error) => record.page_errors.push(String(error)));
      page.on("console", (message) => {
        if (message.type() === "error") record.console_errors.push(message.text());
      });
      page.on("response", (response) => {
        if (response.url().includes("/assets/") && response.status() >= 400) {
          record.failed_assets.push(`${response.status()} ${response.url()}`);
        }
      });
      page.on("requestfailed", (request) => {
        if (request.url().includes("/assets/")) record.failed_assets.push(`failed ${request.url()}`);
      });
      const shoot = async (label) => {
        const path = join(out, `${name}-${label}.png`);
        await page.screenshot({ path });
        result.frames.push(path);
        record.snapshots[label] = await snapshot(page);
      };
      await page.goto(base, { waitUntil: "load" });
      await page.waitForTimeout(opts.settle);
      await shoot("1-title");
      await act(page, viewport, opts.actions);
      await page.waitForTimeout(opts.settle);
      await shoot("2-play");
      if (opts.burst) {
        // Feel is motion: the frames right after one more input show whether the game
        // answers it (a squash, a pop, a flash, a number that rolls) or only changes state.
        await act(page, viewport, opts.burst);
        for (let i = 0; i < 6; i += 1) {
          await shoot(`burst-${i}`);
          await page.waitForTimeout(80);
        }
      }
      await page.waitForTimeout(3000);
      await shoot("3-play-later");
      result.viewports[name] = record;
      await context.close();
    }
  } finally {
    await browser.close();
    server.close();
  }
  writeFileSync(join(out, "look.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ frames: result.frames, summary: join(out, "look.json"),
                               errors: Object.fromEntries(Object.entries(result.viewports)
                                 .map(([k, v]) => [k, v.page_errors.length + v.failed_assets.length])) },
                             null, 2));
}

main().catch((error) => {
  console.error(`look.mjs: ${error.stack || error}`);
  process.exit(1);
});
