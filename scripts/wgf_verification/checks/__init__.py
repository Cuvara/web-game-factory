"""The checks, in the order they run. Later groups read what earlier ones concluded."""

from ..browser_qa import check_browser
from ..model import PASS, Check
from .assets import check_assets
from .build import check_build, check_source
from .code import check_code
from .gameplay import check_gameplay
from .platform import check_platform, check_policy
from .quality import check_quality

__all__ = ["GROUPS", "run_checks"]

# Policy runs before platform: platform requirements read the runtime facts it measures.
# Quality runs before gameplay: gameplay.progression is only a pass on evidence that the
# design's progression was actually played, which is what quality carries.
# Browser QA runs after gameplay: it plays the same build, at every viewport of
# core/reference/browser-qa.yaml, with the Factory's own spec.
GROUPS = (check_source, check_build, check_code, check_quality, check_gameplay, check_browser,
          check_policy, check_platform, check_assets)


def run_checks(session, checkout_evidence):
    checks = [session.record(Check("source.checkout", "source", "Game repository checkout",
                                   PASS, message=session.root, evidence=[checkout_evidence]))]
    for group in GROUPS:
        for check in group(session):
            session.record(check)
            checks.append(check)
    return checks
