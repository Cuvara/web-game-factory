"""Validating a document against a schema in core/artifacts/, with the standard library.

The Factory ships no JSON Schema validator and ajv remains the full check (CLAUDE.md). A
release manifest is the one artifact whose validity is a precondition of the step itself -
a manifest that does not validate is not a release - so this module carries the subset of
draft 2020-12 the artifact schemas actually use:

    $ref (same document, and relative to another schema file), type, enum, const,
    required, properties, additionalProperties, items, minItems, maxItems, minLength,
    pattern, minimum, maximum, format (date-time), allOf, anyOf, oneOf

Anything else in a schema is ignored, as an annotation would be. `x-wgf` and descriptions
are annotations.
"""

import json
import os
import re

from wgflib import paths

__all__ = ["SchemaValidator", "validate_artifact"]

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}
_DATE_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$")


class SchemaValidator:
    def __init__(self, directory=None):
        self.directory = directory or paths.ARTIFACTS
        self._cache = {}

    def _load(self, path):
        path = os.path.normpath(path)
        if path not in self._cache:
            with open(path, encoding="utf-8") as handle:
                self._cache[path] = json.load(handle)
        return self._cache[path]

    def schema_path(self, artifact_type):
        return os.path.join(self.directory, f"{artifact_type}.schema.json")

    def validate(self, document, artifact_type):
        """[problem, ...] for `document` against core/artifacts/<artifact_type>.schema.json."""
        path = self.schema_path(artifact_type)
        problems = []
        self._check(document, self._load(path), path, "$", problems)
        return problems

    # -- the walk ---------------------------------------------------------------------------

    def _resolve(self, ref, base):
        target, _, pointer = ref.partition("#")
        path = os.path.join(os.path.dirname(base), target) if target else base
        node = self._load(path)
        for part in [p for p in pointer.split("/") if p]:
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return node, path

    def _check(self, value, schema, base, where, problems):
        if schema is True or schema is None:
            return
        if schema is False:
            problems.append(f"{where}: not allowed")
            return
        if "$ref" in schema:
            target, target_base = self._resolve(schema["$ref"], base)
            self._check(value, target, target_base, where, problems)

        expected = schema.get("type")
        if expected is not None:
            names = expected if isinstance(expected, list) else [expected]
            if not any(_TYPES[name](value) for name in names):
                problems.append(f"{where}: expected {'/'.join(names)}, got "
                                f"{type(value).__name__}")
                return
        if "const" in schema and value != schema["const"]:
            problems.append(f"{where}: must be {schema['const']!r}")
        if "enum" in schema and value not in schema["enum"]:
            problems.append(f"{where}: {value!r} is not one of {schema['enum']}")

        if isinstance(value, str):
            if "minLength" in schema and len(value) < schema["minLength"]:
                problems.append(f"{where}: shorter than {schema['minLength']}")
            if "pattern" in schema and not re.search(schema["pattern"], value):
                problems.append(f"{where}: {value!r} does not match {schema['pattern']}")
            if schema.get("format") == "date-time" and not _DATE_TIME.match(value):
                problems.append(f"{where}: {value!r} is not a date-time")
        if _TYPES["number"](value):
            if "minimum" in schema and value < schema["minimum"]:
                problems.append(f"{where}: below {schema['minimum']}")
            if "maximum" in schema and value > schema["maximum"]:
                problems.append(f"{where}: above {schema['maximum']}")

        if isinstance(value, dict):
            for key in schema.get("required") or []:
                if key not in value:
                    problems.append(f"{where}: missing required {key!r}")
            properties = schema.get("properties") or {}
            extra = schema.get("additionalProperties", True)
            for key, item in value.items():
                if key in properties:
                    self._check(item, properties[key], base, f"{where}.{key}", problems)
                elif extra is False:
                    problems.append(f"{where}: unexpected property {key!r}")
                elif isinstance(extra, dict):
                    self._check(item, extra, base, f"{where}.{key}", problems)

        if isinstance(value, list):
            if "minItems" in schema and len(value) < schema["minItems"]:
                problems.append(f"{where}: fewer than {schema['minItems']} item(s)")
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                problems.append(f"{where}: more than {schema['maxItems']} item(s)")
            if isinstance(schema.get("items"), dict):
                for index, item in enumerate(value):
                    self._check(item, schema["items"], base, f"{where}[{index}]", problems)

        for sub in schema.get("allOf") or []:
            self._check(value, sub, base, where, problems)
        for key in ("anyOf", "oneOf"):
            options = schema.get(key)
            if not options:
                continue
            passing = 0
            for sub in options:
                trial = []
                self._check(value, sub, base, where, trial)
                passing += not trial
            if passing == 0 or (key == "oneOf" and passing > 1):
                problems.append(f"{where}: does not match {key}")


def validate_artifact(document, artifact_type, directory=None):
    return SchemaValidator(directory).validate(document, artifact_type)
