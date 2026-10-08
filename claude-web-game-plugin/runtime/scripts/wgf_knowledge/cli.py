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
    wgf knowledge report RUN_ID [--md | --json] [--store DIR] [--config PATH]
        The run's knowledge compliance, from its newest quality-report: versions, the rules
        by level - satisfied, failed, unmeasured, excepted - the evidence each check was read
        from, exceptions, regression, lessons applied and new lesson candidates. Exit 0
        PASS, 1 RELEASE_BLOCKED (enforcing or advisory alike), 2 no quality-report yet.
    wgf knowledge table [--families F,..] [--render 2d,3d] [--tiers T,..] [--platform P ...]
                        [--profiles A,..] [--phases N,..] [--facets FILE] [--json]
        The benchmark approval table: one dry resolution per candidate benchmark (facet
        combination, complexity profile, roadmap phase) - rule counts by level, experimental
        gaps, validators, regression tests, and the budget, which every row lists as requiring
        a person's approval. Nothing is started and nothing is spent.
    wgf knowledge ingest RUN_ID [--store DIR] [--config PATH] [--candidates FILE] [--dry-run]
                         [--json]
        The run's lesson candidates (prototype-report, triage-report, quality-report,
        review-report) into workspace/lessons/candidates.yaml: schema-checked, a stated root
        cause, de-duplicated, with the provenance of each report. A candidate whose check an
        active lesson already holds is that lesson's regression observation. Exit 1 (nothing
        written) when any candidate is invalid; 2 when the run store cannot be read.
    wgf knowledge candidates [--open] [--candidates FILE] [--json]
        The stored candidates, with their state (open, promoted, rejected) and basis.
    wgf knowledge reject C-N --reason TEXT [--by NAME] [--candidates FILE]
        A person rejects a candidate; it is kept, never deleted.
    wgf knowledge promote C-N [--id L<n>] [--level L] [--check ID] [--category C]
                          [--title TEXT] [--scope KEY=V,..] [--out FILE] [--json]
        A PR-ready patch: the lessons.yaml entry, the evidence.yaml entry and the test stubs.
        Writes nothing but --out; never edits core/. Exit 1 when refused - subjective
        evidence is never drafted blocking or required.
    wgf knowledge firewall [ID ...] [--run RUN_ID] [--kind catches|passes|generalizes]
                           [--json]
        The regression firewall: every lesson's (or the run's contract's) catches, passes and
        generalizes tests, run here, one verdict per lesson. Exit 1 when one fails, is missing
        or was skipped (a skip is never a pass). A development checkout only.
    wgf knowledge generations [--store DIR] [--config PATH] [--json]
        Runs compared by the Factory and knowledge versions they consumed: lessons applied,
        satisfied, failed, excepted, verdicts; one group per generation.

Also `python3 scripts/wgf-knowledge.py ...`. Exit status: 0 clean; 1 problems found (validate:
a problem; resolve, table: a blocking or required check no workflow step validates; ingest,
promote: refused; firewall: a lesson not held); 2 the command could not run (unreadable
knowledge, an unknown run, a bad argument).
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
    for record in body.get("exceptions") or ():
        approved = record.get("approved_by") if isinstance(record.get("approved_by"),
                                                           dict) else {}
        print(f"excepted     {record.get('rule_id')} by {approved.get('identifier') or '?'} "
              f"until {record.get('expires_at') or '?'}: {record.get('reason') or ''}")
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


def cmd_report(args):
    from wgf_quality import compliance
    from wgflib.workflow.api import WorkflowAPI
    from wgflib.workflow.store import StoreError
    try:
        api = WorkflowAPI(config_path=args.config, store_dir=args.store)
        state = api.store.load(args.run)
        ref = state.latest_of_type("quality-report")
        report = api.store.read_artifact(state.run_id, ref) if ref is not None else None
    except (StoreError, OSError, ValueError, KeyError) as exc:
        raise Unusable(f"run {args.run}: {exc}")
    section = (report or {}).get("compliance")
    if not isinstance(section, dict):
        raise Unusable(f"run {args.run}: no quality-report with a compliance section yet - the "
                       "quality gate has not judged a build of this run")
    if args.json:
        _print_json(section)
    elif args.md:
        sys.stdout.write(compliance.render_markdown(section))
    else:
        print(f"{state.run_id}: quality-report {ref.id} v{ref.version} "
              f"({(report.get('provenance') or {}).get('artifact_id')})")
        for line in compliance.render_lines(section):
            print(line)
    return EXIT_PROBLEMS if section.get("verdict") == "RELEASE_BLOCKED" else EXIT_OK


