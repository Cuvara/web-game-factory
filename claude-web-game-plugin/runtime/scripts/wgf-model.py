#!/usr/bin/env python3
"""3D models outside a workflow run: is Blender usable, build one spec, check one GLB.

    python3 scripts/wgf-model.py doctor [--blender PATH] [--json]
        Where Blender is, which version, and whether it is the pinned series.
        Exit 0 usable, 2 not usable (the message says what to do).

    python3 scripts/wgf-model.py build SPEC.json --id ID -o OUT.glb [--blender PATH]
                                      [--kind model] [--twice] [--allow-unpinned] [--json]
        Build a model spec (the `model` object of an asset requirement) headless, stamp it,
        and check it. --twice builds it again and fails unless the bytes are identical.
        Exit 0 clean, 1 an error-severity finding or a failed build, 2 Blender not usable.

    python3 scripts/wgf-model.py inspect FILE.glb [--spec SPEC.json] [--kind model] [--json]
                                        [--role ROLE] [--palette HEX,HEX] [--primitive-style]
                                        [--design GAME-DESIGN.json [--asset ID]]
        Read and check a GLB or .gltf without Blender: structure, references, transforms,
        triangles, textures, clips, LODs, collision proxy; and, with --spec, what it declares.
        Then its quality (core/reference/asset-quality.yaml `models`): pieces and the
        primitive each one is, triangles, normals, palette colours, bounds, primitive_only,
        and a verdict for the role. --design reads the palette and primitive_style from a
        game design's build_spec.visual_identity, and with --asset the role of that asset.
        Exit 0 clean, 1 an error-severity finding, or a failed quality verdict when a role
        was given (--role, or --design with --asset).

    python3 scripts/wgf-model.py render [ID=]FILE.glb ... -o DIR [--design GAME-DESIGN.json]
                                       [--palette HEX,HEX] [--camera TEXT] [--role ROLE]
                                       [--engine NAME] [--no-set] [--json]
        Render each GLB with the pinned Blender to a contact sheet (three-quarter, side, top,
        the game's camera and the gameplay size), lit by the palette's rig, and all of them
        side by side at their real size (DIR/set.png). What the model author is shown.
        Exit 0 rendered, 1 a render failed, 2 Blender not usable.

Standard library only (Blender itself for `build` and `render`); run from the repository root.
See docs/blender-pipeline.md.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wgf_assets import blender, gltf, model_quality, modelspec  # noqa: E402
from wgf_assets import render as render_mod  # noqa: E402
from wgf_assets.policy import PolicyError, load_policy  # noqa: E402


def _policy():
    try:
        return load_policy()
    except PolicyError as exc:
        print(f"wgf-model: {exc}", file=sys.stderr)
        sys.exit(1)


def _print(payload, as_json, lines):
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for line in lines:
            print(line)


def _findings_lines(findings):
    return [f"  {severity:<7} {code:<28} {message}" for code, severity, message in findings] \
        or ["  no findings"]


def _check(data, name, kind, spec, policy):
    kind_policy = policy.kind(kind)
    inspection = gltf.inspect(data, name=name, kind=kind)
    findings = list(inspection.findings)
    if kind_policy.max_bytes and len(data) > kind_policy.max_bytes:
        findings.append(("too-large", "warning",
                         f"{name}: {len(data)} bytes; {kind} budget is {kind_policy.max_bytes}"))
    findings += gltf.check_expectations(inspection.summary,
                                        modelspec.expectations(spec, kind_policy), data,
                                        name=name)
    return inspection.summary, findings


def doctor(args):
    policy = _policy()
    pin = policy.toolchains.get("blender") or {}
    info = blender.discover(args.blender)
    problem = (blender.missing_message(info, pin) if info.version is None
               else blender.check_pin(info, pin))
    payload = {"blender": info.to_dict(), "pin": pin, "usable": problem is None,
               "problem": problem}
    lines = [f"pin         Blender {pin.get('series')}.x (tested {pin.get('tested')})",
             f"executable  {info.executable or '-'} ({info.source or 'not found'})",
             f"version     {info.raw or info.version_string or '-'}",
             "status      " + ("usable" if problem is None else f"NOT USABLE: {problem}")]
    _print(payload, args.json, lines)
    return 0 if problem is None else 2


def build(args):
    policy = _policy()
    pin = policy.toolchains.get("blender") or {}
    with open(args.spec, encoding="utf-8") as handle:
        spec = json.load(handle)
    problems = modelspec.validate(spec)
    if problems:
        print("wgf-model: invalid model spec:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    info = blender.discover(args.blender)
    problem = (blender.missing_message(info, pin) if info.version is None
               else blender.check_pin(info, pin, allow_unpinned=args.allow_unpinned))
    if problem:
        print(f"wgf-model: {problem}", file=sys.stderr)
        return 2
    try:
        data, report, key = blender.build_model(info, spec, args.id)
        again = blender.build_model(info, spec, args.id)[0] if args.twice else None
    except blender.BlenderError as exc:
        print(f"wgf-model: {exc}", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as handle:
        handle.write(data)
    summary, findings = _check(data, args.out, args.kind, spec, policy)
    deterministic = None if again is None else again == data
    if deterministic is False:
        findings.append(("model-invalid", "error",
                         f"{args.out}: two builds of the same spec differ; the output is not "
                         f"reproducible on this machine"))
    payload = {"out": args.out, "bytes": len(data), "key": key, "blender": info.version_string,
               "exporter": report.get("exporter"), "deterministic": deterministic,
               "summary": summary, "findings": [dict(zip(("code", "severity", "message"), f))
                                                for f in findings]}
    lines = [f"built       {args.out} ({len(data)} bytes) with Blender {info.version_string}",
             f"key         {key}"]
    if deterministic is not None:
        lines.append(f"twice       {'identical bytes' if deterministic else 'DIFFERENT bytes'}")
    if summary:
        lines.append(f"model       {summary['triangles']} triangles, dimensions "
                     f"{summary.get('dimensions')}, clips "
                     f"{[c['name'] for c in summary['animations']]}, LODs "
                     f"{[l['level'] for l in summary['lods']]}, collision "
                     f"{(summary.get('collision') or {}).get('shape')}")
    _print(payload, args.json, lines + ["findings"] + _findings_lines(findings))
    return 1 if any(f[1] == "error" for f in findings) else 0


def inspect_command(args):
    policy = _policy()
    with open(args.file, "rb") as handle:
        data = handle.read()
    spec = None
    if args.spec:
        with open(args.spec, encoding="utf-8") as handle:
            spec = json.load(handle)
        problems = modelspec.validate(spec)
        if problems:
            print("wgf-model: invalid model spec:\n  " + "\n  ".join(problems), file=sys.stderr)
            return 1
    summary, findings = _check(data, args.file, args.kind, spec, policy)
    try:
        role, look = _judging(args)
    except (OSError, ValueError) as exc:
        print(f"wgf-model: {exc}", file=sys.stderr)
        return 1
    judged = model_quality.assess(data, role=role, visual_identity=look, spec=spec,
                                  kind=args.kind, name=args.file, policy=policy)
    quality = judged["quality"]
    stamp = blender.read_stamp(data)
    payload = {"file": args.file, "bytes": len(data), "summary": summary, "stamp": stamp,
               "role": role, "quality": quality,
               "pieces": (judged["geometry"] or {}).get("pieces"),
               "findings": [dict(zip(("code", "severity", "message"), f)) for f in findings]}
    lines = [f"file        {args.file} ({len(data)} bytes)"]
    if stamp:
        lines.append(f"generated   Blender {stamp.get('blender')}, key {stamp.get('key')}")
    if summary:
        lines += [f"triangles   {summary['triangles']} (vertices {summary['vertices']})",
                  f"dimensions  {summary.get('dimensions')} m",
                  f"materials   {summary['materials']}",
                  f"textures    {summary['textures']}",
                  f"clips       {[(c['name'], c['duration']) for c in summary['animations']]}",
                  f"lods        {summary['lods']}",
                  f"collision   {summary.get('collision')}"]
    lines += _quality_lines(quality, judged["geometry"], role)
    _print(payload, args.json, lines + ["findings"] + _findings_lines(findings))
    failed = role is not None and quality["verdict"] == "fail"
    return 1 if failed or any(f[1] == "error" for f in findings) else 0


def _judging(args):
    """(role, visual identity) from --design/--asset, overridden by --role, --palette and
    --primitive-style."""
    role, look = None, {}
    if args.design:
        with open(args.design, encoding="utf-8") as handle:
            design = json.load(handle)
        build_spec = design.get("build_spec") or {}
        look = dict(build_spec.get("visual_identity") or {})
        if args.asset:
            asset = next((a for a in build_spec.get("assets") or []
                          if a.get("id") == args.asset), None)
            if asset is None:
                raise ValueError(f"{args.design}: no build_spec.assets entry {args.asset!r}")
            role = asset.get("role")
    if args.role:
        role = args.role
    if args.palette:
        look["palette"] = [{"hex": h.strip()} for h in args.palette.split(",") if h.strip()]
    if args.primitive_style:
        look["primitive_style"] = {"reason": "stated on the command line"}
    return role, look


def _quality_lines(quality, geometry, role):
    shapes = {}
    for piece in (geometry or {}).get("pieces") or []:
        name = piece["shape"] or "modelled"
        shapes[name] = shapes.get(name, 0) + 1
    lines = [f"quality     {quality['verdict'].upper()} for role {role or 'unset'}: "
             f"{quality['parts']} piece(s) ({', '.join(f'{n} {s}' for s, n in sorted(shapes.items())) or '-'}), "
             f"primitive_only {quality['primitive_only']}, {quality['colors']} colour(s)"]
    lines += [f"  {c['status']:<7} {c['id']:<18} {c['summary']}" for c in quality["checks"]]
    return lines


def render_command(args):
    policy = _policy()
    pin = policy.toolchains.get("blender") or {}
    info = blender.discover(args.blender)
    problem = (blender.missing_message(info, pin) if info.version is None
               else blender.check_pin(info, pin, allow_unpinned=args.allow_unpinned))
    if problem:
        print(f"wgf-model: {problem}", file=sys.stderr)
        return 2
    look = {}
    camera = args.camera
    roles, readability = {}, {}
    if args.design:
        with open(args.design, encoding="utf-8") as handle:
            design = json.load(handle)
        build_spec = design.get("build_spec") or {}
        look = dict(build_spec.get("visual_identity") or {})
        camera = camera or (design.get("engine") or {}).get("camera")
        for asset in build_spec.get("assets") or []:
            if isinstance(asset, dict) and asset.get("id"):
                roles[asset["id"]] = asset.get("role")
                readability[asset["id"]] = asset.get("readability")
    if args.palette:
        look["palette"] = [{"hex": h.strip()} for h in args.palette.split(",") if h.strip()]
    models = []
    for path in args.files:
        model_id, _, file_path = path.rpartition("=") if "=" in path else (None, None, path)
        model_id = model_id or os.path.splitext(os.path.basename(file_path))[0]
        models.append({"id": model_id, "glb": file_path, "role": args.role or roles.get(model_id),
                       "readability": readability.get(model_id)})
    settings = {}
    if args.engine:
        settings["engines"] = [args.engine]
    try:
        report = render_mod.render(info, models, out_dir=args.out, identity=look, camera=camera,
                                   lineup=not args.no_set, settings=settings)
    except render_mod.RenderError as exc:
        print(f"wgf-model: {exc}", file=sys.stderr)
        return 1
    lines = [f"engine      {report['engine']}"]
    for model_id, entry in report["models"].items():
        lines.append(f"{model_id:<12}{entry['sheet']}")
        for name, view in entry["views"].items():
            lines.append(f"  {name:<14} {view['pixels']:>4} px  covers {view['coverage']:.0%}"
                         f"  fill {view['fill'] if view['fill'] is not None else '-'}")
    if report.get("set"):
        lines.append(f"set         {report['set']['path']} ({', '.join(report['set']['order'])})")
    _print(report, args.json, lines)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("doctor", help="find and check Blender")
    p.add_argument("--blender", help="the Blender executable (else $WGF_BLENDER, else PATH)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=doctor)
    p = sub.add_parser("build", help="build a model spec into a GLB")
    p.add_argument("spec")
    p.add_argument("--id", required=True, help="the asset id: the GLB's root node name")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--kind", default="model", choices=["model", "environment", "animation"])
    p.add_argument("--blender")
    p.add_argument("--twice", action="store_true", help="build twice; fail unless identical")
    p.add_argument("--allow-unpinned", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=build)
    p = sub.add_parser("inspect", help="check a GLB or .gltf without Blender")
    p.add_argument("file")
    p.add_argument("--spec", help="a model spec whose declarations the file must meet")
    p.add_argument("--kind", default="model", choices=["model", "environment", "animation"])
    p.add_argument("--role", help="the requirement's role (player, threat, prop, ...): judge "
                                  "the model for it; a failed verdict exits 1")
    p.add_argument("--palette", help="comma-separated #rrggbb colours the materials must use")
    p.add_argument("--primitive-style", action="store_true",
                   help="the art direction is geometric: primitives are allowed for any role")
    p.add_argument("--design", help="a game-design JSON: palette and primitive_style from its "
                                    "build_spec.visual_identity")
    p.add_argument("--asset", help="with --design: the build_spec.assets id whose role to use")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=inspect_command)
    p = sub.add_parser("render", help="render GLBs to contact sheets with the pinned Blender")
    p.add_argument("files", nargs="+", help="GLB files, each optionally ID=PATH")
    p.add_argument("-o", "--out", required=True, help="where the PNGs go")
    p.add_argument("--design", help="a game-design JSON: palette, camera, roles, readability")
    p.add_argument("--palette", help="comma-separated #rrggbb colours: the light rig's")
    p.add_argument("--camera", help="the game's camera, as the design states it ('chase "
                                    "camera, slightly high'): adds the game and gameplay views")
    p.add_argument("--role", help="the role of every file (else from --design)")
    p.add_argument("--engine", help="one Blender engine (BLENDER_EEVEE_NEXT, CYCLES, ...)")
    p.add_argument("--no-set", action="store_true", help="no set lineup")
    p.add_argument("--blender")
    p.add_argument("--allow-unpinned", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=render_command)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
