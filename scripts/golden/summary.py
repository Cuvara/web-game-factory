"""The golden summary: what one golden run did, as machine-readable JSON.

Built only from what the run left behind - run state, the artifacts in the run store, the
game repository's git history and release directory, and the browser evidence. Nothing is
re-derived from console output, and every evidence status is copied exactly as the module
that wrote it recorded it: PASS_MOCK stays PASS_MOCK, BLOCKED_EXTERNAL stays
BLOCKED_EXTERNAL. The summary never upgrades a status.

    passed = every step in games.EXPECTED_STEPS reached its expected outcome
             AND release drafted a manifest (release/<id>/manifest.json exists and its zip
             sha256s reproduce)
             AND the engine is the one the game needs, everywhere it is recorded
    browser_passed = the independent browser evidence passed (reported separately)
"""

import json
import os

from wgflib import procs
from wgflib.yamllite import YamlError, load as yaml_load

from golden import games
from golden.browser import sha256_file

EVIDENCE_STATUSES = ("PASS", "PASS_MOCK", "BLOCKED_EXTERNAL", "UNVERIFIED", "FAIL")


def _git(repo, *args):
    result = procs.run(["git", "-C", repo, *args], timeout=60)
    return result.stdout if result.ok else None


def _artifacts(api, state):
    records, contents = [], {}
    for artifact_id, versions in sorted(state.artifacts.items()):
        for ref in versions:
            records.append({"ref": f"{ref.id}@v{ref.version}", "type": ref.type,
                            "content_hash": ref.content_hash, "checksum": ref.checksum,
                            "schema_version": ref.schema_version,
                            "produced_by": ref.produced_by, "seq": ref.seq})
        latest = versions[-1]
        try:
            contents[latest.type] = api.store.read_artifact(state.run_id, latest)
        except Exception as exc:  # a summary reports; it does not fail on a bad artifact
            contents[latest.type] = {"_unreadable": str(exc)}
    records.sort(key=lambda r: (r["seq"] or 0))
    return records, contents


def _steps(state):
    expected = dict(games.EXPECTED_STEPS)
    rows, ok = [], True
    for step_id, outcome in games.EXPECTED_STEPS:
        st = state.steps.get(step_id)
        status = st.status if st else "NOT_RUN"
        reached = status == outcome
        ok = ok and reached
        rows.append({
            "step": step_id, "expected": outcome, "status": status, "reached": reached,
            "route": st.last_route if st else None,
            "duration_s": round((st.duration_ms or 0) / 1000, 3) if st else None,
            "visits": st.visits if st else 0, "executions": st.executions if st else 0,
            "message": ((st.message or st.error) or "")[:1500] if st else None,
        })
    extra = sorted(set(state.steps) - set(expected))
    return rows, ok, extra


def _evidence(contents):
    out = {}
    verification = contents.get("verification-report") or {}
    qa = contents.get("qa-report") or {}
    manifest = contents.get("release-manifest") or {}
    sdk = contents.get("sdk-report") or {}
    out["verification_report"] = {
        "verdict": verification.get("verdict"),
        "evidence_status": verification.get("evidence_status"),
        "checks": _count(verification.get("checks") or [], "evidence_status"),
        "not_pass": [{"id": c.get("id"), "status": c.get("status"),
                      "evidence_status": c.get("evidence_status"),
                      "required": c.get("required")}
                     for c in verification.get("checks") or []
                     if c.get("evidence_status") != "PASS"],
        "platform_readiness": verification.get("platform_readiness"),
    }
    out["qa_report"] = {"verdict": qa.get("verdict"),
                        "evidence_status": qa.get("evidence_status")}
    evidence = manifest.get("evidence") or {}
    out["release_manifest"] = {
        "state": manifest.get("state"),
        "evidence_status": evidence.get("status"),
        "platforms": [{k: p.get(k) for k in ("platform_id", "readiness", "evidence_status",
                                              "portal_status", "external_approval")}
                      for p in evidence.get("platforms") or []],
        "reproducibility": evidence.get("reproducibility"),
    }
    out["sdk_report"] = [{"platform_id": p.get("platform_id"), "status": p.get("status")}
                         for p in sdk.get("platforms") or []]
    seen = {s for s in (out["verification_report"]["evidence_status"],
                        out["qa_report"]["evidence_status"],
                        out["release_manifest"]["evidence_status"]) if s}
    out["unknown_statuses"] = sorted(seen - set(EVIDENCE_STATUSES))
    return out


def _count(items, key):
    counts = {}
    for item in items:
        counts[item.get(key)] = counts.get(item.get(key), 0) + 1
    return counts


