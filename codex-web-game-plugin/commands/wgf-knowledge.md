# /wgf-knowledge (Web Game Factory)

**Transition** `read-only (ingest writes workspace/lessons/candidates.yaml)`
**Role** `-`


The Factory's knowledge and its learning loop through wgf knowledge - rules, a run's contract and compliance, lesson candidates, promotion drafts, the regression firewall, generations.

## Procedure

1. Read `core/lifecycle/` for the machine that owns this transition, and the
   `procedure` file named on the source state.
2. Read the `x-wgf` block of every artifact schema this transition produces or consumes.
3. Check the transition's guards before acting. A guard that cannot be evaluated is a
   blocker to report, not one to assume.
4. Run the `bin/wgf knowledge` subcommand the user asks for and report what it prints; see *The learning loop* below.
5. Write nothing yourself: only `ingest` and `reject` write, to the project's `workspace/lessons/candidates.yaml`; `promote` prints a patch for a person's pull request.

Commands map to transitions rather than to stages, so this file stays correct as long as
the machine does.

## The learning loop

Read `docs/knowledge-enforcement.md` before acting; it and `core/reference/lessons.yaml` are
authoritative over this section. Where `python3` is not on PATH (Windows), use `python` in its
place.

- **The rules.** `bin/wgf knowledge show [ID]` lists every lesson with its derived level;
  `resolve --family F --render R --platform P --tier T` the rules that apply to those facets;
  `validate` the model's own problems.
- **A run.** `bin/wgf knowledge contract <run-id>` is the knowledge-contract the run is held
  to; `report <run-id> [--md]` its compliance from the newest quality-report. An exception is a
  person's, granted only through `bin/wgf resume <run-id> --except ...`; never grant one.
- **Learning from a run.** `bin/wgf knowledge ingest <run-id>` collects the run's lesson
  candidates (specialist, triage, quality-report and reviewer) into the project's
  `workspace/lessons/candidates.yaml`: schema-checked, each with a root cause, de-duplicated,
  with the run, report and commit it came from. A candidate whose check an active lesson holds
  is recorded as that lesson's regression. `candidates [--open]` lists them; a person rejects
  one with `reject C-<n> --reason TEXT`.
- **Promotion is a person's pull request.** `bin/wgf knowledge promote C-<n> [--out FILE]`
  prints a patch - the lessons.yaml entry, the evidence.yaml entry, failing test stubs - and
  writes nothing to `core/`. A candidate whose evidence is only subjective (a review's
  comment) is never drafted blocking or required. Never apply the patch to `core/` yourself.
- **The firewall.** `bin/wgf knowledge firewall [ID ...] [--run <run-id>]` runs every lesson's
  catches (the check fails the defect), passes (it passes the fix) and generalizes tests; a
  missing or skipped test is never a pass. It needs a Factory checkout: an installed runtime
  does not ship the tests.
- **Generations and benchmarks.** `generations` compares runs by the Factory and knowledge
  versions they consumed; `table` is the dry benchmark approval table, in which every
  complexity profile and phase requires a person's budget approval. Neither starts a run.
