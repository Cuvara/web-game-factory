#!/usr/bin/env python3
"""Measure the old-Factory baseline of the two validation games (2026-10).

Read-only on every input: it reads the runs' `.factory/workflows/<run>/` records, reads game
sources at the release commit with `git show` (never the working tree), and reads the Factory
worktrees' reflogs. It writes only the JSON it prints (or `--out`).

    python docs/benchmark/baseline.py --out docs/benchmark/2026-10-baseline.json

Inputs default to the validation host's paths; override the root with WGF_BASELINE_RUNS.
The 3D course table is TypeScript; it is evaluated by Node (>= 22, type stripping) from
stdin, so nothing is written next to the game.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

RUNS = Path(os.environ.get("WGF_BASELINE_RUNS", "C:/Users/duycu/wgf-runs"))
REPO = Path(__file__).resolve().parents[2]
MAIN = "8daeec8"

GAMES = [
    {
        "key": "2d",
        "name": "Brick Breaker Worlds",
        "run_id": "new-game-20261003-081154-4e5e0a",
        "project": RUNS / "val-2d/project",
        "repo": RUNS / "val-2d/games/brick-breaker-worlds",
        "factory": RUNS / "val-2d/factory",
        "content": "units",
    },
    {
        "key": "3d",
        "name": "Sky Marble",
        "run_id": "new-game-20261003-082542-0de9b5",
        "project": RUNS / "val-3d/project",
        "repo": RUNS / "val-3d/games/sky-marble",
        "factory": RUNS / "val-3d/factory",
        "content": "courses",
    },
]

GATE_TYPES = [
    "playability-report",
    "production-quality-report",
    "visual-qa-report",
    "review-report",
    "sdk-report",
    "verification-report",
    "qa-report",
    "store-listing",
    "listing-validation-report",
    "platform-publication-poki",
    "asset-manifest",
]


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8"
    )
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} in {repo}: {out.stderr.strip()}")
    return out.stdout


def load(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def hours(a: str, b: str) -> float:
    return round((ts(b) - ts(a)).total_seconds() / 3600, 2)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


# --------------------------------------------------------------------------- run records


class Run:
    def __init__(self, game: dict):
        self.game = game
        self.dir = game["project"] / ".factory/workflows" / game["run_id"]
        self.state = load(self.dir / "state.json")
        self.events = [
            json.loads(line)
            for line in open(self.dir / "events.jsonl", encoding="utf-8")
            if line.strip()
        ]
        self.by_hash: dict[str, tuple[str, int, dict]] = {}
        self.versions: dict[str, list[tuple[int, dict]]] = {}
        art = self.dir / "artifacts"
        for d in sorted(art.iterdir()):
            vs = []
            for f in d.iterdir():
                v = int(f.stem[1:])
                doc = load(f)
                vs.append((v, doc))
                h = doc.get("provenance", {}).get("content_hash")
                if h:
                    self.by_hash[h] = (d.name, v, doc)
            self.versions[d.name] = sorted(vs, key=lambda x: x[0])

    def ref(self, artifact_dir: str, v: int) -> dict:
        doc = dict(self.versions[artifact_dir])[v]
        p = doc.get("provenance", {})
        return {
            "file": f"artifacts/{artifact_dir}/v{v}.json",
            "artifact_id": p.get("artifact_id"),
            "schema_version": p.get("schema_version"),
            "content_hash": p.get("content_hash"),
        }

    def output(self, step: str, artifact_dir: str) -> int | None:
        """The version of `artifact_dir` the step's last execution produced."""
        for o in self.state["steps"].get(step, {}).get("outputs") or []:
            name, _, v = o.partition("@v")
            if name == artifact_dir:
                return int(v)
        return None

    def resolve(self, content_hash: str) -> tuple[str, int] | None:
        hit = self.by_hash.get(content_hash)
        return (hit[0], hit[1]) if hit else None


# --------------------------------------------------------------------------- gates


def check_rows(checks: list[dict]) -> list[dict]:
    rows = []
    for c in checks:
        row = {k: c.get(k) for k in ("id", "project", "status", "required", "summary") if k in c}
        rows.append(row)
    return rows


