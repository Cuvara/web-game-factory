#!/usr/bin/env node
// Render a set of SVG drawings to PNG and compose a contact sheet, for an author to look at.
//
//     node render-svgs.mjs <render.json>
//
// Run by wgf_assets.preview (through wgflib.procs) with the Playwright the game repository
// installs: the job's `checkout` is where @playwright/test (or playwright) is resolved from,
// as look.mjs and seam-calls.mjs do. Nothing is served and nothing is fetched: each drawing is
// read from disk and shown as a data: URL in an <img>, the way the game draws an SVG - as an
// image, so it cannot load the game's web fonts either.
//
// The job (written by preview.py):
//   { checkout, out, title, background, surface, small, max_cell,
//     items: [{ id, requirement, path, width, height, role, problems }] }
// Writes, under `out`:
//   sheet.png      every drawing at its in-game size on the design's background (scaled down
//                  to `max_cell` when larger, and labelled so), then every drawing small
//                  (`small` px) on the background and on the panel surface, then the
//                  silhouettes (each drawing filled black) of every counted requirement
//   <id>.png       each drawing alone at its in-game size, on the background
//   render.json    { sheet, files: {id: png}, missing: [id], errors: [text] }
// Exit 2 when the checkout has no Playwright; 1 on a render failure.

import { createRequire } from "node:module";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

function esc(text) {
  return String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;",
                                                     '"': "&quot;" })[c]);
}

function loadPlaywright(checkout) {
  const req = createRequire(join(resolve(checkout), "package.json"));
  for (const name of ["@playwright/test", "playwright"]) {
    try {
      return req(name);
    } catch (error) {
      // try the next
    }
  }
  return null;
}

function fit(item, max) {
  const w = Number(item.width) || 0;
  const h = Number(item.height) || 0;
  if (!w || !h) return { w: 0, h: 0, scale: 1 };
  const scale = Math.min(1, max / Math.max(w, h));
  return { w: Math.round(w * scale), h: Math.round(h * scale), scale };
}

