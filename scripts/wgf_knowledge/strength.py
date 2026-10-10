"""Evidence strength of a lesson candidate (K6.4): derived from the finding ledger, never claimed.

    snapshot(record, ledger=None, classify=None)  the re-measurement a candidate source keeps
                                                  of its finding's ledger record
    class_reader(checks, mapping)                 (producer, check id) -> (check, class), the
                                                  measurement class of K6.3's mapping
    derive(sources, proposed=())                  {"strength", "why", "refused", "unstable",
                                                   "counted"}
    ceiling(strength) / allows(strength, classification)
    problems(vocabulary)                          this module against the core vocabulary

The vocabulary is core/reference/evidence-strength.yaml (held equal to this module by
check-integrity):

    hypothesis   no measured repair: a claim, a judge's prose, a person's note, or a measured
                 failure nothing re-measured passing
    single-run   one measured FAIL->PASS pair on one scenario of one run
    reproduced   the passing measurement repeated (a later passing report of the same check,
                 on a later commit than the one that passed, that is not the same report),
                 on a check whose ledger does not alternate verdicts, by a class that is not
                 only the game's own report
    validated    reproduced in two or more distinct contexts - a context is a run and the
                 commits of its repair, so they differ in run or commit (two viewports of one
                 run and build are one) - by a class that is not only self-reported or one AI
                 judgment

A measurement that may not count is refused with its rule and reason - never dropped:

    same-report     (a) the report that detected the finding (its content hash), counted again
    own-check       (b) the lesson's own proposed check measured on a build that motivated it
                    (a build another of its sources, on another check, saw the defect on)
    same-build      (c) a pass on the commit the failure was measured on; or a later pass
                    on the commit that passed (a re-play of that build, not a repeat)
    self-agreement  (d) an AI judge re-reading a build or frames it already judged
    claim           (e) a person's or specialist's claim: a subjective source, a source a
                    promote cannot re-verify, a person's G4 decision
    duplicate       a hash-identical copy of a report or pair already counted: counted once
    no-repair       a measured failure the ledger never re-measured passing, or a repair
                    the run's newest ledger has reopened since

and what caps a pair at single-run: `unstable` (the ledger's verdicts for the check
alternate - a pass, then a failure again; or a failure and a pass on one commit),
`self-reported` (the game's probe), `single-judge` (one AI judgment), `unknown-class`.

Strength caps a promoted draft's classification below REQUIRED: hypothesis and single-run
at OBSERVATION/HEURISTIC, reproduced at RECOMMENDATION, validated at VALIDATED_PRINCIPLE.
BLOCKING and REQUIRED stay the check tiers' (K4): strength never raises nor lowers them.
Strength is about whether a measurement repeats; it says nothing about player value.

Pure: no file, no process, no clock.
"""

__all__ = ["LEVELS", "CEILING", "ENFORCEMENT", "REFUSALS", "CAPS", "VOCABULARY_FILE",
           "snapshot", "class_reader", "derive", "ceiling", "allows", "rank", "problems"]

VOCABULARY_FILE = "core/reference/evidence-strength.yaml"
LEVELS = ("hypothesis", "single-run", "reproduced", "validated")
CEILING = {"hypothesis": "HEURISTIC", "single-run": "HEURISTIC",
           "reproduced": "RECOMMENDATION", "validated": "VALIDATED_PRINCIPLE"}
ENFORCEMENT = ("REQUIRED", "BLOCKING")
REFUSALS = ("same-report", "own-check", "same-build", "self-agreement", "claim", "duplicate",
            "no-repair")
CAPS = ("unstable", "self-reported", "single-judge", "unknown-class")
# The classifications below the enforcement ones, by how much evidence they claim.
_CLASS_RANK = {"OBSERVATION": 0, "HEURISTIC": 0, "RECOMMENDATION": 1,
               "VALIDATED_PRINCIPLE": 2}
