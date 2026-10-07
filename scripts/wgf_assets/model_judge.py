"""The model judge: an independent reader of a 3D model's renders, never its author.

The model author writes specs and the Factory measures what they build (model_quality,
model_lint). What measurement cannot see - does the marble read as a marble at 64 px from the
chase camera, does the bumper vanish on the track, does the gate's glow belong to a cut-paper
world - a judge sees, from the pictures (core/reference/model-review-rubric.yaml). It is
configured like visual QA's judge (wgf_visualqa), as `factory.assets.model_author.judge`:

    judge:
      kind: none | command | baseline
      argv: []                   # command: the judge's command; placeholders below
      verdict_from: file         # file: it writes {verdict}; stdout: it prints the JSON last
      timeout_seconds: 600       # per invocation; idle_timeout_seconds: null
      repair_rounds: 1           # a malformed verdict goes back with its errors this often
      rounds: 2                  # craft rounds: a failing verdict goes back to the AUTHOR
                                 # with the judge's notes, this many times, then BLOCKED
      references: null           # a directory of reference images: <role>/*.png, or *.png
                                 # for every role - what the judge compares the craft with
      baseline_dir: null         # baseline: approved renders, <id>.<view>.png
      min_similarity: null       # baseline: default wgf_visualqa.baseline.MIN_SIMILARITY

    command   an agent able to read images, run through wgflib.procs with the allowlisted
              environment (wgflib.agentenv), its working directory a directory holding only
              its brief and COPIES of the images. argv placeholders, per element: {images}
              (that directory), {brief} (the brief, markdown), {verdict} (where to write the
              verdict JSON), {prompt} (a one-paragraph instruction naming all three). Images
              it changes, or a guarded Factory path it touches, refuse its verdict.
    baseline  no agent: each model's renders against approved renders of the same model and
              view (wgf_visualqa.baseline's measure: palette, detail, layout). A golden run's
              or a test's judge: deterministic, and blind to anything but regression. A model
              with no approved render cannot be judged: an `error`, never a pass.
    none      no judge: the craft check is `skipped` and says so - nothing is judged that was
              not looked at.

The verdict, per model (the brief states it):

    {"models": {"<id>": {"scores": {"<dimension>": 0-5, ...}, "reads_as": true | false,
                         "findings": [{"severity": "blocker|major|minor",
                                       "dimension": "<dimension>", "note": "..."}],
                         "summary": "one line"}}}

The judge scores; `decide` decides: a model fails on a dimension below `pass_bar`, a mean
below `mean_pass_bar`, `reads_as: false`, or a blocker finding.

    outcome = judge(settings, rubric, entries, workdir, identity=..., design=...)
    outcome = {"verdicts": {id: {status, scores, reads_as, findings, summary, failures,
               notes}}, "runs": [...], "error": None | {code, message, retryable}}
"""

import hashlib
import json
import math
import os
import shutil
import time

from wgflib import agentenv, isolation, paths, procs

__all__ = ["JudgeError", "KINDS", "DEFAULTS", "configure", "judge", "decide", "parse",
           "load_rubric", "brief", "PROMPT", "PROMPT_STDOUT", "MAX_JUDGE_RUNS"]

KINDS = ("none", "command", "baseline")
DEFAULTS = {"kind": "none", "argv": [], "verdict_from": "file", "timeout_seconds": 600,
            "idle_timeout_seconds": None, "repair_rounds": 1, "rounds": 2,
            "references": None, "baseline_dir": None, "min_similarity": None,
            "env_passthrough": []}
MAX_JUDGE_RUNS = 2
SEVERITIES = ("blocker", "major", "minor")
_REPLY_CHARS = 100_000

PROMPT = ("You are an independent judge of 3D model craft for a game; you did not make these "
          "models. Read the brief at {brief}: it names, per model, the images in {images} to "
          "open (a contact sheet, an in-context sheet on the play surface beside the player, "
          "references), the rubric and the verdict's shape. Open every image. Write the verdict "
          "JSON, and nothing else, to {verdict}. Change no image.")
PROMPT_STDOUT = ("You are an independent judge of 3D model craft for a game; you did not make "
                 "these models. Read the brief at {brief}: it names, per model, the images in "
                 "{images} to open, the rubric and the verdict's shape. Open every image. End "
                 "your answer with the verdict as one JSON object. Change no image.")


class JudgeError(ValueError):
    """The judge's configuration or rubric is unusable. Not retryable."""


