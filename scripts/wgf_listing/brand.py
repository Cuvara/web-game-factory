"""Branding from the game's own material: icon, wordmark, thumbnails, promotional image.

Two ways, recorded on the listing as `branding.method`:

    browser-composed   `brand_page(...)` writes one HTML page laying out every rendition
                       (core/reference/store-listing.yaml `renditions`) from the design's
                       palette tokens and display face, the runtime asset that draws the
                       player (else an icon asset), and the best gameplay frame; the capture
                       script screenshots each box (capture.mjs composeBranding)
    frame-derived      no browser: `derive_from_frame(...)` crops and scales the best
                       gameplay frame into the icon, thumbnails and promo in pure Python.
                       No wordmark can be made that way, and the listing says so

Neither invents artwork: every pixel comes from the build's frames, its shipped assets, or
its title set in its own face over its own palette.
"""

import html
import os
import re

from . import imaging

__all__ = ["palette_roles", "brand_page", "brand_shots", "derive_from_frame", "initials"]


def palette_roles(identity):
    """{ground, ink, primary, secondary} hex colours from the visual identity's palette,
    matched by role words; sensible defaults where a role is absent."""
    palette = [p for p in (identity or {}).get("palette") or [] if isinstance(p, dict)]
    found = {}

    def pick(*words):
        for entry in palette:
            role = str(entry.get("role") or "").lower() + " " + str(entry.get("token") or "").lower()
            if any(w in role for w in words) and entry.get("hex"):
                return entry["hex"]
        return None

    found["ground"] = pick("background", "paper", "ground", "sky", "backdrop") or (
        palette[0]["hex"] if palette and palette[0].get("hex") else "#1c1a17")
    found["ink"] = pick("text", "ink", "outline", "line") or "#f4ede1"
    found["primary"] = pick("primary", "player", "accent", "action") or (
        palette[1]["hex"] if len(palette) > 1 and palette[1].get("hex") else "#ff48b0")
    found["secondary"] = pick("second", "world", "goal", "target") or found["primary"]
    return found


def initials(title, limit=3):
    words = [w for w in re.split(r"[^0-9A-Za-zÀ-ɏЀ-ӿ]+", title or "") if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:limit].upper()
    return "".join(w[0] for w in words[:limit]).upper()


def _font_face(fonts):
    """@font-face rules for the bundle's font assets (served under /assets/); the first is
    the display face."""
    rules, families = [], []
    for index, (asset_id, url) in enumerate(fonts or []):
        family = f"wgf-brand-{index}"
        fmt = "woff2" if url.lower().endswith(".woff2") else "woff" if url.lower().endswith(".woff") \
            else "truetype" if url.lower().endswith(".ttf") else "opentype"
        rules.append(f'@font-face {{ font-family: "{family}"; src: url("/assets/{html.escape(url)}") '
                     f'format("{fmt}"); font-display: block; }}')
        families.append(family)
    return "\n".join(rules), families


def brand_shots(renditions):
    """The capture script's shot list: one per rendition family entry."""
    shots = []
    for family in ("icon", "logo", "thumbnail", "promo"):
        for entry in (renditions or {}).get(family) or []:
            shots.append({"id": entry["id"], "selector": f"#{entry['id']}", "width": int(entry["width"]),
                          "height": int(entry["height"]), "transparent": family == "logo",
                          "source": family})
    return shots


def brand_page(*, title, identity, renditions, hero_url=None, frame_url=None, fonts=()):
    """The HTML of the branding page. `hero_url` is the player asset's URL (absolute path on
    the served origin) or None; `frame_url` the best play frame's; `fonts` [(id, url)] of the
    bundle's font assets, relative to /assets/."""
    colours = palette_roles(identity)
    faces, families = _font_face(fonts)
    display = ", ".join(f'"{f}"' for f in families) + (", " if families else "") + \
        '"Rubik Mono One", "Arial Black", Impact, system-ui, sans-serif'
    safe_title = html.escape(title or "")
    boxes = []
    y = 0
    for shot in brand_shots(renditions):
        w, h = shot["width"], shot["height"]
        family = shot["source"]
        if family == "icon":
            inner = (f'<img class="hero" src="{html.escape(hero_url)}" alt="">' if hero_url else
                     f'<div class="initials">{html.escape(initials(title))}</div>')
            body = f'<div class="icon">{inner}</div>'
        elif family == "logo":
            body = f'<div class="wordmark"><span class="fit">{safe_title}</span></div>'
        else:
            frame = f'style="background-image:url(\'{html.escape(frame_url)}\')"' if frame_url else ""
            body = (f'<div class="shot" {frame}>'
                    f'<div class="band"><span class="fit title">{safe_title}</span></div></div>')
        boxes.append(f'<section id="{shot["id"]}" class="box {family}" style="top:{y}px;width:{w}px;height:{h}px">'
                     f'{body}</section>')
        y += h + 20
    total = max(y, 10)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{safe_title} - store branding</title>
