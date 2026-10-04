"""May this run release at all? The evidence preconditions, read from the run's artifacts.

A draft release is only prepared from:

  * a qa-report that PASSES, from the newest verification in the run - it pins, by content
    hash, the newest verification-report, and the newest prototype-report and sdk-report
    the run holds; a report pinning older ones predates work that came after it;
  * a verification-report whose verdict is PASS and whose evidence is PASS or PASS_MOCK
    (PASS_MOCK is carried forward as such, never upgraded);
  * one commit, by the lineage rule (wgf_verification/lineage.py, docs/core-contracts.md
    §5): the qa-report's, the verification-report's and the sdk-report's commit are one,
    and - checked with the checkout - the repository's HEAD; the prototype-report's commit
    is the one sdk built on; the commits between them are exactly this run's sdk commits;
  * a review: the newest review-report approved exactly the commit being shipped - the sdk
    commit, which the workflow's `sdk-review` reads - and pins the run's newest
    prototype-report and sdk-report. A skipped review (no reviewer configured) or none at
    all is `unreviewed`, refused unless factory.release.allow_unreviewed is true, and then
    carried into the manifest as UNREVIEWED - never as an approval;
  * every gate the step's `required_gates` names (default G4), passed in this run and not
    superseded by later work (`context.gates_passed`);
  * the production gates: the newest production-quality-report and visual-qa-report (the
    step's `required_reports`, default both) are PASS for the development commit the
    released sdk commit sits on - a build whose art or UI they did not pass is not released;
  * the quality gate: the newest quality-report PASSED exactly the build released - its
    commit and development commit - and pins the run's newest reports of it; a `development`
    decision (a run at quality tier mvp) is drafted and recorded as such
    (evidence.quality_report), never as a release;
  * a verification of a clean tree: a verified working tree with uncommitted changes is not
    reproducible from any commit.

Each failed precondition is a Refusal. `failed` ones are facts about the evidence that no
retry changes (FAILED, not retryable); `blocked` ones need a person to do something first -
run verify, commit, clean the checkout (BLOCKED).
"""

from dataclasses import dataclass

from wgf_verification.lineage import (CODE as LINEAGE, is_placeholder, lineage_problems,
                                     same_commit)

__all__ = ["Refusal", "FAILED", "BLOCKED", "evidence_refusals", "commit_lineage",
           "verified_commits", "checkout_lineage", "review_status", "gate_refusals",
           "shipped_commit", "ACCEPTED_EVIDENCE", "DEFAULT_REQUIRED_GATES", "UNREVIEWED",
           "REVIEW_MISMATCH", "DEFAULT_REQUIRED_REPORTS", "production_refusals",
           "developed_commit", "listing_refusals", "DEFAULT_REQUIRED_LISTING",
           "quality_refusals", "quality_evidence", "DEFAULT_REQUIRED_QUALITY"]

FAILED, BLOCKED = "failed", "blocked"
ACCEPTED_EVIDENCE = ("PASS", "PASS_MOCK")
UNREVIEWED = "unreviewed"
REVIEW_MISMATCH = "review-commit-mismatch"
# The kill gate: nothing ships before a person has judged the verified prototype. A workflow
# without a G4 checkpoint says so on its release step (`with: required_gates: []`).
DEFAULT_REQUIRED_GATES = ("G4",)
# The production gates: nothing ships whose art and UI they did not pass. A workflow without
# them says so on its release step (`with: required_reports: []`).
DEFAULT_REQUIRED_REPORTS = ("production-quality-report", "visual-qa-report")
# The store listing: a release ships only with the listing of its own build, validated. A
# workflow without the listing steps says so on its release step (`with: required_listing:
# false`).
DEFAULT_REQUIRED_LISTING = True
# The quality gate: a release ships only a build whose quality-report passed. A workflow
# without the quality-gate step says so on its release step (`with: required_quality: false`).
DEFAULT_REQUIRED_QUALITY = True
# The reports a quality-report must have scored for its verdict to be about the run's
# newest evidence (it pins them by content hash).
QUALITY_PINS = ("qa-report", "verification-report", "prototype-report", "sdk-report",
                "review-report", "playability-report", "production-quality-report",
                "visual-qa-report", "content-sufficiency-report")


def _short(sha):
    return (sha or "none")[:12]


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


def _build_commit(loaded, artifact_type):
    return ((loaded.get(artifact_type) or {}).get("build_ref") or {}).get("commit_sha")


