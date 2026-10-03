"""The `author` source for 3D: an agent writes model specs, the pinned Blender builds them,
renders them, and the agent looks at the renders.

A requirement of a readable role - a keeper, a car, a coin - deserves a model a player
recognises, not a cube. The reference game's models were made by a person who wrote a spec,
looked at a render, and changed the spec until the ship read as a ship. An agent that never
sees what it built passes every measured check with "an orange brick with no wings". So
here the author gets the same pictures the person had:

    requirement(s) + visual identity + art direction + the game's camera
      -> author (a command: the agent host)       writes a model spec per requirement
      -> modelspec.validate + the schema           a spec that is not one is shown back
      -> blender.build_model (pinned 4.5, headless) a build failure is shown back
      -> gltf.inspect + model_quality.assess       a model that fails its bars is shown back
      -> render.render (the same Blender)          a contact sheet per model (three-quarter,
                                                   side, top, the game's camera, the size a
                                                   player sees it) and, for a set, every
                                                   model side by side at its real size
      -> repair rounds (`max_repair_rounds`, 2): the problems AND the renders
      -> review rounds (`review_rounds`, 1): every model passes its checks; the author opens
         the renders and revises each spec whose silhouette does not read as its
         `readability` line at gameplay distance, and leaves the rest exactly as they are -
         an unchanged spec is the author's "it reads"
      -> the last spec that passed every check is the model (a revision that breaks a check
         is shown back while repair rounds remain, and otherwise dropped)

The author only writes SPECS. It never touches Blender, the GLB, the renders or the verdict:
an author cannot mark its own homework, and nothing here relaxes a check to let a spec
through. The self-review only ever replaces a passing spec with another passing spec.

Two modes (`mode`):

    each   one session per requirement (produce_model): the request is that asset's.
    set    one session for every 3D requirement of the design (produce_models): one
           palette, one material language, one level of detail, judged together in the
           set render. The pipeline gathers the requirements and calls it once.

    result  = produce_model(requirement, visual_identity, out_dir, settings, context)
    result  = {"files": [<out_dir>/<id>.glb], "quality": {verdict, checks, ...},
               "source": "ai-generated", "license": "LicenseRef-factory-generated",
               "placeholder": False, "notes": "...", "spec": {...}, "model": {...summary},
               "rounds": asks, "history": [...], "renders": {sheet, views} or None,
               "review": {rounds, reads, note} or None}
    results = produce_models([requirement, ...], visual_identity, out_dir, settings, context)
    results = {"results": {id: result}, "errors": {id: ModelAuthorError},
               "set_render": path or None, "rounds": asks}

`requirement` is a build_spec asset (`id`, `role`, `description`, `readability`, `spec`) or
an asset requirement (`requirements.Requirement`, or its dict: `kind`, `label`, `model` -
whose declared clips, collision, fit and budget the authored spec must meet). A
requirement sent back by a failed gate carries `feedback` {notes, frames} (wgf_assets.
feedback): the judge's reasons and the absolute paths of the frames of the running game that
show them, which reach the author's request as `notes` and `frames`. `settings`:

    kind                  "command" (the only kind)
    mode                  each (default) | set
    argv                  the author's command; placeholders, per element, never re-formatted:
                          {request} the request JSON, {spec} where to write the spec JSON
                          (each mode), {dir} the directory the specs are written in (set
                          mode: one <id>.model.json per asset; each mode: {spec}'s), {prompt}
                          a one-paragraph instruction; {request_rule}, {spec_rule},
                          {dir_rule} the paths as a host permission rule names them
                          (wgflib.permpath: `Edit({dir_rule}/**)` on every host OS; the
                          older `Edit(/{dir}/**)` is read as that)
    spec_from             file (default: the author writes the spec files; on a repair or
                          review they hold the previous specs, to edit in place) | stdout
                          (each: the spec JSON last; set: {"models": {id: spec}} last)
    timeout_seconds       900; idle_timeout_seconds 300
    max_repair_rounds     2
    review_rounds         1: asks to look at the renders after every model passes
    render                {enabled: true, engines, samples, tile, timeout_seconds} (render.py)
    blender               {executable, timeout_seconds, allow_unpinned} as the backend's

`context`: `run_dir` (requests, specs, renders and logs; default `<out_dir>/.model-author`),
`config` (the factory section: `factory.agents.env_passthrough` names the host's
credential), `policy` (the asset policy; loaded when absent), `design` ({art_direction,
camera}: what the renders and the request add from the game design), `environ` and
`on_event` (passed to Blender's discovery, builds and renders). A requirement a failed gate
sent back carries `feedback` {notes, frames} (pipeline._model_feedback).

The author runs through wgflib.procs with the allowlisted agent environment
(wgflib.agentenv), like the design author and the developer. A host that fails, times out
or goes silent raises ModelAuthorError with `retryable = True`; anything else - not
configured, Blender unusable, still failing after the last repair - is not retryable. A
render that fails is not a refusal: the round goes on without pictures, and there is no
review round to ask for.
"""

import json
import os
import re

from wgflib import agentenv, jsonschema_lite, paths, permpath, procs

from . import blender, gltf, model_quality, modelspec
from . import render as render_mod
from .policy import GENERATED_LICENSE, PolicyError, load_policy

__all__ = ["ModelAuthorError", "produce_model", "produce_models", "SCHEMA_PATH",
           "MAX_REPAIR_ROUNDS", "REVIEW_ROUNDS", "PROMPT", "DEFAULTS", "MODES"]

