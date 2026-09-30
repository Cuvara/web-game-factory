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
        Read and check a GLB or .gltf without Blender: structure, references, transforms,
        triangles, textures, clips, LODs, collision proxy; and, with --spec, what it declares.
        Exit 0 clean, 1 an error-severity finding.

Standard library only (Blender itself for `build`); run from the repository root.
See docs/blender-pipeline.md.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wgf_assets import blender, gltf, modelspec  # noqa: E402
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
    stamp = blender.read_stamp(data)
    payload = {"file": args.file, "bytes": len(data), "summary": summary, "stamp": stamp,
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
    _print(payload, args.json, lines + ["findings"] + _findings_lines(findings))
    return 1 if any(f[1] == "error" for f in findings) else 0


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
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=inspect_command)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