SELF_REPORTED = "self-reported"
JUDGED = "ai-judged"
# A person's G4 finding: re-measured by a person's next decision, which is a judgment.
PERSON = "decision-record"
# The ledger statuses of a repair that holds (wgf_triage.lifecycle.DONE).
DONE = ("verified", "closed")
MEASURED = "measured"


def rank(level):
    return LEVELS.index(level) if level in LEVELS else -1


def ceiling(level):
    """The strongest classification below REQUIRED a draft may propose on `level`."""
    return CEILING.get(level, CEILING["hypothesis"])


def allows(level, classification):
    """True when evidence of strength `level` supports `classification`. BLOCKING and
    REQUIRED are not strength's to allow: they are the check tiers' (always True here, the
    model holds them to the derived level)."""
    if classification in ENFORCEMENT:
        return True
    if classification not in _CLASS_RANK:
        return False
    return _CLASS_RANK[classification] <= _CLASS_RANK[ceiling(level)]


# ------------------------------------------------------------------- what a source keeps


def _measurement(m):
    """The part of a ledger measurement strength reads."""
    if not isinstance(m, dict):
        return None
    scenario = m.get("scenario")
    frames = sorted(str(f.get("sha256")) for f in m.get("frames") or ()
                    if isinstance(f, dict) and f.get("sha256"))
    return {"artifact_id": m.get("artifact_id"), "content_hash": m.get("content_hash"),
            "commit": m.get("commit"), "seq": m.get("seq"), "status": m.get("status"),
            "scenario": scenario.get("id") if isinstance(scenario, dict) else scenario,
            "frames": frames}


def _outcomes(history):
    """[{"verdict": FAIL|PASS, "commit"}] the ledger's history records of the finding's own
    measurements, in order: detected and reopened are failures, verified is a pass."""
    out = []
    for entry in history or ():
        if not isinstance(entry, dict):
            continue
        status, note = entry.get("status"), str(entry.get("note") or "")
        if status == "detected" or (status == "classified" and note.startswith("reopened")):
            out.append({"verdict": "FAIL", "commit": entry.get("build")})
        elif status == "verified":
            out.append({"verdict": "PASS", "commit": entry.get("build")})
    return out


def snapshot(record, ledger=None, classify=None):
    """What a candidate source keeps of its finding's ledger record: the before and after
    measurements, the comparison, the samples, the detection, the outcomes history and the
    check's measurement class (`classify(producer, check id) -> (check, class)`)."""
    if not isinstance(record, dict):
        return None
    source = record.get("source") or {}
    verification = record.get("verification") if isinstance(record.get("verification"),
                                                             dict) else {}
    history = record.get("history") or []
    detected = next((h for h in history if isinstance(h, dict)
                     and h.get("status") == "detected"), {})
    before = verification.get("before") or record.get("failed_measurement") or (
        {"artifact_id": detected.get("by"), "content_hash": detected.get("content_hash"),
         "commit": detected.get("build"), "seq": detected.get("seq"), "status": "FAIL"}
        if detected else None)
    after = verification.get("after")
    if after is None and verification:
        after = {"artifact_id": verification.get("artifact_id"),
                 "content_hash": verification.get("content_hash"),
                 "commit": (verification.get("build") or {}).get("commit"),
                 "seq": verification.get("seq"),
                 "status": ("PASS" if verification.get("verdict") == "passed"
                            else "FAIL" if verification.get("observed") == "fails" else None)}
    check, klass = (None, None)
    if classify is not None:
        check, klass = classify(source.get("producer"), source.get("check"))
    comparison = verification.get("comparison") or {}
    return {"ledger": ledger, "finding": record.get("id"), "producer": source.get("producer"),
            "check": check, "check_id": source.get("check"), "project": source.get("project"),
            "class": klass, "status": record.get("status"),
            "verdict": verification.get("verdict"),
            "before": _measurement(before), "after": _measurement(after),
            "same_scenario": comparison.get("same_scenario"),
            "differences": list(comparison.get("differences") or []),
            "samples": [_measurement(s) for s in verification.get("samples") or ()
                        if isinstance(s, dict)],
            "detected": {"artifact_id": detected.get("by"),
                         "content_hash": detected.get("content_hash"),
                         "commit": detected.get("build")},
            "outcomes": _outcomes(history)}