SCHEMA_PATH = os.path.join(paths.ARTIFACTS, "shared", "model-spec.schema.json")
MAX_REPAIR_ROUNDS = 2
REVIEW_ROUNDS = 1
MODES = ("each", "set")
DEFAULTS = {"kind": "command", "mode": "each", "argv": [], "spec_from": "file",
            "timeout_seconds": 900, "idle_timeout_seconds": 300,
            "max_repair_rounds": MAX_REPAIR_ROUNDS, "review_rounds": REVIEW_ROUNDS,
            "render": {"enabled": True}, "blender": {}}
_MAX_BYTES = 1024 * 1024

# The craft playbooks (core/craft/) the request's `craft` names, in reading order: the 3D
# production art guide carries the reference game's own spec, material table and rig.
MODEL_CRAFT = ("production-art-3d.md", "3d-assets-and-animation.md", "art-direction.md")

_SHAPES = ("boxes, cylinders, cones, spheres, capsules, extruded outlines and lathed "
           "profiles; scaled, rotated, tapered, bevelled, mirrored")
PROMPT = (
    "You are the 3D modeller for this game. Read the request at {request}: one asset "
    "requirement (its role, description and what a player must recognise in it), the game's "
    "palette, the model spec JSON Schema, and the rules. Write a model spec - a recognisable "
    "low-poly object composed of several shaped parts (" + _SHAPES + ") with materials in "
    "the palette's colours - and nothing else, as JSON to {spec}. The craft guides are the "
    "request's `craft`: read them first."
)
PROMPT_STDOUT = (
    "You are the 3D modeller for this game. Read the request at {request}: one asset "
    "requirement (its role, description and what a player must recognise in it), the game's "
    "palette, the model spec JSON Schema, and the rules. Write a model spec - a recognisable "
    "low-poly object composed of several shaped parts (" + _SHAPES + ") with materials in "
    "the palette's colours. The craft guides are the request's `craft`: read them first. End "
    "your answer with the spec as one JSON object."
)
PROMPT_REPAIR = (
    " Your previous spec (the request's `repair.previous_spec`) was refused for the reasons in "
    "`repair.problems`. Return the complete spec again with exactly those fixed."
)
PROMPT_NOTES = (
    " This asset was modelled before, and the running game was judged and sent it back: the "
    "asset's `notes` say why, in the judge's words. Open every PNG in its `frames` - "
    "screenshots of the running game - find this asset in them, and fix what "
    "they show and the notes say. Model it anew - the same spec fails the game again."
)
PROMPT_REPAIR_RENDERS = (
    " What Blender built from it is rendered in `renders` (PNG images: open them with your "
    "file reader) - use them to see the problem."
)
PROMPT_REVIEW = (
    " The Factory built your spec, it passed every check, and it rendered it: `review.renders` "
    "is a contact sheet (left to right: three-quarter, side, top, the game's camera when the "
    "design states one, and that view at the size a player sees it, enlarged) and each view "
    "on its own. Open the images. Judge as a player: at gameplay size, does the silhouette "
    "read as the asset's `readability` line? If it does, return the spec exactly as it is. "
    "If it does not, revise it - make the parts a player recognises it by stand out of the "
    "main body's outline, exaggerate them, give them the palette's accents - and return the "
    "complete revised spec. Say in one line before the JSON what you saw."
)
PROMPT_REVIEW_FILE = (
    " The Factory built your spec, it passed every check, and it rendered it: `review.renders` "
    "is a contact sheet (left to right: three-quarter, side, top, the game's camera when the "
    "design states one, and that view at the size a player sees it, enlarged) and each view "
    "on its own. Open the images. Judge as a player: at gameplay size, does the silhouette "
    "read as the asset's `readability` line? If it does, leave {spec} exactly as it is. If it "
    "does not, edit {spec} - make the parts a player recognises it by stand out of the main "
    "body's outline, exaggerate them, give them the palette's accents. Say in one line what "
    "you saw."
)

PROMPT_SET = (
    "You are the 3D modeller for this game, and you make ALL of its 3D models in this session "
    "as one set. Read the request at {request}: every 3D asset requirement (role, "
    "description, and the `readability` line - what a player must recognise at gameplay "
    "distance), the game's visual identity, art direction and camera, the model spec JSON "
    "Schema and the rules. Read the craft guides in `craft` first: they hold the reference "
    "game's own specs and material table. Then write one model spec per asset - a "
    "recognisable low-poly object composed of shaped parts (" + _SHAPES + ") - all in one "
    "palette, one material language and one level of detail, "
)
PROMPT_SET_NOTES = (
    " The running game was judged and sent some of these models back: each such asset in "
    "`assets` carries `notes` (why, in the judge's words) and `frames` (screenshots of the "
    "running game). Open those frames, find the model in them, and make it anew so what they "
    "show is fixed - the same spec fails the game again."
)
PROMPT_SET_FILE = "each as JSON (and nothing else) to its path in the request's `spec_paths`."
PROMPT_SET_STDOUT = ("and end your answer with one JSON object: {{\"models\": {{\"<asset "
                     "id>\": <spec>, ...}}}}.")