def verified_commits(loaded):
    """[(source, commit)] for the artifacts that must all name the verified commit."""
    out = []
    qa = loaded.get("qa-report")
    if qa is not None:
        out.append(("qa-report", (qa.get("build_ref") or {}).get("commit_sha")))
    vr = loaded.get("verification-report")
    if vr is not None:
        out.append(("verification-report", (vr.get("commit") or {}).get("sha")))
    if loaded.get("sdk-report") is not None:
        out.append(("sdk-report", _build_commit(loaded, "sdk-report")))
    return out


def commit_lineage(loaded):
    """[(source, commit or None)] for every commit the run's evidence names, in pipeline
    order: what was verified, what sdk built on, and what develop committed."""
    out = verified_commits(loaded)
    sdk_ref = (loaded.get("sdk-report") or {}).get("build_ref") or {}
    if "base_commit_sha" in sdk_ref:
        out.append(("sdk-report.base", sdk_ref.get("base_commit_sha")))
    if loaded.get("prototype-report") is not None:
        out.append(("prototype-report", _build_commit(loaded, "prototype-report")))
    return out


def checkout_lineage(loaded, head, git, run_id):
    """Refusals for the lineage rule with the checkout: HEAD is the verified commit, and the
    commits between the prototype and the sdk commit are this run's sdk commits."""
    out = []
    for source, sha in verified_commits(loaded):
        if sha and not same_commit(sha, head):
            out.append(Refusal(FAILED, LINEAGE,
                               f"{source} describes {sha[:12]}, but the checkout's HEAD is "
                               f"{head[:12]}: the checkout moved after verification. Re-run "
                               "verify at HEAD."))
    if out:
        return out
    problems = lineage_problems(
        verified=head, prototype_commit=_build_commit(loaded, "prototype-report"),
        has_prototype="prototype-report" in loaded, sdk_report=loaded.get("sdk-report"),
        git=git, run_id=run_id)
    return [Refusal(FAILED, LINEAGE, p) for p in problems]


def shipped_commit(loaded):
    """The commit a release would ship: the verified one (qa-report, verification-report and
    sdk-report name it; that they agree, and that it is HEAD, is checked separately). None
    when the evidence names none."""
    for _, sha in verified_commits(loaded):
        if not is_placeholder(sha):
            return sha
    return None


def review_status(refs, loaded, allow_unreviewed=False):
    """([Refusal], {status, ...}): the review of the commit being shipped, as the manifest
    records it.

    The newest review-report must approve exactly the shipped commit - the sdk commit, which
    `sdk-review` reads, not only the development commit `review` read before sdk committed
    on top of it. `skipped` (no reviewer configured) and `absent` (no review-report) are
    refused as `unreviewed`, unless the installation set factory.release.allow_unreviewed:
    then they are carried into the manifest as UNREVIEWED, never as an approval. An approval
    of another commit, or of an older prototype-report or sdk-report than the run's newest,
    is refused whatever the setting: that is a review of a different build.
    """
    review = loaded.get("review-report")
    shipped = shipped_commit(loaded)
    record = {}
    refusals = []
    if review is None:
        status = "absent"
    elif review.get("verdict") == "skipped":
        status = "skipped"
    elif review.get("verdict") != "approve":
        status = "not-approved"
    else:
        status = "approved"
    if review is not None:
        record.update(verdict=review.get("verdict"),
                      reviewed_commit=review.get("reviewed_commit"),
                      artifact_id=(review.get("provenance") or {}).get("artifact_id"),
                      content_hash=getattr((refs or {}).get("review-report"), "content_hash",
                                           None))

    if status in ("absent", "skipped"):
        what = ("the run holds no review-report" if status == "absent" else
                "no reviewer is configured (factory.review.reviewer.kind: none), so the "
                "review was skipped")
        if allow_unreviewed:
            record["note"] = (f"UNREVIEWED: {what}; released only because "
                              "factory.release.allow_unreviewed is true. Nobody but its "
                              "author read this build. This is not an approval.")
        else:
            refusals.append(Refusal(
                FAILED, UNREVIEWED,
                f"{what}: nobody but its author read commit {_short(shipped)}. A release "
                "ships only a commit an independent review approved. Configure "
                "factory.review.reviewer and re-run from develop, or - as an explicit, "
                "recorded exception - set factory.release.allow_unreviewed: true."))
    elif status == "not-approved":
        refusals.append(Refusal(
            FAILED, "review-not-approved",
            f"the newest review-report's verdict is {review.get('verdict')!r}: the build was "
            "not approved"))
    else:
        reviewed = review.get("reviewed_commit")
        if (review.get("reviewer") or {}).get("kind") != "command":
            # Only a reviewer that ran can approve; an approval with no reviewer behind it
            # (a --mock placeholder, a hand-written report) is not a review.
            refusals.append(Refusal(
                FAILED, "review-not-approved",
                f"the newest review-report approves {_short(reviewed)} with no reviewer "
                f"behind it (reviewer kind {(review.get('reviewer') or {}).get('kind')!r}): "
                "that is not a review"))
        if is_placeholder(reviewed) or is_placeholder(shipped) \
                or not same_commit(reviewed, shipped):
            refusals.append(Refusal(
                FAILED, REVIEW_MISMATCH,
                f"the newest review approved {_short(reviewed)}, but the commit being "
                f"released is {_short(shipped)}: the approval is of another build (an "
                "approval of the development commit does not cover the sdk commit made on "
                "top of it; sdk-review must approve the sdk commit)"))
        pinned = {}
        for pin in (review.get("provenance") or {}).get("inputs") or []:
            if isinstance(pin, dict):
                pinned.setdefault(pin.get("artifact_type"), []).append(pin.get("content_hash"))
        for artifact_type in ("prototype-report", "sdk-report"):
            newest = getattr((refs or {}).get(artifact_type), "content_hash", None)
            if newest and pinned.get(artifact_type) and newest not in pinned[artifact_type]:
                refusals.append(Refusal(
                    FAILED, REVIEW_MISMATCH,
                    f"the newest review-report reviewed an older {artifact_type} than the "
                    "run's newest"))
        if refusals:
            status = "mismatch"
    record["status"] = status
    return refusals, {k: v for k, v in record.items() if v is not None}


