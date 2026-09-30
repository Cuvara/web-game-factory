"""Shared helpers for the Factory's scripts.

Standard library only, like everything else under scripts/. The Factory ships no toolchain
and core/ must stay consumable by a provider that cannot execute anything, so these modules
exist to make the *instance* side — workspace/ — mechanically checkable, never to become a
dependency of core/ itself.

Entry points are the kebab-case scripts beside this package (`wgf-hash.py`, `wgf-state.py`,
`wgf-guard.py`). This package holds what they share; the underscore-free module names are
importable, which the entry-point names deliberately are not.
"""
