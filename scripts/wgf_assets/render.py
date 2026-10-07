"""Render built GLBs with the pinned Blender: what the model author looks at.

A model spec that passes every measured check can still read as a brick. The person who
made the reference game's models looked at renders and changed the spec until the ship read
as a ship; this module gives an agent author the same pictures. For each model:

    <dir>/<id>.three-quarter.png   front-right, from above
    <dir>/<id>.side.png            the profile
    <dir>/<id>.top.png             from above, the model's front up
    <dir>/<id>.game.png            from the game's camera, when the design states one
    <dir>/<id>.gameplay.png        that view at the size a player sees it (the requirement's
                                   `readability` "... at 80 px ..."; else 96 px)
    <dir>/<id>.sheet.png           all of them side by side, in that order

and, for a set, `<dir>/set.png`: every model side by side at its real size, from the
three-quarter view and the game's camera, so a set keeps one scale, palette and detail level.

With a `context` ({surface, backdrop, player}: the play surface's and the backdrop's colours,
and the player's GLB), each model is also rendered in context, `<dir>/<id>.context.png`: on a
ground plane of the surface's colour, beside the player at its real size, under the same rig,
from the game's camera (the three-quarter view when the design states none), over the
backdrop - what the model judge reads for `camera_view` (core/reference/
model-review-rubric.yaml).

Lighting follows the 3D craft guide's rig (core/craft/production-art-3d.md, "Lighting rig"):
a hemisphere ambient, a white key high front-right, a rim in the palette's accent from behind;
the background is the palette's darkest colour, the sky tint its lightest. So a model is seen
in the colours and the light the game will show it in, not in a grey studio.

    report = render(info, [{"id", "glb", "role", "readability"}], out_dir=D,
                    identity=visual_identity, camera=design_camera_text, lineup=True)
    report = {"engine", "models": {id: {"sheet", "views": {name: {path, coverage, fill}},
                                        "context": {path, beside} or absent}},
              "set": {"path", "order"} or absent}

Blender runs headless through wgflib.procs (blender.build_environment: no user preferences,
add-ons or home), with the first available engine of `engines` (Eevee, then Cycles on the
CPU, which needs no GPU). The settings are fixed (samples, seed, no denoiser, the Standard
view transform); the PNGs are evidence for a reader, never a build output.
"""

import colorsys
import json
import os
import re
import shutil
import tempfile

from wgflib import procs

from . import blender

__all__ = ["RenderError", "render", "job", "context_job", "rig", "views", "game_direction",
           "gameplay_pixels", "SCRIPT", "DEFAULTS", "VIEW_ORDER"]

SCRIPT = os.path.join(blender.HERE, "blender_scripts", "render_models.py")
DEFAULTS = {"engines": ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"], "samples": 32,
            "tile": 384, "timeout_seconds": 600}
VIEW_ORDER = ("three-quarter", "side", "top", "game", "gameplay")
# Default gameplay size when the readability line names none: a small on-screen object.
GAMEPLAY_PIXELS = 96
_PIXELS = re.compile(r"(\d{2,4})\s*(?:px|pixels?)\b", re.IGNORECASE)
# The craft guide's rig, in glTF directions: key high front-right, rim behind left.
KEY = {"color": [1.0, 1.0, 1.0], "strength": 2.6, "direction": [4.0, 9.0, 7.0]}
RIM = {"strength": 1.4, "direction": [-6.0, 4.0, -12.0]}
AMBIENT = 0.9


class RenderError(RuntimeError):
    """Blender could not render; the message says why."""


