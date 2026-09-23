"""Structural checks on artifacts a step produces, before the engine persists them.

This is not a JSON Schema validator - the Factory ships none, and ajv remains the full check
(see CLAUDE.md). It is the cheap subset that catches a step emitting the wrong thing at the
point of error rather than downstream:

  * the type has a contract: a schema in core/artifacts/ (x-wgf.id == type), or it is listed
    in the workflow's `untyped_artifacts` - anything else is refused;
  * content is a JSON object;
  * for a schematized type: every top-level `required` key is present, no top-level key the
    schema forbids (`additionalProperties: false`), and - when the schema requires
    provenance - `provenance.artifact_type` equals the type and `provenance.content_hash`
    reproduces under the canonicalization in wgflib/hashing.py;
  * for an untyped type: content is a non-empty object. That is all that can be said about
    something with no contract, which is why `untyped_artifacts` is meant to stay empty.

A validator is a callable `(artifact_type, content) -> [problem, ...]`. The engine calls it
if it was given one and fails the step, non-retryably, when it returns problems. The engine
itself never reads core/ - the API wires this in.
"""

import glob
import json
import os

from .. import paths
from ..hashing import CanonicalizationError, content_hash

__all__ = ["ArtifactContracts", "load_schemas"]


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


class ArtifactContracts:
    def __init__(self, untyped=(), schemas=None):
        self.schemas = load_schemas() if schemas is None else dict(schemas)
        self.untyped = set(untyped)

    def has_contract(self, artifact_type):
        return artifact_type in self.schemas or artifact_type in self.untyped

    def __call__(self, artifact_type, content):
        if artifact_type in self.schemas:
            return self._check_schematized(artifact_type, content, self.schemas[artifact_type])
        if artifact_type in self.untyped:
            if not isinstance(content, dict) or not content:
                return [f"{artifact_type}: untyped artifact must be a non-empty JSON object"]
            return []
        return [
            f"{artifact_type}: no contract - no core/artifacts/{artifact_type}.schema.json and "
            f"not listed in the workflow's untyped_artifacts"
        ]

    @staticmethod
    def _check_schematized(artifact_type, content, schema):
        if not isinstance(content, dict):
            return [f"{artifact_type}: content must be a JSON object"]
        problems = []
        missing = [key for key in schema.get("required") or [] if key not in content]
        if missing:
            problems.append(f"{artifact_type}: missing required {', '.join(missing)}")
        if schema.get("additionalProperties") is False:
            allowed = set(schema.get("properties") or {})
            extra = sorted(set(content) - allowed)
            if extra:
                problems.append(f"{artifact_type}: properties not in the schema: "
                                f"{', '.join(extra)}")
        if "provenance" in (schema.get("required") or []) and isinstance(
                content.get("provenance"), dict):
            provenance = content["provenance"]
            if provenance.get("artifact_type") != artifact_type:
                problems.append(
                    f"{artifact_type}: provenance.artifact_type is "
                    f"{provenance.get('artifact_type')!r}"
                )
            try:
                digest = content_hash(content)
            except CanonicalizationError as exc:
                problems.append(f"{artifact_type}: cannot be canonicalized: {exc}")
            else:
                if provenance.get("content_hash") != digest:
                    problems.append(
                        f"{artifact_type}: provenance.content_hash does not reproduce "
                        f"(recorded {provenance.get('content_hash')!r}, computed {digest})"
                    )
        return problems