def load_rubric(path=None):
    """The rubric with its judge part checked: version, pass bars, dimensions, blockers."""
    from . import model_lint
    data = model_lint.load_rubric(path)
    dims = data.get("dimensions")
    if not isinstance(dims, dict) or not dims:
        raise JudgeError("model-review-rubric: no dimensions")
    for key in ("pass_bar", "mean_pass_bar"):
        value = data.get(key)
        if not isinstance(value, (int, float)) or not 0 <= value <= 5:
            raise JudgeError(f"model-review-rubric: {key} must be a number 0..5")
    return data


def configure(raw, *, config=None):
    """The judge settings over DEFAULTS. Raises JudgeError."""
    settings = dict(DEFAULTS)
    settings.update(raw or {})
    if settings["kind"] not in KINDS:
        raise JudgeError(f"model judge kind {settings['kind']!r}: one of {', '.join(KINDS)}")
    if settings["kind"] == "command":
        argv = settings.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise JudgeError("the model judge's argv is not configured (a non-empty list of "
                             "strings)")
        if settings.get("verdict_from") not in ("file", "stdout"):
            raise JudgeError("the model judge's verdict_from must be file or stdout")
    for key in ("references", "baseline_dir"):
        # Relative to the project directory, as every configured path is.
        if isinstance(settings.get(key), str) and not os.path.isabs(settings[key]):
            settings[key] = os.path.join(paths.PROJECT, settings[key])
    if settings["kind"] == "baseline":
        if not settings.get("baseline_dir") or not os.path.isdir(settings["baseline_dir"]):
            raise JudgeError(f"the model judge's baseline_dir is not a directory: "
                             f"{settings.get('baseline_dir')!r}")
    rounds = settings.get("rounds")
    if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < 0:
        raise JudgeError("the model judge's rounds must be a whole number")
    try:
        settings["env"] = agentenv.passthrough(config) if config else []
    except ValueError as exc:
        raise JudgeError(str(exc)) from exc
    return settings


# -- the verdict ---------------------------------------------------------------------------------

def parse(data, rubric, ids):
    """(verdicts {id: entry}, errors). Strict: every model, every dimension an integer 0..5,
    reads_as a boolean, findings well formed. Nothing missing is invented."""
    errors = []
    if not isinstance(data, dict) or not isinstance(data.get("models"), dict):
        return None, ['the verdict must be {"models": {"<id>": {...}}}']
    models = data["models"]
    dims = list(rubric["dimensions"])
    out = {}
    for model_id in ids:
        entry = models.get(model_id)
        where = f"models.{model_id}"
        if not isinstance(entry, dict):
            errors.append(f"{where}: missing")
            continue
        scores = entry.get("scores")
        if not isinstance(scores, dict):
            errors.append(f"{where}.scores: an object of the rubric's dimensions")
            scores = {}
        for dim in dims:
            value = scores.get(dim)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 5:
                errors.append(f"{where}.scores.{dim}: an integer 0..5")
        unknown = sorted(set(scores) - set(dims))
        if unknown:
            errors.append(f"{where}.scores: no dimension {', '.join(unknown)}")
        if not isinstance(entry.get("reads_as"), bool):
            errors.append(f"{where}.reads_as: true or false")
        findings = entry.get("findings", [])
        if not isinstance(findings, list):
            errors.append(f"{where}.findings: a list")
            findings = []
        for index, finding in enumerate(findings):
            if not isinstance(finding, dict) or finding.get("severity") not in SEVERITIES \
                    or not isinstance(finding.get("note"), str) or not finding["note"].strip():
                errors.append(f"{where}.findings[{index}]: {{severity: "
                              f"{'|'.join(SEVERITIES)}, dimension, note}}")
        out[model_id] = {"scores": {d: scores.get(d) for d in dims}, "reads_as":
                         entry.get("reads_as"), "findings": findings,
                         "summary": str(entry.get("summary") or "")[:400]}
    return (None, errors) if errors else (out, [])


