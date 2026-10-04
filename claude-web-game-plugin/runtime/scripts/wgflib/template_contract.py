"""What the Factory assumes about a game repository generated from web-game-template.

The template is a separate repository, pinned by commit (wgflib.template). Everything the
Factory's step modules read from, or run in, a game repository is a string contract with that
template: a path, an npm script name, a node CLI and its flags, a file a suite writes, a key
in game.config.yaml, a Playwright or Vitest project. This module is the single list of them,
grouped by kind, so a module imports a name instead of retyping a literal - and so
scripts/tests/test_template_contract.py can hold every entry against the pinned checkout and
fail when the template drops or renames something the Factory calls.

Data plus small pure helpers only. Nothing here runs a command, and the one file it reads is
the Factory's own tech-plan schema, for the engines (below). What a step does with an entry
stays in the step. See docs/template-contract.md.

Like the rest of wgflib, this module names no renderer or portal
(test_core_security.Coupling). The engines are the tech-plan schema's `engine.type` enum -
the one list, which guards.supported_engines() also reads - and the engine-specific paths
follow from them by the template's naming convention (renderer_package, rendering_dir),
which the drift test holds against the pinned template.

CONTRACT_VERSION versions what the Factory requires of a repository, and follows acceptance:
major when the Factory can refuse a repository it accepted before (a required entry added or
renamed), minor when it only stops assuming something (an entry removed or made optional).
An entry the Factory only recognizes when present - it refuses nothing without it - and a
rule the pinned contract already had that the Factory now encodes change neither. Every
change to the entries is recorded, versioned or not: CONTRACT_LOG says what changed and why,
and CONTRACT_DIGEST (over the entries, never their descriptions) makes a change that skips
the record fail test_template_contract.
"""

import hashlib
import json
import os
import sys

from . import paths

__all__ = [
    "CONTRACT_VERSION", "CONTRACT_LOG", "CONTRACT_DIGEST", "contract_entries",
    "contract_digest",
    # paths
    "PACKAGE_JSON", "PNPM_LOCK", "GAME_CONFIG", "PLAYWRIGHT_CONFIG", "VITEST_WORKSPACE",
    "PLATFORM_PROFILES_DIR", "SHARED_MJS", "CHANGELOG", "INFRASTRUCTURE", "SOURCE_PATHS",
    "platform_profile_path", "renderer_package", "rendering_dir", "build_target",
    # per-platform builds
    "GAME_CONFIG_ENV", "PLATFORM_BUILDS_DIR", "PLATFORM_BUILDS_INDEX", "SCRIPT_BUILD_PLATFORMS",
    "CONTRACT_MARKER", "template_contract_of", "builds_per_platform", "platform_build_dir",
    "platform_dist_dir", "platform_build_config", "platform_build_record",
    # package manager, npm scripts, executables
    "PACKAGE_MANAGER", "SCRIPT_BUILD", "SCRIPT_TYPECHECK", "SCRIPT_LINT", "SCRIPT_FORMAT",
    "SCRIPT_FORMAT_WRITE", "SCRIPT_TEST", "SCRIPT_TEST_UNIT", "SCRIPT_TEST_INTEGRATION",
    "SCRIPT_TEST_E2E", "SCRIPT_TEST_VERIFY", "SCRIPT_SDK_CONFORMANCE", "SCRIPT_SDK_BROWSER",
    "SCRIPT_RELEASE_PACKAGE", "SCRIPT_RELEASE_MANIFEST", "NPM_SCRIPTS", "SCRIPT_FLAGS",
    "EXEC_VITEST", "EXEC_TSC", "EXEC_TOOLS",
    # node CLIs
    "COLLECT_FACTS", "EVALUATE_ASSERTIONS", "NODE_CLIS",
    # outputs
    "RUNTIME_FACTS", "SDK_CONFORMANCE_REPORT", "FACTS_DIR", "ASSERTIONS_DIR",
    "GAMEPLAY_SESSION", "PLAYWRIGHT_E2E_REPORT", "RELEASE_ROOT", "RELEASE_PACKAGES",
    "RELEASE_MANIFEST", "RELEASE_CHECKSUMS", "OUTPUTS", "facts_path", "assertions_path",
    "release_path",
    # game.config.yaml
    "ENGINES", "PLATFORM_ENTRY_KEYS", "PLATFORM_ROLES", "DEFAULT_OUTPUT_DIR",
    "GAME_CONFIG_KEYS", "config_value", "MISSING",
    # test projects
    "PLAYWRIGHT_PROJECTS", "PLAYWRIGHT_MOBILE_PROJECT", "VITEST_PROJECTS", "VITEST_PROJECT_UNIT",
    "ASPECTS",
]

