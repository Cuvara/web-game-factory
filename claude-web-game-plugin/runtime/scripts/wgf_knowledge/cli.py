"""`wgf knowledge`: the Factory's knowledge from the command line.

    wgf knowledge validate [--runtime] [--json]
        Every problem of the knowledge model and the regression registry (the same check
        check-integrity runs). --runtime: as an installed runtime, whose tests are not shipped.
    wgf knowledge show [ID] [--json]
        Every rule with its derived level, lifecycle, status, category and scope; or one rule
        in full: its checks with tier, producer, validating steps and where the result is read,
        its tests, and the instance evidence when this checkout has it.
    wgf knowledge resolve [--family F] [--genre G] [--render 2d|3d] [--platform P ...]
                          [--tier T] [--profile X] [--archetype A] [--json]
        The rules that apply to those facets, and the excluded ones with why. A facet not
        given is undetermined, which never excludes a rule.
    wgf knowledge contract RUN_ID [--store DIR] [--config PATH] [--json]
        The run's knowledge-contract. A run that has none yet is resolved now from its
        game-design, title-strategy, quality tier and pinned knowledge, and says so.
    wgf knowledge table [--families F,..] [--render 2d,3d] [--tiers T,..] [--platform P ...]
                        [--json]
        The benchmark approval table: one dry resolution per facet combination - rule counts
        by level, experimental gaps, validators, regression tests. Nothing is started.

Also `python3 scripts/wgf-knowledge.py ...`. Exit status: 0 clean; 1 problems found (validate:
a problem; resolve, table: a blocking or required check no workflow step validates);
2 the command could not run (unreadable knowledge, an unknown run, a bad argument).
Standard library only. See docs/knowledge-enforcement.md.
"""

import argparse
import itertools
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from wgf_knowledge import model, resolve as resolver, versions  # noqa: E402

EXIT_OK, EXIT_PROBLEMS, EXIT_UNUSABLE = 0, 1, 2
WORKFLOW = "core/workflows/new-game.workflow.yaml"


class Unusable(Exception):
    """The command cannot run."""


def _root():
    from wgflib import paths
    return paths.ROOT


def _load(root):
    from wgf_quality import registry
    try:
        data = registry.load(root)
    except (OSError, ValueError) as exc:
        raise Unusable(f"the knowledge cannot be read ({exc})")
    checks, _ = registry.classify(data["tiers"], root)
    return data, checks


def _workflow(root, path=None):
    from wgflib.yamllite import load as load_yaml
    path = path or os.path.join(root, *WORKFLOW.split("/"))
    try:
        with open(path, encoding="utf-8") as handle:
            return (load_yaml(handle.read()) or {}).get("workflow") or {}
    except (OSError, ValueError) as exc:
        raise Unusable(f"the workflow {path} cannot be read ({exc})")


