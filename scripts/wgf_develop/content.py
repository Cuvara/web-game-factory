"""The content contract: the design's content units, built as data and checked against it.

A design states every unit of content the player meets - every level, wave, track, lap,
encounter, scenario, shift, round, map or run-segment - in `build_spec.content.units`, with
its objective, the mechanics it asks for, its difficulty on the family's axes, how it is won
and how it is lost (game-design 1.9.0, held to `core/reference/genre-models.yaml`). This
module is what stops a one-unit prototype being reported as that game: the brief hands the
developer the table, the developer writes it as data, and `checks.conformance` compares the
data with the design.

The contract applies when the design's `build_spec.content` has
`generation.mode == "authored"` and at least one MVP unit: every unit the tier ships is
listed, so every unit can be compared one for one. A `parametric` or `procedural` design
generates its units from `generation.parameters` and lists only representative segments -
the brief still carries the table, but there is nothing to compare a data file against, so
no data file is owed.

The data file (`public/content/units.json`), written by the developer, read by the game at
boot and by this module:

    {
      "schema": "wgf-content/1",
      "design": {"artifact_id": "wgf:game-design:<title>:<date>-<n>",
                 "content_hash": "<the game-design pin the brief names>"},
      "genre": {"family": "platformer", "node": "platformer",
                "session_profile": "standard", "ending": "finite"},
      "unit_kind": "level",
      "generation": {"mode": "authored"},
      "units": [
        {"id": "l-01", "index": 1, "tier": "mvp",
         "objective": "Reach the exit without falling",
         "mechanics": ["run", "jump"], "introduces": ["jump"],
         "difficulty": {"precision": 0.1, "timing": 0.1},
         "expected_duration_s": 45,
         "success": "The player reaches the exit flag",
         "failure": "A fall costs a life and restarts the level"}
      ],
      "tuning": {"jump": {"height_px": 96, "coyote_ms": 90}}
    }

`units` is the design's MVP units, by the design's ids, in the design's index order, with
the design's values. `tuning` carries every `build_spec.mechanics[].parameters` key as data,
so a playtest changes a number rather than the code. Nothing here is the developer's to
invent: where the design is silent, the gap goes in the development report's `design_gaps`
and the unit is `partial` or `cut`.

Findings are `<code>: <explanation>` strings, the code first so the step and the tests can
name one:

    content.file_missing              the data file is absent or unreadable
    content.design_pin                its `design.content_hash` is not the brief's pin
    content.unit_missing:<id>         a design unit is not in the file
    content.unit_extra:<id>           the file carries a unit the MVP tier does not
    content.unit_field:<id>.<field>   index, objective, mechanics, success or failure differ
    content.difficulty:<id>.<axis>    the value is further than the tolerance from the design
    content.tuning:<mechanic>.<param> a mechanic parameter is not in `tuning`
    content.test_missing              the unit test over the data file was not written
    content.not_loaded                no file under src/ reads the data file
"""

import json
import os

from wgflib import genre_models

__all__ = ["CONTENT_PATH", "TEST_PATH", "SCHEMA", "MVP_TIERS", "GENRE_MODELS_PATH",
           "implementation", "applies", "expected_units", "read_content",
           "content_findings", "table_rows", "codes"]

# The data file the developer writes and the game loads, and the unit test over it. Both are
# inside the paths a developer may write (scope.DEFAULT_WRITABLE: public/, tests/).
CONTENT_PATH = "public/content/units.json"
TEST_PATH = "tests/unit/content.test.ts"  # *.test.ts: the only pattern the template's unit project collects
SCHEMA = "wgf-content/1"

# The tiers the MVP build covers. Kept equal to wgf_develop.brief.BUILD_TIERS (a test checks
# it; importing it here would make brief's import of this module circular).
MVP_TIERS = (None, "mvp")

# core/reference/genre-models.yaml, read through the one loader every judging step uses.
GENRE_MODELS_PATH = genre_models.PATH

# The game source extensions scanned for the load of the data file.
_SOURCE = (".ts", ".tsx", ".js", ".mjs", ".mts")
# What a source file must name to be loading the data file: the path without `public/`, which
# is the url the bundle serves it at.
_LOAD_REFERENCE = CONTENT_PATH.split("/", 1)[1]

def implementation(models=None):
    """The `implementation` block: what the developer and the plan are held to."""
    models = genre_models.load() if models is None else models
    return dict((models or {}).get("implementation") or {})


def _content(design):
    spec = (design or {}).get("build_spec")
    content = (spec or {}).get("content") if isinstance(spec, dict) else None
    return content if isinstance(content, dict) else {}


