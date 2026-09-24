"""What "the developer is done" is checked against: template conformance, then the toolchain.

Conformance is static and runs first, because it is cheap and because a build that passes
every test while having edited `packages/` or imported a portal SDK is exactly the build
that must not get through. The toolchain checks are the game repository's own scripts -
the same commands its CI runs - so a green here predicts a green there.

Each check yields a `CheckResult` with status passed / failed / skipped. Skipped is only for
something genuinely unavailable on this machine (no browser for Playwright), never for a
failure, and the report says so.
"""

import json
import os
import re

from wgflib.netguard import RefusingProxy, sandbox_env

from .brief import ENGINE_DIRS, PROTECTED_PATHS, REPORT_PATH, REQUIRED_SYSTEMS
from .seam import seam_findings

__all__ = ["CheckResult", "run_checks", "conformance", "read_report", "TOOLCHAIN"]

# The game repository's own scripts, from the template's package.json.
TOOLCHAIN = {
    "install": (["pnpm", "install", "--frozen-lockfile", "--prefer-offline"], None),
    "format": (["pnpm", "run", "format"], "format"),
    "typecheck": (["pnpm", "run", "typecheck"], "typecheck"),
    "lint": (["pnpm", "run", "lint"], "lint"),
    "unit": (["pnpm", "run", "test"], "test"),
    "build": (["pnpm", "run", "build"], "build"),
    "smoke": (["pnpm", "run", "test:e2e"], "test:e2e"),
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

ENGINE_MODULES = {
    "pixijs": re.compile(r"""^(pixi\.js|@pixi/.+|@wgf/pixi-framework)$"""),
    "threejs": re.compile(r"""^(three|three/.+|@wgf/three-framework)$"""),
}

# Engines the template does not carry. Adding one is an architecture change, which is the
# tech plan's decision at G3, not an implementation detail.
FOREIGN_ENGINES = re.compile(
    r"^(phaser|phaser3|@babylonjs/.+|babylonjs|playcanvas|excalibur|kaboom|kaplay|melonjs|"
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
ENGINE_SELECTOR = "src/rendering/create-renderer.ts"

_IMPORT = re.compile(
    r"""(?:^|[\s;])(?:import|export)\s[^'"]*?from\s*['"]([^'"]+)['"]|"""
    r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)|^\s*import\s+['"]([^'"]+)['"]""",
    re.M,
)

_SOURCE = (".ts", ".tsx", ".js", ".mjs", ".mts")


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
        dirs[:] = [d for d in dirs if d not in ("node_modules", "dist")]
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


def _report_findings(report, brief):
    findings = []
    if report.get("engine") != brief["engine"]:
        findings.append(f"report engine is {report.get('engine')!r}, game.config.yaml says "
                        f"{brief['engine']!r}")
    systems = report.get("systems") or {}
    for name, _ in REQUIRED_SYSTEMS:
        status = systems.get(name)
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

    main = os.path.join(root, "src", "main.ts")
    if os.path.exists(main) and re.search(r"\bBootScene\b", _read(main)):
        findings.append("src/main.ts still starts the template's BootScene")
    findings.extend(seam_findings(root, git, brief.get("baseline_commit")))

    package = os.path.join(root, "package.json")
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

    if brief.get("baseline_commit"):
        for path in git.changed_since(brief["baseline_commit"], *PROTECTED_PATHS):
            findings.append(f"{path} is template-owned and was changed")

    report, problem = read_report(root)
    if problem:
        findings.append(problem)
    else:
        findings.extend(_report_findings(report, brief))

    if findings:
        return CheckResult("conformance", "failed",
                           f"{len(findings)} template or brief violation(s)",
                           output_tail="\n".join(findings), findings=findings)
    return CheckResult("conformance", "passed", "template rules and brief satisfied")


def _script_names(root):
    try:
        return set((json.loads(_read(os.path.join(root, "package.json"))).get("scripts")
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
            guard = RefusingProxy().start() if check_id in NETWORK_GUARDED else None
            try:
                run = runner.run(argv, cwd=root, timeout=settings.check_timeout,
                                 **({"env": sandbox_env(guard.url)} if guard else {}))
            finally:
                refused = guard.summary() if guard else None
                if guard:
                    guard.stop()
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
