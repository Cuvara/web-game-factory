"""The golden run's network guard: wgflib.netguard, where the develop step's smoke check
uses it too."""

from wgflib.netguard import RefusingProxy  # noqa: F401

__all__ = ["RefusingProxy"]
