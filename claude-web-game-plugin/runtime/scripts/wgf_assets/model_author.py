"""The `author` source for 3D: an agent writes a model spec, the pinned Blender builds it.

A requirement of a readable role - a keeper, a car, a coin - deserves a model a player
recognises, not a cube. Nothing in the pipeline could make one: the Blender backend builds a
model spec (core/artifacts/shared/model-spec.schema.json) but nobody wrote specs. Here an
agent author does, and everything after it is the Factory's own and unchanged:

    requirement + visual identity
      -> author (a command: the agent host)       writes a model spec for the requirement
      -> modelspec.validate + the schema           a spec that is not one is shown back
      -> blender.build_model (pinned 4.5, headless) a build failure is shown back
      -> gltf.inspect + model_quality.assess       a model that fails its bars is shown back
      -> up to `max_repair_rounds` (2) more rounds with exactly those problems, then fail

The author only writes a SPEC. It never touches Blender, the GLB or the verdict: an author
cannot mark its own homework, and nothing here relaxes a check to let a spec through.

    result = produce_model(requirement, visual_identity, out_dir, settings, context)
    result = {"files": [<out_dir>/<id>.glb], "quality": {verdict, checks, primitive_only, ...},
              "source": "ai-generated", "license": "LicenseRef-factory-generated",
              "placeholder": False, "notes": "...", "spec": {...}, "model": {...summary}}

`requirement` is a build_spec asset (`id`, `role`, `description`, `readability`, `spec`) or
an asset requirement (`requirements.Requirement`, or its dict: `kind`, `label`, `model` -
whose declared clips, collision, fit and budget the authored spec must meet). `settings`:

    kind                  "command" (the only kind)
    argv                  the author's command; placeholders, per element, never re-formatted:
                          {request} the request JSON, {spec} where to write the spec JSON,
                          {prompt} a one-paragraph instruction
    spec_from             file (default: the author writes {spec}) | stdout (prints it last)
    timeout_seconds       900; idle_timeout_seconds 300
    max_repair_rounds     2
    blender               {executable, timeout_seconds, allow_unpinned} as the backend's

`context`: `run_dir` (requests, specs and logs; default `<out_dir>/.model-author`), `config`
(the factory section: `factory.agents.env_passthrough` names the host's credential),
`policy` (the asset policy; loaded when absent), `environ` and `on_event` (passed to
Blender's discovery and build).

The author runs through wgflib.procs with the allowlisted agent environment
(wgflib.agentenv), like the design author and the developer. A host that fails, times out
or goes silent raises ModelAuthorError with `retryable = True`; anything else - not
configured, Blender unusable, still failing after the last repair - is not retryable.
"""

import json
import os

from wgflib import agentenv, jsonschema_lite, paths, procs

from . import blender, gltf, model_quality, modelspec
from .policy import GENERATED_LICENSE, PolicyError, load_policy

__all__ = ["ModelAuthorError", "produce_model", "SCHEMA_PATH", "MAX_REPAIR_ROUNDS", "PROMPT",
           "DEFAULTS"]

SCHEMA_PATH = os.path.join(paths.ARTIFACTS, "shared", "model-spec.schema.json")
MAX_REPAIR_ROUNDS = 2
DEFAULTS = {"kind": "command", "argv": [], "spec_from": "file", "timeout_seconds": 900,
            "idle_timeout_seconds": 300, "max_repair_rounds": MAX_REPAIR_ROUNDS, "blender": {}}
_MAX_BYTES = 1024 * 1024

PROMPT = (
    "You are the 3D modeller for this game. Read the request at {request}: one asset "
    "requirement (its role, description and what a player must recognise in it), the game's "
    "palette, the model spec JSON Schema, and the rules. Write a model spec - a recognisable "
    "low-poly object composed of several shaped parts (boxes, cylinders, cones, spheres, "
    "capsules; scaled, rotated, tapered, bevelled, mirrored) with materials in the palette's "
    "colours - and nothing else, as JSON to {spec}."
)
PROMPT_STDOUT = (
    "You are the 3D modeller for this game. Read the request at {request}: one asset "
    "requirement (its role, description and what a player must recognise in it), the game's "
    "palette, the model spec JSON Schema, and the rules. Write a model spec - a recognisable "
    "low-poly object composed of several shaped parts (boxes, cylinders, cones, spheres, "
    "capsules; scaled, rotated, tapered, bevelled, mirrored) with materials in the palette's "
    "colours. End your answer with the spec as one JSON object."
)
PROMPT_REPAIR = (
    " Your previous spec (the request's `repair.previous_spec`) was refused for the reasons in "
    "`repair.problems`. Return the complete spec again with exactly those fixed."
)

