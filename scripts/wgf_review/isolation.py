"""Reviewer isolation. The mechanism moved to wgflib/isolation.py, where the develop step
uses it too; this name stays so existing imports (`from wgf_review import isolation`) keep
working. Nothing is defined here."""

from wgflib.isolation import (  # noqa: F401
    DEFAULT_GUARDED_PATHS,
    EXPLICIT_PATHS,
    GIT_METADATA,
    Git,
    GitError,
    Snapshot,
    diff,
    guarded_paths,
    is_sensitive,
    restore,
    restore_guarded,
    take,
    take_guarded,
)

__all__ = ["Git", "GitError", "Snapshot", "take", "diff", "restore", "is_sensitive",
           "EXPLICIT_PATHS", "GIT_METADATA", "DEFAULT_GUARDED_PATHS", "guarded_paths",
           "take_guarded", "restore_guarded"]
