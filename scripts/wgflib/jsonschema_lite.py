"""A small JSON Schema draft 2020-12 validator, standard library only.

The Factory ships no toolchain, and ajv (see CLAUDE.md) runs only when someone remembers to
run it. This module is the in-process check the workflow engine applies to every artifact
at the point it is produced, so a malformed artifact fails the step that wrote it rather
than a consumer three steps later.

It implements the vocabulary the Factory's schemas actually use, plus the few neighbouring
keywords that cost nothing, and it REFUSES everything else: `Validator.check_schema()` (run
by the constructor) raises `SchemaError` on a keyword it does not implement, so a schema that
starts using `unevaluatedProperties` breaks loudly here instead of being silently ignored.
Annotation keywords (`title`, `description`, `default`, `x-*`, ...) are accepted and ignored.

Supported
    core        $schema (2020-12 only), $id, $ref, $defs, $comment
    any         type (incl. arrays; integer vs number; bool is neither), enum, const,
                allOf, anyOf, oneOf, not, if/then/else
    object      properties, patternProperties, additionalProperties (bool or schema),
                required, dependentRequired, dependentSchemas, propertyNames,
                minProperties, maxProperties
    array       items, prefixItems, minItems, maxItems, uniqueItems, contains,
                minContains, maxContains
    string      minLength, maxLength (code points), pattern
    number      minimum, maximum, exclusiveMinimum, exclusiveMaximum, multipleOf
    format      date-time, date, time, email, uri, uri-reference, uuid, ipv4, hostname -
                ASSERTED, as ajv-formats does, not merely annotated. An unknown format is a
                SchemaError.

Refused (SchemaError): unevaluatedProperties, unevaluatedItems, $dynamicRef,
$dynamicAnchor, $anchor, $recursiveRef, $vocabulary, definitions, dependencies, and any other
keyword not listed above.

$ref resolution: a `#/json/pointer` fragment within the current resource, or a URI - absolute
(`https://.../shared/provenance.schema.json#/$defs/hash`) or relative to the current
resource's `$id` (`./shared/provenance.schema.json#/$defs/hash`) - of any schema added to the
`Registry`. `$ref` applies alongside its sibling keywords, as 2020-12 specifies.

Patterns are ECMA-262 regular expressions; Python's `re` is close but not equal. Before
compiling, each pattern is translated so the differences that matter for anchored ASCII
patterns disappear: an unescaped `$` becomes `\\Z` (Python's `$` also matches before a
trailing newline), and `\\d` / `\\w` become their ASCII classes (Python's match Unicode
digits and letters). Any construct Python cannot compile is a SchemaError, never a skip.
Patterns are unanchored (`re.search`), as in JSON Schema.

Errors are `ValidationError(pointer, message, keyword, schema_path)` where `pointer` is an
RFC 6901 JSON pointer into the instance ("" is the root). Their order is deterministic:
keywords are evaluated in a fixed order and object members in sorted key order.
"""

import datetime
import decimal
import glob
import json
import math
import os
import re
from urllib.parse import urldefrag, urljoin

__all__ = [
    "SchemaError",
    "ValidationError",
    "Registry",
    "Validator",
    "json_problems",
    "json_equal",
    "pointer_join",
    "SUPPORTED_KEYWORDS",
    "ANNOTATION_KEYWORDS",
]

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"

ANNOTATION_KEYWORDS = frozenset({
    "title", "description", "$comment", "examples", "default", "deprecated", "readOnly",
    "writeOnly", "contentMediaType", "contentEncoding", "contentSchema",
})

SUPPORTED_KEYWORDS = frozenset({
    "$schema", "$id", "$ref", "$defs",
    "type", "enum", "const", "allOf", "anyOf", "oneOf", "not", "if", "then", "else",
    "properties", "patternProperties", "additionalProperties", "required",
    "dependentRequired", "dependentSchemas", "propertyNames", "minProperties",
    "maxProperties",
    "items", "prefixItems", "minItems", "maxItems", "uniqueItems", "contains", "minContains",
    "maxContains",
    "minLength", "maxLength", "pattern",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "format",
})

