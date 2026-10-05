# Production wiring

**Serves** the runtime asset manifest (`core/artifacts/shared/runtime-assets.schema.json`,
`public/assets/assets.json`), the play probe (`core/artifacts/shared/play-probe.schema.json`:
`entities[].asset`, `.render`, `assets_loaded`), the game repository's end-to-end tests, and
the checks a production build is held to: playability (`docs/playability-module.md`), the
production gate (`core/reference/production-quality.yaml`) and visual QA
(`core/reference/visual-qa-rubric.yaml`).

Art that is delivered but not drawn, or drawn but not reported, is worth nothing to the
Factory: every check reads the game from outside. This playbook is how both reference ports
wired their art so that the gate could prove it - and a guard test so a later commit cannot
silently undo it. `2d-assets.md` and `3d-assets-and-animation.md` cover engine loading in
depth; this is the contract around it.

## 1. Load through the runtime manifest, by id and role

- **One loader, one fetch**: `assets/assets.json` resolved against `document.baseURI`,
  `cache: "no-cache"`. Refuse a document whose `format` is not `"wgf-runtime-assets"`.
- **Greybox is a state, not an error** - for a 2D game: a missing manifest, a non-OK
  response, or a body that is not JSON (a static server's index fallback) means "no art":
  draw primitives and report them honestly. Invalid JSON with a JSON content type is a bug:
  throw. A 3D game may choose the opposite: the 3D reference throws on a missing model
  (a visible "boot failed") rather than silently driving a box.
- **Every `url` is relative to the manifest**: `new URL(entry.url, manifestUrl)`. Code
  never names a file path.
- **Find by id, then by role.** `find(id, role)`: the design's id if present, else the first
  (sorted) asset of that role that is not a variant of another. Tell two assets of one role
  apart by shape when needed (the 2D reference: a `ui` asset with `width > 1.5*height` is
  the wordmark, the other the panel). Never by array position alone - the 3D reference
  mapped fonts and icons by sorted file order and listed it as a risk.
- **Variants**: a counted requirement (`count: N`) is a parent entry with
  `variants: ["<id>-1", ..., "<id>-N"]`, each its own entry. `drawings(id)` returns the
  variants, or `[id]` when there are none; variant `n` draws level / type `n`; past the last,
  reuse the last with an added mark.
- **Roles** the loader understands: player, threat, goal, target, projectile, collectible,
  hazard, environment, background, prop, ui, vfx, icon, font.
- **Placeholders are visible**: an entry with `placeholder: true` is a stand-in. Draw it, but
  never report it as art - the guard fails on it.
- **Loaders**: 2D - `Assets.load({alias: "wgf:" + id, src, parser: <from the entry's
  format, not the extension>, data: {resolution}})`, SVG rasterised at
  `clamp(ceil(dpr), 2, 3) * scale`. 3D - one `GLTFLoader.loadAsync` per entry with a `url`,
  `format` glb/gltf, not a placeholder; index models by `role` and by the root's
  `userData.wgf_asset`; hide nodes whose `userData.wgf_role === "collision"`; keep the
  `wgf_asset` stamp on anything you merge or clone. Textures `SRGBColorSpace`.
- **Fonts**: the first font drawing becomes the display face, the second the body face
  (one file serves both); an entry with only `family` sets a CSS variable instead. Declare
  with `@font-face { font-display: block }`, await `document.fonts.load(...)`, and mark the
  font loaded only if the face is found (`game-ui-kit.md`).
- **Mark loaded honestly**: an id joins `loaded` when its file has decoded (`img.decode()`,
  the texture resolved, the GLB parsed, the face loaded); a parent joins when all its
  variants have. Report loading progress into the boot bar.

## 2. The play probe tells the truth about drawing

`window.__wgf__.play.snapshot()` - install it **after** the template's `installProbe`,
which replaces `window.__wgf__`. Required: `state` (`title | playing | paused | won | lost`,
the result screen keeps reporting `won`/`lost`), `metrics`, `entities`, `inputs`; plus
`assets_loaded` and, only with `?wgf-probe=1`, `oracle`.

Every entity a player reads:

```json
{"id": "tower-3", "role": "target", "x": 412, "y": 288, "w": 96, "h": 163,
 "visible": true, "asset": "pieces-4", "render": "asset"}
```

- `x, y, w, h` in CSS px from the viewport's top-left - the drawn bounds, not the logical
  cell. In 3D, project the object's world box through its 8 corners to the screen.
- `visible`: in front of the camera, on the surface, not hidden or transparent.
- `asset`: the runtime id actually drawing it (the variant id for a counted requirement), or
  `null`. `render`: `asset` (drawn from a manifest asset), `composite` (several), `text`, or
  `primitive` (an engine box, sphere, rectangle).
- **Derive both from what is drawn, not from intent.** 2D: from the sprite's texture alias.
  3D: walk the visible meshes, union their world boxes, and report `asset` only when every
  mesh has an ancestor stamped `wgf_asset` - one stray box makes it `primitive`.
- An entity spawned but not drawn yet may borrow a drawn sibling's asset and box; never
  invent one.
- `inputs[]`: `{action, input}` per available action - `{type: "pointer", x, y, hold_ms}`
  aimed at real screen positions (a column centre, 10 % / 90 % of width to steer), or a key;
  buttons by their centres.
- `assets_loaded`: every runtime id loaded, parents and variants.

### Assets that first appear after the opening unit

Every bot test starts on a fresh save, so it only meets the opening unit. A readable asset
that first appears later (a boss, a hazard of level 4) is never seen drawn, and the
production gate fails it at `rendered`. Do not move content into the first unit or force a
screen on every boot to satisfy the bot. Declare the optional showcase instead, only with
`?wgf-probe=1`:

```ts
play.showcase = {
  // Runtime asset ids of readable entities the opening play does not show.
  targets: () => ["boss", "embers", "laser-bolt"],
  // Put the running game into a real state of play where that asset is drawn: load the
  // unit it first appears in (and, for something transient, spawn it there).
  show: async (id) => { await game.enterUnit(unitOf(id)); return true; },
};
```

The bot calls it in its own last test, waits until `snapshot()` reports `playing` with an
entity drawn from that asset, and keeps a frame of the screen. The gate credits the asset
only where the frame shows it at the reported box: a probe that names an asset the screen
does not draw is still caught. `show` stages a state through the game's own systems - the
same loading, rendering and assets a player meets there - never a test scene drawn for the
bot.

### A mode beside the main play

A design that includes an endless mode beside its authored units promises its time ramp in
that mode: the playability bot reads `depth.ramp` on a run of it, never on an authored level.
Declare how to enter it, only with `?wgf-probe=1`:

```ts
play.mode = {
  modes: () => ["endless"],
  // Start a fresh run of the mode through the same code path as its menu entry; true once
  // snapshot() reports `playing` in it. A retry after a loss there stays in the mode.
  enter: async (mode) => mode === "endless" && (await game.startEndless(), true),
};
```

Without it the ramp is unmeasured, which fails a release-tier build. The oracle keeps naming
the input that succeeds now in that mode, so the bot can play it for the minute it reads.

## 3. The regression guard: an end-to-end test that fails without the art

Ship one Playwright test in the game repository that proves the art is wired, and keep it.
The pattern both references used:

```ts
test("production art is drawn from the manifest", async ({ page }) => {
  await page.route(/^(?!http:\/\/(localhost|127\.0\.0\.1))/, (r) => r.abort());
  const fetched = new Map<string, number>();
  page.on("response", (r) => { const u = new URL(r.url());
    if (u.pathname.includes("/assets/")) fetched.set(u.pathname, r.status()); });
  const errors: string[] = []; page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/");
  const manifest = await page.evaluate(async () =>
    (await fetch("assets/assets.json")).json().catch(() => null));
  test.skip(!manifest, "greybox build: no runtime manifest");
  await page.click("#play");            // then real input until the readable entities exist
  const snap = await page.evaluate(() => (window as any).__wgf__.play.snapshot());
  for (const e of snap.entities.filter((e: any) => e.role !== "ui")) {
    expect(e.render, e.id).toBe("asset");
    expect(manifest.assets[e.asset], e.id).toBeTruthy();
    expect(manifest.assets[e.asset].placeholder, `${e.id}: ${e.asset} is a placeholder`).not.toBe(true);
    expect(snap.assets_loaded).toContain(e.asset);
  }
  for (const [id, a] of Object.entries<any>(manifest.assets).filter(([, a]) => a.url))
    expect(fetched.get(`/assets/${a.url}`), id).toBe(200);
  expect(await page.evaluate(() => document.fonts.check('16px "wgf-display"'))).toBe(true);
  expect(await page.$eval("#pause", (b) => getComputedStyle(b).fontFamily)).toContain("wgf-display");
  expect(errors).toEqual([]);
});
```

- Pin randomness (`Math.random = () => 0` via `addInitScript`) so the run is reproducible.
- 3D additions: exactly one `player` entity and at least one `threat` visible (force one with
  a test hook such as `spawnObstacleAt`); every model entry a `.glb`, not a placeholder, with
  `model.triangles > 200` - "a cube is 12".
- **Prove the guard bites**: break the art on purpose and watch it fail, then restore -
  placeholder art ("is a placeholder"), the drawing removed ("drawn as primitive"), the
  player swapped for a box, a missing GLB. With no manifest at all it must skip, not fail.

## 4. Check yourself before reporting

The gates run after you; run their measurements first and **look at the frames**. No
production report without frames: the reference agents' first passes would have shipped
white-on-cream text, alike levels, a tiny portrait board and a dark 3D scene without it.

1. `python3 scripts/wgf-assets.py validate <checkout> --strict` - the manifest against its
   files.
2. Build and serve the production bundle (the preview server, not the dev server), play it
   at **1280x720** and **390x844 touch**, and capture title, playing, a reward moment, pause,
   result and after-retry.
3. Read each frame against the bars:
   - every readable entity drawn from an asset, at least 0.2 % of the viewport, visible in
     half the samples or more (`visual-quality.yaml`);
   - at least 1 % of pixels lit and enough spread (no dark, flat 3D frame);
   - text contrast >= 4.5:1, targets >= 44 (kit 48) px, no overlaps, bundled fonts
     (`production-quality.yaml` `ui.*`);
   - a result state reached by losing, and retry back in play within 3 s;
   - the probe's `render`/`asset` matching what the frame shows.
4. When a vision judge is configured, judge the frames with the rubric outside a run:
   `python3 scripts/wgf-visualqa.py --frames <dir>/desktop/frames --frames <dir>/mobile/frames
   --design <game-design.json> --manifest <checkout>/public/assets/assets.json` (exit 0
   PASS, 1 FAIL, 2 unusable). Its blockers - a primitive entity, a missing asset, a
   browser-default UI, debug output, an unreadable frame, cropped play - are the ones to fix
   before anything else.
5. Report what is drawn, with the frames: what passed, what you could not measure, and
   anything left a placeholder - never "done" on a build you have not looked at.

## Failure modes

- A probe that reports `asset` from intent while the screen shows a box.
- `assets_loaded` filled before the decode, or with ids never fetched.
- Assets found by array index; a new file reshuffles every drawing.
- A guard that only runs when art exists and therefore never fails (prove it bites).
- Fonts declared but never awaited: the first frames in a fallback face.
- A report without frames.

## Distilled from

The template's reference ports: `examples/tower-merge-rush/wgf-golden/src/assets/
runtime-assets.ts` (fetch, greybox fallback, `find`, `drawings`, `markLoaded`, `loadFonts`,
`preloadImages`), `src/rendering/pixijs/art.ts` (`Assets.load`, parser, resolution),
`src/game/play-probe.ts` (snapshot, entities from the view, inputs, oracle),
`tests/e2e/tower-merge-rush.spec.ts` (the art guard and its negative runs);
`examples/neon-drift-arena/wgf-golden/src/rendering/threejs/assets.ts` (GLTFLoader by role
and stamp, no primitive fallback, `FontFace`), `src/rendering/threejs/arena-view.ts`
(`#drawn()` and the stamp through merging), `src/game/play-probe.ts` (screen boxes from world
boxes), `tests/e2e/neon-drift-arena.spec.ts` (asset guard, triangle floor); the evidence in
both ports' `baseline/` (probe dumps, production-gate reports); and the 2026-10-01 quality
monitor's rule "no report without frames".
