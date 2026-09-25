"""The template contract (wgflib.template_contract), held against the pinned template.

Every entry - path, npm script, node CLI and its flags, template-written output, game.config
key, Playwright and Vitest project - is checked in a checkout of the commit pinned in
workspace/config/template.lock.json (wgflib.template.checkout, never the sibling working copy).
A failure here means the pinned template dropped or renamed something a Factory step calls:
fix the contract and the step together, or move the pin back.

The modules that read the contract are also checked for a raw copy of one of its strings, which
is how a contract silently forks again.

Run from the web-game-factory repository root:

    python -m unittest scripts.tests.test_template_contract    (or discover scripts/tests)
"""

import ast
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import pinned_template  # noqa: E402

from wgflib import template_contract as contract  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

_PINNED, _PINNED_WHY = pinned_template.checkout()


def _read(root, relative):
    with open(os.path.join(root, *relative.split("/")), encoding="utf-8") as handle:
        return handle.read()


def _tree_text(root, relative, suffixes=(".mjs", ".js", ".ts", ".json")):
    """Every matching file under `relative`, concatenated (node_modules skipped)."""
    parts = []
    for directory, dirnames, filenames in os.walk(os.path.join(root, *relative.split("/"))):
        dirnames[:] = sorted(d for d in dirnames if d != "node_modules")
        for name in sorted(filenames):
            if name.endswith(suffixes):
                with open(os.path.join(directory, name), encoding="utf-8",
                          errors="replace") as handle:
                    parts.append(handle.read())
    return "\n".join(parts)


class ContractShapeTest(unittest.TestCase):
    """The contract itself, without the template."""

    def test_version_is_semver(self):
        self.assertRegex(contract.CONTRACT_VERSION, r"^[0-9]+\.[0-9]+\.[0-9]+$")

    def test_no_duplicate_paths(self):
        paths = [p for p, _ in contract.INFRASTRUCTURE + contract.SOURCE_PATHS]
        self.assertEqual(len(paths), len(set(paths)))

    def test_every_forwarded_script_and_output_producer_is_listed(self):
        for script in contract.SCRIPT_FLAGS:
            self.assertIn(script, contract.NPM_SCRIPTS)
        for output, (producer, owner) in contract.OUTPUTS.items():
            self.assertIn(owner, ("template", "factory"), output)
            if owner == "template" and not producer.startswith("scripts/"):
                self.assertIn(producer, contract.NPM_SCRIPTS, output)

    def test_helpers(self):
        self.assertEqual(contract.facts_path("poki"), "build/facts/poki.json")
        self.assertEqual(contract.assertions_path("poki"), "build/assertions/poki.json")
        self.assertEqual(contract.release_path("r2", contract.RELEASE_MANIFEST),
                         ("release", "r2", "manifest.json"))
        self.assertEqual(contract.platform_profile_path("y8"), "config/platforms/y8.yaml")
        self.assertEqual(contract.config_value({"a": {"b": []}}, "a.b"), [])
        self.assertIs(contract.config_value({"a": {}}, "a.b"), contract.MISSING)
        self.assertIs(contract.config_value({"a": 1}, "a.b"), contract.MISSING)

    def test_infrastructure_is_the_list_init_always_checked(self):
        """The list init required before the contract existed, entry for entry and in order:
        deriving the renderer packages from the engines changed nothing."""
        self.assertEqual(contract.ENGINES, ("pixijs", "threejs"))
        self.assertEqual([p for p, _ in contract.INFRASTRUCTURE], [
            "package.json", "pnpm-workspace.yaml", "pnpm-lock.yaml", "tsconfig.base.json",
            "vite.config.ts", "vitest.workspace.ts", "playwright.config.ts", "game.config.yaml",
            "packages/game-core/", "packages/platform-sdk/", "packages/analytics-sdk/",
            "packages/pixi-framework/", "packages/three-framework/", "config/platforms/",
            "scripts/_shared.mjs", "scripts/verify/", "scripts/release/", "scripts/publish/",
            "tests/unit/", "tests/integration/", "tests/e2e/", "tests/verify/",
            ".github/workflows/ci.yml", ".github/workflows/build.yml",
            ".github/workflows/verify.yml", ".github/workflows/release.yml",
            ".github/workflows/publish.yml", ".github/workflows/campaign.yml"])

    def test_modules_keep_their_public_names(self):
        """Behaviour-preserving: the names modules exported before the contract existed
        still exist, and are the contract's values."""
        from wgf_init import infrastructure
        from wgf_sdk import evidence
        from wgf_verification import session
        from wgf_verification.checks import gameplay, platform
        self.assertIs(infrastructure.TEMPLATE_INFRASTRUCTURE, contract.INFRASTRUCTURE)
        self.assertEqual(infrastructure.GAME_CONFIG, "game.config.yaml")
        self.assertEqual(infrastructure.ENGINES, ("pixijs", "threejs"))
        self.assertEqual(platform.RUNTIME_FACTS, "build/runtime-facts.json")
        self.assertEqual(platform.COLLECT_FACTS, "scripts/verify/collect-facts.mjs")
        self.assertEqual(platform.EVALUATE, "scripts/verify/evaluate-assertions.mjs")
        self.assertEqual(session.DEFAULT_SESSION_FILE,
                         "build/verification/gameplay-session.json")
        self.assertEqual(gameplay.RepositoryPlaywrightDriver.report_path,
                         "build/verification/playwright-e2e.json")
        self.assertIs(gameplay.ASPECTS, contract.ASPECTS)
        self.assertEqual(evidence.REPORT_PATH, os.path.join("build", "sdk-conformance.json"))
        self.assertEqual(evidence.COMMANDS["conformance"], ("pnpm", "sdk:conformance"))
        self.assertEqual(evidence.COMMANDS["browser"], ("pnpm", "test:sdk:browser"))