<style>
{faces}
html, body {{ margin: 0; padding: 0; background: transparent; width: 1920px; height: {total}px; }}
.box {{ position: absolute; left: 0; overflow: hidden; box-sizing: border-box; }}
.icon {{ width: 100%; height: 100%; background: {colours["ground"]}; display: flex; align-items: center;
        justify-content: center; }}
.icon .hero {{ width: 68%; height: 68%; object-fit: contain; image-rendering: auto; }}
.icon .initials {{ font-family: {display}; font-weight: 700; color: {colours["primary"]};
        font-size: 44%; line-height: 1; letter-spacing: -0.02em;
        text-shadow: 0.03em 0.03em 0 {colours["ink"]}; }}
.wordmark {{ width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
        padding: 4%; box-sizing: border-box; }}
.wordmark .fit {{ font-family: {display}; font-weight: 700; color: {colours["ink"]}; white-space: nowrap;
        line-height: 1; letter-spacing: -0.01em; text-transform: uppercase; }}
.shot {{ width: 100%; height: 100%; background-color: {colours["ground"]}; background-size: cover;
        background-position: center; position: relative; }}
.shot .band {{ position: absolute; left: 0; right: 0; bottom: 0; padding: 3% 4%; background: {colours["ink"]}ee;
        display: flex; align-items: center; }}
.shot .title {{ font-family: {display}; font-weight: 700; color: {colours["primary"]}; white-space: nowrap;
        text-transform: uppercase; line-height: 1; }}
</style></head>
<body>
{"".join(boxes)}
<script>
// Fit each title to its box: shrink the font until the text fits the width and the band is
// at most a third of the image.
for (const box of document.querySelectorAll('.box')) {{
  const span = box.querySelector('.fit');
  if (!span) continue;
  const parent = span.parentElement;
  const maxWidth = parent.clientWidth * 0.92;
  const maxHeight = box.classList.contains('logo') ? box.clientHeight * 0.8 : box.clientHeight * 0.14;
  let size = Math.floor(maxHeight);
  span.style.fontSize = size + 'px';
  while (size > 8 && (span.scrollWidth > maxWidth || span.getBoundingClientRect().height > maxHeight)) {{
    size -= Math.max(1, Math.floor(size * 0.06));
    span.style.fontSize = size + 'px';
  }}
}}
for (const icon of document.querySelectorAll('.icon .initials')) {{
  const box = icon.parentElement;
  let size = Math.floor(box.clientHeight * 0.44);
  icon.style.fontSize = size + 'px';
  while (size > 8 && icon.scrollWidth > box.clientWidth * 0.8) {{
    size -= Math.max(1, Math.floor(size * 0.06));
    icon.style.fontSize = size + 'px';
  }}
}}
</script>
</body></html>
"""


def derive_from_frame(frame_path, renditions, out_dir, ground_hex="#000000"):
    """The icon, thumbnails and promo as crops of the best play frame; no wordmark. Returns
    [(rendition id, family, path, width, height)]."""
    frame = imaging.read_png(frame_path)
    ground = imaging.parse_hex(ground_hex)
    made = []
    for family in ("icon", "thumbnail", "promo"):
        for entry in (renditions or {}).get(family) or []:
            w, h = int(entry["width"]), int(entry["height"])
            if w > frame.width or h > frame.height:
                # The frame is smaller than the master: letterbox rather than upscale.
                image = imaging.fit(frame, w, h, "contain", ground)
            else:
                image = imaging.fit(frame, w, h, "cover")
            path = os.path.join(out_dir, f"{entry['id']}.png")
            imaging.write_png(path, image)
            made.append((entry["id"], family, path, w, h))
    return made