def gate_summary(kind: str, doc: dict) -> dict:
    """The verdict-bearing fields of one gate artifact, compact."""
    if kind == "playability-report":
        checks = doc.get("checks", [])
        return {
            "verdict": doc.get("verdict"),
            "commit": doc.get("commit"),
            "measurement_class": doc.get("measurement_class"),
            "checks": len(checks),
            "status_counts": dict(collections.Counter(c.get("status") for c in checks)),
            "failed_checks": doc.get("failed_checks"),
            "skipped_checks": doc.get("skipped_checks"),
            "non_pass": [r for r in check_rows(checks) if r.get("status") != "PASS"],
        }
    if kind == "production-quality-report":
        checks = doc.get("checks", [])
        return {
            "verdict": doc.get("verdict"),
            "commit": doc.get("commit"),
            "measurement_class": doc.get("measurement_class"),
            "checks": len(checks),
            "failed": doc.get("failed"),
            "routes": doc.get("routes"),
            "non_pass": [r for r in check_rows(checks) if r.get("status") != "PASS"],
        }
    if kind == "visual-qa-report":
        scores = doc.get("scores") or {}
        return {
            "verdict": doc.get("verdict"),
            "commit": doc.get("commit"),
            "measurement_class": doc.get("measurement_class"),
            "rubric": {k: (doc.get("rubric") or {}).get(k) for k in ("path", "version", "pass_bar")},
            "judge": doc.get("judge"),
            "judge_runs": doc.get("judge_runs"),
            "judge_repairs": doc.get("judge_repairs"),
            "frames": len(doc.get("frames") or []),
            "scores": scores,
            "mean_score": round(sum(scores.values()) / len(scores), 3) if scores else None,
            "min_score": min(scores.values()) if scores else None,
            "look": doc.get("look"),
            "findings": [
                {k: f.get(k) for k in ("id", "severity", "category", "frame", "route", "summary")}
                for f in doc.get("findings") or []
            ],
            "failed": doc.get("failed"),
            "routes": doc.get("routes"),
        }
    if kind == "review-report":
        return {
            "verdict": doc.get("verdict"),
            "reviewed_commit": doc.get("reviewed_commit"),
            "baseline_commit": doc.get("baseline_commit"),
            "iteration": doc.get("iteration"),
            "blockers": doc.get("blockers"),
            "failure": doc.get("failure"),
            "isolation_intact": (doc.get("isolation") or {}).get("intact"),
            "duration_s": doc.get("duration_s"),
            "notes": doc.get("notes"),
        }
    if kind == "sdk-report":
        return {
            "commit": (doc.get("build_ref") or {}).get("commit_sha"),
            "platforms": [
                {
                    "platform_id": p.get("platform_id"),
                    "profile_version": p.get("profile_version"),
                    "status": p.get("status"),
                    "features": dict(
                        collections.Counter(f.get("status") for f in p.get("features") or [])
                    ),
                }
                for p in doc.get("platforms") or []
            ],
        }
    if kind == "verification-report":
        return {
            "verdict": doc.get("verdict"),
            "evidence_status": doc.get("evidence_status"),
            "commit": doc.get("commit"),
            "gameplay_driver": (doc.get("gameplay_driver") or {}).get("id"),
            "build_artifact": doc.get("build_artifact"),
            "summary": doc.get("summary"),
            "failed_checks": doc.get("failed_checks"),
            "blocked_checks": doc.get("blocked_checks"),
            "warning_checks": doc.get("warning_checks"),
            "platform_readiness": [
                {
                    k: p.get(k)
                    for k in ("platform_id", "role", "readiness", "evidence_status", "portal_status")
                }
                for p in doc.get("platform_readiness") or []
            ],
        }
    if kind == "qa-report":
        return {
            "verdict": doc.get("verdict"),
            "evidence_status": doc.get("evidence_status"),
            "release_id": doc.get("release_id"),
            "build_ref": doc.get("build_ref"),
            "suites": doc.get("suites"),
            "blocking_defects": doc.get("blocking_defects"),
            "perf_results": doc.get("perf_results"),
        }
    if kind == "store-listing":
        return {
            "status": doc.get("status"),
            "commit": doc.get("commit"),
            "measurement_class": doc.get("measurement_class"),
            "screenshots": len(doc.get("screenshots") or []),
            "platforms": [p.get("platform_id") for p in doc.get("platforms") or []],
            "problems": doc.get("problems"),
        }
    if kind == "listing-validation-report":
        return {
            "verdict": doc.get("verdict"),
            "commit": doc.get("commit"),
            "checks": len(doc.get("checks") or []),
            "sections": doc.get("sections"),
            "failed": doc.get("failed"),
            "unknown": len(doc.get("unknown") or []),
            "warnings": doc.get("warnings"),
            "platforms": [
                {
                    "platform_id": p.get("platform_id"),
                    "status": p.get("status"),
                    "spec_status": p.get("spec_status"),
                    "unknown": len(p.get("unknown") or []),
                }
                for p in doc.get("platform_requirements") or []
            ],
        }
    if kind.startswith("platform-publication"):
        return {
            "state": doc.get("state"),
            "readiness": doc.get("readiness"),
            "measurement_class": doc.get("measurement_class"),
            "guards": [{g["guard"]: g["verdict"]} for g in doc.get("guards") or []],
            "package": doc.get("package"),
            "human_required": doc.get("human_required"),
        }
    if kind == "asset-manifest":
        items = doc.get("items") or []
        return {
            "items": len(items),
            "complete": doc.get("complete"),
            "placeholders": sum(1 for i in items if i.get("placeholder")),
            "issues": len(doc.get("issues") or []),
        }
    return {}


