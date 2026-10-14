# Real evidence for the triage ledger's hygiene (K7 #4)

REAL data, copied from the 3D validation run of 2026-10-05 (`sky-marble`, run
`new-game-20261005-002923-597b5e`, read-only evidence kept outside this repository). Replayed
by `scripts/tests/test_triage.py` `PassingReportFindings`.

| File | What it is | Expected |
|---|---|---|
| `triage-v12-3d.json.gz` | every input triage-report v12 (seq 74, entered by `content-sufficiency.develop`, build 3f394e2a31efe64923c0a5a3fab973b102e5592d) pinned in its provenance, resolved by content hash to the run store's version and run-local seq: visual-qa-report v3 (seq 72, verdict PASS, two MAJOR and two minor judge findings), content-sufficiency-report v2, playability-report v12, production-quality-report v6, prototype-report v19, triage-report v11, asset-manifest v4, game-design v3, decision-record (tech-plan-review v3); and what the real v12 recorded (`real_triage_v12`: route, findings, held, the ids in its ledger) | the real v12 recorded neither major; replayed, both are recorded `noted` with the run's own route (`level-designer`), findings and blocking set |

Conversions, nothing else: the reports are verbatim (same content hashes as the run store)
except game-design and asset-manifest, trimmed to what triage reads (provenance, title_id,
engine type and dimension), and the prototype-report's `build_ref.url`, a local checkout
path replaced by `file://<checkout>`. Built by a one-off script from the run store
(`json.dumps(sort_keys=True)`, gzip with mtime 0).
