"""Finding ledgers and run stores for the K6.4 evidence-strength tests. Not a test module.

A ledger here is made by the REAL triage step (wgf_triage, through test_triage.run_triage),
round after round, from reports made the way their producers make them:

  * playability reports by the playability step's own judging and scenario path
    (test_playability.played_report) over FIXTURE bot records - `blind()` (the objective
    never on screen: `start.objective`, a heuristic check, FAILs on every viewport),
    `dead()` (the restart never brings play back: `restart.works`, self-reported by the
    game's probe, FAILs) and `well()` (both pass);
  * visual-qa reports in the shape the visual-qa step writes (test_triage.visual_qa), with a
    FIXTURE judge's scores: `judged(score)` - an environment score under the bar FAILs;
  * `real_naive_pace(run_dir)`: playability reports judged from REAL bot records
    (scripts/tests/fixtures/real/play-realism: this bot's naive play on the 3D validation
    game's builds, 2026-10-07) - 1c6b099, the regressed head, FAILs `naive.pace`; c340631,
    its r1-forward repair, PASSes it (as test_triage.ScenarioVerification reads them).

Each round is one build: the first is the failing one, the owner's visit builds the second
for every finding triage assigned it, and every later round is another measurement of a later
(or the same) commit. `store_run` writes a run store the way the engine does
(knowledge_runs): the specialist's prototype-report on the failing build carrying the lesson
candidate, and every triage-report of the rounds - the newest is the run's ledger.

    rounds = Rounds(tmp)
    rounds.play([("a" * 40, blind()), ("b" * 40, well()), ("c" * 40, well())])
    run = store_run(store, "run-a", rounds, candidate(...))
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import knowledge_runs as kr  # noqa: E402
import test_playability as tp  # noqa: E402
import test_triage as tt  # noqa: E402

OBJECTIVE = "playability-report:start.objective@desktop"
OBJECTIVE_MOBILE = "playability-report:start.objective@mobile"
RESTART = "playability-report:restart.works@desktop"
ENVIRONMENT = "visual-qa-report:score:environment"
# An advisory check (check-tiers): a lesson held by it derives `recommended`, the band
# below REQUIRED that evidence strength caps.
ADVISORY = "browser-qa:browser.button-states"
HARD = "playability:start.objective"
SUMMARY = ("A player is never told what to do when the objective is shown only before play "
           "starts")
ROOT_CAUSE = "No gate checked that the objective is on screen once play has begun"


def blind():
    """FIXTURE records: the objective's words never reach the screen in the first seconds."""
    records = tp.well_played()
    records["first-session"]["texts"] = ["Loading"]
    return records


def dead():
    """FIXTURE records: the restart is pressed and play never comes back."""
    records = tp.well_played()
    records["lose"]["restart"] = {"clicked": "input:retry", "playingMs": None, "metrics": None}
    return records


def well():
    return tp.well_played()


def judged(score, commit, n):
    """A visual-qa report as the step writes one, with a FIXTURE judge's environment score
    (the bar is 3): under it the report FAILs `score:environment`."""
    failing = score < 3
    report = tt.visual_qa(failed=["score:environment"] if failing else [],
                          scores={"environment": score},
                          verdict="FAIL" if failing else "PASS")
    report["commit"] = commit
    report["provenance"] = {"artifact_id": f"visual-qa-report-demo-{n}",
                            "content_hash": "sha256:" + (f"{n:02d}" * 32)[:64]}
    return report


class Rounds:
    """Builds measured and triaged one after another; `triages` holds every triage-report."""

    def __init__(self, run_dir, design=None):
        self.run_dir = run_dir
        self.design = design or tt.DESIGN_2D
        self.triages, self.reports = [], []
        self.visit = 0

    def _report(self, producer, commit, payload):
        if producer == "visual-qa-report" or "checks" in payload:
            return payload  # a report made already
        self.visit += 1
        return tp.played_report(self.run_dir, commit, records=payload, visit=self.visit)

    def play(self, builds, producer="playability-report"):
        """`builds`: [(commit, records or report)], the first failing. Returns the newest
        ledger as {finding id: record}."""
        owner, assigned = None, []
        for k, (commit, payload) in enumerate(builds):
            report = self._report(producer, commit, payload)
            self.reports.append((producer, report))
            specialist = None
            if k == 1 and assigned:
                specialist = {"role": owner, "findings": assigned}
            docs = {"game-design": self.design,
                    "prototype-report": tt._proto(commit, k + 1, specialist),
                    producer: report}
            seqs = {"prototype-report": 10 * k + 5, producer: 10 * k + 8}
            if self.triages:
                docs["triage-report"] = self.triages[-1]
                seqs["triage-report"] = 10 * (k - 1) + 9
            entered = f"{producer.split('-')[0]}.fail" if k == 0 else (
                "playability.success" if producer == "playability-report"
                else "visual-qa.develop")
            if producer == "visual-qa-report":
                entered = "visual-qa.develop"
            triage = tt.run_triage(docs, seqs=seqs, entered=entered).artifacts[0].content
            self.triages.append(triage)
            if k == 0:
                ledger = {r["id"]: r for r in triage["lifecycle"]}
                assigned = sorted(i for i, r in ledger.items() if r["status"] == "assigned")
                owner = ledger[assigned[0]]["owner"] if assigned else None
        return {r["id"]: r for r in self.triages[-1]["lifecycle"]}


