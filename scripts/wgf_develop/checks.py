"""What "the developer is done" is checked against: template conformance, then the toolchain.

Conformance is static and runs first, because it is cheap and because a build that passes
every test while having edited `packages/` or imported a portal SDK is exactly the build
that must not get through. The toolchain checks are the game repository's own scripts -
the same commands its CI runs - so a green here predicts a green there.

Each check yields a `CheckResult` with status passed / failed / skipped. Skipped is only for
something genuinely unavailable on this machine (no browser for Playwright), never for a
failure, and the report says so.

The toolchain checks run code the developer wrote (package.json scripts, tests, the
Playwright webServer), so they get wgflib.agentenv's game-code environment - the allowlist
plus `factory.agents.game_env_passthrough` - never the Factory's own.
"""

import json
import os
import posixpath
import re
import shutil
import tempfile

from wgflib import agentenv
from wgflib import template_contract as contract
from wgflib.netguard import (RefusingProxy, guarded_playwright_config, sandbox_env,
                             wraps_game_config)

from .brief import (ENGINE_DIRS, GREYBOX_DEFERRABLE, PROTECTED_PATHS, REPORT_PATH,
                    REQUIRED_SYSTEMS,
                    STRUCTURAL_PATHS, framework_package)
from .content import content_findings
from .repository import ExactEnv
from .seam import sdk_owned_findings, seam_findings
from .settings import DEFAULTS, PACKAGE_FIELDS

__all__ = ["CheckResult", "run_checks", "conformance", "package_findings", "read_report",
           "TOOLCHAIN"]

# A dependency a developer adds must come from the registry: a version range, never a path
# (file:, link:), a URL, a git or GitHub reference, an alias (npm:) or a workspace package -
# each of which puts code nobody pinned into the install.
_REGISTRY_RANGE = re.compile(r"^[A-Za-z0-9.*^~<>=| +-]+$")

# The game repository's own scripts, from the template's package.json.
# Script names are the template contract's (wgflib.template_contract), not copies of them.
_PM = contract.PACKAGE_MANAGER
TOOLCHAIN = {
    "install": ([_PM, "install", "--frozen-lockfile", "--prefer-offline"], None),
    "format": ([_PM, "run", contract.SCRIPT_FORMAT], contract.SCRIPT_FORMAT),
    "typecheck": ([_PM, "run", contract.SCRIPT_TYPECHECK], contract.SCRIPT_TYPECHECK),
    "lint": ([_PM, "run", contract.SCRIPT_LINT], contract.SCRIPT_LINT),
    "unit": ([_PM, "run", contract.SCRIPT_TEST], contract.SCRIPT_TEST),
    "build": ([_PM, "run", contract.SCRIPT_BUILD], contract.SCRIPT_BUILD),
    "smoke": ([_PM, "run", contract.SCRIPT_TEST_E2E], contract.SCRIPT_TEST_E2E),
}

# Checks that run the built game in a browser. They run behind a proxy that refuses every
# non-local request (wgflib.netguard): a portal build would otherwise load the portal's real
# SDK from its CDN - dev-build traffic to a portal, and a result that depends on the CDN. The
# real acceptance run's smoke failed exactly so, on Poki's SDK pulling an http:// ad bridge.
# A refused SDK is what an ad blocker does; the game must boot and play anyway.
NETWORK_GUARDED = ("smoke",)

# Output that means the check could not run here, not that the game is broken.
_UNAVAILABLE = {
    "smoke": re.compile(r"Executable doesn't exist|browserType\.launch|playwright install",
                        re.I),
}

# Per engine: its upstream library's modules, and the template's renderer package for it.
_ENGINE_LIBRARY_MODULES = {"pixijs": (r"pixi\.js", r"@pixi/.+"),
                           "phaserjs": (r"phaser", r"phaser/.+"),
                           "threejs": (r"three", r"three/.+")}
