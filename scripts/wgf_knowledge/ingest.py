"""Lesson candidates from a run, into the project's candidate store (`wgf knowledge ingest`).

A run's producers report systemic issues as `lesson_candidates`
(core/artifacts/shared/quality-finding.schema.json#/$defs/lesson_candidate): the specialist
visits (prototype-report `specialist.lesson_candidates`), carried forward by triage
(triage-report) and surfaced at G4 (quality-report), and the reviewer (review-report 1.4.0).
They die with the run store (`.factory/`, git-ignored) unless something collects them. This
module does: the structured extraction - symptom -> root cause -> systemic? -> candidate ->
enforcement proposal - into `workspace/lessons/candidates.yaml`, de-duplicated, with the
provenance of every report each was seen in (run, artifact, version, the report's digest,
the build commit, the reporter).

    extract(state, read_artifact)        -> ([observation], [problem])
    ingest(store_doc, observations, lessons, checks, now) -> (store_doc, summary)
    load_store(path) / dump_store(doc) / write_store(path, doc)

Rules:

* Every candidate is checked against `$defs/lesson_candidate`, and must state its root cause
  (`summary` and `root_cause` non-empty): a symptom with no cause is not a lesson. One that
  fails is a problem, and ingestion writes nothing.
* De-duplication, in order: a candidate whose `proposed_check` already holds an active or
  validated lesson is a REGRESSION observation of that lesson (`regressions`), not a new
  candidate; otherwise one whose key - the normalized summary and the proposed check -
  matches a stored candidate adds a source to it; otherwise it is a new candidate `C-<n>`.
  A candidate whose proposed check a candidate or gap lesson already names is stored with
  `duplicate_of` that lesson. The same report ingested twice changes nothing.
* `basis`: a source is `measured` when it names the quality finding it was working (a gate's
  check failed on a build); a review-report's candidate is a judgment and always
  `subjective`. A candidate is measured once any source is. Subjective evidence never
  becomes a blocking or required rule by itself (promote.py).
* Append-only. Nothing here edits `core/`; a person promotes a candidate in a pull request
  (`wgf knowledge promote`), or rejects it (`state: rejected`).

The store is YAML, written as one JSON flow mapping per entry (JSON is YAML; the Factory's
YAML reader loads it, and a diff shows one line per candidate). Standard library only.
"""

import datetime
import json
import os
import re

CANDIDATES_FILE = "workspace/lessons/candidates.yaml"
STORE_VERSION = "1.0.0"

# Where each producer reports its lesson candidates: artifact type -> path into the report.
SOURCES = {
    "prototype-report": ("specialist", "lesson_candidates"),
    "triage-report": ("lesson_candidates",),
    "quality-report": ("lesson_candidates",),
    "review-report": ("lesson_candidates",),
}
# A reviewer's candidate is a judgment about code, never a measurement of a build.
SUBJECTIVE = ("review-report",)
# The producers whose `findings` are measurements of a build: a candidate's `finding` must be
# one of theirs, on the same build, for its evidence to count as measured.
MEASURING = ("quality-report", "triage-report")
SCHEMA = "core/artifacts/shared/quality-finding.schema.json"
ACTIVE = ("active", "validated")

HEADER = """\
# Lesson candidates: what runs observed, collected by `wgf knowledge ingest <run-id>`.
#
# Instance data, append-only (docs/knowledge-enforcement.md). Each entry is a lesson
# candidate a run's producers reported (prototype-report specialist.lesson_candidates,
# triage-report, quality-report, review-report lesson_candidates), checked against
# core/artifacts/shared/quality-finding.schema.json#/$defs/lesson_candidate, de-duplicated by
# its normalized summary and proposed check, with every report it was seen in (`sources`:
# run, artifact, version, report digest, build commit, reporter). Shape:
# quality-finding.schema.json#/$defs/candidate_record.
#
# `regressions` are candidates whose proposed check already holds an active lesson: a
# regression observation of that lesson, not a new one.
#
# Nothing here is a rule. A person promotes a candidate - `wgf knowledge promote C-<n>` drafts
# the lessons.yaml entry, the evidence.yaml entry and the test stubs as a patch for a pull
# request - or rejects it (`wgf knowledge reject C-<n> --reason TEXT`). A candidate whose
# evidence is only subjective (a review's judgment) is never drafted blocking or required.
#
# One JSON mapping per entry (JSON is YAML). Written by scripts/wgf_knowledge/ingest.py;
# edit by hand only to correct a mistake, never to delete evidence.
"""


