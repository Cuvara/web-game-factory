"""How a console adapter is authenticated: a person logs in, live, and nothing is kept.

Since publication profile 2.1.0 every console's credential is `{kind: human-login}`. The
console executor (browser/console.spec.ts) opens a headed browser in a fresh, ephemeral
context - no storage state in, none out, no persistent profile - and when the console shows
its login form, a CAPTCHA, a second factor or an anti-bot check, it waits for the PERSON to
act in that window (WAITING_FOR_HUMAN_LOGIN) and continues in the same browser once the
authenticated console is detected. The Factory never asks for, types or stores a password or
one-time code, never answers a challenge, and never saves cookies or storage: the session
lives only while that window is open.

What is left here is reading the profile's credential for the steps that ask:

    human-login   usable: nothing is needed in advance
    none          usable
    token         a tool's credential (a CLI's login), named by one environment variable the
                  installation allowlists in factory.publish.env_passthrough; registered with
                  wgflib.redact the moment it is read. No shipped adapter uses one yet.
    storage-state deprecated in 2.1.0 and refused: a captured session is never loaded

`StorageState` survives only as an inert name for callers written against 2.0.0: it loads,
copies and writes nothing, and its `path` is always None.
"""

import os

from wgflib import redact

__all__ = ["Credential", "CredentialError", "credential_names", "read_credential",
           "StorageState", "HUMAN_LOGIN"]

HUMAN_LOGIN = "human-login"


class CredentialError(ValueError):
    """The credential is configured but not usable (a deprecated captured session, a
    malformed allowlist). Not retryable; a person fixes it."""


def credential_names(settings):
    """The variable names `factory.publish.env_passthrough` lists; [] when none."""
    names = (settings or {}).get("env_passthrough") or []
    if not isinstance(names, list) or not all(isinstance(n, str) and n for n in names):
        raise CredentialError("factory.publish.env_passthrough must be a list of environment "
                              "variable names")
    return list(names)


class Credential:
    __slots__ = ("kind", "env", "present", "allowed", "value")

    def __init__(self, kind, env, present, allowed, value=None):
        self.kind = kind
        self.env = env
        self.present = present
        self.allowed = allowed
        self.value = value

    @property
    def usable(self):
        return self.kind in ("none", HUMAN_LOGIN) or (self.present and self.allowed)


def read_credential(profile, settings, environ=None):
    """The credential the profile names. A person's live login and `none` need nothing; a
    token is read from `environ` (default os.environ) only when factory.publish.
    env_passthrough allows it, and registered with redact at once. A captured session
    (`storage-state`) raises CredentialError: it is never loaded."""
    environ = os.environ if environ is None else environ
    credential = ((profile or {}).get("submission") or {}).get("credential") or {}
    kind = credential.get("kind", "none")
    env = credential.get("env")
    if kind == "storage-state":
        raise CredentialError("the publication profile names a captured session "
                              "(credential.kind storage-state), which is never loaded since "
                              "profile 2.1.0: a person logs in live in the window the publish "
                              "step opens (credential.kind human-login)")
    if kind == HUMAN_LOGIN:
        return Credential(HUMAN_LOGIN, None, True, True)
    if kind == "none" or not env:
        return Credential("none", env, True, True)
    allowed = env in credential_names(settings)
    raw = environ.get(env) if allowed else None
    present = bool(environ.get(env))
    if raw:
        redact.register(raw)
    return Credential(kind, env, present, allowed, raw if allowed else None)


class StorageState:
    """Inert since 2.1.0: no session is ever loaded, copied or written. Kept so a caller
    written against 2.0.0 still runs; `path` is always None."""

    def __init__(self, credential=None, scratch_dir=None):
        self.credential = credential
        self.scratch_dir = scratch_dir
        self.path = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
