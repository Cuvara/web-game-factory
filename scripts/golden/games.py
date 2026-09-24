"""The two golden games: what each run is steered with and what it must end in.

Data only. The harness, the replay developer and the tests all read the same record, so the
2D and the 3D run differ in these values and in nothing else - the workflow, the engine and
every module are the same code for both. That is what the pair proves: the Factory does not
branch on the renderer.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")

# The frozen market evidence both runs scan (a copy of workspace/research/snapshots taken for
# the golden runs; workspace/ itself is never read by them).
RESEARCH_CORPUS = os.path.join(FIXTURES, "research")
# The scan is "as of" this instant, so evidence freshness is the same every day it runs.
AS_OF = "2026-09-24T00:00:00Z"


class Game:
    def __init__(self, key, title_id, engine, example, scene_id, catalog, port):
        self.key = key                  # "2d" | "3d"
        self.title_id = title_id        # the run's --project, hence the repository name
        self.engine = engine            # what the design must declare and init must write
        self.example = example          # web-game-template examples/<example>
        self.scene_id = scene_id        # the id the ported scene publishes to #hud[data-scene]
        self.catalog = catalog          # the research step's candidate catalog
        self.port = port                # the port overlay, relative to the game repository

    @property
    def dimension(self):
        return self.key


GAMES = {
    "2d": Game(
        key="2d",
        title_id="tower-merge-rush",
        engine="pixijs",
        example="tower-merge-rush",
        scene_id="tower-merge-rush",
        catalog=os.path.join(FIXTURES, "2d", "catalog.yaml"),
        port="examples/tower-merge-rush/wgf-golden",
    ),
    "3d": Game(
        key="3d",
        title_id="neon-drift-arena",
        engine="threejs",
        example="neon-drift-arena",
        scene_id="neon-drift-arena",
        catalog=os.path.join(FIXTURES, "3d", "catalog.yaml"),
        port="examples/neon-drift-arena/wgf-golden",
    ),
}

# Every step of new-game, in order, and the outcome a golden run must reach at each. A step
# listed here that did not reach its outcome fails the run; so does one that is missing.
EXPECTED_STEPS = (
    ("research", "SUCCESS"),
    ("strategy", "SUCCESS"),
    ("strategy-review", "SUCCESS"),
    ("design", "SUCCESS"),
    ("tech-plan", "SUCCESS"),
    ("tech-plan-review", "SUCCESS"),
    ("init", "SUCCESS"),
    ("assets", "SUCCESS"),
    ("develop", "SUCCESS"),
    ("review", "SUCCESS"),
    ("sdk", "SUCCESS"),
    ("verify", "SUCCESS"),
    ("release", "SUCCESS"),
)


def game(key):
    try:
        return GAMES[key]
    except KeyError:
        raise ValueError(f"unknown golden game {key!r}; expected one of {', '.join(GAMES)}")