def history_row(kind: str, v: int, doc: dict) -> dict:
    s = gate_summary(kind, doc)
    row = {"v": v, "produced_at": doc.get("provenance", {}).get("produced_at")}
    for k in ("verdict", "status", "state", "readiness", "evidence_status", "commit",
              "reviewed_commit", "mean_score", "min_score", "items", "placeholders"):
        if s.get(k) is not None:
            row[k] = s[k]
    if kind == "visual-qa-report":
        row["scores"] = s["scores"]
        row["findings"] = len(s["findings"])
    if kind in ("playability-report",):
        row["failed"] = s["failed_checks"]
    if kind in ("production-quality-report", "visual-qa-report"):
        row["failed"] = s["failed"]
    if kind == "review-report":
        row["blockers"] = [
            {"id": b.get("id"), "severity": b.get("severity"), "file": b.get("file"),
             "summary": b.get("summary")}
            for b in s["blockers"] or []
        ]
    for k in ("commit", "reviewed_commit"):
        if isinstance(row.get(k), dict):
            row[k] = row[k].get("sha")
        if isinstance(row.get(k), str):
            row[k] = row[k][:12]
    return row


def gates(run: Run) -> dict:
    steps = {
        "playability": "playability-report",
        "production-quality": "production-quality-report",
        "visual-qa": "visual-qa-report",
        "review": "review-report",
        "sdk": "sdk-report",
        "sdk-review": "review-report",
        "verify": "verification-report",
        "verify:qa": "qa-report",
        "store-listing": "store-listing",
        "listing-validation": "listing-validation-report",
        "platform-validate": "platform-publication-poki",
        "assets": "asset-manifest",
        "greybox-playability": "playability-report",
    }
    out = {}
    for step, kind in steps.items():
        sid = step.split(":")[0]
        v = run.output(sid, kind)
        if v is None:
            continue
        doc = dict(run.versions[kind])[v]
        out[step] = {**run.ref(kind, v), **gate_summary(kind, doc)}
    history = {}
    for kind in GATE_TYPES:
        if kind in run.versions:
            history[kind] = [history_row(kind, v, d) for v, d in run.versions[kind]]
    return {"final": out, "history": history}


def decisions(run: Run) -> list[dict]:
    rows = []
    for kind, vs in run.versions.items():
        if not kind.startswith("decision-record"):
            continue
        for v, d in vs:
            subject = []
            for s in d.get("subject") or []:
                hit = run.resolve(s.get("content_hash"))
                subject.append(
                    {
                        "artifact_id": s.get("artifact_id"),
                        "file": f"artifacts/{hit[0]}/v{hit[1]}.json" if hit else None,
                    }
                )
            rows.append(
                {
                    "file": f"artifacts/{kind}/v{v}.json",
                    "artifact_id": d["provenance"].get("artifact_id"),
                    "gate_id": d.get("gate_id"),
                    "transition": d.get("transition"),
                    "decision": d.get("decision"),
                    "decided_by": d.get("decided_by"),
                    "decided_at": d.get("decided_at"),
                    "rationale": d.get("rationale"),
                    "subject": subject,
                }
            )
    rows.sort(key=lambda r: r["decided_at"] or "")
    return rows