class IngestError(Exception):
    """The run store cannot be read as a run: truncated JSON, wrong types, a missing run."""


# --------------------------------------------------------------------------- the store


def empty_store():
    return {"version": STORE_VERSION, "candidates": [], "regressions": []}


def load_store(path):
    """The candidate store at `path`, or an empty one when the file does not exist. Raises
    IngestError for a file that is not a store."""
    if not os.path.isfile(path):
        return empty_store()
    from wgflib.yamllite import load
    try:
        with open(path, encoding="utf-8") as handle:
            doc = load(handle.read())
    except (OSError, ValueError) as exc:
        raise IngestError(f"{path} cannot be read ({exc})")
    doc = doc if doc is not None else empty_store()
    if not isinstance(doc, dict) or not isinstance(doc.get("candidates") or [], list) \
            or not isinstance(doc.get("regressions") or [], list):
        raise IngestError(f"{path} is not a candidate store (candidates, regressions lists)")
    doc.setdefault("version", STORE_VERSION)
    doc["candidates"] = list(doc.get("candidates") or [])
    doc["regressions"] = list(doc.get("regressions") or [])
    return doc


def _line(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def dump_store(doc):
    """The store as text: the header, then one JSON flow mapping per entry."""
    parts = [HEADER, f"version: {doc.get('version') or STORE_VERSION}\n"]
    for key in ("candidates", "regressions"):
        entries = doc.get(key) or []
        if not entries:
            parts.append(f"{key}: []\n")
            continue
        parts.append(f"{key}:\n")
        parts += [f"  - {_line(entry)}\n" for entry in entries]
    text = "".join(parts)
    from wgflib.yamllite import load
    if load(text) != {"version": doc.get("version") or STORE_VERSION,
                      "candidates": list(doc.get("candidates") or []),
                      "regressions": list(doc.get("regressions") or [])}:
        raise IngestError("the candidate store does not read back as written")
    return text


def write_store(path, doc):
    text = dump_store(doc).encode("utf-8")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(text)
    os.replace(temporary, path)


def record_problems(record):
    """[problem] of one stored candidate against `$defs/candidate_record`."""
    return [f"{e.pointer or '/'}: {e.message}"
            for e in _validator("candidate_record").iter_errors(record)]


def store_problems(doc):
    """[problem] for each entry of a store against its record shapes."""
    validator = _validator("candidate_record")
    problems = []
    for index, entry in enumerate(doc.get("candidates") or []):
        problems += [f"candidates[{index}] {e.pointer or '/'}: {e.message}"
                     for e in validator.iter_errors(entry)]
    source = _validator("candidate_source")
    for index, entry in enumerate(doc.get("regressions") or []):
        if not isinstance(entry, dict) or not entry.get("lesson") or not entry.get("source"):
            problems.append(f"regressions[{index}]: needs a lesson and a source")
            continue
        problems += [f"regressions[{index}] {e.pointer or '/'}: {e.message}"
                     for e in source.iter_errors(entry["source"])]
    return problems


# --------------------------------------------------------------------------- extraction


_VALIDATORS = {}


def _validator(definition):
    if definition not in _VALIDATORS:
        from wgflib import jsonschema_lite, paths
        with open(os.path.join(paths.ROOT, *SCHEMA.split("/")), encoding="utf-8") as handle:
            schema = json.load(handle)
        registry = jsonschema_lite.Registry()
        registry.add(schema, schema["$id"])
        wrapper = {"$ref": f"{schema['$id']}#/$defs/{definition}"}
        _VALIDATORS[definition] = jsonschema_lite.Validator(wrapper, registry=registry)
    return _VALIDATORS[definition]


def candidate_problems(candidate):
    """[problem] of one reported candidate: its schema, and a stated root cause."""
    if not isinstance(candidate, dict):
        return [f"is a {type(candidate).__name__}, not a lesson candidate"]
    problems = [f"{e.pointer or '/'}: {e.message}"
                for e in _validator("lesson_candidate").iter_errors(candidate)]
    for key in ("summary", "root_cause"):
        if not str(candidate.get(key) or "").strip():
            problems.append(f"has no {key} - a candidate states the generalized lesson and "
                            "why the Factory let it through (symptom -> root cause)")
    return problems


def _get(doc, path):
    for key in path:
        if not isinstance(doc, dict):
            return None
        doc = doc.get(key)
    return doc


def _commit(kind, doc):
    if kind == "quality-report":
        build = doc.get("build") if isinstance(doc.get("build"), dict) else {}
        return build.get("commit") or build.get("development_commit")
    if kind == "prototype-report":
        return _get(doc, ("build_ref", "commit_sha"))
    if kind == "review-report":
        return doc.get("reviewed_commit")
    return doc.get("commit")


def _refs(state):
    """Every ref of a type that reports candidates, every version, in production order."""
    found = []
    for versions in (state.artifacts or {}).values():
        for ref in versions or ():
            if getattr(ref, "type", None) in SOURCES:
                found.append(ref)
    return sorted(found, key=lambda r: (r.order(), r.id, r.version))


def _measured_findings(docs):
    """{finding id: {"commits": {build commits}, "guarded_by": {lesson ids}, "reports":
    [(ref or None, report commits)]}} of the findings
    the run's measuring producers recorded (quality-report and triage-report `findings`): what
    a candidate's `finding` must resolve to before its evidence counts as measured."""
    out = {}
    for item in docs:
        ref, kind, doc = item if len(item) == 3 else (None,) + tuple(item)
        if kind not in MEASURING:
            continue
        report_commits = {c for c in (_commit(kind, doc),
                                      _get(doc, ("build", "development_commit"))) if c}
        for finding in doc.get("findings") or ():
            if not isinstance(finding, dict) or not finding.get("id"):
                continue
            entry = out.setdefault(str(finding["id"]), {"commits": set(), "guarded_by": set(),
                                                        "reports": []})
            own = _get(finding, ("build", "commit"))
            commits = ({own} if own else set()) | report_commits
            entry["commits"] |= commits
            entry["reports"].append((ref, commits))
            entry["guarded_by"] |= {g.get("lesson") for g in finding.get("guarded_by") or ()
                                    if isinstance(g, dict) and g.get("lesson")}
    return out


def extract(state, read_artifact):
    """([observation], [problem]) of every lesson candidate the run's reports hold.

    `read_artifact(ref)` returns the report (it raises for a missing or changed file, which
    is the caller's IngestError). An observation is {"candidate": the reported candidate,
    "source": candidate_source, "guarded_by": [lesson ids of the finding it resolved to]}.
    Raises IngestError for a report that is not shaped as one (not an object, candidates not
    a list).

    A source is `measured` only when the candidate's `finding` resolves to a finding a
    measuring producer of this run (quality-report, triage-report) recorded on the same build
    commit as the report the candidate came from; a finding id nothing recorded, or one on
    another build, leaves it `subjective`. A reviewer's candidate is always subjective."""
    docs = []
    for ref in _refs(state):
        try:
            doc = read_artifact(ref)
        except Exception as exc:  # noqa: BLE001 - the store's own errors, named
            raise IngestError(f"{ref.id} v{ref.version} cannot be read ({exc})")
        if not isinstance(doc, dict):
            raise IngestError(f"{ref.id} v{ref.version} is a {type(doc).__name__}, not a "
                              f"{ref.type}")
        docs.append((ref, doc))
    measured = _measured_findings([(ref, ref.type, doc) for ref, doc in docs])
    observations, problems = [], []
    for ref, doc in docs:
        reported = _get(doc, SOURCES[ref.type])
        if reported is None:
            continue
        if not isinstance(reported, list):
            raise IngestError(f"{ref.id} v{ref.version}: {'.'.join(SOURCES[ref.type])} is a "
                              f"{type(reported).__name__}, not a list")
        provenance = doc.get("provenance") if isinstance(doc.get("provenance"), dict) else {}
        commit = _commit(ref.type, doc)
        for index, candidate in enumerate(reported):
            at = f"{state.run_id} {ref.id} v{ref.version} {'.'.join(SOURCES[ref.type])}[{index}]"
            found = candidate_problems(candidate)
            if found:
                problems += [f"{at}: {p}" for p in found]
                continue
            finding = candidate.get("finding")
            resolved = measured.get(str(finding)) if finding else None
            is_measured = (ref.type not in SUBJECTIVE and resolved is not None
                           and commit is not None and commit in resolved["commits"])
            proof = next((r for r, commits in resolved["reports"] if commit in commits),
                         None) if is_measured else None
            observations.append({"candidate": candidate, "source": {
                "run": state.run_id, "artifact_id": ref.id, "artifact_type": ref.type,
                "version": ref.version, "report_hash": ref.checksum,
                "content_hash": provenance.get("content_hash") or ref.content_hash,
                "commit": commit, "role": candidate.get("role"),
                "finding": finding,
                "basis": "measured" if is_measured else "subjective",
                "resolved_in": None if proof is None else {
                    "artifact_id": proof.id, "artifact_type": proof.type,
                    "version": proof.version, "report_hash": proof.checksum},
                "evidence_refs": list(candidate.get("evidence_refs") or []),
                "date": provenance.get("produced_at") or ref.created_at},
                "guarded_by": sorted(resolved["guarded_by"]) if is_measured else []})
    return observations, problems


def basis_of(record, verify=None):
    """A stored candidate's basis, derived from its sources - never read from the record's
    own `basis`, which a hand edit can change.

    Without `verify`, what the sources claim (a measured source from a measuring report, not
    a review, naming a finding and the report it resolved in) - the store's own bookkeeping.
    With `verify(source, record) -> bool` (promote: `verifier(store)`), only a source
    re-verified against the run store AS THIS CANDIDATE'S counts - a measured source copied
    from another candidate does not; anything that cannot be re-verified is subjective."""
    for source in (record or {}).get("sources") or ():
        if not (isinstance(source, dict) and source.get("basis") == "measured"
                and source.get("artifact_type") in SOURCES
                and source.get("artifact_type") not in SUBJECTIVE and source.get("finding")
                and isinstance(source.get("resolved_in"), dict)):
            continue
        if verify is None or verify(source, record):
            return "measured"
    return "subjective"


def verify_source(source, state, read_artifact, record):
    """True when the run store still proves a measured source of `record`: the report the
    candidate came from is the run's, with the digest the source recorded, and still holds
    THIS candidate - one whose key (normalized summary and proposed check) is the record's,
    computed from the record's own text, never its stored `key` - carrying the finding; the
    measuring report it resolved in is the run's, with its recorded digest; and the finding
    is recorded there on the same build commit as the candidate's report."""
    def ref_of(artifact_id, version, digest):
        for ref in (state.artifacts or {}).get(artifact_id) or ():
            if ref.version == version and ref.checksum == digest:
                return ref
        return None

    proof = source.get("resolved_in") or {}
    origin = ref_of(source.get("artifact_id"), source.get("version"), source.get("report_hash"))
    measuring = ref_of(proof.get("artifact_id"), proof.get("version"), proof.get("report_hash"))
    if state.run_id != source.get("run") or origin is None or measuring is None \
            or origin.type in SUBJECTIVE or measuring.type not in MEASURING:
        return False
    try:
        report, findings_doc = read_artifact(origin), read_artifact(measuring)
    except Exception:  # noqa: BLE001 - a report that cannot be read proves nothing
        return False
    if not isinstance(report, dict) or not isinstance(findings_doc, dict):
        return False
    commit = _commit(origin.type, report)
    reported = _get(report, SOURCES[origin.type]) or []
    own_key = key_of(record or {})
    if commit is None or commit != source.get("commit") or not record or not any(
            isinstance(c, dict) and c.get("finding") == source.get("finding")
            and key_of(c) == own_key for c in reported):
        return False
    entry = _measured_findings([(measuring, measuring.type, findings_doc)]).get(
        str(source.get("finding")))
    return entry is not None and commit in entry["commits"]


def verifier(store):
    """verify(source) over a RunStore: loads each run once; a run that is gone, or any
    store error, verifies nothing."""
    cache = {}

    def verify(source, record):
        run = source.get("run")
        if run not in cache:
            try:
                cache[run] = store.load(run)
            except Exception:  # noqa: BLE001 - a run store that is gone proves nothing
                cache[run] = None
        state = cache[run]
        if state is None:
            return False
        return verify_source(source, state,
                             lambda ref: store.read_artifact(state.run_id, ref), record)
    return verify


# --------------------------------------------------------------------------- de-duplication


def normalize(text):
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def key_of(candidate):
    return f"{normalize(candidate.get('summary'))}|{str(candidate.get('proposed_check') or '').strip()}"


def _same_source(a, b):
    return all(a.get(k) == b.get(k) for k in ("run", "artifact_id", "version", "report_hash"))


def _lesson_index(lessons):
    """({check: [active lesson]}, {check: candidate-or-gap lesson id})."""
    active, pending = {}, {}
    for lesson in (lessons or {}).get("lessons") or ():
        if not isinstance(lesson, dict) or not lesson.get("id"):
            continue
        for check in lesson.get("checks") or ():
            if lesson.get("lifecycle") in ACTIVE:
                active.setdefault(check, []).append(lesson)
            elif lesson.get("lifecycle") == "candidate":
                pending.setdefault(check, lesson["id"])
    return active, pending


_STOP = frozenset("a an the of to in on and or is was it its by for not no with as at be "
                  "that this from every any".split())
SIMILAR = 0.5


def _words(*texts):
    return {w for text in texts for w in normalize(text).split() if w not in _STOP}


def similarity(candidate, lesson):
    """The share of the candidate's words (summary, symptom, root cause) the lesson's text
    (title, problem, root cause, lesson) also uses."""
    mine = _words(candidate.get("summary"), candidate.get("symptom"), candidate.get("root_cause"))
    theirs = _words(lesson.get("title"), lesson.get("problem"), lesson.get("root_cause"),
                    lesson.get("lesson"))
    return len(mine & theirs) / len(mine) if mine else 0.0


def _regression_of(candidate, lessons, guarded_by):
    """The active lesson this candidate re-observes, or None: the finding it resolved to is
    guarded by that lesson, or it states that lesson's problem (SIMILAR of its words). A
    candidate that only shares the check is a new observation, not a regression."""
    for lesson in lessons:
        if lesson["id"] in (guarded_by or ()) or similarity(candidate, lesson) >= SIMILAR:
            return lesson["id"]
    return None


def _next_id(candidates):
    numbers = [int(c["id"][2:]) for c in candidates
               if isinstance(c, dict) and re.match(r"^C-[0-9]+$", str(c.get("id") or ""))]
    return f"C-{max(numbers or [0]) + 1}"


def now_iso(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ingest(doc, observations, lessons, now=None):
    """(store, summary): the observations merged into a copy of the store `doc`.

    summary: {"added": [C ids], "merged": [C ids], "regressions": [lesson ids],
    "unchanged": n}."""
    doc = json.loads(json.dumps(doc))
    stamp = now_iso(now)
    active, pending = _lesson_index(lessons)
    summary = {"added": [], "merged": [], "regressions": [], "unchanged": 0}
    by_key = {c.get("key"): c for c in doc["candidates"] if isinstance(c, dict)}
    for observation in observations:
        candidate, source = observation["candidate"], dict(observation["source"])
        source["ingested_at"] = stamp
        check = str(candidate.get("proposed_check") or "").strip() or None
        key = key_of(candidate)
        stored = by_key.get(key)
        # A report already stored as this candidate's source is the same observation - also
        # once the candidate was promoted and an active lesson now holds its check.
        if stored is not None and any(_same_source(s, source)
                                      for s in stored.get("sources") or ()):
            summary["unchanged"] += 1
            continue
        lesson = _regression_of(candidate, active.get(check) or (),
                                observation.get("guarded_by")) if check else None
        if lesson is not None:
            seen = any(r.get("lesson") == lesson and r.get("key") == key
                       and _same_source(r.get("source") or {}, source)
                       for r in doc["regressions"])
            if seen:
                summary["unchanged"] += 1
                continue
            doc["regressions"].append({"lesson": lesson, "check": check, "key": key,
                                       "summary": candidate["summary"], "source": source})
            summary["regressions"].append(lesson)
            continue
        if stored is not None:
            stored["sources"].append(source)
            stored["basis"] = basis_of(stored)
            cause = " ".join(str(candidate["root_cause"]).split())
            causes = [stored.get("root_cause")] + list(stored.get("other_root_causes") or [])
            if normalize(cause) not in {normalize(c) for c in causes}:
                # Another reporter's cause for the same lesson: kept, never dropped.
                stored["other_root_causes"] = list(stored.get("other_root_causes") or []) + [cause]
            for field in ("symptom", "systemic", "proposed_level", "proposed_scope"):
                if stored.get(field) is None and candidate.get(field) is not None:
                    stored[field] = candidate[field]
            summary["merged"].append(stored["id"])
            continue
        related = [l["id"] for l in active.get(check) or ()] if check else []
        record = {"id": _next_id(doc["candidates"]), "state": "open", "key": key,
                  "summary": candidate["summary"], "symptom": candidate.get("symptom"),
                  "root_cause": candidate["root_cause"],
                  "systemic": candidate.get("systemic"), "proposed_check": check,
                  "proposed_level": candidate.get("proposed_level"),
                  "proposed_scope": candidate.get("proposed_scope"),
                  "basis": source["basis"], "duplicate_of": pending.get(check) if check else None,
                  "related_lessons": related, "rejected": None, "sources": [source]}
        record["basis"] = basis_of(record)
        doc["candidates"].append(record)
        by_key[key] = record
        summary["added"].append(record["id"])
    return doc, summary


def reject(doc, candidate_id, reason, by, now=None):
    """A copy of the store with one candidate rejected by a person. Raises KeyError for an
    unknown id, ValueError for a reason under 20 characters."""
    if len(str(reason or "").strip()) < 20:
        raise ValueError("a rejection says why, in at least 20 characters")
    doc = json.loads(json.dumps(doc))
    for record in doc["candidates"]:
        if record.get("id") == candidate_id:
            record["state"] = "rejected"
            record["rejected"] = {"by": by, "at": now_iso(now), "reason": str(reason).strip()}
            return doc
    raise KeyError(candidate_id)


def promoted(evidence):
    """{candidate id: lesson id} from the instance evidence (`candidate` of a lesson entry)."""
    out = {}
    for lesson_id, entry in (((evidence or {}).get("lessons")) or {}).items():
        if isinstance(entry, dict) and entry.get("candidate"):
            out[str(entry["candidate"])] = lesson_id
    return out
