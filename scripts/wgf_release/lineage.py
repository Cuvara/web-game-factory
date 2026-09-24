"""May this run release at all? The evidence preconditions, read from the run's artifacts.

A draft release is only prepared from:

  * a qa-report that PASSES, from the newest verification in the run - it pins, by content
    hash, the newest verification-report, and the newest prototype-report and sdk-report
    the run holds; a report pinning older ones predates work that came after it;
  * a verification-report whose verdict is PASS and whose evidence is PASS or PASS_MOCK
    (PASS_MOCK is carried forward as such, never upgraded);
  * one commit: the qa-report's, the verification-report's, the sdk-report's and the
    prototype-report's (as far as the run holds them), and - checked with the checkout -
    the repository's HEAD;
  * a verification of a clean tree: a verified working tree with uncommitted changes is not
    reproducible from any commit.

Each failed precondition is a Refusal. `failed` ones are facts about the evidence that no
retry changes (FAILED, not retryable); `blocked` ones need a person to do something first -
run verify, commit, clean the checkout (BLOCKED).
"""

from dataclasses import dataclass

from wgf_verification.checks.platform import same_commit

__all__ = ["Refusal", "FAILED", "BLOCKED", "evidence_refusals", "commit_lineage",
           "ACCEPTED_EVIDENCE"]

FAILED, BLOCKED = "failed", "blocked"
ACCEPTED_EVIDENCE = ("PASS", "PASS_MOCK")


@dataclass
class Refusal:
    kind: str       # failed | blocked
    code: str       # stable, kebab-case: what tests and people grep for
    message: str

    def to_dict(self):
        return {"kind": self.kind, "code": self.code, "message": self.message}


def _pins(artifact):
    return {p.get("artifact_type"): p.get("content_hash")
            for p in ((artifact or {}).get("provenance") or {}).get("inputs") or []}


def commit_lineage(loaded):
    """[(source, commit or None)] for every artifact in the run that names a build commit."""
    out = []
    qa = loaded.get("qa-report")
    if qa is not None:
        out.append(("qa-report", (qa.get("build_ref") or {}).get("commit_sha")))
    vr = loaded.get("verification-report")
    if vr is not None:
        out.append(("verification-report", (vr.get("commit") or {}).get("sha")))
    for artifact_type in ("sdk-report", "prototype-report"):
        content = loaded.get(artifact_type)
        if content is not None:
            out.append((artifact_type, (content.get("build_ref") or {}).get("commit_sha")))
    return out


def evidence_refusals(refs, loaded, run_id):
    """Every precondition on the run's evidence that does not hold. `refs` are the newest
    ArtifactRefs per type, `loaded` their contents."""
    out = []
    qa, vr = loaded.get("qa-report"), loaded.get("verification-report")
    if qa is None:
        out.append(Refusal(BLOCKED, "no-qa-report",
                           "no qa-report in this run: verification has not run, so there is "
                           "nothing to release from. Run verify first."))
    if vr is None:
        out.append(Refusal(BLOCKED, "no-verification-report",
                           "no verification-report in this run: the evidence behind a "
                           "qa-report is required to release from it. Run verify first."))
    if qa is None or vr is None:
        return out

    if qa.get("verdict") != "pass":
        defects = [d.get("id") for d in qa.get("blocking_defects") or []]
        out.append(Refusal(FAILED, "qa-not-passed",
                           f"the newest qa-report's verdict is {qa.get('verdict')!r}"
                           + (f" ({len(defects)} blocking defect(s): {', '.join(defects[:8])})"
                              if defects else "")
                           + ". A release is prepared only from a passing verification."))
    if vr.get("verdict") != "PASS":
        out.append(Refusal(FAILED, "verification-not-passed",
                           f"the newest verification-report's verdict is {vr.get('verdict')!r}"
                           f" (failed: {', '.join(vr.get('failed_checks') or []) or 'none'}; "
                           f"blocked: {', '.join(vr.get('blocked_checks') or []) or 'none'})."))
    strength = vr.get("evidence_status")
    if strength is None or qa.get("evidence_status") is None:
        out.append(Refusal(FAILED, "evidence-status-missing",
                           "the verification predates evidence statuses (schema 1.0.x), so "
                           "whether it passed on mocked evidence cannot be told. Re-run verify."))
    elif strength not in ACCEPTED_EVIDENCE or qa["evidence_status"] not in ACCEPTED_EVIDENCE:
        out.append(Refusal(FAILED, "evidence-too-weak",
                           f"the verification's evidence is {strength} (qa-report: "
                           f"{qa['evidence_status']}); a draft needs PASS or PASS_MOCK."))

    # Staleness: the qa-report must be the one computed from the newest verification, and
    # that verification must have consumed the newest development and SDK reports.
    pins = _pins(qa)
    vr_ref = refs.get("verification-report")
    if vr_ref is not None and pins.get("verification-report") != vr_ref.content_hash:
        out.append(Refusal(FAILED, "stale-qa-report",
                           "the newest qa-report was not computed from the newest "
                           "verification-report (it pins "
                           f"{pins.get('verification-report') or 'none'}, the run's newest is "
                           f"{vr_ref.content_hash}). Re-run verify."))
    for artifact_type in ("prototype-report", "sdk-report"):
        ref = refs.get(artifact_type)
        if ref is None:
            continue
        if pins.get(artifact_type) != ref.content_hash:
            out.append(Refusal(FAILED, "stale-qa-report",
                               f"the qa-report was verified against "
                               f"{'no ' + artifact_type if not pins.get(artifact_type) else 'an older ' + artifact_type}"
                               f"; the run has a newer one ({ref.content_hash}), so the "
                               "verification predates later work. Re-run verify."))
    workflow = qa.get("workflow") or {}
    if workflow.get("run_id") and run_id and workflow["run_id"] != run_id:
        out.append(Refusal(FAILED, "foreign-qa-report",
                           f"the qa-report was produced by run {workflow['run_id']}, not this "
                           f"run ({run_id})."))

    # One commit throughout.
    lineage = commit_lineage(loaded)
    missing = [source for source, sha in lineage if not sha or sha == "unknown"]
    if missing:
        out.append(Refusal(FAILED, "commit-unknown",
                           "no build commit recorded in: " + ", ".join(missing)))
    named = [(s, sha) for s, sha in lineage if sha and sha != "unknown"]
    if named and any(not same_commit(sha, named[0][1]) for _, sha in named):
        out.append(Refusal(FAILED, "commit-lineage-mismatch",
                           "the evidence describes different commits: "
                           + ", ".join(f"{s}={sha[:12]}" for s, sha in named)))
    if (vr.get("commit") or {}).get("dirty"):
        out.append(Refusal(BLOCKED, "verified-dirty-tree",
                           "the verification ran on a working tree with uncommitted changes, "
                           "which no commit reproduces. Commit (or discard) them and re-run "
                           "verify."))
    if (vr.get("build_artifact") or {}).get("status") != "built" \
            or not (vr.get("build_artifact") or {}).get("content_hash"):
        out.append(Refusal(FAILED, "no-verified-bundle",
                           "the verification-report records no built bundle to package."))
    return out