CONTRACT_VERSION = "2.0.0"

# (version, Factory release, change). Newest last; its version is CONTRACT_VERSION.
CONTRACT_LOG = (
    ("1.0.0", "2.0.0", "the contract as first written (M10)"),
    ("1.0.0", "2.1.1", "SOURCE_PATHS + src/game/boot-scene.ts: recognized when a game source "
                       "imports it (the BootScene conformance rule); a repository without "
                       "it is refused nowhere"),
    ("1.0.0", "2.2.0", "build_target: the pinned contract's own rule - one bundle, booting "
                       "the first required platform, else the first - now encoded; no entry "
                       "changed"),
    ("2.0.0", "2.3.0", "a second 2D engine in the tech-plan schema's engine.type enum, which "
                       "is where ENGINES comes from: the renderer package and the rendering "
                       "directory that follow from it are required entries the Factory did "
                       "not require before, so a repository generated from a template "
                       "without them is now refused"),
    ("2.0.0", "2.8.0", "per-platform builds: the pinned contract's own WGF_GAME_CONFIG override "
                       "(vite.config.ts, scripts/_shared.mjs readGameConfig) and "
                       "release:package --platform, now encoded so the Factory builds and "
                       "packages one bundle per platforms[] entry under build/platforms/<id>/; "
                       "build:platforms and the package.json wgf.template.contract marker are "
                       "recognized when present (contract 2) and required nowhere"),
)
# contract_digest() of the entries CONTRACT_LOG's last line describes. A change to any entry
# fails test_template_contract until it is recorded: bump CONTRACT_VERSION if acceptance
# changed (above), add a CONTRACT_LOG line either way, then update this.
CONTRACT_DIGEST = "sha256:bdc618c90d657bef5a2acc7c8b38728ca22908b5a23255880e62bf09f385fc7d"

# -- engines ----------------------------------------------------------------------------------


def _engines():
    with open(os.path.join(paths.ARTIFACTS, "tech-plan.schema.json"), encoding="utf-8") as handle:
        schema = json.load(handle)
    return tuple(schema["properties"]["engine"]["properties"]["type"]["enum"])


# game.config.yaml `engine.type`: the engines the template supports, in schema order.
ENGINES = _engines()


def renderer_package(engine):
    """packages/<renderer>-framework/: the renderer package for an engine id, named after
    the library without its `js` suffix."""
    name = engine[:-2] if engine.endswith("js") else engine
    return f"packages/{name}-framework/"


def rendering_dir(engine):
    """src/rendering/<engine>/: the game's rendering code for an engine."""
    return f"src/rendering/{engine}/"


# -- paths ------------------------------------------------------------------------------------

PACKAGE_JSON = "package.json"
PNPM_LOCK = "pnpm-lock.yaml"
GAME_CONFIG = "game.config.yaml"
PLAYWRIGHT_CONFIG = "playwright.config.ts"
VITEST_WORKSPACE = "vitest.workspace.ts"
PLATFORM_PROFILES_DIR = "config/platforms"
SHARED_MJS = "scripts/_shared.mjs"
# Read when present, never required: the release step's fallback for the template version.
CHANGELOG = "CHANGELOG.md"

