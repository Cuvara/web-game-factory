#!/usr/bin/env python3
"""The 2D asset pipeline from the command line: build, validate, pack, inspect.

    python3 scripts/wgf-assets.py build    --design DESIGN.json --root CHECKOUT [--json]
                                           [--library DIR]... [--author-svg-from file|stdout]
                                           [--author-command ARG...]
    python3 scripts/wgf-assets.py validate [CHECKOUT] [--json] [--strict]
    python3 scripts/wgf-assets.py pack     OUT INPUT... [--padding N] [--extrude N]
                                           [--max-size N] [--no-pot] [--trim] [--scale N]
                                           [--animation NAME=PREFIX]... [--json]
    python3 scripts/wgf-assets.py inspect  FILE... [--json]
    python3 scripts/wgf-assets.py fonts    list|check|build [--dir DIR] [--json]

build     Runs the same pipeline as the workflow's `assets` step on a game design (its
          build_spec.assets, or any JSON with an `asset_requirements` list) against a game
          repository checkout: libraries (index.json, library.json), the 2D command author
          when --author-command names one (its argv; {request}, {output}, {prompt}
          substituted; with --author-svg-from stdout it prints the SVG and the
          pipeline writes it), placeholders for the rest, every delivered file judged; files
          into public/assets/ (atlas sources into src/assets/), atlases packed, the runtime
          manifest public/assets/assets.json written, stale placeholders pruned. It prints
          what it did; the asset-manifest artifact itself is only produced inside a run.
validate  Checks a checkout against its public/assets/assets.json: schema, every
          referenced file present with its recorded hash and format, atlas frames and
          animations, tilesets, SVG safety, texture edges, and files shipped but unlisted.
pack      Packs PNG files (or every PNG under a directory, in sorted order) into OUT.png +
          OUT.json, a JSON Hash atlas PixiJS and Phaser load unchanged. Frame names are file
          stems. Same inputs, same bytes.
inspect   What a file really is: sniffed format, size, alpha, SVG hazards, sha256.

Exit status: 0 clean; 1 problems found (errors, or warnings too with --strict); 2 the command
could not run (bad arguments, unreadable input). Standard library only, no external tools.
"""

import argparse
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wgf_assets import atlas, formats, raster, runtime  # noqa: E402
from wgf_assets.author import AuthorError, build_author  # noqa: E402
from wgf_assets.library import open_libraries  # noqa: E402
from wgf_assets.pipeline import AssetPipeline, AssetStore  # noqa: E402
from wgf_assets.placeholders import build_backends  # noqa: E402
from wgf_assets.policy import PolicyError, load_policy  # noqa: E402
from wgf_assets.requirements import RequirementError, inspect as inspect_design  # noqa: E402
from wgf_assets.step import PRODUCERS, build_producers  # noqa: E402

OK, PROBLEMS, UNUSABLE = 0, 1, 2


class Usage(Exception):
    pass


def _emit(args, payload, lines):
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for line in lines:
            print(line)


def _issue_lines(issues):
    order = {"error": 0, "warning": 1, "info": 2}
    for issue in sorted(issues, key=lambda i: (order.get(i["severity"], 3),
                                               i.get("asset_id") or i.get("item_id") or "",
                                               i["code"])):
        yield f"  {issue['severity']:<7} {issue['code']:<22} {issue['message']}"


def _status(issues, strict):
    if any(i["severity"] == "error" for i in issues):
        return PROBLEMS
    if strict and any(i["severity"] == "warning" for i in issues):
        return PROBLEMS
    return OK


# -- build ---------------------------------------------------------------------------------

