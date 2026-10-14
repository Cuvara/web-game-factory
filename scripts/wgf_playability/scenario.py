"""The scenario each playability check was measured on, read from what the bot recorded.

A check's result alone says PASS or FAIL. Whether a later PASS is the same measurement as an
earlier FAIL - the evidence a repair is verified on (scripts/wgf_triage/lifecycle.py) - needs
what was played: which bot, on which viewport, under which policy and seed, pressing what, in
which probe states, producing which frames. `build(...)` gives every check a stable scenario
id, `<check>@<project>`, and the report a `scenarios` list holding, per id:

    bot          the bot's version (sha256 of bot.spec.ts as the step copied it) and the
                 settings it was handed (sha256 of <out>/settings.json)
    viewport     the project's width and height (null for a check of the build, not a
                 viewport: the level.* checks read the commit's content data file)
    policy       how the bot played the recordings the check reads (POLICIES; naive play's
                 policies and seed from the settings, risk's from its record)
    records      the raw records the check is judged on (analysis.EVIDENCE, extended here
                 for the checks that table leaves out), each with its path and sha256
    actions      the inputs those records list, in order, as recorded: the begin press, each
                 act input with its probe state before and after, each anti-oracle press
                 with its time, a retry, a pause; where the bot keeps only a count (the
                 oracle's presses in win), one entry with that count. `actions_complete`
                 says whether every press is listed one by one
    states       the probe state transitions the records list, with their times
    frames       the frames the check and its records name, each with its path and sha256

Nothing is added that the bot did not record: a field the record does not carry is null,
and a record the bot did not write is absent from `records`.
"""

import hashlib
import json
import os

from . import analysis

__all__ = ["build", "scenario_id", "bot_version", "SOURCES", "POLICIES", "MAX_ACTIONS",
           "MAX_FRAMES", "MAX_STATES"]

# The records a check is judged on, beyond analysis.EVIDENCE (the timing-sensitive ones).
SOURCES = dict(analysis.EVIDENCE, **{
    "probe.present": ("first-session",),
    "probe.valid": ("first-session", "act", "traverse"),
    "act.acknowledged": ("act",),
    "frames.readable": ("first-session", "win"),
    "progression.persists": ("persist",),
    "depth.session_length": ("session",),
    "naive.clear_rate": ("naive",),
})
# Checks read off every record the bot wrote (errors and the console are counted on all).
EVERY_RECORD = ("page.errors", "runtime.")
# Checks of the played commit's files, not of play: the content data file kept beside the
# records (step.CONTENT_COPY).
OF_THE_BUILD = ("level.",)
CONTENT_COPY = os.path.join("content", "units.json")
# How bot.spec.ts plays each recording (its tests, by record name).
POLICIES = {
    "first-session": "idle",
    "act": "each-offered-input",
    "win": "oracle",
    "lose": "anti-oracle",
    "pause": "pause-input",
    "traverse": "oracle",
    "persist": "oracle-then-reload",
    "session": "oracle",
    "ramp": "oracle",
    "showcase": "probe-staged",
    "survey": "unit-link",
    "naive": "naive",
    "risk": "declared-policy",
}
MAX_ACTIONS = 80
MAX_FRAMES = 16
MAX_STATES = 40


def scenario_id(check, project):
    return f"{check}@{project}"


def _sha256(path):
    try:
        with open(path, "rb") as handle:
            return "sha256:" + hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None


def bot_version(path):
    """sha256 of the bot as the step copies it into the clone it plays."""
    return _sha256(path)


def _sources(check_id, records):
    if any(check_id == p or (p.endswith(".") and check_id.startswith(p)) for p in EVERY_RECORD):
        return tuple(name for name in records)
    if check_id in SOURCES:
        return SOURCES[check_id]
    best = None
    for key in SOURCES:
        if key.endswith(".") and check_id.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    return SOURCES.get(best, ())


def _state(snapshot):
    return snapshot.get("state") if isinstance(snapshot, dict) else None


def _action(record, action=None, *, input=None, at_ms=None, before=None, after=None,
            count=None, phase=None):
    return {"record": record, "phase": phase, "action": action, "input": input,
            "at_ms": at_ms, "state_before": before, "state_after": after, "count": count}


def _actions(name, record):
    """(the inputs a record lists, in order, and whether it lists every press)."""
    out, complete = [], True
    if record.get("began"):
        out.append(_action(name, record["began"], phase="start",
                           after="playing" if record.get("playingMs") is not None else None))
    if name == "first-session":
        pass  # no input after the begin press: the idle window is the scenario
    elif name == "act":
        for entry in record.get("acted") or []:
            if isinstance(entry, dict):
                out.append(_action(name, entry.get("action"), phase="act",
                                   input=entry.get("input"), before=_state(entry.get("before")),
                                   after=_state(entry.get("after"))))
    elif name == "win":
        out.append(_action(name, "oracle", phase="play", count=record.get("inputs"),
                           after=record.get("reached")))
        complete = False
    elif name == "lose":
        mid = record.get("resetInUnit")
        if isinstance(mid, dict):
            out.append(_action(name, mid.get("clicked"), phase="reset-in-unit",
                               before="playing",
                               after="playing" if mid.get("playingMs") is not None else None))
        presses = [p for p in record.get("wrongPresses") or [] if isinstance(p, dict)]
        for press in presses:
            out.append(_action(name, press.get("action"), phase="bad-play", at_ms=press.get("ms")))
        restart = record.get("restart")
        if isinstance(restart, dict):
            out.append(_action(name, restart.get("clicked"), phase="retry",
                               before=record.get("reached"),
                               after="playing" if restart.get("playingMs") is not None else None))
        # The one oracle success before bad play, and presses past the record's cap of 60,
        # are not listed by the bot.
        complete = False
    elif name == "pause":
        if record.get("how"):
            out.append(_action(name, record["how"], phase="pause", before="playing",
                               after="paused" if record.get("paused") else None))
    elif name == "naive":
        for run in record.get("runs") or []:
            if isinstance(run, dict):
                out.append(_action(name, run.get("policy"), phase=run.get("unit_id") or "run",
                                   count=run.get("inputs"), at_ms=run.get("played_ms"),
                                   after="won" if run.get("won") else None))
        complete = False
    elif name == "risk":
        for attempt in record.get("attempts") or []:
            if isinstance(attempt, dict):
                out.append(_action(name, attempt.get("policy"), phase=attempt.get("unit"),
                                   at_ms=attempt.get("duration_ms"),
                                   after=attempt.get("outcome")))
        complete = False
    else:
        # traverse, persist, session, ramp, showcase, survey: the bot keeps what play
        # reached, not each press.
        complete = False
    return out, complete