ENGINE_MODULES = {
    engine: re.compile("^(" + "|".join(_ENGINE_LIBRARY_MODULES.get(engine, ())
                                       + (re.escape(framework_package(engine)),)) + ")$")
    for engine in contract.ENGINES
}
# The upstream libraries alone, without the template's own renderer packages. Game source
# importing another engine is a finding either way, but the template *depends* on every
# renderer package - that is how its engine selector imports one dynamically - so the
# package.json rule judges the library, never the workspace package.
ENGINE_LIBRARIES = {
    engine: re.compile("^(" + "|".join(modules) + ")$")
    for engine, modules in _ENGINE_LIBRARY_MODULES.items()
}

# Engines the template does not carry. Adding one is an architecture change, which is the
# tech plan's decision at G3, not an implementation detail. An engine the template *does*
# carry is not listed here: importing or depending on it when it is not this game's engine
# is caught by ENGINE_MODULES, with the message that names which engine this game is.
FOREIGN_ENGINES = re.compile(
    r"^(phaser3|@babylonjs/.+|babylonjs|playcanvas|excalibur|kaboom|kaplay|melonjs|"
    r"cocos.*|@cocos/.+|@react-three/.+|aframe|littlejs|kontra)$"
)

# Portal SDKs are the integration module's, behind @wgf/platform-sdk. Game code naming
# one is the `package.platform_sdk` assertion failing at release, found early.
# Matches SDK identifiers and script URLs, not portal names: the template's own comments
# name the portals, and prose about Yandex is not a call into its SDK.
PORTAL_SDK = re.compile(
    r"\bYaGames\b|yandex\.ru/games/sdk|\bPokiSDK\b|@poki/|game-cdn\.poki\.com|"
    r"\bCrazyGames\s*\.\s*SDK\b|window\.CrazyGames\b|sdk\.crazygames\.com|crazygames-sdk|"
    r"\bGameVuiSDK\b|gamevui-sdk"
)

# The template's engine selector imports both frameworks, dynamically, by design.
# The game's entry point, from the same list.
_ENTRY_POINT = next(path for path, what in contract.SOURCE_PATHS
                    if what == "the game's entry point")
ENGINE_SELECTOR = next(path for path, what in contract.SOURCE_PATHS
                       if what == "the engine selector")
# The template's scaffold scene. The game's first scene replaces it: no game source imports
# it. What is checked is the module an import resolves to, not the class name - a game may
# call its own first scene BootScene (found by the 2.1.0 production run, whose developer did).
TEMPLATE_BOOT_SCENE = next(path for path, what in contract.SOURCE_PATHS
                           if what == "the template's boot scene")

_IMPORT = re.compile(
    r"""(?:^|[\s;])(?:import|export)\s[^'"]*?from\s*['"]([^'"]+)['"]|"""
    r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)|^\s*import\s+['"]([^'"]+)['"]""",
    re.M,
)

_SOURCE = (".ts", ".tsx", ".js", ".mjs", ".mts")


def _import_target(importer, specifier):
    """The checkout-relative module a relative import specifier names, without its source
    extension (`./game/boot-scene.js` in src/main.ts -> src/game/boot-scene); None for a
    package import."""
    if not specifier.startswith("."):
        return None
    target = posixpath.normpath(posixpath.join(posixpath.dirname(importer), specifier))
    stem, extension = posixpath.splitext(target)
    return stem if extension in _SOURCE else target


def _template_scene_findings(root):
    """Game source that imports the template's BootScene module (static, dynamic or a
    re-export). src/main.ts importing it is the template's boot sequence left in place."""
    scene = posixpath.splitext(TEMPLATE_BOOT_SCENE)[0]
    findings = []
    for relative, path in _sources(root, "src"):
        if relative == TEMPLATE_BOOT_SCENE:
            continue
        for match in _IMPORT.finditer(_read(path)):
            module = next(group for group in match.groups() if group)
            if _import_target(relative, module) != scene:
                continue
            if relative == _ENTRY_POINT:
                findings.append(f"{relative} still starts the template's BootScene "
                                f"({TEMPLATE_BOOT_SCENE}); your first scene replaces it")
            else:
                findings.append(f"{relative} imports the template's BootScene "
                                f"({TEMPLATE_BOOT_SCENE}); your first scene replaces it")
            break
    return findings


