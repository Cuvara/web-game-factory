# MV-4 — what the real world said

MV-4 ran on branch `mv-4/real-world-evidence` from `9fd21f0` (Factory 2.2.0). `main`, `v2.2.0`
and every existing tag are untouched. The plan and its acceptance criteria are in
[mv-4-plan.md](mv-4-plan.md); the protocols are in [mv-4-playtest-protocol.md](mv-4-playtest-protocol.md)
and [mv-4-touch-sheet.md](mv-4-touch-sheet.md); the evidence files are under
[evidence/mv-4/](evidence/mv-4/).

**Headline.** The Factory's output runs, and runs well, in a real browser on the bytes it would
ship. Three of the four kill criteria could not be measured: there was no Android handset and
no first-time player. One thing the real portal SDK showed is new and material — the time to
interactive the verification step records is measured with the portal SDK blocked, and with the
real SDK served the same build took 5.24 s, past the 5 s the platform profile asserts. MV-4 also
found that the Factory's own test suite does not run on Windows, fixed the five defects behind
that which were the Factory's own rather than its fixtures' - two of which stopped the golden
run's developer before it could build anything - and left the rest recorded. The Windows
baseline went from 70 failures and 37 errors to 27 and 17, with nothing new failing.

## 1. The audit, and what MV-3 left open

| What 2.2.0 said was not covered | Still open after MV-4 |
|---|---|
| Other portals' packages need a build of their own | **Open.** The Factory still pins template `v1.1.0` (`bca41a9`), which is contract 1: `pnpm build` makes one bundle and `build:platforms` does not exist in it. The sibling working copy at `268631d` has `wgf.template.contract: 2` and `build:platforms`, so the capability exists in the template and is not pinned. |
| Device performance is a desktop proxy (`PASS_MOCK`) | **Open, and now measured as such.** No handset was reachable; `policy.device-performance` is still `PASS_MOCK` by construction, and MV-4 adds a device measurement path that refuses to produce a device result without a device. |
| Portal behaviour, submission, publishing | **Open (BLOCKED_EXTERNAL).** No portal account. MV-4 did establish, with the real SDK, what can be established without one. |
| The kill criteria stay unmeasured | **Three of four still unmeasured.** Criterion 3 (timebox) has a run record; 1, 2 and 4 do not. |

Two further things the audit established, which were not in 2.2.0's list:

- **`../tower-merge-rush` is not current Factory output.** Its initial commit
  (`683b258`, 2026-09-23) was generated from template version `0.1.0`, before the pin: its
  `package.json` differs from `bca41a9`'s, and it has no `sdk:check`, no `build:platforms` and
  no `packages/platform-sdk/sdk-signatures.json`. It is a real, complete, playable game the
  Factory produced, and MV-4 measures it as that — but it is evidence about the Factory of
  September 23, not about the pinned template.
- **`PASS_MOCK` was not treated as device evidence anywhere in the code** — the verify step's
  `_device_performance` hard-codes `evidence_status=PASS_MOCK` and cannot be argued up. That
  part of MV-3 holds.

## 2. Real-device results (criteria A, B)

**UNVERIFIED.** `python scripts/mv4/device.py --detect` recorded
`evidence/mv-4/device/device-session.json`:

> `"status": "UNVERIFIED"`, `"measurement_class": null`,
> `"reason": "adb is not installed on this machine, so no handset can be reached from it"`

No physical Android device was available for this run, and the repository owner confirmed there
is none. Criterion A (real mobile performance) and criterion B (real touch) are therefore
UNVERIFIED. Nothing else was promoted in their place:

- the proxies that were taken are labelled `emulated-mobile` and are recorded in the browser
  session below, not in the device file;
- `scripts/mv4/device.py --record` refuses a capture that does not carry the handset's own
  model, Android version, browser version and screen, and refuses a sample shorter than 60 s;
- `scripts/mv4/g4.py` refuses to let an `emulated-mobile` measurement decide criterion 4. The
  regression tests for all three refusals are in `scripts/tests/test_mv4.py`.

When a handset appears, the path is: `python scripts/mv4/device.py --instructions --url <url>`
prints the serve step and the on-device capture snippet; `--record capture.json` turns it into a
`real-device` measurement and decides criterion A on the thresholds fixed in the plan
(median ≥ 30 fps, p95 ≤ 50 ms, no 5 s window below 25 fps).

## 3. Real browser results (criterion C)