@unittest.skipUnless(_PINNED, _PINNED_WHY)
class PinnedTemplateDriftTest(unittest.TestCase):
    """Every contract entry, in the pinned template."""

    @classmethod
    def setUpClass(cls):
        cls.root = _PINNED
        with open(os.path.join(cls.root, contract.PACKAGE_JSON), encoding="utf-8") as handle:
            cls.package = json.load(handle)
        cls.scripts = cls.package.get("scripts") or {}

    def test_infrastructure_is_present(self):
        from wgf_init.infrastructure import missing_infrastructure
        self.assertEqual(missing_infrastructure(self.root), [],
                         "the pinned template lacks paths init requires")

    def test_source_paths_exist(self):
        missing = []
        for path, _purpose in contract.SOURCE_PATHS:
            full = os.path.join(self.root, *path.rstrip("/").split("/"))
            present = os.path.isdir(full) if path.endswith("/") else os.path.isfile(full)
            if not present:
                missing.append(path)
        self.assertEqual(missing, [])

    def test_optional_paths_exist_in_the_template(self):
        self.assertTrue(os.path.isfile(os.path.join(self.root, contract.CHANGELOG)))

    def test_package_manager(self):
        self.assertTrue(str(self.package.get("packageManager", ""))
                        .startswith(contract.PACKAGE_MANAGER + "@"))
        self.assertTrue(os.path.isfile(os.path.join(self.root, contract.PNPM_LOCK)))

    def test_npm_scripts_exist(self):
        missing = sorted(s for s in contract.NPM_SCRIPTS if s not in self.scripts)
        self.assertEqual(missing, [], "package.json scripts the Factory runs are gone")

    def test_forwarded_flags_are_accepted(self):
        for script, flags in contract.SCRIPT_FLAGS.items():
            command = self.scripts.get(script, "")
            found = re.search(r"\bnode\s+(\S+\.mjs)\b", command)
            self.assertIsNotNone(found, f"{script} does not run a node CLI: {command!r}")
            text = _read(self.root, found.group(1))
            for flag in flags:
                self.assertIn(flag, text, f"{found.group(1)} (behind {script}) never "
                                          f"mentions {flag}")

    def test_exec_tools_are_dependencies(self):
        declared = dict(self.package.get("devDependencies") or {})
        declared.update(self.package.get("dependencies") or {})
        for tool, package in contract.EXEC_TOOLS.items():
            self.assertIn(package, declared, f"`{contract.PACKAGE_MANAGER} exec {tool}`")

    def test_node_clis_exist_and_take_their_flags(self):
        for cli, flags in contract.NODE_CLIS.items():
            path = os.path.join(self.root, *cli.split("/"))
            self.assertTrue(os.path.isfile(path), cli)
            text = _read(self.root, cli)
            usage = "\n".join(line for line in text.splitlines() if "usage" in line.lower())
            self.assertTrue(usage, f"{cli} has no usage text")
            for flag in flags:
                self.assertIn(flag, usage, f"{cli}'s usage text does not mention {flag}")

    def test_template_written_outputs(self):
        haystack = "\n".join((_read(self.root, contract.PACKAGE_JSON),
                              _tree_text(self.root, "scripts"),
                              _tree_text(self.root, "tests/verify")))
        for output, (producer, owner) in contract.OUTPUTS.items():
            if owner != "template":
                continue
            last = output.rsplit("/", 1)[-1]
            needle = output.split("<", 1)[0] if "<" in last else last
            self.assertIn(needle, haystack, f"nothing in the template writes {output} "
                                            f"(expected from {producer})")

    def test_game_config_keys(self):
        document = load_file(os.path.join(self.root, contract.GAME_CONFIG)) or {}
        missing = [k for k in contract.GAME_CONFIG_KEYS
                   if contract.config_value(document, k) is contract.MISSING]
        self.assertEqual(missing, [])
        self.assertIn(contract.config_value(document, "engine.type"), contract.ENGINES)
        for entry in document["platforms"]:
            self.assertEqual(sorted(entry), sorted(contract.PLATFORM_ENTRY_KEYS), entry)
            self.assertIn(entry["role"], contract.PLATFORM_ROLES)

    def test_every_engine_has_its_renderer_and_rendering_code(self):
        # The naming convention renderer_package/rendering_dir encode, held against the pin.
        for engine in contract.ENGINES:
            for path in (contract.renderer_package(engine), contract.rendering_dir(engine)):
                full = os.path.join(self.root, *path.rstrip("/").split("/"))
                self.assertTrue(os.path.isdir(full) and os.listdir(full), f"{engine}: {path}")

    def test_playwright_projects(self):
        text = _read(self.root, contract.PLAYWRIGHT_CONFIG)
        for project in contract.PLAYWRIGHT_PROJECTS:
            self.assertRegex(text, r"name:\s*[\"']" + re.escape(project) + r"[\"']",
                             f"{contract.PLAYWRIGHT_CONFIG} has no project {project}")
        self.assertIn(contract.PLAYWRIGHT_MOBILE_PROJECT, contract.PLAYWRIGHT_PROJECTS)
        self.assertIn(f"--project {contract.PLAYWRIGHT_MOBILE_PROJECT}",
                      self.scripts.get(contract.SCRIPT_TEST_E2E, ""))
        self.assertIn("--project verify", self.scripts.get(contract.SCRIPT_TEST_VERIFY, ""))

    def test_vitest_projects(self):
        text = _read(self.root, contract.VITEST_WORKSPACE)
        for project in contract.VITEST_PROJECTS:
            self.assertRegex(text, r"name:\s*[\"']" + re.escape(project) + r"[\"']",
                             f"{contract.VITEST_WORKSPACE} has no project {project}")
        self.assertIn(contract.VITEST_PROJECT_UNIT, contract.VITEST_PROJECTS)


