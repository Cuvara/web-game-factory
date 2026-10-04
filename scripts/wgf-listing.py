#!/usr/bin/env python3
"""The store listing outside a workflow run: validate a package, or write the copy.

    python3 scripts/wgf-listing.py validate <package-dir> [--json]
    python3 scripts/wgf-listing.py copy --design game-design.json [--scaffold scaffold-record.json]
                                        [--sdk sdk-report.json] [--dist ../my-game/dist]
                                        [--sufficiency content-sufficiency-report.json]
                                        [--tier release|mvp] [--locale en --locale ru] [--json]
    python3 scripts/wgf-listing.py requirements [PLATFORM ...] [--json]

    validate       judge a package the store-listing step wrote (its listing.json names the
                   run directory it belongs to: the package is validated in place, exactly
                   as the listing-validation step judges it). Exit 0 PASS, 1 FAIL, 3 BLOCKED
                   (a person must act), 2 unusable input.
    copy           the Factory's own writer over a design (and the bundle's strings when
                   --dist is given), with the grounding check: what a run's listing would
                   say in each locale, to read before a run. --sufficiency holds every count
                   to that report's measurements (as the step does with the report of the
                   build it lists); --tier applies that tier's store bars.
    requirements   the requirement list each platform profile's `store_listing` block
                   yields, with what is UNKNOWN - the questions a person answers by reading
                   the portal.

Standard library only; run from the repository root. See docs/store-listing-module.md.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wgflib import paths  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

from wgf_listing import buildfacts, copywriter, facts as facts_module, grounding, platforms  # noqa: E402
from wgf_listing.settings import REFERENCE_PATH  # noqa: E402
from wgf_listing.validation import validate  # noqa: E402


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _print(payload, as_json):
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))


def cmd_validate(args):
    package = os.path.abspath(args.package)
    listing_path = os.path.join(package, "listing.json")
    if not os.path.isfile(listing_path):
        print(f"wgf-listing: {listing_path} not found: not a store listing package", file=sys.stderr)
        return 2
    listing = _load(listing_path)
    package_dir = (listing.get("package_dir") or "").replace("/", os.sep)
    # Every path in the listing is relative to the run directory the package sits in.
    run_dir = package[:-len(package_dir)].rstrip(os.sep) if package_dir and package.endswith(package_dir) \
        else os.path.dirname(package)
    reference = load_file(args.reference or REFERENCE_PATH)
    profiles = {}
    for rendition in listing.get("platforms") or []:
        profiles[rendition["platform_id"]] = platforms.load_profile(rendition["platform_id"])
    checks, per_platform = validate(listing, run_dir, reference, profiles, listing.get("facts"))
    failed = [c for c in checks if c["status"] == "FAIL" and c["required"]]
    unknown = [c["id"] for c in checks if c["status"] == "UNKNOWN"]
    actionable = any(c.get("fix") in ("recapture", "rerender", "rewrite") for c in failed)
    verdict = "PASS" if not failed else ("FAIL" if actionable else "BLOCKED")
    _print({"verdict": verdict, "checks": checks, "platforms": per_platform, "unknown": unknown}, args.json)
    if not args.json:
        print(f"{verdict}: {len(checks)} checks, {len(failed)} failed, {len(unknown)} unknown")
        for check in checks:
            if check["status"] != "PASS":
                print(f"  {check['status']:8} {check['id']}: {check['summary']}")
        for entry in per_platform:
            print(f"  platform {entry['platform_id']}: {entry['status']}"
                  + (f", unknown: {', '.join(entry['unknown'])}" if entry["unknown"] else ""))
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 3}[verdict]


def cmd_copy(args):
    design = _load(args.design)
    scaffold = _load(args.scaffold) if args.scaffold else None
    sdk = _load(args.sdk) if args.sdk else None
    strings = facts_module.read_strings(args.dist) if args.dist else {}
    runtime = facts_module.read_runtime_assets(args.dist) if args.dist else None
    game_config = None
    if args.dist:
        config_path = os.path.join(os.path.dirname(os.path.abspath(args.dist)), "game.config.yaml")
        if os.path.isfile(config_path):
            game_config = load_file(config_path)
    facts = facts_module.extract(design, sdk_report=sdk, scaffold=scaffold, strings=strings,
                                 runtime_assets=runtime, game_config=game_config)
    reference = load_file(args.reference or REFERENCE_PATH)
    facts["quality"] = {"tier": args.tier, "where": "--tier", "bars": buildfacts.store_bars(args.tier)}
    if args.sufficiency:
        report = _load(args.sufficiency)
        measured = buildfacts.measured_counts(report, design, reference, commits=[report.get("commit")])
        if measured is not None:
            facts["measured"] = measured
    locales = args.locale or ["en"] + [l for l in strings if l != "en"]
    copies, writer = copywriter.write_copy(facts, locales, reference, tier=args.tier,
                                           writer_settings={"kind": "template"})
    problems = {locale: grounding.check(text, facts, reference.get("claims") or [], locale=locale,
                                        counts=reference.get("counts"))
                for locale, text in copies.items() if text is not None}
    _print({"facts": facts, "copy": copies, "writer": writer, "grounding": problems}, args.json)
    if not args.json:
        for locale, text in copies.items():
            print(f"== {locale}")
            if text is None:
                print("  (no grounded copy can be written in this locale without an agent writer)")
                continue
            print(f"  title: {text['title']}")
            print(f"  short: {text['short_description']}")
            print(f"  long:  {text['long_description'][:400]}" + ("..." if len(text["long_description"]) > 400 else ""))
            for bullet in text["features"]:
                print(f"  - {bullet['text']}  [{bullet['source']}]")
            print(f"  tags: {', '.join(text['tags'])}; categories: {', '.join(text['categories'])}")
            for problem in problems.get(locale) or []:
                print(f"  ! {problem['severity']}: {problem['message']}")
    return 0 if not any(p["severity"] == "error" for ps in problems.values() for p in ps) else 1


def cmd_requirements(args):
    reference = load_file(args.reference or REFERENCE_PATH)
    ids = args.platform or sorted(os.path.splitext(n)[0] for n in os.listdir(paths.PLATFORMS)
                                   if n.endswith(".yaml"))
    out = {}
    for pid in ids:
        profile = platforms.load_profile(pid)
        out[pid] = {"spec_status": platforms.spec_status(profile),
                    "requirements": platforms.requirements(profile, reference)}
    _print(out, args.json)
    if not args.json:
        for pid, entry in out.items():
            unknown = [r["id"] for r in entry["requirements"] if not r.get("known")]
            print(f"{pid} ({entry['spec_status']}): {len(entry['requirements'])} requirements, "
                  f"{len(unknown)} unknown" + (": " + ", ".join(unknown) if unknown else ""))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="The store listing outside a run.")
    parser.add_argument("--reference", help="core/reference/store-listing.yaml override")
    sub = parser.add_subparsers(dest="command", required=True)
    validate_p = sub.add_parser("validate", help="judge a store listing package")
    validate_p.add_argument("package")
    validate_p.add_argument("--json", action="store_true")
    validate_p.set_defaults(handler=cmd_validate)
    copy_p = sub.add_parser("copy", help="write the store copy from a design")
    copy_p.add_argument("--design", required=True)
    copy_p.add_argument("--scaffold")
    copy_p.add_argument("--sdk")
    copy_p.add_argument("--dist", help="the built bundle, for its locale strings and runtime assets")
    copy_p.add_argument("--sufficiency", help="a content-sufficiency-report: the counts the copy may state")
    copy_p.add_argument("--tier", help="the run's quality tier (release, mvp): its store bars apply")
    copy_p.add_argument("--locale", action="append")
    copy_p.add_argument("--json", action="store_true")
    copy_p.set_defaults(handler=cmd_copy)
    req_p = sub.add_parser("requirements", help="what each platform's listing requires")
    req_p.add_argument("platform", nargs="*")
    req_p.add_argument("--json", action="store_true")
    req_p.set_defaults(handler=cmd_requirements)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