def decide(entry, rubric):
    """The step's decision on one model's verdict: the entry with `status` pass | fail,
    `failures` (why, one line each) and `notes` (what the author is handed)."""
    bar = rubric["pass_bar"]
    failures = []
    for dim, score in entry["scores"].items():
        if score < bar:
            failures.append(f"{dim} scored {score} (pass bar {bar})")
    scores = list(entry["scores"].values())
    mean = sum(scores) / float(len(scores)) if scores else 0.0
    if mean < rubric["mean_pass_bar"]:
        failures.append(f"mean score {mean:.2f} (pass bar {rubric['mean_pass_bar']})")
    if entry["reads_as"] is False:
        failures.append("it does not read as its readability line")
    blockers = [f for f in entry["findings"] if f.get("severity") == "blocker"]
    failures += [f"blocker: {f['note']}" for f in blockers]
    notes = [f"{f.get('severity')}{' ' + f['dimension'] if f.get('dimension') else ''}: "
             f"{f['note']}" for f in entry["findings"]]
    if entry.get("summary"):
        notes.insert(0, entry["summary"])
    return dict(entry, status="fail" if failures else "pass", mean=round(mean, 2),
                failures=failures, notes=notes)


# -- the brief -----------------------------------------------------------------------------------

def brief(rubric, entries, *, identity=None, design=None, to_stdout=False, verdict_path=None,
          repair=None):
    """The command judge's brief, markdown."""
    lines = ["# 3D model craft review", "",
             "You judge models you did not make. The Factory has measured them already "
             "(validity, parts, palette, silhouette, contrast, the craft lint); you judge what "
             "a measure cannot: whether each model is well made and reads as what it is, at "
             "the size and from the camera a player sees it.", ""]
    look = identity if isinstance(identity, dict) else {}
    if look:
        lines += ["## Visual identity", ""]
        for key in ("concept", "shape_language", "texture", "avoid"):
            if look.get(key):
                lines.append(f"- {key}: {look[key]}")
        palette = [f"{e.get('token')} {e.get('hex')} ({e.get('role')})"
                   for e in look.get("palette") or [] if isinstance(e, dict)]
        if palette:
            lines.append("- palette: " + "; ".join(palette))
        lines.append("")
    for key in ("art_direction", "camera"):
        if (design or {}).get(key):
            lines += [f"## {key.replace('_', ' ').title()}", "", str(design[key]), ""]
    lines += ["## Rubric", "", f"Score every dimension 0-5 for every model (pass bar "
              f"{rubric['pass_bar']}, mean pass bar {rubric['mean_pass_bar']}). The anchors "
              f"describe 0, 3 and 5.", ""]
    for name, dim in rubric["dimensions"].items():
        lines.append(f"- **{name}**: {dim.get('question')}")
        for anchor, text in sorted((dim.get("anchors") or {}).items()):
            lines.append(f"  - {anchor}: {text}")
    lines += ["", "Raise a finding of severity `blocker` whatever the scores for:", ""]
    lines += [f"- {b['id']}: {b['rule']}" for b in rubric.get("blockers") or []]
    lines += ["", "## Models", ""]
    for entry in entries:
        lines += [f"### {entry['id']} ({entry.get('role') or 'no role'})", "",
                  f"- what it is: {entry.get('description') or '-'}",
                  f"- what a player must recognise (`readability`): "
                  f"{entry.get('readability') or '-'}"]
        images = entry.get("images") or {}
        for label, rel in images.items():
            lines.append(f"- image `{label}`: {rel}")
        for warning in entry.get("lint") or []:
            lines.append(f"- measured ({warning['severity']}): {warning['message']}")
        lines.append("")
    lines += ["## Images", "",
              "`sheet`: left to right - three-quarter, side, top, the game's camera (when the "
              "design states one), and that view at the size a player sees it, enlarged with "
              "no smoothing. `context`: the model standing on the play surface beside the "
              "player, under the game's light, from the game's camera - what a player sees. "
              "`reference-*`: the craft bar for the role.", "",
              "## Verdict", "",
              'One JSON object: {"models": {"<id>": {"scores": {"<dimension>": 0-5, ...}, '
              '"reads_as": true|false, "findings": [{"severity": "blocker|major|minor", '
              '"dimension": "<dimension>", "note": "what is wrong and what to change"}], '
              '"summary": "one line"}}} - every model above, every dimension. Notes go back to '
              "the modeller: say what to change.", ""]
    if to_stdout:
        lines.append("End your answer with that JSON object.")
    else:
        lines.append(f"Write it to {verdict_path} and nothing else.")
    if repair:
        lines += ["", "## Your previous verdict was malformed", "",
                  "Return the complete, corrected verdict. Errors:", ""]
        lines += [f"- {e}" for e in repair["errors"]]
        lines += ["", "Your previous reply:", "", "```", repair["reply"], "```"]
    return "\n".join(lines) + "\n"


# -- running it ----------------------------------------------------------------------------------

