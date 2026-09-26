"""The LIVE build: the golden 2D pipeline with real agent hosts as developer and reviewer.

    WGF_LIVE_AGENT=1 python -m unittest test_live_loop -v      (from scripts/tests; costs money)
    python3 scripts/golden/live.py config --workdir DIR [--human-gates]
        writes DIR/factory.yaml for `bin/wgf new-game --config DIR/factory.yaml
        --store DIR/factory-store --project tower-merge-rush`, and DIR/evidence/live-agents.json

A golden run proves the pipeline with a replayed developer and a scripted reviewer. This asks
the question those cannot answer: does a real developer -> reviewer loop converge on a game
the developer builds from the Factory's own brief? It is the golden 2D run - the frozen
research inputs, so the Factory's strategy, design and tech plan come out the same every
time, the pinned template, the real develop checks, sdk, verify, G4, release - with:

- the developer and the reviewer that workspace/config/factory.yaml documents, verbatim,
  from develop visit 1: the developer builds the game from scratch from the brief, with the
  develop step's own prompt, and the reviewer judges it against the design with the review
  step's own. No replay, no planted defect, no prompt written for the test;
- no refusing proxy: the hosts need their API, and the developer runs pnpm online.

Why from scratch. The v2.0.1 candidate first tried the golden replay with a defect planted in
it. The live reviewer rejected that build on six design-fidelity blockers and never reached
the defect: the golden 2D design is the design module's merge-puzzle archetype (a 7x7
swap-and-match level game), and the replayed game is Tower Merge Rush, a different game. The
golden runs pass because their scripted reviewer does not judge design fidelity. A build made
from the brief is the only fixture a competent reviewer can legitimately approve.

`record` - both argvs, verbatim, where they came from, and the host's version - goes into
the evidence, so a paid run can be reproduced from the repository alone.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(HERE))

from golden import games, harness  # noqa: E402
from wgflib import paths, procs  # noqa: E402
from wgflib.yamllite import load  # noqa: E402

FACTORY_YAML = os.path.join(paths.CONFIG, "factory.yaml")
GAME = "2d"


class LiveSetupError(Exception):
    pass


def shipped_agent_examples(path=FACTORY_YAML):
    """The documented developer and reviewer blocks of factory.yaml, uncommented: the
    `    # developer:` / `    # reviewer:` blocks (the first of each, never the opt-ins)."""
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    def block(key):
        try:
            start = next(i for i, line in enumerate(lines) if line == f"    # {key}:")
        except StopIteration:
            raise LiveSetupError(f"{path} documents no `{key}:` example") from None
        out = [f"{key}:"]
        for line in lines[start + 1:]:
            if not line.startswith("    #   "):
                break
            out.append(line[len("    # "):])
        return load("\n".join(out))[key]

    return block("developer"), block("reviewer")


def host_version(argv0):
    """`<host> --version`, through wgflib.procs like every child the Factory starts."""
    try:
        result = procs.run([argv0, "--version"], cwd=paths.ROOT, timeout=60)
    except OSError as exc:
        return f"unavailable: {exc}"
    return result.tail(3).strip() if result.ok else f"unavailable: {result.tail(3).strip()}"


def build_live_config(game, workdir, template_dir=None, examples=None, human_gates=False):
    """The golden configuration with the documented agent hosts in it, from visit 1.
    Returns (config, record). `human_gates`: no gate is auto-approved - G2 and G3 wait for a
    person like G4 (the golden runs auto-approve the two reversible ones)."""
    developer, reviewer = examples or shipped_agent_examples()
    config = harness.build_config(game, workdir, template_dir)
    config["develop"]["developer"] = dict(developer)
    config["review"]["reviewer"] = dict(reviewer)
    if human_gates:
        config["checkpoints"]["auto_approve"] = []
    # The host's credential, when it is an environment variable (WGF_LIVE_ENV_PASSTHROUGH,
    # as for the AgentLoop live tests); a login under HOME needs nothing.
    extra = [n for n in os.environ.get("WGF_LIVE_ENV_PASSTHROUGH", "").split(",") if n]
    if extra:
        agents = config.setdefault("agents", {})
        agents["env_passthrough"] = list(agents.get("env_passthrough") or []) + extra
    record = {"developer": developer, "reviewer": reviewer,
              "source": os.path.relpath(FACTORY_YAML, paths.ROOT),
              "auto_approved_gates": list(config["checkpoints"]["auto_approve"]),
              "host_version": host_version(developer["argv"][0])}
    return config, record


def to_yaml(value, indent=0):
    """Block YAML wgflib.yamllite reads back to the same value: every string JSON-quoted
    (a YAML double-quoted scalar), so no argv element is ever reinterpreted."""
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        return "\n".join(
            f"{pad}{json.dumps(str(k))}:\n{to_yaml(v, indent + 2)}"
            if isinstance(v, (dict, list)) and v else f"{pad}{json.dumps(str(k))}: {to_yaml(v)}"
            for k, v in value.items())
    if isinstance(value, list):
        if not value:
            return "[]"
        return "\n".join(
            f"{pad}- {to_yaml(v, indent + 2).lstrip()}" if isinstance(v, (dict, list)) and v
            else f"{pad}- {to_yaml(v)}" for v in value)
    return json.dumps(value)


def write_evidence(evidence_dir, record):
    os.makedirs(evidence_dir, exist_ok=True)
    path = os.path.join(evidence_dir, "live-agents.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")
    return path


class _Unsandboxed:
    """The golden run's sandbox slot, open: live agent hosts reach their API."""

    class _Proxy:
        @staticmethod
        def summary():
            return {"sandboxed": False,
                    "reason": "live build: the agent hosts need their API"}

    proxy = _Proxy()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class LiveGoldenRun(harness.GoldenRun):
    """GoldenRun with the documented developer and reviewer from visit 1, no refusing proxy.
    G2/G3 are auto-approved and G4 passed by the harness, as in any golden run."""

    def __init__(self, game_key=GAME, **kwargs):
        super().__init__(game_key, **kwargs)
        self.config_data, self.record = build_live_config(self.game, self.workdir,
                                                          self.template_dir)
        write_evidence(self.evidence_dir, self.record)

    def sandbox(self):
        return _Unsandboxed()

    def run_workflow(self, resume=None, from_step=None):
        api, state, seconds = super().run_workflow(resume=resume, from_step=from_step)
        self.api_used, self.state = api, state  # the test reads the run's own artifacts
        return api, state, seconds

    def execute(self, resume=None, from_step=None):
        from golden import summary as summaries
        result = super().execute(resume=resume, from_step=from_step)
        # The golden summary names the replay developer and the scripted reviewer; this run
        # had neither. Say what it had.
        result["developer"] = f"live build: the developer {self.record['source']} documents"
        result["reviewer"] = f"live build: the reviewer {self.record['source']} documents"
        result["live"] = self.record
        summaries.write(result, self.evidence_dir, self.game.key)
        return result

    def reports(self, artifact_type):
        """Every version of one artifact type the run holds, oldest first."""
        refs = [r for versions in self.state.artifacts.values() for r in versions
                if r.type == artifact_type]
        refs.sort(key=lambda r: r.version)
        return [self.api_used.store.read_artifact(self.state.run_id, r) for r in refs]


def main(argv=None):
    parser = argparse.ArgumentParser(description="the live build's configuration")
    sub = parser.add_subparsers(dest="command", required=True)
    config = sub.add_parser("config", help="write <workdir>/factory.yaml for bin/wgf")
    config.add_argument("--workdir", required=True)
    config.add_argument("--human-gates", action="store_true",
                        help="auto-approve no gate: G2 and G3 wait for a person, like G4")
    args = parser.parse_args(argv)
    workdir = os.path.abspath(args.workdir)
    os.makedirs(workdir, exist_ok=True)
    game = games.game(GAME)
    data, record = build_live_config(game, workdir, human_gates=args.human_gates)
    path = os.path.join(workdir, "factory.yaml")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(to_yaml({"factory": data}) + "\n")
    evidence = write_evidence(os.path.join(workdir, "evidence"), record)
    print(f"config:   {path}\nevidence: {evidence}\nrun:      bin/wgf new-game --config {path} "
          f"--store {data['storage']['directory']} --project {game.title_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
