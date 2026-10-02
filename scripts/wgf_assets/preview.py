"""Look at a 2D set: judge every drawing, render it, and compose a contact sheet.

The 2D author's `set` mode (set_author.py) authors every drawing a design needs in one
session; this is what it - and the Factory after it - looks at. One job file describes the
set (written by the Factory, outside what the author may write):

    {format: "wgf-set-preview", version: 1,
     out_dir      where the drawings are (<out_dir>/<variant id>.svg)
     preview_dir  where the renders, the contact sheet and report.json go
     checkout     the game repository whose Playwright renders (None: no render)
     background, surface    the design's ground and panel colours (hex)
     palette, primitive_style, typography, avoid   the design's visual identity
     files: [{id, requirement, role, width, height, count}]}

`review(job)` judges each file exactly as the assets step does (wgf_assets.quality:
svg_quality with the typography and avoid checks, variants.distinct within a requirement,
set.consistent across the set) and renders through tools/render-svgs.mjs - Chromium from
the checkout's own Playwright, run through wgflib.procs - into <preview_dir>/sheet.png
(every drawing at its in-game size on the background, small on the background and on the
panel surface, and each counted requirement's silhouettes) and one PNG per drawing. No
checkout, no node or no Playwright: the review is returned without a render, with a warning.

As a command, for the author to run inside its session (the one command its host allows):

    python3 preview.py <job.json>

prints every file's problems and the contact sheet's path, writes <preview_dir>/report.json,
and exits 0 when every drawing passes, 1 when one does not, 2 when the job is unusable.
"""

import json
import os
import sys

try:
    from . import quality as quality_mod
except ImportError:  # run as a script: import the package beside this file
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from wgf_assets import quality as quality_mod

from wgflib import procs  # noqa: E402

__all__ = ["review", "render", "RENDERER", "JOB_FORMAT", "write_job"]

HERE = os.path.dirname(os.path.abspath(__file__))
RENDERER = os.path.join(HERE, "tools", "render-svgs.mjs")
JOB_FORMAT = "wgf-set-preview"
RENDER_TIMEOUT = 240
MAX_PROBLEMS = 12


def write_job(path, job):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(dict(job, format=JOB_FORMAT, version=1), handle, indent=2, sort_keys=True)