def expected_units(design):
    """The design's MVP content units, in index order. The units a build owes."""
    units = [u for u in _content(design).get("units") or []
             if isinstance(u, dict) and u.get("tier") in MVP_TIERS]
    return sorted(units, key=lambda u: (u.get("index") if isinstance(u.get("index"), int)
                                        else 10 ** 6, str(u.get("id"))))


def applies(design):
    """Whether the content contract applies: an authored design with at least one MVP unit."""
    content = _content(design)
    mode = (content.get("generation") or {}).get("mode")
    return mode == "authored" and bool(expected_units(design))


def read_content(root):
    """The data file as (data, None), or (None, problem)."""
    path = os.path.join(root, CONTENT_PATH)
    if not os.path.exists(path):
        return None, f"{CONTENT_PATH} was not written"
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        return None, f"{CONTENT_PATH} cannot be read: {exc}"
    except ValueError as exc:
        return None, f"{CONTENT_PATH} is not JSON: {exc}"
    if not isinstance(data, dict):
        return None, f"{CONTENT_PATH} is not a JSON object"
    return data, None


def codes(findings):
    """The finding codes of `findings`, without their explanations."""
    return [str(finding).split(": ", 1)[0] for finding in findings]


def table_rows(units, axes):
    """(header, rows) for the content table, so the brief and the GDD render one contract.

    One column per difficulty axis, because the axes are what a unit's difficulty is stated
    on and a table with a single `difficulty` column hides whether they move."""
    axis_ids = [a.get("id") for a in axes or [] if isinstance(a, dict) and a.get("id")]
    header = (["#", "id", "purpose", "objective", "introduces", "mechanics"]
              + [f"d:{axis}" for axis in axis_ids]
              + ["duration s", "success", "failure"])
    rows = []
    for unit in units or []:
        difficulty = unit.get("difficulty") or {}
        rows.append([unit.get("index"), unit.get("id"), unit.get("purpose"),
                     unit.get("objective"),
                     ", ".join(unit.get("introduces") or []) or "-",
                     ", ".join(unit.get("mechanics") or [])]
                    + [difficulty.get(axis, "-") for axis in axis_ids]
                    + [unit.get("expected_duration_s"), unit.get("success"),
                       unit.get("failure")])
    return header, rows


def _selection(brief_or_design):
    """What the findings are computed from, whether given a brief or a game-design.

    A brief carries the selection the developer was handed (`content`, `build_spec.sections`
    and the input pins); a design is selected from directly, so the module can be used on one
    without building a brief first."""
    content = brief_or_design.get("content")
    if isinstance(content, dict) and "applies" in content:
        sections = (brief_or_design.get("build_spec") or {}).get("sections") or {}
        pin = next((p for p in brief_or_design.get("inputs") or []
                    if isinstance(p, dict) and p.get("artifact_type") == "game-design"), {})
        return {
            "applies": bool(content.get("applies")),
            "units": list(content.get("units") or []),
            "axes": list(content.get("axes") or []),
            "mechanics": [m for m in sections.get("mechanics") or [] if isinstance(m, dict)],
            "pin": {"artifact_id": pin.get("artifact_id"),
                    "content_hash": pin.get("content_hash")},
        }
    design = brief_or_design
    spec = design.get("build_spec") or {}
    provenance = design.get("provenance") or {}
    return {
        "applies": applies(design),
        "units": expected_units(design),
        "axes": list((spec.get("difficulty") or {}).get("axes") or []),
        "mechanics": [m for m in spec.get("mechanics") or []
                      if isinstance(m, dict) and m.get("tier") in MVP_TIERS],
        "pin": {"artifact_id": provenance.get("artifact_id"),
                "content_hash": provenance.get("content_hash")},
    }