# --------------------------------------------------------------------------- release


def release(run: Run) -> dict:
    v = run.output("release", "release-manifest")
    doc = dict(run.versions["release-manifest"])[v]
    inputs = []
    for i in doc["provenance"].get("inputs") or []:
        hit = run.resolve(i.get("content_hash"))
        inputs.append(
            {
                "artifact_id": i.get("artifact_id"),
                "file": f"artifacts/{hit[0]}/v{hit[1]}.json" if hit else None,
            }
        )
    repo = run.game["repo"]
    rel_dir = repo / "release" / doc["release_id"]
    on_disk = []
    for p in doc.get("packages") or []:
        f = rel_dir / p["filename"]
        on_disk.append(
            {
                "filename": p["filename"],
                "exists": f.exists(),
                "sha256_matches_manifest": f.exists() and sha256_file(f) == p.get("checksum"),
            }
        )
    verify_v = run.output("verify", "verification-report")
    build = dict(run.versions["verification-report"])[verify_v].get("build_artifact")
    return {
        **run.ref("release-manifest", v),
        "release_id": doc.get("release_id"),
        "version": doc.get("version"),
        "state": doc.get("state"),
        "commit_sha": doc.get("commit_sha"),
        "commit_subject": git(repo, "log", "-1", "--format=%s", doc["commit_sha"]).strip(),
        "frozen_at": doc.get("frozen_at"),
        "packages": doc.get("packages"),
        "packages_on_disk": on_disk,
        "target_platforms": doc.get("target_platforms"),
        "template": doc.get("template"),
        "evidence": doc.get("evidence"),
        "dist_digest": build,
        "inputs": inputs,
    }


# --------------------------------------------------------------------------- content


def objective_kind(text: str) -> str:
    t = text.lower()
    t = re.split(r" - |: |, ", t)[0]
    return re.sub(r"\d+", "N", t).strip()


def objective_class(text: str) -> str:
    """A coarse class of a brick-breaker objective line, by its wording."""
    t = text.lower()
    if "boss" in t:
        return "defeat the boss"
    if "without losing a ball" in t:
        return "clear without losing a ball"
    if "red line" in t or "field drops" in t or "creeps down" in t or "falling field" in t:
        return "clear before the descending field lands"
    return "clear the board"


def stats(values: list[float]) -> dict:
    return {
        "min": min(values),
        "mean": round(sum(values) / len(values), 2),
        "max": max(values),
    }