PROMPT_SET_REPAIR = (
    " This is a repair round: Blender built your specs, the Factory judged and rendered them, "
    "and the specs named in the request's `problems` were refused for exactly those reasons. "
    "`renders` holds a contact sheet per built model and `set` all of them side by side "
    "(PNG images: open them with your file reader). Fix the refused specs; change a spec "
    "that was not refused only if the set render shows it does not belong."
)
PROMPT_SET_REVIEW = (
    " This is a review round: every spec passed its checks, and the Factory rendered them. "
    "`renders` holds a contact sheet per model (left to right: three-quarter, side, top, the "
    "game's camera, and that view at the size a player sees it, enlarged) and `set` every "
    "model side by side at its real size. Open every image. For each model, judge as a "
    "player: at gameplay size, does its silhouette read as its `readability` line, and does "
    "the set look like one game? Revise each spec that does not - make the parts a player "
    "recognises it by stand out of the main body's outline, exaggerate them, give them the "
    "palette's accents - and leave every spec that reads exactly as it is: an unchanged spec "
    "is accepted. Write one line per model in your answer: `<id>: reads` or `<id>: revised - "
    "<what you saw>`."
)
PROMPT_SET_REVIEW_FILE = " The spec files hold your previous specs: edit them in place."
PROMPT_SET_REVIEW_STDOUT = (" End with {{\"models\": {{...}}}} holding only the revised specs "
                            "({{\"models\": {{}}}} when every model reads).")

RULES = [
    "Coordinates are glTF's: metres, +Y up, the model faces +Z. Rotations are Euler degrees, "
    "XYZ order. A child part's position and rotation are relative to its parent.",
    "Compose the object from the parts a player recognises it by - a goalkeeper: torso, head, "
    "arms, gloves, legs, boots; a car: body, cabin, wheels, lights; a coin: a disc with a "
    "raised rim and an emblem. One box or one sphere standing for the whole object is a "
    "placeholder and is refused for a readable role.",
    "The silhouette is what reads at gameplay distance. The parts a player recognises a "
    "player or threat model by (wings, limbs, fins, engines, a gap) must stand out of the "
    "main body's outline in at least one view: a hull with small parts inside its own "
    "outline reads as a brick, and the `model.silhouette` check refuses one component "
    "covering more than `quality_bars.max_dominance` of every view's outline.",
    "A round body - a ball, a marble, an orb, when the requirement names one - keeps its "
    "round outline: never reshape it into a drum or a capsule to pass the silhouette check. "
    "Compose it instead: a sphere or icosphere shell plus what the player recognises it by "
    "(a swirl band or ring, a core, a seam, stripes as separate parts). A lone sphere is a "
    "placeholder; a composed ball whose outline is a disk in every view passes "
    "(`quality_bars.round_body`).",
    "Shape each part: `taper` [x, z] narrows or widens its top (a torso wider at the "
    "shoulders), `bevel` (metres) rounds a box's, cylinder's, cone's or extrude's edges, "
    "`capsule` makes limbs, `mirror: \"x\"` writes the other arm, leg, wing or wheel for you "
    "as `<id>-mirror`.",
    "Beyond primitives: `extrude` pulls a flat `outline` [[x, z], ...] (a top view, points in "
    "order round the shape) up to a thickness - swept and delta wings, fins, blades, "
    "chevrons, arrows, angular rock slabs; `lathe` sweeps a `profile` [[radius, y], ...] "
    "round the Y axis - nozzles, bells, domes, turned posts. Rotate an extrude 90 degrees to "
    "stand a fin upright.",
    "Give every part a material, and take the material colours from the palette (`color`: "
    "#rrggbb); a highlight or a dark detail may be a shade of a palette colour.",
    "Leave `pivot` at its default (the centre of the base) unless the object hangs or "
    "floats, and set `fit` to the object's real size (a player 1.8 m tall: "
    "{\"size\": 1.8, \"axis\": \"y\"}).",
    "Stay low-poly: segments 8-16 on round parts, at most 64 parts, and within `budget`.",
    "Animations, if the request's `expectations` declares clips, are named clips of keyed "
    "part transforms; every declared clip must exist under exactly its name.",
]
# What a set adds: the models are one game's.
SET_RULES = [
    "One palette, one material language: define the same material ids with the same values "
    "in every spec that uses them (paint, hull-dark, metal, trim, glow, hazard - whatever "
    "the game needs), and keep each palette role to its job: the player owns its accent, "
    "threats own the danger colour, the environment stays darker than both.",
    "One level of detail: similar bevel sizes, segment counts and part density across the "
    "set; nothing reads as from another game.",
    "Real sizes: each `fit` is the object's size in the game's world, so the set render "
    "shows them at the scale a player sees them side by side.",
]

