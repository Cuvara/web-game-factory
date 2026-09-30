"""Research selects only what design can build: the catalog's `design_archetype`, held true.

scripts/wgf_discovery/archetypes.yaml declares, per concept, the design module's archetype
that designs it (`design_archetype`), or null. Research never selects a null one (it is kept
in the report as excluded, "not buildable"). This test makes the declaration a measurement:
for every catalog entry, the real research, strategy and design steps run on that concept
alone, and

  * a declared entry's design passes consistency, built from exactly the declared archetype;
  * a null entry's design fails consistency - so when the design module learns a concept,
    this test fails until the catalog declares it.

In 2.4.1 nothing tied the two, and 9 of the 11 concepts research could select failed at
design (concept_mechanics_carried, design_adds_no_foreign_mechanic): a real new-game run
reached design only when the evidence happened to favour one of the other two.

Each entry runs `wgf research` then `wgf plan --run` in a scratch project (WGF_PROJECT_DIR),
offline, on the fixture evidence corpus at its fixed date; G2 and G3 are auto-approved by the
project's config. Nothing past plan runs.

    python -m unittest scripts.tests.test_research_to_design
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from wgf_design import archetypes as design_archetypes  # noqa: E402
from wgf_discovery.step import CATALOG  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

CORPUS = os.path.join(HERE, "fixtures", "discovery", "corpus")
AS_OF = "2026-09-23T00:00:00Z"
ENGINE = os.path.join(SCRIPTS, "wgf.py")


def catalog_entries():
    """(id, entry text) per archetype, and the catalog's header."""
    with open(CATALOG, encoding="utf-8") as handle:
        text = handle.read()
    head, _, body = text.partition("archetypes:\n")
    chunks = re.split(r"(?m)^(?=  - id: )", body)
    return head, [(re.match(r"  - id: (\S+)", c).group(1), c) for c in chunks
                  if c.startswith("  - id: ")]


class ResearchToDesign(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp(prefix="wgf-research-design-")
        cls.addClassCleanup(shutil.rmtree, cls.base, ignore_errors=True)
        cls.declared = {a["id"]: a["design_archetype"]
                        for a in load_file(CATALOG)["archetypes"]}
        cls.head, cls.entries = catalog_entries()

    def run_concept(self, archetype_id, entry):
        """Research, strategy and design on this one concept. Its design_archetype line is
        dropped, so research does not screen it out and design is what is measured."""
        project = os.path.join(self.base, archetype_id)
        os.makedirs(os.path.join(project, "workspace", "config"))
        catalog = os.path.join(project, "catalog.yaml")
        with open(catalog, "w", encoding="utf-8") as handle:
            handle.write(self.head + "archetypes:\n"
                         + re.sub(r"(?m)^    design_archetype: .*\n", "", entry))
        with open(os.path.join(project, "workspace", "config", "factory.yaml"), "w",
                  encoding="utf-8") as handle:
            handle.write("factory:\n"
                         "  checkpoints:\n    auto_approve: [G2, G3]\n"
                         f"  discovery:\n    catalog: {json.dumps(catalog)}\n"
                         f"    corpus: {json.dumps(CORPUS)}\n    as_of: \"{AS_OF}\"\n"
                         f"    backlog: {json.dumps(os.path.join(project, 'none'))}\n")
        env = {k: v for k, v in os.environ.items() if not k.startswith("WGF_")}
        env["WGF_PROJECT_DIR"] = project

        def wgf(*argv):
            return subprocess.run([sys.executable, ENGINE, *argv], cwd=project, env=env,
                                  capture_output=True, text=True, timeout=300)

        research = wgf("research", "--json")
        self.assertEqual(research.returncode, 0, research.stderr[-1500:] + research.stdout[-800:])
        run_id = json.loads(research.stdout.splitlines()[0])["run_id"]
        wgf("plan", "--run", run_id)
        run = os.path.join(project, ".factory", "workflows", run_id)
        with open(os.path.join(run, "state.json"), encoding="utf-8") as handle:
            state = json.load(handle)

        def artifact(kind):
            directory = os.path.join(run, "artifacts", kind)
            with open(os.path.join(directory, sorted(os.listdir(directory))[-1]),
                      encoding="utf-8") as handle:
                return json.load(handle)
        return state, artifact

    def test_each_declaration_matches_what_design_does(self):
        self.assertEqual(sorted(self.declared), sorted(i for i, _ in self.entries))
        self.assertTrue(any(self.declared.values()), "at least one concept must be buildable")
        for archetype_id, entry in self.entries:
            with self.subTest(concept=archetype_id,
                              declared=self.declared[archetype_id]):
                state, artifact = self.run_concept(archetype_id, entry)
                design = state["steps"]["design"]["status"]
                breached = [r["criterion_id"] for r in
                            artifact("game-design")["consistency"]["rule_results"]
                            if r.get("breached")]
                chosen, _why = design_archetypes.select(artifact("title-strategy"))
                if self.declared[archetype_id]:
                    self.assertEqual(design, "SUCCESS", breached)
                    self.assertEqual(state["steps"]["tech-plan-review"]["status"], "SUCCESS")
                    self.assertEqual(chosen, self.declared[archetype_id])
                else:
                    self.assertEqual(design, "FAILED",
                                     f"design now builds {archetype_id} with {chosen}: "
                                     "declare design_archetype in the catalog")
                    self.assertTrue(breached)


if __name__ == "__main__":
    unittest.main()
