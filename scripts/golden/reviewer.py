#!/usr/bin/env python3
"""The golden-run reviewer: a deterministic rule check standing in for a review agent.

    reviewer.py --game 2d|3d --repo <checkout> --verdict <path> --commit <sha> [--brief <md>]

What `factory.review.reviewer: {kind: command}` runs in a golden run, through the real review
step (docs/review-module.md), which fingerprints the checkout around it. It is NOT an AI
reviewer and makes no judgement of quality or fun. It checks, from git objects only (it
never runs `git status`, which may rewrite the index, and writes nothing but the verdict):

    commit-exists        the commit under review is a commit object, and is HEAD
    allowed-paths        the commit changes, since the brief's baseline, only paths a game may
                         change (src/, tests/, public/, index.html, docs/development/,
                         docs/GDD.md - the design the develop step renders -, package.json,
                         pnpm-lock.yaml) and none the template owns
    engine-dependencies  package.json adds no dependency but the design's engine packages
    no-portal-sdk        no portal SDK identifier or script URL anywhere in src/
    ad-calls-in-seam     showRewarded / showInterstitial only under src/platform/
    tests-present        a unit test and a browser test ship with the game, and the browser
                         test is tagged for boot, start, game over and restart
    report-present       docs/development/report.json is committed and says what built it

Any failed check is a blocker, and the verdict is `request-changes`; otherwise `approve`.
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from wgflib import procs  # noqa: E402

REVIEWER = ("golden-run reviewer (scripts/golden/reviewer.py): deterministic rule checks, "
            "not an AI reviewer")

ALLOWED = (re.compile(r"^src/"), re.compile(r"^tests/(unit|e2e)/"), re.compile(r"^public/"),
           re.compile(r"^index\.html$"), re.compile(r"^docs/development/"),
           re.compile(r"^docs/GDD\.md$"),
           re.compile(r"^package\.json$"), re.compile(r"^pnpm-lock\.yaml$"))
TEMPLATE_OWNED = ("packages/", "game.config.yaml", ".github/", "scripts/", "config/platforms/",
                  "playwright.config.ts", "vite.config.ts", "vitest.workspace.ts",
                  "eslint.config.js", "tsconfig.base.json", "pnpm-workspace.yaml")
ENGINE_PACKAGES = {"pixijs": {"pixi.js"}, "threejs": {"three", "@types/three"}}
PORTAL_SDK = re.compile(
    r"\bYaGames\b|yandex\.ru/games/sdk|\bPokiSDK\b|game-cdn\.poki\.com|@poki/|"
    r"\bCrazyGames\s*\.\s*SDK\b|window\.CrazyGames\b|sdk\.crazygames\.com|"
    r"\bGameVuiSDK\b|gamevui-sdk")
AD_CALL = re.compile(r"\.show(Rewarded|Interstitial)\s*\(")
REQUIRED_TAGS = ("@boot", "@start", "@game-over", "@restart")


class Git:
    def __init__(self, repo):
        self.repo = repo

    def __call__(self, *args):
        result = procs.run(["git", "-C", self.repo, *args], timeout=60)
        return result.returncode, result.stdout

    def text(self, *args):
        code, out = self(*args)
        return out if code == 0 else None


def review(game_key, repo, commit):
    git = Git(repo)
    blockers = []

    def block(check, summary, file=None, line=None):
        # `file` is always present - null for a finding about the build as a whole - because
        # the review verdict contract requires the key on every blocker.
        entry = {"id": f"{check}-{len(blockers) + 1}", "file": file or None,
                 "summary": summary, "severity": "blocker"}
        if line:
            entry["line"] = line
        blockers.append(entry)

    # commit-exists
    kind = (git.text("cat-file", "-t", commit) or "").strip()
    head = (git.text("rev-parse", "HEAD") or "").strip()
    if kind != "commit":
        block("commit-exists", f"{commit} is not a commit in this repository")
        return blockers, {}
    if head != commit:
        block("commit-exists", f"HEAD is {head}, not the commit under review {commit}")

    brief = json.loads(git.text("show", f"{commit}:docs/development/brief.json") or "{}")
    engine = brief.get("engine")
    baseline = brief.get("baseline_commit")
    if not baseline or (git.text("cat-file", "-t", baseline) or "").strip() != "commit":
        block("allowed-paths", "the committed brief names no baseline commit to review from",
              file="docs/development/brief.json")
        return blockers, {"engine": engine}

    # allowed-paths
    changed = [line.split("\t") for line in
               (git.text("diff", "--name-status", "--no-renames", baseline, commit) or "")
               .splitlines() if line.strip()]
    paths = [parts[-1] for parts in changed]
    for path in paths:
        if any(path == p.rstrip("/") or path.startswith(p) for p in TEMPLATE_OWNED):
            block("allowed-paths", f"{path} is template-owned and changed", file=path)
        elif not any(p.search(path) for p in ALLOWED):
            block("allowed-paths", f"{path} is outside the paths a game may change", file=path)

    # engine-dependencies
    before = json.loads(git.text("show", f"{baseline}:package.json") or "{}")
    after = json.loads(git.text("show", f"{commit}:package.json") or "{}")
    for field in ("dependencies", "devDependencies"):
        added = set(after.get(field) or {}) - set(before.get(field) or {})
        for name in sorted(added - ENGINE_PACKAGES.get(engine, set())):
            block("engine-dependencies", f"package.json adds {name} ({field}); only the "
                                         f"{engine} packages are expected", file="package.json")

    # no-portal-sdk, ad-calls-in-seam
    tree = (git.text("ls-tree", "-r", "--name-only", commit, "src") or "").splitlines()
    for path in tree:
        if not path.endswith((".ts", ".js", ".mjs", ".tsx")):
            continue
        text = git.text("show", f"{commit}:{path}") or ""
        for number, line in enumerate(text.splitlines(), 1):
            if PORTAL_SDK.search(line):
                block("no-portal-sdk", "portal SDK referenced in game code", path, number)
            if AD_CALL.search(line) and not path.startswith("src/platform/"):
                block("ad-calls-in-seam", "ad API called outside src/platform/", path, number)

    # tests-present
    tests = (git.text("ls-tree", "-r", "--name-only", commit, "tests") or "").splitlines()
    unit = [p for p in paths if p.startswith("tests/unit/") and p in tests]
    e2e = [p for p in paths if p.startswith("tests/e2e/") and p.endswith(".spec.ts")
           and p in tests]
    if not unit:
        block("tests-present", "no unit test ships with the game")
    if not e2e:
        block("tests-present", "no browser test ships with the game")
    else:
        text = "\n".join(git.text("show", f"{commit}:{p}") or "" for p in e2e)
        missing = [t for t in REQUIRED_TAGS if t not in text]
        if missing:
            block("tests-present", "the browser tests cover no " + ", ".join(missing), e2e[0])

    # report-present
    report = git.text("show", f"{commit}:docs/development/report.json")
    try:
        report = json.loads(report) if report else None
    except ValueError:
        report = None
    if not isinstance(report, dict):
        block("report-present", "docs/development/report.json is not committed")
    elif report.get("engine") != engine:
        block("report-present", f"the report says engine {report.get('engine')!r}, the brief "
                                f"{engine!r}", "docs/development/report.json")
    replay = (report or {}).get("replay") or {}
    return blockers, {"engine": engine, "changed": len(paths), "unit_tests": unit,
                      "browser_tests": e2e, "developer": replay.get("developer")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--game", required=True, choices=["2d", "3d"])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--verdict", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--brief", default=None)
    args = parser.parse_args(argv)
    procs.install_signal_cleanup()

    blockers, facts = review(args.game, os.path.abspath(args.repo), args.commit)
    notes = (f"{REVIEWER}. Checked commit-exists, allowed-paths, engine-dependencies, "
             f"no-portal-sdk, ad-calls-in-seam, tests-present, report-present against "
             f"{facts.get('changed', 0)} changed path(s); engine {facts.get('engine')}; "
             f"built by: {facts.get('developer') or 'unstated'}.")
    verdict = {"verdict": "request-changes" if blockers else "approve", "commit": args.commit,
               "blockers": blockers, "notes": notes}
    with open(args.verdict, "w", encoding="utf-8") as handle:
        json.dump(verdict, handle, indent=2)
        handle.write("\n")
    print(f"[golden-reviewer] {verdict['verdict']} ({len(blockers)} blocker(s))", flush=True)
    for blocker in blockers:
        print(f"[golden-reviewer]   {blocker['id']}: {blocker['summary']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
