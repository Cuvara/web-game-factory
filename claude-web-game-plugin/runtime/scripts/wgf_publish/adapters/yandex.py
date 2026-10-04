"""Yandex Games Console: the profile-driven console adapter, nothing portal-specific yet.

Every locator, url and status word is data in core/reference/publication/yandex.yaml, where
each is a HYPOTHESIS until a person has observed the console (`wgf-publish.py observe
yandex`): the profile says `status: unverified` and `automation_terms: unverified`, so the
publish step stops HUMAN_REQUIRED before this adapter is reached. A portal subclass
overrides a phase only for behaviour the flow cannot describe.
"""

from .console import ConsoleAdapter

__all__ = ["YandexAdapter"]


class YandexAdapter(ConsoleAdapter):
    pass
