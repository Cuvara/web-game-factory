"""Run stores for the knowledge learning-loop tests: a run directory written the way the engine
writes one (state.json, artifacts/<id>/v<n>.json with their checksums), holding only the
reports a test names. Not a test module.

    store = make_store(tmp)
    run = add_run(store, "run-a", params={...})
    add_report(store, run, "quality-report", {...})
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from wgflib.workflow.model import ArtifactRef, RunState  # noqa: E402
from wgflib.workflow.store import RunStore  # noqa: E402

COMMIT = "a" * 40


def make_store(directory):
    return RunStore(directory, fsync=False)


def add_run(store, run_id, params=None, status="completed", created_at="2026-10-08T10:00:00Z"):
    state = RunState(run_id=run_id, workflow_id="new-game", workflow_version=17,
                     status=status, cursor=None, scope=[], params=dict(params or {}),
                     created_at=created_at, updated_at=created_at)
    store.create(state)
    return state


def add_report(store, state, kind, doc, artifact_id=None):
    artifact_id = artifact_id or kind
    versions = state.artifacts.setdefault(artifact_id, [])
    version = len(versions) + 1
    seq = sum(len(v) for v in state.artifacts.values()) + 1
    location, checksum = store.write_artifact(state.run_id, artifact_id, version, doc)
    ref = ArtifactRef(id=artifact_id, type=kind, version=version, location=location,
                      checksum=checksum, produced_by="test", seq=seq,
                      created_at=f"2026-10-08T10:{seq:02d}:00Z",
                      content_hash=((doc or {}).get("provenance") or {}).get("content_hash")
                      if isinstance(doc, dict) else None)
    versions.append(ref)
    store.save(state)
    return ref


def candidate(summary="Gates read uncaught exceptions only, never the console",
              root_cause="No gate reads the console during play", **extra):
    out = {"summary": summary, "root_cause": root_cause}
    out.update(extra)
    return out


def findings(ids, commit=COMMIT, guarded_by=()):
    """Measured findings, as quality-report and triage-report record them."""
    return [{"id": i, "build": {"commit": commit, "digest": None},
             "guarded_by": [{"lesson": l, "check": "x:y"} for l in guarded_by]} for i in ids]


def quality_report(candidates, commit=COMMIT, compliance=None, found=()):
    doc = {"findings": list(found),
           "provenance": {"artifact_id": "qr-1", "content_hash": "sha256:" + "b" * 64},
           "build": {"commit": commit, "development_commit": commit, "digest": None},
           "verdict": "PASS", "release_decision": "release",
           "lesson_candidates": list(candidates)}
    if compliance is not None:
        doc["compliance"] = compliance
    return doc


def triage_report(candidates, commit=COMMIT, found=()):
    return {"provenance": {"artifact_id": "tr-1"}, "commit": commit, "findings": list(found),
            "lesson_candidates": list(candidates)}


def prototype_report(candidates, commit=COMMIT, role="ui"):
    return {"provenance": {"artifact_id": "pr-1"},
            "build_ref": {"commit_sha": commit, "url": "http://localhost:4173"},
            "specialist": {"role": role, "lesson_candidates": list(candidates)}}


def review_report(candidates, commit=COMMIT):
    return {"provenance": {"artifact_id": "rr-1"}, "reviewed_commit": commit,
            "verdict": "approve", "lesson_candidates": list(candidates)}