function page(job, data) {
  const bg = job.background || "#808080";
  const surface = job.surface || "#ffffff";
  const max = Number(job.max_cell) || 320;
  const small = Number(job.small) || 40;
  const cells = [];
  const smalls = [];
  const silhouettes = {};
  for (const item of job.items) {
    const src = data[item.id];
    const size = fit(item, max);
    // No in-game size stated: the drawing's own, never larger than a cell.
    const sizeAttr = size.w ? `width="${size.w}" height="${size.h}"`
      : `style="max-width:${max}px;max-height:${max}px"`;
    const scaled = size.scale < 1 ? ` (shown x${size.scale.toFixed(2)})` : "";
    const bad = item.problems ? `<b class="bad">${item.problems} problem(s)</b>` : "";
    const body = src
      ? `<img id="img-${esc(item.id)}" src="${src}" ${sizeAttr}>`
      : `<div class="missing" style="width:${size.w || 96}px;height:${size.h || 96}px">missing</div>`;
    cells.push(`<figure>${body}<figcaption>${esc(item.id)} ${item.width || "?"}x${item.height || "?"}`
               + `${scaled} ${bad}</figcaption></figure>`);
    if (src && item.role !== "background") {
      smalls.push(`<figure class="small"><div style="background:${bg}"><img src="${src}" `
                  + `style="max-width:${small}px;max-height:${small}px"></div><div style="background:${surface}">`
                  + `<img src="${src}" style="max-width:${small}px;max-height:${small}px"></div>`
                  + `<figcaption>${esc(item.id)}</figcaption></figure>`);
    }
    if (src && item.count > 1) {
      (silhouettes[item.requirement] = silhouettes[item.requirement] || []).push(
        `<figure><img class="sil" src="${src}" style="max-width:${Math.min(96, size.w || 96)}px;`
        + `max-height:${Math.min(96, size.h || 96)}px"><figcaption>${esc(item.id)}</figcaption></figure>`);
    }
  }
  const silRows = Object.entries(silhouettes).map(([req, figs]) =>
    `<h3>${esc(req)}: silhouettes (filled black - variants must still differ)</h3><div class="row light">${figs.join("")}</div>`);
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    body { margin: 0; padding: 16px; background: ${bg}; font: 13px/1.3 monospace; color: #fff; }
    h2, h3 { margin: 18px 0 8px; padding: 3px 6px; background: rgba(0,0,0,.7); color: #fff; display: inline-block; font: bold 14px sans-serif; }
    .row { display: flex; flex-wrap: wrap; gap: 18px; align-items: flex-end; }
    .light { background: #f2f2f2; padding: 10px; color: #222; }
    figure { margin: 0; display: flex; flex-direction: column; align-items: center; gap: 4px; }
    figcaption { background: rgba(0,0,0,.55); color: #fff; padding: 1px 4px; }
    .light figcaption { background: none; color: #222; }
    .bad { color: #ff6b6b; }
    .missing { border: 2px dashed #f55; display: flex; align-items: center; justify-content: center; }
    .small div { padding: 6px; display: inline-flex; }
    .sil { filter: brightness(0); }
  </style></head><body>
  <h2>${esc(job.title || "Asset set")} - in-game size on the background ${esc(bg)}</h2>
  <div class="row">${cells.join("")}</div>
  <h2>Small (${small}px) on the background and on the panel surface ${esc(surface)}</h2>
  <div class="row">${smalls.join("")}</div>
  ${silRows.join("")}
  </body></html>`;
}

async function main() {
  const jobPath = process.argv[2];
  if (!jobPath) {
    console.error("render-svgs.mjs: usage: node render-svgs.mjs <render.json>");
    process.exit(2);
  }
  const job = JSON.parse(readFileSync(jobPath, "utf8"));
  const playwright = loadPlaywright(job.checkout || process.cwd());
  if (!playwright) {
    console.error(`render-svgs.mjs: ${job.checkout} installs no @playwright/test or playwright`);
    process.exit(2);
  }
  const out = resolve(job.out);
  mkdirSync(out, { recursive: true });
  const data = {};
  const missing = [];
  for (const item of job.items) {
    if (item.path && existsSync(item.path)) {
      data[item.id] = "data:image/svg+xml;base64," + readFileSync(item.path).toString("base64");
    } else {
      missing.push(item.id);
    }
  }
  const result = { sheet: null, files: {}, missing, errors: [] };
  const browser = await playwright.chromium.launch();
  try {
    const context = await browser.newContext({ viewport: { width: Number(job.page_width) || 1400,
                                                           height: 900 } });
    const tab = await context.newPage();
    tab.on("pageerror", (error) => result.errors.push(String(error)));
    await tab.setContent(page(job, data), { waitUntil: "load" });
    await tab.evaluate(() => Promise.all([...document.images].map((img) =>
      img.decode().catch(() => null))));
    for (const item of job.items) {
      if (!data[item.id]) continue;
      const element = await tab.$(`[id="img-${item.id}"]`);
      if (!element) continue;
      const broken = await element.evaluate((img) => !img.naturalWidth);
      if (broken) {
        result.errors.push(`${item.id}: the browser could not draw this SVG`);
        continue;
      }
      const file = join(out, `${item.id}.png`);
      await element.screenshot({ path: file });
      result.files[item.id] = file;
    }
    const sheet = join(out, "sheet.png");
    await tab.screenshot({ path: sheet, fullPage: true });
    result.sheet = sheet;
  } catch (error) {
    result.errors.push(String(error && error.message ? error.message : error));
  } finally {
    await browser.close();
  }
  writeFileSync(join(out, "render.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
  process.exit(result.sheet ? 0 : 1);
}

main().catch((error) => {
  console.error(`render-svgs.mjs: ${error && error.stack ? error.stack : error}`);
  process.exit(1);
});
