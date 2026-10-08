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
a record - the grant stamps `approved_by` itself: `identifier` is the person who runs the
command (`--approved-by NAME`, else the login name, named explicitly - never a placeholder
such as `human` or `person`, never a value read from an exception file) and `mode` human -
and never past its expiry.

The event's data is {"exception": <record>}; the engine adds `decided_by` (`human`: who the
run records deciding), `decided_at` and `resume_nonce`, and keeps the nonce it issued in
state.json (`resume_nonces`) with the digest of the operator events that resume recorded.
A reader honours it only when `decided_by` is `human`, the record's mode is human and names
a person, the resume with the same nonce corroborates it, that nonce is one the engine
issued, exactly one WORKFLOW_RESUMED carries it, and the events carrying it still digest to
what state.json kept (granted(events, issued_nonces(run_dir))). Without a run directory or
state.json nothing is honoured (fail closed).

`--approved-by` (or the login name) is the person's own claim of who they are, recorded as
given: the Factory checks that it names someone - not a role, a program or a placeholder -
and never that it is that person. Identity is the installation's to establish.

    approver(name=None)             the person granting: `name`, else the login name;
                                    raises ExceptionRefused for no name or a placeholder
    request(rule_ids, reason, expires, scope_pairs, approver)   partial records from the CLI
    requests_from_file(path, approver)                          partial records from a file
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
import re

from . import model

__all__ = ["EVENT", "ExceptionRefused", "approver", "approver_problem", "request",
           "requests_from_file", "grant", "recorded", "granted", "issued_nonces",
           "from_config",
           "SCOPE_KEYS"]

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


# A person's handle: what `approved_by.identifier` must be. Never a placeholder that names a
# kind of decider rather than someone.
_HANDLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@ '-]{0,63}")
# Words that name a kind of decider, a role or a program - never one person. A handle is
# refused when, articles, punctuation and numbers aside, it is made only of these: "the
# reviewer", "release team", "claude code". A name with a person's word in it passes -
# "alice the reviewer" names alice - because the check refuses placeholders, it does not
# verify identity: --approved-by is the person's own claim.
NOT_A_PERSON = frozenset((
    "human", "humans", "person", "people", "someone", "somebody", "anyone", "everyone",
    "nobody", "none", "unknown", "anonymous", "n/a", "na", "user", "users", "operator",
    "owner", "me", "myself", "self", "root", "admin", "administrator", "system", "sysadmin",
    "automation", "automated", "auto", "agent", "agents", "bot", "bots", "robot", "ai",
    "assistant", "llm", "model", "script", "ci", "pipeline", "runner", "github", "actions",
    "workflow", "factory", "wgf", "step", "developer", "reviewer", "tester", "qa",
    "claude", "anthropic", "codex", "openai", "gpt", "chatgpt", "copilot", "gemini", "bard",
    "llama", "mistral", "cursor", "code", "team", "cli", "tool", "service", "staff",
    "crew", "group", "department", "approver", "maintainer", "manager", "lead", "ops",
    "devops", "release", "publisher", "studio"))
_ARTICLES = frozenset(("the", "a", "an", "my", "our", "your", "this", "that"))


def approver_problem(name):
    """Why `name` does not name the person who granted an exception, or None."""
    if not isinstance(name, str) or not name.strip():
        return "the exception names no approver: give --approved-by NAME"
    name = name.strip()
    if not _HANDLE.fullmatch(name):
        return f"approver {name!r} is not a handle (letters, digits, . _ @ - ' and spaces)"
    words = [w for w in re.split(r"[\s._@'-]+", name.lower()) if w]
    words = [w for w in words if w not in _ARTICLES and not w.isdigit()]
    if not words or all(w in NOT_A_PERSON or w.rstrip("0123456789") in NOT_A_PERSON
                        for w in words):
        return (f"approver {name!r} names no one: give the person's own handle with "
                "--approved-by NAME")
    return None


def approver(name=None):
    """The person granting: `name` as given, else this host's login name - explicitly that
    person's, never a placeholder. Raises ExceptionRefused when there is none."""
    if not (isinstance(name, str) and name.strip()):
        try:
            name = getpass.getuser()
        except Exception:  # noqa: BLE001 - no login name on this host
            name = None
    why = approver_problem(name)
    if why:
        raise ExceptionRefused(why)
    return name.strip()


def request(rule_ids, reason, expires, scope_pairs=(), approver_name=None):
    """[partial record] for each rule id given on the command line, with the same reason,
    expiry and scope. `approved_by.mode` is not taken from here: grant() stamps it."""
    if not rule_ids:
        raise ExceptionRefused("--except names the rule (a lesson id) or a JSON file")
    expires_at = expiry(expires)
    scope = _scope(scope_pairs)
    who = approver(approver_name)
    return [{"rule_id": str(rule_id).strip(), "reason": reason, "scope": dict(scope),
             "expires_at": expires_at,
             "approved_by": {"identifier": who}}
            for rule_id in rule_ids]