NAIVE_PACE = "playability-report:naive.pace@desktop"


def real_naive_pace(run_dir):
    """{commit: playability-report} judged from the REAL naive bot records of the 3D
    validation game: 1c6b099 (FAILs naive.pace) and c340631 (PASSes), padded to 40 hex
    digits, through the playability step's own judging, scenario and report path."""
    import json
    import types
    import test_play_realism as tpr
    from wgf_playability import analysis, realism
    from wgf_playability import scenario as scenarios
    from wgf_playability.step import PlayabilityStep
    from wgflib import paths
    from wgflib.yamllite import load_file
    reports = {}
    for visit, commit in enumerate(("1c6b099", "c340631"), 1):
        record = tpr.real(f"naive-bot-3d-{commit}.json")["record"]
        units = [{"id": u["id"], "parameters": u.get("parameters") or {}}
                 for u in tpr.real(f"content-3d-{commit}.json")["units"]]
        out = os.path.join(run_dir, "playability", f"real-{visit}", "out")
        os.makedirs(os.path.join(out, "desktop"), exist_ok=True)
        with open(os.path.join(out, "desktop", "naive.json"), "w", encoding="utf-8") as h:
            json.dump(record, h)
        with open(os.path.join(out, "settings.json"), "w", encoding="utf-8") as h:
            json.dump({}, h)  # the real settings were not kept: nothing is claimed of them
        rules = load_file(os.path.join(paths.REFERENCE, "visual-quality.yaml"))
        checks = analysis._environment(
            realism.judge({"naive": record}, tpr.D3, tpr.RULES, "desktop", tpr.RELEASE, units),
            {"naive": record}, rules.get("environment") or {}, {})
        projects = [{"id": "desktop", "viewport": {"width": 1280, "height": 720}, "ran": True}]
        handed, sha = scenarios.settings_of(out)
        bot = {"version": tp.BOT_A, "settings_sha256": sha}
        checks, found = scenarios.build(checks, projects, [], {"desktop": {"naive": record}},
                                        out, run_dir, bot=bot, settings=handed)
        full = commit.ljust(40, "0")
        reports[full] = PlayabilityStep(types.SimpleNamespace(params={}))._finish(
            types.SimpleNamespace(logger=tt.Log(), execution=visit),
            types.SimpleNamespace(refs={}), "demo", full, checks, [], {}, None, projects,
            os.path.relpath(out, run_dir).replace(os.sep, "/"), bot=bot,
            scenarios=found).artifacts[0].content
    return reports


def candidate(finding, proposed_check=ADVISORY, summary=SUMMARY, **extra):
    out = kr.candidate(summary, ROOT_CAUSE, finding=finding, proposed_check=proposed_check,
                       role="ui", symptom="The first seconds of play show no goal",
                       systemic={"value": True, "why": "no gate reads the screen after start"})
    out.update(extra)
    return out


def store_run(store, run_id, rounds, candidates, commit=None, triages=None):
    """A run store holding the specialist's prototype-reports (on the first, failing build) -
    one per list in `candidates` (a list of candidates is one report) - and the rounds'
    triage-reports (or `triages`), in order."""
    run = kr.add_run(store, run_id)
    first = commit or rounds.triages[0]["commit"]
    groups = candidates if candidates and isinstance(candidates[0], list) else [candidates]
    for group in groups:
        kr.add_report(store, run, "prototype-report",
                      kr.prototype_report(list(group), commit=first),
                      artifact_id="prototype-report")
    for n, triage in enumerate(triages if triages is not None else rounds.triages, 1):
        kr.add_report(store, run, "triage-report", triage, artifact_id="triage-report")
    return run