def _read(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def render(job, items, *, env=None, timeout=RENDER_TIMEOUT):
    """(render result or None, warning or None). `items` [{id, requirement, path, width,
    height, role, count, problems}]."""
    checkout = job.get("checkout")
    if not checkout or not os.path.isfile(os.path.join(checkout, "package.json")):
        return None, ("no game checkout with a package.json to render with: the drawings "
                      "were judged, not looked at")
    out = job["preview_dir"]
    os.makedirs(out, exist_ok=True)
    render_job = {"checkout": checkout, "out": out, "title": job.get("title"),
                  "background": job.get("background"), "surface": job.get("surface"),
                  "small": job.get("small") or 40, "max_cell": job.get("max_cell") or 320,
                  "items": items}
    path = os.path.join(out, "render-job.json")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(render_job, handle, indent=2)
    result = procs.run(["node", RENDERER, path], cwd=checkout, env=env, timeout=timeout,
                       idle_timeout=None, log_path=os.path.join(out, "render.log"),
                       heartbeat_seconds=0)
    if result.error:
        return None, f"cannot render: node is not available ({result.error})"
    if result.returncode == 2:
        return None, ("cannot render: the game checkout installs no Playwright "
                      f"({result.tail(2)})")
    try:
        with open(os.path.join(out, "render.json"), encoding="utf-8") as handle:
            done = json.load(handle)
    except (OSError, ValueError):
        return None, f"the render failed ({result.status}): {result.tail(4)}"
    if not done.get("sheet"):
        return done, "the render failed: " + "; ".join(done.get("errors") or ["no sheet"])
    return done, None


def review(job, *, extra=None, render_env=None, do_render=True):
    """{files: {id: {problems, quality, path, exists}}, sheet, renders, warnings, passed,
    set: {measured}}. `extra(file entry, bytes)` -> [problem] adds the caller's own checks (the
    assets step's format and policy validation)."""
    bars = quality_mod.load_bars()
    palette = quality_mod.parse_palette(job.get("palette"))
    files, drawings, by_req = {}, [], {}
    for entry in job.get("files") or []:
        vid = entry["id"]
        path = os.path.join(job["out_dir"], f"{vid}.svg")
        data = _read(path)
        record = {"path": path, "exists": data is not None, "problems": [], "quality": None,
                  "requirement": entry.get("requirement"), "role": entry.get("role")}
        files[vid] = record
        if data is None:
            record["problems"].append(f"{vid}.svg was not written")
            continue
        size = (entry.get("width"), entry.get("height"))
        judged = quality_mod.svg_quality(
            data, role=entry.get("role"), palette=palette, bars=bars,
            spec_size=size if all(size) else None,
            primitive_style=bool(job.get("primitive_style")), author=job.get("author"),
            typography=job.get("typography"), avoid=job.get("avoid"))
        record["quality"] = judged
        record["problems"].extend(quality_mod.problems(judged))
        if extra is not None:
            record["problems"].extend(extra(entry, data))
        drawings.append((vid, data, entry.get("role"), size if all(size) else None))
        by_req.setdefault(entry.get("requirement"), []).append((vid, data))
    for req_id, members in by_req.items():
        if len(members) < 2:
            continue
        found = quality_mod.variants_distinct([(v, d, "svg") for v, d in members], bars)
        if found and found[0]["status"] == "fail":
            for vid, _data in members:
                named = [k for k, dist in found[1]["pairs"].items()
                         if vid in k.split("~") and dist < found[1]["bar"]]
                if named:
                    files[vid]["problems"].append(
                        f"variants.distinct: {vid} shares a silhouette with "
                        + ", ".join(k.replace(vid, "").strip("~") for k in named[:4])
                        + f" (bar {found[1]['bar']:.2f}) - give each {req_id} variant its "
                          f"own outline and size, not a recolour or another numeral")
    consistency, measured = quality_mod.set_consistency(drawings, bars)
    for vid, check in consistency.items():
        record = files[vid]
        if record["quality"] is not None:
            checks = list(record["quality"]["checks"]) + [check]
            verdict = "fail" if any(c["status"] == "fail" for c in checks) else "pass"
            record["quality"] = dict(record["quality"], checks=checks, verdict=verdict)
        if check["status"] == "fail":
            record["problems"].append(f"set.consistent: {check['summary']}")
    warnings, renders, sheet = [], {}, None
    if do_render:
        items = [{"id": vid, "requirement": e.get("requirement"), "role": e.get("role"),
                  "path": files[vid]["path"], "width": e.get("width"),
                  "height": e.get("height"), "count": e.get("count") or 1,
                  "problems": len(files[vid]["problems"])}
                 for e in job.get("files") or [] for vid in [e["id"]]]
        done, warning = render(job, items, env=render_env)
        if warning:
            warnings.append(warning)
        if done:
            sheet = done.get("sheet")
            renders = done.get("files") or {}
            for error in done.get("errors") or []:
                vid = error.split(":", 1)[0]
                if vid in files and "could not draw" in error:
                    files[vid]["problems"].append("render: the browser could not draw it")
    passed = all(not r["problems"] for r in files.values())
    return {"files": files, "sheet": sheet, "renders": renders, "warnings": warnings,
            "passed": passed, "set": {"measured": measured}}


def summary(result):
    """The text the author reads after running the preview."""
    lines = []
    bad = {vid: r for vid, r in result["files"].items() if r["problems"]}
    lines.append(f"{len(result['files']) - len(bad)} of {len(result['files'])} drawings pass "
                 f"the quality bars.")
    for vid, record in bad.items():
        lines.append(f"- {vid}:")
        lines.extend(f"    {p}" for p in record["problems"][:MAX_PROBLEMS])
    if result.get("sheet"):
        lines.append(f"Contact sheet: {result['sheet']} - open it and look: does every "
                     f"drawing read at its size, do the variants differ in silhouette, does "
                     f"the set look like one game in the visual identity?")
    for warning in result.get("warnings") or []:
        lines.append(f"warning: {warning}")
    return "\n".join(lines)


def _jsonable(result):
    out = dict(result)
    out["files"] = {vid: {k: v for k, v in r.items()} for vid, r in result["files"].items()}
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("usage: preview.py <job.json>", file=sys.stderr)
        return 2
    try:
        with open(argv[0], encoding="utf-8") as handle:
            job = json.load(handle)
    except (OSError, ValueError) as exc:
        print(f"preview.py: cannot read the job: {exc}", file=sys.stderr)
        return 2
    if job.get("format") != JOB_FORMAT or not job.get("out_dir") or not job.get("preview_dir"):
        print("preview.py: not a set preview job", file=sys.stderr)
        return 2
    result = review(job)
    os.makedirs(job["preview_dir"], exist_ok=True)
    with open(os.path.join(job["preview_dir"], "report.json"), "w", encoding="utf-8") as handle:
        json.dump(_jsonable(result), handle, indent=2, sort_keys=True, default=str)
    print(summary(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