def _states(name, record):
    out = []
    for entry in record.get("states") or []:
        if isinstance(entry, dict) and entry.get("state"):
            out.append({"record": name, "ms": entry.get("ms"), "state": entry["state"]})
    last = None
    for entry in record.get("series") or []:
        if isinstance(entry, dict) and entry.get("state") and entry["state"] != last:
            out.append({"record": name, "ms": entry.get("ms"), "state": entry["state"]})
            last = entry["state"]
    return out


def _policy(sources, records, settings):
    names = [n for n in sources if n in records]
    policy = {"recordings": {n: POLICIES.get(n) for n in names}, "seed": None, "naive": None,
              "risk": None}
    if "naive" in names:
        policy["seed"] = settings.get("naive_seed")
        policy["naive"] = settings.get("naive_policies")
    if "risk" in names:
        policy["risk"] = (records.get("risk") or {}).get("policies")
    return policy


def build(checks, projects, frames, records_by_project, out_dir, run_dir, *, bot=None,
          settings=None):
    """(checks, each with its `scenario` id; the report's `scenarios`).

    `projects` are the report's projects, `frames` its frames, `records_by_project`
    {project: {record name: record}} as the step read them from `out_dir`/<project>/,
    `bot` {"version", "settings_sha256"}, `settings` what the bot was handed."""
    settings = settings or {}
    bot = dict(bot or {})
    viewports = {p.get("id"): p.get("viewport") for p in projects or [] if isinstance(p, dict)}
    by_frame = {(f.get("project"), f.get("id")): f for f in frames or [] if isinstance(f, dict)}

    def rel(path):
        return os.path.relpath(path, run_dir).replace(os.sep, "/") if run_dir else path

    scenarios, seen, out = [], {}, []
    for check in checks:
        check = dict(check)
        cid, project = check.get("id"), check.get("project")
        sid = scenario_id(cid, project)
        check["scenario"] = sid
        out.append(check)
        if sid in seen:
            continue
        records = records_by_project.get(project) or {}
        files = []
        if any(cid.startswith(p) for p in OF_THE_BUILD):
            path = os.path.join(out_dir, CONTENT_COPY)
            if os.path.isfile(path):
                files.append({"name": "content", "path": rel(path), "sha256": _sha256(path)})
            sources = ()
        else:
            sources = tuple(n for n in _sources(cid, records) if n in records)
            for name in sources:
                path = os.path.join(out_dir, project, f"{name}.json")
                files.append({"name": name, "path": rel(path), "sha256": _sha256(path)})
        actions, complete, states, frame_ids = [], bool(sources), [], []
        for name in sources:
            record = records.get(name) or {}
            listed, whole = _actions(name, record)
            actions += listed
            complete = complete and whole
            states += _states(name, record)
            frame_ids += [f for f in record.get("frames") or [] if isinstance(f, str)]
        ordered = []
        for fid in list(check.get("frames") or []) + frame_ids:
            if fid not in ordered:
                ordered.append(fid)
        refs = []
        for fid in ordered:
            entry = by_frame.get((project, fid))
            if entry is not None:
                refs.append({"id": fid, "path": entry.get("path"), "sha256": entry.get("sha256")})
        scenario = {
            "id": sid, "check": cid, "project": project,
            "bot": {"version": bot.get("version"), "settings_sha256": bot.get("settings_sha256")},
            "viewport": viewports.get(project),
            "policy": _policy(sources, records, settings),
            "records": files,
            "actions": actions[:MAX_ACTIONS],
            "actions_complete": complete and len(actions) <= MAX_ACTIONS,
            "states": states[:MAX_STATES],
            "frames": refs[:MAX_FRAMES],
        }
        omitted = {"actions": max(0, len(actions) - MAX_ACTIONS),
                   "states": max(0, len(states) - MAX_STATES),
                   "frames": max(0, len(refs) - MAX_FRAMES)}
        if any(omitted.values()):
            scenario["omitted"] = omitted
        seen[sid] = scenario
        scenarios.append(scenario)
    return out, scenarios


def settings_of(out_dir):
    """(what the bot was handed, its sha256): <out>/settings.json."""
    path = os.path.join(out_dir, "settings.json")
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle), _sha256(path)
    except (OSError, ValueError):
        return {}, None