TYPES = ("null", "boolean", "object", "array", "number", "integer", "string")
MAX_REF_DEPTH = 256


class SchemaError(ValueError):
    """The schema itself is unusable here: unknown keyword, bad value, unresolvable $ref."""


class ValidationError:
    """One way an instance fails a schema."""

    __slots__ = ("pointer", "message", "keyword", "schema_path")

    def __init__(self, pointer, message, keyword, schema_path=""):
        self.pointer = pointer
        self.message = message
        self.keyword = keyword
        self.schema_path = schema_path

    def __str__(self):
        return f"{self.pointer or '/'}: {self.message}"

    def __repr__(self):
        return f"ValidationError({self.pointer!r}, {self.message!r}, {self.keyword!r})"

    def __eq__(self, other):
        return (isinstance(other, ValidationError)
                and (self.pointer, self.message, self.keyword)
                == (other.pointer, other.message, other.keyword))

    def __hash__(self):
        return hash((self.pointer, self.message, self.keyword))


# -- JSON values -------------------------------------------------------------------------

def _escape(token):
    return str(token).replace("~", "~0").replace("/", "~1")


def pointer_join(pointer, token):
    return f"{pointer}/{_escape(token)}"


def _unescape(token):
    return token.replace("~1", "/").replace("~0", "~")


def json_problems(value, pointer=""):
    """[(pointer, reason)] for every part of `value` JSON cannot represent.

    NaN and the infinities, non-string object keys, tuples, sets, bytes and any other
    Python object. A value that fails here cannot be written, hashed or read back as the
    same thing, so it is malformed regardless of what the schema says.
    """
    problems = []
    if value is None or isinstance(value, (bool, str)):
        return problems
    if isinstance(value, int):
        return problems
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            problems.append((pointer, f"{value!r} is not a JSON number"))
        return problems
    if isinstance(value, list):
        for index, item in enumerate(value):
            problems.extend(json_problems(item, pointer_join(pointer, index)))
        return problems
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                problems.append((pointer, f"object key {key!r} is not a string"))
        for key in sorted(k for k in value if isinstance(k, str)):
            problems.extend(json_problems(value[key], pointer_join(pointer, key)))
        return problems
    problems.append((pointer, f"{type(value).__name__} is not a JSON value"))
    return problems


