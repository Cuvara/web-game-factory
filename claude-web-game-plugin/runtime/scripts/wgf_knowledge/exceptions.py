"""A person's knowledge exception: granted on one run, recorded as an operator event.

    wgf resume <run-id> --except RULE --reason TEXT --expires DATE [--scope KEY=VALUE ...]
                        [--approved-by NAME]
    wgf resume <run-id> --except FILE.json      a knowledge-exception record, or a list

A blocking or required rule that applies to a run must be satisfied by the build, or
excepted by a person (core/artifacts/shared/knowledge-exception.schema.json). An exception
is granted the way a budget is raised: on a person's `wgf resume`, as an operator event
(EVENT) the engine records with the resume's nonce, refused when the command runs inside a
Factory step's process tree. It is never granted by configuration (`factory.knowledge.
exceptions` is reported refused, never honoured), never by a mode or an approver written in
a record - the grant stamps `approved_by` itself from who invokes it: `identifier` is the
resume's `decided_by` (the event's own, so the two always agree) and `mode` human - and never
past its expiry.

The event's data is {"exception": <record>, "approver": <name>}: `approver` is the person's
handle as given (`--approved-by`, else the login name), for the audit; the engine adds
`decided_by`, `decided_at` and `resume_nonce`.

    request(rule_ids, reason, expires, scope_pairs, approver)   partial records from the CLI
    requests_from_file(path)                                    partial records from a file
    grant(state, run_dir, requests, decided_by, now=None, read_artifact=None)
                                    the operator events' data: each complete record checked
                                    against the run's pinned knowledge
                                    (model.exception_problems at `now`), its schema, and the
                                    run itself (its rules, platforms and viewports); raises
                                    ExceptionRefused naming every problem
    granted(events)                 the records a person's resume recorded, oldest first
    from_config(config)             a configured exception, as a contract's refused entry
"""

import datetime
import getpass
import json
import os

from . import model

__all__ = ["EVENT", "ExceptionRefused", "request", "requests_from_file", "grant", "granted",
           "from_config", "SCOPE_KEYS"]

EVENT = "KNOWLEDGE_EXCEPTION_GRANTED"
RESUMED_EVENT = "WORKFLOW_RESUMED"
CONFIG_SECTION, CONFIG_KEY = "knowledge", "exceptions"
SCHEMA = "core/artifacts/shared/knowledge-exception.schema.json"
# --scope KEY=VALUE: singular or plural key -> the record's scope key.
SCOPE_KEYS = {"platform": "platforms", "platforms": "platforms", "check": "checks",
              "checks": "checks", "viewport": "viewports", "viewports": "viewports"}


class ExceptionRefused(ValueError):
    """An exception that cannot be granted, with every reason."""


def _stamp(moment):
    return moment.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now(now=None):
    if isinstance(now, datetime.datetime):
        return now if now.tzinfo else now.replace(tzinfo=datetime.timezone.utc)
    parsed = model.parse_time(now) if now else None
    return parsed or datetime.datetime.now(datetime.timezone.utc)


def expiry(text):
    """An ISO 8601 date-time with its offset, as given; a bare date YYYY-MM-DD is the end of
    that day, UTC. Raises ExceptionRefused for anything else."""
    text = str(text or "").strip()
    if not text:
        raise ExceptionRefused("an exception expires: give --expires DATE (YYYY-MM-DD, or an "
                               "ISO 8601 date-time with its offset)")
    try:
        day = datetime.date.fromisoformat(text)
    except ValueError:
        day = None
    if day is not None and len(text) == 10:
        return f"{day.isoformat()}T23:59:59Z"
    if model.parse_time(text) is None:
        raise ExceptionRefused(f"--expires {text!r} is not a date (YYYY-MM-DD) or an ISO 8601 "
                               "date-time with its offset")
    return text


def _scope(pairs):
    scope = {}
    for pair in pairs or ():
        key, sep, value = str(pair).partition("=")
        key, value = key.strip().lower(), value.strip()
        if not sep or key not in SCOPE_KEYS or not value:
            raise ExceptionRefused(f"--scope {pair!r} is not KEY=VALUE with KEY one of "
                                   "platform, check, viewport")
        values = scope.setdefault(SCOPE_KEYS[key], [])
        for item in value.split(","):
            item = item.strip()
            if item and item not in values:
                values.append(item)
    return scope


def _approver(name=None):
    if name and str(name).strip():
        return str(name).strip()
    try:
        return getpass.getuser() or "person"
    except Exception:  # noqa: BLE001 - no login name on this host: a person, unnamed
        return "person"


