"""What a run builds before G4 (scripts/wgflib/build_scope.py), read one way by the tech plan
that plans it and by every step that judges the build.

Live 2026-10-05 (3D run new-game-20261005-002923-597b5e): the tech plan built twelve units at
tier release while the playability bot still read the design's units as its three mvp ones,
and failed probe.valid on the first post-mvp unit. These tests hold the planner and the
judges to the same rule.

    python -m unittest scripts.tests.test_build_scope
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from wgflib import build_scope, genre_models  # noqa: E402
from wgf_sufficiency import audit  # noqa: E402
from wgf_techplan import budget as plan_budget  # noqa: E402


def design(tier=None, sequence=None):
    units = [{"id": "u-01", "index": 1, "tier": "mvp"},
             {"id": "u-02", "index": 2, "tier": "mvp"},
             {"id": "u-03", "index": 3, "tier": "post-mvp"},
             {"id": "u-04", "index": 4, "tier": "post-mvp"},
             {"id": "u-05", "index": 5, "tier": "optional"},
             {"id": "u-06", "index": 6}]
    content = {"generation": {"mode": "authored"}, "units": units}
    if tier:
        content["quality_tier"] = tier
    spec = {"content": content}
    if sequence:
        spec["progression"] = {"unit_sequence": sequence}
    return {"build_spec": spec}


def ids(units):
    return [u["id"] for u in units]


class TheScope(unittest.TestCase):
    def test_release_builds_the_mvp_and_post_mvp_units(self):
        self.assertEqual(build_scope.design_tiers(design("release")), ("mvp", "post-mvp"))
        self.assertEqual(ids(build_scope.units(design("release"))),
                         ["u-01", "u-02", "u-03", "u-04", "u-06"])

    def test_mvp_builds_the_mvp_units_and_untiered_ones(self):
        self.assertEqual(build_scope.design_tiers(design("mvp")), ("mvp",))
        self.assertEqual(ids(build_scope.units(design("mvp"))), ["u-01", "u-02", "u-06"])

    def test_the_tier_the_design_states_then_the_strategy_then_the_run(self):
        strategy = {"concept": {"content_model": {"quality_tier": "release"}}}
        self.assertEqual(build_scope.quality_tier(design("mvp"), strategy, "release")[0], "mvp")
        self.assertEqual(build_scope.quality_tier(design(), strategy, "mvp")[0], "release")
        self.assertEqual(build_scope.quality_tier(design(), None, "release")[0], "release")
        self.assertEqual(build_scope.quality_tier(design())[0], build_scope.DEFAULT_TIER)

    def test_a_tier_the_benchmark_does_not_state_is_refused(self):
        with self.assertRaises(build_scope.BuildScopeError):
            build_scope.builds("platinum")

    def test_the_order_is_the_unit_sequence(self):
        built = build_scope.units(design("release", sequence=["u-04", "u-01"]))
        self.assertEqual(ids(built)[:2], ["u-04", "u-01"])


class OneRuleEverywhere(unittest.TestCase):
    """The planner and the judges read the same scope."""

    def test_the_tech_plan_builds_what_the_judges_hold_the_build_to(self):
        benchmark = build_scope.load_benchmark()
        for tier in ("mvp", "release"):
            planned = plan_budget.builds(plan_budget.quality_tier(design(tier), None)[0],
                                         benchmark)
            self.assertEqual(tuple(planned["design_tiers"]),
                             build_scope.design_tiers(design(tier)), tier)

    def test_content_sufficiency_owes_the_scope(self):
        self.assertEqual(ids(audit.owed_units(design("release"), "release")),
                         ids(build_scope.units(design("release"))))
        self.assertEqual(ids(audit.owed_units(design("mvp"), "mvp")), ["u-01", "u-02", "u-06"])
        self.assertEqual(ids(audit.owed_units(design(), None)), ["u-01", "u-02", "u-06"])
        self.assertNotIn("u-05", ids(audit.owed_units(design("release"), "release")))

    def test_the_genre_models_reading_takes_the_scope(self):
        _content, mode, mvp = genre_models.units_of(design("release"))
        self.assertEqual(mode, "authored")
        self.assertEqual(ids(mvp), ["u-01", "u-02"])
        _content, _mode, built = genre_models.units_of(design("release"), ("mvp", "post-mvp"))
        self.assertEqual(ids(built), ["u-01", "u-02", "u-03", "u-04", "u-06"])


if __name__ == "__main__":
    unittest.main()