def _sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _references(settings, role):
    root = settings.get("references")
    if not root or not os.path.isdir(root):
        return []
    found = []
    for directory in ([os.path.join(root, role)] if role else []) + [root]:
        if os.path.isdir(directory):
            found += [os.path.join(directory, n) for n in sorted(os.listdir(directory))
                      if n.lower().endswith(".png")]
    return found[:6]


def _stage(entries, settings, images_dir):
    """Copy every image into images_dir/<id>/; each entry gains `images` {label: relative}
    and `staged` {label: absolute}."""
    shutil.rmtree(images_dir, ignore_errors=True)
    staged = []
    for entry in entries:
        sources = {}
        if entry.get("sheet"):
            sources["sheet"] = entry["sheet"]
        if entry.get("context"):
            sources["context"] = entry["context"]
        for name, path in sorted((entry.get("views") or {}).items()):
            sources[f"view-{name}"] = path
        for index, path in enumerate(_references(settings, entry.get("role"))):
            sources[f"reference-{index + 1}"] = path
        images, absolute = {}, {}
        for label, source in sources.items():
            if not source or not os.path.isfile(source):
                continue
            target = os.path.join(images_dir, entry["id"], f"{label}.png")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(source, target)
            images[label] = os.path.relpath(target, os.path.dirname(images_dir))
            absolute[label] = target
        staged.append(dict(entry, images=images, staged=absolute))
    return staged


def _fingerprint(images_dir):
    out = {}
    for root, _dirs, files in os.walk(images_dir):
        for name in files:
            path = os.path.join(root, name)
            out[path] = _sha(path)
    return out


def _failure(result, settings):
    if result.error is not None:
        return {"code": "judge-not-started", "retryable": False,
                "message": f"the model judge could not start: {result.error}"}
    if result.timed_out or result.idle_timed_out:
        return {"code": "judge-timeout", "retryable": True,
                "message": f"the model judge ended {result.status}"}
    if result.cancelled:
        return {"code": "cancelled", "retryable": False, "message": "cancelled"}
    if result.returncode != 0:
        return {"code": "judge-crashed", "retryable": True,
                "message": f"the model judge exited {result.returncode}"}
    return None


