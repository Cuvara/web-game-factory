#!/usr/bin/env python3
"""Publication outside a workflow run: what a person does around the publish group.

    python3 scripts/wgf-publish.py profiles                      every publication profile:
                                                                 method, terms, credential kind
    python3 scripts/wgf-publish.py readiness --manifest FILE [--publication FILE] [--platform ID]
                                                                 the publication guards on a
                                                                 release-manifest (and a record)
    python3 scripts/wgf-publish.py registry show <title> [--json]
                                                                 the portal games known for a
                                                                 title (portals.json)
    python3 scripts/wgf-publish.py registry associate <title> <platform> <external-id> --note TEXT
                                                                 a person links a portal game
                                                                 they created by hand
    python3 scripts/wgf-publish.py observe <platform> --checkout DIR [--out DIR]
            [--login-timeout-s 900] [--max-minutes 30] [--authenticated-url REGEX]
                                                                 a person logs in to the real
                                                                 console in a fresh browser; what
                                                                 the console shows is recorded,
                                                                 read-only, nothing of the session
                                                                 kept (wgf_publish/observe.py)
    python3 scripts/wgf-publish.py observe-summary DIR          an observation's summary and its
                                                                 field inventory as JSON
    python3 scripts/wgf-publish.py drift-review <run-id|DIR> [--platform ID]
            [--apply --profile-out FILE]                         the bounded adaptive mode's
                                                                 drift.json proposals; --apply
                                                                 writes a NEW profile file for a
                                                                 person to review and commit -
                                                                 never the shipped profile

No session is ever captured or saved (profile 2.1.0, credential `human-login`): the publish
step's console executor opens a headed browser and a person logs in there, live, each visit;
the session ends with the window. There is no `capture` command.

Standard library only; run from the repository root. See docs/publish-module.md.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wgflib import paths, publication  # noqa: E402
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
                     (submission.get("credential") or {}).get("kind") or "-",
                     f"{profile.get('version')} ({profile.get('status')})"))
    if args.json:
        print(json.dumps([dict(zip(("platform", "method", "automation_terms", "credential",
                                    "version"), row)) for row in rows], indent=2))
        return 0
    width = max(len(r[0]) for r in rows) if rows else 8
    print(f"{'platform':<{width}}  method   terms       credential                           version")
    for row in rows:
        print(f"{row[0]:<{width}}  {row[1]:<8} {row[2]:<11} {row[3]:<36} {row[4]}")
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
    if args.platform:
        # A target is not a package: a release that targets a platform without packaging
        # its build cannot be uploaded there (a new release candidate must be built).
        pid = args.platform
        targeted = pid in {str(t.get("id")) for t in manifest.get("target_platforms") or []}
        package = next((p for p in manifest.get("packages") or []
                        if str(p.get("platform_id")) == pid), None)
        if package and package.get("checksum"):
            results["platform_packaged"] = publication.GuardResult(
                True, f"{pid}: {package.get('filename')} {package['checksum'][:19]}...")
        else:
            packaged = ", ".join(str(p.get("platform_id")) for p in manifest.get("packages") or [])
            results["platform_packaged"] = publication.GuardResult(
                False, f"{pid}: {'targeted but ' if targeted else 'not targeted and '}not packaged "
                       f"in release {manifest.get('release_id')} (packages: {packaged or 'none'}); "
                       f"a {pid} build is a new release candidate with its own G5 and G6")
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


def cmd_registry_show(args):
    from wgf_publish import registry
    try:
        reg = registry.load(args.title)
    except registry.RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(reg.document, indent=2, ensure_ascii=False))
        return 0
    print(f"{reg.title_id}: {reg.path}")
    if not reg.platforms():
        print("  no portal game recorded (every platform NOT_CREATED)")
    for platform in reg.platforms():
        entry = reg.get(platform)
        last = entry["history"][-1]
        print(f"  {platform:<16} {entry['status']:<15} id={entry.get('external_game_id') or '-'}"
              f"  {entry.get('association') or '-'}  release={entry.get('release_id') or '-'}"
              f"  last change {last['at']} by {last['by']}")
    return 0


def cmd_registry_associate(args):
    from wgf_publish import registry
    if not os.path.isfile(os.path.join(paths.PLATFORMS, f"{args.platform}.yaml")):
        print(f"error: no platform profile {args.platform!r} (core/reference/platforms/)",
              file=sys.stderr)
        return 2
    try:
        reg = registry.load(args.title)
        entry = reg.associate(args.platform, args.external_id, by="human", note=args.note)
    except registry.RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{args.title} {args.platform}: {entry['external_game_id']} associated "
          f"({entry['status']}); {reg.path}")
def cmd_observe(args):
    from wgf_publish import observe
    try:
        profile = publication.load_publication_profile(args.platform, args.extra or ())
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return observe.EXIT_USAGE
    if args.url or args.allow_origin:
        # Discovery of a console the profile does not describe yet (or describes wrongly): the
        # person names the console and the origins to record; the profile is untouched.
        profile = dict(profile or {}, id=args.platform)
        submission = dict(profile.get("submission") or {})
        console = dict(submission.get("console") or {})
        if args.url:
            console["url"] = args.url
        if args.allow_origin:
            console["allowed_origins"] = list(args.allow_origin)
        submission["console"] = console
        profile["submission"] = submission
    if profile is None:
        print(f"error: no publication profile for {args.platform!r} "
              f"(core/reference/publication/); give --url and --allow-origin", file=sys.stderr)
        return observe.EXIT_USAGE
    checkout = os.path.abspath(os.path.expanduser(args.checkout))
    out = os.path.abspath(os.path.expanduser(args.out)) if args.out else         observe.default_out(args.platform)
    try:
        code, state = observe.observe(args.platform, profile, checkout, out,
                                      authenticated_url=args.authenticated_url,
                                      login_timeout_s=args.login_timeout_s,
                                      max_minutes=args.max_minutes)
    except (observe.ObserveError, re.error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return observe.EXIT_USAGE
    print(f"{state.get('status', 'NO STATE')}: {len(observe.load_pages(out))} page(s) recorded "
          f"in {out} (index.json, summary.md)")
    return code


def cmd_observe_summary(args):
    from wgf_publish import observe
    out = os.path.abspath(os.path.expanduser(args.dir))
    if not os.path.isfile(os.path.join(out, "index.json")):
        print(f"error: {out} holds no observation (no index.json)", file=sys.stderr)
        return observe.EXIT_USAGE
    state = {}
    if os.path.isfile(os.path.join(out, "state.json")):
        with open(os.path.join(out, "state.json"), encoding="utf-8") as handle:
            state = json.load(handle)
    pages = [observe.sanitize_page(page) for page in observe.load_pages(out)]
    print(observe.summary_markdown(observe.sanitize_page(state), pages))
    print(json.dumps(observe.field_inventory(pages), indent=2, ensure_ascii=False))
    return 0


def _run_root(target):
    """A directory as given, else the run's directory in the Factory's run store."""
    if os.path.isdir(target):
        return os.path.abspath(target)
    from wgflib.workflow.config import load_config
    return os.path.join(load_config().storage_directory(), "workflows", target)


def cmd_drift_review(args):
    from wgf_publish import adaptive
    root = _run_root(args.target)
    files = adaptive.find_drift_files(root)
    if not files:
        print(f"no drift.json under {root}: no adaptive exchange was recorded")
        return 0
    by_portal = {}
    for path in files:
        document = adaptive.load_drift(path)
        portal = (document.get("profile") or {}).get("id") or document.get("portal")
        for entry in document.get("entries") or []:
            by_portal.setdefault(portal, []).append(entry)
            print(f"== {os.path.relpath(path, root)}  {portal}  intent {entry.get('intent')}"
                  + (f" ({entry.get('locale')})" if entry.get("locale") else "")
                  + f"  outcome {entry.get('outcome')}")
            print(f"   why: {entry.get('why')}")
            print(f"   proposal: {json.dumps(entry.get('proposal'), ensure_ascii=False)}")
            failed = [c.get("check") for c in entry.get("checks") or [] if not c.get("ok")]
            if failed:
                print(f"   refused by: {', '.join(failed)}")
            if entry.get("proposed_patch"):
                print("   proposed profile change (review; never applied by the Factory):")
                for line in entry["proposed_patch"].splitlines():
                    print(f"     {line}")
    if not args.apply:
        return 0
    if not args.profile_out:
        print("error: --apply needs --profile-out FILE (a new file; the shipped profile is "
              "never edited)", file=sys.stderr)
        return 2
    portals = [p for p in by_portal if p]
    platform = args.platform or (portals[0] if len(portals) == 1 else None)
    if platform is None or platform not in by_portal:
        print(f"error: name the platform (--platform): drift recorded for {', '.join(portals)}",
              file=sys.stderr)
        return 2
    source = publication.publication_profiles(args.extra or ()).get(platform)
    if source is None:
        print(f"error: no publication profile for {platform!r}", file=sys.stderr)
        return 2
    out = os.path.abspath(os.path.expanduser(args.profile_out))
    shipped = {os.path.realpath(p) for p in publication.publication_profiles(args.extra or ()).values()}
    if os.path.exists(out) or os.path.realpath(out) in shipped:
        print(f"error: {out} exists; --profile-out writes a NEW file, never over a profile",
              file=sys.stderr)
        return 2
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    profile = publication.load_publication_profile(platform, args.extra or ())
    version = adaptive.bump_patch(profile.get("version"))
    patched, applied, skipped = adaptive.patched_profile_text(text, by_portal[platform], version)
    for problem in skipped:
        print(f"skipped: {problem}")
    if not applied:
        print("nothing to apply: no adaptive resolution held its post-condition")
        return 1
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(patched)
    print(f"wrote {out}: {platform} {profile.get('version')} -> {version}, the locator that "
          f"worked put first in {', '.join(applied)}. A person reviews it, then commits it as "
          f"the profile's new version.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--extra", action="append", help="another publication profiles directory")
    sub = parser.add_subparsers(dest="command", required=True)
    profiles = sub.add_parser("profiles")
    profiles.add_argument("--json", action="store_true")
    profiles.set_defaults(run=cmd_profiles)
    readiness = sub.add_parser("readiness")
    readiness.add_argument("--manifest", required=True)
    readiness.add_argument("--publication")
    readiness.add_argument("--platform", help="also require this platform's package in the manifest")
    readiness.set_defaults(run=cmd_readiness)
    registry_cmd = sub.add_parser("registry")
    registry_sub = registry_cmd.add_subparsers(dest="registry_command", required=True)
    show = registry_sub.add_parser("show")
    show.add_argument("title")
    show.add_argument("--json", action="store_true")
    show.set_defaults(run=cmd_registry_show)
    associate = registry_sub.add_parser("associate")
    associate.add_argument("title")
    associate.add_argument("platform")
    associate.add_argument("external_id")
    associate.add_argument("--note", required=True)
    associate.set_defaults(run=cmd_registry_associate)
    observing = sub.add_parser("observe", help="record a real console while a person uses it")
    observing.add_argument("platform")
    observing.add_argument("--checkout", required=True,
                           help="the game checkout whose Playwright and Chromium are used")
    observing.add_argument("--out", help="default <project>/.factory/observations/<platform>/"
                                         "<UTC timestamp>/")
    observing.add_argument("--login-timeout-s", type=int, default=900)
    observing.add_argument("--max-minutes", type=float, default=30)
    observing.add_argument("--url", help="the console url to open (default the profile's)")
    observing.add_argument("--allow-origin", action="append", default=[],
                           help="an origin whose pages are recorded (repeatable; default the "
                                "profile's allowed_origins)")
    observing.add_argument("--authenticated-url",
                           help="a regex the console's url (origin + path) matches once logged "
                                "in; default the profile's session.authenticated_url")
    observing.set_defaults(run=cmd_observe)
    summary = sub.add_parser("observe-summary")
    summary.add_argument("dir")
    summary.set_defaults(run=cmd_observe_summary)
    review = sub.add_parser("drift-review", help="the adaptive mode's proposed profile changes")
    review.add_argument("target", metavar="run", help="a run id, or a run or visit directory")
    review.add_argument("--platform", help="the portal whose proposals --apply writes")
    review.add_argument("--apply", action="store_true",
                        help="write the proposals into a NEW profile file (--profile-out)")
    review.add_argument("--profile-out", help="the new profile file --apply writes")
    review.set_defaults(run=cmd_drift_review)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
