"""Browser e2e for the sdk module: a real template revision, the real step, a built game.

    python -m wgf_sdk.e2e --template ../web-game-template --ref origin/main --work <dir>

run from `scripts/`. For one web-game-template revision it:

    1. exports the revision into <work>/tree and installs its dependencies (pnpm)
    2. makes it a develop-step game: the seam develop hands out (src/game/integration.ts,
       from wgf_develop), a plain default implementation of it, and a stand-in gameplay
       loop (e2e/run-loop.ts) that calls only the seam, with its own placement ids
    3. runs the `sdk` step on it for real: the integration phase (inspection, plan, files,
       main.ts and seam wiring, the integration's own vitest suite and typecheck) and the
       conformance phase (the template's `pnpm sdk:conformance`, where the ref has it)
    4. runs the template's own checks over the result: every unit and integration test,
       the typecheck and the lint
    5. for each engine and each target platform: writes game.config.yaml with that platform
       first, builds the production bundle, and runs e2e/smoke.spec.ts against it in
       Chromium (desktop and mobile), with every portal SDK URL fulfilled from the mock the
       template itself ships, or aborted to play an ad blocker
    6. builds once more for a platform the revision has no adapter for, and checks that the
       boot fails visibly

It writes <work>/e2e-summary.json and exits non-zero if anything failed. It contacts no
portal and publishes nothing. Needs node, pnpm and Playwright's Chromium on the machine; it
is not part of `python -m unittest`, which stays offline.
"""

import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from wgflib import paths, procs  # noqa: E402
from wgflib.workflow.config import load_config  # noqa: E402

from .inspect_sdk import inspect_sdk  # noqa: E402
from .step import SdkStep  # noqa: E402

E2E = os.path.join(HERE, "e2e")
PLATFORMS = ("yandex", "crazygames", "poki", "gamevui")
ENGINES = ("pixijs", "threejs")

# A design with one rewarded and one interstitial placement on every platform: the widest
# integration the step can make, so every hook is exercised.
DESIGN = {
    "provenance": {"artifact_id": "wgf:game-design:sdk-e2e:20260923-01",
                   "content_hash": "sha256:" + "0" * 64},
    "title_id": "sdk-e2e",
    "monetization": {"placements": [
        {"kind": "rewarded", "trigger": "On death, offer a continue",
         "player_value": "Continue the run"},
        {"kind": "interstitial", "trigger": "Between levels"},
    ]},
    "retention": {"hooks": ["progression"], "return_reason": "beat the best score"},
}


def sh(argv, cwd, timeout=900, env=None, check=True):
    """Run a command as an owned process tree (wgflib.procs): the preview servers and
    browsers a Playwright run starts never outlive it, even on a timeout."""
    started = time.monotonic()
    done = procs.run(argv, cwd=cwd, timeout=timeout, env={**os.environ, **(env or {})})
    took = round(time.monotonic() - started, 1)
    if done.error is not None:
        raise RuntimeError(f"{' '.join(argv)} could not be started: {done.error}")
    if done.timed_out:
        raise RuntimeError(f"{' '.join(argv)} timed out after {took}s:\n{done.tail(60)}")
    if check and done.returncode != 0:
        raise RuntimeError(f"{' '.join(argv)} failed ({done.returncode}) in {took}s:\n"
                           f"{(done.stdout + done.stderr)[-3000:]}")
    return done


def prepare(template, ref, tree):
    if os.path.exists(tree):
        shutil.rmtree(tree)
    os.makedirs(tree)
    archive = os.path.join(os.path.dirname(os.path.abspath(tree)), "template.tar")
    sh(["git", "-C", template, "archive", "-o", archive, ref], None, timeout=300)
    try:
        sh(["tar", "-x", "-f", archive, "-C", tree], None, timeout=300)
    finally:
        os.remove(archive)
    sh(["pnpm", "install", "--frozen-lockfile", "--prefer-offline"], tree)
    commit = sh(["git", "-C", template, "rev-parse", ref], None, timeout=60).stdout.strip()
    return commit