def _command(settings, rubric, entries, workdir, identity, design, guarded, on_event, stem):
    from wgf_review.verdict import from_output
    images_dir = os.path.join(workdir, "images")
    staged = _stage(entries, settings, images_dir)
    ids = [e["id"] for e in entries]
    to_stdout = settings["verdict_from"] == "stdout"
    outcome = {"verdicts": None, "runs": [], "error": None, "brief": None}
    repair, fresh, run = None, 0, 0
    while True:
        run += 1
        kind = "repair" if repair else "fresh"
        fresh += kind == "fresh"
        verdict_path = os.path.join(workdir, f"{stem}-{run}.verdict.json")
        brief_path = os.path.join(workdir, f"{stem}-{run}.brief.md")
        log_path = os.path.join(workdir, f"{stem}-{run}.log")
        for stale in (verdict_path, log_path):
            if os.path.exists(stale):
                os.remove(stale)
        with open(brief_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(brief(rubric, staged, identity=identity, design=design,
                               to_stdout=to_stdout, verdict_path=verdict_path, repair=repair))
        outcome["brief"] = brief_path
        values = {"images": images_dir, "brief": brief_path, "verdict": verdict_path}
        values["prompt"] = (PROMPT_STDOUT if to_stdout else PROMPT).format(**values)
        argv = [part.format(**values) for part in settings["argv"]]
        env = agentenv.scrubbed(settings.get("env") or [])
        before = (_fingerprint(images_dir), isolation.take_guarded(guarded) if guarded else None)
        result = procs.run(argv, cwd=workdir, env=env,
                           timeout=settings.get("timeout_seconds"),
                           idle_timeout=settings.get("idle_timeout_seconds"),
                           log_path=log_path, heartbeat_seconds=15.0, on_event=on_event)
        after = (_fingerprint(images_dir), isolation.take_guarded(guarded) if guarded else None)
        record = {"run": run, "kind": kind, "argv0": os.path.basename(argv[0]),
                  "exit_code": result.returncode, "status": result.status, "log": log_path}
        outcome["runs"].append(record)
        violations = isolation.diff(before[1], after[1]) if guarded else []
        if before[0] != after[0] or violations:
            if violations:
                isolation.restore_guarded(before[1], guarded)
            outcome["error"] = {"code": "judge-isolation-violation", "retryable": False,
                                "message": "the model judge changed what it may only read"}
            return outcome
        failure = _failure(result, settings)
        if failure is not None:
            outcome["error"] = failure
            return outcome
        text = None
        if to_stdout:
            text = from_output(result.stdout)
        elif os.path.isfile(verdict_path):
            with open(verdict_path, encoding="utf-8", errors="replace") as handle:
                text = handle.read(_REPLY_CHARS + 1)
        try:
            data = json.loads(text) if text else None
        except ValueError as exc:
            data, errors = None, [f"not JSON: {exc}"]
        else:
            errors = [] if data is not None else ["no verdict was written"]
        verdicts = None
        if data is not None:
            verdicts, errors = parse(data, rubric, ids)
        if verdicts is not None:
            outcome["verdicts"] = {k: decide(v, rubric) for k, v in verdicts.items()}
            return outcome
        record["problem"] = "; ".join(errors)[:600]
        reply = (text or result.stdout or "")[-_REPLY_CHARS:]
        repairs = sum(1 for r in outcome["runs"] if r["kind"] == "repair")
        if reply.strip() and repairs < int(settings.get("repair_rounds") or 0):
            repair = {"reply": reply, "errors": errors}
        elif fresh < MAX_JUDGE_RUNS:
            repair = None
        else:
            outcome["error"] = {"code": "malformed-verdict", "retryable": False,
                                "message": "the model judge's verdict was malformed: "
                                           + "; ".join(errors[:4])}
            return outcome


def _baseline(settings, rubric, entries):
    """Each model's renders against approved renders of the same model and view."""
    from wgf_assets.raster import RasterError, decode_png
    from wgf_visualqa import baseline as measure
    least = float(settings.get("min_similarity") or measure.MIN_SIMILARITY)
    root = settings["baseline_dir"]
    passing = max(rubric["pass_bar"], int(math.ceil(rubric.get("mean_pass_bar") or 0)))
    verdicts, error = {}, None

    def signature(path):
        with open(path, "rb") as handle:
            return measure.signature(decode_png(handle.read()))

    for entry in entries:
        shown = dict(entry.get("views") or {})
        if entry.get("context"):
            shown["context"] = entry["context"]
        compared, regressed = [], []
        try:
            for view, path in sorted(shown.items()):
                approved = os.path.join(root, f"{entry['id']}.{view}.png")
                if not (path and os.path.isfile(path) and os.path.isfile(approved)):
                    continue
                score, _parts = measure.similarity(signature(path), signature(approved))
                compared.append((view, score))
                if score < least:
                    regressed.append((view, score))
        except (OSError, RasterError) as exc:
            error = {"code": "baseline-unreadable", "retryable": False,
                     "message": f"{entry['id']}: {exc}"}
            continue
        if not compared:
            error = {"code": "baseline-missing", "retryable": False,
                     "message": f"no approved render of {entry['id']} under {root} "
                                f"(<id>.<view>.png): a model nobody approved cannot be judged "
                                f"by the baseline judge"}
            continue
        findings = [{"severity": "blocker", "dimension": "in_identity",
                     "note": f"the {view} render is {score:.2f} like the approved one "
                             f"(at least {least:.2f}): the model regressed from the approved "
                             f"craft"} for view, score in regressed]
        scores = {d: (0 if regressed else passing) for d in rubric["dimensions"]}
        summary = (f"baseline: {len(compared)} view(s) compared with the approved renders, "
                   f"lowest {min(s for _v, s in compared):.2f} (bar {least:.2f}); no "
                   f"aesthetic judgement")
        verdicts[entry["id"]] = decide({"scores": scores, "reads_as": not regressed,
                                        "findings": findings, "summary": summary}, rubric)
    return {"verdicts": None if error else verdicts, "runs": [], "error": error,
            "brief": None}


def judge(settings, rubric, entries, workdir, *, identity=None, design=None, guarded=(),
          on_event=None, stem="judge"):
    """Judge `entries` - [{id, role, description, readability, sheet, views {name: path},
    context, lint [warnings]}]. Never raises for the judge's own failure: `error` says why."""
    os.makedirs(workdir, exist_ok=True)
    began = time.monotonic()
    if settings["kind"] == "baseline":
        outcome = _baseline(settings, rubric, entries)
    elif settings["kind"] == "command":
        outcome = _command(settings, rubric, entries, workdir, identity, design, guarded,
                           on_event, stem)
    else:
        outcome = {"verdicts": None, "runs": [], "error": {
            "code": "no-judge", "retryable": False, "message": "no model judge configured"},
            "brief": None}
    outcome["duration_s"] = round(time.monotonic() - began, 3)
    return outcome