# -- no module keeps its own copy of a contract string -------------------------------------------

# The modules that read the contract (M10). wgf_develop is not yet among them.
_MIGRATED = (
    "wgf_init/infrastructure.py",
    "wgf_sdk/evidence.py",
    "wgf_sdk/runner.py",
    "wgf_release/step.py",
    "wgf_release/package.py",
)
_MIGRATED_TREES = ("wgf_verification",)


def _distinctive():
    """Contract strings specific enough that a literal copy can only be a duplicate: paths,
    output paths and namespaced script names. Plain words (build, lint, dist, release,
    pnpm, an aspect name) are also check categories, config keys and roles, so they are
    not listed."""
    strings = {p for p, _ in contract.INFRASTRUCTURE + contract.SOURCE_PATHS}
    strings |= {p.rstrip("/") for p in strings}
    strings |= {contract.PLATFORM_PROFILES_DIR, contract.CHANGELOG, contract.RUNTIME_FACTS,
                contract.SDK_CONFORMANCE_REPORT, contract.FACTS_DIR, contract.ASSERTIONS_DIR,
                contract.GAMEPLAY_SESSION, contract.PLAYWRIGHT_E2E_REPORT,
                contract.RELEASE_PACKAGES, contract.RELEASE_MANIFEST, contract.RELEASE_CHECKSUMS}
    strings |= set(contract.NODE_CLIS)
    strings |= {s for s in contract.NPM_SCRIPTS if ":" in s}
    return strings


def _literals(path):
    """(line, value) of every string constant in `path` that is not a docstring."""
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), path)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [(node.lineno, node.value) for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstrings]


def _migrated_files():
    files = [os.path.join(SCRIPTS, *m.split("/")) for m in _MIGRATED]
    for tree in _MIGRATED_TREES:
        for directory, dirnames, filenames in os.walk(os.path.join(SCRIPTS, tree)):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            files += [os.path.join(directory, f) for f in sorted(filenames) if f.endswith(".py")]
    return files


class NoDuplicateLiteralsTest(unittest.TestCase):
    def test_migrated_modules_import_instead_of_copying(self):
        distinctive = _distinctive()
        found = []
        for path in _migrated_files():
            for line, value in _literals(path):
                if value in distinctive:
                    found.append(f"{os.path.relpath(path, SCRIPTS)}:{line}: {value!r}")
        self.assertEqual(found, [], "import these from wgflib.template_contract")

    def test_the_scan_would_see_a_copy(self):
        self.assertIn((1, "scripts/verify/collect-facts.mjs"), _literals_of(
            'X = "scripts/verify/collect-facts.mjs"\n'))
        self.assertEqual(_literals_of('"""build/runtime-facts.json"""\n'), [])


def _literals_of(source):
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
    try:
        return _literals(handle.name)
    finally:
        os.remove(handle.name)


if __name__ == "__main__":
    unittest.main()
