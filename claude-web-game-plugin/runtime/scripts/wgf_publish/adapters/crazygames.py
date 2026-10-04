"""CrazyGames developer portal: the profile-driven console adapter, nothing portal-specific yet.

Every locator, url and status word is data in core/reference/publication/crazygames.yaml, where
each is a HYPOTHESIS until a person has observed the console (`wgf-publish.py observe
crazygames`): the profile says `status: unverified` and `automation_terms: unverified`, so the
publish step stops HUMAN_REQUIRED before this adapter is reached. A portal subclass
overrides a phase only for behaviour the flow cannot describe.
"""

from .console import ConsoleAdapter

__all__ = ["CrazyGamesAdapter"]


class CrazyGamesAdapter(ConsoleAdapter):
    pass
