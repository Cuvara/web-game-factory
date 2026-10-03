"""The publish module: the release lifecycle's tail, run by the Factory (docs/publish-module.md).

Two step types for two lifecycle states:

    platform-validate   release:validating   the publication guards, the package on disk,
                                             the pinned profile's assertions as verify
                                             recorded them, the publication profile; writes
                                             a platform-publication with a `readiness`
    publish             release:submitting   behind G6: the platform adapter uploads,
                                             configures, submits ONCE and reads the portal's
                                             state back; writes the platform-publication
                                             advanced only from what it observed

Platform-specific behaviour lives in `adapters/` and in core/reference/publication/<id>.yaml
(data); neither step names a portal. Where a portal publishes no API - none of the shipped
profiles documents one - the console adapter drives its developer console through direct
Playwright under wgflib.procs, deterministically: fixed selectors, explicit waits, one submit.
Playwright MCP is not used here and never submits anything; it stays the QA and diagnosis
tool (workspace/config/mcp-playwright-localhost.json).

Nothing here bypasses a login, a CAPTCHA, a second factor or a portal's terms: each of them
stops the step WAITING_FOR_HUMAN with the reason, and a person continues it.
"""

from .step import PublishStep
from .validate import PlatformValidateStep

__all__ = ["PublishStep", "PlatformValidateStep", "register"]


def register(registry):
    registry.register(PlatformValidateStep.type, PlatformValidateStep)
    registry.register(PublishStep.type, PublishStep)
    return registry
