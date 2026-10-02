#!/usr/bin/env python3
"""Publication outside a workflow run: what a person does around the publish group.

    python3 scripts/wgf-publish.py profiles                      every publication profile:
                                                                 method, terms, credential name
    python3 scripts/wgf-publish.py capture <platform> --out PATH [--checkout DIR]
                                                                 log into the portal once, in a
                                                                 headed browser; the Playwright
                                                                 storage state is saved to PATH
    python3 scripts/wgf-publish.py readiness --manifest FILE [--publication FILE]
                                                                 the publication guards on a
                                                                 release-manifest (and a record)

`capture` is how a console platform's credential comes to exist: the publication profile
names the variable (`submission.credential.env`) that must hold PATH, and the installation
lists that name in `factory.publish.env_passthrough`. The browser is the game checkout's
own Playwright (`--checkout`, default the current directory), run as `playwright open
--save-storage PATH <console url>`: a person logs in, solves whatever the portal asks, and
closes the window; nothing here types a password or answers a challenge. The file holds a
live session: keep it where the installation keeps secrets, never in a repository, and
capture it again when the portal expires it (the publish step then says AUTH_REQUIRED).

Standard library only; run from the repository root. See docs/publish-module.md.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wgflib import procs, publication, redact  # noqa: E402
from wgflib.workspace import WorkspaceError, load_platform_profile  # noqa: E402


def cmd_profiles(args):
    rows = []
    for pid, path in sorted(publication.publication_profiles(args.extra or ()).items()):
        try:
            profile = publication.load_publication_profile(pid, args.extra or ())
        except ValueError as exc:
            rows.append((pid, "invalid", str(exc), "", ""))
            continue
        submission = profile.get("submission") or {}
        rows.append((pid, submission.get("method", "-"), submission.get("automation_terms", "-"),
                     (submission.get("credential") or {}).get("env") or "-",
                     f"{profile.get('version')} ({profile.get('status')})"))
    if args.json:
        print(json.dumps([dict(zip(("platform", "method", "automation_terms", "credential_env",
                                    "version"), row)) for row in rows], indent=2))
        return 0
    width = max(len(r[0]) for r in rows) if rows else 8
    print(f"{'platform':<{width}}  method   terms       credential                           version")
    for row in rows:
        print(f"{row[0]:<{width}}  {row[1]:<8} {row[2]:<11} {row[3]:<36} {row[4]}")
    return 0


def cmd_capture(args):
    try:
        profile = publication.load_publication_profile(args.platform, args.extra or ())
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if profile is None:
        print(f"error: no publication profile for {args.platform!r} "
              f"(core/reference/publication/)", file=sys.stderr)
        return 2
    submission = profile.get("submission") or {}
    console = submission.get("console") or {}
    url = args.url or console.get("url")
    if submission.get("method") != "console" or not url:
        print(f"error: {args.platform} is published by {submission.get('method')}, not through "
              f"a console; nothing to capture", file=sys.stderr)
        return 2
    credential = submission.get("credential") or {}
    out = os.path.abspath(os.path.expanduser(args.out))
    if os.path.exists(out) and not args.force:
        print(f"error: {out} exists; --force to replace it", file=sys.stderr)
        return 2
    checkout = os.path.abspath(args.checkout or os.getcwd())
    if not os.path.isfile(os.path.join(checkout, "package.json")):
        print(f"error: {checkout} is not a game checkout (no package.json); give --checkout",
              file=sys.stderr)
        return 2
    print(f"Opening {url} in a headed browser. Log in, finish every challenge the portal asks, "
          f"then close the browser window. The session is saved to {out}; set "
          f"{credential.get('env') or '<the profile names no variable>'} to that path and list "
          f"it in factory.publish.env_passthrough.")
    done = procs.run(["pnpm", "exec", "playwright", "open", f"--save-storage={out}", url],
                     cwd=checkout, timeout=args.timeout, stderr_to_stdout=True)
    if not done.ok:
        print(f"error: playwright open did not succeed ({done.status}): "
              f"{redact.scrub_text(done.tail(5))}", file=sys.stderr)
        return 1
    if not os.path.isfile(out):
        print(f"error: no storage state was written to {out}", file=sys.stderr)
        return 1
    try:
        with open(out, encoding="utf-8") as handle:
            state = json.load(handle)
        cookies = len(state.get("cookies") or [])
    except ValueError:
        print(f"error: {out} is not JSON", file=sys.stderr)
        return 1
    try:
        os.chmod(out, 0o600)
    except OSError:
        pass
    print(f"saved {out}: {cookies} cookie(s). Never commit it; never print it.")
    return 0


def cmd_readiness(args):
    with open(args.manifest, encoding="utf-8") as handle:
        manifest = json.load(handle)
    record = None
    if args.publication:
        with open(args.publication, encoding="utf-8") as handle:
            record = json.load(handle)
    profiles = {}
    for target in manifest.get("target_platforms") or []:
        pid = str(target.get("id"))
        try:
            profiles[pid] = load_platform_profile(pid)
        except WorkspaceError:
            profiles[pid] = None
    results = {"candidate_frozen": publication.candidate_frozen(manifest),
               "store_metadata_complete": publication.store_metadata_complete(manifest, profiles)}
    if record is not None:
        for name in publication.PLATFORM_GUARDS:
            for entry in record.get("guards") or []:
                if entry.get("guard") == name:
                    value = {"GREEN": True, "RED": False}.get(entry.get("verdict"))
                    results[name] = publication.GuardResult(value, entry.get("reason", ""))
        results["all_targeted_validated"] = publication.all_targeted_validated(manifest, [record])
        results["required_all_live"] = publication.required_all_live(manifest, [record])
        results["none_permanently_rejected"] = publication.none_permanently_rejected(manifest,
                                                                                    [record])
    width = max(len(n) for n in results)
    for name, result in results.items():
        print(f"{name:<{width}}  {result.symbol:<8} {result.reason}")
    print(f"readiness: {publication.readiness(results)}")
    return 0 if all(r.value for r in results.values()) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--extra", action="append", help="another publication profiles directory")
    sub = parser.add_subparsers(dest="command", required=True)
    profiles = sub.add_parser("profiles")
    profiles.add_argument("--json", action="store_true")
    profiles.set_defaults(run=cmd_profiles)
    capture = sub.add_parser("capture")
    capture.add_argument("platform")
    capture.add_argument("--out", required=True)
    capture.add_argument("--checkout")
    capture.add_argument("--url")
    capture.add_argument("--force", action="store_true")
    capture.add_argument("--timeout", type=int, default=1800)
    capture.set_defaults(run=cmd_capture)
    readiness = sub.add_parser("readiness")
    readiness.add_argument("--manifest", required=True)
    readiness.add_argument("--publication")
    readiness.set_defaults(run=cmd_readiness)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
