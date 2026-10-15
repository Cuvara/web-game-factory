"""The critic's brief: every sampled unit with its objective, the design's words for it and its
frames by moment, the rubric, and the verdict shape. Self-contained - the critic reads it and
the frames, nothing else."""

import json

from .rubric import ROUTES, SEVERITIES, applicable, contract, dimensions

__all__ = ["render_brief", "PROMPT", "PROMPT_STDOUT"]

PROMPT = (
    "You are the level design critic for a web game, not its designer or developer. Read "
    "{brief} in full, then look at every PNG frame under {frames_dir} it lists. You are "
    "READ-ONLY: do not create, edit or delete anything except your verdict. Write your "
    "verdict, and nothing else, as one JSON object to {verdict}, exactly in the shape the "
    "brief gives."
)

PROMPT_STDOUT = (
    "You are the level design critic for a web game, not its designer or developer. Read "
    "{brief} in full, then look at every PNG frame under {frames_dir} it lists. You are "
    "READ-ONLY: do not create, edit or delete any file. End your answer with your verdict as "
    "one JSON object, exactly in the shape the brief gives."
)

# What the design may say of a unit that the critic should know (build_spec.content.units[]).
_UNIT_FIELDS = ("name", "kind", "objective", "layout", "set_piece", "beats", "climax",
                "mechanics", "elements", "notes", "tier")


def _design_lines(unit):
    authored = unit.get("design") or {}
    lines = []
    for key in _UNIT_FIELDS:
        value = authored.get(key)
        if value in (None, "", [], {}):
            continue
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        lines.append(f"  - {key}: {text[:400]}")
    return lines or ["  - (the design states nothing more for this unit)"]


def render_brief(*, title_id, commit, units, rubric, frames_dir, verdict_path, to_stdout,
                 previous_problem=None, repair=None):
    moments = rubric["moments"]
    out = [f"# Level design critique: {title_id} at {commit[:12]}", ""]
    if repair:
        out += ["## Repair your previous verdict", "",
                "Your previous verdict could not be used. Its problems:", ""]
        out += [f"- {p}" for p in repair["problems"]]
        out += ["", "Your previous reply:", "", "```", repair["reply"], "```", "",
                "Write the corrected FULL verdict - every unit, every dimension - not a diff.",
                ""]
    elif previous_problem:
        out += [f"A previous attempt failed: {previous_problem}. Follow the shape exactly.", ""]
    out += [
        "You judge whether the units (levels, waves, courses, rounds) of this game are "
        "DESIGNED: how they use the play space, whether each has an identity, offers a choice, "
        "reveals something and ends on an event, and whether it differs from the unit before "
        "it. You are not judging the art (another judge does) - judge the layout and the play "
        "the frames show. Score what the frames show; where they cannot show a dimension, "
        "score null and say why in score_reasons. Never guess a score.", "",
        "## The frames", "",
        f"Each unit has up to {len(moments)} frames, under {frames_dir}/<unit>/<moment>.png:", ""]
    out += [f"- `{m['id']}`: {m['shows']}" for m in moments]
    out += [""]
    for position, unit in enumerate(units):
        out.append(f"### Unit `{unit['unit_id']}` (sample {position + 1} of {len(units)}"
                   + (f", index {unit['index']}" if unit.get("index") is not None else "")
                   + ")")
        out.append(f"- objective: {unit.get('objective') or '(none stated)'}")
        out.append("- what the design says of it:")
        out += _design_lines(unit)
        for frame in unit["frames"]:
            out.append(f"- frame `{frame['key']}`: {frame['file']}")
        if unit.get("missing_moments"):
            out.append(f"- not captured: {', '.join(unit['missing_moments'])} (judge on the "
                       "frames there are; null what they cannot show)")
        out.append("")
    out += ["## The rubric", "",
            f"Score every dimension 0-5 for every unit (anchors below; 1, 2 and 4 lie between). "
            f"A unit below {rubric['pass_bar']} on any dimension fails; the mean must reach "
            f"{rubric['mean_pass_bar']}. The first unit has no previous unit: score null on "
            "the dimensions marked so.", ""]
    for name in dimensions(rubric):
        dim = rubric["dimensions"][name]
        out.append(f"### `{name}` (route `{dim['route']}`)")
        out.append(dim["question"])
        for anchor in ("0", "3", "5"):
            out.append(f"- {anchor}: {dim['anchors'][anchor]}")
        if not applicable(rubric, name, 0):
            out.append("- the first sampled unit: null (no previous unit)")
        out.append("")
    out += ["## Blockers", "", "Raise each as a finding with `severity: blocker` wherever it "
            "holds, whatever the scores:", ""]
    out += [f"- `{b['id']}` (route `{b['route']}`): {b['rule']}"
            for b in rubric.get("blockers") or []]
    out += ["", "Other findings are `major` or `minor`. Every finding names its route: "
            f"{' or '.join(f'`{r}`' for r in ROUTES)} - `design-gap` only when the design itself "
            "says nothing that would let the unit be built better. Severities: "
            f"{', '.join(SEVERITIES)}.", "",
            "## Your verdict", "",
            ("End your answer with ONE JSON object in this shape:" if to_stdout else
             f"Write ONE JSON object to {verdict_path} in this shape:"), "",
            "```json", json.dumps(contract(rubric, units), indent=2, ensure_ascii=False), "```",
            ""]
    return "\n".join(out)