`python scripts/mv4/session.py --repo ../tower-merge-rush --out docs/evidence/mv-4/browser`
Commit `072ed75`, fresh build, target platform **poki**, artifact
`sha256:c4754ea4ec2a86368ceeff163a9c7abd4c2db603a02e724f6470028443d93ecc`. Headed Chromium,
`--enable-precise-memory-info`, 20 s of continuous play driven from inside the page, every
external request aborted and recorded. Full record:
`evidence/mv-4/browser/browser-session.json`.

| | desktop-real | mobile-emulated | mobile-emulated-throttled (4×) |
|---|---|---|---|
| `measurement_class` | `real-browser-desktop` | `emulated-mobile` | `emulated-mobile` |
| Time to interactive | 0.242 s | 0.239 s | 0.419 s |
| Median frame rate | 200 fps | 100 fps | 100 fps |
| p95 frame time | 5.1 ms | 10.2 ms | 10.1 ms |
| Worst 1 s window | 188 fps | 117 fps | 119 fps |
| JS heap, run 1 → run 2 | 7.38 → 7.39 MB | 7.50 → 6.91 MB | 7.48 → 7.81 MB |
| Page errors | none | none | none |

Checks, identical across the three sessions except where noted:

| Check | Result |
|---|---|
| `boot` | PASS |
| `time_to_interactive` (≤ 5 s) | PASS |
| `sustained_frame_rate` (≥ 30 fps median) | PASS |
| `audio_unlocks_on_gesture` | PASS — no `AudioContext` existed before the first gesture, one in state `running` after |
| `survives_resize` | PASS — simulation kept stepping across a 40% width change |
| `survives_orientation_swap` | PASS — kept stepping across a portrait/landscape viewport swap, one canvas |
| `game_over_reached` | PASS — two full runs driven to game-over and restarted |
| `no_leak_across_restart` | PASS — two equivalent runs, one game-over and restart apart, within 1.5× |
| `recovers_after_return` | PASS |
| `telemetry_collected` | PASS |
| `pauses_when_hidden` | **UNVERIFIED** |
| `mute / unmute` | **UNVERIFIED** — the template has no in-game mute; mute is portal-driven (`platform.settings.muteAudio`), so it needs a portal |

Three notes on how to read this, because the numbers are easy to over-read:

- **These frame rates are the display's, not a headroom measurement.** The desktop session
  rendered at this machine's refresh rate (200 Hz) throughout; the two device-descriptor
  sessions sit at exactly half that, which is the descriptor's own frame cap, not the game
  reaching a limit. A 4x CPU throttle moved the median not at all and the worst one-second
  window from 117 to 119 fps. This hardware never put the game under frame-budget pressure, so
  the sample says the game is cheap here and says nothing about a handset. The figures also move
  between runs with the build unchanged, which is the other reason not to read them as a
  property of the game. An earlier sample, taken while the harness drove the game through a CDP
  round trip every 250 ms, read a suspiciously exact 30.03 fps - it was measuring the harness.
  The play loop runs inside the page now.
- **The leak check needed correcting before it said anything true.** The first version compared
  the heap just after boot against the heap after a played, restarted run, and reported a FAIL
  on two of three projects. That compares two different games. Corrected to compare two
  equivalent runs one game-over apart, the same build passes on all three. The wrong version's
  output is not reported as a finding; the method is recorded in the evidence file.
- **`pauses_when_hidden` is UNVERIFIED, not PASS.** Four ways to background the page from
  outside it were tried, and every one left `document.visibilityState` at `"visible"`, so the
  pause-on-hidden path was never entered and nothing was measured. Each attempt and its outcome
  is recorded in the session's `hide_attempt` field:

  | # | Method | Outcome |
  |---|---|---|
  | 1 | `context.newPage()` + `bringToFront` | a second *window*; both stay visible |
  | 2 | `Browser.setWindowBounds { minimized }` on the page's CDP session | rejected — `No web contents in the target`; `Browser.*` belongs to the browser target |
  | 3 | the same on a browser CDP session with the page's `targetId` | accepted, window minimised, page still `"visible"` (rAF did throttle to ≈10 Hz) |
  | 4 | a second *tab* in the page's own window (`Target.createTarget` + `activateTarget`) | `Failed to open new tab - no browser is open`: Playwright launches with `--no-startup-window`, so there is no tab strip. Dropping that flag made the tab open — and the page still reported `"visible"`, while the browser closed under the third project mid-sample. The flag is kept; losing a session is worse than a check that says UNVERIFIED |

  The game's own e2e suite (`tests/e2e/tower-merge-rush.spec.ts`) covers the behaviour by
  redefining `document.visibilityState` and dispatching the event — a stand-in, not a hidden
  tab. **Nothing in this stack has tested a genuinely hidden tab**, which matters because a real
  pause bug was found by the live reviewer in the 2.1.2 production run. What is left is a real
  browser driven by a person: the developer playtest sheet's `tab_away_and_back` line.