class CheckResult:
    def __init__(self, check_id, status, summary, output_tail=None, duration_s=None,
                 findings=None):
        self.id = check_id
        self.status = status
        self.summary = summary
        self.output_tail = output_tail
        self.duration_s = duration_s
        self.findings = list(findings or [])

    @property
    def failed(self):
        return self.status == "failed"

    def to_dict(self):
        data = {"id": self.id, "status": self.status, "summary": self.summary}
        if self.findings:
            data["findings"] = self.findings
        if self.duration_s is not None:
            data["duration_s"] = round(self.duration_s, 1)
        if self.output_tail and self.status != "passed":
            data["output_tail"] = self.output_tail
        return data


def _sources(root, base):
    top = os.path.join(root, base)
    for directory, dirs, files in os.walk(top):
        dirs[:] = [d for d in dirs if d not in ("node_modules", contract.DEFAULT_OUTPUT_DIR)]
        for name in files:
            if name.endswith(_SOURCE):
                path = os.path.join(directory, name)
                yield os.path.relpath(path, root).replace(os.sep, "/"), path


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def read_report(root):
    """The developer's report, or (None, reason)."""
    path = os.path.join(root, REPORT_PATH)
    if not os.path.exists(path):
        return None, f"{REPORT_PATH} was not written"
    try:
        data = json.loads(_read(path))
    except ValueError as exc:
        return None, f"{REPORT_PATH} is not JSON: {exc}"
    if not isinstance(data, dict):
        return None, f"{REPORT_PATH} is not a JSON object"
    return data, None


# Systems whose "done" is a claim about the content data the conformance check reads: a
# developer may not report them done while that data disagrees with the design.
CONTENT_SYSTEMS = ("content", "difficulty-curve")
_GAP_SEVERITIES = ("blocking", "minor")


def _gap_names(report, unit_id):
    """Whether any reported design gap names `unit_id` - by its `unit`, or in its `field`."""
    for gap in report.get("design_gaps") or []:
        if not isinstance(gap, dict):
            continue
        if gap.get("unit") == unit_id or unit_id in str(gap.get("field") or ""):
            return True
    return False


def _content_report_findings(report, brief, content_issues):
    """The development report against the content the brief asked for.

    Only when the content contract applies: a parametric or procedural design owes no unit
    list to report against, which is the same reason it owes no data file."""
    content = brief.get("content") or {}
    findings = []
    for gap in report.get("design_gaps") or []:
        if not isinstance(gap, dict):
            findings.append("design_gaps holds an entry that is not an object")
        elif gap.get("severity") not in _GAP_SEVERITIES:
            findings.append(f"design_gaps entry {gap.get('field')!r} has severity "
                            f"{gap.get('severity')!r}; it is one of "
                            f"{', '.join(_GAP_SEVERITIES)}")
    if not content.get("applies"):
        return findings
    reported = {entry.get("id"): entry for entry in report.get("content_units") or []
                if isinstance(entry, dict)}
    for unit in content.get("units") or []:
        unit_id = unit.get("id")
        entry = reported.get(unit_id)
        if entry is None:
            findings.append(f"content unit {unit_id!r} is not reported in content_units")
            continue
        status = entry.get("status")
        if status not in ("built", "partial", "cut"):
            findings.append(f"content unit {unit_id!r} has status {status!r}; it is built, "
                            f"partial or cut")
        elif status == "partial" and not str(entry.get("notes") or "").strip():
            findings.append(f"content unit {unit_id!r} is partial with no notes saying what "
                            f"is missing")
        elif status == "cut" and not _gap_names(report, unit_id):
            findings.append(f"content unit {unit_id!r} is cut and no design_gaps entry names "
                            f"it; a unit dropped without a design gap is scope lost silently")
    systems = report.get("systems") or {}
    if content_issues:
        for name in CONTENT_SYSTEMS:
            if systems.get(name) == "done":
                findings.append(f"required system {name!r} is reported done while the content "
                                f"data disagrees with the design "
                                f"({len(content_issues)} finding(s) above)")
    return findings