def class_reader(checks, mapping):
    """(producer, check id) -> (check name or None, class or None), by K6.3's mapping
    (wgf_quality.assessment.expand over check-tiers' declared checks). A producer's finding
    whose check is not a declared one (a judge's own finding, `score:<dim>`) takes the class
    of the families that name that producer's report as their judge (ai-judged), else the
    one class every mapped check of the producer shares, else none."""
    from wgf_quality import assessment
    mapped, _ = assessment.expand(mapping or {}, checks or {})
    by_pair, by_producer = {}, {}
    for name, family in mapped.items():
        entry = (checks or {}).get(name) or {}
        klass = family.get("class")
        by_pair.setdefault((entry.get("producer"), entry.get("id")), set()).add((name, klass))
        by_producer.setdefault(entry.get("producer"), set()).add(klass)
    judges = {}
    for family in (mapping or {}).get("families") or ():
        judge = family.get("judge") if isinstance(family, dict) else None
        if isinstance(judge, dict) and judge.get("report"):
            judges.setdefault(judge["report"], set()).add(family.get("class"))

    def classify(producer, check_id):
        found = by_pair.get((producer, check_id))
        if found:
            classes = {k for _, k in found}
            names = sorted(n for n, _ in found)
            return names[0], (classes.pop() if len(classes) == 1 else None)
        if producer in judges and len(judges[producer]) == 1:
            return None, next(iter(judges[producer]))
        shared = by_producer.get(producer) or set()
        return None, (next(iter(shared)) if len(shared) == 1 else None)
    return classify


# ------------------------------------------------------------------------ derivation


def _short(commit):
    return str(commit or "?")[:12]


def _unstable(snap):
    """Why the ledger shows the check alternating verdicts, or None: a pass followed by a
    failure again, or a failure and a pass on one commit."""
    outcomes = snap.get("outcomes") or []
    seen_pass = False
    for item in outcomes:
        if item["verdict"] == "PASS":
            seen_pass = True
        elif seen_pass:
            flips = sum(1 for a, b in zip(outcomes, outcomes[1:]) if a["verdict"] != b["verdict"])
            return f"its verdict flipped {flips} time(s) in the ledger (passed, then failed again)"
    by_commit = {}
    for item in outcomes:
        if item.get("commit"):
            by_commit.setdefault(item["commit"], set()).add(item["verdict"])
    both = sorted(c for c, v in by_commit.items() if len(v) > 1)
    if both:
        return f"it failed and passed on the same commit ({_short(both[0])}): nondeterministic"
    return None


def _refuse(refused, source, rule, reason, measurement=None):
    entry = {"rule": rule, "reason": reason, "run": source.get("run"),
             "artifact_id": source.get("artifact_id"), "report_hash": source.get("report_hash"),
             "finding": source.get("finding")}
    if measurement is not None:
        entry["measurement"] = {k: measurement.get(k)
                                for k in ("artifact_id", "content_hash", "commit", "seq")}
    refused.append(entry)