# A worked example of the shape the author writes - deliberately not any game's asset.
EXAMPLE = {
    "parts": [
        {"id": "body", "shape": "box", "size": [1.6, 0.45, 3.4], "position": [0, 0.45, 0],
         "bevel": 0.08, "material": "paint"},
        {"id": "cabin", "shape": "box", "size": [1.3, 0.45, 1.6], "position": [0, 0.42, -0.2],
         "parent": "body", "taper": [0.8, 0.7], "bevel": 0.05, "material": "glass"},
        {"id": "wheel", "shape": "cylinder", "size": [0.6, 0.3, 0.6],
         "position": [0.78, -0.15, 1.05], "rotation": [0, 0, 90], "parent": "body",
         "bevel": 0.04, "mirror": "x", "material": "tyre"},
        {"id": "wheel-rear", "shape": "cylinder", "size": [0.6, 0.3, 0.6],
         "position": [0.78, -0.15, -1.05], "rotation": [0, 0, 90], "parent": "body",
         "bevel": 0.04, "mirror": "x", "material": "tyre"},
        {"id": "spoiler", "shape": "extrude", "outline": [[0, 0], [1, 0], [0.8, 0.5], [0.1, 0.5]],
         "size": [1.5, 0.05, 0.35], "position": [0, 0.5, -1.55], "parent": "body",
         "material": "tyre"},
        {"id": "light", "shape": "sphere", "size": [0.25, 0.15, 0.08],
         "position": [0.55, 0.05, 1.7], "parent": "body", "mirror": "x", "material": "lamp"},
        {"id": "exhaust", "shape": "lathe", "profile": [[0.6, 0], [1, 0.7], [0.8, 1]],
         "segments": 10, "size": [0.16, 0.25, 0.16], "position": [0.45, -0.1, -1.75],
         "rotation": [-90, 0, 0], "parent": "body", "material": "tyre"},
    ],
    "materials": [{"id": "paint", "color": "#d7263d", "roughness": 0.4},
                  {"id": "glass", "color": "#1b998b", "roughness": 0.2},
                  {"id": "tyre", "color": "#2e294e", "roughness": 0.9},
                  {"id": "lamp", "color": "#f46036", "emissive": "#f46036",
                   "emissive_strength": 2}],
    "fit": {"size": 3.4, "axis": "z"},
    "budget": {"max_triangles": 4000},
}


class ModelAuthorError(RuntimeError):
    """The author could not produce a model that passes. `retryable`: the host failed, timed
    out or went silent, and the same request may succeed again. `problems`: the last
    round's."""

    def __init__(self, message, *, retryable=False, problems=None):
        super().__init__(message)
        self.retryable = retryable
        self.problems = list(problems or [])


def _requirement(requirement):
    """The fields the author and the checks read, from a dict or a Requirement."""
    if isinstance(requirement, dict):
        data = dict(requirement)
    else:
        data = dict(getattr(requirement, "data", None) or {})
        for key in ("id", "kind", "label", "model", "notes", "feedback"):
            value = getattr(requirement, key, None)
            if value is not None:
                data.setdefault(key, value)
    if not data.get("id"):
        raise ModelAuthorError("the requirement has no id")
    kind = data.get("kind") or data.get("type") or "model"
    return {
        "id": data["id"],
        "role": data.get("role"),
        "kind": kind,
        "build_kind": kind if kind in ("model", "environment", "animation") else "model",
        "description": data.get("description") or data.get("label") or data.get("notes") or "",
        "readability": data.get("readability"),
        "spec": data.get("spec"),
        "tier": data.get("tier") or data.get("scope_tier"),
        "count": data.get("count"),
        # A model spec on the requirement is what the delivered GLB is held to (clips,
        # collision, fit, budget), whoever wrote the geometry.
        "expectations": data.get("model") if isinstance(data.get("model"), dict) else None,
        # What a failed gate sent it back for (wgf_assets.feedback): {notes, frames}.
        "feedback": data.get("feedback") if isinstance(data.get("feedback"), dict) else None,
        # What a re-entry report found wrong with the last delivered file.
        "findings": data.get("notes") if isinstance(data.get("notes"), list) else None,
    }


def _last_json_object(text):
    decoder = json.JSONDecoder()
    found, index = None, 0
    while True:
        start = text.find("{", index)
        if start < 0:
            return found
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            index = start + 1
            continue
        if isinstance(value, dict):
            found = value
        index = end


_VALIDATOR = []


def _schema_problems(spec):
    if not _VALIDATOR:
        with open(SCHEMA_PATH, encoding="utf-8") as handle:
            _VALIDATOR.append(jsonschema_lite.Validator(json.load(handle)))
    return [f"schema: {error}" for error in list(_VALIDATOR[0].iter_errors(spec))[:20]]


def _spec_problems(spec, asset_id):
    """Problems a repair can fix in a spec as written."""
    if not isinstance(spec, dict):
        return ["the spec is not a JSON object"]
    problems = _schema_problems(spec) + [f"spec: {p}" for p in modelspec.validate(spec)]
    if not problems and not modelspec.buildable(spec):
        problems.append("spec: it has no parts to build")
    if not problems and any(p["id"] == asset_id for p in modelspec.expand_parts(spec["parts"])):
        problems.append(f"spec: a part may not share the asset's id {asset_id!r}")
    return list(dict.fromkeys(problems))


def _merged(spec, expectations):
    """The authored spec with what the requirement declares and the author left out: the
    requirement's budget, fit and collision proxy win when the spec has none."""
    if not expectations:
        return spec
    merged = dict(spec)
    for key in ("budget", "fit", "collision", "pivot", "lods"):
        if key in expectations and key not in merged:
            merged[key] = expectations[key]
    return merged


def _expectation_problems(summary, expectations, data, name):
    if not expectations:
        return []
    return [f"{code}: {message}" for code, severity, message in gltf.check_expectations(
        summary, modelspec.expectations(expectations), data, name=name) if severity == "error"]


def _read_spec(path):
    """(spec, problems) from a spec file the author wrote."""
    if not os.path.isfile(path):
        return None, [f"the author wrote no spec at {path}"]
    if os.path.getsize(path) > _MAX_BYTES:
        return None, ["the spec is larger than 1 MiB"]
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle), []
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, [f"the spec is not readable JSON: {exc}"]


