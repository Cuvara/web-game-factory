# MV-4 — real-world evidence

MV-4 is the validation step after MV-3 (Factory 2.2.0, [v2.2-release.md](v2.2-release.md)). Its
object is not another architecture change. It is evidence: what the Factory's own output does
on real hardware, in a real browser, against a real portal SDK, and in front of a real player —
and, where none of those can be reached, an explicit and durable record that they were not.

The rule that governs every line below: **a measurement carries the class of thing it was taken
on, and a weaker class never becomes a stronger claim.** A CPU-throttled desktop Chromium is not
a phone; an emulated touch event is not a finger; a mocked portal SDK is not a portal; the
person who built the game is not a first-time player. The Factory already encodes this for
verification evidence (`PASS`, `PASS_MOCK`, `BLOCKED_EXTERNAL`, `UNVERIFIED`, `FAIL` —
`core/artifacts/shared/evidence.schema.json`). MV-4 uses the same vocabulary for evidence taken
outside a workflow run, and adds one field of its own, `measurement_class`, with four values:

| `measurement_class` | Means | Strongest evidence status it may carry |
|---|---|---|
| `real-device` | A physical handset, its own browser, its own CPU and GPU | `PASS` |
| `real-browser-desktop` | A real browser binary on this machine, real bytes, desktop hardware | `PASS` for browser behaviour; never for device performance |
| `emulated-mobile` | A desktop browser under a device descriptor, touch emulation and/or a CPU throttle | `PASS_MOCK` |
| `developer-test` | A person who already knows the game | `PASS_MOCK`; never evidence about first-time players |

## What MV-4 measures

### A. Real mobile performance

- **Measured.** Sustained frame rate and frame-time distribution across at least 60 s of
  continuous play; JS heap at start and at the end of the sample; time from navigation to the
  game signalling ready; all on a physical mid-range Android handset.
- **How.** The bytes that ship — the release package for the target platform, unpacked and
  served — opened in the handset's own Chrome. Frame deltas are sampled from
  `requestAnimationFrame` and the counters are read from the game's own read-only probe
  (`window.__wgf__`), so no instrumented build is involved. Recorded by
  `scripts/mv4/session.py`, which refuses to write `measurement_class: real-device` unless the
  device identity it was given came from the device itself.
- **PASS.** Median FPS across the whole sample ≥ 30, and p95 frame time ≤ 50 ms, with no
  single 5-second window below 25 FPS.
- **FAIL.** Median FPS < 30, or p95 frame time > 50 ms, or any 5-second window below 25 FPS.
- **UNVERIFIED.** No physical handset was reachable from the machine running MV-4. A desktop
  proxy is recorded alongside, labelled `emulated-mobile`, and does not decide the criterion.
- **Evidence retained.** `device-session.json`: device model, Android version, browser version,
  viewport, the artifact's sha256, raw per-sample frame deltas, the derived statistics,
  `measurement_class`, and the operator who took it.

### B. Real touch interaction

- **Measured.** Whether each control the game exposes can be operated by a finger on a
  touchscreen: first-touch acknowledgement, no input dropped during animation, no double-fire
  from a single tap, no control smaller than the platform's minimum target, and no gesture that
  collides with the browser's own (pull-to-refresh, back-swipe, text selection, double-tap zoom).
- **How.** A scripted observation pass on the handset, one line per control, taken by the person
  holding the device, against `docs/mv-4-touch-sheet.md`.
- **PASS.** Every control operable; no dropped first touch; no browser gesture collision.
- **FAIL.** Any control unreachable or unresponsive, or any browser gesture that interrupts play.
- **UNVERIFIED.** No handset. Playwright's touch emulation is run for regression value only and
  is recorded as `emulated-mobile`; it cannot decide this criterion, because the failures this
  criterion exists to find (hit targets, gesture collisions, touch latency) are the ones
  emulation reproduces least.
- **Evidence retained.** The completed sheet, with the build's sha256 and the device identity.

### C. Real browser behaviour

- **Measured.** On the shipping bytes, in a real browser binary: cold load to interactive;
  sustained frame rate and frame-time percentiles; JS heap growth over a session and across a
  restart; behaviour on resize and on an orientation change; audio unlocked by the first
  gesture and silent before it; mute and unmute; pause when the tab is hidden and no simulation
  progress while hidden; and full recovery — input, rendering and audio — on return.
- **How.** `scripts/mv4/session.py` plus its browser side `scripts/mv4/session.spec.ts`, driving
  a real Chromium against a preview server serving the unpacked release package. Every external
  request is aborted and recorded, as in the golden runs, so no portal is contacted.