def developed_commit(loaded):
    """The development commit the released build sits on: the sdk-report's base, else the
    prototype-report's commit - or, with neither, the verified commit. The production gates
    judge that commit - they run before sdk commits on top of it - so it is the one their
    reports must name."""
    sdk_ref = (loaded.get("sdk-report") or {}).get("build_ref") or {}
    return (sdk_ref.get("base_commit_sha") or _build_commit(loaded, "prototype-report")
            or shipped_commit(loaded))


def production_refusals(loaded, required_reports=DEFAULT_REQUIRED_REPORTS):
    """[Refusal] for each production gate report in `required_reports` that is absent, did
    not PASS, or judged another commit than the released build's development commit."""
    out = []
    developed = developed_commit(loaded)
    for artifact_type in required_reports or ():
        report = loaded.get(artifact_type)
        gate = artifact_type.rsplit("-report", 1)[0]
        if report is None:
            out.append(Refusal(BLOCKED, f"no-{artifact_type}",
                               f"no {artifact_type} in this run: the {gate} gate has not "
                               "judged the build, and a release ships only a build whose "
                               f"art and UI it passed. Run {gate} first."))
            continue
        if report.get("verdict") != "PASS":
            failed = [str(f) for f in report.get("failed") or []]
            out.append(Refusal(FAILED, f"{gate}-not-passed",
                               f"the newest {artifact_type}'s verdict is "
                               f"{report.get('verdict')!r}"
                               + (f" (failed: {', '.join(failed[:8])})" if failed else "")
                               + f": the build's {gate} was not passed."))
        judged = report.get("commit")
        if is_placeholder(judged) or is_placeholder(developed) \
                or not same_commit(judged, developed):
            out.append(Refusal(FAILED, f"{gate}-commit-mismatch",
                               f"the newest {artifact_type} judged {_short(judged)}, but the "
                               f"released build was developed at {_short(developed)}: its "
                               "verdict is about another build. Run the gate on this one."))
    return out


