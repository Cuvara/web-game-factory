"""One verification: the game repository under test, its configuration, and the results so far.

The checks read everything through this object. It owns where the checkout is, how commands
are run in it, and what earlier checks concluded, so a check that depends on another (no
bundle checks without a build) can say so instead of producing noise.
"""

import hashlib
import json
import os

from wgflib import paths
from wgflib.netguard import RefusingProxy, sandbox_env
from wgflib.yamllite import YamlError, load_file

from .model import BLOCKED, Check, Evidence, PASS

__all__ = ["VerificationSession", "locate_checkout", "DEFAULT_TIMEOUTS"]

DEFAULT_TIMEOUTS = {"install": 900, "build": 600, "script": 600, "browser": 900, "git": 30}

# Relative to the checkout. Written by whoever drove the game in a browser - typically an
# agent with a Playwright browser tool - for this module to ingest. See gameplay.py.
DEFAULT_SESSION_FILE = "build/verification/gameplay-session.json"


def locate_checkout(params, config, scaffold, environ=None, section="verification"):
    """(path or None, evidence). Where the game repository under test is checked out.

    In order: the step's `with: repo_dir`, the WGF_GAME_REPO environment variable, then
    `<section>.checkouts` in factory.yaml joined with the scaffold-record's repository
    name. The module never clones: fetching code is not verification, and a checkout at an
    unknown commit would make the report's commit meaningless.
    """
    environ = os.environ if environ is None else environ
    tried = []
    candidates = []
    if params.get("repo_dir"):
        candidates.append(("step parameter repo_dir", params["repo_dir"]))
    if environ.get("WGF_GAME_REPO"):
        candidates.append(("WGF_GAME_REPO", environ["WGF_GAME_REPO"]))
    checkouts = ((config or {}).get(section) or {}).get("checkouts")
    name = ((scaffold or {}).get("repository") or {}).get("name")
    if checkouts and name:
        try:
            candidates.append((f"{section}.checkouts + scaffold-record repository",
                               paths.checkout_path(checkouts, name)))
        except ValueError:
            pass  # not one directory entry: never resolved to a path

    for source, candidate in candidates:
        path = os.path.abspath(os.path.expanduser(candidate))
        if os.path.isfile(os.path.join(path, "package.json")):
            return path, Evidence("reference", f"checkout from {source}: {path}", path=path)
        tried.append(f"{source}: {path}")

    if not candidates:
        summary = ("no checkout configured: set the step's repo_dir, WGF_GAME_REPO, or "
                   f"{section}.checkouts in factory.yaml")
        if not name:
            summary += " (and no scaffold-record names the repository)"
    else:
        summary = "no game repository (package.json) at: " + "; ".join(tried)
    return None, Evidence("observation", summary)


