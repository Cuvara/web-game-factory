"""The canonical content hash of a Factory artifact.

The algorithm is specified on `#/$defs/hash` in core/artifacts/shared/provenance.schema.json.
It is a contract rather than an implementation detail because artifacts are produced on both
sides of a repository boundary: workspace artifacts here, release artifacts in the game
repository by web-game-template/scripts/_shared.mjs. Two producers that disagree on the
serialization produce two different digests for the same content, and every gate pins its
subject by that digest.

This module is the Factory-side implementation. `_shared.mjs` is the game-repo-side one.
They must agree exactly; scripts/tests/test_hashing.py checks them against a shared vector
file, and against the live `node` implementation when a Node runtime is available.

Where Python and JavaScript disagree and why it matters here:

  * `JSON.stringify(12.0)` is "12"; Python's `repr(12.0)` is "12.0". Integral floats are
    therefore emitted in integer form.
  * JavaScript switches to exponential notation below 1e-6 and at or above 1e21, on
    thresholds Python does not share. Rather than reimplement ECMA-262 Number::toString for
    values no artifact has ever held, such numbers raise. A wrong digest is silent; an
    exception is not.
"""

import hashlib
import json

__all__ = ["stable_stringify", "content_hash", "CanonicalizationError"]


class CanonicalizationError(ValueError):
    """A value cannot be serialized identically on both sides of the boundary."""


def _number(value):
    """A number as `JSON.stringify` would render it."""
    if isinstance(value, bool):  # bool is an int in Python; never reach the numeric path
        raise AssertionError("handled by the caller")

    if isinstance(value, int):
        return str(value)

    if value != value or value in (float("inf"), float("-inf")):
        # JSON.stringify renders these as null. No artifact should contain one, and a digest
        # over a value JSON cannot round-trip is not worth defending.
        raise CanonicalizationError(f"{value!r} is not representable in JSON")

    if value.is_integer() and abs(value) < 1e21:
        return str(int(value))

    rendered = repr(value)
    if "e" in rendered or "E" in rendered:
        raise CanonicalizationError(
            f"{value!r} needs exponential notation, where Python and JavaScript disagree on "
            "both the threshold and the exponent format. Express it as a decimal."
        )
    return rendered


def stable_stringify(value):
    """Serialize `value` the way the canonicalization rule requires.

    Object keys sort lexicographically by code point; array order is left alone, because in
    an artifact a list's order is meaning rather than formatting.
    """
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        # Matches JSON.stringify for strings: short escapes for the control characters that
        # have them, \u00XX for the rest, and non-ASCII left as itself.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, list):
        return "[" + ",".join(stable_stringify(item) for item in value) + "]"
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise CanonicalizationError(f"object key {key!r} is not a string")
        return (
            "{"
            + ",".join(
                json.dumps(key, ensure_ascii=False) + ":" + stable_stringify(value[key])
                for key in sorted(value)
            )
            + "}"
        )
    raise CanonicalizationError(f"{type(value).__name__} has no JSON representation")


def content_hash(artifact):
    """The digest of `artifact`, computed over a copy with its own hash slot blanked.

    Blanked rather than removed: a value cannot contain a digest of itself, and removing the
    key instead would make the digest depend on whether the producer had written the slot
    yet.
    """
    if not isinstance(artifact, dict):
        raise CanonicalizationError("an artifact is a JSON object")

    provenance = artifact.get("provenance")
    if not isinstance(provenance, dict):
        raise CanonicalizationError(
            "artifact has no provenance object, so it carries no content_hash to compute"
        )

    blanked = dict(artifact)
    blanked["provenance"] = dict(provenance, content_hash="")
    digest = hashlib.sha256(stable_stringify(blanked).encode("utf-8")).hexdigest()
    return "sha256:" + digest
