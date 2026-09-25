# Where the game checkout is

Seven steps work in a title's game repository: `init` (which creates it), `assets` (when it
writes into it), `develop`, `review` / `sdk-review`, `sdk`, `verify` and `release`. They all
find it the same way, in `scripts/wgflib/checkout.py`, and while one of them works in it no
other run can.

## One precedence

| # | Rule | Names |
|---|---|---|
| 1 | The step's `with: repo_dir` (alias `game_repo`) | the checkout itself |
| 2 | `WGF_GAME_REPO` | the checkout itself, for every step |
| 3 | scaffold-record `repository.local_path` | where init put it, if that path exists here; a missing one is skipped with a warning |
| 4 | `factory.checkouts` + `<repository name>` | the checkouts directory joined with the scaffold-record's `repository.name` (init: the name it is about to create) |

The first rule that names a path decides. No step falls through to a later rule because the
path it was given is empty or missing: `verify` and `release` report the checkout missing,
naming the rule; `develop` and `review` block; `sdk` blocks with "platform not configured".
Only a recorded `local_path` that does not exist is skipped, because a run can be resumed
on another machine.

Every relative path resolves against the Factory root, never the working directory:
`WGF_GAME_REPO=../neon-drift` means the same place from wherever `wgf` runs. A repository
name read from a scaffold-record must be one plain directory entry (`paths.checkout_path`),
whichever rule decides: a record naming `..` is refused outright.

### Configuration

```yaml
factory:
  checkouts: ..        # <checkouts>/<repository name>; relative to the Factory root
```

`factory.checkouts` replaced six per-module keys. They still work, as deprecated aliases,
read in this order when `factory.checkouts` is unset. The first one set is used by **every**
step; any other that names a different directory is warned about and ignored:

1. `develop.checkouts`
2. `init.projects_dir`
3. `review.checkouts`
4. `sdk.games_dir`
5. `verification.checkouts`
6. `release.checkouts`

`sdk.game_repo` named one checkout for the sdk step only. It still does, after
`WGF_GAME_REPO`, with a deprecation warning; use the step's `with: game_repo` or
`WGF_GAME_REPO` instead. A step's own `with: checkouts` (or `games_dir`) overrides the
checkouts directory for that step.

Migration: set `factory.checkouts` and delete the per-module keys.

### What init records

The scaffold-record (schema 1.2.0) carries `repository.local_path`: relative to the Factory
root (`../neon-drift`) when the checkout is beside the Factory - anywhere under the
Factory's parent directory, the default layout - and absolute otherwise. Relative, so a run
resumed on another machine with the same layout finds it; absolute when relative would mean
`../../../tmp/...`, which is meaningless anywhere else too. Records written before 1.2.0 have
no `local_path` and resolve by rule 4.

## One run per checkout at a time

A step holds an advisory lock on the checkout for as long as its execute runs:
`<storage>/checkouts/<sha256 of the checkout's real path>.lock`, naming the process (pid and
start time, as the run lock does) and the run. A second run that reaches the same checkout
while the first is inside a step gets BLOCKED, with the holding run named; resume it once
that step has finished. The same run is never refused - a resumed or continued run, or a
nested hold. A holder whose process is dead, or whose pid now belongs to another process,
is taken over.

The lock covers a step, not the whole run: two runs on one title can still alternate
between steps. Review, sdk, verify and release each check the commit they are given against
the checkout's HEAD (review's subject, sdk's prototype commit, verify's and release's
lineage), so an interleaving that moved HEAD is refused rather than mixed into evidence;
develop builds on whatever HEAD it finds and records it as the baseline. Do not continue
two runs of one title at once.

`assets` takes the lock only when it writes into the checkout. A step run outside a run
store (a unit test's bare context) takes none.

## Assets reach the game

With a scaffold-record in the run and the checkout on disk, the `assets` step writes into
`<checkout>/public/assets/` - `public/` is a `develop.writable_paths` entry, so the
development commit includes the files - and the develop brief lists each asset's
repository-relative file paths for the developer to load. `factory.assets.root` still
overrides it. Without a scaffold-record, or before the checkout exists, assets go to
`.factory/assets/<title>` under the Factory root: git-ignored scratch that no build sees.
