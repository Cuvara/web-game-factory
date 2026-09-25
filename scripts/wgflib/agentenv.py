"""The environment an agent process starts with: an allowlist, not the Factory's own.

A developer or reviewer agent runs with the Factory user's file access, and before this it
also ran with the Factory's whole environment - every token the operator had exported: the
GitHub CLI's, a cloud key, the agent host's own. An agent that can run `pnpm exec` can
print them. What an agent host needs to run is small and known, so the environment is
built from names, never inherited:

  * PATH, HOME, USER, LOGNAME, SHELL, TERM, TMPDIR (and TMP/TEMP), TZ, LANG, CI;
  * the proxy variables (http_proxy ... NO_PROXY, either case) and SSL_CERT_FILE/DIR: how
    this machine reaches the network. A proxy URL can carry a password; an installation
    that puts one there is trusting its agents with it;
  * every LC_*, XDG_*, NODE_*, PNPM_* and npm_config_* / NPM_CONFIG_* variable - where
    the toolchain looks for its store, its cache and its registry;
  * what the installation names in `factory.agents.env_passthrough` - typically the agent
    host's own credential, which it cannot run without. An entry is a variable name, or a
    prefix ending in `*`.

A variable matched only by a prefix is still dropped when its name says it is a secret
(TOKEN, SECRET, PASSWORD, PASSWD, CREDENTIAL, AUTH, KEY): `npm_config__authToken` is a
registry credential that a prefix would otherwise carry through. Naming it exactly in
`env_passthrough` passes it; the installation then decided so, knowingly.

Game code - what the Factory itself runs inside a game repository: the package.json
scripts the develop checks, verify, sdk and release steps call, the tests, the Playwright
webServer, a build script - was written by the developer agent, and gets the same kind of
environment: `game_code_env(config)`, the same allowlist plus the names in
`factory.agents.game_env_passthrough` (default: none). That key is deliberately separate
from `env_passthrough`, so the agent host's credential never reaches game code. A package
registry credential normally lives in ~/.npmrc under HOME, which is passed; an installation
whose install step reads one from the environment names it in `game_env_passthrough`.
PLAYWRIGHT_* and COREPACK_* are toolchain configuration (where the browsers are, which
package manager version corepack provides) and are allowlisted as prefixes, still subject
to the secret-name filter.

wgflib.procs adds the WGF_PROC_* lineage tags to whatever environment it is given, so the
process tree stays findable with this environment too. The provider is never named here:
which variable an agent host reads its credential from is the installation's knowledge.
Standard library only.
"""

import os
import re

__all__ = ["BASE_NAMES", "BASE_PREFIXES", "scrubbed", "passthrough", "game_passthrough",
           "game_code_env", "ConfigError"]

BASE_NAMES = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "TMPDIR", "TMP", "TEMP",
              "TZ", "LANG", "LANGUAGE", "CI",
              # How this machine reaches the network, and which CAs it trusts: an agent host
              # behind a proxy cannot reach its API without them, and the golden runs' and
              # the smoke check's refusing proxy (wgflib.netguard) is set the same way.
              "http_proxy", "https_proxy", "all_proxy", "no_proxy", "HTTP_PROXY",
              "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR")
BASE_PREFIXES = ("LC_", "XDG_", "NODE_", "PNPM_", "npm_config_", "NPM_CONFIG_", "WGF_PROC_",
                 # Toolchain configuration, not credentials: PLAYWRIGHT_BROWSERS_PATH is
                 # where an installation keeps its browsers, COREPACK_HOME where corepack
                 # keeps its package managers.
                 "PLAYWRIGHT_", "COREPACK_")

_SECRET = re.compile(r"TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|KEY", re.I)
_ENTRY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\*?$")


class ConfigError(ValueError):
    """`factory.agents.env_passthrough` or `game_env_passthrough` is malformed. Not
    retryable."""


def _listed(config, key):
    # The factory section as a mapping (what the engine hands a step), or a FactoryConfig.
    agents = config.section("agents") if hasattr(config, "section") else \
        (config or {}).get("agents")
    listed = (agents or {}).get(key) or []
    if not isinstance(listed, list) or not all(isinstance(e, str) and _ENTRY.match(e)
                                               for e in listed):
        raise ConfigError(f"factory.agents.{key} must be a list of environment "
                          "variable names (a trailing * matches a prefix)")
    return list(listed)


def passthrough(config):
    """The names in `factory.agents.env_passthrough` of `config` (the factory section as a
    step receives it). Raises ConfigError on anything but a list of names/prefixes."""
    return _listed(config, "env_passthrough")


def game_passthrough(config):
    """The names in `factory.agents.game_env_passthrough`: what game code gets beyond the
    allowlist. Never the agents' `env_passthrough`. Raises ConfigError like passthrough()."""
    return _listed(config, "game_env_passthrough")


def game_code_env(config=None, env=None):
    """The environment for a process that runs game-repository code (a package.json script,
    the tests, a build): the allowlisted variables of `env` (default os.environ) plus
    `factory.agents.game_env_passthrough`. Raises ConfigError on a malformed key."""
    return scrubbed(game_passthrough(config), env)


def scrubbed(extra_names=(), env=None):
    """A new environment holding only the allowlisted variables of `env` (default
    os.environ), plus `extra_names`: exact names, or prefixes ending in `*`."""
    source = os.environ if env is None else env
    exact = set(BASE_NAMES)
    prefixes = list(BASE_PREFIXES)
    for entry in extra_names or ():
        if entry.endswith("*"):
            prefixes.append(entry[:-1])
        else:
            exact.add(entry)
    result = {}
    for name, value in source.items():
        if name in exact:
            # A base name is never a secret by its name alone; an installation's exact
            # entry is its own decision.
            result[name] = value
        elif any(name.startswith(prefix) for prefix in prefixes) and not _SECRET.search(name):
            result[name] = value
    return result
