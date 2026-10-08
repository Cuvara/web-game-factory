"""A design visit takes what the strategy owns from the CURRENT strategy, never a previous design.

Found live (2026-10-08, the 2D run new-game-20261005-002926-318384, defect L31): a person
re-planned the strategy (title-strategy v3: session.target_seconds 360, first session 270; v2
said 300 and 220) and resumed from design. The visit was a design-gap repair, so the starting
draft was game-design v2 verbatim - genre.session_profile casual, 300 s - and every round
failed the casual profile's rules (one axis raised per unit) that a 360 s session does not ask
for. The fixtures are the run store's own title-strategy v2 and v3 and game-design v2.

These tests hold, on the replayed run store:

  * wgf_design/inherit.py: the strategy-owned fields (session lengths, the depth block's first
    session, the derived genre.session_profile, locales, approved placements, quality tier,
    research) follow the current strategy, and the rule deriving the profile is unchanged;
  * wgf_design/agent.py: a gap repair, a revision, and a resumed repair round all start from a
    draft that holds standard / 360 / 270, and the request records what was set and what changed
    in the strategy since the previous design (`strategy_followed`);
  * wgf_design/step.py: a gap visit computes that strategy change, and a draft the step last
    accepted is composed with the current strategy's fields.

Offline. Run from the repository root:

    python -m unittest scripts.tests.test_design_follows_strategy
"""

import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import test_design_module as design_tests  # noqa: E402
from wgf_design import AgentAuthor  # noqa: E402
from wgf_design import inherit  # noqa: E402
from wgf_design.platforms import load_platforms  # noqa: E402
from wgf_design.revision import as_draft  # noqa: E402
from wgflib.workflow.model import ArtifactRef  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures", "design", "follows-strategy-2d")

# Records what it was given - the request and the seeded draft file - and answers by marking
# every gap answered (a gap visit) or by editing the fantasy (any other visit).
HOST = r'''
import json, os, sys
request_path, draft_path = sys.argv[1:3]
with open(request_path, encoding="utf-8") as handle:
    request = json.load(handle)
with open(draft_path, encoding="utf-8") as handle:
    draft = json.load(handle)
stem = os.path.basename(draft_path)[:-len(".draft.json")]
with open(os.path.join(os.path.dirname(draft_path), f"seen-{stem}.json"), "w") as handle:
    json.dump({"request": request, "seeded": draft, "prompt": sys.argv[3]}, handle)
if request.get("gaps"):
    draft["gaps_answered"] = [{"id": g["id"], "reason": "test host"} for g in request["gaps"]]
else:
    draft["fantasy"] = "Revised: " + draft["fantasy"]
with open(draft_path, "w", encoding="utf-8") as handle:
    json.dump(draft, handle)
'''


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


