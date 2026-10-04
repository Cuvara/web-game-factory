"""A check never reports stronger than it measured: core/reference/quality-policy.yaml rule 5,
read by scripts/wgflib/check_strength.py for the develop and playability steps.

The residuals WS-12 named (docs/new-game-quality-inheritance.md): develop counted a skipped
check (a missing package.json script, no browser for smoke) as green, and playability made
content.variety non-required when the probe reported no entity kinds. At the release tier a
skip is not passed; below it, it is reported as skipped; a failure is never turned into one.
"""

import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from wgflib import check_strength  # noqa: E402
from wgf_develop.checks import CheckResult, apply_skip_policy  # noqa: E402

POLICY = """version: 9.9.9
tier:
  config: strategy.quality_tier
  default: release
  classes:
    release: release
    mvp: development
skipped_checks:
  not_passed_at: [release]
  optional:
    - step: develop
      check: smoke
      tiers: [release]
      platforms: [generic-web]
      why: a person decided the generic build is smoke-tested elsewhere
"""


class ThePolicy(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-strength-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.path = os.path.join(self.base, "quality-policy.yaml")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(POLICY)

    def test_the_shipped_policy_holds_skips_at_the_release_tier_and_declares_none_optional(self):
        release = check_strength.for_tier("release")
        self.assertTrue(release.strict)
        self.assertEqual(release.optional_entries, [])
        self.assertTrue(release.required("smoke", ("develop",), ("yandex",)))
        self.assertFalse(check_strength.for_tier("mvp").strict)
        self.assertFalse(check_strength.for_tier(None).strict)
        self.assertIn("unknown", check_strength.for_tier(None).describe())

    def test_an_optional_entry_holds_only_for_its_step_tier_and_platforms(self):
        policy = check_strength.for_tier("release", self.path)
        self.assertFalse(policy.required("smoke", ("develop",), ("generic-web",)))
        self.assertIn("a person decided", policy.optional("smoke", ("develop",),
                                                          ("generic-web",)))
        # Another platform beside it, another check, another step: not optional.
        self.assertTrue(policy.required("smoke", ("develop",), ("generic-web", "yandex")))
        self.assertTrue(policy.required("unit", ("develop",), ("generic-web",)))
        self.assertTrue(policy.required("smoke", ("playability",), ("generic-web",)))
        # A platform-scoped entry is not met by not knowing the platforms.
        self.assertTrue(policy.required("smoke", ("develop",), ()))

    def test_an_unreadable_policy_is_never_defaulted(self):
        with self.assertRaises(ValueError):
            check_strength.for_tier("release", os.path.join(self.base, "missing.yaml"))


class DevelopSkips(unittest.TestCase):
    """wgf_develop.checks.apply_skip_policy over the results run_checks produces."""

    def results(self):
        return [CheckResult("unit", "passed", "pnpm run test"),
                CheckResult("lint", "failed", "pnpm run lint: exit 1"),
                CheckResult("typecheck", "skipped", "package.json has no 'typecheck' script"),
                CheckResult("smoke", "skipped",
                            "not available on this machine (no browser installed)",
                            output_tail="browserType.launch: Executable doesn't exist")]

    def test_at_the_release_tier_a_missing_script_and_a_missing_browser_block(self):
        results = apply_skip_policy(self.results(), check_strength.for_tier("release"))
        unit, lint, typecheck, smoke = results
        self.assertFalse(unit.blocking)
        self.assertTrue(lint.blocking)
        self.assertEqual(lint.status, "failed")          # a failure stays a failure
        self.assertFalse(lint.required)
        self.assertEqual(typecheck.status, "skipped")    # a skip stays a skip
        self.assertTrue(typecheck.blocking)
        self.assertIn("package.json has no 'typecheck' script", typecheck.findings[0])
        self.assertTrue(smoke.blocking)
        self.assertIn("playwright install", smoke.findings[0])
        self.assertTrue(smoke.output_tail.startswith(smoke.findings[0]))
        self.assertIn("Executable doesn't exist", smoke.output_tail)
        record = smoke.to_dict()
        self.assertEqual((record["required"], record["blocking"]), (True, True))

    def test_at_the_mvp_tier_skips_are_reported_not_held(self):
        results = apply_skip_policy(self.results(), check_strength.for_tier("mvp"))
        self.assertEqual([r.id for r in results if r.blocking], ["lint"])
        for result in results:
            if result.skipped:
                self.assertEqual(result.to_dict()["required"], False)
                self.assertNotIn("blocking", result.to_dict())
                self.assertEqual(result.findings, [])

    def test_without_a_policy_nothing_changes(self):
        results = apply_skip_policy(self.results(), None)
        self.assertEqual([r.id for r in results if r.blocking], ["lint"])


if __name__ == "__main__":
    unittest.main()