def _print_json(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _scope_text(lesson):
    scope = model.scope_of(lesson)
    if scope is None:
        return "?"
    if not scope:
        return "global"
    return "; ".join(f"{k}={','.join(map(str, v))}" for k, v in scope.items())


# ----------------------------------------------------------------------------- commands


def cmd_validate(args):
    from wgf_quality import registry
    root = _root()
    found = registry.problems(root, runtime=args.runtime)
    if any("cannot be read" in p for p in found):
        raise Unusable("; ".join(p for p in found if "cannot be read" in p))
    if args.json:
        _print_json({"ok": not found, "problems": found})
    else:
        for problem in found:
            print(f"problem  {problem}")
        print("knowledge: OK" if not found else f"knowledge: {len(found)} problem(s)")
    return EXIT_PROBLEMS if found else EXIT_OK


def _row(lesson, checks):
    return {"id": lesson.get("id"), "level": model.level_of(lesson, checks)
            or ("process" if model.is_process(lesson) else None),
            "derived_level": model.derive_level(lesson, checks),
            "lifecycle": lesson.get("lifecycle"), "status": lesson.get("status"),
            "category": lesson.get("category"), "scope": model.scope_of(lesson),
            "checks": list(lesson.get("checks") or []), "title": lesson.get("title")}


def _detail(lesson, data, checks, workflow):
    from wgf_quality import registry
    steps = {}
    for step in workflow.get("steps") or ():
        for artifact in (step or {}).get("outputs") or ():
            steps.setdefault(artifact, []).append(step.get("id"))
    held = []
    for check_id in lesson.get("checks") or ():
        entry = checks.get(check_id) or {}
        source = entry.get("source") or check_id.split(":", 1)[0]
        held.append({"check": check_id, "tier": entry.get("tier"),
                     "producer": entry.get("producer"),
                     "validators": steps.get(entry.get("producer")) or [],
                     "status_at": registry.status_at(data["tiers"], source)})
    out = dict(_row(lesson, checks))
    out.update({"problem": lesson.get("problem"), "root_cause": lesson.get("root_cause"),
                "lesson": lesson.get("lesson"), "introduced": lesson.get("introduced"),
                "checks": held, "tests": model.tests_of(lesson), "gap": lesson.get("gap"),
                "held_by": lesson.get("held_by"),
                "evidence": (((data.get("evidence") or {}).get("lessons") or {})
                             .get(lesson.get("id")))})
    return out


def cmd_show(args):
    root = _root()
    data, checks = _load(root)
    lessons = [l for l in (data["lessons"] or {}).get("lessons") or [] if isinstance(l, dict)]
    if args.id:
        lesson = next((l for l in lessons if l.get("id") == args.id), None)
        if lesson is None:
            raise Unusable(f"no lesson {args.id!r}")
        detail = _detail(lesson, data, checks, _workflow(root))
        if args.json:
            _print_json(detail)
            return EXIT_OK
        print(f"{detail['id']}  {detail['title']}")
        for key in ("level", "derived_level", "lifecycle", "status", "category"):
            print(f"  {key:<14}{detail[key]}")
        print(f"  {'scope':<14}{_scope_text(lesson)}")
        for key in ("problem", "root_cause", "lesson", "gap", "held_by"):
            if detail.get(key):
                print(f"  {key:<14}{detail[key]}")
        for check in detail["checks"]:
            print(f"  check         {check['check']} [{check['tier']}] reported in "
                  f"{check['producer']} by {', '.join(check['validators']) or 'no step'}")
        for kind, refs in detail["tests"].items():
            for ref in refs:
                print(f"  {kind:<14}{ref}")
        if detail["evidence"]:
            print(f"  evidence      {json.dumps(detail['evidence'], ensure_ascii=False)}")
        return EXIT_OK
    rows = [_row(l, checks) for l in lessons]
    if args.json:
        _print_json({"version": (data["lessons"] or {}).get("version"), "rules": rows})
        return EXIT_OK
    print(f"lessons {(data['lessons'] or {}).get('version')}: {len(rows)} rule(s)")
    for row, lesson in zip(rows, lessons):
        print(f"  {row['id']:<5} {str(row['level']):<13} {str(row['lifecycle']):<10} "
              f"{str(row['status']):<9} {str(row['category']):<20} {_scope_text(lesson)}")
    return EXIT_OK


def _resolve(root, data, checks, run_facets, workflow, exceptions=(), now=None, read=None,
             pins=None):
    found_versions = versions.collect(read=read, root=root, workflow=workflow,
                                      platforms=run_facets.get("platforms") or (), pins=pins)
    body = resolver.resolve(data["lessons"], checks, data["tiers"], run_facets,
                            workflow=workflow, exceptions=exceptions, now=now,
                            versions=found_versions, vocabulary=model.vocabulary(root))
    return dict({"versions": found_versions}, **body)


def _render(body, header=None):
    if header:
        print(header)
    facets = body["facets"]
    print("facets       " + ", ".join(f"{k}={v if v not in (None, []) else '-'}"
                                     for k, v in facets.items()))
    counts = body["counts"]
    print("counts       " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    for level in resolver.COUNTED:
        ids = [r["id"] for r in body["rules"] if r["level"] == level]
        if ids:
            print(f"{level:<13}{', '.join(ids)}")
    for entry in body["not_applicable"]:
        print(f"excluded     {entry['id']}: {entry['why_not']}")
    print("validators   " + (", ".join(body["required_validators"]) or "-"))
    for entry in body.get("missing_validators") or ():
        print(f"MISSING      {entry['rule']} {entry['check']}: no step outputs "
              f"{entry['producer']}")
    print(f"tests        {len(body['regression_suite'])}")
    for refused in body.get("exceptions_refused") or ():
        print(f"refused      {refused['exception'].get('rule_id')}: "
              + "; ".join(refused["problems"]))


def cmd_resolve(args):
    root = _root()
    data, checks = _load(root)
    try:
        run_facets = resolver.facets(family=args.family, genre=args.genre, render=args.render,
                                     platforms=args.platform, tier=args.tier,
                                     profile=args.profile, archetype=args.archetype)
        body = _resolve(root, data, checks, run_facets, _workflow(root))
    except ValueError as exc:
        raise Unusable(str(exc))
    except model.KnowledgeError as exc:
        raise Unusable(str(exc))
    if args.json:
        _print_json(body)
    else:
        _render(body)
    return EXIT_PROBLEMS if body["missing_validators"] else EXIT_OK


def _run_reader(state, run_dir):
    """A reader of the run's pinned copy of a Factory file, else the live file."""
    from wgflib.workflow import references

    def read(relpath):
        try:
            text, _, _ = references.read(relpath, state.params, run_dir)
        except references.PinError as exc:
            raise OSError(str(exc))
        return text.encode("utf-8")
    return read


def cmd_contract(args):
    from wgflib.workflow.api import WorkflowAPI
    from wgflib.workflow.store import StoreError
    try:
        api = WorkflowAPI(config_path=args.config, store_dir=args.store)
        state = api.store.load(args.run)
    except (StoreError, OSError, ValueError, KeyError) as exc:
        raise Unusable(f"run {args.run}: {exc}")
    recorded = state.latest_of_type("knowledge-contract")
    if recorded is not None:
        contract = api.store.read_artifact(state.run_id, recorded)
        if args.json:
            _print_json(contract)
        else:
            _render(contract, header=f"{state.run_id}: knowledge-contract {recorded.id} "
                                     f"v{recorded.version} (recorded)")
        return EXIT_OK
    # Not made yet (a run started before the knowledge step): resolve it now, dry, from what
    # the run holds and what it pinned - shown, never written into the run.
    from wgflib.yamllite import load as load_yaml
    root = _root()
    read = _run_reader(state, api.store.run_dir(state.run_id))

    def artifact(kind):
        ref = state.latest_of_type(kind)
        return api.store.read_artifact(state.run_id, ref) if ref is not None else None

    try:
        lessons = load_yaml(read(versions.FILES["lessons"]).decode("utf-8"))
        tiers = load_yaml(read(versions.FILES["check_tiers"]).decode("utf-8"))
        from wgf_quality import registry
        # The run's pinned check tiers, classified against the run's pinned copies of the
        # files they enumerate (the live file where the run pinned none) - never the live
        # tiers against pinned files, or the reverse.
        checks, _ = registry.classify(
            tiers, root, reader=lambda relative: load_yaml(read(relative).decode("utf-8")))
        data = {"lessons": lessons, "tiers": tiers}
        tier = ((state.params or {}).get("quality") or {}).get("tier")
        strategy = artifact("title-strategy")
        run_facets = resolver.facets_from(artifact("game-design"), strategy, tier)
        workflow = None
        source = getattr(state, "workflow_source", None)
        source = os.path.join(root, source) if source else None
        if source and os.path.isfile(source):
            workflow = _workflow(root, source)
        workflow = workflow or _workflow(root)
        body = _resolve(root, data, checks, run_facets, workflow, read=read,
                        pins=resolver.platform_pins(strategy))
    except (OSError, ValueError, StoreError, model.KnowledgeError) as exc:
        raise Unusable(f"run {state.run_id}: the knowledge cannot be resolved ({exc})")
    body = dict({"recorded": False, "run_id": state.run_id}, **body)
    if args.json:
        _print_json(body)
    else:
        _render(body, header=f"{state.run_id}: no knowledge-contract recorded - resolved now "
                             "from the run's design, strategy, tier and pinned knowledge")
    return EXIT_OK


def _split(values):
    out = []
    for value in values or ():
        out += [v.strip() for v in str(value).split(",") if v.strip()]
    return out


def cmd_table(args):
    root = _root()
    data, checks = _load(root)
    vocabulary = model.vocabulary(root)
    families = _split(args.families) or vocabulary["families"]
    renders = _split(args.render) or vocabulary["render"]
    tiers = _split(args.tiers) or [t for t in vocabulary["tiers"] if t != "premium"]
    workflow = _workflow(root)
    rows, missing = [], False
    for family, render, tier in itertools.product(families, renders, tiers):
        run_facets = resolver.facets(family=family, render=render, tier=tier,
                                     platforms=args.platform)
        body = resolver.resolve(data["lessons"], checks, data["tiers"], run_facets,
                                workflow=workflow)
        missing = missing or bool(body["missing_validators"])
        rows.append({"facets": {k: v for k, v in run_facets.items() if v not in (None, [])},
                     "counts": body["counts"],
                     "experimental_gaps": [e["id"] for e in body["experimental"]],
                     "required_validators": body["required_validators"],
                     "missing_validators": body["missing_validators"],
                     "regression_tests": len(body["regression_suite"]),
                     "cost_estimate": "unmetered", "approved_by": None, "approved_at": None})
    if args.json:
        _print_json({"rows": rows})
    else:
        print(f"{'facets':<34} {'blk':>3} {'req':>3} {'rec':>3} {'exp':>3} {'n/a':>3} "
              f"{'tests':>5}  experimental gaps / validators")
        for row in rows:
            facets = ",".join(f"{v if not isinstance(v, list) else '+'.join(v)}"
                              for v in row["facets"].values())
            counts = row["counts"]
            print(f"{facets:<34} {counts['blocking']:>3} {counts['required']:>3} "
                  f"{counts['recommended']:>3} {counts['experimental']:>3} "
                  f"{counts['not_applicable']:>3} {row['regression_tests']:>5}  "
                  f"{' '.join(row['experimental_gaps']) or '-'} / "
                  f"{' '.join(row['required_validators'])}")
        print("approved by / date: (a person fills these in)")
    return EXIT_PROBLEMS if missing else EXIT_OK


def build_parser():
    parser = argparse.ArgumentParser(
        prog="wgf knowledge", description="The Factory's knowledge: rules, levels, scope.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    validate = sub.add_parser("validate", help="every problem of the knowledge model")
    validate.add_argument("--runtime", action="store_true",
                          help="as an installed runtime: test existence is not checked")
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(handler=cmd_validate)
    show = sub.add_parser("show", help="every rule, or one in full")
    show.add_argument("id", nargs="?", metavar="ID")
    show.add_argument("--json", action="store_true")
    show.set_defaults(handler=cmd_show)
    res = sub.add_parser("resolve", help="the rules that apply to a facet set")
    res.add_argument("--family")
    res.add_argument("--genre")
    res.add_argument("--render", choices=["2d", "3d"])
    res.add_argument("--platform", action="append", metavar="ID")
    res.add_argument("--tier")
    res.add_argument("--profile")
    res.add_argument("--archetype")
    res.add_argument("--json", action="store_true")
    res.set_defaults(handler=cmd_resolve)
    contract = sub.add_parser("contract", help="a run's knowledge-contract")
    contract.add_argument("run", metavar="RUN_ID")
    contract.add_argument("--store", metavar="DIR")
    contract.add_argument("--config", metavar="PATH")
    contract.add_argument("--json", action="store_true")
    contract.set_defaults(handler=cmd_contract)
    table = sub.add_parser("table", help="the benchmark approval table (dry)")
    table.add_argument("--families", action="append", metavar="F,..")
    table.add_argument("--render", action="append", metavar="2d,3d")
    table.add_argument("--tiers", action="append", metavar="T,..")
    table.add_argument("--platform", action="append", metavar="ID")
    table.add_argument("--json", action="store_true")
    table.set_defaults(handler=cmd_table)
    return parser


def main(argv=None):
    parser = build_parser()
    try:
        args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as exc:
        return EXIT_OK if exc.code in (0, None) else EXIT_UNUSABLE
    if not getattr(args, "handler", None):
        parser.print_help()
        return EXIT_UNUSABLE
    try:
        return args.handler(args)
    except (Unusable, model.KnowledgeError) as exc:
        print(f"wgf knowledge: {exc}", file=sys.stderr)
        return EXIT_UNUSABLE


if __name__ == "__main__":
    sys.exit(main())