def listing_refusals(refs, loaded, required=DEFAULT_REQUIRED_LISTING):
    """[Refusal] for the store listing: absent (BLOCKED when required: run store-listing),
    of another commit than the one shipped, not complete, not validated by the newest
    listing-validation-report of exactly this listing, or validated FAIL/BLOCKED."""
    out = []
    listing = loaded.get("store-listing")
    report = loaded.get("listing-validation-report")
    if listing is None:
        if required:
            out.append(Refusal(BLOCKED, "no-store-listing",
                               "no store-listing in this run: the store package (branding, "
                               "screenshots, trailer, copy, per-platform renditions) has not "
                               "been made, and a release ships with its listing. Run "
                               "store-listing and listing-validation first."))
        return out
    shipped = shipped_commit(loaded)
    judged = listing.get("commit")
    if is_placeholder(judged) or is_placeholder(shipped) or not same_commit(judged, shipped):
        out.append(Refusal(FAILED, "listing-commit-mismatch",
                           f"the newest store-listing shows {_short(judged)}, but the release ships "
                           f"{_short(shipped)}: its screenshots and recording are of another build. "
                           "Run store-listing on this one."))
    if listing.get("status") != "complete":
        problems = [p.get("code") for p in listing.get("problems") or [] if p.get("severity") == "error"]
        out.append(Refusal(FAILED, "listing-incomplete",
                           f"the newest store-listing is {listing.get('status')!r}"
                           + (f" ({', '.join(str(p) for p in problems[:6])})" if problems else "")
                           + ": a release ships a complete listing or none."))
    if report is None:
        out.append(Refusal(BLOCKED, "listing-not-validated",
                           "no listing-validation-report in this run: the store listing has not "
                           "been validated against the platforms' requirements. Run "
                           "listing-validation first."))
        return out
    ref = refs.get("store-listing")
    pinned = (report.get("listing") or {}).get("content_hash")
    if ref is not None and pinned != ref.content_hash:
        out.append(Refusal(BLOCKED, "listing-not-validated",
                           f"the newest listing-validation-report judged another listing ({pinned or 'none'}; "
                           f"the run's newest is {ref.content_hash}). Run listing-validation again."))
    if report.get("verdict") != "PASS":
        failed = [str(f) for f in report.get("failed") or []]
        out.append(Refusal(FAILED, "listing-not-passed",
                           f"the newest listing-validation-report's verdict is {report.get('verdict')!r}"
                           + (f" (failed: {', '.join(failed[:8])})" if failed else "")
                           + ": the listing did not pass the platforms' requirements."))
    return out


def quality_refusals(refs, loaded, required=DEFAULT_REQUIRED_QUALITY):
    """[Refusal] for the quality gate: no quality-report (BLOCKED when required: run
    quality-gate), one that did not PASS, one about another build than the released one or
    that predates the run's newest reports of it, or a `not-release` decision. A
    `development` decision (tier mvp) is no refusal: the manifest carries it as such."""
    out = []
    report = loaded.get("quality-report")
    if report is None:
        if required:
            out.append(Refusal(BLOCKED, "no-quality-report",
                               "no quality-report in this run: the build has not been held to "
                               "the Factory's quality floor, and a release ships only a build "
                               "that holds it. Run quality-gate first."))
        return out
    if report.get("verdict") != "PASS":
        failed = [str(f) for f in report.get("failed") or []]
        out.append(Refusal(FAILED, "quality-not-passed",
                           f"the newest quality-report's verdict is {report.get('verdict')!r}"
                           + (f" (below the floor: {', '.join(failed[:8])})" if failed else "")
                           + (f": {report.get('blocked_reason')}"
                              if report.get("blocked_reason") else "")
                           + ". A release ships only a build that holds the quality floor."))
    build = report.get("build") or {}
    shipped, developed = shipped_commit(loaded), developed_commit(loaded)
    for label, judged, wanted in (("commit", build.get("commit"), shipped),
                                  ("development commit", build.get("development_commit"),
                                   developed)):
        if is_placeholder(judged) or is_placeholder(wanted) or not same_commit(judged, wanted):
            out.append(Refusal(FAILED, "quality-commit-mismatch",
                               f"the newest quality-report scored {_short(judged)} as the "
                               f"build's {label}, but the release ships {_short(wanted)}: its "
                               "scores are about another build. Run quality-gate on this one."))
            break
    pins = _pins(report)
    stale = [t for t in QUALITY_PINS
             if refs.get(t) is not None and pins.get(t) != refs[t].content_hash]
    if stale:
        out.append(Refusal(FAILED, "stale-quality-report",
                           "the newest quality-report did not score the run's newest "
                           f"{', '.join(stale)}: work came after it. Run quality-gate again."))
    decision = (report.get("release_decision") or {}).get("decision")
    if decision == "not-release":
        out.append(Refusal(FAILED, "quality-not-release",
                           "the newest quality-report decided not-release: "
                           + "; ".join((report.get("release_decision") or {}).get("reasons")
                                       or [])[:400]))
    return out