def derive(sources, proposed=()):
    """{"strength", "why", "refused", "unstable", "counted"} of a candidate's sources.

    Each source is a candidate source (ingest.py) with its `basis` and its `remeasurement`
    (snapshot()); a source whose basis is not measured is a claim. `proposed` are the
    candidate's proposed checks (check-tiers names). Pure."""
    refused, pairs, unstable = [], [], []
    seen_reports, seen_pairs = set(), set()
    for source in sources or ():
        if not isinstance(source, dict):
            continue
        report = (source.get("report_hash"), source.get("finding"))
        if source.get("report_hash") and report in seen_reports:
            _refuse(refused, source, "duplicate", "the same report (digest) as a source already "
                    "counted, offered again - counted once")
            continue
        seen_reports.add(report)
        if source.get("basis") != MEASURED:
            _refuse(refused, source, "claim",
                    f"a claim, not a measurement: {source.get('artifact_type')} "
                    + ("names no finding" if not source.get("finding") else
                       f"names {source.get('finding')}, which no gate of the run measured on "
                       "the build it was reported on (or it could not be re-verified)"))
            continue
        snap = source.get("remeasurement")
        if not isinstance(snap, dict):
            _refuse(refused, source, "no-repair", f"{source.get('finding')}: the run's ledger "
                    "holds no re-measurement of it - a measured failure, never measured fixed")
            continue
        if snap.get("producer") == PERSON:
            _refuse(refused, source, "claim", f"{snap.get('finding')} is a person's G4 finding: "
                    "its re-measurement is the person's next decision, a judgment")
            continue
        before, after = snap.get("before") or {}, snap.get("after") or {}
        if snap.get("verdict") == "same-build" or (
                before.get("commit") and before.get("commit") == after.get("commit")):
            _refuse(refused, source, "same-build", f"{snap.get('finding')} passed on the commit "
                    f"it failed on ({_short(before.get('commit'))}): a re-play, not a repair",
                    after)
            continue
        if snap.get("status") and snap.get("status") not in DONE:
            # The ledger holds the record open again: its repair failed a later
            # measurement (reopened), whatever verification it kept from before.
            why_unstable = _unstable(snap)
            if why_unstable:
                unstable.append(snap.get("finding"))
            _refuse(refused, source, "no-repair", f"{snap.get('finding')}: the run's ledger "
                    f"holds it {snap.get('status')} - reopened after its verification, so the "
                    "repair did not hold" + (f" ({why_unstable})" if why_unstable else ""),
                    after)
            continue
        if snap.get("verdict") != "passed" or before.get("status") != "FAIL" \
                or after.get("status") != "PASS":
            _refuse(refused, source, "no-repair", f"{snap.get('finding')}: the ledger's "
                    f"verification is {snap.get('verdict') or 'none'} - no measured FAIL->PASS")
            continue
        detected = (snap.get("detected") or {}).get("content_hash")
        failing = {h for h in (before.get("content_hash"), detected) if h}
        if after.get("content_hash") and (after["content_hash"] in failing
                                          or after["content_hash"] == source.get("content_hash")):
            _refuse(refused, source, "same-report", f"{snap.get('finding')}: the passing "
                    "measurement is the report that detected it (or the candidate's own), "
                    "counted again", after)
            continue
        key = (snap.get("finding"), before.get("content_hash"), after.get("content_hash"))
        if all(key) and key in seen_pairs:
            _refuse(refused, source, "duplicate", f"{snap.get('finding')}: the same FAIL->PASS "
                    "pair (content hashes) as one already counted - counted once", after)
            continue
        seen_pairs.add(key)
        pairs.append({"source": source, "snap": snap})

    # (b) the lesson's own check, measured on a build another source saw the defect on.
    proposed = {str(c) for c in proposed or () if c}
    kept = []
    for pair in pairs:
        snap = pair["snap"]
        if snap.get("check") in proposed:
            motivating = set()
            for other in pairs:
                if other is not pair and other["snap"].get("check") != snap.get("check"):
                    motivating |= {other["source"].get("commit"),
                                   (other["snap"].get("before") or {}).get("commit")}
            motivating.discard(None)
            hit = [c for c in ((snap.get("before") or {}).get("commit"),
                               (snap.get("after") or {}).get("commit")) if c in motivating]
            if hit:
                _refuse(refused, pair["source"], "own-check",
                        f"{snap.get('finding')}: {snap.get('check')} is the lesson's own "
                        f"proposed check, measured on {_short(hit[0])}, a build that "
                        "motivated the lesson - not independent of it", snap.get("after"))
                continue
        kept.append(pair)

    counted = []
    for pair in kept:
        source, snap = pair["source"], pair["snap"]
        before, after = snap["before"], snap["after"]
        klass = snap.get("class")
        failing = {h for h in (before.get("content_hash"),
                               (snap.get("detected") or {}).get("content_hash")) if h}
        used_hashes = {after.get("content_hash")}
        judged = [after]
        repeats = []
        for sample in snap.get("samples") or ():
            if not isinstance(sample, dict) or sample.get("status") not in (None, "PASS"):
                continue
            if sample.get("seq") == after.get("seq") and \
                    sample.get("content_hash") == after.get("content_hash"):
                continue  # the verifying measurement itself, kept as the first sample
            if sample.get("commit") and sample.get("commit") == before.get("commit"):
                _refuse(refused, source, "same-build", f"{snap.get('finding')}: a later pass on "
                        f"the commit it failed on ({_short(sample.get('commit'))}) - a re-play "
                        "of the failing build, not a repeat of the repair", sample)
                continue
            if sample.get("content_hash") in failing:
                _refuse(refused, source, "same-report", f"{snap.get('finding')}: a sample that "
                        "is the report that detected it", sample)
                continue
            if sample.get("content_hash") in used_hashes:
                _refuse(refused, source, "duplicate", f"{snap.get('finding')}: a sample "
                        "hash-identical to a measurement already counted - counted once", sample)
                continue
            if klass == JUDGED and any(
                    (sample.get("commit") and sample.get("commit") == j.get("commit"))
                    or (sample.get("frames") and sample.get("frames") == j.get("frames"))
                    for j in judged):
                _refuse(refused, source, "self-agreement", f"{snap.get('finding')}: the judge "
                        f"re-read a build or frames it had already judged "
                        f"({_short(sample.get('commit'))}) - its own verdict again, not a "
                        "second judgment", sample)
                continue
            if klass != JUDGED and sample.get("commit") and \
                    sample.get("commit") == after.get("commit"):
                _refuse(refused, source, "same-build", f"{snap.get('finding')}: a later pass "
                        f"on the commit that passed ({_short(sample.get('commit'))}) - a "
                        "re-play of the build that passed, not an independent repeat", sample)
                continue
            if snap.get("check") in proposed and sample.get("commit") in {
                    p["source"].get("commit") for p in kept
                    if p is not pair and p["snap"].get("check") != snap.get("check")}:
                _refuse(refused, source, "own-check", f"{snap.get('finding')}: the lesson's own "
                        "check passing on a build that motivated it", sample)
                continue
            used_hashes.add(sample.get("content_hash"))
            judged.append(sample)
            repeats.append(sample)
        level, caps = ("reproduced" if repeats else "single-run"), []
        why_unstable = _unstable(snap)
        if why_unstable:
            unstable.append(snap.get("finding"))
            caps.append(f"unstable: {why_unstable}")
        if klass == SELF_REPORTED:
            caps.append("self-reported: measured from the game's own probe")
        elif klass == JUDGED and not repeats:
            caps.append("single-judge: one AI judgment passed it")
        elif klass is None:
            caps.append("unknown-class: no measurement class is known for "
                        f"{snap.get('check') or snap.get('check_id')}")
        if caps:
            level = "single-run"
        counted.append({"finding": snap.get("finding"), "run": source.get("run"),
                        "scenario": snap.get("scenario") or (after.get("scenario")
                                                             or snap.get("project")
                                                             or snap.get("finding")),
                        "class": klass, "level": level, "repeats": len(repeats),
                        "before": before.get("commit"), "after": after.get("commit"),
                        "after_artifact": after.get("artifact_id"),
                        "caps": caps, "comparison": "same scenario" if snap.get(
                            "same_scenario") else "weaker comparison"})

    reproduced = [c for c in counted if c["level"] == "reproduced"]
    # A context is a run and the builds of its repair: two scenarios (desktop and mobile) of
    # one run, failing and passing on the same commits, are one repair measured twice by one
    # bot - not two independent contexts.
    contexts = {}
    for c in reproduced:
        contexts.setdefault((c["run"], c["before"], c["after"]), []).append(c["scenario"])
    if len(contexts) >= 2:
        strength = "validated"
        why = (f"validated: the repair reproduced in {len(contexts)} distinct contexts ("
               + "; ".join(f"{r} {_short(b)}->{_short(a)} {', '.join(map(str, s))}"
                           for (r, b, a), s in sorted(contexts.items(), key=str)) + ")")
    elif reproduced:
        first = reproduced[0]
        strength = "reproduced"
        why = (f"reproduced: {first['finding']} FAILED on {_short(first['before'])}, PASSED on "
               f"{_short(first['after'])} and passed again in {first['repeats']} later "
               f"independent measurement(s) ({first['class']}); only one context - validation "
               "needs a second run, or a repair on other builds"
               + (f" ({len(reproduced)} scenarios of one run and build are one context)"
                  if len(reproduced) > 1 else ""))
    elif counted:
        first = counted[0]
        strength = "single-run"
        capped = [cap for c in counted for cap in c["caps"]]
        why = (f"single-run: {first['finding']} FAILED on {_short(first['before'])} and PASSED "
               f"on {_short(first['after'])} once ({first['class'] or 'class unknown'})"
               + (f"; capped - {'; '.join(dict.fromkeys(capped))}" if capped else
                  "; the pass was not repeated in a later independent measurement"))
    else:
        strength = "hypothesis"
        why = ("hypothesis: no measured FAIL->PASS pair counts"
               + (f" ({len(refused)} offered measurement(s) refused: "
                  + ", ".join(sorted({r['rule'] for r in refused})) + ")" if refused else ""))
    if refused and strength != "hypothesis":
        why += (f"; {len(refused)} measurement(s) refused: "
                + ", ".join(sorted({r["rule"] for r in refused})))
    return {"strength": strength, "why": why, "refused": refused,
            "unstable": sorted({u for u in unstable if u}), "counted": counted}