def _loads_content(root):
    """Whether any game source under src/ reads the data file."""
    top = os.path.join(root, "src")
    for directory, dirs, files in os.walk(top):
        dirs[:] = [d for d in dirs if d != "node_modules"]
        for name in files:
            if not name.endswith(_SOURCE):
                continue
            try:
                with open(os.path.join(directory, name), encoding="utf-8",
                          errors="replace") as handle:
                    if _LOAD_REFERENCE in handle.read():
                        return True
            except OSError:
                continue
    return False


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _unit_findings(unit, built, tolerance):
    """One design unit against the one the data file carries."""
    uid = unit.get("id")
    findings = []
    for field in ("index", "objective", "success", "failure"):
        if field not in unit:
            continue
        if built.get(field) != unit.get(field):
            findings.append(f"content.unit_field:{uid}.{field}: the design says "
                            f"{unit.get(field)!r}, {CONTENT_PATH} says {built.get(field)!r}")
    designed = [m for m in unit.get("mechanics") or [] if isinstance(m, str)]
    if designed and set(built.get("mechanics") or []) != set(designed):
        findings.append(f"content.unit_field:{uid}.mechanics: the design asks for "
                        f"{sorted(designed)}, {CONTENT_PATH} carries "
                        f"{sorted(set(built.get('mechanics') or []))}")
    difficulty = built.get("difficulty") if isinstance(built.get("difficulty"), dict) else {}
    for axis, value in sorted((unit.get("difficulty") or {}).items()):
        if not _number(value):
            continue
        got = difficulty.get(axis)
        if not _number(got):
            findings.append(f"content.difficulty:{uid}.{axis}: the design sets {value}, "
                            f"{CONTENT_PATH} sets none")
        # Rounded, so a value the design states as 0.1 and the file as 0.15 is inside a
        # tolerance of 0.05 rather than outside it by a float's last bit.
        elif round(abs(float(got) - float(value)), 9) > tolerance:
            findings.append(f"content.difficulty:{uid}.{axis}: the design sets {value}, "
                            f"{CONTENT_PATH} sets {got} - further than the family's "
                            f"tolerance of {tolerance}")
    return findings


def _same_pin(written, pinned):
    """The data file's pin names the design: the full hash, or an unambiguous prefix of it of
    at least 12 hex digits (the brief's Input line shows the pin shortened)."""
    if not isinstance(written, str) or not isinstance(pinned, str):
        return False
    if written == pinned:
        return True
    w, p = written.lower(), pinned.lower()
    for prefix in ("sha256:",):
        if w.startswith(prefix) and p.startswith(prefix):
            w, p = w[len(prefix):], p[len(prefix):]
    return len(w) >= 12 and p.startswith(w)


def content_findings(root, brief_or_design, models=None):
    """Every way the checkout's content data disagrees with the design it was built from.

    Empty when the content contract does not apply: a parametric or procedural design owes
    no data file, and a design that states no content units owes nothing at all."""
    selection = _selection(brief_or_design)
    if not selection["applies"]:
        return []
    tolerance = implementation(models).get("difficulty_tolerance")
    tolerance = float(tolerance) if _number(tolerance) else 0.0
    findings = []
    data, problem = read_content(root)
    if problem:
        findings.append(f"content.file_missing: {problem} - every MVP content unit of the "
                        f"brief's table belongs in it")
    else:
        pinned = selection["pin"].get("content_hash")
        built_pin = (data.get("design") or {}).get("content_hash")
        if pinned and not _same_pin(built_pin, pinned):
            findings.append(f"content.design_pin: {CONTENT_PATH} says it was built from "
                            f"game-design {built_pin or 'none'}, this visit builds "
                            f"{pinned}")
        built = {u.get("id"): u for u in data.get("units") or [] if isinstance(u, dict)}
        for unit in selection["units"]:
            uid = unit.get("id")
            if uid not in built:
                findings.append(f"content.unit_missing:{uid}: the design's {uid!r} is not in "
                                f"{CONTENT_PATH}")
                continue
            findings.extend(_unit_findings(unit, built[uid], tolerance))
        designed = {u.get("id") for u in selection["units"]}
        for uid in sorted(i for i in built if i not in designed):
            findings.append(f"content.unit_extra:{uid}: {CONTENT_PATH} carries a unit the "
                            f"design's MVP tier does not name")
        tuning = data.get("tuning") if isinstance(data.get("tuning"), dict) else {}
        for mechanic in selection["mechanics"]:
            parameters = mechanic.get("parameters")
            if not isinstance(parameters, dict):
                continue
            values = tuning.get(mechanic.get("id"))
            values = values if isinstance(values, dict) else {}
            for name in sorted(parameters):
                if name not in values:
                    findings.append(f"content.tuning:{mechanic.get('id')}.{name}: the "
                                    f"mechanic's starting tuning is not in "
                                    f"{CONTENT_PATH} under tuning["
                                    f"{mechanic.get('id')!r}]")
    if not os.path.exists(os.path.join(root, TEST_PATH)):
        findings.append(f"content.test_missing: {TEST_PATH} was not written - the data file "
                        f"is what the units are, so it is unit-tested")
    if not _loads_content(root):
        findings.append(f"content.not_loaded: no file under src/ reads {_LOAD_REFERENCE}, so "
                        f"the units are not the ones the game plays")
    return findings