def install_fixtures(tree):
    """Make the template a develop-step game: the seam, a default implementation, a loop."""
    from wgf_develop.brief import INTEGRATION_CONTRACT  # the contract develop hands out

    with open(os.path.join(tree, "src", "game", "integration.ts"), "w",
              encoding="utf-8") as handle:
        handle.write(INTEGRATION_CONTRACT)
    shutil.copy(os.path.join(E2E, "run-loop.ts"), os.path.join(tree, "src", "game"))
    shutil.copy(os.path.join(E2E, "default-integration.ts"),
                os.path.join(tree, "src", "platform"))
    main = os.path.join(tree, "src", "main.ts")
    with open(main, encoding="utf-8") as handle:
        lines = handle.read().splitlines(keepends=True)
    last_import = max(i for i, line in enumerate(lines) if line.startswith("import "))
    lines[last_import + 1:last_import + 1] = [
        'import { DefaultIntegration } from "./platform/default-integration.js";\n',
        'import { startRunLoop } from "./game/run-loop.js";\n',
    ]
    game = next(i for i, line in enumerate(lines) if "const game = new Game();" in line)
    lines.insert(game + 1, "  startRunLoop(new DefaultIntegration(platform), game);\n")
    with open(main, "w", encoding="utf-8") as handle:
        handle.write("".join(lines))
    os.makedirs(os.path.join(tree, "tests", "wgf-sdk-e2e"), exist_ok=True)
    shutil.copy(os.path.join(E2E, "smoke.spec.ts"),
                os.path.join(tree, "tests", "wgf-sdk-e2e", "smoke.spec.ts"))
    shutil.copy(os.path.join(E2E, "playwright.config.ts"),
                os.path.join(tree, "playwright.wgf-sdk-e2e.config.ts"))


