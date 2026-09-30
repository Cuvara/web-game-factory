"""The adapter surfaces name the same things in all four places that list them.

core/bindings/adapter-binding.yaml says WHAT an adapter must cover; scripts/gen-adapters.sh
holds the tables the surfaces are generated from; the generated files are on disk; and each
plugin's CONFORMANCE.md maps every surface to its file. Nothing else ties the four together -
the generator does not read the binding, and never deletes a file - so a surface added to
one and forgotten in another drifts silently. This test is that tie, by id only: wording,
order and whitespace are not contractual here, and are not compared.

It also holds the workflow entry points (`workflows:` in the binding, commands/<id>.md) to
what makes them entry points and not a second orchestrator: they point at the workflow and
at bin/wgf, and they never answer a gate.

Run from the repository root:

    python -m unittest scripts.tests.test_adapter_binding
"""

import importlib.util
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from wgflib.workflow.definition import load_definition  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

PLUGINS = ("claude-web-game-plugin", "codex-web-game-plugin")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def generator_rows(table):
    """The rows of one `<table>=( "..." )` array in gen-adapters.sh, split on `|`."""
    text = read("scripts", "gen-adapters.sh")
    match = re.search(rf"^{table}=\(\n(.*?)^\)", text, re.M | re.S)
    if match is None:
        raise AssertionError(f"gen-adapters.sh has no `{table}=(` table")
    return [line.strip()[1:-1].split("|")
            for line in match.group(1).splitlines() if line.strip().startswith('"')]