# (path, what it carries). A trailing slash means a non-empty directory. Everything a
# freshly generated repository must contain; init refuses a project missing any of it.
# `bootstrap.yml` is deliberately absent: it deletes itself on its first run.
INFRASTRUCTURE = (
    (PACKAGE_JSON, "workspace scripts: build, test, verify, release"),
    ("pnpm-workspace.yaml", "the packages/ workspace"),
    (PNPM_LOCK, "pinned dependencies"),
    ("tsconfig.base.json", "shared TypeScript configuration"),
    ("vite.config.ts", "the build"),
    (VITEST_WORKSPACE, "unit and integration test projects"),
    (PLAYWRIGHT_CONFIG, "e2e and verify test projects"),
    (GAME_CONFIG, "the game's link to its approved plan"),
    ("packages/game-core/", "loop, scenes, events, pause, renderer seam"),
    ("packages/platform-sdk/", "the platform abstraction and portal adapters"),
    ("packages/analytics-sdk/", "the analytics event vocabulary"),
    *((renderer_package(engine), f"Renderer for engine.type: {engine}") for engine in ENGINES),
    (PLATFORM_PROFILES_DIR + "/", "platform profiles vendored at the pinned versions"),
    (SHARED_MJS, "the game-repository side of the content hash"),
    ("scripts/verify/", "package facts and the assertion evaluator"),
    ("scripts/release/", "release packaging and manifest"),
    ("scripts/publish/", "publication records"),
    ("tests/unit/", "unit test layer"),
    ("tests/integration/", "integration test layer"),
    ("tests/e2e/", "end-to-end test layer"),
    ("tests/verify/", "verify suite"),
    (".github/workflows/ci.yml", "the ci_green guard"),
    (".github/workflows/build.yml", "develop preview builds"),
    (".github/workflows/verify.yml", "the verify_suite_green guard"),
    (".github/workflows/release.yml", "release candidates"),
    (".github/workflows/publish.yml", "gate G6"),
    (".github/workflows/campaign.yml", "gate G7"),
)

# Template source the developer brief, the develop checks and the SDK inspector name. Not
# init's concern (a game may reshape its src/), but the pinned template must ship them.
SOURCE_PATHS = (
    ("src/main.ts", "the game's entry point"),
    ("src/rendering/create-renderer.ts", "the engine selector"),
    ("src/game/boot-scene.ts", "the template's boot scene"),
    *((rendering_dir(engine), f"{engine} rendering") for engine in ENGINES),
    ("src/platform/", "the game's platform wiring"),
    ("tests/e2e/smoke.spec.ts", "the smoke suite the developer extends"),
    ("eslint.config.js", "lint configuration"),
    ("packages/platform-sdk/src/types.ts", "the Platform interface"),
    ("packages/platform-sdk/src/registry.ts", "the adapter registry"),
)


def build_target(platforms):
    """The one platform a build of this contract targets, or None for no platforms.

    Contract 1.0.0 has no per-platform build: `pnpm build` makes one bundle, and that bundle
    boots one adapter - game.config.yaml's first platform whose role is exactly "required",
    else its first platform (the template's src/core/config.ts primaryPlatform() and
    scripts/build/game-config-plugin.ts; a missing role is not "required" there). Every
    other platforms[] entry is packaged from the same bundle and would boot the target's
    SDK on the wrong portal (found by the 2.1.2 production run's release draft)."""
    entries = [p for p in platforms or () if isinstance(p, dict) and p.get("id")]
    if not entries:
        return None
    return next((p["id"] for p in entries if p.get("role") == "required"), entries[0]["id"])


