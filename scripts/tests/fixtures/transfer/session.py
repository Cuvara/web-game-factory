"""One session of the knowledge-transfer test, run in a process of its own.

    python session.py run --session a|b --store DIR --out FILE
                          [--knowledge with|without] [--designer follow|violate|claim]
                          [--developer faithful|violating] [--family F]
    python session.py knowledge --before-l29|--without-l29 --tmp DIR -- <wgf knowledge args>

`run` drives the shipped new-game workflow through the real engine and the real gates, in
the quality-consistency suite's fixture world (scripts/tests/fixtures/quality/world.py: a
fixture developer, bot, assets and verify; no agent host, no network), to G4 - or to where
it stops - and writes what it did to --out:

  Session A  (always on the Factory before L29, prelesson.py) a 2D puzzle-like game whose
             build debuts two new elements at once in unit k: the fixture bot's naive clear
             rate for unit k falls against the accepted build's, `naive.clear_rate` FAILs on
             that build (a real gate check), triage routes it to the encounter designer, whose
             visit splits the introductions and reports the lesson candidate; the next build
             passes. THE CLEAR RATE IS A FIXTURE MEASUREMENT, and a tautological one: the fixture
             bot fails exactly the units content.unit_debuts flags, the count the new checks
             make. It proves the pipeline -
             measured finding, candidate, ingest, promote - not the principle, which rests on
             the observed real games and the craft (workspace/lessons/evidence.yaml L29).
  Session B  a fresh game of another family and render (a 3D racer by default) designed by
             the REAL design step through the `agent` author, whose host is designer.py: it
             reads only its request. `--knowledge without` runs it on the Factory before L29
             (the control); `--developer violating` makes the fixture developer debut two
             elements in units.json whatever the design says (once; the level designer's
             visit repairs it).

Session B records every file the process opens (an audit hook) and its environment and
argv, so the test can show it read nothing of Session A's.

`knowledge` runs the knowledge CLI (`wgf knowledge ...`, scripts/wgf_knowledge/cli.py) with
the Factory root it reads pointed at the Factory before L29 (`--before-l29`: how Session A's
candidate is ingested, against the knowledge that did not have it yet) or at the Factory once
a person has implemented the check the candidate proposes, without the lesson
(`--without-l29`: promote refuses a blocking draft no classified check can hold, so the check
comes first - the person's completion - and the lesson is drafted on it).

Not a test module.
"""

