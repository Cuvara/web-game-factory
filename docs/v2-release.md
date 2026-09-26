# Factory 2.0.0 — release record

2.0.0 is the release after 1.1.0 ([v1-usable.md](v1-usable.md)). It carries the
architectural audit that followed 1.1.0 (Waves 1–3, modules M1–M13), the game production
workflow (the `core/craft/` playbooks, adapter binding 1.2.0, follow-ups F1–F7), and the fixes
from the release audit of the candidate. This page is the record of what was validated, on
which commit, and what the evidence does not cover. What changed, and how to upgrade, is in
[CHANGELOG.md](../CHANGELOG.md) under 2.0.0: **Breaking** and **Upgrading from 1.1.0** come
first.

It is a major version because defaults a 1.1.0 installation or script relied on changed:
- the agent environment is an allowlist;
- the development commit is scoped;
- a release no review approved is refused;
- `wgf status` exits as the run;
- `new-game --mock` stops at G4.

Each has a configuration or command that keeps things working. No schema's required fields
changed, and an artifact written by 1.1.0 still validates.

## Pins

| | |
|---|---|
| Factory | `VERSION` 2.0.0 |
| Template | web-game-template `v1.1.0` (`bca41a97665f8a32d0f803d46a7bbd001ac94d41`), unchanged since 1.1.0 |
| Workflow | `new-game` version 2; `gates.yaml` 1.1.0 |
| Adapters | binding 1.2.0; Claude plugin 0.4.0 |
| Template contract | `CONTRACT_VERSION` 1.0.0 |

## The release audit

The first candidate (`aff77a8`) was audited read-only before release. Three blockers were
found and fixed, each with tests that fail on that candidate:

- **Links in the checkout (B1).** The Factory wrote its own files into the game checkout
  through links a developer could leave there. They are now written by
  `wgf_develop/safewrite.py`.
- **The event log (B2).** A step's process could append a forged budget raise that the
  resume nonce corroborated, or truncate the log. The engine now seals a driven run's
  `events.jsonl` and puts back anything another process wrote there (`EVENT_LOG_RESTORED`).
  Negative costs are rejected.
- **The release notes (B3).** They did not identify the breaking changes. The CHANGELOG now
  has Breaking and Upgrading sections.

## Validation

VALIDATION_RESULTS

## What the evidence does not cover

- **No live agent host in this release's runs.** The golden runs use a replayed developer and
  a scripted reviewer. The live developer and reviewer path was verified for 1.1.0 (v1-usable.md).
  2.0.0 changes what that host receives — an allowlisted environment
  (`factory.agents.env_passthrough`), a scoped commit — and has not been run live.
- **The opt-in design agent (F4) and developer self-playtest (F6)** are verified offline only
  ([claude-capabilities.md](claude-capabilities.md)).
- **The golden runs used local workarounds:** a pnpm store warmed from the pinned template, and
  a `PLAYWRIGHT_BROWSERS_PATH` shim mapping the Playwright build the template expects onto the
  Chromium installed on the validation machine. Neither changed a test or a check. A run on a
  clean machine is not recorded.
- **Opt-in suites not run:** `WGF_LIVE_AGENT`, `WGF_AJV` (ajv against the stdlib validator),
  `WGF_LIVE_PROCESS_TEST`, `WGF_TEMPLATE_RELEASE_TEST`.
- **Portal behaviour, submission and publishing** remain outside the Factory (BLOCKED_EXTERNAL,
  behind G6).

## Recommended before publishing

1. One live agent-host run (`WGF_LIVE_AGENT=1` with `WGF_LIVE_DEVELOPER_ARGV` /
   `WGF_LIVE_REVIEWER_ARGV`), confirming authentication through
   `factory.agents.env_passthrough` and a scoped development commit.
2. `WGF_GOLDEN=1 bin/wgf test-core --strict` on a clean machine: no warmed store, and
   Playwright's browsers installed for the template's own Playwright version.
3. `WGF_AJV=1` and `WGF_LIVE_PROCESS_TEST=1` once.