def request(rule_ids, reason, expires, scope_pairs=(), approver=None):
    """[partial record] for each rule id given on the command line, with the same reason,
    expiry and scope. `approved_by.mode` is not taken from here: grant() stamps it."""
    if not rule_ids:
        raise ExceptionRefused("--except names the rule (a lesson id) or a JSON file")
    expires_at = expiry(expires)
    scope = _scope(scope_pairs)
    return [{"rule_id": str(rule_id).strip(), "reason": reason, "scope": dict(scope),
             "expires_at": expires_at,
             "approved_by": {"identifier": _approver(approver)}}
            for rule_id in rule_ids]


def requests_from_file(path, approver=None):
    """[partial record] from a JSON file holding one knowledge-exception record or a list.
    `approved_by.mode` and `created_at` in the file are not trusted: grant() stamps both."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ExceptionRefused(f"--except {path}: {exc}")
    records = data if isinstance(data, list) else [data]
    out = []
    for record in records:
        if not isinstance(record, dict):
            raise ExceptionRefused(f"--except {path}: an exception is a JSON object")
        record = dict(record)
        if record.get("expires_at"):
            record["expires_at"] = expiry(record["expires_at"])
        approved = record.get("approved_by")
        identifier = approved.get("identifier") if isinstance(approved, dict) else None
        record["approved_by"] = {"identifier": _approver(approver or identifier)}
        out.append(record)
    return out


# --------------------------------------------------------------------------- the grant


def _schema_problems(record):
    from wgflib import jsonschema_lite, paths
    path = os.path.join(paths.ROOT, *SCHEMA.split("/"))
    try:
        with open(path, encoding="utf-8") as handle:
            schema = json.load(handle)
    except (OSError, ValueError) as exc:
        return [f"the exception schema cannot be read ({exc})"]
    validator = jsonschema_lite.Validator(schema)
    return [f"{e.pointer or '/'}: {e.message}" for e in validator.iter_errors(record)]


def _latest(state, kind, read_artifact):
    ref = state.latest_of_type(kind) if hasattr(state, "latest_of_type") else None
    if ref is None or read_artifact is None:
        return None
    try:
        return read_artifact(ref)
    except Exception:  # noqa: BLE001 - an artifact that cannot be read is not the run's word
        return None


def run_facets(state, read_artifact):
    """The run's facets as it holds them now: its contract's, else resolved from its newest
    game-design, title-strategy and the tier it started with. ({facets}, contract or None)."""
    from . import resolve as resolver
    from wgflib.workflow import quality
    contract = _latest(state, "knowledge-contract", read_artifact)
    if isinstance(contract, dict) and isinstance(contract.get("facets"), dict):
        return resolver.facets(**{k: contract["facets"].get(k) for k in resolver.FACET_KEYS}), \
            contract
    design = _latest(state, "game-design", read_artifact)
    strategy = _latest(state, "title-strategy", read_artifact)
    return resolver.facets_from(design, strategy, quality.run_tier(state.params)), None


def _run_problems(record, knowledge, facets, contract):
    """What does not match the run beyond the record's own rules (model.exception_problems,
    which holds platforms against the run's targets and viewports against the ones a gate
    plays): a rule that does not apply to it, and a platform scope while the run targets
    none yet."""
    from . import resolve as resolver
    problems = []
    if isinstance(contract, dict):
        applicable = {r.get("id") for r in contract.get("rules") or ()}
        if record.get("rule_id") not in applicable:
            problems.append(f"rule {record.get('rule_id')} does not apply to this run (its "
                            "knowledge-contract does not list it)")
    else:
        lesson = next((l for l in (knowledge.lessons or {}).get("lessons") or ()
                       if isinstance(l, dict) and l.get("id") == record.get("rule_id")), None)
        if lesson is not None:
            ok, why = resolver.applies(lesson, facets)
            if not ok:
                problems.append(f"rule {record.get('rule_id')} does not apply to this run "
                                f"({why})")
    scope = record.get("scope") if isinstance(record.get("scope"), dict) else {}
    if scope.get("platforms") and not facets.get("platforms"):
        problems.append("scope.platforms: the run targets no platform yet (no "
                        "title-strategy), so an exception cannot be scoped to one")
    return problems


def grant(state, run_dir, requests, decided_by, now=None, read_artifact=None):
    """[{"exception": record, "approver": name}]: the operator events' data for the
    knowledge-exception records `requests` grant the run `state`, each stamped `approved_by`
    {identifier: `decided_by`, mode: human} and `created_at` now. Raises ExceptionRefused
    naming every problem of every record (none is granted unless all hold), and for
    `decided_by` automation - an agent never excepts a rule it is held to."""
    from .step import advisory_run, load_run_knowledge, KnowledgeUnavailable
    if not isinstance(decided_by, str) or not decided_by.strip() or decided_by == "automation":
        raise ExceptionRefused(
            f"unauthorized: decided_by {decided_by!r} - an exception is a person's act, granted "
            "from outside the run, never by automation")
    moment = _now(now)
    params = getattr(state, "params", None) or {}
    if advisory_run(params):
        raise ExceptionRefused(
            f"run {getattr(state, 'run_id', '?')} started before the knowledge model: it "
            "holds no knowledge contract, and its compliance is advisory only - there is "
            "nothing to except")
    try:
        facets, contract = run_facets(state, read_artifact)
        knowledge = load_run_knowledge(params, run_dir, facets["platforms"], strict=True)
        vocabulary = model.vocabulary(knowledge.root)
    except (KnowledgeUnavailable, model.KnowledgeError, ValueError) as exc:
        raise ExceptionRefused(f"the run's knowledge cannot be read ({exc})")
    records, problems = [], []
    for index, partial in enumerate(requests or ()):
        if not isinstance(partial, dict):
            problems.append(f"exception {index + 1}: not a mapping")
            continue
        claimed = partial.get("created_at")
        if claimed not in (None, ""):
            # Stamped below, never taken from the request; one that claims a moment after
            # this one says the request is not what it seems.
            stamp = model.parse_time(claimed)
            if stamp is None or stamp > moment:
                problems.append(f"exception {index + 1} ({partial.get('rule_id')}): "
                                f"created_at {claimed!r} is in the future or not a date-time")
        approved = partial.get("approved_by")
        name = approved.get("identifier") if isinstance(approved, dict) else None
        record = {key: partial[key] for key in ("rule_id", "reason", "scope", "expires_at")
                  if key in partial}
        record.setdefault("scope", {})
        # Stamped here, from who invokes the grant - never trusted from the request: the
        # identifier is the event's decided_by, so a reader can hold them equal.
        record["approved_by"] = {"identifier": decided_by, "mode": "human"}
        record["created_at"] = _stamp(moment)
        found = _schema_problems(record)
        found += model.exception_problems(record, knowledge.lessons, knowledge.checks,
                                          moment, run_facets=facets, vocabulary=vocabulary)
        found += _run_problems(record, knowledge, facets, contract)
        if found:
            problems += [f"exception {index + 1} ({record.get('rule_id')}): {p}"
                         for p in dict.fromkeys(found)]
        else:
            records.append({"exception": record, "approver": _approver(name)})
    if problems:
        raise ExceptionRefused("; ".join(problems))
    if not records:
        raise ExceptionRefused("no exception was given")
    return records


# --------------------------------------------------------------------------- reading


def _corroborated(events, index, nonce):
    """The event at `index` is part of an engine-recorded resume: every event after it up
    to WORKFLOW_RESUMED carries the same nonce, and that resume does too."""
    if not isinstance(nonce, str) or not nonce:
        return False
    for event in events[index + 1:]:
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if event.get("event") == RESUMED_EVENT:
            return data.get("resume_nonce") == nonce
        if data.get("resume_nonce") != nonce:
            return False
    return False


def granted(events):
    """The exception records a person's resume recorded on the run, oldest first. An event a
    step's process tree wrote, one no engine-recorded resume corroborates (a line appended
    to events.jsonl), or one whose record names another approver than the event's
    decided_by is no one's act and is not read."""
    events = [e for e in events or () if isinstance(e, dict)]
    out = []
    for index, event in enumerate(events):
        if event.get("event") != EVENT:
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if data.get("decided_by") in (None, "automation"):
            continue
        if not _corroborated(events, index, data.get("resume_nonce")):
            continue
        record = data.get("exception")
        approved = record.get("approved_by") if isinstance(record, dict) else None
        if (isinstance(approved, dict) and approved.get("identifier") == data.get("decided_by")
                and approved.get("mode") == "human"):
            out.append(dict(record))
    return out


def from_config(config):
    """[{"exception", "problems"}] for every exception a configuration names
    (factory.knowledge.exceptions): reported, never honoured - an exception is a person's
    act on one run."""
    section = (config or {}).get(CONFIG_SECTION) if isinstance(config, dict) else None
    listed = section.get(CONFIG_KEY) if isinstance(section, dict) else None
    if listed in (None, [], {}):
        return []
    listed = listed if isinstance(listed, list) else [listed]
    return [{"exception": entry if isinstance(entry, dict) else {"value": entry},
             "problems": ["granted by configuration (factory.knowledge.exceptions): an "
                          "exception is a person's act on one run (wgf resume --except), "
                          "never configuration - ignored"]}
            for entry in listed]
