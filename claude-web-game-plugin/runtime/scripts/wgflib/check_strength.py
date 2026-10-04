"""Whether a check that did not run may stand as passed: core/reference/quality-policy.yaml
rule 5, `skipped_checks`.

A check that could not run here - a script the game's package.json lacks, no browser for the
smoke suite, a play probe that omits what the check reads - measured nothing. At a tier whose
class is under `skipped_checks.not_passed_at` (the release tier, as shipped) the step that owns
the check treats it as not passed, unless an `optional` entry declares that check optional for
the step, the tier and the platforms. At any other tier, or when the tier is not known (a step
run outside a workflow run, a run from before the policy recorded one), it is reported as
SKIPPED and does not hold the build up - today's behaviour, stated rather than hidden.

Shared by the develop and playability steps, which own the checks; the rule is data, so no
step names a tier here. A real failure is never this module's business: it only ever makes a
skip weaker than a pass, never a failure weaker than a fail.
"""

import os

from . import paths
from .yamllite import load_file

__all__ = ["SkipPolicy", "for_tier", "POLICY_FILE"]

POLICY_FILE = os.path.join(paths.REFERENCE, "quality-policy.yaml")


class SkipPolicy:
    """The rule for one run's tier. `strict` when a skipped check is not passed at it."""

    def __init__(self, tier, klass, strict, optional):
        self.tier = tier
        self.klass = klass
        self.strict = strict
        self.optional_entries = list(optional)

    def optional(self, check, steps=(), platforms=()):
        """The `why` of the entry declaring `check` optional for any of `steps` at this tier
        and these platforms, or None."""
        steps = {s for s in steps if s}
        for entry in self.optional_entries:
            if not isinstance(entry, dict) or entry.get("check") != check:
                continue
            if entry.get("step") not in steps:
                continue
            tiers = entry.get("tiers")
            if tiers and self.tier not in tiers:
                continue
            allowed = entry.get("platforms")
            if allowed and (not platforms or any(p not in allowed for p in platforms)):
                continue
            return entry.get("why") or "declared optional in core/reference/quality-policy.yaml"
        return None

    def required(self, check, steps=(), platforms=()):
        """True when `check` skipped is not passed: a strict tier and no optional entry."""
        return self.strict and self.optional(check, steps, platforms) is None

    def describe(self):
        if self.tier is None:
            return "quality tier unknown: a skipped check is reported, not held against the build"
        return (f"quality tier {self.tier} ({self.klass}): a skipped check is "
                + ("not passed" if self.strict else "reported, not held against the build"))


def for_tier(tier, path=None):
    """The SkipPolicy for quality tier `tier` (None: unknown). Raises ValueError when the
    policy file cannot be read: a rule about what counts as passed is never defaulted."""
    path = path or POLICY_FILE
    try:
        data = load_file(path)
    except Exception as exc:
        raise ValueError(f"{paths.display(path)} cannot be read: {exc}")
    data = data if isinstance(data, dict) else {}
    classes = ((data.get("tier") or {}).get("classes")) or {}
    block = data.get("skipped_checks") or {}
    klass = classes.get(tier) if tier is not None else None
    strict = klass is not None and klass in (block.get("not_passed_at") or ())
    return SkipPolicy(tier, klass, strict, block.get("optional") or ())