def proposed_checks(record):
    """Every check a candidate proposes (`proposed_check` and `proposed_checks`)."""
    out = [record.get("proposed_check")] + list(record.get("proposed_checks") or [])
    return [str(c).strip() for c in dict.fromkeys(out) if c and str(c).strip()]


def problems(vocabulary):
    """[problem] of this module against core/reference/evidence-strength.yaml."""
    where = VOCABULARY_FILE
    if not isinstance(vocabulary, dict):
        return [f"{where}: not a mapping"]
    found = []
    levels = [l for l in vocabulary.get("levels") or () if isinstance(l, dict)]
    if [l.get("id") for l in levels] != list(LEVELS):
        found.append(f"{where}: levels must be {', '.join(LEVELS)}, in that order")
    for level in levels:
        if level.get("id") in CEILING and level.get("ceiling") != CEILING[level["id"]]:
            found.append(f"{where}: {level['id']}'s ceiling is {level.get('ceiling')}, "
                         f"strength.py holds {CEILING[level['id']]}")
        if not str(level.get("meaning") or "").strip():
            found.append(f"{where}: {level.get('id')} says what it means")
    if list(vocabulary.get("enforcement") or ()) != list(ENFORCEMENT):
        found.append(f"{where}: enforcement must be {', '.join(ENFORCEMENT)}")
    for key, expected in (("refusals", REFUSALS), ("caps", CAPS)):
        table = vocabulary.get(key) or {}
        if not isinstance(table, dict) or list(table) != list(expected):
            found.append(f"{where}: {key} must be {', '.join(expected)}, in that order")
        elif any(not str(v or "").strip() for v in table.values()):
            found.append(f"{where}: every one of {key} says why")
    return found