# -- per-platform builds ------------------------------------------------------------------------
#
# Contract 1 (the pinned release) builds one bundle per `pnpm build`, booting build_target().
# It already honours WGF_GAME_CONFIG: vite.config.ts builds against the config it names, and
# scripts/_shared.mjs readGameConfig() - read by collect-facts, release:package and
# release:manifest - measures and packages against that same config. The Factory builds each
# platform with a config whose only platforms[] entry is that platform (role required) and
# whose build.output is that platform's own directory, and keeps the bundle there: the layout
# contract 2's `build:platforms` writes itself (build/platforms/<id>/dist/, build.json).
# Contract 2 (template main, unreleased) marks itself in package.json `wgf.template.contract`
# and ships `build:platforms`; when both are present the Factory runs that instead.

GAME_CONFIG_ENV = "WGF_GAME_CONFIG"
PLATFORM_BUILDS_DIR = "build/platforms"
PLATFORM_BUILDS_INDEX = PLATFORM_BUILDS_DIR + "/index.json"
SCRIPT_BUILD_PLATFORMS = "build:platforms"
# package.json keys leading to the template's contract number.
CONTRACT_MARKER = ("wgf", "template", "contract")


def template_contract_of(package):
    """The template contract a game's package.json declares (an int), else 1: the pinned
    release declares none."""
    node = package if isinstance(package, dict) else {}
    for key in CONTRACT_MARKER:
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, int) and not isinstance(node, bool) and node > 0 else 1


def builds_per_platform(package):
    """True when the repository builds its platforms itself (`build:platforms`, contract 2+);
    False when the Factory makes each platform's build (contract 1)."""
    scripts = (package or {}).get("scripts") if isinstance(package, dict) else None
    return template_contract_of(package) >= 2 and SCRIPT_BUILD_PLATFORMS in (scripts or {})


def platform_build_dir(platform_id):
    """build/platforms/<id>: one platform's build."""
    return f"{PLATFORM_BUILDS_DIR}/{platform_id}"


def platform_dist_dir(platform_id):
    """build/platforms/<id>/dist: the bundle a platform's package is made from."""
    return f"{platform_build_dir(platform_id)}/dist"


def platform_build_config(platform_id):
    """build/platforms/<id>/game.config.json: the config a contract-1 platform build was made
    against (WGF_GAME_CONFIG). JSON, which the template's YAML parser reads."""
    return f"{platform_build_dir(platform_id)}/game.config.json"


def platform_build_record(platform_id):
    """build/platforms/<id>/build.json: what was built (contract 2's own record shape)."""
    return f"{platform_build_dir(platform_id)}/build.json"


def platform_profile_path(platform_id):
    """The vendored profile a game pins: config/platforms/<id>.yaml."""
    return f"{PLATFORM_PROFILES_DIR}/{platform_id}.yaml"


# -- package manager, npm scripts, executables -------------------------------------------------

PACKAGE_MANAGER = "pnpm"   # package.json `packageManager`, and the lockfile above

SCRIPT_BUILD = "build"
SCRIPT_TYPECHECK = "typecheck"
SCRIPT_LINT = "lint"
SCRIPT_FORMAT = "format"
SCRIPT_FORMAT_WRITE = "format:write"
SCRIPT_TEST = "test"
SCRIPT_TEST_UNIT = "test:unit"
SCRIPT_TEST_INTEGRATION = "test:integration"
SCRIPT_TEST_E2E = "test:e2e"
SCRIPT_TEST_VERIFY = "test:verify"
SCRIPT_SDK_CONFORMANCE = "sdk:conformance"
SCRIPT_SDK_BROWSER = "test:sdk:browser"
SCRIPT_RELEASE_PACKAGE = "release:package"
SCRIPT_RELEASE_MANIFEST = "release:manifest"