RULES = [
    "Coordinates are glTF's: metres, +Y up, the model faces +Z. Rotations are Euler degrees, "
    "XYZ order. A child part's position and rotation are relative to its parent.",
    "Compose the object from the parts a player recognises it by - a goalkeeper: torso, head, "
    "arms, gloves, legs, boots; a car: body, cabin, wheels, lights; a coin: a disc with a "
    "raised rim and an emblem. One box or one sphere standing for the whole object is a "
    "placeholder and is refused for a readable role.",
    "Shape each part: `taper` [x, z] narrows or widens its top (a torso wider at the "
    "shoulders), `bevel` (metres) rounds a box's or cylinder's edges, `capsule` makes limbs, "
    "`mirror: \"x\"` writes the other arm, leg or wheel for you as `<id>-mirror`.",
    "Give every part a material, and take the material colours from the palette (`color`: "
    "#rrggbb); a highlight or a dark detail may be a shade of a palette colour.",
    "Leave `pivot` at its default (the centre of the base) unless the object hangs or "
    "floats, and set `fit` to the object's real size (a player 1.8 m tall: "
    "{\"size\": 1.8, \"axis\": \"y\"}).",
    "Stay low-poly: segments 8-16 on round parts, at most 64 parts, and within `budget`.",
    "Animations, if the request's `expectations` declares clips, are named clips of keyed "
    "part transforms; every declared clip must exist under exactly its name.",
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
        {"id": "light", "shape": "sphere", "size": [0.25, 0.15, 0.08],
         "position": [0.55, 0.05, 1.7], "parent": "body", "mirror": "x", "material": "lamp"},
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
        for key in ("id", "kind", "label", "model", "notes"):
            value = getattr(requirement, key, None)
            if value is not None:
                data.setdefault(key, value)
    if not data.get("id"):
        raise ModelAuthorError("the requirement has no id")
    return {
        "id": data["id"],
        "role": data.get("role"),
        "kind": data.get("kind") or data.get("type") or "model",
        "description": data.get("description") or data.get("label") or data.get("notes") or "",
        "readability": data.get("readability"),
        "spec": data.get("spec"),
        "tier": data.get("tier") or data.get("scope_tier"),
        # A model spec on the requirement is what the delivered GLB is held to (clips,
        # collision, fit, budget), whoever wrote the geometry.
        "expectations": data.get("model") if isinstance(data.get("model"), dict) else None,
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


def produce_model(requirement, visual_identity, out_dir, settings, context=None):
    """Author, build and judge one model. Returns the result dict described in the module
    docstring; raises ModelAuthorError when no round produced a passing model."""
    req = _requirement(requirement)
    context = dict(context or {})
    config = dict(DEFAULTS)
    config.update(settings or {})
    if config.get("kind") != "command":
        raise ModelAuthorError(f"model author kind {config.get('kind')!r}: only 'command' "
                               f"exists")
    argv = config.get("argv") or []
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise ModelAuthorError("the model author's argv is not configured (a non-empty list "
                               "of strings); there is nothing to run")
    if config.get("spec_from") not in ("file", "stdout"):
        raise ModelAuthorError("the model author's spec_from must be file or stdout")
    rounds = int(config.get("max_repair_rounds", MAX_REPAIR_ROUNDS))

    policy = context.get("policy")
    if policy is None:
        try:
            policy = load_policy()
        except PolicyError as exc:
            raise ModelAuthorError(f"asset policy: {exc}")
    blender_settings = dict(config.get("blender") or {})
    info = blender.discover(blender_settings.get("executable"), environ=context.get("environ"))
    pin = dict((getattr(policy, "toolchains", None) or {}).get("blender") or {})
    refusal = (blender.missing_message(info, pin) if info.version is None
               else blender.check_pin(info, pin,
                                      allow_unpinned=bool(blender_settings.get("allow_unpinned"))))
    if refusal:
        raise ModelAuthorError(f"the model author needs Blender to build its specs: {refusal}")

    run_dir = context.get("run_dir") or os.path.join(out_dir, ".model-author")
    directory = os.path.join(run_dir, req["id"])
    os.makedirs(directory, exist_ok=True)
    try:
        env = agentenv.scrubbed(agentenv.passthrough(context.get("config")))
    except ValueError as exc:
        raise ModelAuthorError(str(exc)) from exc
    bars = model_quality.load_bars()
    look = visual_identity if isinstance(visual_identity, dict) else {}
    kind = req["kind"] if req["kind"] in ("model", "environment", "animation") else "model"

    repair = None
    history = []
    for round_index in range(rounds + 1):
        stem = f"round{round_index}"
        spec, problems = _ask(req, look, bars, config, argv, env, directory, stem, repair,
                              context)
        data = summary = quality = None
        if not problems:
            spec = _merged(spec, req["expectations"])
            try:
                data, report, key = blender.build_model(
                    info, spec, req["id"],
                    timeout=float(blender_settings.get("timeout_seconds")
                                  or blender.DEFAULT_TIMEOUT),
                    on_event=context.get("on_event"))
            except blender.BlenderError as exc:
                problems = [f"build: {exc}"]
        if data is not None:
            judged = model_quality.assess(data, role=req["role"], visual_identity=look,
                                          spec=spec, kind=kind, name=f"{req['id']}.glb",
                                          bars=bars, policy=policy, author="author:command")
            quality, summary = judged["quality"], judged["summary"]
            problems = [f"{code}: {message}" for code, severity, message in judged["findings"]
                        if severity == "error"]
            problems += _expectation_problems(summary, req["expectations"], data,
                                              f"{req['id']}.glb")
            # model.valid restates the error findings already listed above.
            problems += [f"quality {c['id']}: {c['summary']}" for c in quality["checks"]
                         if c["status"] == "fail" and c["id"] != "model.valid"]
        history.append({"round": round_index, "problems": problems})
        if not problems:
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.abspath(os.path.join(out_dir, f"{req['id']}.glb"))
            with open(path, "wb") as handle:
                handle.write(data)
            with open(os.path.join(directory, "accepted.model.json"), "w", encoding="utf-8",
                      newline="\n") as handle:
                json.dump(spec, handle, indent=2, sort_keys=True)
            parts = len(modelspec.expand_parts(spec["parts"]))
            notes = (f"Authored as a model spec of {parts} parts by the command author "
                     f"({round_index} repair round(s)), built by Blender "
                     f"{info.version_string}, key {key}.")
            return {"files": [path], "quality": quality, "source": "ai-generated",
                    "license": GENERATED_LICENSE, "placeholder": False, "notes": notes,
                    "spec": spec, "model": summary, "rounds": round_index + 1,
                    "history": history}
        repair = {"round": round_index + 1, "problems": problems, "previous_spec": spec}
    raise ModelAuthorError(
        f"the model author's spec for {req['id']!r} still fails after {rounds} repair "
        f"round(s): " + "; ".join(problems[:6]), problems=problems)


def _ask(req, look, bars, config, argv, env, directory, stem, repair, context):
    """(spec, problems) from one run of the author. Problems a repair can fix - a spec that
    is not JSON, not a spec, or not buildable - come back as problems; a host that failed
    raises."""
    request_path = os.path.join(directory, f"{stem}.request.json")
    spec_path = os.path.join(directory, f"{stem}.model.json")
    log_path = os.path.join(directory, f"{stem}.log")
    for stale in (spec_path, log_path):
        if os.path.exists(stale):
            os.remove(stale)
    request = {
        "asset": {k: req[k] for k in ("id", "role", "kind", "description", "readability",
                                      "spec", "tier") if req.get(k) is not None},
        "palette": look.get("palette") or [],
        "visual_identity": {k: look[k] for k in ("concept", "shape_language", "texture",
                                                 "avoid", "primitive_style") if k in look},
        "schema": SCHEMA_PATH,
        "rules": RULES,
        "example": EXAMPLE,
        "quality_bars": bars,
        "spec_path": spec_path,
    }
    if req["expectations"]:
        request["expectations"] = req["expectations"]
    if repair:
        request["repair"] = repair
    with open(request_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(request, handle, indent=2, ensure_ascii=False, default=str)

    stdout_mode = config["spec_from"] == "stdout"
    values = {"request": request_path, "spec": spec_path}
    values["prompt"] = (PROMPT_STDOUT if stdout_mode else PROMPT).format(**values)
    if repair:
        values["prompt"] += PROMPT_REPAIR
    try:
        command = [part.format(**values) for part in argv]
    except (KeyError, IndexError, ValueError) as exc:
        raise ModelAuthorError(f"the model author's argv has a placeholder this author does "
                               f"not provide ({exc}); use {{request}}, {{spec}}, {{prompt}}, "
                               f"and double any literal brace") from exc
    result = procs.run(command, cwd=directory, env=env,
                       timeout=config.get("timeout_seconds"),
                       idle_timeout=config.get("idle_timeout_seconds"),
                       log_path=log_path, heartbeat_seconds=15.0,
                       on_event=context.get("on_event"))
    if not result.ok:
        raise ModelAuthorError(
            f"the model author {os.path.basename(command[0])} ended {result.status} "
            f"(exit {result.returncode}); log: {log_path}", retryable=True)

    if stdout_mode:
        spec = _last_json_object(result.stdout or "")
        if spec is None:
            return None, ["the author printed no JSON object"]
    else:
        if not os.path.isfile(spec_path):
            return None, [f"the author wrote no spec at {spec_path}"]
        if os.path.getsize(spec_path) > _MAX_BYTES:
            return None, ["the spec is larger than 1 MiB"]
        try:
            with open(spec_path, encoding="utf-8") as handle:
                spec = json.load(handle)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            return None, [f"the spec is not readable JSON: {exc}"]
    if not isinstance(spec, dict):
        return spec, ["the spec is not a JSON object"]
    problems = _schema_problems(spec) + [f"spec: {p}" for p in modelspec.validate(spec)]
    if not problems and not modelspec.buildable(spec):
        problems.append("spec: it has no parts to build")
    if not problems and any(p["id"] == req["id"]
                            for p in modelspec.expand_parts(spec["parts"])):
        problems.append(f"spec: a part may not share the asset's id {req['id']!r}")
    return spec, list(dict.fromkeys(problems))
