#!/usr/bin/env python3
"""The pinned web-game-template: where it is, and whether anything has drifted from it.

    python3 scripts/wgf-template.py            # the pin, and the sibling checkout against it
    python3 scripts/wgf-template.py --path     # obtain a checkout of the pin; print its path
    python3 scripts/wgf-template.py --install  # ... and install its node dependencies
    python3 scripts/wgf-template.py --check    # exit 1 unless a checkout of the pin is obtainable

Standard library only; run from the repository root. See scripts/wgflib/template.py.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wgflib import template  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", action="store_true", help="obtain the pinned checkout")
    parser.add_argument("--install", action="store_true", help="also install node deps")
    parser.add_argument("--check", action="store_true", help="fail unless obtainable")
    args = parser.parse_args(argv)
    try:
        lock = template.load_lock()
    except template.TemplateError as exc:
        print(f"wgf-template: {exc}", file=sys.stderr)
        return 1
    if args.path or args.install or args.check:
        try:
            path = template.checkout()
            if args.install:
                template.ensure_dependencies(path)
        except template.TemplateError as exc:
            print(f"wgf-template: {exc}", file=sys.stderr)
            return 1
        print(path)
        return 0
    report = {"lock": {k: lock[k] for k in ("repository", "commit", "ref", "validated_on")},
              "expected": template.expected_commit(lock), "sibling": template.drift(lock)}
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