# npm script -> what the Factory uses it for. Each must be in package.json `scripts`.
NPM_SCRIPTS = {
    SCRIPT_BUILD: "the production build (unless game.config.yaml build.command overrides it)",
    SCRIPT_TYPECHECK: "code.typecheck; the develop checks",
    SCRIPT_LINT: "code.lint; the develop checks",
    SCRIPT_FORMAT: "the develop checks",
    SCRIPT_FORMAT_WRITE: "named in the developer brief, as the whole-repository write not to run",
    SCRIPT_TEST: "code.unit fallback; the develop checks",
    SCRIPT_TEST_UNIT: "code.unit",
    SCRIPT_TEST_INTEGRATION: "code.integration",
    SCRIPT_TEST_E2E: "gameplay evidence from the repository's Playwright suites",
    SCRIPT_TEST_VERIFY: "measures build/runtime-facts.json",
    SCRIPT_SDK_CONFORMANCE: "the sdk step's conformance report",
    SCRIPT_SDK_BROWSER: "the sdk step's optional browser smoke",
    SCRIPT_RELEASE_PACKAGE: "release/<id>/ packages, packages.json and checksums.txt",
    SCRIPT_RELEASE_MANIFEST: "release/<id>/manifest.json",
}

# Flags the Factory passes through a script to the CLI behind it.
SCRIPT_FLAGS = {
    SCRIPT_RELEASE_PACKAGE: ("--release", "--platform"),
    SCRIPT_RELEASE_MANIFEST: ("--release", "--version", "--kind", "--state"),
}

# Executables run through `pnpm exec`, and the devDependency that provides each.
EXEC_VITEST = "vitest"
EXEC_TSC = "tsc"
EXEC_TOOLS = {EXEC_VITEST: "vitest", EXEC_TSC: "typescript"}

# -- node CLIs ----------------------------------------------------------------------------------

COLLECT_FACTS = "scripts/verify/collect-facts.mjs"
EVALUATE_ASSERTIONS = "scripts/verify/evaluate-assertions.mjs"

# CLI -> the flags the Factory passes it.
NODE_CLIS = {
    COLLECT_FACTS: ("--platform", "--out"),
    EVALUATE_ASSERTIONS: ("--platform", "--facts", "--out"),
}

# -- outputs: files written in the checkout -----------------------------------------------------

RUNTIME_FACTS = "build/runtime-facts.json"
SDK_CONFORMANCE_REPORT = "build/sdk-conformance.json"
FACTS_DIR = "build/facts"
ASSERTIONS_DIR = "build/assertions"
# Chosen by the Factory, not the template: a recorded browser session the verify step
# ingests, and where it asks Playwright to write its JSON report.
GAMEPLAY_SESSION = "build/verification/gameplay-session.json"
PLAYWRIGHT_E2E_REPORT = "build/verification/playwright-e2e.json"
RELEASE_ROOT = "release"
RELEASE_PACKAGES = "packages.json"
RELEASE_MANIFEST = "manifest.json"
RELEASE_CHECKSUMS = "checksums.txt"

# output -> (who writes it, whose name it is: "template" or "factory"). A template-named
# output is one the template's own code writes at that path; the drift test finds it there.
OUTPUTS = {
    RUNTIME_FACTS: (SCRIPT_TEST_VERIFY, "template"),
    SDK_CONFORMANCE_REPORT: (SCRIPT_SDK_CONFORMANCE, "template"),
    FACTS_DIR + "/<platform>.json": (COLLECT_FACTS, "template"),
    ASSERTIONS_DIR + "/<platform>.json": (EVALUATE_ASSERTIONS, "factory"),
    RELEASE_ROOT + "/<release-id>/" + RELEASE_PACKAGES: (SCRIPT_RELEASE_PACKAGE, "template"),
    RELEASE_ROOT + "/<release-id>/" + RELEASE_CHECKSUMS: (SCRIPT_RELEASE_PACKAGE, "template"),
    RELEASE_ROOT + "/<release-id>/" + RELEASE_MANIFEST: (SCRIPT_RELEASE_MANIFEST, "template"),
    GAMEPLAY_SESSION: ("a browser-driving agent", "factory"),
    # Contract 1: the Factory's per-platform build (wgf_verification.platform_builds).
    PLATFORM_BUILDS_DIR + "/<platform>/dist": ("the verify step, per platform", "factory"),
    PLATFORM_BUILDS_DIR + "/<platform>/game.config.json": ("the verify step, per platform",
                                                          "factory"),
    PLATFORM_BUILDS_DIR + "/<platform>/build.json": ("the verify step, per platform", "factory"),
    PLATFORM_BUILDS_INDEX: ("the verify step", "factory"),
    PLAYWRIGHT_E2E_REPORT: (SCRIPT_TEST_E2E, "factory"),
}


