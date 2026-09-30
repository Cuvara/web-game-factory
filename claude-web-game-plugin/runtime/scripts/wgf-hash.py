#!/usr/bin/env python3
"""Compute, audit and repair artifact content hashes and the pins between them.

Every gate pins its subject by `provenance.content_hash`, and every artifact pins what it
was derived from by `provenance.inputs[].content_hash`. Together those are the Factory's
staleness detection: a decision built on a market read that has since been superseded is
supposed to be *detectable* rather than invisible. That only works if the digests reproduce.

Two failures are worth catching and neither is visible by reading:

    stale hash   an artifact's recorded digest does not match its content - it was edited
                 after something was decided on it, or was never a digest to begin with
    stale pin    an input pins a digest the referenced artifact no longer has

Artifacts form a DAG, so repairing them is not a per-file operation: re-pinning an input
changes the dependent's own digest, which changes what its own dependents must pin. `--fix`
therefore relinks and rehashes the whole tree to a fixed point.

The algorithm is specified on `#/$defs/hash` in core/artifacts/shared/provenance.schema.json
and implemented in wgflib/hashing.py. The game-repo side implements the same rule in
web-game-template/scripts/_shared.mjs; scripts/tests/test_hashing.py checks they agree.

Usage, from the web-game-factory repository root:

    python scripts/wgf-hash.py --check workspace/       # audit; exit 1 on any problem
    python scripts/wgf-hash.py --compute <file.json>    # print one digest, change nothing
    python scripts/wgf-hash.py --fix workspace/         # relink and rehash in place

`--fix` rewrites hash strings only, leaving the rest of each file byte-for-byte alone. These
files are hand-readable and their formatting is not this script's to normalize.

Artifacts with no `provenance` block are skipped rather than failed: `claim` is deliberately
one of them, being identified by id and made immutable by append-only discipline instead.

A pin to an artifact that is not in the tree being scanned is reported as external, not as
an error - release artifacts live in the game repository and are not visible from here.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wgflib.hashing import CanonicalizationError, content_hash  # noqa: E402

MAX_PASSES = 50


def pinned_refs(value):
    """Every pinned reference to another artifact, anywhere in this one.

    A pin is any object carrying both `artifact_id` and `content_hash` - the shape of
    `provenance.schema.json#/$defs/artifactRef`. Walking for the shape rather than visiting
    known field names is deliberate: `provenance.inputs[]` is not the only place one
    appears. A decision-record pins its subject the same way, outside provenance entirely,
    and that pin is the whole point of the artifact.

    `evaluation.scoring_model` is correctly not matched. It records `file_hash` of a file in
    core/, which is not an artifact and has no artifact_id.
    """
    if isinstance(value, dict):
        if "artifact_id" in value and "content_hash" in value:
            yield value
        for item in value.values():
            yield from pinned_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from pinned_refs(item)


class Artifact:
    """One hashable file, its parsed content, and the text it was read from."""

    def __init__(self, path, text, data):
        self.path = path
        self.display = path.replace(os.sep, "/")
        self.text = text
        self.data = data
        self.provenance = data["provenance"]
        self.artifact_id = self.provenance.get("artifact_id")
        # Captured before anything is relinked: these are the strings present in `text`, and
        # therefore the only ones a rewrite can find to replace.
        self.original_own = self.provenance.get("content_hash")
        # The provenance object itself carries both keys, but it is the artifact's own
        # identity rather than a pin to another artifact - so walk its inputs and the body,
        # never the provenance object as a whole.
        body = {key: item for key, item in data.items() if key != "provenance"}
        self.original_pins = [
            (ref, ref.get("content_hash"))
            for ref in list(pinned_refs(self.provenance.get("inputs") or []))
            + list(pinned_refs(body))
        ]

    def refs(self):
        return [ref for ref, _original in self.original_pins]

    def digest(self):
        return content_hash(self.data)


def json_files(path):
    if os.path.isfile(path):
        return [path]
    found = []
    for root, _dirs, files in os.walk(path):
        for name in sorted(files):
            if name.endswith(".json"):
                found.append(os.path.join(root, name))
    return sorted(found)


def load(paths):
    """Return (artifacts, skipped, broken)."""
    artifacts, skipped, broken = [], [], []
    for path in paths:
        try:
            with open(path, encoding="utf-8", newline="") as handle:
                text = handle.read()
            data = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            broken.append((path.replace(os.sep, "/"), f"unreadable as JSON: {exc}"))
            continue
        if isinstance(data, dict) and isinstance(data.get("provenance"), dict):
            artifacts.append(Artifact(path, text, data))
        else:
            skipped.append(path)
    return artifacts, skipped, broken


def index_by_id(artifacts):
    index = {}
    collisions = []
    for artifact in artifacts:
        if artifact.artifact_id is None:
            continue
        if artifact.artifact_id in index:
            collisions.append((artifact.artifact_id, index[artifact.artifact_id].display,
                               artifact.display))
            continue
        index[artifact.artifact_id] = artifact
    return index, collisions


def audit(artifacts, index):
    """Report every stale hash and stale pin. Returns a list of problem strings."""
    problems = []
    external = 0

    for artifact in artifacts:
        try:
            computed = artifact.digest()
        except CanonicalizationError as exc:
            problems.append(f"BROKEN  {artifact.display}: {exc}")
            continue

        recorded = artifact.provenance.get("content_hash")
        if recorded != computed:
            problems.append(
                f"HASH    {artifact.display}\n"
                f"          recorded {recorded}\n"
                f"          computed {computed}"
            )

        for entry in artifact.refs():
            target = index.get(entry.get("artifact_id"))
            if target is None:
                external += 1
                continue
            try:
                expected = target.digest()
            except CanonicalizationError:
                continue  # already reported against the target itself
            if entry.get("content_hash") != expected:
                problems.append(
                    f"PIN     {artifact.display} -> {entry.get('artifact_id')}\n"
                    f"          pinned   {entry.get('content_hash')}\n"
                    f"          actual   {expected}"
                )

    return problems, external


def reconcile(artifacts, index):
    """Relink pins and recompute digests until nothing changes.

    Iterating to a fixed point rather than sorting topologically: the graph is small, a
    fixed point is the same answer, and it does not fall over on a cycle - it stops and
    says so, which a topological sort would have to do anyway.
    """
    for _ in range(MAX_PASSES):
        changed = False
        for artifact in artifacts:
            for entry in artifact.refs():
                target = index.get(entry.get("artifact_id"))
                if target is None:
                    continue
                expected = target.digest()
                if entry.get("content_hash") != expected:
                    entry["content_hash"] = expected
                    changed = True
            computed = artifact.digest()
            if artifact.provenance.get("content_hash") != computed:
                artifact.provenance["content_hash"] = computed
                changed = True
        if not changed:
            return True
    return False


def rewrite(artifact):
    """Write the artifact's new hash strings over its old ones, changing nothing else.

    Replacement is a single regex pass so that a new value can never be re-matched as if it
    were an old one. A digest string that must map to two different values would mean two
    artifacts shared a digest, so an ambiguous mapping is refused rather than guessed at.
    """
    pairs = [(artifact.original_own, artifact.provenance.get("content_hash"))]
    pairs += [(original, ref.get("content_hash")) for ref, original in artifact.original_pins]

    mapping = {}
    for old, new in pairs:
        if not old or old == new:
            continue
        if mapping.setdefault(old, new) != new:
            return False, f"{old} would map to two different digests"

    if not mapping:
        return False, ""

    pattern = re.compile("|".join(re.escape(old) for old in mapping))
    updated = pattern.sub(lambda match: mapping[match.group(0)], artifact.text)

    with open(artifact.path, "w", encoding="utf-8", newline="") as handle:
        handle.write(updated)
    return True, ""


def main():
    parser = argparse.ArgumentParser(
        description="Compute, audit and repair artifact content hashes."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", metavar="PATH", help="audit a file or directory tree")
    group.add_argument("--compute", metavar="FILE", help="print one artifact's digest")
    group.add_argument("--fix", metavar="PATH", help="relink and rehash a tree in place")
    parser.add_argument("-v", "--verbose", action="store_true", help="list clean artifacts")
    args = parser.parse_args()

    target = args.check or args.compute or args.fix
    if not os.path.exists(target):
        print(f"{target}: no such file or directory", file=sys.stderr)
        return 2

    if args.compute:
        artifacts, skipped, broken = load([target])
        for _path, why in broken:
            print(f"{target}: {why}", file=sys.stderr)
            return 1
        if skipped:
            print(f"{target}: no provenance block, so no content hash", file=sys.stderr)
            return 1
        print(artifacts[0].digest())
        return 0

    artifacts, skipped, broken = load(json_files(target))
    index, collisions = index_by_id(artifacts)

    for path, why in broken:
        print(f"BROKEN  {path}: {why}")
    for artifact_id, first, second in collisions:
        print(f"DUP     {artifact_id} recorded by both {first} and {second}")

    if args.fix:
        settled = reconcile(artifacts, index)
        if not settled:
            print(
                f"FAILED - digests did not settle in {MAX_PASSES} passes; the provenance "
                "graph has a cycle, and an artifact cannot be derived from itself"
            )
            return 1

        written = 0
        for artifact in artifacts:
            done, why = rewrite(artifact)
            if done:
                print(f"FIXED   {artifact.display}")
                written += 1
            elif why:
                print(f"BLOCKED {artifact.display}: {why}")
        print()
        print(f"artifacts   {len(artifacts)} hashed, {len(skipped)} without provenance")
        print(f"rewritten   {written}")
        if broken or collisions:
            return 1
        print("\ncontent hashes: reconciled")
        return 0

    problems, external = audit(artifacts, index)
    for problem in problems:
        print(problem)
    if args.verbose:
        for artifact in artifacts:
            print(f"ok      {artifact.display}")

    print()
    print(f"artifacts   {len(artifacts)} hashed, {len(skipped)} without provenance")
    print(f"pins        {external} to artifacts outside this tree")

    failures = len(problems) + len(broken) + len(collisions)
    if failures:
        print(f"\nFAILED - {failures} problem(s)")
        return 1
    print("\ncontent hashes and pins: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