def _split(values):
    out = []
    for value in values or ():
        out += [v.strip() for v in str(value).split(",") if v.strip()]
    return out


BUDGET_APPROVAL = "requires human budget approval"


def _table_candidates(args, vocabulary):
    """[{facets..., profile, phase, cost_estimate}] from --facets FILE, else the product of
    the facet options (complexity profiles and roadmap phases included when given)."""
    if args.facets:
        from wgflib.yamllite import load as load_yaml
        try:
            with open(args.facets, encoding="utf-8") as handle:
                text = handle.read()
            try:
                data = json.loads(text)
            except ValueError:
                data = load_yaml(text)
        except (OSError, ValueError) as exc:
            raise Unusable(f"{args.facets} cannot be read ({exc})")
        data = data.get("candidates") if isinstance(data, dict) else data
        if not isinstance(data, list) or not all(isinstance(e, dict) for e in data):
            raise Unusable(f"{args.facets}: a list of candidate benchmarks (mappings), or "
                           "`candidates:` holding one")
        return data
    families = _split(args.families) or vocabulary["families"]
    renders = _split(args.render) or vocabulary["render"]
    tiers = _split(args.tiers) or [t for t in vocabulary["tiers"] if t != "premium"]
    profiles = _split(args.profiles) or [None]
    phases = _split(args.phases) or [None]
    return [{"family": f, "render": r, "tier": t, "profile": p, "phase": n}
            for p, n, f, r, t in itertools.product(profiles, phases, families, renders, tiers)]


def cmd_table(args):
    # Dry by construction: the resolver is pure, and nothing here imports the engine or a
    # step - a benchmark is approved, and its budget granted, by a person, never by a table.
    root = _root()
    data, checks = _load(root)
    vocabulary = model.vocabulary(root)
    workflow = _workflow(root)
    rows, missing = [], False
    for entry in _table_candidates(args, vocabulary):
        try:
            run_facets = resolver.facets(
                family=entry.get("family"), genre=entry.get("genre"), render=entry.get("render"),
                tier=entry.get("tier"), platforms=entry.get("platforms") or args.platform,
                profile=entry.get("profile"), archetype=entry.get("archetype"))
        except ValueError as exc:
            raise Unusable(str(exc))
        body = resolver.resolve(data["lessons"], checks, data["tiers"], run_facets,
                                workflow=workflow)
        missing = missing or bool(body["missing_validators"])
        rows.append({"facets": {k: v for k, v in run_facets.items() if v not in (None, [])},
                     "phase": entry.get("phase"),
                     "counts": body["counts"],
                     "experimental_gaps": [e["id"] for e in body["experimental"]],
                     "required_validators": body["required_validators"],
                     "missing_validators": body["missing_validators"],
                     "regression_tests": len(body["regression_suite"]),
                     "cost_estimate": entry.get("cost_estimate") or "unmetered",
                     "budget": BUDGET_APPROVAL, "starts_run": False,
                     "approved_by": None, "approved_at": None})
    if args.json:
        _print_json({"rows": rows, "budget": BUDGET_APPROVAL, "starts_run": False})
    else:
        print(f"{'facets':<34} {'blk':>3} {'req':>3} {'rec':>3} {'exp':>3} {'n/a':>3} "
              f"{'tests':>5}  experimental gaps / validators / budget")
        for row in rows:
            facets = ",".join(f"{v if not isinstance(v, list) else '+'.join(v)}"
                              for v in row["facets"].values())
            if row["phase"] is not None:
                facets = f"phase {row['phase']}:{facets}"
            counts = row["counts"]
            print(f"{facets:<34} {counts['blocking']:>3} {counts['required']:>3} "
                  f"{counts['recommended']:>3} {counts['experimental']:>3} "
                  f"{counts['not_applicable']:>3} {row['regression_tests']:>5}  "
                  f"{' '.join(row['experimental_gaps']) or '-'} / "
                  f"{' '.join(row['required_validators'])} / {row['cost_estimate']}, "
                  f"{BUDGET_APPROVAL}")
        print("Nothing was started and nothing was spent. Every profile and phase "
              f"{BUDGET_APPROVAL}; approved by / date: (a person fills these in)")
    return EXIT_PROBLEMS if missing else EXIT_OK


