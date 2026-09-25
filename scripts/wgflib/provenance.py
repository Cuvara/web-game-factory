"""One provenance builder for every artifact the Factory writes.

Every artifact carries `provenance` (core/artifacts/shared/provenance.schema.json#/$defs/
provenance): who made it, when, from which pinned inputs, under which contract version, and
its own content hash. Each step module used to assemble that object by hand, with its own
hardcoded SCHEMA_VERSION that nothing tied to the schema. This module is the one place it is
built, and the contract version comes from where the contract lives: the schema's
`x-wgf.version`.

    from wgflib import provenance

    artifact = {"provenance": provenance.build(
        "game-design",
        artifact_id=provenance.artifact_id("game-design", title_id, now, context.execution),
        produced_by=provenance.producer("game-designer"),
        produced_at=now,
        inputs=provenance.pin_inputs(inputs),
        title_id=title_id)}
    artifact.update(body)
    provenance.seal(artifact)

Versioning. `x-wgf.version` is semver. A producer writes it into `provenance.schema_version`
(build() does, unless given one explicitly). The engine's contract check
(wgflib/workflow/contracts.py) refuses an artifact whose schema_version has another MAJOR than
the schema's `x-wgf.version`; an older or newer MINOR of the same major is accepted, so
artifacts written before a minor bump stay readable. Bump the minor for an additive change,
the major for one that makes an existing artifact invalid or changes a field's meaning.

Key order inside `provenance` is fixed here (the schema's order); the content hash does not
depend on it (wgflib/hashing.py sorts keys).
"""

import functools
import glob
import json
import os
import re

from . import paths
from .hashing import content_hash

__all__ = ["ProvenanceError", "SEMVER", "version_of", "schema_versions", "major",
           "artifact_id", "producer", "pin", "pin_inputs", "build", "seal"]

SEMVER = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)$")


class ProvenanceError(ValueError):
    """A contract version cannot be determined, or a builder argument is unusable."""


@functools.lru_cache(maxsize=8)
def _versions(directory):
    versions = {}
    for path in sorted(glob.glob(os.path.join(directory, "*.schema.json"))):
        with open(path, encoding="utf-8") as handle:
            meta = json.load(handle).get("x-wgf") or {}
        if meta.get("id"):
            versions[meta["id"]] = meta.get("version")
    return versions


def schema_versions(directory=None):
    """{artifact type: x-wgf.version or None} for every top-level schema."""
    return dict(_versions(os.path.abspath(directory or paths.ARTIFACTS)))


def version_of(artifact_type, directory=None):
    """The `x-wgf.version` of core/artifacts/<artifact_type>.schema.json."""
    version = _versions(os.path.abspath(directory or paths.ARTIFACTS)).get(artifact_type)
    if not isinstance(version, str) or not SEMVER.match(version):
        raise ProvenanceError(f"{artifact_type}: no schema with a semver x-wgf.version "
                              f"(found {version!r})")
    return version


def major(version):
    """The MAJOR of a semver string, or None if it is not one."""
    match = SEMVER.match(version) if isinstance(version, str) else None
    return int(match.group(1)) if match else None


def artifact_id(artifact_type, scope, produced_at, sequence):
    """`wgf:<type>:<scope>:<yyyymmdd>-<nn>`: the date of `produced_at` (an ISO 8601 string)
    and `sequence` capped at 99 - in practice the step's execution count."""
    return (f"wgf:{artifact_type}:{scope}:{str(produced_at)[:10].replace('-', '')}-"
            f"{min(int(sequence), 99):02d}")


def producer(role, actor="automation"):
    """A `produced_by` object."""
    return {"role": role, "actor": actor}


def pin(artifact_type, content, digest):
    """An artifactRef pinning `content` (a loaded artifact) at `digest` - the hash the engine
    recorded for the version consumed - or None when there is nothing to pin (no provenance,
    no artifact_id, or no hash)."""
    source = content.get("provenance") if isinstance(content, dict) else None
    if not isinstance(source, dict) or not source.get("artifact_id") or not digest:
        return None
    return {"artifact_id": source["artifact_id"], "artifact_type": artifact_type,
            "content_hash": digest}


def pin_inputs(inputs, types=None):
    """artifactRefs for what a step consumed, in type order: every present input of
    `inputs.refs` (or only `types`) that has provenance and a recorded hash."""
    refs = getattr(inputs, "refs", None) or {}
    pinned = []
    for input_type, ref in sorted(refs.items()):
        if ref is None or (types is not None and input_type not in types):
            continue
        entry = pin(input_type, inputs.load(input_type), getattr(ref, "content_hash", None))
        if entry:
            pinned.append(entry)
    return pinned


def build(artifact_type, *, artifact_id, produced_by, produced_at, inputs=(),
          schema_version=None, opportunity_id=None, title_id=None, status="draft",
          supersedes=None, directory=None):
    """A provenance object with an empty content_hash; seal() the finished artifact.

    `opportunity_id` and `title_id` are written when not None (pass `value or None` to
    leave out an empty one).

    `schema_version` defaults to the schema's x-wgf.version. Pass one explicitly only to
    write an artifact under an older contract on purpose (a fixture, a migration)."""
    version = schema_version or version_of(artifact_type, directory)
    if not SEMVER.match(str(version)):
        raise ProvenanceError(f"{artifact_type}: schema_version {version!r} is not semver")
    provenance = {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "schema_version": version,
    }
    if opportunity_id is not None:
        provenance["opportunity_id"] = opportunity_id
    if title_id is not None:
        provenance["title_id"] = title_id
    provenance.update({
        "produced_by": dict(produced_by),
        "produced_at": produced_at,
        "inputs": list(inputs),
        "content_hash": "",
        "status": status,
    })
    if supersedes:
        provenance["supersedes"] = supersedes
    return provenance


def seal(artifact):
    """Record the artifact's own content hash in its provenance; returns the artifact."""
    artifact["provenance"]["content_hash"] = content_hash(artifact)
    return artifact
