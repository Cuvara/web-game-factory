"""The `baseline` judge: runtime frames against approved frames of the same state, no agent.

    factory:
      visualqa:
        judge:
          kind: baseline
          baseline_dir: <dir>        # <viewport>/<name>.png, the approved frames
          min_similarity: 0.70       # optional; the bar a frame's best match must reach

For a game whose look has been approved once - a golden run's reference port - the question
visual QA asks ("does this look like the finished game?") has a mechanical answer: does each
frame of the build look like the approved frame of the same state? This judge answers it, and
writes the verdict a command judge would (rubric.parse checks it), so the step decides it the
same way (rubric.decide).

Approved frames are grouped into the rubric's states by file name: a file named after a
state (`gameplay.png`), one of NAMES (`title.png` is `initial`, `game-over.png` is `loss`,
...), or as `<baseline_dir>/states.json` maps it ({"<file stem>": "<state>" | null}). A name
mapped to null, or unknown, is not compared. Runtime frames get their state from their id
(brief.frame_state), as the brief shows a command judge.

The measure tolerates what differs between two plays of one finished game - where the pieces
are, animation timing, a score - and fails what a regression to placeholders or primitives
changes: the palette (colour histogram intersection), the detail (how much of the frame is
edges) and the large-scale layout (a coarse grid of mean colours). Each frame is compared with
every approved frame of its state and viewport; its best match must reach `min_similarity`.

    regression  a frame whose best match is below the bar: a blocker finding (`assets`,
                route assets), and its state's `entities_recognisable` false and
                `primitives_or_placeholders` true
    unmatched   a runtime state with no approved frame on that viewport, or an approved
                state no runtime frame shows: a minor finding each, reported, never a pass
                or a failure on its own

Scores carry no aesthetic judgement: every dimension is at the pass bar when nothing
regressed; the asset dimensions are 0 when anything did. The notes say so.
"""

import math
import json
import os

from wgf_assets.raster import RasterError, decode_png

from .rubric import parse, questions_for, state_ids

__all__ = ["BaselineError", "judge", "signature", "similarity", "load_baseline", "NAMES",
           "MIN_SIMILARITY"]

# Common names of approved frames that are not rubric state ids.
NAMES = {
    "title": "initial", "start": "initial", "menu": "initial", "boot": "initial",
    "playing": "gameplay", "near-full": "gameplay", "play": "gameplay",
    "merge": "interaction", "action": "interaction",
    "game-over": "loss", "lost": "loss", "gameover": "loss",
    "won": "win", "victory": "win",
    "retry-playing": "retry", "restart": "retry",
    # A pause screen is what the player sees just after the pause action (the bot's
    # act-pause-after and state-paused frames).
    "paused": "interaction", "pause": "interaction",
}
# Calibrated on both golden ports (docs/visual-qa-module.md, "The baseline judge"): with
# placeholder art 0.37-0.52 and with none 0.45-0.69 (2D), 0.53-0.78 with none (3D, where a
# mostly-DOM screen can pass); finished, 0.76-0.99 (2D, two runs) and 0.81-0.99 (3D).
MIN_SIMILARITY = 0.70
# The measure: weights of its three parts (they sum to 1), and the sampling it uses.
WEIGHTS = {"palette": 0.5, "detail": 0.2, "layout": 0.3}
GRID = (16, 9)          # layout cells
SAMPLE = (160, 90)      # pixels sampled per frame for the palette and the detail
EDGE_DELTA = 48         # luminance step between neighbours that counts as an edge
ASSET_DIMENSIONS = ("art_completeness", "character_readability", "environment", "consistency")


class BaselineError(ValueError):
    """The baseline directory is unusable."""


def _load(path):
    try:
        with open(path, "rb") as handle:
            return decode_png(handle.read())
    except (OSError, RasterError) as exc:
        raise BaselineError(f"cannot read {path}: {exc}")