def content_units(run: Run, commit: str, design: dict) -> dict:
    repo = run.game["repo"]
    path = "public/content/units.json"
    data = json.loads(git(repo, "show", f"{commit}:{path}"))
    units = data["units"]
    dunits = {u["id"]: u for u in ((design.get("build_spec") or {}).get("content") or {}).get("units", [])}
    assets = json.loads(git(repo, "show", f"{commit}:public/assets/assets.json"))["assets"]

    def group(u: dict) -> str:
        d = dunits.get(u["id"], {})
        w = (d.get("parameters") or {}).get("world")
        if w is not None:
            return f"world {w}"
        m = re.match(r"w(\d+)-", u["id"])
        return f"world {m.group(1)}" if m else "?"

    legend_cells = collections.Counter()
    structure = collections.Counter()
    per_unit = []
    for u in units:
        lay = u.get("layout") or {}
        cells = sorted({c for row in lay.get("rows", []) for c in row if c != "."})
        legend_cells.update(cells)
        kinds = sorted(k for k in lay if k not in ("rows", "par_time_s"))
        structure.update(kinds or ["static"])
        per_unit.append(
            {
                "id": u["id"],
                "group": group(u),
                "purpose": dunits.get(u["id"], {}).get("purpose"),
                "mechanics": len(u.get("mechanics") or []),
                "cell_kinds": cells,
                "structure": kinds or ["static"],
                "introduces": u.get("introduces") or [],
                "objective_kind": objective_kind(u.get("objective", "")),
                "objective_class": objective_class(u.get("objective", "")),
                "expected_duration_s": u.get("expected_duration_s"),
                "par_time_s": lay.get("par_time_s"),
                "boss": lay.get("boss"),
                "layout": "|".join(lay.get("rows", [])),
            }
        )

    mech = sorted({m for u in units for m in u.get("mechanics") or []})
    combos = collections.Counter(tuple(sorted(u.get("mechanics") or [])) for u in units)
    element_sets = collections.Counter(
        (tuple(p["cell_kinds"]), tuple(p["structure"])) for p in per_unit
    )
    layouts = collections.Counter(p["layout"] for p in per_unit)
    intro_idx = [i + 1 for i, u in enumerate(units) if u.get("introduces")]
    bosses = [p for p in per_unit if p["boss"]]
    boss_art = sorted(k for k, a in assets.items() if "boss" in k and a.get("type") == "sprite")
    boss_rows = []
    for b in bosses:
        kind = b["boss"].get("kind")
        own = [k for k in assets if kind and kind in k]
        boss_rows.append(
            {
                "unit": b["id"],
                "kind": kind,
                "health": b["boss"].get("health"),
                "art_ids": own or boss_art,
                "art_is_kind_specific": bool(own),
            }
        )
    durations = [p["expected_duration_s"] for p in per_unit if p["expected_duration_s"]]
    pars = [p["par_time_s"] for p in per_unit if p["par_time_s"]]
    difficulty_axes = sorted({k for u in units for k in (u.get("difficulty") or {})})
    first, last = units[0].get("difficulty") or {}, units[-1].get("difficulty") or {}
    return {
        "source": f"{path} @ {commit[:12]} (git show), design {design['provenance']['artifact_id']}",
        "unit_kind": data.get("unit_kind"),
        "generation": data.get("generation"),
        "units": len(units),
        "groups": dict(collections.Counter(p["group"] for p in per_unit)),
        "purposes": dict(collections.Counter(p["purpose"] for p in per_unit)),
        "distinct_mechanics": len(mech),
        "mechanics": mech,
        "distinct_cell_kinds": len(legend_cells),
        "cell_kinds_units": dict(sorted(legend_cells.items())),
        "structure_kinds": dict(structure),
        "distinct_structure_kinds": len(structure),
        "mechanics_per_unit": stats([p["mechanics"] for p in per_unit]),
        "distinct_mechanic_combinations": len(combos),
        "distinct_element_combinations": len(element_sets),
        "distinct_element_combination_share": round(len(element_sets) / len(units), 3),
        "repeated_layouts": sum(n - 1 for n in layouts.values() if n > 1),
        "introduction_points": len(intro_idx),
        "last_introduction_at_unit": max(intro_idx) if intro_idx else None,
        "objective_classes": dict(collections.Counter(p["objective_class"] for p in per_unit)),
        "objective_kinds": dict(collections.Counter(p["objective_kind"] for p in per_unit)),
        "distinct_objectives": len({u.get("objective") for u in units}),
        "climax_units": boss_rows,
        "distinct_boss_art": len({a for b in boss_rows for a in b["art_ids"]}),
        "difficulty_axes": difficulty_axes,
        "difficulty_first_last": {"first": first, "last": last},
        "designed_play_s": sum(durations),
        "expected_duration_s": stats(durations),
        "par_sum_s": sum(pars),
        "design_session": {
            k: (design.get("session") or {}).get(k)
            for k in ("first_session_seconds", "target_seconds", "time_to_first_play_s")
        },
        "per_unit": per_unit,
    }


def segment_length(s: dict) -> float:
    import math

    if s["t"] in ("line", "mover"):
        return s["len"]
    if s["t"] == "turn":
        return abs(s["deg"]) * math.pi * s["r"] / 180
    if s["t"] == "jump":
        return s["gap"]
    return 0.0