class VerificationSession:
    def __init__(self, root, runner, *, params=None, inputs=None, config=None, logger=None):
        self.root = root
        self.runner = runner
        self.network_refusals = []   # one wgflib.netguard summary per browser command
        self.params = dict(params or {})
        self.inputs = inputs or {}          # artifact type -> loaded content
        self.config = config or {}
        self.logger = logger
        self.results = {}                   # check id -> Check
        self.timeouts = dict(DEFAULT_TIMEOUTS)
        self.timeouts.update(self.params.get("timeouts") or {})
        self.package = self.read_json("package.json") or {}
        self.game_config = self.read_yaml("game.config.yaml") or {}
        self.commit = None
        self.dirty = None
        self.build_artifact = None
        self.runtime_facts = None
        self.assertions = {}                # platform id -> [criterionResult]
        self.gameplay_driver = None
        self.gameplay = None                # checks.gameplay.Observation

    # -- files ----------------------------------------------------------------------------

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def exists(self, *parts):
        return os.path.exists(self.path(*parts))

    def read_json(self, relative):
        try:
            with open(self.path(relative), encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return None

    def remove(self, relative):
        """Delete a generated file, so a later read cannot mistake an old one for new."""
        try:
            os.remove(self.path(relative))
        except FileNotFoundError:
            pass

    def file_hash(self, relative):
        """sha256 of a file's bytes, as provenance.schema.json#/$defs/hash, or None."""
        try:
            with open(self.path(relative), "rb") as handle:
                return "sha256:" + hashlib.sha256(handle.read()).hexdigest()
        except OSError:
            return None

    def read_yaml(self, relative):
        try:
            return load_file(self.path(relative))
        except (OSError, YamlError, ValueError):
            return None

    def walk(self, relative):
        """Every file under `relative`, as repository-relative forward-slash paths."""
        base = self.path(relative)
        found = []
        for directory, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d != "node_modules")
            for name in sorted(filenames):
                full = os.path.join(directory, name)
                found.append(os.path.relpath(full, self.root).replace(os.sep, "/"))
        return found

    def digest_tree(self, relative):
        """(sha256 digest, file count, bytes) over paths and contents, order-independent."""
        files = self.walk(relative)
        outer = hashlib.sha256()
        total = 0
        for rel in files:
            with open(self.path(rel), "rb") as handle:
                data = handle.read()
            total += len(data)
            outer.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
        return "sha256:" + outer.hexdigest(), len(files), total

    # -- configuration --------------------------------------------------------------------

    @property
    def output_dir(self):
        return ((self.game_config.get("build") or {}).get("output")) or "dist"

    @property
    def platforms(self):
        """Target platforms: game.config.yaml, else the scaffold-record's copy of it."""
        listed = self.game_config.get("platforms")
        if not listed:
            listed = ((self.inputs.get("scaffold-record") or {}).get("game_config") or {}) \
                .get("platforms")
        return [p for p in (listed or []) if isinstance(p, dict) and p.get("id")]

    def verification_flag(self, name, default=True):
        return bool((self.game_config.get("verification") or {}).get(name, default))

    def profile(self, platform_id):
        """(profile, source): the vendored copy the game pins, else the Factory's own."""
        vendored = self.read_yaml(f"config/platforms/{platform_id}.yaml")
        if vendored:
            return vendored, f"config/platforms/{platform_id}.yaml"
        core = os.path.join(paths.PLATFORMS, f"{platform_id}.yaml")
        if os.path.exists(core):
            try:
                return load_file(core), paths.display(core)
            except (YamlError, ValueError):
                return None, None
        return None, None

    # -- commands -------------------------------------------------------------------------

    @property
    def package_manager(self):
        if self.exists("pnpm-lock.yaml") or str(self.package.get("packageManager", "")) \
                .startswith("pnpm"):
            return "pnpm"
        if self.exists("yarn.lock"):
            return "yarn"
        return "npm"

    def has_script(self, name):
        return name in (self.package.get("scripts") or {})

    def script_command(self, name, *extra):
        manager = self.package_manager
        command = [manager, "run", name]
        if extra:
            command += (["--"] if manager == "npm" else []) + list(extra)
        return command

    def install_command(self):
        manager = self.package_manager
        if manager == "pnpm":
            return ["pnpm", "install", "--frozen-lockfile"]
        if manager == "yarn":
            return ["yarn", "install", "--frozen-lockfile"]
        return ["npm", "ci"] if self.exists("package-lock.json") else ["npm", "install"]

    def exec_command(self, *command):
        manager = self.package_manager
        if manager == "npm":
            return ["npx", "--no-install", *command]
        return [manager, "exec", *command]

    def run(self, command, timeout_key="script", env=None):
        """Run a command in the checkout. A browser command (the game's Playwright suites,
        the runtime-facts run) goes through a proxy that refuses every non-local request
        (wgflib.netguard): a portal build would otherwise load the portal's real SDK from its
        CDN, and a verdict - "no insecure requests", time to interactive - would measure the
        portal's CDN rather than the game. Refused requests are logged."""
        if self.logger:
            self.logger.info("verification command", command=" ".join(command))
        guard = RefusingProxy().start() if timeout_key == "browser" else None
        try:
            return self.runner.run(command, cwd=self.root, timeout=self.timeouts[timeout_key],
                                   env=dict(env or {}, **sandbox_env(guard.url)) if guard
                                   else env)
        finally:
            if guard:
                refused = guard.summary()
                guard.stop()
                self.network_refusals.append(refused)
                if self.logger and refused["refused_requests"]:
                    self.logger.info("network guarded", command=" ".join(command),
                                     refused=refused["refused_requests"],
                                     targets=refused["targets"][:5])

    # -- results --------------------------------------------------------------------------

    def record(self, check):
        self.results[check.id] = check
        return check

    def passed(self, check_id):
        check = self.results.get(check_id)
        return check is not None and check.status == PASS

    def blocked_by(self, check_id, *, id, category, title, required=True, platform_id=None):
        """A BLOCKED check whose evidence points at the check it depended on."""
        upstream = self.results.get(check_id)
        state = upstream.status if upstream else "not run"
        return Check(id, category, title, BLOCKED, required=required, platform_id=platform_id,
                     message=f"depends on {check_id}, which is {state}",
                     evidence=[Evidence("reference", f"{check_id} is {state}",
                                        check_ref=check_id)])
