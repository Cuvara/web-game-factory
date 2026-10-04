"""Research selects only what design can build: the catalog's two roads, held true.

scripts/wgf_discovery/archetypes.yaml declares, per concept, how the design module builds it:
a `design_archetype` (a hand-written shape in scripts/wgf_design/archetypes.py), a
`genre_model` (a family of core/reference/genre-models.yaml, which the genre seed author
designs from), or neither - and then it is not buildable, research never selects it, and it
stays in the report as excluded. This test makes the declaration a measurement: for every
catalog entry, the real research, strategy and design steps run on that concept alone, and

  * an entry with a `design_archetype` gets a design built from exactly that archetype;
  * an entry with only a `genre_model` gets a design of exactly that genre family, carrying at
    least the family's `units.min_mvp` content units, with no content rule breached and the
    content recorded in `research.applied`;
  * an entry with neither fails design - so when the design module learns a concept, this test
    fails until the catalog declares it.

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
from wgf_design import consistency  # noqa: E402
from wgf_discovery.step import CATALOG  # noqa: E402
from wgflib import genre_models  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

CORPUS = os.path.join(HERE, "fixtures", "discovery", "corpus")
AS_OF = "2026-09-23T00:00:00Z"
ENGINE = os.path.join(SCRIPTS, "wgf.py")
FAMILIES = genre_models.load()["families"]


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
        cls.declared = {a["id"]: (a["design_archetype"], a.get("genre_model"))
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

    @staticmethod
    def why(breached, design, artifact):
        """The breached rules, and - for the two concept rules - which mechanic words the
        design and the strategy disagree on. A genre family's seed wording and a catalog
        entry's concept wording have to name the same mechanics, and when they do not this is
        where it shows: `uncarried` a mechanic the concept names and the design does not
        build, `foreign` a mechanic the design builds that nothing implies."""
        if not {"concept_mechanics_carried", "design_adds_no_foreign_mechanic"} & set(breached):
            return breached
        view = consistency.concept_view(design, artifact("title-strategy"))
        return (f"{breached}: uncarried {view['uncarried']}, foreign {view['foreign']} "
                f"(the genre model's seed wording and the catalog entry's concept wording "
                f"name different mechanics)")

    def test_each_declaration_matches_what_design_does(self):
        self.assertEqual(sorted(self.declared), sorted(i for i, _ in self.entries))
        self.assertTrue(any(a for a, _ in self.declared.values()),
                        "at least one concept must be buildable from a design archetype")
        self.assertTrue(any(m for _, m in self.declared.values()),
                        "at least one concept must be buildable from a genre model")
        for archetype_id, entry in self.entries:
            archetype, family = self.declared[archetype_id]
            with self.subTest(concept=archetype_id, design_archetype=archetype,
                              genre_model=family):
                state, artifact = self.run_concept(archetype_id, entry)
                design = state["steps"]["design"]["status"]
                body = artifact("game-design")
                breached = [r["criterion_id"] for r in body["consistency"]["rule_results"]
                            if r.get("breached")]
                strategy = artifact("title-strategy")
                rendering = design_archetypes.dimension_of(strategy)
                if archetype and rendering and \
                        design_archetypes.ARCHETYPES[archetype]["dimension"] != rendering:
                    # The catalog builds this concept in another dimension than it renders
                    # (endless-runner: rendering 3d, lane-runner 2d). That is the catalog's
                    # explicit declaration; without it, design never crosses the dimension
                    # the strategy states by a keyword match (F09) - it picks within it.
                    chosen, _why = design_archetypes.select(strategy)
                    self.assertEqual(design_archetypes.ARCHETYPES[chosen]["dimension"],
                                     rendering)
                    continue
                chosen, _why = design_archetypes.select(strategy)
                if archetype:
                    self.assertEqual(design, "SUCCESS", breached)
                    self.assertEqual(state["steps"]["tech-plan-review"]["status"], "SUCCESS")
                    self.assertEqual(chosen, archetype)
                elif family:
                    # The genre seed author designs it from the family's own model. No
                    # hand-written archetype is involved, and none is expected to match.
                    self.assertEqual(design, "SUCCESS", self.why(breached, body, artifact))
                    self.assertEqual(state["steps"]["tech-plan-review"]["status"], "SUCCESS")
                    self.assertEqual(body["genre"]["family"], family)
                    units = [u for u in body["build_spec"]["content"]["units"]
                             if u["tier"] == "mvp"]
                    self.assertGreaterEqual(len(units), FAMILIES[family]["units"]["min_mvp"])
                    self.assertEqual([r for r in breached if r.startswith("content.")], [])
                    applied = {e["field"] for e in body["research"]["applied"]}
                    self.assertIn("build_spec.content", applied)
                    self.assertIn("genre.family", applied)
                else:
                    # Research declares the shape unbuildable, so in production it is never
                    # selected (a capability gap). Stripped of the declaration, design falls
                    # back to the nearest hand-coded archetype: either the consistency rules
                    # refuse it as a different game, or the artifact itself records that the
                    # archetype was a fallback research did not name - never the concept's
                    # own game passed off as designed.
                    if design == "FAILED":
                        self.assertTrue(breached)
                    else:
                        applied = {e["field"]: e for e in body["research"]["applied"]}
                        self.assertEqual(applied["archetype"]["source"], "default",
                                         f"design built {archetype_id} with {chosen} as if "
                                         "research had chosen it: declare design_archetype "
                                         "or genre_model in the catalog")
                        self.assertIn("research named no buildable design archetype",
                                      applied["archetype"]["detail"])


if __name__ == "__main__":
    unittest.main()