# ----------------------------------------------------------------------------- learning


def _candidates_path(args):
    if getattr(args, "candidates", None):
        return os.path.abspath(args.candidates)
    from wgflib import paths
    from wgf_knowledge import ingest
    return os.path.join(paths.PROJECT, *ingest.CANDIDATES_FILE.split("/"))


def _load_candidates(args):
    from wgf_knowledge import ingest
    path = _candidates_path(args)
    try:
        return path, ingest.load_store(path)
    except ingest.IngestError as exc:
        raise Unusable(str(exc))


def cmd_ingest(args):
    from wgf_knowledge import ingest
    from wgflib.workflow.api import WorkflowAPI
    from wgflib.workflow.store import StoreError
    try:
        api = WorkflowAPI(config_path=args.config, store_dir=args.store)
        state = api.store.load(args.run)
        observations, problems = ingest.extract(
            state, lambda ref: api.store.read_artifact(state.run_id, ref))
    except (StoreError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise Unusable(f"run {args.run}: {exc}")
    except ingest.IngestError as exc:
        raise Unusable(f"run {args.run}: the run store is malformed - {exc}")
    path, store = _load_candidates(args)
    data, _ = _load(_root())
    updated, summary = ingest.ingest(store, observations, data["lessons"])
    written = False
    if not problems and not args.dry_run and updated != store:
        ingest.write_store(path, updated)
        written = True
    out = dict(summary, run=state.run_id, observations=len(observations),
               problems=problems, written=written, candidates=path)
    if args.json:
        _print_json(out)
    else:
        for problem in problems:
            print(f"refused  {problem}")
        print(f"{state.run_id}: {len(observations)} candidate observation(s); added "
              f"{', '.join(summary['added']) or '-'}; merged "
              f"{', '.join(summary['merged']) or '-'}; regression observations "
              f"{', '.join(summary['regressions']) or '-'}; unchanged {summary['unchanged']}")
        tail = (" (invalid candidates: fix the producer's report, or ingest nothing)"
                if problems else " (dry run)" if args.dry_run else "")
        print(f"{'wrote' if written else 'nothing written to'} {path}{tail}")
    return EXIT_PROBLEMS if problems else EXIT_OK


def _candidate_rows(store, evidence):
    from wgf_knowledge import ingest
    done = ingest.promoted(evidence)
    out = []
    for record in store["candidates"]:
        state = "promoted" if record.get("id") in done else record.get("state")
        out.append(dict(record, state=state, promoted_to=done.get(record.get("id"))))
    return out


def cmd_candidates(args):
    path, store = _load_candidates(args)
    data, _ = _load(_root())
    rows = _candidate_rows(store, data.get("evidence"))
    if args.open:
        rows = [r for r in rows if r["state"] == "open"]
    if args.json:
        _print_json({"candidates": rows, "regressions": store["regressions"], "file": path})
        return EXIT_OK
    print(f"{path}: {len(store['candidates'])} candidate(s), "
          f"{len(store['regressions'])} regression observation(s)")
    for r in rows:
        print(f"  {r['id']:<6} {r['state']:<9} {r['basis']:<10} {len(r['sources'])} source(s)  "
              f"{r.get('proposed_check') or '-'}  {r['summary'][:80]}")
    for r in store["regressions"]:
        print(f"  regression of {r['lesson']} ({r['check']}) in {r['source']['run']} "
              f"{r['source']['artifact_id']}")
    return EXIT_OK


def cmd_reject(args):
    import getpass
    from wgf_knowledge import ingest
    path, store = _load_candidates(args)
    try:
        updated = ingest.reject(store, args.candidate, args.reason,
                                args.by or getpass.getuser())
    except KeyError:
        raise Unusable(f"no candidate {args.candidate} in {path}")
    except ValueError as exc:
        raise Unusable(str(exc))
    ingest.write_store(path, updated)
    print(f"{args.candidate} rejected; kept in {path}")
    return EXIT_OK


def _scope_arg(values):
    scope = {}
    for value in values or ():
        key, _, rest = str(value).partition("=")
        if not key or not rest:
            raise Unusable(f"--scope {value!r} is KEY=V[,V..]")
        scope.setdefault(key.strip(), []).extend(v.strip() for v in rest.split(",") if v.strip())
    return scope


def cmd_promote(args):
    from wgf_knowledge import ingest, promote
    path, store = _load_candidates(args)
    record = next((c for c in store["candidates"] if c.get("id") == args.candidate), None)
    if record is None:
        raise Unusable(f"no candidate {args.candidate} in {path}")
    problems = ingest.store_problems(store)
    if problems:
        print(f"refused  {path} is not a valid candidate store (fix it before promoting): "
              + "; ".join(problems[:5]))
        return EXIT_PROBLEMS
    from wgflib import paths
    root = _root()
    if paths.INSTALLED or not os.path.isfile(
            os.path.join(root, *promote.EVIDENCE_PATH.split("/"))):
        raise Unusable("promote drafts a patch against the Factory repository itself "
                       f"({promote.LESSONS_PATH}, {promote.EVIDENCE_PATH}, scripts/tests/): run "
                       "it from a web-game-factory checkout - an installed plugin runtime does "
                       "not ship them")
    data, checks = _load(root)
    try:
        with open(os.path.join(root, *promote.LESSONS_PATH.split("/")),
                  encoding="utf-8") as handle:
            lessons_text = handle.read()
        with open(os.path.join(root, *promote.EVIDENCE_PATH.split("/")),
                  encoding="utf-8") as handle:
            evidence_text = handle.read()
    except OSError as exc:
        raise Unusable(f"the knowledge files cannot be read ({exc})")
    try:
        result = promote.draft(
            record, data["lessons"], lessons_text, evidence_text, checks,
            model.vocabulary(root), evidence=data.get("evidence"), lesson_id=args.id,
            level=args.level, check=args.check, category=args.category, title=args.title,
            scope=_scope_arg(args.scope) if args.scope else None,
            promoted=ingest.promoted(data.get("evidence")))
    except promote.PromoteRefused as exc:
        if args.json:
            _print_json({"refused": str(exc)})
        else:
            print(f"refused  {exc}")
        return EXIT_PROBLEMS
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(result.patch)
    if args.json:
        _print_json({"lesson": result.lesson, "evidence": result.evidence,
                     "files": sorted(result.files), "notes": result.notes,
                     "patch": result.patch, "out": args.out})
        return EXIT_OK
    if not args.out:
        sys.stdout.write(result.patch)
    for note in result.notes:
        print(f"# note: {note}", file=sys.stderr)
    print("# a draft for a pull request: apply it with `git apply`"
          + (f" {args.out}" if args.out else "")
          + ", write the stub tests, run check-integrity and `wgf knowledge firewall "
          f"{result.lesson['id']}`; nothing was written to core/", file=sys.stderr)
    return EXIT_OK


def cmd_firewall(args):
    from wgf_knowledge import firewall
    root = _root()
    if args.run:
        from wgflib.workflow.api import WorkflowAPI
        from wgflib.workflow.store import StoreError
        try:
            api = WorkflowAPI(config_path=args.config, store_dir=args.store)
            state = api.store.load(args.run)
            ref = state.latest_of_type("knowledge-contract")
            contract = api.store.read_artifact(state.run_id, ref) if ref is not None else None
        except (StoreError, OSError, ValueError, KeyError) as exc:
            raise Unusable(f"run {args.run}: {exc}")
        if contract is None:
            raise Unusable(f"run {args.run} has no knowledge-contract: run "
                           "`wgf knowledge firewall` for every lesson instead")
        lessons = firewall.suite_of(contract)
    else:
        data, _ = _load(root)
        lessons = data["lessons"]
    kinds = tuple(args.kind) if args.kind else model.TEST_KINDS
    try:
        report = firewall.run(lessons, root, ids=args.ids or None, kinds=kinds)
    except firewall.FirewallUnusable as exc:
        raise Unusable(str(exc))
    if args.json:
        _print_json(report)
    else:
        for line in firewall.render_lines(report):
            print(line)
    return EXIT_OK if report["verdict"] == firewall.PASS else EXIT_PROBLEMS


def cmd_generations(args):
    from wgf_knowledge import generations
    from wgflib.workflow.api import WorkflowAPI
    try:
        api = WorkflowAPI(config_path=args.config, store_dir=args.store)
    except (OSError, ValueError) as exc:
        raise Unusable(str(exc))
    entries, problems = generations.rows(api.store)
    groups = generations.generations(entries)
    if args.json:
        _print_json({"runs": entries, "generations": groups, "problems": problems})
    else:
        for line in generations.render_lines(entries, groups, problems):
            print(line)
    return EXIT_OK


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
    report = sub.add_parser("report", help="a run's knowledge compliance")
    report.add_argument("run", metavar="RUN_ID")
    report.add_argument("--store", metavar="DIR")
    report.add_argument("--config", metavar="PATH")
    form = report.add_mutually_exclusive_group()
    form.add_argument("--md", action="store_true", help="markdown, for a person")
    form.add_argument("--json", action="store_true")
    report.set_defaults(handler=cmd_report)
    table = sub.add_parser("table", help="the benchmark approval table (dry)")
    table.add_argument("--families", action="append", metavar="F,..")
    table.add_argument("--render", action="append", metavar="2d,3d")
    table.add_argument("--tiers", action="append", metavar="T,..")
    table.add_argument("--platform", action="append", metavar="ID")
    table.add_argument("--profiles", action="append", metavar="A,..",
                       help="complexity benchmark profiles (each requires budget approval)")
    table.add_argument("--phases", action="append", metavar="N,..",
                       help="roadmap phases (each requires budget approval)")
    table.add_argument("--facets", metavar="FILE",
                       help="candidate benchmarks: a list of {family, render, tier, platforms, "
                            "profile, phase, cost_estimate}")
    table.add_argument("--json", action="store_true")
    table.set_defaults(handler=cmd_table)

    def store_args(sub_parser):
        sub_parser.add_argument("--store", metavar="DIR")
        sub_parser.add_argument("--config", metavar="PATH")

    ingest = sub.add_parser("ingest", help="a run's lesson candidates into candidates.yaml")
    ingest.add_argument("run", metavar="RUN_ID")
    store_args(ingest)
    ingest.add_argument("--candidates", metavar="FILE")
    ingest.add_argument("--dry-run", action="store_true")
    ingest.add_argument("--json", action="store_true")
    ingest.set_defaults(handler=cmd_ingest)
    candidates = sub.add_parser("candidates", help="the stored lesson candidates")
    candidates.add_argument("--open", action="store_true")
    candidates.add_argument("--candidates", metavar="FILE")
    candidates.add_argument("--json", action="store_true")
    candidates.set_defaults(handler=cmd_candidates)
    reject = sub.add_parser("reject", help="a person rejects a candidate (kept)")
    reject.add_argument("candidate", metavar="C-N")
    reject.add_argument("--reason", required=True)
    reject.add_argument("--by", metavar="NAME")
    reject.add_argument("--candidates", metavar="FILE")
    reject.set_defaults(handler=cmd_reject)
    prom = sub.add_parser("promote", help="a candidate drafted as a lesson: a PR-ready patch")
    prom.add_argument("candidate", metavar="C-N")
    prom.add_argument("--id", metavar="L<n>")
    prom.add_argument("--level", choices=list(model.LEVELS))
    prom.add_argument("--check", metavar="SOURCE:ID")
    prom.add_argument("--category")
    prom.add_argument("--title")
    prom.add_argument("--scope", action="append", metavar="KEY=V,..")
    prom.add_argument("--out", metavar="FILE", help="write the patch here (else stdout)")
    prom.add_argument("--candidates", metavar="FILE")
    prom.add_argument("--json", action="store_true")
    prom.set_defaults(handler=cmd_promote)
    fw = sub.add_parser("firewall", help="every lesson's regression tests, run here")
    fw.add_argument("ids", nargs="*", metavar="ID")
    fw.add_argument("--run", metavar="RUN_ID", help="the run's contract's regression suite")
    store_args(fw)
    fw.add_argument("--kind", action="append", choices=list(model.TEST_KINDS))
    fw.add_argument("--json", action="store_true")
    fw.set_defaults(handler=cmd_firewall)
    gens = sub.add_parser("generations", help="runs compared by the knowledge they consumed")
    store_args(gens)
    gens.add_argument("--json", action="store_true")
    gens.set_defaults(handler=cmd_generations)
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
