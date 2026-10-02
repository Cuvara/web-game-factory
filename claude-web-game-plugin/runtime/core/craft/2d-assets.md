# 2D assets: from a requirement to a frame on screen

How a 2D game asks for its assets, and how its code loads them. Serves the game design's
`asset_requirements`, the asset manifest, and the runtime asset manifest
(`shared/runtime-assets.schema.json`) the asset pipeline writes into the game repository.
Defaults with reasons, like every playbook here.

## Ask for assets in the design, not in code

Every image, sheet, sound and font the game uses is one entry in
`game_design.asset_requirements`, with a stable kebab-case `id`. The id is the only name the
game code ever uses for it. Nothing else is stable: files are renamed when a placeholder
becomes art, moved when a sprite joins an atlas, re-encoded when a format changes.

| Want | Kind | Say also |
|---|---|---|
| A character, pickup, obstacle, projectile | `sprite` | `width`/`height` (logical), `atlas` |
| An animated character or effect | `spritesheet` | `frames`, frame `width`/`height`, `animations` |
| A button, panel, bar, HUD element | `ui` | `atlas` (the HUD's group) |
| A small symbol; the store icon | `icon` | `atlas` for in-game icons; not for the store icon |
| A particle or burst texture | `vfx` | `atlas` |
| A full-screen backdrop | `background` | — (opaque; never in an atlas) |
| A tile grid for a tilemap | `tileset` | `tile_width`, `tile_height`; size a multiple of them |
| Tap, coin, hit, jingle; a loop | `sfx`, `music` | see `game-audio.md` |
| Text face | `font` | — (a system stack stands in until one is chosen) |

## Atlas groups: what is drawn together, packed together

A draw call is spent per texture switch. Name an `atlas` group on every sprite, UI element,
icon and particle that is drawn **in the same scene at the same time** — the HUD, one level's
props, the menu. The pipeline packs each group into one texture (`atlases/<group>.png` +
`.json`) and keeps the members' own images out of the build, so each pixel ships once.

- One group per scene or layer, not one for the whole game: a 2048 px atlas that is half
  unused on every screen costs memory on the phones that have least.
- Backgrounds and tilesets do not join atlases: they are large, opaque or tiled, and gain
  nothing.
- Spritesheets keep their own atlas: an animation's frames are already one texture.
- All members of a group share one `scale`.
- A group that does not fit the atlas limit (policy: 2048 px) fails with the group named.
  Split it; do not raise the limit to make the error go away.

## Resolution: author once, at the scale you display

`width`/`height` are **logical** pixels — what the layout uses. `scale: 2` asks for art with
twice the pixels, drawn at the logical size, for crisp results on high-density phone
screens. Default to 1 for pixel art and for anything drawn at or below its size; use 2 for
smooth art that is shown large on mobile. Do not ship 1x, 2x and 3x copies: portal bundles
are small and a portal game has one layout. The runtime manifest records `scale`; display
size is pixel size divided by it.

## Animations are data

A spritesheet's `animations` name frame ranges with an `fps` and `loop`:
`{"run": {"frames": [0, 1, 2, 3], "fps": 12}, "die": {"frames": [4, 5, 6], "loop": false}}`.
The runtime manifest carries them with frame names resolved, so code creates animations by
iterating data, and a retimed or re-cut sheet needs no code change. An animation naming a
frame the sheet lacks is an error before the game ever runs.

## Load everything through the runtime manifest

The pipeline writes `public/assets/assets.json`. Fetch it once at boot, queue every entry,
report progress to the platform's loading API, and resolve assets by id afterwards. Never
write an asset path in source: a path in code is the one reference nothing checks.

- Every `url` and `data` is **relative to the manifest**. Resolve against the manifest's own
  URL (`new URL(entry.url, manifestUrl)`) or set the loader's base path to the manifest's
  directory. Never prefix `/`: portals serve the game from a sub-path.
- `atlas` + `frame` means: load `atlases[atlas]` once, draw frame `frame` of it.
- `url` + `data` + `frames` + `animations` is a spritesheet: load the pair as an atlas, then
  create its animations from the entry.
- `placeholder: true` loads exactly like final art. Replacing a placeholder changes the
  manifest, not the code.
- `files[url].hash` is the file's sha256; append it as a query (`?v=`) if a portal's CDN
  caches aggressively.

PixiJS (v8) — atlases and spritesheets are TexturePacker JSON, which `Assets` recognises:

```ts
const manifestUrl = new URL("assets/assets.json", document.baseURI).href;
const manifest = await (await fetch(manifestUrl)).json();
const at = (u: string) => new URL(u, manifestUrl).href;
const aliases: string[] = [];
const add = (alias: string, src: string, data?: object) => { Assets.add({ alias, src, data }); aliases.push(alias); };
for (const [id, a] of Object.entries<any>(manifest.atlases)) add(`atlas:${id}`, at(a.data));
for (const [id, e] of Object.entries<any>(manifest.assets)) {
  if (e.data) add(id, at(e.data));                     // spritesheet: meta.scale sets resolution
  else if (e.url && !["font", "sfx", "music"].includes(e.type))
    add(id, at(e.url), { resolution: e.scale ?? 1 });
}
await Assets.load(aliases, onProgress);
const texture = (id: string) => { const e = manifest.assets[id];
  return e.atlas ? Assets.get(`atlas:${e.atlas}`).textures[e.frame] : Assets.get(id); };
// Animations: new AnimatedSprite(e.animations.run.frames.map((f) => sheet.textures[f])),
// animationSpeed = fps / 60, loop = e.animations.run.loop.
```

Phaser 3 — set the loader path to the manifest's directory and every URL is already right:

```ts
// Boot: this.load.json("wgf-assets", "assets/assets.json");  Preload:
const m = this.cache.json.get("wgf-assets");
this.load.setPath("assets/");
for (const [id, a] of Object.entries<any>(m.atlases)) this.load.atlas(`atlas:${id}`, a.url, a.data);
for (const [id, e] of Object.entries<any>(m.assets)) {
  if (e.atlas || !e.url) continue;
  if (e.data) this.load.atlas(id, e.url, e.data);
  else if (e.type === "sfx" || e.type === "music") this.load.audio(id, e.url);
  else if (e.format === "svg") this.load.svg(id, e.url, { width: e.width, height: e.height });
  else if (e.type !== "font") this.load.image(id, e.url);
}
// Draw: e.atlas ? this.add.image(x, y, `atlas:${e.atlas}`, e.frame) : this.add.image(x, y, id)
// then .setScale(1 / (e.scale ?? 1)). Animations, once, in create():
// this.anims.create({ key: `${id}:${name}`, frames: a.frames.map((f) => ({ key: id, frame: f })),
//                     frameRate: a.fps, repeat: a.loop ? -1 : 0 })
// Tilesets: map.addTilesetImage(name, id, e.tile_width, e.tile_height).
```

Fonts: an entry with a `url` is a file — `new FontFace(e.family, \`url(${at(e.url)})\`,
e.weight ? { weight: e.weight } : {})`, `await face.load()`, `document.fonts.add(face)`; a
requirement with several faces lists them in `variants`, each with its own `family` (the
typography's face) and `weight` (one weight, or a variable file's range); an entry with only `family` is a system
stack to use as the CSS `font-family`. Audio: load through the engine's audio or Web Audio,
and unlock on the first gesture (`game-audio.md`).

## What not to do

- **Do not edit `assets.json`, an atlas, or a file it lists by hand.** Change the requirement
  (or drop the final file in and name it in `existing`) and rebuild. A hand-edit is
  overwritten by the next run and a stale hash is reported by the check.
- **Do not load files the manifest does not list.** A shipped file nobody registered is
  flagged as unused; a file loaded but unregistered is invisible to every check.
- **No SVG with script, event handlers, external references or DOCTYPE.** An SVG is an
  image, not a document; the pipeline rejects the rest.
- **Keep cut-out art transparent and backgrounds opaque.** A sprite without alpha draws a
  rectangle; a background with an alpha channel is wasted bytes.
- **No texture edge over 2048 px** unless the tech plan says why; over 4096 fails outright on
  part of the mobile fleet.
