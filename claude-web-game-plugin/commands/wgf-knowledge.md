---
description: The Factory's knowledge and its learning loop through wgf knowledge - rules, a run's contract and compliance, lesson candidates, promotion drafts, the regression firewall, generations.
---

# /wgf-knowledge

**Not a transition** - read-only (ingest writes workspace/lessons/candidates.yaml)
**Role** `-`


The Factory's knowledge and its learning loop through wgf knowledge - rules, a run's contract and compliance, lesson candidates, promotion drafts, the regression firewall, generations.

## Procedure

1. Read `${CLAUDE_PLUGIN_ROOT}/runtime/docs/knowledge-enforcement.md` and `${CLAUDE_PLUGIN_ROOT}/runtime/core/reference/lessons.yaml`.
2. Run the `python3 "${CLAUDE_PLUGIN_ROOT}/runtime/scripts/wgf.py" knowledge` subcommand the user asks for and report what it prints; see *The learning loop* below.
3. Write nothing yourself: only `ingest` and `reject` write, to the project's `workspace/lessons/candidates.yaml`; `promote` prints a patch for a person's pull request.

This command moves no lifecycle state, answers no gate and grants no exception.

## The learning loop

Read `${CLAUDE_PLUGIN_ROOT}/runtime/docs/knowledge-enforcement.md` before acting; it and `${CLAUDE_PLUGIN_ROOT}/runtime/core/reference/lessons.yaml` are
authoritative over this section. Where `python3` is not on PATH (Windows), use `python` in its
place.

- **The rules.** `python3 "${CLAUDE_PLUGIN_ROOT}/runtime/scripts/wgf.py" knowledge show [ID]` lists every lesson with its derived level;
  `resolve --family F --render R --platform P --tier T` the rules that apply to those facets;
  `validate` the model's own problems.
- **A run.** `python3 "${CLAUDE_PLUGIN_ROOT}/runtime/scripts/wgf.py" knowledge contract <run-id>` is the knowledge-contract the run is held
  to; `report <run-id> [--md]` its compliance from the newest quality-report. An exception is a
  person's, granted only through `python3 "${CLAUDE_PLUGIN_ROOT}/runtime/scripts/wgf.py" resume <run-id> --except ...`; never grant one.
- **Learning from a run.** `python3 "${CLAUDE_PLUGIN_ROOT}/runtime/scripts/wgf.py" knowledge ingest <run-id>` collects the run's lesson
  candidates (specialist, triage, quality-report and reviewer) into the project's
  `workspace/lessons/candidates.yaml`: schema-checked, each with a root cause, de-duplicated,
  with the run, report and commit it came from. A candidate whose check an active lesson holds
  is recorded as that lesson's regression. `candidates [--open]` lists them; a person rejects
  one with `reject C-<n> --reason TEXT`.
- **Promotion is a person's pull request.** `python3 "${CLAUDE_PLUGIN_ROOT}/runtime/scripts/wgf.py" knowledge promote C-<n> [--out FILE]`
  prints a patch - the lessons.yaml entry, the evidence.yaml entry, failing test stubs - and
  writes nothing to `${CLAUDE_PLUGIN_ROOT}/runtime/core/`. A candidate whose evidence is only subjective (a review's
  comment, or a finding no gate of that run recorded on that build) is never drafted
  blocking or required. Never apply the patch to `${CLAUDE_PLUGIN_ROOT}/runtime/core/` yourself. Promote drafts against
  the Factory repository's own `lessons.yaml`, `evidence.yaml` and tests, so it runs only
  from a web-game-factory checkout; from an installed plugin it refuses and says so, while
  `ingest`, `candidates` and `reject` work in the project.
- **The firewall.** `python3 "${CLAUDE_PLUGIN_ROOT}/runtime/scripts/wgf.py" knowledge firewall [ID ...] [--run <run-id>]` runs every lesson's
  catches (the check fails the defect), passes (it passes the fix) and generalizes tests; a
  missing or skipped test is never a pass. It needs a Factory checkout: an installed runtime
  does not ship the tests.
- **Generations and benchmarks.** `generations` compares runs by the Factory and knowledge
  versions they consumed; `table` is the dry benchmark approval table, in which every
  complexity profile and phase requires a person's budget approval. Neither starts a run.