def _release(repo, manifest):
    if not manifest or not manifest.get("release_id"):
        return None
    release_id = manifest["release_id"]
    base = os.path.join(repo, "release", release_id)
    manifest_path = os.path.join(base, "manifest.json")
    targets = manifest.get("target_platforms") or []
    ids = [t.get("id") or t.get("platform_id") for t in targets]
    primary = next((i for i, t in zip(ids, targets) if t.get("role") == "required"),
                   ids[0] if ids else None)
    packages = []
    for package in manifest.get("packages") or []:
        path = os.path.join(base, package.get("filename") or "")
        actual = sha256_file(path) if os.path.isfile(path) else None
        packages.append({"platform_id": package.get("platform_id"),
                         "path": os.path.relpath(path, repo),
                         "checksum": package.get("checksum"), "sha256": actual,
                         "reproduces": actual == package.get("checksum"),
                         "content_digest": package.get("content_digest"),
                         "files": package.get("files")})
    return {"release_id": release_id, "state": manifest.get("state"),
            "manifest_path": os.path.relpath(manifest_path, repo)
            if os.path.isfile(manifest_path) else None,
            "manifest_sha256": sha256_file(manifest_path)
            if os.path.isfile(manifest_path) else None,
            "commit_sha": manifest.get("commit_sha"), "primary_platform": primary,
            "packages": packages}


def _engine_type(value):
    return value.get("type") if isinstance(value, dict) else value


def _engine(game, contents, repo, browser):
    design = contents.get("game-design") or {}
    scaffold = contents.get("scaffold-record") or {}
    plan = contents.get("tech-plan") or {}
    config = {}
    text = _git(repo, "show", "HEAD:game.config.yaml")
    if text:
        try:
            config = yaml_load(text) or {}
        except YamlError:
            config = {}
    recorded = {
        "game-design": _engine_type(design.get("engine")),
        "tech-plan": _engine_type(plan.get("engine")),
        "tech-plan.repo_params": _engine_type(
            ((plan.get("repo_params") or {}).get("game_config") or {}).get("engine")),
        "scaffold-record": _engine_type((scaffold.get("game_config") or {}).get("engine")),
        "game.config.yaml@HEAD": _engine_type(config.get("engine")),
        "browser window.__wgf__": ((browser or {}).get("probe") or {}).get("engine_reported"),
    }
    values = {v for v in recorded.values() if isinstance(v, str) and v}
    return {"expected": game.engine, "recorded": recorded,
            "consistent": values == {game.engine}}


def _repository(repo):
    log = _git(repo, "log", "--format=%H%x09%s") or ""
    commits = [dict(zip(("sha", "subject"), line.split("\t", 1)))
               for line in log.splitlines() if line.strip()]
    for commit in commits:
        files = _git(repo, "show", "--name-only", "--format=", commit["sha"]) or ""
        commit["files"] = sorted(f for f in files.splitlines() if f.strip())
    status = _git(repo, "status", "--porcelain", "--untracked-files=all") or ""
    return {"path": repo, "head": commits[0]["sha"] if commits else None,
            "commits": commits, "dirty_paths": status.splitlines()[:50],
            "clean": status.strip() == ""}


