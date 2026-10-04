"""One verification: the game repository under test, its configuration, and the results so far.

The checks read everything through this object. It owns where the checkout is, how commands
are run in it, and what earlier checks concluded, so a check that depends on another (no
bundle checks without a build) can say so instead of producing noise.
"""

import hashlib
import json
import os
import shutil
import tempfile

from wgflib import checkout, paths
from wgflib import template_contract as contract
from wgflib.netguard import (RefusingProxy, guarded_playwright_config, sandbox_env,
                             wraps_game_config)
from wgflib.yamllite import YamlError, load_file

from wgf_init.profiles import pin_identity

from .model import BLOCKED, Check, Evidence, PASS

__all__ = ["VerificationSession", "locate_checkout", "DEFAULT_TIMEOUTS"]

DEFAULT_TIMEOUTS = {"install": 900, "build": 600, "script": 600, "browser": 900, "git": 30}

# Relative to the checkout. Written by whoever drove the game in a browser - typically an
# agent with a Playwright browser tool - for this module to ingest. See gameplay.py.
DEFAULT_SESSION_FILE = contract.GAMEPLAY_SESSION


def locate_checkout(params, config, scaffold, environ=None, section="verification",
                    logger=None):
    """(path or None, evidence). Where the game repository under test is checked out.

    wgflib.checkout.locate's one precedence, shared by every step: the step's `with:
    repo_dir` (or `game_repo`), WGF_GAME_REPO, the scaffold-record's repository.local_path,
    then the checkouts directory (factory.checkouts; `<section>.checkouts` is a deprecated
    alias) joined with the scaffold-record's repository name. The first rule that names a
    path decides; this module never falls through to another candidate, never clones:
    fetching code is not verification, and a checkout at an unknown commit would make the
    report's commit meaningless.
    """
    try:
        path, source = checkout.locate(config, scaffold, section, params or {}, environ,
                                       logger=logger)
    except checkout.CheckoutError as exc:
        summary = (f"no checkout: {exc}. Set the step's repo_dir, WGF_GAME_REPO, or "
                   "factory.checkouts in factory.yaml")
        return None, Evidence("observation", summary)
    if os.path.isfile(os.path.join(path, contract.PACKAGE_JSON)):
        return path, Evidence("reference", f"checkout from {source}: {path}", path=path)
    return None, Evidence("observation",
                          f"no game repository ({contract.PACKAGE_JSON}) at {path} "
                          f"(from {source})")