def _report_findings(report, brief, content_issues=()):
    findings = []
    visit = brief.get("report_visit")
    if visit and report.get("visit") != visit:
        # A handoff visit: nothing else refreshes the report, so one from an earlier visit
        # would reach review as this visit's account of the build.
        findings.append(f"{REPORT_PATH} is not this visit's: its visit is "
                        f"{report.get('visit')!r}, this visit is {visit!r}. Rewrite it for "
                        f"what the checkout holds now (systems, mvp, content_units, "
                        f"design_gaps, known_issues, how_to_play) and set \"visit\": "
                        f"\"{visit}\"")
    if report.get("engine") != brief["engine"]:
        findings.append(f"report engine is {report.get('engine')!r}, game.config.yaml says "
                        f"{brief['engine']!r}")
    systems = report.get("systems") or {}
    greybox = brief.get("phase") == "greybox"
    for name, _ in REQUIRED_SYSTEMS:
        status = systems.get(name)
        if greybox and name in GREYBOX_DEFERRABLE and status in ("done", "partial", "deferred"):
            continue
        if status != "done":
            findings.append(f"required system {name!r} is {status or 'not reported'}")
    reported = {entry.get("item"): entry.get("status") for entry in report.get("mvp") or []
                if isinstance(entry, dict)}
    for item in brief["mvp"]:
        if item not in reported:
            findings.append(f"MVP item not reported: {item!r}")
        elif reported[item] not in ("built", "partial", "cut", "deferred"):
            findings.append(f"MVP item {item!r} has status {reported[item]!r}")
    kinds = {p.get("kind") for p in report.get("placements") or [] if isinstance(p, dict)}
    for placement in brief["placements"]:
        if placement["kind"] not in kinds:
            findings.append(f"no {placement['kind']} placement reported for "
                            f"{placement['trigger']!r}")
    findings.extend(_content_report_findings(report, brief, content_issues))
    return findings


def _json_object(text, label):
    try:
        value = json.loads(text)
    except ValueError as exc:
        return None, f"{label} is not JSON: {exc}"
    if not isinstance(value, dict):
        return None, f"{label} is not a JSON object"
    return value, None


def package_findings(root, git, baseline, allowed):
    """package.json compared with the baseline commit's, field by field; pnpm-lock.yaml
    allowed to differ only alongside an allowed dependency change.

    Every field but `dependencies`/`devDependencies` must be exactly the baseline's - the
    `scripts` above all, which are what install, typecheck, lint, test, build and the smoke
    suite run here and in the sdk and verify steps. In the dependency maps, each addition,
    version change and removal must be allowed for that map (`allowed`:
    {field: [add|change|remove]}), and an added version must be a registry range. Structure,
    not text: key order and formatting are the formatter's business."""
    findings = []
    base_text = git.file_at(baseline, contract.PACKAGE_JSON)
    path = os.path.join(root, contract.PACKAGE_JSON)
    current_text = _read(path) if os.path.exists(path) else None
    changed = False
    if base_text is None:
        if current_text is not None:
            findings.append("package.json was added; the template's package.json is the only "
                            "one a game has")
    elif current_text is None:
        findings.append("package.json is template-owned and was deleted")
    else:
        base, problem = _json_object(base_text, "the baseline package.json")
        current, current_problem = _json_object(current_text, "package.json")
        if problem or current_problem:
            if base_text != current_text:
                findings.append(current_problem or f"package.json changed and {problem}")
        else:
            for key in sorted(set(base) | set(current)):
                if key in PACKAGE_FIELDS or base.get(key) == current.get(key):
                    continue
                findings.append(f"package.json `{key}` is template-owned and was changed"
                                + (" - every later check runs these scripts"
                                   if key == "scripts" else ""))
            for field in PACKAGE_FIELDS:
                old, new = base.get(field) or {}, current.get(field) or {}
                if not isinstance(new, dict):
                    findings.append(f"package.json `{field}` is not an object")
                    continue
                permitted = set((allowed or {}).get(field) or ())
                for name in sorted(set(old) | set(new)):
                    if old.get(name) == new.get(name):
                        continue
                    kind = ("add" if name not in old else
                            "remove" if name not in new else "change")
                    if kind not in permitted:
                        verb = {"add": "adds", "remove": "removes", "change": "changes"}[kind]
                        findings.append(f"package.json {verb} {field} {name!r}; allowed "
                                        f"{field} changes: {', '.join(sorted(permitted)) or 'none'}")
                        continue
                    if kind != "remove" and not (isinstance(new[name], str)
                                                 and _REGISTRY_RANGE.match(new[name])):
                        findings.append(f"package.json {field} {name!r} is {new[name]!r}, not a "
                                        f"registry version range")
                        continue
                    changed = True
    # By git's own comparison, not by reading the file back through a process's output: a
    # lockfile can be larger than the output a process may keep.
    if git.changed_since(baseline, contract.PNPM_LOCK) and not changed:
        findings.append("pnpm-lock.yaml is template-owned and changed without an allowed "
                        "dependency change in package.json")
    return findings