def cmd_build(args):
    try:
        with open(args.design, encoding="utf-8") as handle:
            design = json.load(handle)
    except (OSError, ValueError) as exc:
        raise Usage(f"cannot read the design {args.design}: {exc}")
    if not os.path.isdir(args.root):
        raise Usage(f"{args.root} is not a directory (the game repository checkout)")
    try:
        policy = load_policy(args.policy)
        requirements, dimension = inspect_design(design, policy, dimension=args.dimension)
    except (PolicyError, RequirementError) as exc:
        raise Usage(f"asset requirements: {exc}")
    libraries, problems = open_libraries(args.library or [])
    for problem in problems:
        print(f"warning: asset library unavailable: {problem}", file=sys.stderr)
    backends = build_backends(["procedural"], {})
    store = AssetStore(args.root)
    try:
        author = build_author({"kind": "command", "argv": args.author_command,
                               "repair_rounds": args.repair_rounds,
                               "svg_from": args.author_svg_from}
                              if args.author_command else None)
    except AuthorError as exc:
        raise Usage(f"author: {exc}")
    identity = (design.get("build_spec") or {}).get("visual_identity") \
        if isinstance(design.get("build_spec"), dict) else None
    work_dir = args.work_dir or (tempfile.mkdtemp(prefix="wgf-assets-author-") if author
                                 else None)
    pipeline = AssetPipeline(policy, store, backends, libraries,
                             placeholders=not args.no_placeholders,
                             optimize=not args.no_optimize, prune=not args.no_prune,
                             title_id=design.get("title_id"), author=author,
                             identity=identity, work_dir=work_dir,
                             locales=(design.get("scope") or {}).get("locales") or (),
                             producers=build_producers(
                                 [p for p in (args.producers or "").split(",") if p], design,
                                 args.title_id or design.get("title_id")))
    result = pipeline.run(requirements)
    payload = {
        "root": os.path.abspath(args.root),
        "dimension": dimension,
        "items": [{k: item.get(k) for k in ("id", "type", "role", "source", "status",
                                            "placeholder", "atlas", "production_ready",
                                            "quality") if k in item}
                  | {"files": [f["path"] for f in item.get("files") or []]}
                  for item in result.items],
        "atlases": result.atlases,
        "runtime_manifest": result.runtime_manifest,
        "writes": dict(store.writes, removed=len(store.removed)),
        "removed": result.removed,
        "issues": result.issues,
    }
    lines = [f"{len(result.items)} asset(s), {len(result.atlases)} atlas(es) -> "
             f"{os.path.abspath(args.root)}"]
    for item in payload["items"]:
        where = (f"atlas {item['atlas']['id']}" if item.get("atlas")
                 else ", ".join(item["files"]) or "-")
        verdict = (item.get("quality") or {}).get("verdict") or "-"
        lines.append(f"  {item['id']:<24} {item['status']:<12} {verdict:<8} {where}")
    if result.runtime_manifest:
        lines.append(f"runtime manifest: {result.runtime_manifest['path']} "
                     f"({result.runtime_manifest['content_hash'][:19]}...)")
    if result.issues:
        lines.append("issues:")
        lines.extend(_issue_lines(result.issues))
    _emit(args, payload, lines)
    return _status(result.issues, args.strict)


# -- fonts ---------------------------------------------------------------------------------

def cmd_fonts(args):
    from wgf_assets import fontlib
    if args.action == "build":
        try:
            index = fontlib.build(args.dir)
        except ImportError as exc:
            raise Usage(f"building the font library needs fontTools and Brotli: {exc}")
        _emit(args, index, [f"{len(index['families'])} families -> "
                            f"{args.dir or fontlib.LIBRARY_DIR}"])
        return OK
    if args.action == "check":
        problems = fontlib.check(args.dir)
        _emit(args, {"problems": problems}, problems or ["font library: ok"])
        return PROBLEMS if problems else OK
    library = fontlib.load(args.dir)
    if library is None:
        raise Usage("no font library index")
    lines = [f"{name:<20} {e['weights'][0]}-{e['weights'][1]}  {e['bytes']:>7} B  "
             f"{', '.join(e['subsets'])}" for name, e in sorted(library.families.items())]
    _emit(args, library.index, lines)
    return OK


# -- validate ------------------------------------------------------------------------------

