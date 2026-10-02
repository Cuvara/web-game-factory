"""A stand-in for the 2D set author (author mode `set`): argv <mode> <request> <out> <preview>.

It reads the set brief the assets step wrote, appends it to calls.jsonl beside the brief
(what the tests assert on), writes STYLE.md and one SVG per file the brief lists - only
inside <out>, as its host would be restricted to - and, like a real author, runs the preview
command it was given and records what it printed (preview.txt beside the brief).

    good             every drawing outlined in ink at one width, each variant its own size
    font-then-good   the first session sets one drawing's lettering in a system font and
                     another's outline three times as heavy; a repair session fixes both
    inconsistent     every session draws the second entity without an outline
    partial          writes only the first file
    crash-then-good  the first session writes the first file and exits 3 (a host bound hit
                     mid-set); the repair session draws the rest
"""

import json
import os
import shlex
import subprocess
import sys

mode, request_path, out, preview = sys.argv[1:5]
with open(request_path, encoding="utf-8") as handle:
    brief = json.load(handle)
with open(os.path.join(os.path.dirname(request_path), "calls.jsonl"), "a",
          encoding="utf-8") as handle:
    handle.write(json.dumps(brief, sort_keys=True) + "\n")

if mode == "fail":
    print("author crashed", file=sys.stderr)
    sys.exit(3)

palette = [e["hex"] for e in (brief.get("visual_identity") or {}).get("palette") or []] or [
    "#FF2E88", "#2EF2FF", "#16162A"]
faces = brief.get("typography_faces") or ["display"]
repair = brief.get("repair")
INK = "#000000"


def drawing(width, height, k, outline=2.5, text=None):
    a, b, c = (palette * 3)[:3]
    stroke = f' stroke="{INK}" stroke-width="{outline}"' if outline else ""
    body = (f'<ellipse cx="{width / 2}" cy="{height * 0.6}" rx="{width * (0.18 + 0.1 * k)}" '
            f'ry="{height * (0.36 - 0.05 * k)}" fill="{a}"{stroke}/>'
            f'<circle cx="{width / 2}" cy="{height * (0.25 + 0.05 * k)}" r="{width * 0.12}" '
            f'fill="{b}"{stroke}/>'
            f'<path d="M {width * 0.3} {height * 0.85} L {width / 2} {height * 0.97} '
            f'L {width * 0.7} {height * 0.85} Z" fill="{c}"{stroke}/>'
            f'<rect x="{width * 0.05}" y="{height * 0.05}" width="{width * 0.1}" '
            f'height="{height * 0.1}" fill="{b}"{stroke}/>')
    if text:
        body += text
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">{body}</svg>')


os.makedirs(out, exist_ok=True)
with open(os.path.join(out, "STYLE.md"), "w", encoding="utf-8") as handle:
    handle.write("| outline | 2.5px ink |\n")
files = [(req, f) for req in brief["requirements"] for f in req["files"]]
if mode == "partial" or (mode == "crash-then-good" and not repair):
    files = files[:1]
entity = 0
for index, (req, entry) in enumerate(files):
    width, height = req.get("width") or 96, req.get("height") or 96
    k = int(entry["variant"].rsplit("-", 1)[-1]) - 1 if entry["variant"][-1].isdigit() \
        and req.get("count", 1) > 1 else 0
    outline, text = 2.5, None
    if req["role"] in ("player", "threat", "target", "collectible", "hazard", "prop", "goal",
                       "projectile"):
        entity += 1
        if mode == "inconsistent" and entity == 2:
            outline = 0
        if mode == "font-then-good" and not repair and entity == 2:
            outline = 7.5
    if mode == "font-then-good" and not repair and index == 0:
        text = '<text x="4" y="20" font-family="Arial, sans-serif">Hi</text>'
    elif index == 0:
        text = f'<text x="4" y="20" font-family="\'{faces[0].title()}\', serif">Hi</text>'
    if entry.get("accepted") and os.path.isfile(entry["path"]) and mode == "good":
        continue  # keep what was accepted before
    with open(entry["path"], "w", encoding="utf-8") as handle:
        handle.write(drawing(width, height, k, outline, text))

if mode == "crash-then-good" and not repair:
    sys.exit(3)
done = subprocess.run(shlex.split(preview), capture_output=True, text=True)
with open(os.path.join(os.path.dirname(request_path), "preview.txt"), "a",
          encoding="utf-8") as handle:
    handle.write(f"exit {done.returncode}\n{done.stdout}{done.stderr}\n")
print("Drew the set; looked at the preview.")