class Replay(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-design-follows-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.host = os.path.join(self.scratch, "host.py")
        with open(self.host, "w", encoding="utf-8") as handle:
            handle.write(HOST)
        self.run_dir = os.path.join(self.scratch, "run")
        self.before = fixture("title-strategy-v2.json")
        self.strategy = fixture("title-strategy-v3.json")
        self.design = fixture("game-design-v2.json")
        self.platforms = load_platforms(self.strategy, None)
        # The run store as the engine left it: both strategies, and v2 of the design.
        self.write("artifacts/title-strategy/v2.json", self.before)
        self.write("artifacts/title-strategy/v3.json", self.strategy)
        payload = self.write("artifacts/game-design/v2.json", self.design)
        self.ref = ArtifactRef(
            id="game-design", type="game-design", version=2,
            location="artifacts/game-design/v2.json",
            checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
            content_hash=self.design["provenance"]["content_hash"], seq=9)

    def write(self, location, content):
        path = os.path.join(self.run_dir, *location.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = json.dumps(content, indent=2).encode("utf-8")
        with open(path, "wb") as handle:
            handle.write(payload)
        return payload

    def config(self):
        return {"design": {"author": "agent", "agent": {
            "argv": [sys.executable, self.host, "{request}", "{draft}", "{prompt}"],
            "timeout_seconds": 60, "idle_timeout_seconds": None}}}

    def seen(self, stem):
        with open(os.path.join(self.run_dir, "design", f"seen-{stem}.json"),
                  encoding="utf-8") as handle:
            return json.load(handle)

    def assertFollows(self, draft):
        self.assertEqual(draft["session"]["target_seconds"], 360)
        self.assertEqual(draft["session"]["first_session_seconds"], 270)
        self.assertEqual(draft["build_spec"]["depth"]["first_session"]["target_s"], 270)
        self.assertEqual(draft["genre"]["session_profile"], "standard")

    def gap_report(self):
        return {"design_gaps": [{"field": "build_spec.content.units[0].difficulty",
                                 "question": "Is the first unit too easy?",
                                 "severity": "minor"}],
                "provenance": {"artifact_id": "wgf:prototype-report:brick-breaker-worlds:01",
                               "content_hash": "sha256:" + "cd" * 32}}

    def visit(self, extra=None):
        context = design_tests.FakeContext(self.config(), run_dir=self.run_dir,
                                           previous_outputs=[self.ref], visit=5)
        step = design_tests.FixedClockStep(design_tests.FakeDefinition())
        return step.execute(design_tests.FakeInputs(self.strategy, extra=extra), context), \
            context


class TheStrategyOwnedFields(Replay):
    def test_the_previous_design_follows_the_replanned_strategy(self):
        draft = copy.deepcopy(self.design)
        self.assertEqual(draft["genre"]["session_profile"], "casual")
        changes = inherit.follow(draft, self.strategy, self.platforms)
        self.assertFollows(draft)
        self.assertEqual({c["field"]: (c.get("before"), c["after"]) for c in changes}, {
            "session.target_seconds": (300, 360),
            "session.first_session_seconds": (220, 270),
            "build_spec.depth.first_session.target_s": (220, 270),
            "genre.session_profile": ("casual", "standard")})
        # Nothing else of the design is touched, and following twice changes nothing.
        self.assertEqual(inherit.follow(draft, self.strategy, self.platforms), [])
        self.assertEqual(draft["build_spec"]["content"], self.design["build_spec"]["content"])
        self.assertEqual(draft["build_spec"]["monetization_touchpoints"],
                         self.design["build_spec"]["monetization_touchpoints"])

    def test_the_design_v2_strategy_is_already_followed(self):
        draft = copy.deepcopy(self.design)
        self.assertEqual(inherit.follow(draft, self.before, self.platforms), [])

    def test_the_profile_rule_is_unchanged(self):
        def strategy(kind, target):
            return {"audience": {"type": kind}, "session": {"target_seconds": target}}
        self.assertEqual(inherit.session_profile_name(strategy("casual", 300)), "casual")
        self.assertEqual(inherit.session_profile_name(strategy("casual", 360)), "standard")
        self.assertEqual(inherit.session_profile_name(strategy("midcore", 120)), "standard")
        self.assertEqual(inherit.session_profile_name({}), "standard")

    def test_placements_locales_and_tier_follow_the_strategy(self):
        draft = copy.deepcopy(self.design)
        strategy = copy.deepcopy(self.strategy)
        strategy["monetization"] = {"class": "interstitial-led", "placements": ["interstitial"]}
        strategy["concept"]["content_model"]["quality_tier"] = "production"
        draft["scope"]["locales"] = ["en", "es"]
        changes = {c["field"] for c in inherit.follow(draft, strategy, self.platforms)}
        self.assertEqual({t["kind"] for t in draft["build_spec"]["monetization_touchpoints"]},
                         {"interstitial"})
        self.assertIn("build_spec.monetization_touchpoints[rewarded-extra-ball]", changes)
        # The platforms' required locales first, en, then the design's own choices.
        self.assertEqual(draft["scope"]["locales"], ["ru", "en", "es"])
        self.assertEqual(draft["build_spec"]["content"]["quality_tier"], "production")


class TheAgentStartsFromTheCurrentStrategy(Replay):
    def brief(self, **extra):
        brief = {"title_id": self.strategy["title_id"], "strategy": self.strategy,
                 "platforms": self.platforms, "params": {}, "config": self.config(),
                 "run_dir": self.run_dir, "visit": 5, "attempt": 1}
        brief.update(extra)
        return brief

    def test_a_gap_repair_starts_from_standard_360(self):
        # The live visit: design gaps on game-design v2, strategy v3.
        gaps = [{"field": "build_spec.content.units[0].difficulty", "question": "Too easy?"}]
        AgentAuthor().draft(self.brief(gaps=gaps, previous_design=copy.deepcopy(self.design)))
        seen = self.seen("5-1-gaps")
        self.assertFollows(seen["seeded"])
        with open(seen["request"]["previous_design"], encoding="utf-8") as handle:
            self.assertFollows(json.load(handle))
        self.assertEqual(seen["request"]["content_rules"]["session_profile"]["name"],
                         "standard")
        followed = seen["request"]["strategy_followed"]
        self.assertIn("genre.session_profile", [c["field"] for c in followed["fields"]])
        self.assertIn("strategy_followed", seen["prompt"])

    def test_a_revision_starts_from_standard_360(self):
        from wgf_design.revision import previous_design
        context = design_tests.FakeContext({}, run_dir=self.run_dir,
                                           previous_outputs=[self.ref])
        revision = previous_design(context, self.strategy)
        self.assertFalse(revision["strategy_delta"]["unchanged"])
        AgentAuthor().draft(self.brief(revision=revision))
        seen = self.seen("5-1")
        self.assertFollows(seen["seeded"])
        self.assertFollows(seen["request"]["starting_draft"])
        delta = seen["request"]["strategy_followed"]["strategy_delta"]
        self.assertIn("session.target_seconds", [c["field"] for c in delta["changes"]])

    def test_a_resumed_repair_round_is_seeded_with_the_current_strategy(self):
        # The live visit's last draft (5-last-draft.json) still held casual / 300.
        last = as_draft(self.design, self.before)
        gaps = [{"field": "build_spec.content.units[0].difficulty", "question": "Too easy?"}]
        AgentAuthor().draft(self.brief(
            gaps=gaps, previous_design=copy.deepcopy(self.design),
            repair={"round": 0, "problems": ["[content.axes_monotone_with_relief] ..."],
                    "previous_draft": last}))
        self.assertFollows(self.seen("5-1-gaps-repair0")["seeded"])
        # The caller's draft is not edited behind its back.
        self.assertEqual(last["genre"]["session_profile"], "casual")


class TheStepTellsTheAuthorWhatChanged(Replay):
    def test_a_gap_visit_records_the_strategy_change(self):
        result, context = self.visit({"prototype-report": self.gap_report()})
        seen = self.seen("5-1-gaps")
        self.assertFollows(seen["seeded"])
        delta = seen["request"]["strategy_followed"]["strategy_delta"]
        self.assertTrue(delta["found"])
        changed = {c["field"]: (c.get("before"), c.get("after")) for c in delta["changes"]}
        self.assertEqual(changed["session.target_seconds"], (300, 360))
        self.assertTrue(any("strategy changed" in r[1] for r in context.logger.records))
        if result.artifacts:
            design = result.artifacts[0].content
            self.assertEqual(design["genre"]["session_profile"], "standard")
            self.assertEqual(design["session"]["target_seconds"], 360)

    def test_an_accepted_last_draft_is_composed_with_the_current_strategy(self):
        # Accepted on an earlier execution of the visit (no problems), then lost: composed
        # again without an author session - with the strategy's fields, not the draft's.
        last = as_draft(self.design, self.before)
        os.makedirs(os.path.join(self.run_dir, "design"), exist_ok=True)
        with open(os.path.join(self.run_dir, "design", "5-last-draft.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"problems": [], "draft": last}, handle)
        result, context = self.visit()
        self.assertTrue(any("composes the draft" in r[1] for r in context.logger.records))
        design = (result.artifacts or [None])[0]
        self.assertIsNotNone(design, result.error)
        self.assertFollows(design.content)


if __name__ == "__main__":
    unittest.main()
