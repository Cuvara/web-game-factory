#!/usr/bin/env python3
"""Visual QA outside a workflow run: run the judge over a frames directory, so a person can
look at the brief, the frames and the verdict the step would have acted on.

    python3 scripts/wgf-visualqa.py --frames out/desktop/frames --frames out/mobile/frames
                                    [--design game-design.json] [--manifest asset-manifest.json]
                                    [--quality production-quality-report.json]
                                    [--title ID] [--commit SHA] [--out DIR]
                                    [--judge-argv JSON] [--verdict-from file|stdout]
                                    [--timeout S] [--config factory.yaml] [--brief-only] [--json]

    --frames      a directory of PNG frames; repeat it per viewport. Its viewport is
                  VIEWPORT=DIR when given so, else the parent directory's name when the
                  directory is called `frames` (the playability step's out/<viewport>/frames),
                  else its own name.
    --judge-argv  the judge's argv as a JSON list, placeholders {frames_dir} {brief}
                  {verdict} {prompt}. Default: factory.visualqa.judge from the configuration
                  (--config, else the Factory's layered workspace/config/factory.yaml).
    --brief-only  stage the frames and write the brief; run no judge.

Exactly what the step does - the same staging, brief, judge process, isolation check,
verdict parse (one retry of a malformed verdict) and rubric decision - with nothing pinned
to a run. Writes everything under --out (default a new directory under the system temp
directory) and prints where. Exit 0 PASS, 1 FAIL, 2 the judge or the input was unusable.

Standard library only; run from the repository root. See docs/visual-qa-module.md.
"""

import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wgflib import isolation  # noqa: E402
from wgflib.workflow.config import load_config  # noqa: E402

from wgf_visualqa.brief import render_brief  # noqa: E402
from wgf_visualqa.judge import FrameError, run_judge, stage_frames  # noqa: E402
from wgf_visualqa.rubric import RubricError, decide, load_rubric  # noqa: E402
from wgf_visualqa.settings import Settings, SettingsError  # noqa: E402


class _Log:
    def __init__(self, quiet):
        self.quiet = quiet

    def __getattr__(self, level):
        def log(message, **fields):
            if not self.quiet:
                extra = " ".join(f"{k}={v}" for k, v in fields.items())
                print(f"[{level}] {message} {extra}".rstrip(), file=sys.stderr)
        return log


def _load(path):
    if not path:
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _frame_entries(specs):
    entries = []
    for spec in specs:
        viewport, _, directory = spec.rpartition("=") if "=" in spec else ("", "", spec)
        directory = os.path.abspath(directory)
        if not viewport:
            name = os.path.basename(directory.rstrip(os.sep))
            viewport = (os.path.basename(os.path.dirname(directory.rstrip(os.sep)))
                        if name == "frames" else name)
        if not os.path.isdir(directory):
            raise FrameError("missing", f"no frames directory at {directory}")
        for name in sorted(os.listdir(directory)):
            if name.lower().endswith(".png"):
                entries.append({"project": viewport, "id": name[:-4],
                                "source": os.path.join(directory, name),
                                "path": os.path.join(directory, name)})
    return entries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--frames", action="append", required=True)
    parser.add_argument("--design")
    parser.add_argument("--manifest")
    parser.add_argument("--quality")
    parser.add_argument("--title")
    parser.add_argument("--commit")
    parser.add_argument("--out")
    parser.add_argument("--judge-argv")
    parser.add_argument("--verdict-from", choices=("file", "stdout"))
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--rubric")
    parser.add_argument("--config")
    parser.add_argument("--brief-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    config = load_config(args.config).data
    override = {}
    if args.judge_argv:
        override["argv"] = json.loads(args.judge_argv)
        override["kind"] = "command"
    if args.verdict_from:
        override["verdict_from"] = args.verdict_from
    if args.timeout:
        override["timeout_seconds"] = args.timeout
    params = {"judge": override} if override else {}
    if args.rubric:
        params["rubric"] = args.rubric
    try:
        settings = Settings.resolve(config, params)
        rubric = load_rubric(settings.rubric_path)
        design, manifest, quality = _load(args.design), _load(args.manifest), _load(args.quality)
        out = os.path.abspath(args.out or tempfile.mkdtemp(prefix="wgf-visualqa-"))
        os.makedirs(out, exist_ok=True)
        frames_dir, frames = stage_frames(_frame_entries(args.frames), out)
    except (SettingsError, RubricError, FrameError, OSError, ValueError) as exc:
        print(f"wgf-visualqa: {exc}", file=sys.stderr)
        return 2
    if not frames:
        print("wgf-visualqa: no PNG frames found", file=sys.stderr)
        return 2
    title = args.title or (design or {}).get("title_id")
    if args.brief_only:
        brief_path = os.path.join(out, "brief.md")
        with open(brief_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(render_brief(
                title_id=title, commit=args.commit, frames=frames, rubric=rubric,
                design=design, manifest=manifest, quality=quality,
                verdict_path=os.path.join(out, "verdict.json"),
                to_stdout=settings.verdict_from == "stdout"))
        print(brief_path)
        return 0
    if settings.kind == "none":
        print("wgf-visualqa: no judge: factory.visualqa.judge.kind is none; pass --judge-argv "
              "or configure one", file=sys.stderr)
        return 2

    outcome = run_judge(settings, rubric, out, frames, frames_dir, title_id=title,
                        commit=args.commit, design=design, manifest=manifest, quality=quality,
                        guarded=isolation.guarded_paths(config), logger=_Log(args.json))
    result = {"out": out, "frames": len(frames), "brief": outcome.brief_path,
              "verdict_path": outcome.verdict_path, "runs": outcome.runs,
              "duration_s": round(outcome.duration_s, 1)}
    if outcome.failure is not None:
        result["failure"] = outcome.failure
        code = 2
    else:
        identity = ((design or {}).get("build_spec") or {}).get("visual_identity") or {}
        status, failed, routes = decide(outcome.verdict, rubric,
                                        primitive_style=bool(identity.get("primitive_style")))
        result.update(verdict=status, failed=failed, routes=routes,
                      route=routes[0] if routes else None, judge_verdict=outcome.verdict)
        code = 0 if status == "PASS" else 1
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"frames   {len(frames)} staged under {frames_dir}")
        print(f"brief    {outcome.brief_path}")
        print(f"verdict  {outcome.verdict_path}")
        if outcome.failure is not None:
            print(f"FAILED   {outcome.failure['code']}: {outcome.failure['message']}")
        else:
            print(json.dumps(outcome.verdict, indent=2))
            print(f"{result['verdict']}  failed={result['failed']} route={result['route']}")
    return code


if __name__ == "__main__":
    sys.exit(main())