import argparse
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.dirname(TESTS)
QUALITY = os.path.join(TESTS, "fixtures", "quality")
for _path in (SCRIPTS, TESTS, QUALITY, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

OPENED = []


def _audit(event, args):
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        OPENED.append(os.fsdecode(args[0]))


CHECK = "content.introductions_one_at_a_time"
DOUBLE = "double-debut"
DESIGNER = os.path.join(HERE, "designer.py")


# --------------------------------------------------------------------------- the world


def _world_class():
    import world as worlds
    from wgf_design import content as content_rules
    from wgf_playability import realism
    from wgflib import genre_models
    from wgflib.yamllite import load_file
    from wgflib import paths

    worlds.DEFECTS.setdefault(DOUBLE, {"where": "build"})
    naive_bars = load_file(os.path.join(paths.REFERENCE, "play-realism.yaml"))

    class SessionWorld(worlds.World):
        """The fixture world, with one defect more - the build debuts the element of a later
        unit one unit early, in a unit the naive bot plays - and a bot whose naive clear rate
        falls on a unit that debuts two elements at once."""

        settings = None
        target = None

        def __init__(self, scenario, design, checkout):
            super().__init__(scenario, design, checkout)
            self.adopt(design)

        def adopt(self, design):
            """Build what `design` describes from now on (Session B: the design the real
            design step wrote)."""
            self.design = design
            self.family = design["genre"]["family"]
            self.dimension = (design.get("engine") or {}).get("dimension") or "2d"
            self.spec = design["build_spec"]
            self.units = [u for u in self.spec["content"]["units"] if u.get("tier") != "optional"]
            self.qa = genre_models.qa_of(design)
            self.target = self._target()

        def naive_units(self):
            count = int((naive_bars.get("naive") or {}).get("units") or 1)
            return [self.units[0]["id"]] + realism.naive_units(self.units, count)

        def _target(self):
            """(unit k, [the elements it debuts early]): a naive-played unit after the opening
            one, and as many of the next elements later units debut as make it debut two."""
            news = content_rules.unit_debuts(self.units)
            positions = {u["id"]: n for n, u in enumerate(self.units)}
            for unit_id in self.naive_units()[1:]:
                n = positions[unit_id]
                own = len(news[n][1] or [])
                later = [e for _u, new in news[n + 1:] for e in (new or [])]
                if n and own < 2 and len(later) >= 2 - own:
                    return unit_id, later[:2 - own]
            return None

        listed = False
        held = False

        def held_target(self):
            """(unit k, [one element]) for the held build: a unit after the opening one whose
            DESIGN states a non-empty `introduces`, and the next element a later unit debuts -
            shown at k with k's `introduces` copied from the design, only the build's
            comparison with its design unit can tell it is a debut there."""
            news = content_rules.unit_debuts(self.units)
            for n, unit in enumerate(self.units):
                if not n or not unit.get("introduces"):
                    continue
                later = [e for u, new in news[n + 1:] for e in (new or [])
                         if e in (u.get("elements") or [])
                         and e not in (unit.get("elements") or [])]
                if later:
                    return unit["id"], later[:1]
            return None

        def built_units(self, build):
            out = super().built_units(build)
            # The build states each unit's introductions as its design does.
            designed = {u["id"]: u for u in self.units}
            for unit in out:
                if designed.get(unit["id"], {}).get("introduces"):
                    unit["introduces"] = list(designed[unit["id"]]["introduces"])
            if self.held:
                self.target = self.held_target()
            if DOUBLE in build["defects"] and self.target:
                unit_id, early = self.target
                for unit in out:
                    if unit["id"] != unit_id:
                        continue
                    # The developer shows a later unit's elements here, a unit early.
                    own = [n for u, n in content_rules.unit_debuts(out)
                           if u is unit][0] or []
                    unit["elements"] = list(unit.get("elements") or []) + [
                        e for e in early if e not in (unit.get("elements") or [])]
                    if self.listed:
                        # ...and states it introduces them (Session B's violating build);
                        # otherwise `introduces` stays the design's (Session A).
                        unit["introduces"] = list(own) + [e for e in early if e not in own]
            return out

        def records(self, build, project, items):
            self._build = build
            return super().records(build, project, items)

        def naive(self, project, common):
            record = super().naive(project, common)
            if project != "desktop" or not record.get("runs"):
                return record
            settings = self.settings or {}
            repeats = int(settings.get("naive_repeats") or 1)
            units = [self.units[0]["id"]] + list(settings.get("naive_units") or [])
            built = self.built_units(self._build)
            doubled = {u["id"] for n, (u, new) in enumerate(content_rules.unit_debuts(built))
                       if n and new and len(new) > 1}
            template = record["runs"][0]
            runs = []
            for unit_id in units:
                for policy in ("steady", "jitter"):
                    for attempt in range(repeats):
                        # The fixture bot: a unit that debuts two never-seen elements at once
                        # is cleared once in its repeats, any other unit every time.
                        won = unit_id not in doubled or attempt == 0
                        runs.append(dict(copy.deepcopy(template), policy=policy,
                                         unit_id=unit_id, won=won,
                                         clear_ms=21000 if won else None,
                                         losses=0 if won else 1))
            return dict(record, units=[None] + units[1:], repeats=repeats, runs=runs)

        def accepted_rates(self):
            """The accepted build's naive clear rates: every sampled unit cleared every time."""
            runs = int((naive_bars.get("clear_rate") or {}).get("runs") or 1)
            return {"units": {u: {p: {"won": runs, "n": runs} for p in ("steady", "jitter")}
                              for u in self.naive_units()}}

    return SessionWorld


# --------------------------------------------------------------------------- the steps


def _steps(world, accepted_path, candidate, session):
    import world as worlds
    from wgf_develop import specialist as specialists
    from wgflib.workflow.model import StepResult

    class Playability(worlds.FixturePlayabilityStep):
        @property
        def params(self):
            # The step's `with: accepted_play`: the accepted build's naive record (Session A).
            found = dict(super().params or {})
            if accepted_path:
                found["accepted_play"] = accepted_path
            return found

        def _play(self, repo, out, logs, settings, context, *args, **kwargs):
            self.world.settings = settings
            return super()._play(repo, out, logs, settings, context, *args, **kwargs)

    class Develop(worlds.FixtureDevelopStep):
        """The fixture developer. In Session A the encounter designer's first visit to the
        failing clear rate tunes what it owns, finds the cause is not difficulty - the unit
        debuts two never-seen elements at once - and reports it as a systemic lesson
        candidate (prototype-report `specialist.lesson_candidates`) on the build it made,
        which naive play measures again and fails again; its next visit splits the
        introductions."""

        def execute(self, inputs, context):
            phase = (self.params or {}).get("phase") or "production"
            spec, problem = specialists.resolve(context, inputs, phase)
            if problem:
                return StepResult.failed(problem, retryable=False)
            reporting = bool(candidate and spec and spec["role"] == "encounter-designer"
                             and DOUBLE in self.world.defects
                             and not self.world.fixes.get("encounter-designer"))
            build = self.world.develop(phase, spec["role"] if spec else None)
            if reporting:
                # The next visit of the encounter designer splits the introductions.
                self.world.fixes["encounter-designer"] = {"fixes": [DOUBLE]}
            body = worlds._fixture_body("prototype-report", context)
            body["build_ref"]["commit_sha"] = build["commit"]
            body["iteration"] = context.visit
            if spec:
                body["specialist"] = {"role": spec["role"],
                                      "findings": [f["id"] for f in spec["findings"]],
                                      "pending": list(spec["pending"]),
                                      "triage_report": spec["triage_report"],
                                      "source": spec["source"], "sessions": 1, "cost_usd": 3.5}
                if reporting:
                    finding = next((f["id"] for f in spec["findings"]
                                    if "naive.clear_rate" in str(f.get("id"))
                                    or "naive.clear_rate" in str(f.get("check"))), None)
                    unit_id, early = self.world.target
                    entry = dict(candidate, finding=finding, role=spec["role"],
                                 symptom=candidate["symptom"].format(
                                     unit=unit_id, element=" and ".join(early)))
                    body["specialist"]["lesson_candidates"] = [entry]
            artifact = worlds._seal(self, "prototype-report", body, inputs, context, self.role)
            if spec and spec["pending"]:
                return StepResult.success([artifact], route=specialists.NEXT_SPECIALIST,
                                          message=f"{spec['role']} visit (fixture)")
            return StepResult.success([artifact],
                                      message=f"{phase} build {build['commit'][:12]}")

    out = [Playability, Develop]
    if session == "b":
        from wgf_design.step import DesignStep

        class Design(DesignStep):
            """The REAL design step; the world builds what it wrote."""

            def __init__(self, definition, world=None):
                super().__init__(definition)
                self.world = world

            def execute(self, inputs, context):
                result = super().execute(inputs, context)
                if result.outcome == "SUCCESS" and result.artifacts:
                    self.world.adopt(result.artifacts[0].content)
                return result

        out.append(Design)
    return out


def _strategy_step(family):
    import world as worlds
    import test_design_seed as seeds
    from wgflib.workflow import mock
    from wgflib.workflow.model import StepResult

    class Strategy(worlds._Fixture):
        """The strategy G2 approved for a `family` game: its concept is the family seed's."""
        type, role = "strategy", "game-designer"

        def execute(self, inputs, context):
            # The placeholder strategy (schema-valid), its game restated as the family seed's:
            # the one-liner, the concept and the research handoff test_design_seed writes.
            body = worlds._fixture_body("title-strategy", context)
            body.pop("provenance", None)
            seeded = seeds.strategy_for(family)
            body["one_liner"] = seeded["one_liner"]
            body["concept"] = dict({"control_scheme": "drag"}, **seeded["concept"])
            body["research"] = seeded["research"]
            # Pinned at the profiles the Factory ships (the placeholder's pins are older).
            from wgflib import paths
            from wgflib.yamllite import load_file
            for entry in body.get("platform_set") or []:
                profile = load_file(os.path.join(paths.REFERENCE, "platforms",
                                                 f"{entry['id']}.yaml"))
                entry["profile_version"] = str(profile.get("version"))
            body["title_id"] = context.project_id or mock.FIXTURE_SLUG
            return StepResult.success([worlds._seal(self, "title-strategy", body, inputs,
                                                    context, self.role)],
                                      message=f"{family} strategy (fixture)")
    return Strategy


# --------------------------------------------------------------------------- a run


CANDIDATE = None


def _candidate():
    """The lesson candidate the encounter designer reports after splitting the introductions:
    symptom -> root cause -> systemic -> enforcement proposal, stated so it is true of any
    game. Its text is the text a person would review; promote drafts the lesson from it."""
    from wgflib.yamllite import load_file
    from wgflib import paths
    return {
        "summary": ("A unit that debuts two never-seen elements at once teaches neither: the "
                    "player meets both in the same breath, cannot tell which one beat them, "
                    "and fails the unit far more often than the units around it. Nothing "
                    "counted how many new elements one unit debuts, on the design or on the "
                    "built content."),
        "symptom": ("Unit {unit} debuted {element}, never seen before, at once, and naive "
                    "play cleared it once in six runs per player model, against six in six "
                    "on the accepted build."),
        "root_cause": ("The design was checked only for teaching a mechanic before relying on "
                       "it, never for how many new elements one unit debuts, and nothing "
                       "counted it on the built content."),
        "systemic": {"value": True, "why": "any authored game can debut two elements in one "
                                           "unit, and no gate counts debuts"},
        "proposed_check": f"design-consistency:{CHECK}",
        "proposed_checks": [f"design-consistency:{CHECK}", f"content-sufficiency:{CHECK}"],
        "proposed_level": "blocking",
        "proposed_scope": {},
        "domain": "level-design",
        "principle": ("After the opening unit, a unit introduces at most one element the "
                      "player has not met, so every new element is first met on its own and "
                      "practised before it is combined with another new one."),
        "anti_pattern": "A unit that debuts two or more never-seen elements at once.",
    }


def run(args):
    import designs
    from wgflib.workflow import checkpoint
    from wgflib.workflow.api import RunRequest, WorkflowAPI
    from wgflib.workflow.config import FactoryConfig
    from wgflib.workflow.model import RunStatus
    from wgflib.workflow.step import StepRegistry
    import world as worlds
    import prelesson

    os.makedirs(args.store, exist_ok=True)
    if args.session == "a" or args.knowledge == "without":
        prelesson.install(os.path.join(args.store, "factory-before-l29"))
    elif args.knowledge == "pinned-before" and not args.resume:
        # Started on the Factory before L29; nothing else is filtered, here or on resume.
        prelesson.install(os.path.join(args.store, "factory-before-l29"), pins_only=True)
    family = args.family or ("puzzle" if args.session == "a" else "racing")
    design, result = designs.design(family)
    if design is None:
        raise SystemExit(f"the {family} release design was refused: {result.error}")
    checkout = os.path.join(args.store, f"game-{family}")
    os.makedirs(os.path.join(checkout, ".git"), exist_ok=True)
    scenario = {"defects": [], "fixes": {}}
    if args.session == "a":
        scenario = {"defects": [DOUBLE], "fixes": {}}
    elif args.developer == "duplicate":
        # Session C: a defect another lesson holds - two units of one group ship the same
        # level (content.structure) - while every introduction is paced.
        scenario = {"defects": ["duplicate-level"],
                    "fixes": {"level-designer": {"fixes": ["duplicate-level"]}}}
    elif args.developer in ("violating", "violating-unlisted", "violating-held"):
        scenario = {"defects": [DOUBLE], "fixes": {"level-designer": {"fixes": [DOUBLE]}}}
    world = _world_class()(scenario, design, checkout)
    # Session A's defect adds the elements only; Session B's violating build also lists them.
    world.listed = args.session == "b" and args.developer == "violating"
    world.held = args.session == "b" and args.developer == "violating-held"
    accepted = None
    if args.session == "a":
        accepted = os.path.join(args.store, "accepted-play.json")
        with open(accepted, "w", encoding="utf-8") as handle:
            json.dump(world.accepted_rates(), handle)
    extra = _steps(world, accepted, _candidate() if args.session == "a" else None,
                   args.session)
    if args.session == "b":
        # The agent author's starting point: the family seed laid out for the release tier
        # (the quality suite's own release author) - the draft the designer is given.
        from wgf_design import agent as agent_author

        class ReleaseStartingPoint:
            def __init__(self, starting_point=True):
                self.author = designs.ReleaseSeedAuthor()

            def draft(self, brief):
                return self.author.draft(brief)

        agent_author.ArchetypeAuthor = ReleaseStartingPoint
        extra.append(_strategy_step(family))

    class API(WorkflowAPI):
        def registry(self, use_mock, load_modules=True):
            registry = StepRegistry()
            checkpoint.register(registry)
            worlds.register(registry, world)
            for cls in extra:
                registry.register(cls.type, (lambda c: (lambda d: c(d, world)))(cls))
            return registry

    gates = ["G3"] if args.hold_g2 or args.resume else ["G2", "G3"]
    config = {"storage": {"fsync": False}, "checkpoints": {"auto_approve": gates},
              "design": {"author": "agent",
                         "agent": {"argv": [sys.executable, DESIGNER, args.designer,
                                            "{request}", "{draft}"],
                                   "timeout_seconds": 120, "idle_timeout_seconds": 60}},
              "visualqa": {"judge": {"kind": "command",
                                     "argv": [sys.executable, worlds.JUDGE, "{frames_dir}",
                                              "{verdict}"]}}}
    api = API(config=FactoryConfig(config), store_dir=os.path.join(args.store, "store"))
    if args.resume:
        state = api.run(RunRequest(resume=args.resume, decision="approve",
                                   decided_by="human", note="K5 transfer test"))
    else:
        state = api.run(RunRequest())
    summary = {"session": args.session, "run_id": state.run_id, "status": str(state.status),
               "waiting_at_g4": (state.status, state.cursor) == (RunStatus.WAITING,
                                                                  "prototype-review"),
               "cursor": state.cursor, "message": state.message,
               "trail": [{"step": e["step"], "outcome": e.get("outcome"),
                          "route": e.get("route")} for e in state.trail],
               "target": list(world.target) if world.target else None,
               "visits": list(world.visits), "store": os.path.join(args.store, "store")}
    return summary


def knowledge(args, rest):
    import prelesson
    from wgf_knowledge import cli
    if args.before_l29 or args.without_l29:
        root = prelesson.knowledge_root(args.tmp, lesson_only=args.without_l29)
        cli._root = lambda: root
    return cli.main(rest)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    rest = []
    if "--" in argv:
        at = argv.index("--")
        argv, rest = argv[:at], argv[at + 1:]
    parser = argparse.ArgumentParser(prog="session.py")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--session", choices=("a", "b"), required=True)
    r.add_argument("--store", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--knowledge", choices=("with", "without", "pinned-before"),
                   default="with")
    r.add_argument("--hold-g2", action="store_true", help="stop at G2 (a person's gate)")
    r.add_argument("--resume", metavar="RUN_ID", help="approve G2 of this run and go on")
    r.add_argument("--designer", choices=("follow", "declare", "violate", "claim"),
                   default="follow")
    r.add_argument("--developer", choices=("faithful", "violating", "violating-unlisted",
                                           "violating-held", "duplicate"),
                   default="faithful")
    r.add_argument("--family")
    k = sub.add_parser("knowledge")
    k.add_argument("--before-l29", action="store_true",
                   help="the Factory as Session A ran on it: no L29, no check holding it")
    k.add_argument("--without-l29", action="store_true",
                   help="the Factory once its check is implemented, before L29 is promoted")
    k.add_argument("--tmp", required=True)
    args = parser.parse_args(argv)
    if args.command == "knowledge":
        return knowledge(args, rest)
    sys.addaudithook(_audit)
    summary = run(args)
    summary["opened"] = sorted(set(OPENED))
    summary["env"] = dict(os.environ)
    summary["argv"] = list(sys.argv)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