class VerificationSession:
    def __init__(self, root, runner, *, params=None, inputs=None, config=None, logger=None,
                 missing_inputs=()):
        self.root = root
        self.runner = runner
        self.network_refusals = []   # one wgflib.netguard summary per browser command
        self.params = dict(params or {})
        self.inputs = inputs or {}          # artifact type -> loaded content
        # Inputs the workflow declares for this step that did not reach it. A check that needs
        # one can tell "the run never asked for it" from "the run asked and it is missing".
        self.missing_inputs = tuple(missing_inputs or ())
        self.config = config or {}
        self.logger = logger
        self.results = {}                   # check id -> Check
        self.e2e_workers = self._e2e_workers()
        self.timeouts = dict(DEFAULT_TIMEOUTS)
        self.timeouts.update(self.params.get("timeouts") or {})
        self.package = self.read_json(contract.PACKAGE_JSON) or {}
        self.game_config = self.read_yaml(contract.GAME_CONFIG) or {}
        self.commit = None
        self.dirty = None
        self.build_artifact = None
        self.platform_builds = {}           # platform id -> platform_builds.PlatformBuild
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
        return (((self.game_config.get("build") or {}).get("output"))
                or contract.DEFAULT_OUTPUT_DIR)

    @property
    def platforms(self):
        """Target platforms: game.config.yaml, else the scaffold-record's copy of it."""
        listed = self.game_config.get("platforms")
        if not listed:
            listed = ((self.inputs.get("scaffold-record") or {}).get("game_config") or {}) \
                .get("platforms")
        return [p for p in (listed or []) if isinstance(p, dict) and p.get("id")]

    @property
    def platform_build_mode(self):
        """platform_builds.FACTORY, REPOSITORY or None (one ordinary build): how each target
        platform gets a bundle of its own."""
        from .platform_builds import mode
        return mode(self.package, self.platforms)

    def platform_bundle(self, platform_id):
        """(directory, env): where a platform's bundle is, and the environment the
        template's scripts need to read it - its own build when there is one, else the
        ordinary output directory and no environment."""
        build = self.platform_builds.get(platform_id)
        if build is not None and build.built:
            return build.path, build.env
        return self.output_dir, {}

    def verification_flag(self, name, default=True):
        return bool((self.game_config.get("verification") or {}).get(name, default))

    def profile_identity(self, platform_id):
        """(profile, source, problems, content_hash) for a platform game.config.yaml pins.

        The game's vendored copy (config/platforms/<id>.yaml) is used only when it verifies
        by identity - version AND content hash, against pinned.json and the Factory's
        profile (wgf_init.profiles.pin_identity) - never by the version string it declares:
        two documents can both say `<id>@1.0.0`. A copy that does not verify is reported in
        `problems` and not read; the Factory's own profile stands in when its version is the
        pinned one, so the other checks are still judged by the real rules. A game that
        vendors nothing for the platform is judged by the Factory's profile."""
        cache = self.__dict__.setdefault("_profiles", {})
        if platform_id in cache:
            return cache[platform_id]
        entry = next((p for p in self.platforms if p.get("id") == platform_id),
                     {"id": platform_id})
        problems, content_hash, vendored = pin_identity(self.root, entry)
        pinned = str(entry.get("profile") or "")
        pinned_version = pinned.split("@", 1)[1] if "@" in pinned else None
        vendored_path = contract.platform_profile_path(platform_id)
        result = (None, None, problems, content_hash)
        if vendored and not problems:
            profile = self.read_yaml(vendored_path)
            if profile:
                result = (profile, vendored_path, problems, content_hash)
        if result[0] is None:
            core = os.path.join(paths.PLATFORMS, f"{platform_id}.yaml")
            if os.path.exists(core):
                try:
                    profile = load_file(core)
                except (YamlError, ValueError):
                    profile = None
                if profile is not None and (not problems or pinned_version is None
                                            or str(profile.get("version")) == pinned_version):
                    result = (profile, paths.display(core), problems, content_hash)
        cache[platform_id] = result
        return result

    def profile(self, platform_id):
        """(profile, source): the verified vendored copy the game pins, else the Factory's
        own (profile_identity says which, and why)."""
        profile, source, _problems, _hash = self.profile_identity(platform_id)
        return profile, source

    # -- commands -------------------------------------------------------------------------

    @property
    def package_manager(self):
        if self.exists(contract.PNPM_LOCK) or str(self.package.get("packageManager", "")) \
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

    def _e2e_workers(self):
        """Playwright workers for the game's own browser suite: the step's `e2e_workers`, else
        the machine's `factory.develop.smoke_workers` - the same suite on the same machine,
        which cannot stand desktop + mobile in parallel when that is set. None: the suite's
        own setting."""
        value = self.params.get("e2e_workers")
        if value is None:
            # A step's context carries the configuration as a plain dict (FactoryConfig.data);
            # a FactoryConfig is accepted too.
            config = self.config
            develop = (config.section("develop") if hasattr(config, "section")
                       else config.get("develop") if isinstance(config, dict) else None) or {}
            value = develop.get("smoke_workers") if isinstance(develop, dict) else None
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            return None
        return value

    def run(self, command, timeout_key="script", env=None):
        """Run a command in the checkout. A browser command (the game's Playwright suites,
        the runtime-facts run) goes through a proxy that refuses every non-local request
        (wgflib.netguard): a portal build would otherwise load the portal's real SDK from its
        CDN, and a verdict - "no insecure requests", time to interactive - would measure the
        portal's CDN rather than the game. Refused requests are logged.

        Every browser command is a script running the game's own Playwright config. Where
        Chromium ignores the proxy variables (wgflib.netguard.wraps_game_config) it runs with
        `-c` on a wrapper of that config handing the browser the proxy itself."""
        if self.logger:
            self.logger.info("verification command", command=" ".join(command))
        guard = RefusingProxy().start() if timeout_key == "browser" else None
        wrapper_dir, plain = None, list(command)
        if guard and wraps_game_config():
            wrapper_dir = tempfile.mkdtemp(prefix="wgf-pw-")
            wrapper = guarded_playwright_config(self.root, wrapper_dir, contract.PLAYWRIGHT_CONFIG)
            separator = ["--"] if self.package_manager == "npm" and "--" not in command else []
            command = [*command, *separator, "-c", wrapper]
        try:
            result = self.runner.run(command, cwd=self.root, timeout=self.timeouts[timeout_key],
                                     env=dict(env or {}, **sandbox_env(guard.url)) if guard
                                     else env)
            if wrapper_dir and isinstance(getattr(result, "command", None), list):
                # Evidence names the game command, not the scratch wrapper's path: the same
                # verification twice gives the same report (the summary says it was guarded).
                result.command = plain
            return result
        finally:
            if wrapper_dir:
                shutil.rmtree(wrapper_dir, ignore_errors=True)
            if guard:
                refused = guard.summary(explicit=wrapper_dir is not None)
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