def write_config(tree, target, engine, platforms=PLATFORMS):
    entries = [target] + [p for p in platforms if p != target]
    lines = ["game:", "  id: sdk-e2e", "  name: SDK E2E", "  version: 0.1.0",
             "engine:", f"  type: {engine}", "platforms:"]
    for platform in entries:
        role = "required" if platform == target else "optional"
        lines.append(f"  - {{ id: {platform}, profile: {platform}@1.0.0, role: {role} }}")
    lines += ["monetization:", "  ad_kinds: [rewarded, interstitial]", "  iap: false",
              "build:", "  command: pnpm build", "  output: dist",
              "verification:", "  smoke_test: true", "  performance_test: true",
              "  mobile_test: true", "publishing:", "  enabled: false", ""]
    with open(os.path.join(tree, "game.config.yaml"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


class _Inputs:
    def __init__(self, artifacts):
        self.artifacts = artifacts
        self.refs = {k: type("Ref", (), {"content_hash": v["provenance"]["content_hash"]})()
                     for k, v in artifacts.items()}
        self.missing = []

    def __contains__(self, artifact_type):
        return artifact_type in self.artifacts

    def load(self, artifact_type):
        return self.artifacts[artifact_type]


class _Logger:
    def info(self, message, **fields):
        print(f"  step: {message} {json.dumps(fields, default=str)}")

    debug = warning = error = info


class _Context:
    def __init__(self):
        self.config = load_config()
        self.environment = {}
        self.execution = 1
        self.project_id = "sdk-e2e"
        self.logger = _Logger()


class _Definition:
    def __init__(self, repo):
        self.id = self.type = "sdk"
        self.params = {"game_repo": repo}
        self.outputs = ["sdk-report"]


def run_step(tree):
    scaffold = {"provenance": {"artifact_id": "wgf:scaffold-record:sdk-e2e:20260923-01",
                               "content_hash": "sha256:" + "1" * 64},
                "repository": {"owner": "local", "name": "tree"},
                "game_config": {"path": "game.config.yaml"}}
    result = SdkStep(_Definition(tree)).execute(
        _Inputs({"game-design": DESIGN, "scaffold-record": scaffold}), _Context())
    report = result.artifacts[0].content if result.artifacts else None
    return result.outcome, result.message or result.error, report


def playwright(tree, work, platform, engine, expect="boot"):
    report = os.path.join(work, f"e2e-{platform}-{engine}-{expect}.json")
    done = sh(["pnpm", "exec", "playwright", "test", "-c", "playwright.wgf-sdk-e2e.config.ts"],
              tree, env={"WGF_E2E_PLATFORM": platform, "WGF_E2E_ENGINE": engine,
                         "WGF_E2E_EXPECT": expect, "WGF_E2E_REPORT": report}, check=False)
    tests = []
    try:
        with open(report, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = {}

    def walk(suite, prefix):
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                status = test.get("status")  # expected | unexpected | skipped | flaky
                tests.append({"title": f"{prefix}{spec['title']}",
                              "project": test.get("projectName"),
                              "status": {"expected": "passed", "unexpected": "failed"}
                              .get(status, status)})
        for child in suite.get("suites", []):
            walk(child, prefix)

    for suite in data.get("suites", []):
        walk(suite, "")
    return {"exit": done.returncode, "tests": tests,
            "output": (done.stdout + done.stderr)[-2000:] if done.returncode else ""}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--template", default=None)  # default: the pinned checkout
    # The pinned revision (workspace/config/template.lock.json), never a floating branch.
    parser.add_argument("--ref", default=None)
    parser.add_argument("--work", required=True)
    parser.add_argument("--platforms", default=",".join(PLATFORMS))
    parser.add_argument("--engines", default=",".join(ENGINES))
    args = parser.parse_args(argv)
    from wgflib import template
    if args.ref is None:
        args.ref = template.expected_commit()
    if args.template is None:
        args.template = template.checkout(args.ref)

    work = os.path.abspath(args.work)
    tree = os.path.join(work, "tree")
    os.makedirs(work, exist_ok=True)
    summary = {"template": os.path.abspath(args.template), "ref": args.ref, "checks": {},
               "builds": []}

    print(f"preparing {args.ref} ...")
    summary["commit"] = prepare(args.template, args.ref, tree)
    install_fixtures(tree)
    write_config(tree, "yandex", "pixijs")
    sh(["git", "init", "-q"], tree)
    sh(["git", "add", "-A"], tree)
    sh(["git", "-c", "user.name=wgf-e2e", "-c", "user.email=wgf-e2e@invalid", "commit", "-qm",
        "base"], tree)

    print("running the sdk step ...")
    outcome, message, report = run_step(tree)
    summary["step"] = {"outcome": outcome, "message": message}
    if report:
        with open(os.path.join(work, "sdk-report.json"), "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        summary["step"]["tests"] = report["integration"]["tests"]
        summary["step"]["platforms"] = {p["platform_id"]: p["status"]
                                        for p in report["platforms"]}

    for name, argv in (("template-tests", ["pnpm", "test"]),
                       ("typecheck", ["pnpm", "typecheck"]),
                       ("lint", ["pnpm", "exec", "eslint", "src", "tests/unit",
                                 "tests/integration"])):
        done = sh(argv, tree, check=False)
        summary["checks"][name] = {"exit": done.returncode,
                                   "tail": (done.stdout + done.stderr)[-1500:]}
        print(f"{name}: {'PASS' if done.returncode == 0 else 'FAIL'}")

    sdk = inspect_sdk(tree)
    wanted = [p for p in args.platforms.split(",") if p]
    for engine in [e for e in args.engines.split(",") if e]:
        for platform in wanted:
            configured = sdk.adapter(platform).implemented or platform in (
                load_config().section("sdk").get("adapter_substitutes") or {})
            expect = "boot" if configured else "boot-failure"
            write_config(tree, platform, engine)
            build = sh(["pnpm", "build"], tree, check=False)
            entry = {"platform": platform, "engine": engine, "expect": expect,
                     "build": build.returncode}
            if build.returncode == 0:
                entry["e2e"] = playwright(tree, work, platform, engine, expect)
            else:
                entry["build_tail"] = (build.stdout + build.stderr)[-1500:]
            passed = [t for t in entry.get("e2e", {}).get("tests", []) if t["status"] == "passed"]
            failed = [t for t in entry.get("e2e", {}).get("tests", []) if t["status"] == "failed"]
            print(f"{platform}/{engine} ({expect}): build "
                  f"{'PASS' if build.returncode == 0 else 'FAIL'}, e2e {len(passed)} passed, "
                  f"{len(failed)} failed")
            summary["builds"].append(entry)

    with open(os.path.join(work, "e2e-summary.json"), "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    # The step's outcome is recorded, not required: a ref without the conformance suite, or
    # a required platform with no adapter there, fails it by design. The integration must
    # pass, and so must everything the template itself checks.
    integration = summary["step"].get("tests", {}).get("status")
    if integration is None and "sdk:conformance" in (summary["step"]["message"] or ""):
        # A ref older than the template's conformance suite: the step stops at that phase,
        # and the integration's own suites are proven by the template's `pnpm test` instead.
        integration = "passed" if summary["checks"]["template-tests"]["exit"] == 0 else "failed"
        summary["step"]["note"] = ("no `pnpm sdk:conformance` on this ref; integration suites "
                                   "verified through `pnpm test`")
    ok = (integration == "passed"
          and all(c["exit"] == 0 for c in summary["checks"].values())
          and all(b["build"] == 0 and b["e2e"]["exit"] == 0 for b in summary["builds"]))
    print("e2e:", "PASS" if ok else "FAIL", "-", os.path.join(work, "e2e-summary.json"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
