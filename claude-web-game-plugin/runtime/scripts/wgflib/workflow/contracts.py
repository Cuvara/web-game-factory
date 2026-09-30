"""Schema validation of artifacts a step produces or consumes, before the engine trusts them.

Every artifact type with a schema in core/artifacts/ is validated against the WHOLE schema -
nested objects, enums, patterns, formats, conditionals, `$ref`s into core/artifacts/shared/ -
by wgflib/jsonschema_lite.py, the Factory's stdlib draft 2020-12 validator. On top of the
schema, two things no schema can say:

  * `provenance.artifact_type` equals the type the artifact is being checked as;
  * `provenance.schema_version` has the MAJOR of the schema's `x-wgf.version` (another
    minor is accepted, so artifacts written under an older minor stay readable);
  * `provenance.content_hash` reproduces under the canonicalization in wgflib/hashing.py.

And before any of it, content must be a JSON object that JSON can represent (no NaN or
infinities, no non-string keys, no Python-only values) - otherwise it cannot be written,
hashed or read back as the same thing.

The type must have a contract: a schema (x-wgf.id == type), or a place in the workflow's
`untyped_artifacts`, for which nothing is known beyond "a non-empty JSON object" - which is
why that list is meant to stay empty. Anything else is refused.

A validator is a callable `(artifact_type, content) -> [problem, ...]` returning readable
strings, `"<type>: <json pointer>: <message>"`, at most MAX_PROBLEMS of them plus a line
saying how many were left out. The engine calls it if it was given one and fails the step,
non-retryably, when it returns problems. The engine itself never reads core/ - the API wires
this in.

`check_lineage(content, consumed)` is the other half of provenance: it checks that an
artifact's `provenance.inputs` pins exactly the versions of its inputs that were consumed.
See its docstring and docs/core-contracts.md.
"""

import glob
import json
import os

from .. import paths
from ..hashing import CanonicalizationError, content_hash
from ..jsonschema_lite import Registry, SchemaError, Validator, json_problems
from ..provenance import major

__all__ = ["ArtifactContracts", "load_schemas", "load_registry", "check_lineage",
           "MAX_PROBLEMS"]

MAX_PROBLEMS = 20


def load_schemas(directory=None):
    """{artifact id: schema} for every top-level schema that carries an x-wgf block."""
    directory = directory or paths.ARTIFACTS
    schemas = {}
    for path in sorted(glob.glob(os.path.join(directory, "*.schema.json"))):
        with open(path, encoding="utf-8") as handle:
            schema = json.load(handle)
        meta = schema.get("x-wgf")
        if meta and meta.get("id"):
            schemas[meta["id"]] = schema
    return schemas


def load_registry(directory=None):
    """A Registry holding every schema under `directory`, shared/ included."""
    return Registry().add_directory(directory or paths.ARTIFACTS)


def _cap(problems, limit=MAX_PROBLEMS):
    if len(problems) <= limit:
        return problems
    return problems[:limit] + [f"... and {len(problems) - limit} more problems"]