def requests_from_file(path, approver_name=None):
    """[partial record] from a JSON file holding one knowledge-exception record or a list.
    Nothing in the file says who approved it: `approved_by` is the person running the
    command (`approver_name`, else the login name); `created_at` is stamped by grant()."""
    who = approver(approver_name)
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
        record["approved_by"] = {"identifier": who}
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
    """[{"exception": record}]: the operator events' data for the knowledge-exception
    records `requests` grant the run `state`, each stamped `approved_by` {identifier: the
    person the request names (request()/requests_from_file(): --approved-by or the login
    name, validated here again), mode: human} and `created_at` now. Raises ExceptionRefused
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
        name = name.strip() if isinstance(name, str) else name
        record = {key: partial[key] for key in ("rule_id", "reason", "scope", "expires_at")
                  if key in partial}
        record.setdefault("scope", {})
        # The person who ran the command, and a mode stamped here - never a mode from the
        # request. Validated again: a placeholder or no name is refused, never filled in.
        record["approved_by"] = {"identifier": name, "mode": "human"}
        record["created_at"] = _stamp(moment)
        found = [approver_problem(name)] if approver_problem(name) else []
        found += _schema_problems(record)
        found += model.exception_problems(record, knowledge.lessons, knowledge.checks,
                                          moment, run_facets=facets, vocabulary=vocabulary)
        found += _run_problems(record, knowledge, facets, contract)
        if found:
            problems += [f"exception {index + 1} ({record.get('rule_id')}): {p}"
                         for p in dict.fromkeys(found)]
        else:
            records.append({"exception": record})
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


STATE_FILE = "state.json"


def issued_nonces(run_dir):
    """{nonce: digest} the engine issued the run (state.json `resume_nonces`: each nonce
    with the digest of the operator events its resume recorded). Fails closed: no run
    directory, no state.json, or a state.json from before the digests (a list) gives
    nothing a grant could be checked by - {} or {nonce: None} - and every grant is
    refused."""
    if not run_dir:
        return {}
    try:
        with open(os.path.join(run_dir, STATE_FILE), encoding="utf-8") as handle:
            found = (json.load(handle) or {}).get("resume_nonces")
    except (OSError, ValueError, AttributeError):
        return {}
    if isinstance(found, dict):
        return {n: d for n, d in found.items() if isinstance(n, str) and n}
    return {n: None for n in found or () if isinstance(n, str) and n}


def _resume_problem(events, nonce, issued):
    """Why the operator events carrying `nonce` are not exactly what the engine recorded
    for that resume, or None: the nonce was never issued, it was issued before digests were
    kept, more than one WORKFLOW_RESUMED carries it (a copied nonce), or the events that
    carry it no longer digest to what state.json kept (a grant added, removed or edited)."""
    from wgflib.workflow.engine import operator_digest
    if nonce not in issued:
        return ("its resume nonce is not one the engine issued this run (state.json "
                "resume_nonces): a forged pair of lines")
    if issued[nonce] is None:
        return ("its resume nonce was issued before the engine kept the digest of what each "
                "resume recorded: it cannot be checked, so it is not honoured - grant it "
                "again")
    acts, resumes = [], 0
    for event in events:
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if data.get("resume_nonce") != nonce:
            continue
        if event.get("event") == RESUMED_EVENT:
            resumes += 1
        else:
            acts.append((event.get("event"), data))
    if resumes != 1:
        return (f"its resume nonce corroborates {resumes} WORKFLOW_RESUMED events: a nonce "
                "is used once, so one was copied")
    if operator_digest(acts) != issued[nonce]:
        return ("the events carrying its resume nonce are not the ones that resume recorded "
                "(their digest differs from state.json's): lines were added, removed or "
                "edited")
    return None


def recorded(events, issued=None):
    """[(record, why)] for every EVENT on the run, oldest first: `why` None for a person's
    act, else why it is not one - an event a step's process tree wrote (decided_by missing
    or `automation`), one no engine-recorded resume corroborates (a line appended to
    events.jsonl), or a record that is not a person's (mode not human, an approver that
    names no one). `issued`: issued_nonces(run_dir) - {nonce: digest}; None or {} refuses
    every grant (fail closed). An event is honoured only when its nonce was issued, one
    WORKFLOW_RESUMED carries it, and the operator events carrying it digest to what the
    engine kept: a made-up nonce, or a real one copied onto new lines, is a forgery. The
    one reader of the event: granted() keeps the first kind, and the quality gate lists
    the others refused
    (wgf_quality.compliance.run_exceptions)."""
    events = [e for e in events or () if isinstance(e, dict)]
    issued = issued if isinstance(issued, dict) else {}
    out = []
    for index, event in enumerate(events):
        if event.get("event") != EVENT:
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        record = data.get("exception") if isinstance(data.get("exception"), dict) else {}
        approved = record.get("approved_by") if isinstance(record.get("approved_by"),
                                                           dict) else {}
        who = data.get("decided_by")
        why = None
        if who != "human":
            why = f"the event was not recorded by a person (decided_by {who!r})"
        elif not _corroborated(events, index, data.get("resume_nonce")):
            why = "the event is not corroborated by the resume that recorded it"
        elif _resume_problem(events, data.get("resume_nonce"), issued):
            why = "the event is not the engine's record: " + _resume_problem(
                events, data.get("resume_nonce"), issued)
        elif approved.get("mode") != "human":
            why = f"the record's approver is not a person (mode {approved.get('mode')!r})"
        elif approver_problem(approved.get("identifier")):
            why = approver_problem(approved.get("identifier"))
        out.append((dict(record), why))
    return out


def granted(events, issued=None):
    """The exception records a person's resume recorded on the run, oldest first: those
    recorded() finds a person's act. Any other is no one's and is not read."""
    return [record for record, why in recorded(events, issued) if why is None]


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