def conformance(root, brief, git):
    """Static rules. Returns a CheckResult."""
    findings = []
    engine = brief["engine"]
    own_dir = ENGINE_DIRS[engine] + "/"

    for relative, path in _sources(root, "src"):
        text = _read(path)
        for match in _IMPORT.finditer("" if relative == ENGINE_SELECTOR else text):
            module = next(group for group in match.groups() if group)
            for name, pattern in ENGINE_MODULES.items():
                if not pattern.match(module):
                    continue
                if name != engine:
                    findings.append(f"{relative} imports {module}: engine is {engine}")
                elif not relative.startswith(own_dir):
                    findings.append(f"{relative} imports {module} outside {own_dir}")
            if FOREIGN_ENGINES.match(module):
                findings.append(f"{relative} imports {module}, an engine the template does "
                                f"not carry")
        if PORTAL_SDK.search(text):
            findings.append(f"{relative} references a portal SDK; use the integration seam")
        if (re.search(r"\.show(Rewarded|Interstitial)\s*\(", text)
                and not relative.startswith("src/platform/")):
            findings.append(f"{relative} calls the platform's ad API directly; call the "
                            f"integration seam")

    findings.extend(_template_scene_findings(root))
    findings.extend(seam_findings(root, git, brief.get("baseline_commit")))
    findings.extend(sdk_owned_findings(root, git, brief.get("baseline_commit")))
    # The content the design states, against the content the build carries. Empty unless the
    # content contract applies (content.py).
    content_issues = content_findings(root, brief)
    findings.extend(content_issues)

    package = os.path.join(root, contract.PACKAGE_JSON)
    if os.path.exists(package):
        try:
            manifest = json.loads(_read(package))
        except ValueError:
            manifest = {}
        for field in ("dependencies", "devDependencies"):
            for name in manifest.get(field) or {}:
                if FOREIGN_ENGINES.match(name):
                    findings.append(f"package.json adds {name}, an engine the template does "
                                    f"not carry")
                    continue
                # Another engine's library is refused here too. The import rule above only
                # sees game source; a dependency nothing imports yet would otherwise sit in
                # the manifest until a later visit added the import.
                for other, pattern in ENGINE_LIBRARIES.items():
                    if other != engine and pattern.match(name):
                        findings.append(f"package.json adds {name}: engine is {engine}")

    if brief.get("baseline_commit"):
        simple = [p for p in PROTECTED_PATHS if p not in STRUCTURAL_PATHS]
        for path in git.changed_since(brief["baseline_commit"], *simple):
            findings.append(f"{path} is template-owned and was changed")
        allowed = (brief["package_changes"] if "package_changes" in brief
                   else DEFAULTS["allowed_package_changes"])  # a brief from before the key
        findings.extend(package_findings(root, git, brief["baseline_commit"], allowed))

    report, problem = read_report(root)
    if problem:
        findings.append(problem)
    else:
        findings.extend(_report_findings(report, brief, content_issues))

    if findings:
        return CheckResult("conformance", "failed",
                           f"{len(findings)} template or brief violation(s)",
                           output_tail="\n".join(findings), findings=findings)
    return CheckResult("conformance", "passed", "template rules and brief satisfied")