class ArtifactContracts:
    def __init__(self, untyped=(), schemas=None, registry=None, max_problems=MAX_PROBLEMS):
        self.schemas = load_schemas() if schemas is None else dict(schemas)
        self.untyped = set(untyped)
        self.max_problems = max_problems
        self._registry = registry
        self._validators = {}

    @property
    def registry(self):
        if self._registry is None:
            self._registry = load_registry()
        return self._registry

    def has_contract(self, artifact_type):
        return artifact_type in self.schemas or artifact_type in self.untyped

    def validator(self, artifact_type):
        """The compiled Validator for a schematized type. Raises SchemaError if it will not
        compile - a broken contract is a Factory bug, not a problem with the artifact."""
        validator = self._validators.get(artifact_type)
        if validator is None:
            schema = self.schemas[artifact_type]
            validator = Validator(schema, self.registry,
                                  base_uri=None if schema.get("$id") else
                                  f"urn:wgf:artifact:{artifact_type}")
            self._validators[artifact_type] = validator
        return validator

    def __call__(self, artifact_type, content):
        """At most `max_problems` problems (plus a count of the rest). The provenance
        identity and hash problems are always kept: they are few, and they explain the rest."""
        if artifact_type in self.schemas:
            schema_problems, integrity = self._split(artifact_type, content)
            room = max(self.max_problems - len(integrity), 1)
            capped = _cap(schema_problems, room)
            if len(capped) > room:  # the "... and N more" line goes last
                return capped[:-1] + integrity + capped[-1:]
            return capped + integrity
        return _cap(self.problems(artifact_type, content), self.max_problems)

    def problems(self, artifact_type, content):
        """Every problem, uncapped: schema violations first, then provenance integrity."""
        if artifact_type in self.schemas:
            schema_problems, integrity = self._split(artifact_type, content)
            return schema_problems + integrity
        if artifact_type in self.untyped:
            if not isinstance(content, dict) or not content:
                return [f"{artifact_type}: untyped artifact must be a non-empty JSON object"]
            return [f"{artifact_type}: {pointer or '/'}: {reason}"
                    for pointer, reason in json_problems(content)]
        return [
            f"{artifact_type}: no contract - no core/artifacts/{artifact_type}.schema.json and "
            f"not listed in the workflow's untyped_artifacts"
        ]

    def _split(self, artifact_type, content):
        """(schema problems, provenance integrity problems)."""
        schema = self.schemas[artifact_type]
        if not isinstance(content, dict):
            return [f"{artifact_type}: content must be a JSON object"], []
        malformed = json_problems(content)
        if malformed:
            return [f"{artifact_type}: {pointer or '/'}: not JSON - {reason}"
                    for pointer, reason in malformed], []

        try:
            errors = self.validator(artifact_type).iter_errors(content)
        except SchemaError as exc:
            return [f"{artifact_type}: the schema cannot be applied: {exc}"], []
        problems = []
        if "provenance" in (schema.get("required") or []) and isinstance(
                content.get("provenance"), dict):
            provenance = content["provenance"]
            if provenance.get("artifact_type") != artifact_type:
                problems.append(
                    f"{artifact_type}: /provenance/artifact_type: is "
                    f"{provenance.get('artifact_type')!r}, not {artifact_type!r}"
                )
            problem = self._version_problem(artifact_type, schema, provenance)
            if problem:
                problems.append(problem)
            try:
                digest = content_hash(content)
            except CanonicalizationError as exc:
                problems.append(f"{artifact_type}: cannot be canonicalized: {exc}")
            else:
                if provenance.get("content_hash") != digest:
                    problems.append(
                        f"{artifact_type}: /provenance/content_hash: does not reproduce "
                        f"(recorded {provenance.get('content_hash')!r}, computed {digest})"
                    )
        return [f"{artifact_type}: {error}" for error in errors], problems

    @staticmethod
    def _version_problem(artifact_type, schema, provenance):
        """A problem unless `provenance.schema_version` has the MAJOR of the schema's
        `x-wgf.version`. Another minor or patch of the same major is compatible by
        definition (wgflib/provenance.py), so older artifacts stay readable. A schema that
        declares no version cannot be checked against; a malformed schema_version is the
        schema's own pattern violation, reported there."""
        declared = (schema.get("x-wgf") or {}).get("version")
        claimed = provenance.get("schema_version")
        expected, found = major(declared), major(claimed)
        if expected is None or found is None or expected == found:
            return None
        return (f"{artifact_type}: /provenance/schema_version: {claimed} is major {found}, "
                f"but the contract is {declared} (x-wgf.version); a producer must write "
                f"the contract's major")


# -- lineage -----------------------------------------------------------------------------