def _write_json(path, value):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False, default=str)


def _review_lines(text, ids):
    """{id: the author's one-line judgement} from its answer: `<id>: reads | revised - ...`."""
    found = {}
    for line in (text or "").splitlines():
        for asset_id in ids:
            match = re.match(r"^\W*" + re.escape(asset_id) + r"\W*[:\-]\s*(.+)$", line.strip())
            if match and asset_id not in found:
                found[asset_id] = match.group(1).strip()[:400]
    return found


# -- the session -----------------------------------------------------------------------------


class _Model:
    """One asset through the rounds."""

    def __init__(self, req):
        self.req = req
        self.spec = None             # the current spec (merged with the expectations)
        self.problems = []           # the current spec's
        self.data = self.summary = self.quality = self.key = None
        self.best = None             # the last spec that passed: dict
        self.renders = None          # the latest renders of the current build
        self.accepted = False        # the author reviewed it and left it as it was
        self.silhouette = None       # model_quality's outline measures of the current build
        self.history = []
        self.notes = []              # the author's review lines


class _Session:
    def __init__(self, reqs, look, out_dir, settings, context, mode):
        self.context = dict(context or {})
        config = dict(DEFAULTS)
        config.update(settings or {})
        if config.get("kind") != "command":
            raise ModelAuthorError(f"model author kind {config.get('kind')!r}: only "
                                   f"'command' exists")
        argv = config.get("argv") or []
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise ModelAuthorError("the model author's argv is not configured (a non-empty "
                                   "list of strings); there is nothing to run")
        if config.get("spec_from") not in ("file", "stdout"):
            raise ModelAuthorError("the model author's spec_from must be file or stdout")
        self.config, self.argv, self.mode = config, argv, mode
        self.repairs = int(config.get("max_repair_rounds", MAX_REPAIR_ROUNDS))
        self.reviews = int(config.get("review_rounds", REVIEW_ROUNDS))
        render_settings = config.get("render")
        self.render_settings = dict(render_settings) if isinstance(render_settings, dict) \
            else {"enabled": bool(render_settings)}
        self.look = look if isinstance(look, dict) else {}
        design = self.context.get("design") if isinstance(self.context.get("design"),
                                                          dict) else {}
        self.design = {k: design[k] for k in ("art_direction", "camera") if design.get(k)}
        self.out_dir = out_dir

        policy = self.context.get("policy")
        if policy is None:
            try:
                policy = load_policy()
            except PolicyError as exc:
                raise ModelAuthorError(f"asset policy: {exc}")
        self.policy = policy
        self.blender_settings = dict(config.get("blender") or {})
        info = blender.discover(self.blender_settings.get("executable"),
                                environ=self.context.get("environ"))
        pin = dict((getattr(policy, "toolchains", None) or {}).get("blender") or {})
        refusal = (blender.missing_message(info, pin) if info.version is None
                   else blender.check_pin(info, pin, allow_unpinned=bool(
                       self.blender_settings.get("allow_unpinned"))))
        if refusal:
            raise ModelAuthorError(f"the model author needs Blender to build its specs: "
                                   f"{refusal}")
        self.info = info
        run_dir = self.context.get("run_dir") or os.path.join(out_dir, ".model-author")
        self.directory = os.path.join(run_dir, reqs[0]["id"] if mode == "each" else "set")
        os.makedirs(self.directory, exist_ok=True)
        try:
            self.env = agentenv.scrubbed(agentenv.passthrough(self.context.get("config")))
        except ValueError as exc:
            raise ModelAuthorError(str(exc)) from exc
        self.bars = model_quality.load_bars()
        self.models = [_Model(r) for r in reqs]
        self.builds = {}             # spec hash -> (data, report, key) or problem text
        self.asks = 0
        self.set_render = None
        self.render_note = None

    # -- one round's evaluation ------------------------------------------------------------

    def _evaluate(self, model):
        """Build and judge the model's current spec (cached by its hash)."""
        model.data = model.summary = model.quality = model.key = None
        model.silhouette = None
        if model.problems:
            return
        spec, req = model.spec, model.req
        digest = modelspec.spec_hash(spec)
        built = self.builds.get(digest)
        if built is None:
            try:
                built = blender.build_model(
                    self.info, spec, req["id"],
                    timeout=float(self.blender_settings.get("timeout_seconds")
                                  or blender.DEFAULT_TIMEOUT),
                    on_event=self.context.get("on_event"))
            except blender.BlenderError as exc:
                built = f"build: {exc}"
            self.builds[digest] = built
        if isinstance(built, str):
            model.problems = [built]
            return
        data, _report, key = built
        judged = model_quality.assess(data, role=req["role"], visual_identity=self.look,
                                      spec=spec, kind=req["build_kind"],
                                      name=f"{req['id']}.glb", bars=self.bars,
                                      policy=self.policy, author="author:command",
                                      requirement=req)
        problems = [f"{code}: {message}" for code, severity, message in judged["findings"]
                    if severity == "error"]
        problems += _expectation_problems(judged["summary"], req["expectations"], data,
                                          f"{req['id']}.glb")
        # model.valid restates the error findings already listed above.
        problems += [f"quality {c['id']}: {c['summary']}" for c in judged["quality"]["checks"]
                     if c["status"] == "fail" and c["id"] != "model.valid"]
        model.problems = problems
        model.data, model.summary, model.quality, model.key = (
            data, judged["summary"], judged["quality"], key)
        model.silhouette = (judged.get("geometry") or {}).get("silhouette")

    def _render(self, round_index):
        """Render every model that built this round; None on any failure (noted)."""
        if not self.render_settings.get("enabled", True):
            return
        built = [m for m in self.models if m.data is not None]
        for model in self.models:
            model.renders = None
        if not built:
            return
        out = os.path.join(self.directory, f"round{round_index}-renders")
        os.makedirs(out, exist_ok=True)
        entries = []
        for model in built:
            path = os.path.join(out, f"{model.req['id']}.glb")
            with open(path, "wb") as handle:
                handle.write(model.data)
            entries.append({"id": model.req["id"], "glb": path, "role": model.req["role"],
                            "readability": model.req["readability"]})
        settings = {k: v for k, v in self.render_settings.items() if k != "enabled"}
        try:
            report = render_mod.render(self.info, entries, out_dir=out, identity=self.look,
                                       camera=self.design.get("camera"),
                                       lineup=self.mode == "set", settings=settings,
                                       on_event=self.context.get("on_event"))
        except render_mod.RenderError as exc:
            self.render_note = str(exc)
            return
        for model in built:
            entry = report["models"].get(model.req["id"])
            if entry:
                model.renders = {"sheet": entry["sheet"],
                                 "views": {n: v["path"] for n, v in entry["views"].items()},
                                 "measured": {n: {"covers": v["coverage"], "fill": v["fill"]}
                                              for n, v in entry["views"].items()}}
        self.set_render = (report.get("set") or {}).get("path")

    # -- the request -----------------------------------------------------------------------

    def _asset(self, model):
        req = model.req
        asset = {k: req[k] for k in ("id", "role", "kind", "description", "readability",
                                     "spec", "tier", "count") if req.get(k) is not None}
        if req["expectations"]:
            asset["expectations"] = req["expectations"]
        if req["findings"]:
            asset["findings_from_review"] = req["findings"]
        feedback = req.get("feedback") or {}
        if feedback.get("notes"):
            # A failed gate sent it back: the judge's words and the frames of the running
            # game that show the problem (PROMPT_NOTES).
            asset["notes"] = list(feedback["notes"])
            asset["frames"] = [str(f) for f in feedback.get("frames") or []]
        return asset

    def _base_request(self):
        identity = {k: v for k, v in self.look.items() if k != "palette"}
        request = {
            "palette": self.look.get("palette") or [],
            "visual_identity": identity,
            "schema": SCHEMA_PATH,
            "rules": RULES,
            "example": EXAMPLE,
            "quality_bars": self.bars,
            "craft": [os.path.join(paths.CORE, "craft", name) for name in MODEL_CRAFT],
        }
        request.update(self.design)
        return request

    def _measured(self, model):
        out = {}
        if getattr(model, "silhouette", None):
            out["silhouette"] = {"dominance": model.silhouette.get("dominance"),
                                 "view": model.silhouette.get("view"),
                                 "views": model.silhouette.get("views")}
        if model.renders:
            out["renders"] = model.renders["measured"]
        return out or None

    def _command(self, prompt, request_path, spec_path):
        values = {"request": request_path, "spec": spec_path or "",
                  "dir": self.directory, "prompt": ""}
        values["prompt"] = prompt.format(**values)
        try:
            return permpath.format_argv(self.argv, values, ("request", "spec", "dir"))
        except (KeyError, IndexError, ValueError) as exc:
            raise ModelAuthorError(f"the model author's argv has a placeholder this author "
                                   f"does not provide ({exc}); use {{request}}, {{spec}}, "
                                   f"{{dir}}, {{prompt}}, {{dir_rule}}, and double any "
                                   f"literal brace") from exc

    def _run(self, command, stem):
        log_path = os.path.join(self.directory, f"{stem}.log")
        if os.path.exists(log_path):
            os.remove(log_path)
        self.asks += 1
        result = procs.run(command, cwd=self.directory, env=self.env,
                           timeout=self.config.get("timeout_seconds"),
                           idle_timeout=self.config.get("idle_timeout_seconds"),
                           log_path=log_path, heartbeat_seconds=15.0,
                           on_event=self.context.get("on_event"))
        if not result.ok:
            raise ModelAuthorError(
                f"the model author {os.path.basename(command[0])} ended {result.status} "
                f"(exit {result.returncode}); log: {log_path}", retryable=True)
        return result.stdout or ""

    # -- each mode -------------------------------------------------------------------------

    def _ask_one(self, model, round_index, stage):
        """Ask for one model's spec; stage is author | repair | review."""
        stem = f"round{round_index}"
        request_path = os.path.join(self.directory, f"{stem}.request.json")
        spec_path = os.path.join(self.directory, f"{stem}.model.json")
        stdout_mode = self.config["spec_from"] == "stdout"
        for stale in (spec_path,):
            if os.path.exists(stale):
                os.remove(stale)
        request = self._base_request()
        request["asset"] = self._asset(model)
        request["spec_path"] = spec_path
        if stage == "repair":
            request["repair"] = {"round": round_index, "problems": model.problems,
                                 "previous_spec": model.spec}
            if model.renders:
                request["renders"] = model.renders
        elif stage == "review":
            request["review"] = {"round": round_index, "renders": model.renders,
                                 "measured": self._measured(model),
                                 "previous_spec": model.spec}
        if stage != "author" and not stdout_mode and model.spec is not None:
            _write_json(spec_path, model.spec)  # edit in place
        _write_json(request_path, request)
        prompt = PROMPT_STDOUT if stdout_mode else PROMPT
        if stage == "author" and request["asset"].get("notes"):
            prompt += PROMPT_NOTES
        if stage == "repair":
            prompt += PROMPT_REPAIR + (PROMPT_REPAIR_RENDERS if model.renders else "")
        elif stage == "review":
            prompt += PROMPT_REVIEW if stdout_mode else PROMPT_REVIEW_FILE
        text = self._run(self._command(prompt, request_path, spec_path), stem)
        if stage == "review":
            model.notes.extend(_review_lines(text, [model.req["id"]]).values()
                               or [line for line in text.strip().splitlines()[:1]])
        if stdout_mode:
            spec = _last_json_object(text)
            if spec is None:
                return None, ["the author printed no JSON object"]
            return spec, _spec_problems(spec, model.req["id"])
        spec, problems = _read_spec(spec_path)
        if problems:
            return None, problems
        return spec, _spec_problems(spec, model.req["id"])

    # -- set mode --------------------------------------------------------------------------

    def _ask_set(self, round_index, stage):
        """Ask for every model's spec in one session. Returns {id: (spec, problems)} for
        the models the answer touched (a review answer leaves the rest unchanged)."""
        stem = f"round{round_index}"
        request_path = os.path.join(self.directory, f"{stem}.request.json")
        stdout_mode = self.config["spec_from"] == "stdout"
        specs_dir = os.path.join(self.directory, "specs")
        os.makedirs(specs_dir, exist_ok=True)
        spec_paths = {m.req["id"]: os.path.join(specs_dir, f"{m.req['id']}.model.json")
                      for m in self.models}
        before = {}
        for model in self.models:
            path = spec_paths[model.req["id"]]
            if stdout_mode or stage == "author" or model.spec is None:
                if os.path.exists(path):
                    os.remove(path)
            else:
                _write_json(path, model.spec)  # edit in place
            before[model.req["id"]] = (os.path.getmtime(path) if os.path.exists(path)
                                       else None, model.spec)
        request = self._base_request()
        request["mode"] = "set"
        request["set_rules"] = SET_RULES
        request["assets"] = [self._asset(m) for m in self.models]
        request["stage"] = stage
        if not stdout_mode:
            request["spec_paths"] = spec_paths
        if stage in ("repair", "review"):
            request["renders"] = {m.req["id"]: m.renders for m in self.models if m.renders}
            if self.set_render:
                request["set"] = self.set_render
            request["measured"] = {m.req["id"]: self._measured(m) for m in self.models
                                   if self._measured(m)}
            request["accepted"] = [m.req["id"] for m in self.models if m.accepted]
        if stage == "repair":
            request["problems"] = {m.req["id"]: m.problems for m in self.models if m.problems}
        if stdout_mode and stage != "author":
            request["previous"] = {m.req["id"]: m.spec for m in self.models
                                   if m.spec is not None}
        _write_json(request_path, request)
        prompt = PROMPT_SET + (PROMPT_SET_STDOUT if stdout_mode else PROMPT_SET_FILE)
        if stage == "author" and any(a.get("notes") for a in request["assets"]):
            prompt += PROMPT_SET_NOTES
        if stage == "repair":
            prompt += PROMPT_SET_REPAIR
        elif stage == "review":
            prompt += PROMPT_SET_REVIEW + (PROMPT_SET_REVIEW_STDOUT if stdout_mode
                                           else PROMPT_SET_REVIEW_FILE)
        if stage == "repair" and not stdout_mode:
            prompt += PROMPT_SET_REVIEW_FILE
        text = self._run(self._command(prompt, request_path, None), stem)
        lines = _review_lines(text, [m.req["id"] for m in self.models])
        for model in self.models:
            if model.req["id"] in lines:
                model.notes.append(lines[model.req["id"]])

        answers = {}
        if stdout_mode:
            answer = _last_json_object(text)
            models = answer.get("models") if isinstance(answer, dict) else None
            if not isinstance(models, dict):
                if stage == "review":
                    return {}
                problem = "the author printed no {\"models\": {...}} JSON object"
                return {m.req["id"]: (None, [problem]) for m in self.models}
            for model in self.models:
                if model.req["id"] in models:
                    spec = models[model.req["id"]]
                    answers[model.req["id"]] = (spec, _spec_problems(spec, model.req["id"]))
                elif stage == "author":
                    answers[model.req["id"]] = (None, [f"the author's answer has no spec for "
                                                       f"{model.req['id']!r}"])
            return answers
        for model in self.models:
            path = spec_paths[model.req["id"]]
            mtime, previous = before[model.req["id"]]
            if stage != "author" and mtime is not None and os.path.exists(path) \
                    and os.path.getmtime(path) == mtime:
                continue  # untouched: the author left it as it was
            spec, problems = _read_spec(path)
            answers[model.req["id"]] = (spec, problems or _spec_problems(spec,
                                                                         model.req["id"]))
        return answers

    # -- the rounds ------------------------------------------------------------------------

    def _apply(self, model, spec, problems, stage):
        """Take an answered spec: "changed", "unchanged" (the current spec, as it was), or
        "ignored" (a review answer that is no spec at all: the passing spec stands)."""
        if spec is not None and not problems:
            spec = _merged(spec, model.req["expectations"])
        if stage == "review" and spec is None:
            model.notes.append("the review answer held no readable spec: " + "; ".join(
                problems[:2]))
            return "ignored"
        if stage == "review" and model.spec is not None \
                and modelspec.spec_hash(spec) == modelspec.spec_hash(model.spec):
            return "unchanged"
        model.spec = spec
        model.problems = list(problems)
        return "changed"

    def run(self):
        stage, round_index = "author", 0
        repairs, reviews = self.repairs, self.reviews
        while True:
            if self.mode == "each":
                model = self.models[0]
                spec, problems = self._ask_one(model, round_index, stage)
                answers = {model.req["id"]: (spec, problems)}
            else:
                answers = self._ask_set(round_index, stage)
            changed = []
            for model in self.models:
                if model.req["id"] not in answers:
                    if stage == "review" and model.problems == [] and model.data is not None:
                        model.accepted = True
                    continue
                spec, problems = answers[model.req["id"]]
                taken = self._apply(model, spec, problems, stage)
                if taken == "changed":
                    model.accepted = False
                    changed.append(model)
                elif taken == "unchanged":
                    model.accepted = True
            for model in changed:
                self._evaluate(model)
            for model in self.models:
                model.history.append({"round": round_index, "stage": stage,
                                      "problems": list(model.problems),
                                      "changed": model in changed})
                if model.data is not None and not model.problems:
                    model.best = {"spec": model.spec, "data": model.data,
                                  "summary": model.summary, "quality": model.quality,
                                  "key": model.key, "round": round_index}
            if changed:
                self._render(round_index)
            failing = [m for m in self.models if m.problems]
            if failing and repairs > 0:
                stage, repairs = "repair", repairs - 1
            elif (not failing or self.mode == "set") and reviews > 0 and any(
                    m.renders and not m.problems and not m.accepted for m in self.models):
                stage, reviews = "review", reviews - 1
            else:
                break
            round_index += 1
        return self._results()

    def _results(self):
        results, errors = {}, {}
        for model in self.models:
            req = model.req
            best = model.best
            if best is None:
                problems = model.problems or ["no spec was accepted"]
                errors[req["id"]] = ModelAuthorError(
                    f"the model author's spec for {req['id']!r} still fails after "
                    f"{self.repairs} repair round(s): " + "; ".join(problems[:6]),
                    problems=problems)
                continue
            os.makedirs(self.out_dir, exist_ok=True)
            path = os.path.abspath(os.path.join(self.out_dir, f"{req['id']}.glb"))
            with open(path, "wb") as handle:
                handle.write(best["data"])
            accepted_dir = self.directory if self.mode == "each" else os.path.join(
                self.directory, req["id"])
            os.makedirs(accepted_dir, exist_ok=True)
            _write_json(os.path.join(accepted_dir, "accepted.model.json"), best["spec"])
            parts = len(modelspec.expand_parts(best["spec"]["parts"]))
            reviewed = any(h["stage"] == "review" for h in model.history)
            dropped = model.spec is not best["spec"] and model.problems
            review = None
            if reviewed:
                review = {"rounds": sum(1 for h in model.history if h["stage"] == "review"),
                          "reads": bool(model.accepted),
                          "note": " | ".join(model.notes)[:600] or None}
            notes = (f"Authored as a model spec of {parts} parts by the command author "
                     f"({'set' if self.mode == 'set' else 'own'} session, {self.asks} "
                     f"ask(s)), built by Blender {self.info.version_string}, key "
                     f"{best['key']}.")
            if review:
                notes += (" Self-reviewed from renders: "
                          + ("the author judged that it reads." if review["reads"] else
                             "the review rounds ended with a revision; the last passing "
                             "spec is the model."))
            elif self.render_note:
                notes += f" Not rendered: {self.render_note[:200]}"
            if dropped:
                notes += " The last revision failed its checks and was dropped."
            results[req["id"]] = {
                "files": [path], "quality": best["quality"], "source": "ai-generated",
                "license": GENERATED_LICENSE, "placeholder": False, "notes": notes,
                "spec": best["spec"], "model": best["summary"], "rounds": self.asks,
                "history": model.history, "renders": model.renders, "review": review}
        return results, errors


def produce_model(requirement, visual_identity, out_dir, settings, context=None):
    """Author, build, render and judge one model in its own session. Returns the result dict
    described in the module docstring; raises ModelAuthorError when no round produced a
    passing model."""
    req = _requirement(requirement)
    session = _Session([req], visual_identity, out_dir, settings, context, "each")
    results, errors = session.run()
    if req["id"] in errors:
        raise errors[req["id"]]
    return results[req["id"]]


def produce_models(requirements, visual_identity, out_dir, settings, context=None):
    """Author every requirement in one set session. {results, errors, set_render, rounds}:
    a requirement with no passing model is in `errors` (a ModelAuthorError each); a session
    that cannot run at all raises."""
    reqs = [_requirement(r) for r in requirements]
    if not reqs:
        return {"results": {}, "errors": {}, "set_render": None, "rounds": 0}
    ids = [r["id"] for r in reqs]
    if len(set(ids)) != len(ids):
        raise ModelAuthorError(f"duplicate requirement ids in the set: {ids}")
    session = _Session(reqs, visual_identity, out_dir, settings, context, "set")
    results, errors = session.run()
    return {"results": results, "errors": errors, "set_render": session.set_render,
            "rounds": session.asks}