def _ancestors(pid):
    chain = set()
    while pid and pid not in chain:
        chain.add(pid)
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
                pid = int(handle.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return chain


def leftover_processes(marker):
    """Live processes whose command line or cwd names `marker` (the work directory)."""
    found = []
    ancestors = _ancestors(os.getpid())  # this process and whoever started it
    for name in os.listdir("/proc") if os.path.isdir("/proc") else []:
        if not name.isdigit() or int(name) in ancestors:
            continue
        try:
            with open(f"/proc/{name}/cmdline", "rb") as handle:
                cmdline = handle.read().replace(b"\0", b" ").decode("utf-8", "replace")
            cwd = os.readlink(f"/proc/{name}/cwd")
        except OSError:
            continue
        if marker in cmdline or cwd.startswith(marker):
            found.append({"pid": int(name), "cmdline": cmdline[:300], "cwd": cwd})
    return found


def _production(contents):
    """The production gates' newest reports: what a golden run must pass for its art and UI.
    `passed` only when production-quality is PASS and visual-qa is PASS by a judge that
    looked (the baseline judge, or a command) - never a mock or `none`."""
    quality = contents.get("production-quality-report") or {}
    visual = contents.get("visual-qa-report") or {}
    judge = (visual.get("judge") or {}).get("kind")
    return {
        "production_quality": {"verdict": quality.get("verdict"),
                               "commit": quality.get("commit"),
                               "failed": list(quality.get("failed") or []),
                               "checks": len(quality.get("checks") or []),
                               "passed": sum(1 for c in quality.get("checks") or []
                                             if c.get("status") == "PASS")},
        "visual_qa": {"verdict": visual.get("verdict"), "commit": visual.get("commit"),
                      "judge": judge, "failed": list(visual.get("failed") or []),
                      "frames": len(visual.get("frames") or []),
                      "findings": [f.get("id") for f in visual.get("findings") or []],
                      "look": (visual.get("look") or {}).get("verdict")},
        "passed": (quality.get("verdict") == "PASS" and visual.get("verdict") == "PASS"
                   and judge in ("baseline", "command")),
    }


def _listing(contents, repo):
    """The store listing a golden run captured from its verified build, and its validation:
    `passed` only when the listing is complete with real screenshots, a recorded trailer and
    browser-composed branding, validated PASS, and shipped beside the release's packages."""
    listing = contents.get("store-listing") or {}
    report = contents.get("listing-validation-report") or {}
    manifest = contents.get("release-manifest") or {}
    shipped = ((manifest.get("evidence") or {}).get("store_listing") or {})
    release_id = manifest.get("release_id")
    shipped_dir = (os.path.join(repo, "release", release_id, "listing")
                   if repo and release_id else None)
    return {
        "status": listing.get("status"),
        "commit": listing.get("commit"),
        "screenshots": [{"id": s.get("id"), "scene": s.get("scene"), "viewport": s.get("viewport"),
                         "state": s.get("state")} for s in listing.get("screenshots") or []],
        "trailer": {k: (listing.get("trailer") or {}).get(k)
                    for k in ("status", "container", "duration_s", "trimmed")},
        "branding": {"method": (listing.get("branding") or {}).get("method"),
                     "items": [i.get("id") for i in (listing.get("branding") or {}).get("items") or []]},
        "locales": sorted(((listing.get("copy") or {}).get("locales") or {})),
        "platforms": [{"platform_id": p.get("platform_id"), "files": len(p.get("files") or []),
                       "unmet": [u.get("code") for u in p.get("unmet") or []]}
                      for p in listing.get("platforms") or []],
        "problems": [p.get("code") for p in listing.get("problems") or []],
        "validation": {"verdict": report.get("verdict"), "failed": list(report.get("failed") or []),
                       "unknown": len(report.get("unknown") or []),
                       "platforms": {p.get("platform_id"): p.get("status")
                                     for p in report.get("platform_requirements") or []}},
        "shipped": bool(shipped) and bool(shipped_dir and os.path.isdir(shipped_dir)),
        "store_metadata_platforms": sorted((manifest.get("store_metadata") or {})),
        "passed": (listing.get("status") == "complete" and report.get("verdict") == "PASS"
                   and len(listing.get("screenshots") or []) >= 3
                   and (listing.get("trailer") or {}).get("status") == "recorded"
                   and (listing.get("branding") or {}).get("method") == "browser-composed"
                   and bool(shipped)),
    }


def build(run, api, state, seconds, browser):
    artifacts, contents = _artifacts(api, state)
    steps, steps_ok, extra = _steps(state)
    repository = _repository(run.repo) if os.path.isdir(run.repo) else None
    release = _release(run.repo, contents.get("release-manifest")) if repository else None
    engine = (_engine(run.game, contents, run.repo, browser) if repository
              else {"consistent": False})
    drafted = bool(release and release["manifest_path"] and release["packages"]
                   and all(p["reproduces"] for p in release["packages"]))
    manifest = contents.get("release-manifest") or {}
    review_status = ((manifest.get("evidence") or {}).get("review") or {}).get("status")
    # A golden run passes only through a real review: `skipped` (reviewer kind none) or an
    # absent review is a run that proves less than it claims.
    # And only through the production gates: the port's art delivered and drawn
    # (production-quality) and its frames matching the approved ones (visual-qa).
    production = _production(contents)
    # And only with its store listing: captured from the verified build, validated, shipped.
    listing = _listing(contents, run.repo if repository else None)
    passed = (steps_ok and drafted and engine["consistent"] and review_status == "approved"
              and production["passed"] and listing["passed"])
    return {
        "format": 1,
        "golden": run.game.key,
        "title_id": run.game.title_id,
        "workflow": "new-game",
        "run_id": state.run_id,
        "run_status": state.status,
        "run_message": state.message,
        "duration_s": round(seconds, 1),
        "workdir": run.workdir,
        "template": run.template_dir,
        "template_ref": run.config_data["init"]["template_ref"],
        "developer": "golden-run replay developer (scripts/golden/replay_developer.py) - a "
                     "deterministic port of a known-good template example, NOT an AI developer",
        "reviewer": "golden-run reviewer (scripts/golden/reviewer.py) - deterministic rule "
                    "checks, NOT an AI reviewer",
        "auto_approved_gates": list(run.config_data["checkpoints"]["auto_approve"]),
        "review_status": review_status,
        "production": production,
        "listing": listing,
        "steps": steps,
        "unexpected_steps": extra,
        "artifacts": artifacts,
        "repository": repository,
        "engine": engine,
        "release": release,
        "evidence": _evidence(contents),
        "browser": browser,
        "leftover_processes": leftover_processes(run.workdir),
        "pipeline_passed": passed,
        "browser_passed": bool(browser and browser.get("passed")),
        "passed": passed,
    }


def write(summary, evidence_dir, key):
    os.makedirs(evidence_dir, exist_ok=True)
    path = os.path.join(evidence_dir, f"golden-{key}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")
    summary["summary_path"] = path
    return path