def _consumed_entries(consumed):
    """Normalize what a step consumed to [(artifact_type, content_hash, artifact_id|None)].

    Accepts a mapping {type: item} or an iterable of items, where an item is
    - a workflow ArtifactRef (or anything with `.type` and `.content_hash`),
    - a provenance-style reference {"artifact_type", "content_hash", "artifact_id"?},
    - the consumed artifact's full content (anything with a `provenance` object).
    Items that carry no content hash - untyped artifacts, claims - cannot be pinned and are
    skipped.
    """
    if isinstance(consumed, dict):
        items = [(key, value) for key, value in sorted(consumed.items())]
    else:
        items = [(None, value) for value in consumed or ()]
    entries = []
    for key, item in items:
        if isinstance(item, dict) and isinstance(item.get("provenance"), dict):
            provenance = item["provenance"]
            entries.append((provenance.get("artifact_type") or key,
                            provenance.get("content_hash"), provenance.get("artifact_id")))
        elif isinstance(item, dict):
            entries.append((item.get("artifact_type") or key, item.get("content_hash"),
                            item.get("artifact_id")))
        elif hasattr(item, "content_hash"):
            entries.append((getattr(item, "type", None) or key, item.content_hash, None))
        else:
            raise TypeError(f"cannot read a consumed artifact reference from {item!r}")
    return [entry for entry in entries if entry[0] and entry[1]]


def check_lineage(content, consumed):
    """[problem, ...] unless `content.provenance.inputs` pins exactly what was consumed.

    Lineage in the Factory is `provenance.inputs[]`: an artifactRef (artifact_id,
    artifact_type, content_hash) for every artifact this one was derived from
    (shared/provenance.schema.json#/$defs/artifactRef). This checks, for the artifacts a
    step actually consumed:

      * every consumed artifact that carries a content hash is pinned - an entry of its type
        whose content_hash equals the consumed hash (and, where the consumed side names one,
        whose artifact_id matches);
      * no entry of a consumed TYPE pins a hash that was not consumed - a stale pin, the
        signature of an artifact rebuilt from an older input or copied from a previous run.

    Entries of types the step did not consume (claims, upstream artifacts carried forward)
    are left alone: they cannot be checked from here.
    """
    if not isinstance(content, dict) or not isinstance(content.get("provenance"), dict):
        return ["lineage: artifact has no provenance object"]
    pins = content["provenance"].get("inputs")
    if not isinstance(pins, list):
        return ["lineage: /provenance/inputs is not an array"]
    pins = [(index, pin) for index, pin in enumerate(pins) if isinstance(pin, dict)]

    problems = []
    entries = _consumed_entries(consumed)
    consumed_types = {artifact_type for artifact_type, _, _ in entries}
    for artifact_type, digest, artifact_id in entries:
        same_type = [(i, pin) for i, pin in pins if pin.get("artifact_type") == artifact_type]
        match = [(i, pin) for i, pin in same_type if pin.get("content_hash") == digest]
        if not match:
            if same_type:
                problems.append(
                    f"lineage: /provenance/inputs/{same_type[0][0]}: pins {artifact_type} at "
                    f"{same_type[0][1].get('content_hash')}, but {digest} was consumed")
            else:
                problems.append(
                    f"lineage: /provenance/inputs: does not pin consumed {artifact_type} "
                    f"({digest})")
            continue
        if artifact_id and not any(pin.get("artifact_id") == artifact_id for _, pin in match):
            index, pin = match[0]
            problems.append(
                f"lineage: /provenance/inputs/{index}/artifact_id: is "
                f"{pin.get('artifact_id')!r}, but the consumed {artifact_type} is {artifact_id!r}")

    hashes = {(t, h) for t, h, _ in entries}
    for index, pin in pins:
        artifact_type = pin.get("artifact_type")
        if artifact_type in consumed_types and (artifact_type, pin.get("content_hash")) \
                not in hashes:
            already = any(f"/provenance/inputs/{index}:" in p for p in problems)
            if not already:
                problems.append(
                    f"lineage: /provenance/inputs/{index}: pins {artifact_type} at "
                    f"{pin.get('content_hash')}, which this step did not consume")
    return problems