## 4. Real platform integration results (criterion D)

`python scripts/mv4/session.py ... --allow-host game-cdn.poki.com --allow-host a.poki.com`,
one desktop session, recorded in `evidence/mv-4/platform/browser-session.json`. This is the one
deliberately outward-facing step MV-4 took: two GETs to the portal's own CDN, no credentials, no
account, no ad requested, nothing submitted.

| Check | Result | Evidence |
|---|---|---|
| `portal_sdk_script_served` | **PASS** | `https://game-cdn.poki.com/scripts/v2/poki-sdk.js` → 200, and its core bundle `poki-sdk-core-832e4f21….js` → 200 |
| `boots_with_the_portal_script_present` | **PASS** | the build reached ready with the real SDK on the page |
| Runs without the portal SDK (fallback) | **PASS** | in the three sessions of section 3 the SDK request was aborted and the game booted anyway |
| `time_to_interactive` | **FAIL (5.236 s vs the profile's 5 s)** | see below |
| Ad lifecycle, mute/unmute from the portal, save through the portal, lifecycle acceptance, review | **BLOCKED_EXTERNAL** | no account and no registered game; no ad was requested, deliberately |

**The finding.** With the portal SDK blocked, this build reports 0.22–0.25 s to interactive.
With the real SDK served, the same build reports **5.236 s** — past the 5 s that
`core/reference/platforms/poki.yaml` asserts as `poki_time_to_interactive`. The template's fact
collection (`tests/verify/facts.spec.ts`) blocks portal SDK requests by design — "What the
portal's own script does is the portal's QA step, not a package fact" — so **the number the
Factory records for that assertion is measured in a configuration no player is ever in**.

Two honest qualifications, neither of which removes the finding:

- In this session the SDK's own sub-resources were still blocked (8 aborted requests:
  `ads.poki.com`, `geo.poki.io`, `securepubads.g.doubleclick.net`, `imasdk.googleapis.com`,
  prebid, Amazon's `apstag`, two SVG icons). Some of the 5.2 s is the SDK retrying against a
  blocked network, and a real portal page would fetch them. The measurement is not a production
  TTI.
- It does show that the gap between "SDK blocked" and "SDK present" is the difference between
  0.25 s and something past the profile's own limit. A number taken with the SDK absent cannot
  be compared against an assertion about the loaded game, in either direction.

The page also recorded two `Failed to fetch` page errors, both from the SDK's blocked
sub-resources, not from the game.

**Platform documentation requirements are recorded separately, and MV-4 makes no legal claim.**
The Factory's own Poki profile carries `status: unverified` and says its figures "are starting
values to be corrected from portal documentation". Nothing in `core/` or `docs/` records a web
exclusivity requirement for any portal; MV-4 did not read portal terms and does not assert what
they say. What MV-4 can state is technical and is in section 6: the three packages this release
produces are byte-identical, so submitting them to three portals would be submitting one
artifact three times. Whether that is permitted is a portal-terms question the repository does
not currently answer, and it should be answered from the portal's own documentation before any
submission.

## 5. Playtest results (criterion E) and the kill criteria

**No first-time player was available**, so criteria 1 and 2 are UNVERIFIED.
`evidence/mv-4/playtest-summary.json`:

```
first_time_players: 0     developer_tests: 0     minimum_for_a_share: 5
control_not_understood: UNVERIFIED   no_retry_pull: UNVERIFIED
```

A developer test by the repository owner is prepared but not yet run: the protocol is in
[mv-4-playtest-protocol.md](mv-4-playtest-protocol.md) and the sheet to fill in is
`evidence/mv-4/playtest-sheet-dev-01.template.yaml`. By the owner's instruction and by the
protocol it is classified `developer-test` and **does not count towards either criterion**;
`scripts/mv4/playtest.py` enforces that — a sheet with `prior_knowledge: yes` is excluded from
both shares whatever its own label says, and a share is not reported at all below five
first-time participants. Both rules have regression tests.

### The four kill criteria (criterion G)

`evidence/mv-4/g4-evidence.json`. Verified by automated/technical evidence, verified by the
developer test, and still unverified — kept apart, as asked:

| # | Criterion | Status | Class | What it rests on |
|---|---|---|---|---|
| 1 | Fewer than 60% of first-time players understand the control | **UNVERIFIED** | — | 0 first-time participants; 5 is the minimum |
| 2 | Fewer than 50% retry without being prompted | **UNVERIFIED** | — | as above |
| 3 | The prototype exceeds the allowed timebox | **NOT MET** | `run-record` | 2.5 days planned against 10.5 allowed, from the production run `new-game-20260927-123223-371104` ([handoff](handoff/2026-09-27-production-validation.md)) |
| 4 | Mobile performance below 30 FPS on a mid-range mobile browser | **UNVERIFIED** | — | no device. The proxies (200 fps desktop, 200 fps emulated, 78 fps worst 1 s window under a 4× throttle) are retained in the file as `proxies_recorded_but_not_deciding` |

1. **Verified by automated/technical evidence:** criterion 3, and the whole of section 3's
   browser checks and section 6's package checks.
2. **Verified by the developer test:** nothing yet — the test has not been run. When it is, it
   will carry the observations in the sheet, and nothing more.
3. **Still UNVERIFIED for want of first-time participants:** criteria 1 and 2. For want of a
   handset: criterion 4, and criterion B entirely.

**G4 is not decided by this report.** Three of four criteria have no measurement of a class that
can decide them, and `core/lifecycle/stages/prototype-review.md` reserves the decision for a
person: "an inconclusive on a central question is an argument for iterate, not for pass."

## 6. Release and package evidence (criterion G, section 7 of the brief)

`python scripts/mv4/packaging.py --checkout … --release r90` on the fresh build of `072ed75`.
Record: `evidence/mv-4/packaging/packaging.json`.

| Question | Answer |
|---|---|
| Build target | `poki` — the first platform whose role is exactly `required` (template contract 1.0.0's own rule, `wgflib.template_contract.build_target`) |
| Required platform's package exists | **Yes** — `poki.zip`, 0.288 MB |
| Recorded checksum matches the bytes | **Yes**, for all three packages |
| `checksums.txt` matches the bytes | **Yes**, for all three |
| Manifest matches the artifacts | **Yes** — `manifest.json` names exactly `crazygames`, `poki`, `yandex`, version `0.1.0` |
| Non-target packages | **Produced by the repository's own script**: `crazygames.zip` and `yandex.zip` |
| Are the packages different artifacts | **No.** All three have payload digest `sha256:c185222764ee…` and the same sha256. One bundle, three filenames |

This is MV-3's premise, reproduced from the outside: on the pinned contract the repository's own
`release:package` packages every declared platform from one bundle, and the Factory's release
step is what prunes the ones the build does not target (`wgf_release`, 2.2.0; `test_core_release`
covers the pruning and the refusal of a foreign package). The distinction matters because a game
repository can also be released from its own workflow, where nothing prunes.

Two gaps in this evidence, stated rather than papered over:

- **Which portal SDK each package's bundle references was not scanned.** The scan needs
  `packages/platform-sdk/sdk-signatures.json`, which this repository (template 0.1.0) does not
  ship; the pinned template does. The report records `sdk_signatures_in_bundle: null` with that
  reason rather than an empty result, which would have read as "none found".
- The runtime evidence for what the bundle actually targets is section 3's: every session's
  build requested `https://game-cdn.poki.com/scripts/v2/poki-sdk.js` and nothing else external.
  A `crazygames.zip` with those bytes would request the Poki SDK on CrazyGames.

## 7. Telemetry evidence (criterion F)

Kept in three separate kinds, by name, as the plan requires:

- **Test telemetry — collected, PASS.** `evidence/mv-4/browser/telemetry.jsonl`, one record per
  session, each naming its commit, artifact sha256 and `measurement_class`. The counters are
  read out of the running build through its own read-only probe (`window.__wgf__`); nothing was
  added to the bundle and the game was not modified. Every session:
  `loadingProgressCalls: 5`, `signalReadyCalls: 1`, `adsRequested: {0,0,0}`,
  `adsShown: {0,0,0}`, ~6 100 frames, ~31 s elapsed.
- **Production telemetry — absent, and recorded as absent.** The game emits its events into
  `new Analytics({ sink: new NullSink() })` (`src/platform/integration.ts`), which discards
  them. Nothing the shipped game emits reaches any destination. MV-4 did not build one: the
  measurements MV-4 needed were available from the probe without one, and a destination is a
  product decision, not an evidence-gathering one.
- **Mocked telemetry — not used as evidence.** The unit suites observe events against stand-in
  sinks; that is evidence about a code path and is not cited anywhere in this report.

**A finding inside the telemetry.** Every session reports `gameplayStartCalls: 0` and
`gameplayStopCalls: 0` after two full runs, two game-overs and three restarts — while
`loadingProgressCalls` and `signalReadyCalls` are recorded normally. The cause is in the
template, not the game: `UsageRecorder.recordGameplayStart` / `recordGameplayStop` are called by
the `generic-web` adapter and **not by the `poki` adapter**, which forwards the calls to the SDK
(`#send`) without recording them. In the pinned template `bca41a9` the same is true of
`poki`, `yandex` and `gamevui`; only `generic-web` and `gamemonetize` record them. Consequence:
on the required platform, the gameplay lifecycle is invisible to every fact, assertion and probe
reading that counts — the game may be reporting gameplay correctly, as this one is, and the
evidence cannot show it. Not fixed here: it is a `web-game-template` defect and this branch
changes no game or template source.

## 8. Factory bugs discovered and fixed

All three were found by running the existing suite on Windows, all three have regression
coverage, and none weakens an existing test.

1. **A path guard that failed open, and differently per host** —
   `scripts/wgf_review/verdict.py`. A reviewer's verdict is untrusted agent output, and the
   `blockers[].file` guard was `os.path.isabs(...) or ".." in path.split("/")`. `os.path.isabs`
   is the host's rule, and the host's rule moved: on Windows with Python 3.13 and later
   `/etc/passwd` is drive-relative, not absolute, so the guard **accepted `/etc/passwd`** there
   while refusing it on Linux. On POSIX the same guard accepted `C:\Windows\x` and
   `..\..\secrets.env`, because neither is absolute there and neither splits on `/`.
   Fixed by judging the string, not the host: `wgflib.paths.repo_relative` refuses a leading
   separator of either kind, a drive, and `..` on either separator.
   Regressions: `test_core_security.HostileIdentifiers.test_a_repository_path_is_judged_the_same_on_every_host`
   and `…test_a_reviewer_cannot_name_a_file_outside_the_repository`. This also repaired three
   suite failures that were already there: `test_core_security.test_a_verdict_cannot_point_a_blocker_outside_the_repository`,
   `test_review_module.Refusals.test_blockers_shape`, `test_core_agents.VerdictContract.test_refusals`.
2. **No child process could be started on Windows** — `scripts/wgflib/procs.py`. A shell applies
   `PATHEXT`; `CreateProcess` does not. `pnpm` is installed as `pnpm.CMD`, so every
   `procs.run(["pnpm", …])` failed with `FileNotFoundError: [WinError 2]` before the child
   existed, and the step reported a plainly-installed tool as not startable
   (`release refused: [package-failed] 'pnpm run release:package --release r1' could not be
   started`). Fixed by resolving `argv[0]` on the child's own `PATH` with `shutil.which` when it
   has no directory part; POSIX is untouched, and a name that resolves to nothing is left as
   given so the caller's error still names what was asked for. The first version of this fix was
   itself wrong, in a way the golden run found: `shutil.which` answers "exists and is
   executable", and a *directory* of the same name on the child's `PATH` satisfies both, after
   which `CreateProcess` fails with `NotADirectoryError: [WinError 267]` — which reads as a
   broken working directory rather than a bad lookup. Only a file is accepted as a program now.
   Regressions: `test_core_process.ResolvingTheProgram` — five cases, plus one that simply
   starts an installed tool, which is the thing that was impossible.
3. **An agent could not start a tool at all on Windows** — `scripts/wgflib/agentenv.py`. The
   agent environment is an allowlist, and the allowlist held only the POSIX names. Without
   `SystemRoot` no child starts on Windows, because `pnpm` is `pnpm.CMD` and is started through
   the command processor: every golden run's developer refused with
   `pnpm install --offline --no-frozen-lockfile failed (not-started): NotADirectoryError:
   [WinError 267]`, on every attempt, and the run stopped at `develop` with the repository
   scaffolded and nothing built. The same basics are now allowlisted under the names Windows
   uses — `SystemRoot`, `windir`, `COMSPEC`, `PATHEXT`, `SystemDrive`, the Program Files and
   ProgramData locations, and `USERPROFILE` / `APPDATA` / `LOCALAPPDATA`, which are `HOME`
   there. None of them carries a credential and the secret-name filter over prefixes is
   untouched. Names are also compared the way the platform compares them: Windows upper-cases
   environment names, so an allowlist spelled `SystemRoot` matched nothing.
   Regressions: `test_core_security.AgentEnvironment` — an agent can start a tool at all; the
   allowlist is matched the way the platform matches names; a secret is still dropped with the
   base names widened.
4. **The refusing proxy was not refusing, and said nothing about it** —
   `scripts/wgflib/netguard.py`. The guard is set through the proxy environment variables, which
   Chromium reads on Linux and ignores everywhere else in favour of the system configuration. On
   Windows the develop step's smoke check therefore loaded a portal's real SDK from its CDN and
   failed on the `http://` ad bridge it pulled in — while the guard's own summary reported
   `refused_requests: 0`, which reads as isolation. Every summary now carries `enforced` and,
   when false, the reason, so zero refusals means "nothing tried" where the guard holds and
   "nothing was routed here" where it does not. The proxy is unchanged; what changed is that a
   caller can no longer read silence as safety. Making it hold on Windows needs the proxy passed
   to the browser at launch, which is the game repository's Playwright configuration, not the
   Factory's. Regression: `test_netguard.Enforcement`.
5. **A finished run's report was lost to the console's encoding** — `scripts/wgf.py`. Anything
   the CLI prints can carry a character the console cannot encode: a tool's output quoted in a
   failure detail, a package manager's thin space. On cp1252 - the Windows default - that
   raised `UnicodeEncodeError` *after* all the work was done and printed nothing at all: a
   whole `bin/wgf test-core --json` run was lost to
   `'charmap' codec can't encode character ' '`. The CLI's streams now escape what they
   cannot encode instead of raising. Regression: `test_workflow_cli.ConsoleEncoding`.
6. **A run record that differed by host** — `scripts/golden/live.py` recorded
   `os.path.relpath(...)`, so a record written on Windows said `workspace\config\factory.yaml`
   where one written on Linux said `workspace/config/factory.yaml`. Records are compared across
   machines; a separator is not part of what the path names. Fixed to `paths.display`.
   Regression: the existing `test_live_loop.LiveConfig.test_both_agents_are_the_documented_ones_verbatim`,
   which was failing.

## 9. Factory bugs discovered and not resolved

1. **The suite does not fully run on Windows.** On this machine,
   `python -m unittest discover scripts/tests` ends
   `FAILED (failures=27, errors=17, skipped=81)` out of 1 639 tests, against a baseline on
   `9fd21f0` of 70 failures and 37 errors in 1 593. The `v2.0.0`-`2.2.0` release records
   describe a green ladder; that evidence is from Linux containers, and **the Factory still has
   no evidence of a green ladder on Windows**. The 44 remaining failures, classified from their
   tracebacks (not individually diagnosed):

   | Count | Root cause |
   |---|---|
   | 14 | Other: four `test_core_security` game-code-environment cases whose command does not run here, so "sees no secret" is not exercised; `chmod`-only and symlink semantics that Windows does not have; two store-concurrency cases (below) |
   | 14 | A path separator or a drive letter inside an expectation (`'C:\srv\review\demo' != '\srv\review\demo'`) |
   | 11 | `os.symlink` needs a privilege this account does not hold (`WinError 1314`) |
   | 2 | A test starting a tool through `subprocess` directly rather than through `procs` (`npx`, `WinError 2`) |
   | 2 | A file still open when the test removed it (`WinError 5` / `WinError 32`) |
   | 1 | The process-tree kill reports no killed pids on Windows: `procs` finds a tree through `/proc/<pid>/environ` on Linux and has only the process group elsewhere, so `test_a_reviewer_timeout_is_retried_and_its_tree_is_killed` sees `killed_pids: []`. **Whether an agent's whole tree is actually taken down on Windows is therefore not established** - the safety claim "no agent process was left running" rests on Linux evidence |

   Fixes 8.3, 8.4 and the release fixture's Windows shim moved 63 of the baseline's failures
   into passing - the developer and reviewer loops, the reviewer isolation refusals, the
   malformed-verdict refusals, the retry budgets, and the whole release and commit-lineage
   suites, which had been measuring a repository the fixture never reached.

   Most of what is left is fixture portability rather than product behaviour, which is why it is
   recorded rather than fixed: porting it is a piece of work in its own right, and doing it
   inside MV-4 would have meant changing dozens of tests on a branch whose purpose is evidence.
   Two entries in the "other" bucket deserve a look on their own terms —
   `test_core_persistence.LockTakeover` (`4 != 5`, a real concurrency assertion) and
   `UniqueTemporaryNames` (35 `PermissionError`s) — because they are about the store's
   behaviour under concurrency, which is not a fixture concern.
2. **The 2D golden run stops at `develop` on the template's own checks** — diagnosed, not
   fixed, because both causes are in `web-game-template` and this branch changes no template
   source. Recorded with reproductions in `evidence/mv-4/golden/template-blockers.md`:
   `pnpm run test` — ten unit files fail to parse under vitest on this platform, every one of
   them (and only those) importing a `scripts/*.mjs` CLI that begins with a shebang; Node
   imports the same modules without complaint, and 823 tests pass in the files that do load.
   `pnpm run test:e2e` — the smoke suite's "makes no insecure requests" counts the `http://`
   IMA bridge that the *portal's* SDK pulls in as the game's own request; the pinned `v1.1.0`
   spec has no ad-host exclusion, while a later template commit does. Neither fires on Linux,
   where the refusing proxy stops the portal SDK from loading at all — which is fix 8.4.
3. **Verify cannot consume a device measurement even if one existed.** `policy.device-performance`
   is `PASS_MOCK` by construction and there is no input by which a real measurement could make
   it `PASS`. MV-4 deliberately did not add one: with no device to test it against, the code
   would be unexercised, and MV-4's rule is not to ship an evidence path nothing has produced
   evidence through. `scripts/mv4/device.py` is the path outside the workflow until then.
4. **The verified time to interactive is measured with the portal SDK blocked** (section 4).
   Unfixed, and not obviously a bug in one place: the template blocks portal SDKs on purpose,
   and the platform profile asserts on a number that means something else. The decision — assert
   on a fact measured without the SDK, or measure a fact that includes it — belongs to whoever
   owns the profile.
5. **Nothing tests a genuinely hidden tab** (section 3).
6. **Template, not Factory: the gameplay lifecycle is not recorded on the required platform**
   (section 7).

## 10. What the evidence proves about the Factory workflow

The question asked was whether the current workflow can do eight things. Each answer names what
it rests on, and no answer rests on a mock presented as the real thing.

| | | Verdict | Evidence |
|---|---|---|---|
| 1 | Generate a playable game | **Yes, on Linux; partly here** | `tower-merge-rush` exists, boots, plays, reaches game-over and restarts — measured here in a real browser. It was generated from template `0.1.0`, and the production runs that made it were on Linux. On this machine the 2D golden run reached a scaffolded repository with the whole example game written into it and then stopped at `develop` (section 11). |
| 2 | Have an agent implement it | **Yes, previously; not re-run here** | The 2.1.2 production run's live developer built the MVP in 2.12 agent-hours across sessions ([handoff](handoff/2026-09-27-production-validation.md)). MV-4 ran no agent. |
| 3 | Review and iterate it | **Yes, previously; not re-run here** | Same run: review 1 requested two genuine blockers, the developer fixed them, review 2 approved `9788f2e`. |
| 4 | Verify it | **Yes, with a qualification** | Verify passed 41/45 with 0 FAIL in that run. The qualification is section 4: one of the numbers it verifies is measured with the portal SDK absent. |
| 5 | Produce platform-specific packages | **No — one package, correctly targeted** | Section 6: the pinned contract produces one bundle; all three zips are byte-identical. The Factory correctly names `poki` as the target and prunes the rest. "Platform-specific" needs template contract 2, which is not pinned. |
| 6 | Validate a real device | **No** | Section 2. No device existed; nothing was substituted for one. |
| 7 | Validate real player behaviour | **No** | Section 5. No first-time player existed; the developer test is classified as such and counts towards neither criterion. |
| 8 | Produce a release-ready artifact | **Partly** | The bytes are there and are internally consistent: package, checksums, `checksums.txt` and manifest all agree, and the target platform's package exists. It is not release-*ready* in the sense that matters: G4 is undecided, three kill criteria are unmeasured, and no portal has seen anything. |

**The Factory is not production-ready on the strength of this run, and this report does not say
it is.** What it says is narrower and, on the evidence, true: the pipeline's output is a real
game that behaves correctly in a real browser, the pipeline's own bookkeeping about that output
is accurate, and the two questions that decide whether a game is worth shipping — what a
stranger does with it, and what a phone does with it — remain unanswered because neither a
stranger nor a phone was available.

## 11. Validation of this branch

| Check | Result |
|---|---|
| `python scripts/check-integrity.py` | **OK** (with the pre-existing note that `y8@1.0.0` diverges template-side) |
| `python scripts/wgf-hash.py --check workspace/` | **OK** |
| `bash scripts/gen-adapters.sh` | **no diff** |
| `python -m unittest scripts.tests.test_mv4` | **29 / 29 OK** |
| `python -m unittest discover scripts/tests` | 1 639 tests, **27 failures, 17 errors**, 81 skipped - against a Windows baseline on `9fd21f0` of **70 failures and 37 errors** in 1 593 tests. 63 of the baseline's failures now pass; the failing set is compared name by name after every increment, and **none is new**. |
| `bin/wgf test-core --json` | FAIL / INCOMPLETE on Windows, and it now prints its report at all (fix 8.5 — the previous run raised `UnicodeEncodeError` after twenty minutes of work and emitted nothing): |

| Category | Result | tests | passed | failed | errors | skipped |
|---|---|---|---|---|---|---|
| WORKFLOW | FAIL | 224 | 215 | 2 | 0 | 7 |
| AGENTS | FAIL | 47 | 41 | 2 | 1 | 3 |
| CONTRACTS | FAIL | 131 | 128 | 2 | 0 | 1 |
| VERIFY | **PASS** | 22 | 22 | 0 | 0 | 0 |
| RELEASE | **PASS** | 49 | 48 | 0 | 0 | 1 |
| 2D GOLDEN | SKIP | 10 | 0 | 0 | 0 | 10 |
| 3D GOLDEN | SKIP | 10 | 0 | 0 | 0 | 10 |
| PROCESS CLEANUP | **PASS** | 40 | 6 | 0 | 0 | 34 |
| SECURITY | FAIL | 117 | 105 | 8 | 1 | 3 |

AGENTS went from 17 passed of 47 to 41 of 47, RELEASE from 27 of 49 to 48 of 49 - now PASS -
and CONTRACTS from 124 to 128 of 131. PROCESS CLEANUP passes what it runs and skips 34 of 40
as POSIX-only, which is the same thing as saying the Factory's process-ownership guarantees
are not tested on this platform. The suite is still INCOMPLETE: a SKIP is never a PASS, and
both golden categories are skipped without `WGF_GOLDEN=1`.

| Check | Result |
|---|---|
| `WGF_GOLDEN=1 bin/wgf test-core --only "2D GOLDEN"` | **FAIL on Windows, 3 of 10** — below |
| MV-4 harness | 3 browser sessions, 1 platform session, 1 packaging audit, 1 device record, 1 playtest summary, 1 G4 record, 1 golden-run record — all under `evidence/mv-4/` |

**The 2D golden run on Windows**, run six times, and diagnosed to a stop rather than left at
one. The record of the last run is `evidence/mv-4/golden/golden-2d-windows.json`; the two
remaining causes, with their reproductions, are in
`evidence/mv-4/golden/template-blockers.md`.

- research, strategy, strategy-review, design, tech-plan, tech-plan-review, init and assets all
  SUCCEED. The run's artifacts are pinned by hash: `research-report`, `opportunity`,
  `title-strategy`, `game-design`, `tech-plan`, `asset-manifest`, `scaffold-record`,
  `decision-record`.
- `develop` first failed with `developer command exited 3` — a refusal from the replay
  developer, the deterministic stand-in the golden runs use. Two Factory defects were behind it,
  one after the other: the child could not be started at all (fix 8.2), and then the agent
  environment had no `SystemRoot`, so `pnpm.CMD` could not run (fix 8.3). After both, the replay
  developer installs, ports the whole example game into the checkout and formats it.
- `develop` now fails on the **game repository's own checks**: `unit: pnpm run test: exit 1;
  smoke: pnpm run test:e2e: exit 1`. Both causes are in `web-game-template` — ten unit files
  that do not parse under vitest on this platform, and a smoke assertion that counts the
  portal SDK's `http://` ad bridge as the game's own insecure request. Neither is fixed here.
- Everything after `develop` is therefore NOT_RUN: review, sdk, sdk-review, verify,
  prototype-review, release. No release was drafted in a golden run on this machine, and the
  browser evidence in section 3 was taken by MV-4's own harness, not by the golden run.
- The run's own network record now says what it is worth:
  `"enforced": false, "platform": "win32", "refused_requests": 0` with the reason. Before fix
  8.4 it said `refused_requests: 0` and nothing else, which reads as isolation and was not.
- The 3D golden run was not attempted: it has the same developer stand-in and the same game
  repository checks, and would stop at the same step.

The Linux ladder that `v2.2.0` was released against was not re-run: this machine is Windows and
no Linux host was available. **A merge of this branch should be validated on Linux before it is
believed**, exactly as the release records describe. While MV-4 ran, `origin/main` gained a
Linux acceptance runner (`031ca0e`, PR #10), which is where that validation now belongs; this
branch was not merged, rebased or brought up to it.

## 12. Not done, and why

- No release was cut. No Factory defect found here changes released behaviour on the platform
  the releases were validated on, so nothing requires a new version. `VERSION` stays 2.2.0.
- No game or template source was changed. Two of MV-4's findings are template defects; they are
  recorded here and belong in `web-game-template`.
- Nothing was published, submitted, or paid for. The only outward request was two GETs to a
  public CDN, recorded in full in section 4.
