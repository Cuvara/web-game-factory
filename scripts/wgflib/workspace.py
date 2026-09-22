"""Load instance data: a title, an opportunity, the portfolio policy, the reference files.

workspace/ holds what this factory has actually done, and core/ may never reference it. The
dependency runs one way, and it runs through here.
"""

import glob
import json
import os

from . import paths
from .yamllite import load_file

__all__ = [
    "Entity",
    "load_title",
    "load_opportunity",
    "load_portfolio_config",
    "load_scoring_model",
    "load_platform_profile",
    "all_title_states",
    "WorkspaceError",
]


class WorkspaceError(ValueError):
    """Instance data is missing or not shaped the way the schemas require."""


# Artifacts that are appended to rather than overwritten, and the directory each accumulates
# in. Re-scoring writes a new evaluation; a gate writes a new decision record. The newest
# file is the current one, and the older ones are why a ranking can be re-derived later.
APPEND_ONLY = {
    "evaluation": "evaluations",
    "decision-record": "decisions",
    "performance-review": "reviews",
}


def _read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class Entity:
    """One thing with a lifecycle: a title, or an opportunity.

    Carries its state cursor and whatever artifacts it has produced, loaded lazily so that
    asking about a guard does not require every artifact to exist.
    """

    def __init__(self, entity_id, directory, state):
        self.id = entity_id
        self.directory = directory
        self.state = state
        self.machine = state["machine"]
        self._artifacts = {}

    @property
    def state_path(self):
        return os.path.join(self.directory, "state.json")

    def artifact_path(self, artifact_type):
        """Where an artifact of this type lives, whether or not it exists yet.

        The state file's `artifacts` map wins when present - it is the record of what was
        actually written. Otherwise fall back to the layout workspace/README.md describes:
        append-only kinds accumulate in a directory and the newest file is the current one;
        everything else is a single `<type>.json` the producer overwrites.
        """
        recorded = (self.state.get("artifacts") or {}).get(artifact_type)
        if recorded:
            return os.path.join(self.directory, recorded)

        collection = APPEND_ONLY.get(artifact_type)
        if collection:
            existing = sorted(glob.glob(os.path.join(self.directory, collection, "*.json")))
            if existing:
                return existing[-1]
            return os.path.join(self.directory, collection)

        return os.path.join(self.directory, f"{artifact_type}.json")

    def has(self, artifact_type):
        return os.path.exists(self.artifact_path(artifact_type))

    def artifact(self, artifact_type):
        """Load an artifact, or raise WorkspaceError naming what is missing."""
        if artifact_type not in self._artifacts:
            path = self.artifact_path(artifact_type)
            if not os.path.exists(path):
                raise WorkspaceError(
                    f"{self.id} has no {artifact_type} at {paths.display(path)}"
                )
            self._artifacts[artifact_type] = _read_json(path)
        return self._artifacts[artifact_type]

    def maybe(self, artifact_type):
        return self.artifact(artifact_type) if self.has(artifact_type) else None

    def decisions(self):
        """Every decision-record under this entity, oldest filename first."""
        found = []
        for path in sorted(glob.glob(os.path.join(self.directory, "decisions", "*.json"))):
            found.append((path, _read_json(path)))
        return found

    def decision_for(self, gate_id):
        return [record for _path, record in self.decisions() if record.get("gate_id") == gate_id]

    def visits(self, state_id):
        """How many times this entity has entered `state_id`."""
        return sum(1 for visit in self.state.get("history", []) if visit["state"] == state_id)


def load_title(title_id):
    directory = os.path.join(paths.TITLES, title_id)
    state_path = os.path.join(directory, "state.json")
    if not os.path.exists(state_path):
        raise WorkspaceError(f"no title {title_id!r} at {paths.display(directory)}")
    return Entity(title_id, directory, _read_json(state_path))


def load_opportunity(opportunity_id):
    directory = os.path.join(paths.OPPORTUNITIES, opportunity_id)
    state_path = os.path.join(directory, "state.json")
    if not os.path.exists(state_path):
        # The worked example predates the state contract; an opportunity's own
        # opportunity.json still carries a `state` string, so fall back to it rather than
        # refusing to read a backlog that was written before the cursor existed.
        artifact_path = os.path.join(directory, "opportunity.json")
        if not os.path.exists(artifact_path):
            raise WorkspaceError(f"no opportunity {opportunity_id!r}")
        artifact = _read_json(artifact_path)
        synthesised = {
            "machine": "portfolio",
            "machine_version": "1.0.0",
            "opportunity_id": opportunity_id,
            "current_state": artifact.get("state", "discovered"),
            "history": [],
            "artifacts": {"opportunity": "opportunity.json"},
        }
        return Entity(opportunity_id, directory, synthesised)
    return Entity(opportunity_id, directory, _read_json(state_path))


def all_title_states():
    """Every title's state cursor, for portfolio-wide questions such as the WIP cap."""
    found = []
    for path in sorted(glob.glob(os.path.join(paths.TITLES, "*", "state.json"))):
        found.append((os.path.basename(os.path.dirname(path)), _read_json(path)))
    return found


def load_portfolio_config():
    path = os.path.join(paths.CONFIG, "portfolio.yaml")
    if not os.path.exists(path):
        raise WorkspaceError(f"{paths.display(path)} is missing")
    return load_file(path)


def load_scoring_model(model_id):
    """The newest version of a scoring model, or a specific file if given one."""
    if model_id.endswith(".yaml"):
        return load_file(os.path.join(paths.SCORING, model_id))
    candidates = sorted(glob.glob(os.path.join(paths.SCORING, f"{model_id}.v*.yaml")))
    if not candidates:
        raise WorkspaceError(f"no scoring model {model_id!r} in {paths.display(paths.SCORING)}")
    return load_file(candidates[-1])


def load_platform_profile(platform_id):
    path = os.path.join(paths.PLATFORMS, f"{platform_id}.yaml")
    if not os.path.exists(path):
        raise WorkspaceError(
            f"platform {platform_id!r} has no profile; adding one is a single new file at "
            f"{paths.display(path)}"
        )
    return load_file(path)