def _json_type(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_type(value, name):
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "number":
        return _is_number(value) and not (isinstance(value, float) and not math.isfinite(value))
    if name == "integer":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        return isinstance(value, float) and math.isfinite(value) and value.is_integer()
    raise AssertionError(name)


def json_equal(a, b):
    """Equality in the JSON data model: 1 == 1.0, but true != 1 and key order is ignored."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if _is_number(a) and _is_number(b):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    if type(a) is not type(b):
        return False
    return a == b


def _short(value, limit=60):
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = repr(value)
    return text if len(text) <= limit else text[:limit - 3] + "..."


# -- patterns ----------------------------------------------------------------------------

def translate_pattern(pattern):
    """An ECMA-262 pattern as an equivalent Python pattern, for the constructs that differ."""
    out = []
    in_class = False
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            if index + 1 >= len(pattern):
                raise SchemaError(f"pattern {pattern!r} ends in a lone backslash")
            nxt = pattern[index + 1]
            if nxt == "d":
                out.append("0-9" if in_class else "[0-9]")
            elif nxt == "w":
                out.append("A-Za-z0-9_" if in_class else "[A-Za-z0-9_]")
            elif nxt in "DW" and not in_class:
                out.append("[^0-9]" if nxt == "D" else "[^A-Za-z0-9_]")
            elif nxt in "DW":
                raise SchemaError(f"pattern {pattern!r}: \\{nxt} inside a class is not supported")
            elif nxt in "pPuck":
                # \p{..}, \u{..}/\uXXXX, \cX, \k<name>: ECMA constructs re reads differently.
                if nxt == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", pattern[index + 2:index + 6]):
                    out.append(pattern[index:index + 6])
                    index += 6
                    continue
                raise SchemaError(f"pattern {pattern!r}: \\{nxt} is not supported")
            else:
                out.append(char + nxt)
            index += 2
            continue
        if in_class:
            if char == "]":
                in_class = False
            elif char == "[":
                out.append("\\[")
                index += 1
                continue
            out.append(char)
        elif char == "[":
            in_class = True
            out.append(char)
            if pattern[index + 1:index + 2] == "^":
                out.append("^")
                index += 1
            if pattern[index + 1:index + 2] == "]":
                raise SchemaError(f"pattern {pattern!r}: an empty class is not supported")
        elif char == "$":
            out.append(r"\Z")
        elif char == "(" and pattern.startswith("(?<", index) and \
                pattern[index + 3:index + 4] not in ("=", "!"):
            out.append("(?P<")
            index += 3
            continue
        else:
            out.append(char)
        index += 1
    return "".join(out)


_PATTERN_CACHE = {}


def compile_pattern(pattern):
    compiled = _PATTERN_CACHE.get(pattern)
    if compiled is None:
        if not isinstance(pattern, str):
            raise SchemaError(f"pattern {pattern!r} is not a string")
        try:
            compiled = re.compile(translate_pattern(pattern))
        except re.error as exc:
            raise SchemaError(f"pattern {pattern!r} does not compile: {exc}") from None
        _PATTERN_CACHE[pattern] = compiled
    return compiled


# -- formats -----------------------------------------------------------------------------

_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})\Z")
_TIME = re.compile(r"(\d{2}):(\d{2}):(\d{2})(\.\d+)?(z|[+-]\d{2}:\d{2})\Z", re.IGNORECASE)
_EMAIL = re.compile(
    r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z",
    re.IGNORECASE,
)
_URI = re.compile(r"[a-z][a-z0-9+.-]*:[^\s]*\Z", re.IGNORECASE)
_URI_REF = re.compile(r"[^\s]*\Z")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z", re.I)
_IPV4 = re.compile(r"(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
                   r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\Z")
_HOSTNAME = re.compile(r"(?=.{1,253}\.?\Z)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
                       r"(?:\.[a-z0-9](?:[-0-9a-z]{0,61}[0-9a-z])?)*\.?\Z", re.IGNORECASE)


def _valid_date(text):
    match = _DATE.match(text)
    if not match:
        return False
    try:
        datetime.date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        return False
    return True


def _valid_time(text):
    match = _TIME.match(text)
    if not match:
        return False
    hour, minute, second = int(match[1]), int(match[2]), int(match[3])
    if hour > 23 or minute > 59:
        return False
    if second > 60:
        return False
    zone = match[5]
    if zone.lower() != "z" and (int(zone[1:3]) > 23 or int(zone[4:6]) > 59):
        return False
    # A leap second is only meaningful as 23:59:60 UTC; accept it in any offset rather
    # than reimplement offset arithmetic for a value no artifact has held.
    return second < 60 or minute == 59


def _valid_date_time(text):
    parts = re.split(r"[Tt ]", text, maxsplit=1)
    return len(parts) == 2 and _valid_date(parts[0]) and _valid_time(parts[1])


FORMATS = {
    # RFC 3339 section 5.6. The offset is REQUIRED - a timestamp without one is ambiguous.
    "date-time": _valid_date_time,
    "date": _valid_date,
    "time": _valid_time,
    "email": lambda s: bool(_EMAIL.match(s)),
    "uri": lambda s: bool(_URI.match(s)),
    "uri-reference": lambda s: bool(_URI_REF.match(s)),
    "uuid": lambda s: bool(_UUID.match(s)),
    "ipv4": lambda s: bool(_IPV4.match(s)),
    "hostname": lambda s: bool(_HOSTNAME.match(s)),
}


# -- registry ----------------------------------------------------------------------------

class Registry:
    """Every schema resource by its absolute URI, so `$ref` can cross files."""

    def __init__(self):
        self.resources = {}

    def add(self, schema, uri=None):
        uri = uri or (schema.get("$id") if isinstance(schema, dict) else None)
        if not uri:
            raise SchemaError("a registered schema needs an $id or an explicit uri")
        uri = urldefrag(uri)[0]
        if not (isinstance(schema, dict) and "$id" in schema):
            self.resources[uri] = schema  # an explicit uri names this schema, replacing any
        self._index(schema, uri)
        return uri

    def _index(self, schema, base):
        if isinstance(schema, dict):
            if "$id" in schema:
                if not isinstance(schema["$id"], str):
                    raise SchemaError(f"$id {schema['$id']!r} is not a string")
                base = urldefrag(_join(base, schema["$id"]))[0]
            existing = self.resources.get(base)
            if existing is not None and existing is not schema and "$id" in schema:
                if existing != schema:
                    raise SchemaError(f"two different schemas claim $id {base}")
            if "$id" in schema or base not in self.resources:
                self.resources[base] = schema
            for key, value in schema.items():
                if key in ("enum", "const", "default", "examples") or key.startswith("x-"):
                    continue
                if key in ("properties", "patternProperties", "$defs", "dependentSchemas"):
                    if isinstance(value, dict):
                        for sub in value.values():
                            self._index(sub, base)
                elif isinstance(value, (dict, list)):
                    self._index(value, base)
        elif isinstance(schema, list):
            for item in schema:
                self._index(item, base)

    def add_directory(self, directory, pattern="**/*.schema.json"):
        for path in sorted(glob.glob(os.path.join(directory, pattern), recursive=True)):
            with open(path, encoding="utf-8") as handle:
                schema = json.load(handle)
            self.add(schema, schema.get("$id") or _file_uri(path))
        return self

    def resolve(self, ref, base):
        """(subschema, base uri of the resource it lives in) for `ref` seen under `base`."""
        target = _join(base, ref)
        uri, fragment = urldefrag(target)
        if uri not in self.resources:
            raise SchemaError(f"$ref {ref!r} (resolved to {target}) names no known schema")
        node = self.resources[uri]
        if fragment:
            if not fragment.startswith("/"):
                raise SchemaError(f"$ref {ref!r}: anchors are not supported, only JSON pointers")
            for token in fragment[1:].split("/"):
                token = _unescape(token.replace("%25", "%").replace("%22", '"'))
                if isinstance(node, dict) and token in node:
                    node = node[token]
                elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
                    node = node[int(token)]
                else:
                    raise SchemaError(f"$ref {ref!r}: pointer does not resolve at {token!r}")
        return node, uri


def _file_uri(path):
    return "file://" + os.path.abspath(path).replace(os.sep, "/")


def _join(base, ref):
    """RFC 3986 reference resolution, plus the fragment-only case for non-hierarchical bases
    (`urn:`), which urljoin leaves unresolved."""
    if ref.startswith("#"):
        return urldefrag(base)[0] + ref
    return urljoin(base, ref)


_ANONYMOUS = [0]


# -- validator ---------------------------------------------------------------------------

class Validator:
    """Validates instances against one schema, resolving `$ref` through a Registry."""

    def __init__(self, schema, registry=None, base_uri=None, check_formats=True):
        self.schema = schema
        self.registry = registry or Registry()
        self.check_formats = check_formats
        if isinstance(schema, dict) and schema.get("$id"):
            self.base = urldefrag(_join(base_uri or "", schema["$id"]))[0]
            if self.base not in self.registry.resources:
                self.registry.add(schema, self.base)
        else:
            # A schema with no $id is its own resource under a name nothing else can take.
            if base_uri is None:
                _ANONYMOUS[0] += 1
                base_uri = f"urn:wgf:anonymous:{_ANONYMOUS[0]}"
            self.base = base_uri
            self.registry.add(schema, self.base)
        self.check_schema()

    # -- the schema ----------------------------------------------------------------------

    def check_schema(self):
        """Raise SchemaError unless every reachable subschema uses only known keywords."""
        seen = set()
        self._check(self.schema, self.base, "#", seen)

    def _check(self, schema, base, where, seen):
        if isinstance(schema, bool):
            return
        if not isinstance(schema, dict):
            raise SchemaError(f"{where}: a schema is an object or a boolean, not {_short(schema)}")
        marker = (id(schema), base)
        if marker in seen:
            return
        seen.add(marker)
        if "$id" in schema:
            base = urldefrag(_join(base, schema["$id"]))[0]
        for key, value in schema.items():
            path = f"{where}/{key}"
            if key in ANNOTATION_KEYWORDS or key.startswith("x-"):
                continue
            if key not in SUPPORTED_KEYWORDS:
                raise SchemaError(f"{path}: keyword {key!r} is not implemented by jsonschema_lite")
            if key == "$schema" and value != DRAFT_2020_12:
                raise SchemaError(f"{path}: only {DRAFT_2020_12} is supported, not {value!r}")
            elif key == "$ref":
                if not isinstance(value, str):
                    raise SchemaError(f"{path}: $ref must be a string")
                target, target_base = self.registry.resolve(value, base)
                self._check(target, target_base, f"{path}->{value}", seen)
            elif key in ("$defs", "properties", "patternProperties", "dependentSchemas"):
                if not isinstance(value, dict):
                    raise SchemaError(f"{path}: must be an object")
                for name, sub in value.items():
                    if key == "patternProperties":
                        compile_pattern(name)
                    self._check(sub, base, f"{path}/{name}", seen)
            elif key in ("allOf", "anyOf", "oneOf", "prefixItems"):
                if not isinstance(value, list) or not value:
                    raise SchemaError(f"{path}: must be a non-empty array of schemas")
                for index, sub in enumerate(value):
                    self._check(sub, base, f"{path}/{index}", seen)
            elif key in ("not", "if", "then", "else", "items", "contains", "propertyNames",
                         "additionalProperties"):
                self._check(value, base, path, seen)
            elif key == "type":
                names = value if isinstance(value, list) else [value]
                if not names or any(name not in TYPES for name in names):
                    raise SchemaError(f"{path}: unknown type {value!r}")
            elif key == "enum":
                if not isinstance(value, list):
                    raise SchemaError(f"{path}: enum must be an array")
            elif key == "required":
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    raise SchemaError(f"{path}: required must be an array of strings")
            elif key == "dependentRequired":
                if not isinstance(value, dict) or not all(
                        isinstance(v, list) and all(isinstance(s, str) for s in v)
                        for v in value.values()):
                    raise SchemaError(f"{path}: dependentRequired must map to string arrays")
            elif key in ("minItems", "maxItems", "minLength", "maxLength", "minProperties",
                         "maxProperties", "minContains", "maxContains"):
                if isinstance(value, bool) or not _is_type(value, "integer") or value < 0:
                    raise SchemaError(f"{path}: must be a non-negative integer")
            elif key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
                if not _is_number(value):
                    raise SchemaError(f"{path}: must be a number")
            elif key == "multipleOf":
                if not _is_number(value) or value <= 0:
                    raise SchemaError(f"{path}: must be a number greater than 0")
            elif key == "uniqueItems":
                if not isinstance(value, bool):
                    raise SchemaError(f"{path}: must be a boolean")
            elif key == "pattern":
                compile_pattern(value)
            elif key == "format":
                if value not in FORMATS:
                    raise SchemaError(f"{path}: format {value!r} is not implemented")

    # -- instances -----------------------------------------------------------------------

    def iter_errors(self, instance):
        return self._validate(instance, self.schema, self.base, "", "#", 0)

    def is_valid(self, instance):
        return not self.iter_errors(instance)

    def _validate(self, instance, schema, base, pointer, spath, depth):
        if schema is True:
            return []
        if schema is False:
            return [ValidationError(pointer, "no value is allowed here", "false", spath)]
        if depth > MAX_REF_DEPTH:
            raise SchemaError(f"{spath}: $ref recursion deeper than {MAX_REF_DEPTH}")
        if "$id" in schema:
            base = urldefrag(_join(base, schema["$id"]))[0]

        errors = []
        add = errors.extend
        kind = _json_type(instance)

        if "$ref" in schema:
            target, target_base = self.registry.resolve(schema["$ref"], base)
            add(self._validate(instance, target, target_base, pointer,
                               f"{spath}/$ref", depth + 1))

        if "type" in schema:
            names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(_is_type(instance, name) for name in names):
                expected = " or ".join(names)
                errors.append(ValidationError(
                    pointer, f"expected {expected}, got {kind}", "type", f"{spath}/type"))
                # Every other keyword is type-specific or would repeat this diagnosis.
                return errors

        if "enum" in schema and not any(json_equal(instance, v) for v in schema["enum"]):
            allowed = ", ".join(_short(v, 30) for v in schema["enum"])
            errors.append(ValidationError(
                pointer, f"{_short(instance)} is not one of [{allowed}]", "enum",
                f"{spath}/enum"))
        if "const" in schema and not json_equal(instance, schema["const"]):
            errors.append(ValidationError(
                pointer, f"must be {_short(schema['const'])}, got {_short(instance)}", "const",
                f"{spath}/const"))

        if isinstance(instance, dict):
            add(self._object(instance, schema, base, pointer, spath, depth))
        elif isinstance(instance, list):
            add(self._array(instance, schema, base, pointer, spath, depth))
        elif isinstance(instance, str):
            add(self._string(instance, schema, pointer, spath))
        elif _is_number(instance):
            add(self._number(instance, schema, pointer, spath))

        add(self._applicators(instance, schema, base, pointer, spath, depth))
        return errors

    def _applicators(self, instance, schema, base, pointer, spath, depth):
        errors = []
        for index, sub in enumerate(schema.get("allOf") or ()):
            errors.extend(self._validate(instance, sub, base, pointer,
                                         f"{spath}/allOf/{index}", depth + 1))
        for keyword in ("anyOf", "oneOf"):
            if keyword not in schema:
                continue
            branches = [
                self._validate(instance, sub, base, pointer, f"{spath}/{keyword}/{index}",
                               depth + 1)
                for index, sub in enumerate(schema[keyword])
            ]
            passing = [index for index, branch in enumerate(branches) if not branch]
            if not passing:
                count = len(branches)
                best = min(range(count), key=lambda i: (_shallow(branches[i], pointer),
                                                        len(branches[i]), i))
                # The closest branch's own errors follow, so the pointer names the value
                # that is actually wrong rather than the union around it.
                errors.append(ValidationError(
                    pointer,
                    f"matches none of the {count} alternatives in {keyword}; closest is "
                    f"#{best}, which fails as follows",
                    keyword, f"{spath}/{keyword}"))
                errors.extend(branches[best])
            elif keyword == "oneOf" and len(passing) > 1:
                errors.append(ValidationError(
                    pointer, f"matches alternatives {passing} of oneOf; exactly one must match",
                    keyword, f"{spath}/{keyword}"))
        if "not" in schema:
            if not self._validate(instance, schema["not"], base, pointer, f"{spath}/not",
                                  depth + 1):
                errors.append(ValidationError(
                    pointer, "must not match the schema under `not`", "not", f"{spath}/not"))
        if "if" in schema:
            matched = not self._validate(instance, schema["if"], base, pointer, f"{spath}/if",
                                         depth + 1)
            branch = "then" if matched else "else"
            if branch in schema:
                errors.extend(self._validate(instance, schema[branch], base, pointer,
                                             f"{spath}/{branch}", depth + 1))
        return errors

    def _object(self, instance, schema, base, pointer, spath, depth):
        errors = []
        for name in schema.get("required") or ():
            if name not in instance:
                errors.append(ValidationError(
                    pointer, f"missing required {name}", "required", f"{spath}/required"))
        for name, needed in sorted((schema.get("dependentRequired") or {}).items()):
            if name in instance:
                for other in needed:
                    if other not in instance:
                        errors.append(ValidationError(
                            pointer, f"{name} requires {other}", "dependentRequired",
                            f"{spath}/dependentRequired/{name}"))
        if "minProperties" in schema and len(instance) < schema["minProperties"]:
            errors.append(ValidationError(
                pointer, f"has {len(instance)} properties, fewer than {schema['minProperties']}",
                "minProperties", f"{spath}/minProperties"))
        if "maxProperties" in schema and len(instance) > schema["maxProperties"]:
            errors.append(ValidationError(
                pointer, f"has {len(instance)} properties, more than {schema['maxProperties']}",
                "maxProperties", f"{spath}/maxProperties"))

        properties = schema.get("properties") or {}
        patterns = schema.get("patternProperties") or {}
        additional = schema.get("additionalProperties", True)
        names = schema.get("propertyNames")
        for key in sorted(k for k in instance if isinstance(k, str)):
            child = pointer_join(pointer, key)
            value = instance[key]
            if names is not None:
                for error in self._validate(key, names, base, child,
                                            f"{spath}/propertyNames", depth + 1):
                    errors.append(ValidationError(
                        pointer, f"property name {key!r} is not allowed: {error.message}",
                        "propertyNames", error.schema_path))
            evaluated = False
            if key in properties:
                evaluated = True
                errors.extend(self._validate(value, properties[key], base, child,
                                             f"{spath}/properties/{_escape(key)}", depth + 1))
            for regex in sorted(patterns):
                if compile_pattern(regex).search(key):
                    evaluated = True
                    errors.extend(self._validate(value, patterns[regex], base, child,
                                                 f"{spath}/patternProperties/{_escape(regex)}",
                                                 depth + 1))
            if not evaluated and additional is not True:
                if additional is False:
                    errors.append(ValidationError(
                        child, f"property {key!r} is not in the schema "
                               "(additionalProperties is false)",
                        "additionalProperties", f"{spath}/additionalProperties"))
                else:
                    errors.extend(self._validate(value, additional, base, child,
                                                 f"{spath}/additionalProperties", depth + 1))
        for name, sub in sorted((schema.get("dependentSchemas") or {}).items()):
            if name in instance:
                errors.extend(self._validate(instance, sub, base, pointer,
                                             f"{spath}/dependentSchemas/{_escape(name)}",
                                             depth + 1))
        return errors

    def _array(self, instance, schema, base, pointer, spath, depth):
        errors = []
        count = len(instance)
        if "minItems" in schema and count < schema["minItems"]:
            errors.append(ValidationError(
                pointer, f"has {count} items, fewer than {schema['minItems']}", "minItems",
                f"{spath}/minItems"))
        if "maxItems" in schema and count > schema["maxItems"]:
            errors.append(ValidationError(
                pointer, f"has {count} items, more than {schema['maxItems']}", "maxItems",
                f"{spath}/maxItems"))
        if schema.get("uniqueItems"):
            for later in range(count):
                duplicate = next((earlier for earlier in range(later)
                                  if json_equal(instance[earlier], instance[later])), None)
                if duplicate is not None:
                    errors.append(ValidationError(
                        pointer, f"items {duplicate} and {later} are equal; items must be "
                                 "unique", "uniqueItems", f"{spath}/uniqueItems"))
                    break
        prefix = schema.get("prefixItems") or []
        for index, sub in enumerate(prefix[:count]):
            errors.extend(self._validate(instance[index], sub, base,
                                         pointer_join(pointer, index),
                                         f"{spath}/prefixItems/{index}", depth + 1))
        if "items" in schema:
            for index in range(len(prefix), count):
                errors.extend(self._validate(instance[index], schema["items"], base,
                                             pointer_join(pointer, index), f"{spath}/items",
                                             depth + 1))
        if "contains" in schema:
            matches = sum(
                1 for index, item in enumerate(instance)
                if not self._validate(item, schema["contains"], base,
                                      pointer_join(pointer, index), f"{spath}/contains",
                                      depth + 1))
            low = schema.get("minContains", 1)
            high = schema.get("maxContains")
            if matches < low:
                errors.append(ValidationError(
                    pointer, f"{matches} items match `contains`, fewer than {low}", "contains",
                    f"{spath}/contains"))
            if high is not None and matches > high:
                errors.append(ValidationError(
                    pointer, f"{matches} items match `contains`, more than {high}",
                    "maxContains", f"{spath}/maxContains"))
        return errors

    def _string(self, instance, schema, pointer, spath):
        errors = []
        length = len(instance)  # code points, as ajv counts them
        if "minLength" in schema and length < schema["minLength"]:
            errors.append(ValidationError(
                pointer, f"is {length} characters, shorter than {schema['minLength']}",
                "minLength", f"{spath}/minLength"))
        if "maxLength" in schema and length > schema["maxLength"]:
            errors.append(ValidationError(
                pointer, f"is {length} characters, longer than {schema['maxLength']}",
                "maxLength", f"{spath}/maxLength"))
        if "pattern" in schema and not compile_pattern(schema["pattern"]).search(instance):
            errors.append(ValidationError(
                pointer, f"{_short(instance)} does not match pattern {schema['pattern']}",
                "pattern", f"{spath}/pattern"))
        if "format" in schema and self.check_formats:
            if not FORMATS[schema["format"]](instance):
                errors.append(ValidationError(
                    pointer, f"{_short(instance)} is not a valid {schema['format']}", "format",
                    f"{spath}/format"))
        return errors

    def _number(self, instance, schema, pointer, spath):
        errors = []
        if isinstance(instance, float) and not math.isfinite(instance):
            return [ValidationError(pointer, f"{instance!r} is not a JSON number", "type",
                                    f"{spath}")]
        checks = (
            ("minimum", lambda v, b: v >= b, "less than"),
            ("maximum", lambda v, b: v <= b, "greater than"),
            ("exclusiveMinimum", lambda v, b: v > b, "not greater than"),
            ("exclusiveMaximum", lambda v, b: v < b, "not less than"),
        )
        for keyword, holds, words in checks:
            if keyword in schema and not holds(instance, schema[keyword]):
                errors.append(ValidationError(
                    pointer, f"{_short(instance)} is {words} {schema[keyword]}", keyword,
                    f"{spath}/{keyword}"))
        if "multipleOf" in schema:
            divisor = schema["multipleOf"]
            try:
                quotient = decimal.Decimal(repr(instance)) / decimal.Decimal(repr(divisor))
                ok = quotient == quotient.to_integral_value()
            except decimal.DecimalException:
                ok = False
            if not ok:
                errors.append(ValidationError(
                    pointer, f"{_short(instance)} is not a multiple of {divisor}", "multipleOf",
                    f"{spath}/multipleOf"))
        return errors


def _shallow(errors, pointer):
    """1 when a branch failed on its type at this very value - the least informative kind."""
    return 1 if any(e.pointer == pointer and e.keyword in ("type", "false") for e in errors) \
        else 0