def _rgb(hex_colour):
    value = hex_colour.lstrip("#")
    return [int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def _luma(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _palette(identity):
    palette = identity.get("palette") if isinstance(identity, dict) else identity
    out = []
    for entry in palette or []:
        value = entry.get("hex") if isinstance(entry, dict) else entry
        if isinstance(value, str) and re.match(r"^#[0-9a-fA-F]{6}$", value):
            out.append(_rgb(value))
    return out


def _named_accent(identity):
    """The palette entry whose token or role names the player's accent (the craft guide's
    rim is the player accent, never the danger colour), or None."""
    palette = identity.get("palette") if isinstance(identity, dict) else None
    for entry in palette or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("hex"), str):
            continue
        words = f"{entry.get('token', '')} {entry.get('role', '')}".lower()
        if re.search(r"danger|warning|hazard|threat", words):
            continue
        if re.search(r"\b(player|accent|signal|primary)\b", words) \
                and re.match(r"^#[0-9a-fA-F]{6}$", entry["hex"]):
            return _rgb(entry["hex"])
    return None


def rig(identity):
    """(background, rig) from the visual identity's palette: the darkest colour is the
    background and the ambient's ground, the lightest tinted toward the accent its sky, and
    the player's accent (by token or role; else the most saturated bright colour) the rim
    light's."""
    colours = _palette(identity)
    if not colours:
        colours = [[0.07, 0.07, 0.1], [0.92, 0.92, 1.0], [1.0, 0.18, 0.53]]
    darkest = min(colours, key=_luma)
    lightest = max(colours, key=_luma)

    def vivid(rgb):
        _h, s, v = colorsys.rgb_to_hsv(*rgb)
        return s * v

    accent = _named_accent(identity) or max((c for c in colours if c is not darkest),
                                            key=vivid, default=lightest)
    sky = [0.62 * (0.7 * a + 0.3 * b) for a, b in zip(lightest, accent)]
    return list(darkest), {
        "ground": list(darkest), "sky": sky, "ambient": AMBIENT,
        "key": dict(KEY), "rim": dict(RIM, color=list(accent)),
    }


def game_direction(camera, role=None):
    """(direction, up) of the game's camera as seen from the model, from the design's
    camera statement, or None when it states none a view can be made from. A chase camera
    sees the player from behind and everything coming at the player from the front."""
    text = (camera or "").lower()
    if not text.strip():
        return None
    if re.search(r"top[- ]down|overhead|bird", text):
        return [0.0, 1.0, -0.35], [0.0, 0.0, 1.0]
    if "isometric" in text:
        return [1.0, 0.82, 1.0], [0.0, 1.0, 0.0]
    if re.search(r"\bside\b|side-scroll|profile", text):
        return [1.0, 0.12, 0.0], [0.0, 1.0, 0.0]
    if re.search(r"first[- ]person|cockpit", text):
        return ([0.0, 0.05, 1.0], [0.0, 1.0, 0.0]) if role != "player" else None
    behind = role == "player"
    high = 0.6 if re.search(r"\bhigh\b|elevated|above", text) and "slightly" not in text else 0.42
    return [0.0, high, -1.0 if behind else 1.0], [0.0, 1.0, 0.0]


def gameplay_pixels(readability):
    """The on-screen size the readability line names ("readable at 80 px wide"), clamped to
    24..384; GAMEPLAY_PIXELS when it names none."""
    match = _PIXELS.search(readability or "")
    if not match:
        return GAMEPLAY_PIXELS
    return max(24, min(384, int(match.group(1))))


def views(role=None, readability=None, camera=None):
    """The views of one model's sheet, in VIEW_ORDER."""
    out = [
        {"name": "three-quarter", "direction": [1.0, 0.75, 1.25], "fov": 30},
        {"name": "side", "direction": [1.0, 0.08, 0.0], "fov": 30},
        {"name": "top", "direction": [0.0, 1.0, 0.0], "up": [0.0, 0.0, 1.0], "fov": 30},
    ]
    game = game_direction(camera, role)
    if game:
        out.append({"name": "game", "direction": game[0], "up": game[1], "fov": 38})
    base = out[-1] if game else out[0]
    pixels = gameplay_pixels(readability)
    # The model's longer side spans `margin` of the tile; at that size it spans `pixels`.
    out.append(dict(base, name="gameplay", margin=0.9,
                    pixels=max(16, int(round(pixels / 0.9)))))
    return out


def context_job(context, camera, identity=None):
    """The job's `context` block from {surface, backdrop, player, player_id}, or None when
    there is no surface to stand the model on."""
    if not isinstance(context, dict) or not context.get("surface"):
        return None
    background, _light = rig(identity)
    game = game_direction(camera, None)
    view = ({"name": "context", "direction": game[0], "up": game[1], "fov": 38} if game else
            {"name": "context", "direction": [1.0, 0.75, 1.25], "fov": 30})
    out = {"surface": _rgb(context["surface"]),
           "backdrop": _rgb(context["backdrop"]) if context.get("backdrop") else background,
           "view": view}
    if context.get("player") and os.path.isfile(context["player"]):
        out["player"] = os.path.abspath(context["player"])
        out["player_id"] = context.get("player_id") or "player"
    return out


def job(models, out_dir, *, identity=None, camera=None, lineup=True, settings=None,
        context=None):
    """The job render_models.py reads."""
    settings = dict(DEFAULTS, **(settings or {}))
    background, light = rig(identity)
    entries = []
    for model in models:
        entries.append({
            "id": model["id"], "glb": os.path.abspath(model["glb"]),
            "dir": os.path.abspath(out_dir),
            "sheet": os.path.abspath(os.path.join(out_dir, f"{model['id']}.sheet.png")),
            "views": views(model.get("role"), model.get("readability"), camera),
        })
    document = {"format": 1, "engines": list(settings["engines"]),
                "samples": int(settings["samples"]), "tile": int(settings["tile"]),
                "background": background, "rig": light, "models": entries}
    in_context = context_job(context, camera, identity)
    if in_context:
        document["context"] = in_context
    if lineup and len(models) > 1:
        # A long lens: models side by side keep their relative size wherever they stand.
        set_views = [{"name": "three-quarter", "direction": [1.0, 0.75, 1.25], "fov": 12}]
        game = game_direction(camera, None)
        if game:
            set_views.append({"name": "game", "direction": game[0], "up": game[1],
                              "fov": 12})
        document["set"] = {"out": os.path.abspath(os.path.join(out_dir, "set.png")),
                           "views": set_views, "width": int(settings["tile"]) * 2,
                           "height": int(settings["tile"])}
    return document


def command(executable, job_path, report_path, version=None, script=SCRIPT):
    argv = [executable, "--background", "--factory-startup", "-noaudio"]
    if version is None or tuple(version[:2]) >= (4, 2):
        argv.append("--offline-mode")
    return argv + ["--python-exit-code", "3", "--python", script, "--",
                   "--job", job_path, "--report", report_path]


def render(info, models, *, out_dir, identity=None, camera=None, lineup=True, settings=None,
           runner=None, on_event=None, context=None):
    """Render `models` ([{id, glb, role, readability}]) into `out_dir`; the report.
    Raises RenderError. Eevee first; when it cannot render here (no GPU context), Cycles on
    the CPU."""
    if info is None or info.executable is None:
        raise RenderError("no Blender to render with")
    settings = dict(DEFAULTS, **(settings or {}))
    os.makedirs(out_dir, exist_ok=True)
    runner = runner or procs.run
    engines = list(settings["engines"])
    attempts = [engines]
    if engines and engines[-1] == "CYCLES" and engines[0] != "CYCLES":
        attempts.append(["CYCLES"])
    problem = None
    for attempt in attempts:
        document = job(models, out_dir, identity=identity, camera=camera, lineup=lineup,
                       settings=dict(settings, engines=attempt), context=context)
        scratch = tempfile.mkdtemp(prefix="wgf-render-")
        try:
            job_path = os.path.join(scratch, "job.json")
            report_path = os.path.join(scratch, "report.json")
            with open(job_path, "w", encoding="utf-8") as handle:
                json.dump(document, handle, indent=1, sort_keys=True)
            result = runner(command(info.executable, job_path, report_path, info.version),
                            timeout=float(settings["timeout_seconds"]),
                            env=blender.build_environment(scratch), on_event=on_event,
                            cwd=scratch)
            report = None
            if os.path.isfile(report_path):
                with open(report_path, encoding="utf-8") as handle:
                    report = json.load(handle)
            if report is not None and report.get("ok"):
                with open(os.path.join(out_dir, "render-report.json"), "w",
                          encoding="utf-8", newline="\n") as handle:
                    json.dump(report, handle, indent=2, sort_keys=True)
                return report
            problem = (report or {}).get("error") or (
                f"Blender exited {result.status}/{result.returncode}: {result.tail(8)}")
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    raise RenderError(f"rendering {', '.join(m['id'] for m in models)} failed: {problem}")
