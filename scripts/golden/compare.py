#!/usr/bin/env python3
"""Compare two golden summaries: what must repeat, and what legitimately differs.

    python3 scripts/golden/compare.py <golden-2d.json> <golden-2d.json> [--json]

Exit 0 when every field that must be identical is identical (docs/golden-runs.md,
"Repeatability"); 1 otherwise. Fields expected to differ are listed, not judged.
"""

import argparse
import json
import sys

# Artifact types whose content does not embed run-specific values: research is pinned by
# the fixed `as_of` and frozen fixtures, and carries no run id.
STABLE_TYPES = ("research-report", "opportunity")


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _latest_hashes(summary):
    latest = {}
    for record in summary.get("artifacts") or []:
        latest[record["type"]] = record["content_hash"]
    return latest


def _commit_files(summary):
    return [(c.get("subject"), c.get("files")) for c in
            (summary.get("repository") or {}).get("commits") or []]


def _suite(summary):
    browser = summary.get("browser") or {}
    return {"suites": (browser.get("suites") or {}).get("counts"),
            "probe": {k: (v.get("steps"), (v.get("probe") or {}).get("engine"))
                      for k, v in ((browser.get("probe") or {}).get("viewports") or {}).items()}}


def compare(a, b):
    must = {
        "steps": ([(s["step"], s["status"], s["route"]) for s in a["steps"]],
                  [(s["step"], s["status"], s["route"]) for s in b["steps"]]),
        "engine": (a["engine"].get("recorded"), b["engine"].get("recorded")),
        "stable_artifact_hashes": ({t: _latest_hashes(a).get(t) for t in STABLE_TYPES},
                                   {t: _latest_hashes(b).get(t) for t in STABLE_TYPES}),
        "artifact_types": (sorted({r["type"] for r in a["artifacts"]}),
                           sorted({r["type"] for r in b["artifacts"]})),
        "files_per_commit": (_commit_files(a), _commit_files(b)),
        "package_content_digests": (
            [(p["platform_id"], p["content_digest"], p["files"])
             for p in (a.get("release") or {}).get("packages") or []],
            [(p["platform_id"], p["content_digest"], p["files"])
             for p in (b.get("release") or {}).get("packages") or []]),
        "evidence_statuses": (
            {k: a["evidence"][k].get("evidence_status") for k in ("qa_report", "release_manifest")},
            {k: b["evidence"][k].get("evidence_status") for k in ("qa_report", "release_manifest")}),
        "verification_counts": (a["evidence"]["verification_report"]["checks"],
                                b["evidence"]["verification_report"]["checks"]),
        "browser_results": (_suite(a), _suite(b)),
    }
    may = {
        "run_id": (a["run_id"], b["run_id"]),
        "head_commit": ((a.get("repository") or {}).get("head"),
                        (b.get("repository") or {}).get("head")),
        "zip_checksums": ([p["checksum"] for p in (a.get("release") or {}).get("packages") or []],
                          [p["checksum"] for p in (b.get("release") or {}).get("packages") or []]),
        "run_specific_artifact_hashes": sum(
            1 for t, h in _latest_hashes(a).items()
            if t not in STABLE_TYPES and _latest_hashes(b).get(t) != h),
        "duration_s": (a["duration_s"], b["duration_s"]),
    }
    same = {k: v[0] == v[1] for k, v in must.items()}
    return {"identical": same, "all_identical": all(same.values()),
            "differs": {k: v for k, v in must.items() if v[0] != v[1]},
            "legitimately_differs": may}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("first")
    parser.add_argument("second")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = compare(_load(args.first), _load(args.second))
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        for key, ok in result["identical"].items():
            print(f"  {'same' if ok else 'DIFF'}  {key}")
        for key, value in result["legitimately_differs"].items():
            print(f"  may   {key}: {value}")
        print("REPEATABLE" if result["all_identical"] else "NOT REPEATABLE")
    return 0 if result["all_identical"] else 1


if __name__ == "__main__":
    sys.exit(main())