- **PASS.** Load to interactive ≤ 5 s (Poki's own assertion); no page error and no console
  error; hidden-tab simulation progress exactly zero; audio silent before the first gesture and
  audible after; heap after a restart no more than 1.5× the heap after the first session
  (a leak-on-restart guard, the failure the web-performance playbook names); every one of
  resize, orientation change and return-from-hidden leaves the game playable.
- **FAIL.** Any of the above not holding.
- **Evidence retained.** `browser-session.json` with every measurement, the captured console and
  page errors, the blocked external requests, screenshots at each stage and their hashes, and
  `measurement_class: real-browser-desktop`.

### D. Real SDK / platform behaviour

- **Measured.** For the required platform: that the portal's own SDK, fetched from the portal's
  own origin, loads and initialises against the template's adapter; that the game's lifecycle
  calls (loading progress, ready, gameplay start, gameplay stop) reach it; that a commercial
  break and a rewarded break follow the portal's contract; that mute and unmute are honoured;
  and that persistence survives a reload.
- **How.** The adapter under test is the one in the shipping bundle. The portal SDK is loaded
  from the portal's documented URL in a single, isolated session that is recorded in full. No
  credentials, no submission, no spend.
- **PASS.** Only with portal credentials and a registered game: SDK initialises, every
  lifecycle call is accepted, and ad calls return the portal's documented outcomes.
- **FAIL.** The SDK rejects the integration, or a lifecycle call is refused.
- **BLOCKED_EXTERNAL.** No portal account exists, so no ad can be served and no portal-side
  behaviour can be observed. What is still testable without an account — that the SDK script
  loads, that the adapter binds to it, and that the game boots both with and without it — is
  recorded as such, separately, and never summed into a claim about the portal.
- **Evidence retained.** `platform-session.json` per platform: the SDK URL and the sha256 of
  what was served, the adapter's own call log, which of the listed behaviours were exercised,
  and the evidence status of each.

### E. Real player testing

- **Measured.** Kill criterion 1 — the share of first-time players who understand the control
  without being told. Kill criterion 2 — the share who retry without being prompted.
- **How.** `docs/mv-4-playtest-protocol.md`: participants with no prior knowledge of the game,
  one instruction only ("play this"), no coaching, observation against a fixed sheet, and a
  fixed calculation written down before any session is run.
- **PASS.** ≥ 60% understand the control, and ≥ 50% retry unprompted, over at least five
  participants.
- **FAIL.** Below either threshold over at least five participants.
- **UNVERIFIED.** Fewer than five first-time participants. A session run by someone who already
  knows the game is recorded as `developer-test` and is explicitly excluded from both
  percentages: it is evidence about the build, never about first-time players.
- **Evidence retained.** Participant count, whether each had prior knowledge, the exact
  instruction given, raw per-participant observations, the calculation, and the resulting
  figure or the reason there is none. No personal information beyond "prior knowledge:
  yes/no" is collected or retained.

### F. Telemetry

- **Measured.** That the measurements MV-4 needs are *collected* somewhere durable — not merely
  emitted into a sink that discards them.
- **How.** The smallest mechanism that is honest: the game's own read-only probe already exposes
  the session counters (runs started, runs stopped, ads requested, ads shown, frames rendered,
  elapsed time), so a session harness reads them out of the live page and writes them to a file.
  Nothing is added to the game, and nothing is added to the shipping bundle.
- **PASS.** A file exists, written by this run, containing the counters read from the running
  build, with the artifact's hash and the session's identity.
- **FAIL.** The counters could not be read from a running build.
- **The three kinds stay separated, by name, in every artifact.** *Production telemetry*: what
  the shipped game sends to a destination in the field — currently nothing, because the
  analytics sink the template wires by default discards events (`NullSink`); recorded as a gap,
  not as a result. *Test telemetry*: the probe counters MV-4 reads out of a running build, which
  is what the evidence below rests on. *Mocked telemetry*: events observed against a stand-in
  sink inside the unit suite, which are evidence about the code path and about nothing else.
- **Evidence retained.** `telemetry.jsonl`, one record per session, each naming its kind.

### G. G4 evidence

- **Measured.** Each of the four kill criteria set at strategy, with the class of the
  measurement behind it.
  1. Fewer than 60% of first-time players understand the control.
  2. Fewer than 50% retry without being prompted.
  3. The prototype exceeds the allowed timebox.
  4. Mobile performance below 30 FPS on a mid-range mobile browser.
- **How.** 1 and 2 from E; 3 from the run's own event log against the timebox the strategy set;
  4 from A.
- **PASS.** Every criterion carries a measurement of a class that can decide it, and none of the
  four is met.
- **FAIL.** Any criterion is met by a measurement of a class that can decide it.
- **UNVERIFIED.** Any criterion whose only measurement is of a weaker class. G4 may still be
  decided by a person on an incomplete record — the methodology reserves that decision for a
  person precisely because it is a judgement — but the record must say which of the four were
  measured and which were not. An inconclusive on a central question argues for `iterate`, not
  for `pass` (`core/lifecycle/stages/prototype-review.md`).
- **Evidence retained.** `g4-evidence.json`: per criterion, the measurement, its
  `measurement_class`, its evidence status, and the artifact it was taken on.

## What MV-4 will not do

- Convert a desktop throttle into a device result, under any label.
- Count a developer's session towards a first-time-player percentage.
- Report a mocked SDK as platform integration.
- Change the game to make a criterion pass.
- Weaken, skip or retry a test to make the ladder green.
- Make a legal claim about any portal's terms. Portal documentation requirements are recorded
  as quotations with their source, separately from what was technically observed.
- Publish, submit, or spend.