def _script_names(root):
    try:
        return set((json.loads(_read(os.path.join(root, contract.PACKAGE_JSON))).get("scripts")
                    or {}))
    except (OSError, ValueError):
        return set()


def run_checks(root, brief, settings, runner, git, logger=None):
    """Run the configured checks in order. A failure stops the toolchain checks after it
    only where a later one depends on it (install -> everything, build -> smoke)."""
    results = []
    scripts = _script_names(root)
    stop_all = False
    for check_id in settings.checks:
        if stop_all:
            results.append(CheckResult(check_id, "skipped", "not run: install failed"))
            continue
        if check_id == "conformance":
            result = conformance(root, brief, git)
        else:
            argv, script = TOOLCHAIN[check_id]
            if check_id == "smoke" and any(r.id == "build" and r.failed for r in results):
                results.append(CheckResult("smoke", "skipped", "not run: build failed"))
                continue
            if script and script not in scripts:
                results.append(CheckResult(check_id, "skipped",
                                           f"package.json has no {script!r} script"))
                continue
            workers = getattr(settings, "smoke_workers", None)
            if check_id == "smoke" and workers:
                # pnpm hands what follows the script name to the script itself.
                argv = [*argv, f"--workers={workers}"]
            # Code the developer wrote: an allowlisted environment, never the Factory's.
            env = agentenv.scrubbed(getattr(settings, "game_env_passthrough", ()))
            guard = RefusingProxy().start() if check_id in NETWORK_GUARDED else None
            wrapper_dir, run_argv = None, argv
            if guard:
                env.update(sandbox_env(guard.url))
                if wraps_game_config():
                    # Chromium here ignores the proxy variables: the suite runs on the game's
                    # config, wrapped to hand the browser the proxy itself (wgflib.netguard).
                    wrapper_dir = tempfile.mkdtemp(prefix="wgf-pw-")
                    run_argv = [*argv, "-c", guarded_playwright_config(
                        root, wrapper_dir, contract.PLAYWRIGHT_CONFIG)]
            try:
                run = runner.run(run_argv, cwd=root, timeout=settings.check_timeout,
                                 env=ExactEnv(env))
            finally:
                refused = guard.summary(explicit=wrapper_dir is not None) if guard else None
                if guard:
                    guard.stop()
                if wrapper_dir:
                    shutil.rmtree(wrapper_dir, ignore_errors=True)
            unavailable = _UNAVAILABLE.get(check_id)
            if not run.ok and unavailable and unavailable.search(run.output):
                result = CheckResult(check_id, "skipped",
                                     "not available on this machine (no browser installed)",
                                     output_tail=run.tail(1500), duration_s=run.duration_s)
            elif run.ok:
                result = CheckResult(check_id, "passed", " ".join(argv),
                                     duration_s=run.duration_s)
            else:
                why = "timed out" if run.timed_out else f"exit {run.returncode}"
                result = CheckResult(check_id, "failed", f"{' '.join(argv)}: {why}",
                                     output_tail=run.tail(), duration_s=run.duration_s)
            if refused and refused["refused_requests"]:
                result.summary += (f" (network guarded: {refused['refused_requests']} "
                                   f"request(s) refused: {', '.join(refused['targets'][:5])})")
            if check_id == "install" and result.failed:
                stop_all = True
        if logger is not None:
            logger.info("develop check", check=result.id, status=result.status)
        results.append(result)
    return results