def signature(image):
    """What the measure compares, from one decoded frame: a 512-bin colour histogram, the
    share of sampled neighbours that differ by an edge, and a grid of mean colours."""
    width, height, pixels = image.width, image.height, image.pixels
    sw, sh = SAMPLE
    gw, gh = GRID
    hist = [0] * 512
    cells = [[0, 0, 0, 0] for _ in range(gw * gh)]
    luma = []
    for j in range(sh):
        y = min(height - 1, (2 * j + 1) * height // (2 * sh))
        row = []
        for i in range(sw):
            x = min(width - 1, (2 * i + 1) * width // (2 * sw))
            k = (y * width + x) * 4
            r, g, b = pixels[k], pixels[k + 1], pixels[k + 2]
            hist[(r >> 5) << 6 | (g >> 5) << 3 | (b >> 5)] += 1
            cell = cells[(j * gh // sh) * gw + (i * gw // sw)]
            cell[0] += r
            cell[1] += g
            cell[2] += b
            cell[3] += 1
            row.append((299 * r + 587 * g + 114 * b) // 1000)
        luma.append(row)
    total = float(sw * sh)
    edges = pairs = 0
    for j in range(sh):
        for i in range(sw):
            if i + 1 < sw:
                pairs += 1
                edges += abs(luma[j][i] - luma[j][i + 1]) >= EDGE_DELTA
            if j + 1 < sh:
                pairs += 1
                edges += abs(luma[j][i] - luma[j + 1][i]) >= EDGE_DELTA
    return {"hist": [h / total for h in hist],
            "detail": edges / float(pairs),
            "cells": [tuple(c[n] / max(c[3], 1) for n in range(3)) for c in cells]}


def similarity(a, b):
    """(score 0..1, parts) of two signatures."""
    palette = sum(min(x, y) for x, y in zip(a["hist"], b["hist"]))
    high, low = max(a["detail"], b["detail"]), min(a["detail"], b["detail"])
    detail = 1.0 if high == 0 else low / high
    layout = 1.0 - sum(abs(p - q) for ca, cb in zip(a["cells"], b["cells"])
                       for p, q in zip(ca, cb)) / (255.0 * 3 * len(a["cells"]))
    parts = {"palette": round(palette, 4), "detail": round(detail, 4),
             "layout": round(layout, 4)}
    score = sum(WEIGHTS[k] * v for k, v in parts.items())
    return round(score, 4), parts


def load_baseline(baseline_dir, rubric):
    """{(state, viewport): [{name, path, signature}]} and the approved files not compared."""
    if not baseline_dir or not os.path.isdir(baseline_dir):
        raise BaselineError(f"the baseline directory {baseline_dir!r} does not exist")
    names = dict(NAMES)
    mapping = os.path.join(baseline_dir, "states.json")
    if os.path.isfile(mapping):
        try:
            with open(mapping, encoding="utf-8") as handle:
                names.update(json.load(handle))
        except (OSError, ValueError) as exc:
            raise BaselineError(f"cannot read {mapping}: {exc}")
    states = set(state_ids(rubric))
    approved, ignored = {}, []
    for viewport in sorted(os.listdir(baseline_dir)):
        folder = os.path.join(baseline_dir, viewport)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".png"):
                continue
            stem = name[:-4]
            state = stem if stem in states else names.get(stem)
            if state not in states:
                ignored.append(f"{viewport}/{name}")
                continue
            path = os.path.join(folder, name)
            approved.setdefault((state, viewport), []).append(
                {"name": f"{viewport}/{stem}", "path": path, "signature": signature(_load(path))})
    if not approved:
        raise BaselineError(f"{baseline_dir} holds no approved frame of a rubric state "
                            f"(<viewport>/<name>.png)")
    return approved, ignored


def _slug(text):
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")


def judge(rubric, frames, baseline_dir, min_similarity=None):
    """(verdict, comparisons): the rubric verdict for the staged `frames` ({key, state,
    project, file}), and every comparison made. BaselineError when the baseline is
    unusable."""
    bar = MIN_SIMILARITY if min_similarity is None else float(min_similarity)
    approved, ignored = load_baseline(baseline_dir, rubric)
    comparisons, findings = [], []
    regressed, matched = set(), set()
    for frame in frames:
        pair = (frame["state"], frame["project"])
        candidates = approved.get(pair) or []
        if not candidates:
            comparisons.append({"frame": frame["key"], "state": pair[0], "viewport": pair[1],
                                "baseline": None, "score": None, "parts": None,
                                "passed": None})
            continue
        own = signature(_load(frame["file"]))
        scored = sorted(((similarity(own, c["signature"]), c["name"]) for c in candidates),
                        key=lambda item: -item[0][0])
        (score, parts), name = scored[0]
        passed = score >= bar
        comparisons.append({"frame": frame["key"], "state": pair[0], "viewport": pair[1],
                            "baseline": name, "score": score, "parts": parts,
                            "passed": passed,
                            "others": [{"baseline": n, "score": s} for (s, _p), n in scored[1:]]})
        (matched if passed else regressed).add(pair)
        if not passed:
            findings.append({
                "id": f"baseline-regression-{_slug(frame['key'])}", "severity": "blocker",
                "category": "assets", "frame": frame["key"], "route": "assets",
                "summary": (f"{frame['key']} ({pair[1]} {pair[0]}) is not the approved look: "
                            f"best match {name} scores {score} (palette {parts['palette']}, "
                            f"detail {parts['detail']}, layout {parts['layout']}), below "
                            f"{bar} - placeholders, primitives or missing art where the "
                            f"approved frame has finished art")})
    shown = {(f["state"], f["project"]) for f in frames}
    for state, viewport in sorted(shown - set(approved)):
        findings.append({"id": f"no-baseline-{_slug(viewport)}-{_slug(state)}",
                         "severity": "minor", "category": "consistency", "frame": None,
                         "route": "develop",
                         "summary": f"no approved frame of {viewport} {state}: its frames "
                                    f"were not compared"})
    viewports = {f["project"] for f in frames}
    for state, viewport in sorted(set(approved) - shown):
        if viewport in viewports:
            findings.append({"id": f"baseline-unseen-{_slug(viewport)}-{_slug(state)}",
                             "severity": "minor", "category": "consistency", "frame": None,
                             "route": "develop",
                             "summary": f"the approved {viewport} {state} was not seen at "
                                        f"runtime: no frame of it was captured to compare"})
    # "Matches the approved frames" sits exactly at the bars: the per-dimension one and the
    # mean one (rounded up to a whole score). Not an aesthetic judgement - see the notes.
    pass_bar = max(rubric["pass_bar"], math.ceil(rubric.get("mean_pass_bar") or 0))
    scores = {name: (0 if regressed and name in ASSET_DIMENSIONS else pass_bar)
              for name in rubric["dimensions"]}
    states = []
    for state in state_ids(rubric):
        for viewport in sorted(viewports):
            pair = (state, viewport)
            if pair not in shown:
                continue
            verdict_known = pair in regressed or pair in matched
            answers = {}
            for question in questions_for(rubric, state):
                value = None
                if verdict_known and question["id"] == "entities_recognisable":
                    value = pair not in regressed
                elif verdict_known and question["id"] == "primitives_or_placeholders":
                    value = pair in regressed
                answers[question["id"]] = value
            states.append({"state": state, "viewport": viewport, "answers": answers,
                           "comment": ("regressed from the approved frame" if pair in regressed
                                       else "matches the approved frame" if pair in matched
                                       else "no approved frame to compare")})
    compared = [c for c in comparisons if c["score"] is not None]
    verdict = {
        "scores": scores,
        "findings": findings,
        "states": states,
        "look": "developer-prototype" if regressed else "finished-game",
        "look_reason": (f"{len(regressed)} state(s) regressed from the approved frames"
                        if regressed else
                        f"every compared frame matches its approved state ({len(compared)} "
                        f"frames, lowest {min((c['score'] for c in compared), default=None)})"),
        "notes": ("baseline judge: frames compared with approved frames by palette, detail "
                  f"and layout (bar {bar}); scores are not an aesthetic judgement - every "
                  "dimension sits at the pass bars unless a frame regressed, when the asset "
                  "dimensions are 0. Not compared: "
                  + (", ".join(ignored) if ignored else "nothing") + "."),
    }
    checked, problem = parse(verdict, rubric, frames)
    if problem:
        raise BaselineError(f"the baseline verdict is malformed ({problem}): a defect in "
                            f"wgf_visualqa/baseline.py")
    return checked, comparisons