def facts_path(platform_id):
    return f"{FACTS_DIR}/{platform_id}.json"


def assertions_path(platform_id):
    return f"{ASSERTIONS_DIR}/{platform_id}.json"


def release_path(release_id, *names):
    """release/<release-id>[/<name>...], as forward-slash parts to join onto a root."""
    return (RELEASE_ROOT, release_id) + tuple(names)


# -- game.config.yaml ---------------------------------------------------------------------------

PLATFORM_ENTRY_KEYS = ("id", "profile", "role")
PLATFORM_ROLES = ("required", "optional")
DEFAULT_OUTPUT_DIR = "dist"

# Dotted keys the Factory reads. Each is present in the pinned template's game.config.yaml.
GAME_CONFIG_KEYS = (
    "game.id",
    "game.version",
    "engine.type",
    "platforms",
    "monetization.ad_kinds",
    "build.command",
    "build.output",
    "verification.mobile_test",
)

MISSING = object()

# Descriptions, not entries: text that explains an entry and may change freely.
_DESCRIBED_PAIRS = ("INFRASTRUCTURE", "SOURCE_PATHS")
_DESCRIPTION_VALUES = ("NPM_SCRIPTS",)


def contract_entries():
    """Every entry of the contract, without descriptions: {name: canonical value}. What
    CONTRACT_DIGEST is computed over."""
    module = sys.modules[__name__]
    entries = {}
    for name in __all__:
        if name in ("CONTRACT_VERSION", "CONTRACT_LOG", "CONTRACT_DIGEST"):
            continue
        value = getattr(module, name)
        if callable(value) or value is MISSING:
            continue
        if name in _DESCRIBED_PAIRS:
            value = [path for path, _ in value]
        elif name in _DESCRIPTION_VALUES:
            value = sorted(value)
        elif isinstance(value, dict):
            value = {k: list(v) if isinstance(v, tuple) else v for k, v in sorted(value.items())}
        elif isinstance(value, tuple):
            value = list(value)
        entries[name] = value
    return entries


def contract_digest():
    """CONTRACT_DIGEST as the entries are now."""
    text = json.dumps(contract_entries(), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def config_value(document, dotted):
    """The value at a dotted key of a parsed game.config.yaml, or MISSING."""
    node = document
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return MISSING
        node = node[part]
    return node


# -- test projects ------------------------------------------------------------------------------

# Playwright projects in playwright.config.ts: `test:e2e` runs desktop and mobile, whose
# results are gameplay evidence (mobile is the responsive evidence); `test:verify` runs verify.
PLAYWRIGHT_PROJECTS = ("desktop", "mobile", "verify")
PLAYWRIGHT_MOBILE_PROJECT = "mobile"
# Vitest projects in vitest.workspace.ts. The sdk step runs its own suite in `unit`.
VITEST_PROJECTS = ("unit", "integration", "sdk")
VITEST_PROJECT_UNIT = "unit"

# The `@aspect` tag vocabulary: a Playwright test tagged `@restart` (or a recorded scenario
# with aspect `restart`) is gameplay evidence for that aspect. The Factory owns the words;
# a game's suites use them.
ASPECTS = ("boot", "loading", "start", "input", "core-loop", "progression", "game-over",
           "restart", "pause-resume", "responsive")