def content_courses(run: Run, commit: str, design: dict) -> dict:
    repo = run.game["repo"]
    path = "src/game/courses.ts"
    src = git(repo, "show", f"{commit}:{path}")
    proc = subprocess.run(
        ["node", "--no-warnings", "--experimental-strip-types",
         "--input-type=module-typescript", "-"],
        input=src + "\nconsole.log(JSON.stringify(COURSES));\n",
        capture_output=True, text=True, encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"node could not evaluate {path}: {proc.stderr.strip()}")
    courses = json.loads(proc.stdout)
    locale = json.loads(git(repo, "show", f"{commit}:public/locales/en.json"))

    per_unit = []
    for c in courses:
        segs = c["segments"]
        seg_kinds = sorted({s["t"] for s in segs})
        feats = set()
        gems = cps = 0
        for s in segs:
            for k in ("bumpers", "walls", "rails"):
                if s.get(k):
                    feats.add(k)
            if s.get("w") is not None and s["w"] < c["width"]:
                feats.add("narrow")
            if s.get("w") is not None and s["w"] > c["width"]:
                feats.add("plaza")
            if s.get("rise"):
                feats.add("slope")
            if s.get("land"):
                feats.add("drop-landing")
            gems += len(s.get("gems") or []) + (1 if s.get("arcGem") else 0)
            cps += 1 if s.get("cp") else 0
        per_unit.append(
            {
                "id": c["id"],
                "name": locale.get(c["name"], c["name"]),
                "group": locale.get(f"tier.{c['tier']}", f"tier {c['tier']}"),
                "segments": len(segs),
                "segment_kinds": seg_kinds,
                "features": sorted(feats),
                "elements": len(seg_kinds) + len(feats),
                "turns": sum(1 for s in segs if s["t"] == "turn"),
                "length_m": round(sum(segment_length(s) for s in segs), 1),
                "width": c["width"],
                "gems": gems,
                "checkpoints": cps,
                "par_s": c["par_s"],
                "unlock_stars": c["unlock_stars"],
            }
        )
    seg_all = collections.Counter(k for p in per_unit for k in p["segment_kinds"])
    feat_all = collections.Counter(k for p in per_unit for k in p["features"])
    combos = collections.Counter(
        (tuple(p["segment_kinds"]), tuple(p["features"])) for p in per_unit
    )
    mech = [m["id"] for m in (design.get("build_spec") or {}).get("mechanics", [])]
    pars = [p["par_s"] for p in per_unit]
    return {
        "source": f"{path} @ {commit[:12]} (git show, evaluated by node), "
        f"design {design['provenance']['artifact_id']} (schema "
        f"{design['provenance']['schema_version']}, no build_spec.content)",
        "unit_kind": "course (not a content-contract unit: no public/content/units.json)",
        "units": len(courses),
        "groups": dict(collections.Counter(p["group"] for p in per_unit)),
        "purposes": None,
        "distinct_mechanics": len(mech),
        "mechanics": mech,
        "segment_kinds_units": dict(seg_all),
        "feature_kinds_units": dict(feat_all),
        "distinct_element_kinds": len(seg_all) + len(feat_all),
        "distinct_structure_kinds": len(seg_all),
        "elements_per_unit": stats([p["elements"] for p in per_unit]),
        "distinct_element_combinations": len(combos),
        "distinct_element_combination_share": round(len(combos) / len(courses), 3),
        "objective_classes": {"reach the goal gate (+ par stars, gems)": len(courses)},
        "climax_units": [],
        "climax_note": "the design declares no climax or boss unit; the last course of each "
        "tier is not marked as one",
        "unlock_gates": {p["id"]: p["unlock_stars"] for p in per_unit if p["unlock_stars"]},
        "par_sum_s": sum(pars),
        "par_s": stats(pars),
        "length_m": stats([p["length_m"] for p in per_unit]),
        "gems_total": sum(p["gems"] for p in per_unit),
        "design_session": {
            k: (design.get("session") or {}).get(k)
            for k in ("first_session_seconds", "target_seconds", "time_to_first_play_s")
        },
        "per_unit": per_unit,
    }


def content(run: Run, commit: str) -> dict:
    g4 = [d for d in decisions(run) if d["gate_id"] == "G4" and d["decision"] == "pass"][-1]
    design_file = next(s["file"] for s in g4["subject"] if "game-design" in (s["file"] or ""))
    kind, v = design_file.split("/")[1], int(design_file.split("/v")[-1][:-5])
    design = dict(run.versions[kind])[v]
    fn = content_units if run.game["content"] == "units" else content_courses
    return {"design": run.ref(kind, v), **fn(run, commit, design)}


