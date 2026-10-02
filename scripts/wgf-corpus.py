#!/usr/bin/env python3
"""The research corpus from the command line: check teardown records, start one, list codes.

    python3 scripts/wgf-corpus.py validate [CORPUS] [--json]
    python3 scripts/wgf-corpus.py template GAME_ID --name NAME [--platform ID] [--url URL]
    python3 scripts/wgf-corpus.py facets [FACET]

validate  Reads CORPUS/games/*.json (default workspace/research) the way the research step
          does: every record against core/artifacts/shared/game-record.schema.json, every
          coding against core/reference/research-vocabulary.yaml. Reports refused codings,
          sessions without a played viewport, records marked fixture, and how many games
          are coded on each facet. A record the step would refuse is an error here.
template  Prints a game-record skeleton for a teardown about to be played: one session to
          fill in, no codings. Nothing in it is an observation until a person or an agent
          has played the game and written what they saw (core/craft/competitive-teardown.md).
facets    The facets a game is coded on, or the allowed values of one.

Exit status: 0 clean; 1 problems found; 2 the command could not run. Standard library only.
"""

import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wgf_discovery.corpus import load_records  # noqa: E402
from wgf_discovery.evidence import EvidenceError  # noqa: E402
from wgf_discovery.vocabulary import Vocabulary, VocabularyError  # noqa: E402
from wgflib import paths  # noqa: E402


def validate(args):
    corpus = args.corpus or os.path.join(paths.PROJECT, "workspace", "research")
    games = os.path.join(corpus, "games")
    try:
        vocabulary = Vocabulary()
        records = load_records(games)
    except (EvidenceError, VocabularyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    problems, fixtures, coded = [], [], Counter()
    for name, record, _digest in records:
        if record.get("fixture"):
            fixtures.append(record["id"])
        if record["vocabulary_version"].split(".")[0] != vocabulary.version.split(".")[0]:
            problems.append(f"{name}: coded against vocabulary {record['vocabulary_version']}, "
                            f"not {vocabulary.version}")
        sessions = {s["id"] for s in record["sessions"]}
        seen = set()
        for index, item in enumerate(record["observations"]):
            if item["session"] not in sessions:
                problems.append(f"{name}: observation {index} names unknown session "
                                f"{item['session']}")
            reason = vocabulary.check(item["facet"], item["value"])
            if reason:
                problems.append(f"{name}: observation {index}: {reason}")
            else:
                seen.add(item["facet"])
        coded.update(seen)
    summary = {"corpus": corpus, "records": len(records), "fixture_records": fixtures,
               "problems": problems,
               "coded": {facet: coded.get(facet, 0) for facet in sorted(vocabulary.facets)}}
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"{len(records)} game record(s) in {games}")
        if fixtures:
            print(f"fixture (test data, never evidence): {', '.join(fixtures)}")
        for facet, count in summary["coded"].items():
            if count:
                print(f"  {facet:32} {count} game(s)")
        for problem in problems:
            print(f"problem: {problem}")
        print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def template(args):
    slug = args.game_id[len("game-"):] if args.game_id.startswith("game-") else args.game_id
    record = {
        "id": f"game-{slug}",
        "name": args.name,
        "listing_names": [args.name],
        "vocabulary_version": Vocabulary().version,
        "sessions": [{
            "id": f"ts-{slug}-a",
            "source_uri": args.url or "<the game's page URL>",
            "source_kind": "competitor-teardown",
            "observed_at": "<ISO 8601 time the session started>",
            "method": "played",
            "observer": "<role or person who played>",
            "platform": args.platform or "<platform id>",
            "viewport": "<e.g. 390x844 phone, throttled 4G>",
            "runs": 2,
            "capture_uri": "<recording or screenshots the excerpts can be checked against>",
            "note": "<what was done, plainly enough to repeat>",
        }],
        "observations": [],
        "notes": [],
    }
    print(json.dumps(record, indent=2, ensure_ascii=False))
    return 0


def facets(args):
    vocabulary = Vocabulary()
    if args.facet:
        spec = vocabulary.facet(args.facet)
        if spec is None:
            print(f"error: no facet {args.facet!r}", file=sys.stderr)
            return 2
        if spec["kind"] == "number":
            print(f"{spec['id']}: a number in {spec['unit']}")
            return 0
        for value, entry in vocabulary.values(args.facet).items():
            parent = f"  (under {entry['parent']})" if entry.get("parent") else ""
            print(f"{value:24} {entry['label']}{parent}")
        return 0
    for spec in vocabulary.facets.values():
        kind = f"number ({spec['unit']})" if spec["kind"] == "number" else \
            f"{spec['kind']} of {spec['values']}"
        print(f"{spec['id']:32} {kind:30} {spec['label']}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="wgf-corpus", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("validate")
    p.add_argument("corpus", nargs="?")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=validate)
    p = sub.add_parser("template")
    p.add_argument("game_id")
    p.add_argument("--name", required=True)
    p.add_argument("--platform")
    p.add_argument("--url")
    p.set_defaults(func=template)
    p = sub.add_parser("facets")
    p.add_argument("facet", nargs="?")
    p.set_defaults(func=facets)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (VocabularyError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