def conformance_section(plugin, heading):
    """The backticked first cells of the table under the `## <heading>` section."""
    text = read(plugin, "CONFORMANCE.md")
    match = re.search(rf"^## {re.escape(heading)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if match is None:
        raise AssertionError(f"{plugin}/CONFORMANCE.md has no '## {heading}' section")
    rows = re.findall(r"^\|\s*`([^`]+)`\s*\|\s*(?:`([^`]+)`|—)", match.group(1), re.M)
    return {first: path for first, path in rows}


class AdapterBindingDrift(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binding = load_file(os.path.join(ROOT, "core", "bindings", "adapter-binding.yaml"))

    def ids(self, kind):
        return sorted(entry["id"] for entry in self.binding.get(kind) or [])

    def test_generator_tables_match_the_binding(self):
        for kind in ("agents", "commands", "skills", "workflows"):
            with self.subTest(kind=kind):
                self.assertEqual(sorted(row[0] for row in generator_rows(kind)), self.ids(kind))

    def test_generated_workflow_runs_the_binding_workflow(self):
        runs = {entry["id"]: entry["runs"] for entry in self.binding["workflows"]}
        for wid, path, _summary in generator_rows("workflows"):
            self.assertEqual(path, runs[wid])

    def test_every_surface_is_on_disk_and_nothing_else_is(self):
        expected_commands = ({f"wgf-{cid}.md" for cid in self.ids("commands")}
                             | {f"{wid}.md" for wid in self.ids("workflows")})
        for plugin in PLUGINS:
            with self.subTest(plugin=plugin):
                self.assertEqual(set(os.listdir(os.path.join(ROOT, plugin, "commands"))),
                                 expected_commands)
                self.assertEqual(set(os.listdir(os.path.join(ROOT, plugin, "agents"))),
                                 {f"{aid}.md" for aid in self.ids("agents")})
                self.assertEqual(
                    {d for d in os.listdir(os.path.join(ROOT, plugin, "skills"))
                     if os.path.isfile(os.path.join(ROOT, plugin, "skills", d, "SKILL.md"))},
                    set(self.ids("skills")))

    def test_conformance_maps_every_surface_to_its_file(self):
        sections = {
            "Commands": {f"/wgf-{cid}": f"commands/wgf-{cid}.md" for cid in self.ids("commands")},
            "Workflow entry points": {f"/{wid}": f"commands/{wid}.md"
                                      for wid in self.ids("workflows")},
            "Skills": {sid: f"skills/{sid}/SKILL.md" for sid in self.ids("skills")},
        }
        for plugin in PLUGINS:
            for heading, expected in sections.items():
                with self.subTest(plugin=plugin, section=heading):
                    listed = conformance_section(plugin, heading)
                    self.assertEqual(sorted(listed), sorted(expected))
                    for surface, path in expected.items():
                        self.assertEqual(listed[surface], f"{plugin}/{path}")
                        self.assertTrue(os.path.isfile(os.path.join(ROOT, plugin, path)))


class WorkflowEntryPoints(unittest.TestCase):
    """What keeps an entry point a pointer to the engine rather than an orchestrator."""

    @classmethod
    def setUpClass(cls):
        binding = load_file(os.path.join(ROOT, "core", "bindings", "adapter-binding.yaml"))
        cls.entries = binding["workflows"]

    def surfaces(self):
        for entry in self.entries:
            for plugin in PLUGINS:
                yield entry, plugin, read(plugin, "commands", f"{entry['id']}.md")

    def test_points_at_the_workflow_and_the_engine(self):
        for entry, plugin, text in self.surfaces():
            with self.subTest(plugin=plugin, workflow=entry["id"]):
                self.assertIn(f"`{entry['runs']}`", text)
                self.assertIn(f"bin/wgf {entry['id']} ", text)
                self.assertIn("bin/wgf resume <run-id>", text)
                self.assertIn("bin/wgf status <run-id>", text)

    def test_restates_no_step_order(self):
        """The workflow file is the only step order: an entry point names no chain of steps.
        `develop` is the one step it may name, for the handoff it must not answer."""
        for entry, plugin, text in self.surfaces():
            steps = {step.id for step in load_definition(os.path.join(ROOT, entry["runs"])).steps}
            named = set(re.findall(r"`([a-z][a-z0-9-]*)`", text)) & steps
            with self.subTest(plugin=plugin, workflow=entry["id"]):
                self.assertLessEqual(named, {"develop"})
                self.assertNotRegex(text, r"(→|->)")

    def test_never_answers_a_gate(self):
        for entry, plugin, text in self.surfaces():
            with self.subTest(plugin=plugin, workflow=entry["id"]):
                self.assertIn("Never run `bin/wgf decide`", text)
                for flag in ("--decision", "--note", "decide", "--budget-sessions",
                             "--budget-cost", "--workflow", "--config"):
                    self.assertRegex(text, rf"Refuse[^#]*`{re.escape(flag)}`")
                # Every command that answers a checkpoint is either forbidden or handed to
                # the user to type (`! ...`), never an instruction to run it here.
                for line in text.splitlines():
                    if re.search(r"wgf decide|--decision (?!`)|--decision done", line):
                        self.assertTrue(
                            line.lstrip().startswith(("Never run", "Refuse", "`--decision`"))
                            or "`! bin/wgf" in line,
                            f"{plugin}: answers a checkpoint: {line.strip()}")

    def test_claude_surface_is_user_invoked_only(self):
        for entry in self.entries:
            text = read("claude-web-game-plugin", "commands", f"{entry['id']}.md")
            front = text.split("---")[1]
            with self.subTest(workflow=entry["id"]):
                self.assertRegex(front, r"(?m)^description: \S")
                self.assertRegex(front, r"(?m)^argument-hint: \S")
                self.assertRegex(front, r"(?m)^disable-model-invocation: true$")
                self.assertIn("$ARGUMENTS", text)


class BindingWorkflowIntegrity(unittest.TestCase):
    """check-integrity.py's check of each `workflows:` entry against its workflow file."""

    ENTRY = ("workflows:\n  - id: new-game\n"
             "    runs: core/workflows/new-game.workflow.yaml\n"
             "    role: null\n    gates: [G2, G3, G4]\n")

    def setUp(self):
        cwd = os.getcwd()
        os.chdir(ROOT)
        self.addCleanup(os.chdir, cwd)
        spec = importlib.util.spec_from_file_location(
            "check_integrity_binding", os.path.join(SCRIPTS, "check-integrity.py"))
        self.ci = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ci)
        self.real = self.ci.read(os.path.join("core", "bindings", "adapter-binding.yaml"))
        self.assertIn(self.ENTRY, self.real)
        self.roles = self.ci.load_roles()

    def check(self, entry):
        text = self.real.replace(self.ENTRY, entry)
        real_read = self.ci.read
        self.ci.read = lambda path: (text if path == "core/bindings/adapter-binding.yaml"
                                     else real_read(path))
        try:
            return self.ci.check_binding_workflows(self.roles), self.ci.ERRORS
        finally:
            self.ci.read = real_read

    def test_the_shipped_binding_passes(self):
        ids, errors = self.check(self.ENTRY)
        self.assertEqual(ids, ["new-game"])
        self.assertEqual(errors, [])

    def test_a_broken_entry_is_an_error(self):
        cases = {
            "file named for another id": self.ENTRY.replace(
                "runs: core/workflows/new-game", "runs: core/workflows/other"),
            "missing file": self.ENTRY.replace("id: new-game", "id: nope").replace(
                "new-game.workflow", "nope.workflow"),
            "outside core": self.ENTRY.replace("runs: core/", "runs: workspace/"),
            "no runs": self.ENTRY.replace("    runs: core/workflows/new-game.workflow.yaml\n", ""),
            "gates drift": self.ENTRY.replace("[G2, G3, G4]", "[G2, G4]"),
            "gate the workflow lacks": self.ENTRY.replace("[G2, G3, G4]", "[G2, G3, G4, G6]"),
            "unknown role": self.ENTRY.replace("role: null", "role: nobody"),
        }
        for name, entry in cases.items():
            with self.subTest(case=name):
                del self.ci.ERRORS[:]
                _ids, errors = self.check(entry)
                self.assertTrue(errors, f"{name}: accepted")


if __name__ == "__main__":
    unittest.main()