# --------------------------------------------------------------------------- cost and time


def costs(run: Run) -> dict:
    sessions = []
    spawned = collections.Counter()
    decisions_ev = collections.Counter()
    resumes = budget = 0
    for e in run.events:
        d = e.get("data") or {}
        if e["event"] == "STEP_LOG" and d.get("budget") == "developer-cost":
            sessions.append(
                {"step": e.get("step_id"), "at": e["ts"], "cost_usd": round(d["cost"], 4),
                 "transcript": Path(d.get("transcript", "")).name}
            )
        elif e["event"] == "STEP_PROGRESS" and d.get("kind") == "spawned":
            spawned[(e.get("step_id"), d.get("argv0"))] += 1
        elif e["event"] == "DECISION_RECORDED":
            decisions_ev[(e.get("step_id"), d.get("decision"))] += 1
        elif e["event"] == "WORKFLOW_RESUMED":
            resumes += 1
        elif e["event"] == "BUDGET_RAISED":
            budget += 1
    by_step = collections.defaultdict(lambda: {"sessions": 0, "cost_usd": 0.0})
    for s in sessions:
        by_step[s["step"]]["sessions"] += 1
        by_step[s["step"]]["cost_usd"] = round(by_step[s["step"]]["cost_usd"] + s["cost_usd"], 4)
    raised = [e["data"] for e in run.events if e["event"] == "BUDGET_RAISED"]
    agent_spawns = {f"{k[0]}:{k[1]}": n for k, n in sorted(spawned.items()) if k[1] == "claude"}
    return {
        "developer_budget": run.state["params"].get("develop_budget"),
        "budget_raises": raised,
        "developer_sessions": len(sessions),
        "developer_cost_usd": round(sum(s["cost_usd"] for s in sessions), 2),
        "developer_by_step": dict(by_step),
        "developer_sessions_detail": sessions,
        "agent_processes_spawned": agent_spawns,
        "agent_processes_total": sum(agent_spawns.values()),
        "uncounted": "only developer sessions record a cost; design, asset-author, judge, "
        "reviewer and copy sessions record none, and lead/worker/delegated-agent sessions "
        "outside the engine are not in the run at all",
        "human_decisions": {f"{k[0]}:{k[1]}": n for k, n in sorted(decisions_ev.items())},
        "handoff_visits": sum(n for (s, d), n in decisions_ev.items()
                              if s in ("greybox", "develop") and d == "done"),
        "resumes": resumes,
    }


def timing(run: Run) -> dict:
    st = run.state
    ev = run.events
    first = ev[0]["ts"]
    g4 = [e["ts"] for e in ev if e["event"] == "DECISION_RECORDED"
          and e.get("step_id") == "prototype-review" and (e["data"] or {}).get("decision") == "pass"]
    g6_wait = [e["ts"] for e in ev if e["event"] == "STEP_WAITING"
               and e.get("step_id") == "publish-review"]
    done = [e["ts"] for e in ev if e["event"] == "STEP_COMPLETED" and e.get("step_id") == "release"]
    busy_ms = sum(e.get("duration_ms") or 0 for e in ev
                  if e["event"] in ("STEP_COMPLETED", "STEP_FAILED", "STEP_WAITING"))
    visits = {k: v.get("visits") for k, v in st["steps"].items()}
    executions = {k: v.get("executions") for k, v in st["steps"].items()}
    return {
        "created_at": st["created_at"],
        "first_event": first,
        "g4_pass_at": g4[-1] if g4 else None,
        "release_drafted_at": done[-1] if done else None,
        "g6_waiting_since": g6_wait[-1] if g6_wait else None,
        "wall_h_to_g4": hours(first, g4[-1]) if g4 else None,
        "wall_h_to_release": hours(first, done[-1]) if done else None,
        "wall_h_to_g6_wait": hours(first, g6_wait[-1]) if g6_wait else None,
        "engine_step_time_h": round(busy_ms / 3.6e6, 2),
        "status": st["status"],
        "cursor": st["cursor"],
        "visits": visits,
        "executions": executions,
        "trail_entries": len(st["trail"]),
        "failed_step_events": sum(1 for e in ev if e["event"] == "STEP_FAILED"),
        "blocked_events": [
            {"at": e["ts"], "step": e.get("step_id"), "message": (e["data"] or {}).get("message")}
            for e in ev if e["event"] == "WORKFLOW_BLOCKED"
        ],
    }


