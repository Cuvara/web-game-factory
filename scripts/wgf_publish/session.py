"""The credential a console adapter acts with, and how it is kept out of everything else.

A portal session is a Playwright storageState JSON a PERSON captured by logging in once
(`python scripts/wgf-publish.py capture <platform>`), kept where the installation keeps
secrets, and named to the Factory by one environment variable per platform
(core/reference/publication/<id>.yaml `submission.credential.env`). The publish step reads
that variable only when `factory.publish.env_passthrough` names it - a third allowlist,
beside the agents' and game code's, so a portal session never reaches an agent or a build -
and only for the platform whose profile names it.

The value is the path of the storage-state file, or the JSON itself. Either way the step
writes a private copy under the run's scratch directory for the one browser run, registers
every cookie and token value in it with wgflib.redact, and deletes the copy when the run
ends, whatever happened. The step never types a password: a session that has expired is
AUTH_REQUIRED, and a person captures a new one.
"""

import json
import os
import stat

from wgflib import redact

__all__ = ["Credential", "CredentialError", "credential_names", "read_credential",
           "StorageState"]


class CredentialError(ValueError):
    """The credential exists but is not usable: not JSON, not a storage state, a file that
    cannot be read. Not retryable; a person fixes it."""


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
        return self.kind == "none" or (self.present and self.allowed)


def read_credential(profile, settings, environ=None):
    """The credential the profile names, read from `environ` (default os.environ) only when
    factory.publish.env_passthrough allows it. Never logs the value; registers it with
    redact at once."""
    environ = os.environ if environ is None else environ
    credential = ((profile or {}).get("submission") or {}).get("credential") or {}
    kind = credential.get("kind", "none")
    env = credential.get("env")
    if kind == "none" or not env:
        return Credential("none", env, True, True)
    allowed = env in credential_names(settings)
    raw = environ.get(env) if allowed else None
    present = bool(environ.get(env))
    if raw:
        redact.register(raw)
    return Credential(kind, env, present, allowed, raw if allowed else None)


class StorageState:
    """A private, short-lived copy of a Playwright storage state for one browser run."""

    def __init__(self, credential, scratch_dir):
        self.credential = credential
        self.scratch_dir = scratch_dir
        self.path = None

    def __enter__(self):
        value = self.credential.value
        if value is None:
            return self
        text = value
        if not value.lstrip().startswith("{"):
            # A path to the file the person captured.
            try:
                with open(os.path.expanduser(value), encoding="utf-8") as handle:
                    text = handle.read()
            except OSError as exc:
                raise CredentialError(f"{self.credential.env} names a file that cannot be read: "
                                      f"{exc.__class__.__name__}")
        try:
            state = json.loads(text)
        except ValueError:
            raise CredentialError(f"{self.credential.env} is neither a storage-state JSON nor "
                                  f"the path of one")
        if not isinstance(state, dict) or not isinstance(state.get("cookies"), list):
            raise CredentialError(f"{self.credential.env} is not a Playwright storage state "
                                  f"(no `cookies` list)")
        for cookie in state.get("cookies") or []:
            redact.register(str(cookie.get("value") or ""))
        for origin in state.get("origins") or []:
            for item in origin.get("localStorage") or []:
                redact.register(str(item.get("value") or ""))
        redact.register(text)
        os.makedirs(self.scratch_dir, exist_ok=True)
        self.path = os.path.join(self.scratch_dir, "storage-state.json")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(state))
        try:
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        return self

    def __exit__(self, *exc):
        if self.path and os.path.exists(self.path):
            try:
                with open(self.path, "wb") as handle:  # overwrite before unlinking
                    handle.write(b"\0" * 64)
            except OSError:
                pass
            try:
                os.remove(self.path)
            except OSError:
                pass
        self.path = None
        return False