def cmd_validate(args):
    root = args.root
    if not os.path.isdir(root):
        raise Usage(f"{root} is not a directory")
    try:
        policy = load_policy(args.policy)
        limits = {"max_edge": policy.max_texture_edge, "warn_edge": policy.warn_texture_edge}
    except PolicyError:
        limits = {}
    issues = runtime.validate(root, unused=not args.no_unused, **limits)
    status = _status(issues, args.strict)
    errors = sum(i["severity"] == "error" for i in issues)
    warnings = sum(i["severity"] == "warning" for i in issues)
    lines = [f"{runtime.RUNTIME_PATH} in {os.path.abspath(root)}: "
             f"{'OK' if status == OK else 'PROBLEMS'} ({errors} error(s), "
             f"{warnings} warning(s))"]
    lines.extend(_issue_lines(issues))
    _emit(args, {"root": os.path.abspath(root), "ok": status == OK, "errors": errors,
                 "warnings": warnings, "issues": issues}, lines)
    return status


# -- pack ----------------------------------------------------------------------------------

def _pngs(inputs):
    found = []
    for item in inputs:
        if os.path.isdir(item):
            for directory, dirs, names in os.walk(item):
                dirs.sort()
                found.extend(os.path.join(directory, n) for n in sorted(names)
                             if n.lower().endswith(".png"))
        elif os.path.isfile(item):
            found.append(item)
        else:
            raise Usage(f"{item} does not exist")
    if not found:
        raise Usage("no PNG files to pack")
    return found


def cmd_pack(args):
    sprites, sources = [], {}
    for path in _pngs(args.inputs):
        name = os.path.splitext(os.path.basename(path))[0]
        if name in sources:
            raise Usage(f"two inputs have the frame name {name!r}: {sources[name]} and {path}")
        sources[name] = path
        with open(path, "rb") as handle:
            data = handle.read()
        try:
            sprites.append((name, raster.decode_png(data)))
        except raster.RasterError as exc:
            raise Usage(f"{path}: {exc}")
    animations = {}
    for spec in args.animation or []:
        anim, _, prefix = spec.partition("=")
        if not anim or not prefix:
            raise Usage(f"--animation {spec!r}: expected NAME=PREFIX")
        frames = atlas.frame_order(n for n in sources if n.startswith(prefix))
        if not frames:
            raise Usage(f"--animation {spec!r}: no frame name starts with {prefix!r}")
        animations[anim] = frames
    options = {"padding": args.padding, "extrude": args.extrude, "max_size": args.max_size,
               "power_of_two": not args.no_pot, "trim": args.trim}
    try:
        image, frames = atlas.pack(sprites, options)
    except atlas.AtlasError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return PROBLEMS
    out_png, out_json = args.out + ".png", args.out + ".json"
    png = raster.encode_png(image)
    document = atlas.atlas_document(frames, os.path.basename(out_png),
                                    (image.width, image.height), animations=animations,
                                    scale=args.scale)
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    for path, data in ((out_png, png), (out_json, document)):
        with open(path, "wb") as handle:
            handle.write(data)
    payload = {"image": out_png, "data": out_json, "width": image.width,
               "height": image.height, "frames": sorted(frames),
               "animations": animations,
               "sha256": {"image": hashlib.sha256(png).hexdigest(),
                          "data": hashlib.sha256(document).hexdigest()}}
    _emit(args, payload, [f"{len(frames)} frame(s) -> {out_png} ({image.width}x"
                          f"{image.height}) + {out_json}"])
    return OK


# -- inspect -------------------------------------------------------------------------------