# --------------------------------------------------------------------------- factory commit


def reflog(factory: Path) -> list[tuple[dt.datetime, str, str]]:
    rows = []
    for line in git(factory, "reflog", "--date=iso-strict", "--format=%H\t%gd\t%gs").splitlines():
        sha, sel, msg = line.split("\t", 2)
        m = re.search(r"\{(.+)\}", sel)
        rows.append((dt.datetime.fromisoformat(m.group(1)), sha, msg))
    return sorted(rows)


def factory_at(log, when: str) -> str | None:
    t = ts(when)
    cur = None
    for at, sha, _ in log:
        if at <= t:
            cur = sha
    return cur


def describe_factory(sha: str) -> dict:
    parents = git(REPO, "rev-list", "--parents", "-n", "1", sha).split()[1:]
    on_main = subprocess.run(["git", "-C", str(REPO), "merge-base", "--is-ancestor", sha, MAIN]).returncode == 0
    row = {"sha": sha[:12], "subject": git(REPO, "log", "-1", "--format=%s", sha).strip(),
           "date": git(REPO, "log", "-1", "--format=%cI", sha).strip(), "on_main": on_main}
    if not on_main:
        for p in parents:
            if subprocess.run(["git", "-C", str(REPO), "merge-base", "--is-ancestor", p, MAIN]).returncode == 0:
                same = subprocess.run(["git", "-C", str(REPO), "diff", "--quiet", sha, p]).returncode == 0
                row["main_parent"] = p[:12]
                row["tree_equals_main_parent"] = same
    return row


def factory(run: Run) -> dict:
    log = reflog(run.game["factory"])
    marks = {}
    for e in run.events:
        if e["event"] == "STEP_STARTED":
            marks.setdefault(e["step_id"], []).append(e["ts"])
    points = {
        "run_start": run.events[0]["ts"],
        "last_develop_start": marks.get("develop", [None])[-1],
        "last_playability_start": marks.get("playability", [None])[-1],
        "last_visual_qa_start": marks.get("visual-qa", [None])[-1],
        "last_verify_start": marks.get("verify", [None])[-1],
        "release_start": marks.get("release", [None])[-1],
        "platform_validate_start": marks.get("platform-validate", [None])[-1],
    }
    used = {k: factory_at(log, v) for k, v in points.items() if v}
    distinct = sorted({s for s in used.values() if s}, key=lambda s: [r[1] for r in log].index(s))
    return {
        "worktree": str(run.game["factory"]),
        "head": git(run.game["factory"], "rev-parse", "HEAD").strip()[:12],
        "dirty": bool(git(run.game["factory"], "status", "--porcelain").strip()),
        "head_moves": len(log),
        "at": {k: (v[:12] if v else None) for k, v in used.items()},
        "commits": [describe_factory(s) for s in distinct],
        "note": "commit in force at each point, from the worktree reflog; the run read the "
        "Factory from this worktree throughout",
    }


# --------------------------------------------------------------------------- main


def measure(game: dict) -> dict:
    run = Run(game)
    rel = release(run)
    return {
        "game": game["name"],
        "dimension": game["key"].upper(),
        "run_id": game["run_id"],
        "project": str(game["project"]),
        "repo": str(game["repo"]),
        "workflow": {k: run.state[k] for k in ("workflow_id", "workflow_version", "status", "cursor")},
        "idea": run.state["params"].get("idea"),
        "factory": factory(run),
        "release": rel,
        "gates": gates(run),
        "decisions": decisions(run),
        "content": content(run, rel["commit_sha"]),
        "costs": costs(run),
        "timing": timing(run),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", help="write the JSON here instead of stdout")
    args = ap.parse_args()
    doc = {
        "format": 1,
        "kind": "old-factory-baseline",
        "baseline_main": git(REPO, "rev-parse", MAIN).strip(),
        "script": "docs/benchmark/baseline.py",
        "status": "OBSERVED BASELINE - what the old Factory produced and recorded; not expected "
        "findings for the new Factory",
        "games": [measure(g) for g in GAMES],
    }
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
