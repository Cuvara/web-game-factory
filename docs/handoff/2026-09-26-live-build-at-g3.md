# Handoff: live production run stopped in develop visit 1 (2026-09-26)

A checkpoint of branch `fix/live-agent-reproducibility`, not a release. `v2.0.0` (`5b74e30`)
and `main` are untouched. The run below was stopped by hand before the machine was shut down;
it is **not complete** and **not portable** as it stands.

## Where the run is

| | |
|---|---|
| Run ID | `new-game-20260926-192631-341e1b` (workflow `new-game` v2, project `tower-merge-rush`) |
| Code | branch `fix/live-agent-reproducibility`, the commit before this one (`d04a5b9`): the candidate fixes on top of `5b74e30` |
| Config | written by `python3 scripts/golden/live.py config --workdir /home/duycuong/wgf-live-build --human-gates`: the golden 2D inputs; developer and reviewer = the examples `workspace/config/factory.yaml` documents, verbatim (Claude Code 2.1.280, `--model sonnet`; developer 400 turns / US$40 / 5400 s / idle 900 s, reviewer 60 turns / US$5 / 1800 s); no gate auto-approved |
| Started | 2026-09-26T19:26:31Z |
| research, strategy | completed |
| G2 `strategy-review` | **approved** 2026-09-26T19:38:10Z, decided by the user (`mode: human`), relayed by the operating agent |
| design, tech-plan | completed |
| G3 `tech-plan-review` | **approved** 2026-09-26T19:39:33Z, decided by the user (`mode: human`), with this note recorded in the decision: the design (the `merge-puzzle` archetype: a 7x7 swap-and-match level game) contradicts the approved strategy's concept (one-tap drop-merge on a seven-column track), and the design consistency check does not compare them; approved so the live developer/reviewer loop could be validated on an internally consistent brief |
| init | completed (local source, template pin `bca41a9`; game checkout commit `7cde9ef`) |
| assets | completed |
| develop visit 1, attempt 1 | **interrupted**. The live Sonnet developer started 19:39:34Z and ran about 2 min 20 s; it was stopped by SIGTERM to the workflow driver (pid 480665) at about 19:41:57Z. The whole process tree ended (driver and developer child confirmed gone); no agent or workflow process is running. Nothing was committed by develop: the game checkout is still at the init commit with the brief, the seam file and the placeholder assets untracked |
| review, sdk, sdk-review, verify, G4, release | **not run** |
| Stored status | `RUNNING` with liveness `stale` (the driver is gone). `wgf status` says so |

## Resuming

- **On this machine**, `bin/wgf resume new-game-20260926-192631-341e1b --config
  /home/duycuong/wgf-live-build/factory.yaml --store /home/duycuong/wgf-live-build/factory-store`
  would take over the stale run and run develop visit 1 **again from the beginning** (the
  engine re-runs an interrupted step; nothing before it). Treat the partial developer session
  as discarded: its edits were never committed. Resuming starts paid agent work.
- **On another machine, it is not resumable by copying the store.** The config, the state,
  the scaffold record and the artifacts name absolute paths under
  `/home/duycuong/wgf-live-build` and `/home/duycuong/.cache/wgf/templates/`, and the game
  checkout (`games/tower-merge-rush`) is not in this commit: it is game source, which the
  Factory repository never holds. Reproducing the run elsewhere means starting a new one from
  this branch with the same command (`live.py config ... --human-gates`, then `bin/wgf
  new-game --config ... --store ... --project tower-merge-rush`) and deciding G2 and G3 again;
  research, strategy, design and tech plan come out the same from the frozen golden inputs.

## The forensic archive

`2026-09-26-live-build-at-g3.run-store.tar.gz` (sha256
`b59ba322958d163d87a5c6ca06d86f3e911cdcafddef6d7854abd002a57b44da`) is a **diagnostic copy
only - machine-specific, not portable resume state**. It holds `factory-store/` (state,
events, every artifact, the interrupted developer's log), `evidence/` (the argvs as run, the
host version, the CLI transcripts) and `factory.yaml`. It does not hold the game checkout.

It is **redacted**: this repository is public, so the user's e-mail address, which the two
decision notes and the events that carry them recorded, is replaced by `<user>` in
`state.json`, `events.jsonl` and both decision records. Those two records therefore no longer
match their recorded content hashes; the unredacted originals stay on the machine the run
was made on. No credential was found in the store (the host authenticated from its login
under `HOME`; `apiKeySource: none`).

## Open findings this run was meant to settle

- Whether a live developer -> reviewer loop converges on a game built from the brief: **not
  yet known** - the run was stopped before the first review.
- New: the design step turned an approved drop-merge strategy into a swap-and-match design
  and passed its own consistency check (above; also CHANGELOG "Known").