def cmd_inspect(args):
    reports, status = [], OK
    for path in args.files:
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError as exc:
            raise Usage(f"{path}: {exc}")
        found = formats.sniff(data)
        report = {"path": path, "bytes": len(data),
                  "sha256": hashlib.sha256(data).hexdigest(),
                  "format": found.format if found else None,
                  "width": found.width if found else None,
                  "height": found.height if found else None}
        declared = formats.format_for_extension(path)
        if found and declared and declared != found.format:
            report["problem"] = f"named .{declared} but is {found.format}"
            status = PROBLEMS
        if found is None:
            report["problem"] = "not a recognisable asset file"
            status = PROBLEMS
        elif found.format == "png":
            header = raster.png_header(data)
            report.update(alpha=header.has_alpha, interlaced=header.interlaced)
        elif found.format == "svg":
            report["svg_hazards"] = formats.svg_hazards(data)
            if report["svg_hazards"]:
                status = PROBLEMS
        elif found.format == "json":
            try:
                document = json.loads(data.decode("utf-8-sig"))
            except ValueError:
                document = None
            if isinstance(document, dict) and "frames" in document:
                report["atlas_problems"] = atlas.check_document(document)
                report["frames"] = len(atlas.frames_of(document))
                if report["atlas_problems"]:
                    status = PROBLEMS
        reports.append(report)
    lines = []
    for r in reports:
        size = f" {r['width']}x{r['height']}" if r.get("width") else ""
        extra = "".join(f" {k}={r[k]}" for k in ("alpha", "frames", "svg_hazards",
                                                   "atlas_problems", "problem") if r.get(k))
        lines.append(f"{r['path']}: {r['format'] or '?'}{size}, {r['bytes']} B{extra}")
    _emit(args, reports, lines)
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="wgf-assets.py", description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="run the asset pipeline on a design")
    build.add_argument("--design", required=True, help="game-design JSON")
    build.add_argument("--root", required=True, help="game repository checkout")
    build.add_argument("--library", action="append", help="asset library directory")
    build.add_argument("--dimension", choices=("2d", "3d"))
    build.add_argument("--no-placeholders", action="store_true")
    build.add_argument("--no-optimize", action="store_true")
    build.add_argument("--no-prune", action="store_true")
    build.add_argument("--author-command", nargs=argparse.REMAINDER,
                       help="the 2D author's argv (last option): {request} {output} {prompt}")
    build.add_argument("--author-svg-from", choices=("file", "stdout"), default="file",
                       help="file: the author writes {output}; stdout: it prints the SVG last")
    build.add_argument("--repair-rounds", type=int, default=2)
    build.add_argument("--work-dir", help="author requests, logs and rejected files "
                                          "(default: a fresh temporary directory)")
    build.add_argument("--producers", default="",
                       help=f"comma-separated producers of final assets: {', '.join(PRODUCERS)}"
                            " (the Factory font library; the composer)")
    build.add_argument("--title-id", help="the title id the composer seeds its key from")
    build.set_defaults(func=cmd_build)

    fonts = sub.add_parser("fonts", help="the Factory font library: list, check, build")
    fonts.add_argument("action", choices=("list", "check", "build"))
    fonts.add_argument("--dir", help="library directory (default: the Factory's)")
    fonts.set_defaults(func=cmd_fonts)

    validate = sub.add_parser("validate", help="validate a checkout's runtime manifest")
    validate.add_argument("root", nargs="?", default=".", help="game repository checkout")
    validate.add_argument("--no-unused", action="store_true",
                          help="do not report files shipped but unlisted")
    validate.set_defaults(func=cmd_validate)

    pack = sub.add_parser("pack", help="pack PNGs into a texture atlas")
    pack.add_argument("out", help="output path without extension")
    pack.add_argument("inputs", nargs="+", help="PNG files or directories")
    pack.add_argument("--padding", type=int, default=atlas.DEFAULT_OPTIONS["padding"])
    pack.add_argument("--extrude", type=int, default=atlas.DEFAULT_OPTIONS["extrude"])
    pack.add_argument("--max-size", type=int, default=atlas.DEFAULT_OPTIONS["max_size"])
    pack.add_argument("--no-pot", action="store_true", help="allow non-power-of-two edges")
    pack.add_argument("--trim", action="store_true", help="crop transparent borders")
    pack.add_argument("--scale", type=int, default=1, choices=(1, 2, 3, 4))
    pack.add_argument("--animation", action="append", metavar="NAME=PREFIX",
                      help="an animation over the frames whose names start with PREFIX")
    pack.set_defaults(func=cmd_pack)

    inspect = sub.add_parser("inspect", help="what files really are")
    inspect.add_argument("files", nargs="+")
    inspect.set_defaults(func=cmd_inspect)

    for command in (build, validate, pack, inspect, fonts):
        command.add_argument("--json", action="store_true", help="machine-readable output")
        if command in (build, validate):
            command.add_argument("--strict", action="store_true",
                                 help="warnings fail too")
            command.add_argument("--policy", help="asset policy file (default: core's)")

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Usage as exc:
        print(f"error: {exc}", file=sys.stderr)
        return UNUSABLE


if __name__ == "__main__":
    sys.exit(main())