def quality_evidence(refs, loaded):
    """The manifest's evidence.quality_report: the quality-report that cleared the build, or
    None."""
    report = loaded.get("quality-report")
    ref = refs.get("quality-report")
    if report is None or ref is None:
        return None
    benchmark = report.get("benchmark") or {}
    return {"artifact_id": (report.get("provenance") or {}).get("artifact_id"),
            "content_hash": ref.content_hash,
            "verdict": report.get("verdict"),
            "decision": (report.get("release_decision") or {}).get("decision"),
            "quality_tier": report.get("quality_tier"),
            "floor_version": (benchmark.get("floor") or {}).get("version"),
            "benchmark_version": (benchmark.get("quality_benchmark") or {}).get("version")}


def gate_refusals(gates_passed, required_gates):
    """[Refusal] for each gate in `required_gates` that this run has not passed, or whose
    approval later work superseded (the engine's `context.gates_passed`)."""
    passed = set(gates_passed or ())
    return [Refusal(BLOCKED, f"{str(gate).lower()}-not-passed",
                    f"{gate} has not been passed in this run, or a newer verification "
                    f"superseded its decision: a release is drafted only after a person "
                    f"passes {gate} on the evidence it ships. Resume the run and decide it.")
            for gate in required_gates or () if gate not in passed]


def evidence_refusals(refs, loaded, run_id, *, gates_passed,
                      required_gates=DEFAULT_REQUIRED_GATES, allow_unreviewed=False,
                      required_reports=DEFAULT_REQUIRED_REPORTS,
                      required_listing=DEFAULT_REQUIRED_LISTING,
                      required_quality=False):
    """Every precondition on the run's evidence that does not hold. `refs` are the newest
    ArtifactRefs per type, `loaded` their contents.

    `gates_passed` is the engine's `context.gates_passed` and has no default: a caller that
    does not say which gates the run passed gets a TypeError, never a release. The review
    rule and `allow_unreviewed` are review_status's; the gate rule is gate_refusals'.
    """
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

    # One build throughout: the verified commit, and the lineage that leads to it.
    lineage = commit_lineage(loaded)
    missing = [source for source, sha in lineage if is_placeholder(sha)]
    if missing:
        out.append(Refusal(FAILED, "commit-unknown",
                           "no build commit recorded in: " + ", ".join(
                               f"{s} ({sha or 'missing'})" for s, sha in lineage
                               if s in missing)))
    named = [(s, sha) for s, sha in verified_commits(loaded) if not is_placeholder(sha)]
    if named and any(not same_commit(sha, named[0][1]) for _, sha in named):
        out.append(Refusal(FAILED, LINEAGE,
                           "the evidence describes different commits: "
                           + ", ".join(f"{s}={sha[:12]}" for s, sha in named)))
    elif named and not missing:
        problems = lineage_problems(
            verified=named[0][1], prototype_commit=_build_commit(loaded, "prototype-report"),
            has_prototype="prototype-report" in loaded, sdk_report=loaded.get("sdk-report"),
            git=None, run_id=run_id, history=False)
        out.extend(Refusal(FAILED, LINEAGE, p) for p in problems)
    problems, _ = review_status(refs, loaded, allow_unreviewed=allow_unreviewed)
    out.extend(problems)
    out.extend(gate_refusals(gates_passed, required_gates))
    out.extend(production_refusals(loaded, required_reports))
    out.extend(listing_refusals(refs, loaded, required_listing))
    out.extend(quality_refusals(refs, loaded, required_quality))
    if (vr.get("commit") or {}).get("dirty") is None:
        out.append(Refusal(BLOCKED, "verified-tree-unknown",
                           "the verification could not establish whether its working tree "
                           "was clean (git status failed), so no commit is known to "
                           "reproduce what it verified. Re-run verify."))
    elif (vr.get("commit") or {}).get("dirty"):
        out.append(Refusal(BLOCKED, "verified-dirty-tree",
                           "the verification ran on a working tree with uncommitted changes, "
                           "which no commit reproduces. Commit (or discard) them and re-run "
                           "verify."))
    if (vr.get("build_artifact") or {}).get("status") != "built" \
            or not (vr.get("build_artifact") or {}).get("content_hash"):
        out.append(Refusal(FAILED, "no-verified-bundle",
                           "the verification-report records no built bundle to package."))
    return out
