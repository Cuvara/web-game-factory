"""CONTRACTS - the artifact-contract category of the Core Acceptance Suite.

What it proves:

  * every schema in core/artifacts/ compiles under wgflib/jsonschema_lite.py, and the
    validator implements every keyword those schemas use (enumerated here, not assumed);
  * every instance under workspace/, and every reference file in core/reference/ that a
    shared schema describes, validates against its schema;
  * the validator's semantics on the constructs that matter - type, enum, nested required,
    additionalProperties, pattern (with the ECMA/Python differences), format, conditionals,
    composition, $ref across files - with a JSON pointer on every error, in a fixed order;
  * ArtifactContracts rejects wrong content, missing and malformed artifacts, hash and type
    mismatches, and caps its diagnostics;
  * check_lineage catches an artifact that pins something other than what was consumed;
  * every artifact a --mock run produces is schema-valid and its lineage closes;
  * where npx and ajv are available, the validator agrees with ajv on a corpus of valid and
    mutated instances (skipped otherwise - see AjvDifferential).

Deterministic and offline except AjvDifferential, which skips unless `npx` can run ajv from
its cache or the network. Run from the repository root:

    python -m unittest discover scripts/tests
"""

import copy
import glob
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from wgflib import jsonschema_lite as js  # noqa: E402
from wgflib import paths  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import (  # noqa: E402
    MAX_PROBLEMS,
    ArtifactContracts,
    check_lineage,
    load_registry,
    load_schemas,
)
from wgflib.workflow.model import ArtifactRef, RunStatus  # noqa: E402
from wgflib.yamllite import load as load_yaml  # noqa: E402

SHARED = os.path.join(paths.ARTIFACTS, "shared")
SCHEMA_FILES = sorted(glob.glob(os.path.join(paths.ARTIFACTS, "**", "*.schema.json"),
                                recursive=True))
REGISTRY = load_registry()
CONTRACTS = ArtifactContracts()

# Workspace directories whose files no Factory schema describes, and why.
UNSCHEMATIZED = {
    # Raw evidence snapshots are the discovery module's own input format (read by
    # wgf_discovery/evidence.py); claims cite them. They are not artifacts.
    os.path.join("research", "snapshots"),
    # Installation configuration (factory.yaml, the template lock) is read by the tooling
    # that owns it (wgflib.workflow.config, wgflib.template) and validated there; it is
    # not an artifact and has no artifact schema.
    "config",
}

REFERENCE_FILES = (
    [(os.path.join(paths.REFERENCE, "dimensions.yaml"), "dimension-vocabulary")]
    + [(path, "platform-profile")
       for path in sorted(glob.glob(os.path.join(paths.PLATFORMS, "*.yaml")))]
    + [(path, "scoring-model")
       for path in sorted(glob.glob(os.path.join(paths.SCORING, "*.yaml")))]
)


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def schema_path(schema_id):
    top = os.path.join(paths.ARTIFACTS, f"{schema_id}.schema.json")
    return top if os.path.exists(top) else os.path.join(SHARED, f"{schema_id}.schema.json")


def validator_for(schema_id):
    return js.Validator(read_json(schema_path(schema_id)), REGISTRY)


def workspace_instances():
    """[(path, schema id)] for every JSON file under workspace/ that is an artifact.

    The schema is named by the instance itself where it can be: `provenance.artifact_type`.
    Claims and state carry no provenance by design (CLAUDE.md), so they are recognised by
    where they live."""
    found = []
    for path in sorted(glob.glob(os.path.join(paths.WORKSPACE, "**", "*.json"),
                                 recursive=True)):
        relative = os.path.relpath(os.path.dirname(path), paths.WORKSPACE)
        if relative in UNSCHEMATIZED:
            continue
        content = read_json(path)
        provenance = content.get("provenance") if isinstance(content, dict) else None
        if isinstance(provenance, dict):
            schema_id = provenance.get("artifact_type")
        elif relative == "claims":
            schema_id = "claim"
        else:
            schema_id = os.path.basename(path)[:-len(".json")]
        found.append((path, schema_id))
    return found


def rehash(artifact):
    artifact["provenance"]["content_hash"] = content_hash(artifact)
    return artifact


def neon(name):
    return read_json(os.path.join(paths.TITLES, "neon-drift", f"{name}.json"))


def schema_keywords():
    """Every keyword used anywhere in core/artifacts/**, walking only schema positions."""
    maps = {"properties", "patternProperties", "$defs", "dependentSchemas"}
    single = {"items", "not", "additionalProperties", "if", "then", "else", "contains",
              "propertyNames", "unevaluatedProperties", "unevaluatedItems", "contentSchema"}
    lists = {"allOf", "anyOf", "oneOf", "prefixItems"}
    used = set()

    def walk(schema):
        if not isinstance(schema, dict):
            return
        for key, value in schema.items():
            used.add(key)
            if key in maps and isinstance(value, dict):
                for sub in value.values():
                    walk(sub)
            elif key in single:
                walk(value)
            elif key in lists and isinstance(value, list):
                for sub in value:
                    walk(sub)

    for path in SCHEMA_FILES:
        walk(read_json(path))
    return used


# -- mutation corpus (also the ajv differential's input) ---------------------------------

def _nodes(value, pointer=""):
    yield pointer, value
    if isinstance(value, dict):
        for key in sorted(value):
            yield from _nodes(value[key], js.pointer_join(pointer, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _nodes(item, js.pointer_join(pointer, index))


def _set(document, pointer, value):
    if pointer == "":
        return value
    tokens = [t.replace("~1", "/").replace("~0", "~") for t in pointer[1:].split("/")]
    node = document
    for token in tokens[:-1]:
        node = node[int(token)] if isinstance(node, list) else node[token]
    last = tokens[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value
    return document


def _delete(document, pointer):
    tokens = [t.replace("~1", "/").replace("~0", "~") for t in pointer[1:].split("/")]
    node = document
    for token in tokens[:-1]:
        node = node[int(token)] if isinstance(node, list) else node[token]
    if isinstance(node, list):
        del node[int(tokens[-1])]
    else:
        del node[tokens[-1]]
    return document


def _variants(value):
    if isinstance(value, bool):
        return [not value, 1, "true"]
    if isinstance(value, int):
        return [-1, 0, 10 ** 9, 0.5, "7", True]
    if isinstance(value, float):
        return [-1.5, 2.0, 1e9 + 0.5, "0.5"]
    if isinstance(value, str):
        return [value + "\n", "", "NOT a valid VALUE!", 42, value.upper(), None,
                "2026-02-30T00:00:00Z", "sha256:" + "0" * 63, value + " "]
    if isinstance(value, list):
        extra = [value + value[:1], [], value + [1]] if value else [[1], [None]]
        return extra + [{"not": "a list"}]
    if isinstance(value, dict):
        return [dict(value, zz_unexpected=1), {}, [value]]
    return [0, "null"]


def mutations(seed_document, count, rng):
    """Deterministic mutants of a document: value swaps, deletions, additions."""
    nodes = list(_nodes(seed_document))
    produced = []
    for _ in range(count):
        pointer, value = nodes[rng.randrange(len(nodes))]
        choice = rng.random()
        mutant = copy.deepcopy(seed_document)
        if pointer and choice < 0.25:
            mutant = _delete(mutant, pointer)
            label = f"delete {pointer}"
        else:
            options = _variants(value)
            replacement = options[rng.randrange(len(options))]
            mutant = _set(mutant, pointer, copy.deepcopy(replacement))
            label = f"set {pointer or '/'} = {json.dumps(replacement)[:40]}"
        produced.append((label, mutant))
    return produced


# -- 1. schemas --------------------------------------------------------------------------

class SchemaCompilation(unittest.TestCase):
    def test_every_keyword_the_schemas_use_is_implemented(self):
        used = schema_keywords()
        unknown = sorted(k for k in used if k not in js.SUPPORTED_KEYWORDS
                         and k not in js.ANNOTATION_KEYWORDS and not k.startswith("x-"))
        self.assertEqual(unknown, [], "keywords the validator would refuse")
        # Sanity: the inventory really walked the schemas.
        for keyword in ("$ref", "if", "then", "oneOf", "prefixItems", "propertyNames",
                        "uniqueItems", "pattern", "format"):
            self.assertIn(keyword, used)

    def test_every_schema_compiles(self):
        for path in SCHEMA_FILES:
            with self.subTest(schema=os.path.relpath(path, ROOT)):
                js.Validator(read_json(path), REGISTRY)  # raises SchemaError on failure

    def test_every_top_level_schema_has_a_contract(self):
        schemas = load_schemas()
        for path in glob.glob(os.path.join(paths.ARTIFACTS, "*.schema.json")):
            stem = os.path.basename(path)[:-len(".schema.json")]
            self.assertIn(stem, schemas, "x-wgf.id must be the filename stem")
            CONTRACTS.validator(stem)

    def test_an_unimplemented_keyword_is_refused_loudly(self):
        for schema in ({"unevaluatedProperties": False},
                       {"properties": {"a": {"$dynamicRef": "#x"}}},
                       {"definitions": {}},
                       {"items": {"typo_minimum": 1}}):
            with self.subTest(schema=schema), self.assertRaises(js.SchemaError):
                js.Validator(schema)

    def test_annotations_are_accepted(self):
        js.Validator({"title": "t", "description": "d", "$comment": "c", "default": 1,
                      "examples": [1], "deprecated": False, "x-wgf": {"id": "z"}})

    def test_bad_schema_values_are_refused(self):
        for schema in ({"format": "not-a-format"}, {"type": "text"},
                       {"$ref": "#/$defs/missing"}, {"$ref": "./nowhere.schema.json"},
                       {"pattern": "(unclosed"}, {"pattern": "\\p{L}"},
                       {"minItems": -1}, {"multipleOf": 0},
                       {"$schema": "http://json-schema.org/draft-07/schema#"}):
            with self.subTest(schema=schema), self.assertRaises(js.SchemaError):
                js.Validator(schema)


# -- 2. instances ------------------------------------------------------------------------

class WorkspaceInstances(unittest.TestCase):
    def test_the_workspace_holds_the_worked_example(self):
        types = {schema_id for _, schema_id in workspace_instances()}
        self.assertTrue({"claim", "opportunity", "evaluation", "title-strategy", "game-design",
                         "prototype-report", "decision-record", "state"} <= types, types)

    def test_every_workspace_artifact_validates_against_its_schema(self):
        for path, schema_id in workspace_instances():
            with self.subTest(instance=os.path.relpath(path, ROOT), schema=schema_id):
                self.assertTrue(os.path.exists(schema_path(schema_id)),
                                f"no schema named {schema_id}")
                errors = validator_for(schema_id).iter_errors(read_json(path))
                self.assertEqual([str(e) for e in errors], [])

    def test_every_workspace_artifact_passes_its_contract(self):
        for path, schema_id in workspace_instances():
            if schema_id in CONTRACTS.schemas:
                with self.subTest(instance=os.path.relpath(path, ROOT)):
                    self.assertEqual(CONTRACTS(schema_id, read_json(path)), [])

    def test_the_worked_example_lineage_closes(self):
        """Every pin in workspace/ names an artifact that is there, at the pinned hash."""
        by_id = {}
        for path, _ in workspace_instances():
            content = read_json(path)
            if isinstance(content.get("provenance"), dict):
                by_id[content["provenance"]["artifact_id"]] = content
        self.assertGreaterEqual(len(by_id), 6)
        for artifact in by_id.values():
            upstream = [by_id[pin["artifact_id"]] for pin in artifact["provenance"]["inputs"]]
            with self.subTest(artifact=artifact["provenance"]["artifact_id"]):
                self.assertEqual(check_lineage(artifact, upstream), [])

    def test_every_reference_file_validates_against_its_shared_schema(self):
        self.assertGreaterEqual(len(REFERENCE_FILES), 3)
        for path, schema_id in REFERENCE_FILES:
            with self.subTest(reference=os.path.relpath(path, ROOT)):
                with open(path, encoding="utf-8") as handle:
                    document = load_yaml(handle.read())
                errors = validator_for(schema_id).iter_errors(document)
                self.assertEqual([str(e) for e in errors], [])


# -- 3. validator semantics --------------------------------------------------------------

def errors_of(schema, instance, registry=None):
    return js.Validator(schema, registry).iter_errors(instance)


class ValidatorSemantics(unittest.TestCase):
    def assertValid(self, schema, instance):
        self.assertEqual([str(e) for e in errors_of(schema, instance)], [], instance)

    def assertInvalid(self, schema, instance, pointer=None, keyword=None):
        errors = errors_of(schema, instance)
        self.assertTrue(errors, f"{instance!r} should fail {schema}")
        if pointer is not None:
            self.assertIn(pointer, [e.pointer for e in errors])
        if keyword is not None:
            self.assertIn(keyword, [e.keyword for e in errors])
        return errors

    def test_types(self):
        self.assertValid({"type": "integer"}, 3)
        self.assertValid({"type": "integer"}, 3.0)  # JSON Schema: 3.0 is an integer
        self.assertInvalid({"type": "integer"}, 3.5, "", "type")
        self.assertInvalid({"type": "integer"}, True, "", "type")
        self.assertInvalid({"type": "number"}, False, "", "type")
        self.assertInvalid({"type": "number"}, float("nan"), "", "type")
        self.assertValid({"type": ["string", "null"]}, None)
        self.assertInvalid({"type": ["string", "null"]}, 0)
        self.assertInvalid({"type": "object"}, [], "", "type")
        self.assertInvalid({"type": "array"}, (1, 2), "", "type")

    def test_enum_and_const_use_json_equality(self):
        self.assertValid({"enum": [1, "a"]}, 1.0)
        self.assertInvalid({"enum": [1, "a"]}, True, "", "enum")
        self.assertInvalid({"const": False}, 0, "", "const")
        self.assertValid({"const": {"a": [1, {"b": None}]}}, {"a": [1.0, {"b": None}]})

    def test_nested_required_and_additional_properties_point_at_the_value(self):
        schema = {"type": "object", "properties": {"a": {
            "type": "object", "required": ["b"], "additionalProperties": False,
            "properties": {"b": {"type": "string"}}}}}
        errors = self.assertInvalid(schema, {"a": {"c": 1}})
        self.assertEqual([(e.pointer, e.keyword) for e in errors],
                         [("/a", "required"), ("/a/c", "additionalProperties")])
        self.assertIn("missing required b", str(errors[0]))
        self.assertIn("not in the schema", str(errors[1]))

    def test_pointer_escaping(self):
        errors = self.assertInvalid(
            {"additionalProperties": {"type": "string"}}, {"a/b~c": 1})
        self.assertEqual(errors[0].pointer, "/a~1b~0c")

    def test_pattern_follows_ecma_not_python(self):
        schema = {"type": "string", "pattern": "^[a-z]+$"}
        self.assertValid(schema, "abc")
        # Python's `$` matches before a trailing newline; ECMA's (and ajv's) does not.
        self.assertInvalid(schema, "abc\n", "", "pattern")
        # Python's \d matches any Unicode digit; ECMA's only 0-9.
        self.assertInvalid({"pattern": "^\\d+$"}, "٣٤", "", "pattern")
        self.assertValid({"pattern": "^\\d+$"}, "34")
        # Patterns are unanchored.
        self.assertValid({"pattern": "b"}, "abc")
        self.assertValid({"patternProperties": {"^x-": {"type": "integer"}},
                          "additionalProperties": False}, {"x-a": 1})
        self.assertInvalid({"patternProperties": {"^x-": {"type": "integer"}},
                            "additionalProperties": False}, {"y": 1}, "/y")

    def test_formats_are_asserted(self):
        schema = {"type": "string", "format": "date-time"}
        for good in ("2026-09-03T14:00:00Z", "2026-09-03T14:00:00.123+05:30",
                     "2024-02-29t00:00:00z", "2026-09-03 14:00:00Z"):
            self.assertValid(schema, good)
        for bad in ("2026-02-30T00:00:00Z", "2026-09-03", "2026-09-03T25:00:00Z",
                    "2026-09-03T14:00:00", "yesterday", "2026-09-03T14:00:00Z\n"):
            self.assertInvalid(schema, bad, "", "format")
        self.assertValid({"format": "date"}, "2026-09-03")
        self.assertInvalid({"format": "date"}, "2026-13-01", "", "format")
        self.assertValid({"format": "email"}, "qa@example.com")
        self.assertInvalid({"format": "email"}, "not-an-email", "", "format")
        self.assertValid({"format": "uri"}, "https://example.com/a?b=c")
        self.assertInvalid({"format": "uri"}, "/relative/path", "", "format")
        self.assertValid({"format": "date-time"}, 5)  # format applies to strings only

    def test_numbers(self):
        self.assertInvalid({"minimum": 0}, -1, "", "minimum")
        self.assertValid({"maximum": 0.6}, 0.6)
        self.assertInvalid({"exclusiveMaximum": 1}, 1, "", "exclusiveMaximum")
        self.assertInvalid({"exclusiveMinimum": 0}, 0, "", "exclusiveMinimum")
        self.assertValid({"multipleOf": 0.1}, 0.3)  # decimal, not binary, arithmetic
        self.assertInvalid({"multipleOf": 2}, 3, "", "multipleOf")

    def test_strings_count_code_points(self):
        self.assertValid({"maxLength": 1}, "\U0001F600")
        self.assertInvalid({"minLength": 2}, "a", "", "minLength")

    def test_arrays(self):
        self.assertInvalid({"minItems": 1}, [], "", "minItems")
        self.assertInvalid({"maxItems": 1}, [1, 2], "", "maxItems")
        self.assertInvalid({"uniqueItems": True}, [{"a": 1}, {"a": 1.0}], "", "uniqueItems")
        self.assertValid({"uniqueItems": True}, [1, True])
        pair = {"prefixItems": [{"type": "number"}, {"type": "string"}], "items": False}
        self.assertValid(pair, [1, "a"])
        self.assertInvalid(pair, ["a", "a"], "/0", "type")
        self.assertInvalid(pair, [1, "a", 2], "/2", "false")
        self.assertInvalid({"items": {"type": "string"}}, ["a", 1], "/1")
        self.assertValid({"contains": {"const": 2}, "minContains": 2}, [2, 1, 2])
        self.assertInvalid({"contains": {"const": 2}}, [1], "", "contains")
        self.assertInvalid({"contains": {"const": 2}, "maxContains": 1}, [2, 2], "",
                           "maxContains")

    def test_objects(self):
        self.assertInvalid({"minProperties": 1}, {}, "", "minProperties")
        self.assertInvalid({"dependentRequired": {"a": ["b"]}}, {"a": 1}, "",
                           "dependentRequired")
        self.assertValid({"dependentRequired": {"a": ["b"]}}, {"b": 1})
        self.assertInvalid({"maxProperties": 1}, {"a": 1, "b": 2}, "", "maxProperties")
        dependent = {"dependentSchemas": {"a": {"required": ["c"]}}}
        self.assertInvalid(dependent, {"a": 1}, "", "required")
        self.assertValid(dependent, {"b": 1})
        names = {"propertyNames": {"pattern": "^[a-z-]+$"}}
        self.assertValid(names, {"ok-name": 1})
        self.assertInvalid(names, {"Bad": 1}, "", "propertyNames")

    def test_composition_and_conditionals(self):
        one = {"oneOf": [{"type": "integer"}, {"minimum": 0}]}
        self.assertValid(one, -1)
        self.assertInvalid(one, 1, "", "oneOf")  # both match
        self.assertInvalid({"anyOf": [{"type": "string"}, {"type": "null"}]}, 1, "", "anyOf")
        self.assertInvalid({"not": {"type": "string"}}, "x", "", "not")
        self.assertInvalid({"allOf": [{"minimum": 0}, {"maximum": 1}]}, 2, "", "maximum")
        conditional = {"if": {"properties": {"tier": {"const": "hypothesis"}},
                              "required": ["tier"]},
                       "then": {"properties": {"confidence": {"maximum": 0.6}}},
                       "else": {"required": ["evidence"]}}
        self.assertValid(conditional, {"tier": "hypothesis", "confidence": 0.5})
        self.assertInvalid(conditional, {"tier": "hypothesis", "confidence": 0.9},
                           "/confidence", "maximum")
        self.assertInvalid(conditional, {"tier": "observed"}, "", "required")

    def test_one_of_reports_the_closest_alternative(self):
        schema = {"oneOf": [{"type": "string"},
                            {"type": "object", "required": ["left"],
                             "properties": {"left": {"type": "string"}}}]}
        errors = self.assertInvalid(schema, {"left": 3})
        self.assertIn("closest is #1", errors[0].message)
        self.assertIn("/left", [e.pointer for e in errors])

    def test_refs_resolve_locally_relatively_and_by_id(self):
        registry = load_registry()
        local = {"$defs": {"n": {"type": "integer"}}, "$ref": "#/$defs/n"}
        self.assertEqual(len(errors_of(local, "x")), 1)
        relative = {"$id": "https://webgamefactory.dev/schemas/artifacts/probe.schema.json",
                    "$ref": "./shared/provenance.schema.json#/$defs/hash"}
        self.assertEqual(errors_of(relative, "sha256:" + "a" * 64, registry), [])
        self.assertEqual(len(errors_of(relative, "md5:x", registry)), 1)
        absolute = {"$ref": "https://webgamefactory.dev/schemas/artifacts/shared/"
                            "criteria-expression.schema.json#/$defs/expression"}
        self.assertEqual(errors_of(absolute, {"left": "a", "op": "gt", "right": 1},
                                   registry), [])
        self.assertTrue(errors_of(absolute, {"left": "a", "op": "bigger"}, registry))
        # $ref applies alongside its siblings (2020-12), not instead of them.
        sibling = {"$defs": {"s": {"type": "string"}}, "$ref": "#/$defs/s", "minLength": 3}
        self.assertEqual(len(errors_of(sibling, "ab")), 1)

    def test_recursive_refs_follow_the_instance(self):
        registry = load_registry()
        expression = {"$ref": "https://webgamefactory.dev/schemas/artifacts/shared/"
                              "criteria-expression.schema.json#/$defs/expression"}
        deep = {"left": "a", "op": "exists"}
        for _ in range(30):
            deep = {"not": deep}
        self.assertEqual(errors_of(expression, deep, registry), [])
        both = {"all_of": [{"left": "a", "op": "eq", "right": 1, "right_path": "b"}]}
        self.assertTrue(errors_of(expression, both, registry))

    def test_errors_are_deterministic(self):
        design = neon("game-design")
        broken = copy.deepcopy(design)
        broken["zz"] = 1
        broken["aa"] = 2
        broken["session"] = "x"
        del broken["provenance"]["status"]
        first = [str(e) for e in validator_for("game-design").iter_errors(broken)]
        reordered = dict(reversed(list(broken.items())))
        second = [str(e) for e in validator_for("game-design").iter_errors(reordered)]
        self.assertEqual(first, second)
        self.assertEqual(len(first), 4)
        for error in validator_for("game-design").iter_errors(broken):
            self.assertTrue(error.pointer == "" or error.pointer.startswith("/"))
            self.assertTrue(error.schema_path.startswith("#"))


# -- 4. the contract ---------------------------------------------------------------------

class ContractRejections(unittest.TestCase):
    """ArtifactContracts on the worked example's game-design, broken one way at a time.

    Each mutant is re-hashed, so the ONLY thing wrong with it is the thing under test."""

    def setUp(self):
        self.valid = neon("game-design")

    def rejected(self, mutate, artifact_type="game-design", rehash_it=True):
        broken = copy.deepcopy(self.valid)
        mutate(broken)
        if rehash_it:
            rehash(broken)
        problems = CONTRACTS(artifact_type, broken)
        self.assertTrue(problems, "should have been rejected")
        return problems

    def test_the_valid_artifact_is_accepted(self):
        self.assertEqual(CONTRACTS("game-design", self.valid), [])

    def test_wrong_type(self):
        problems = self.rejected(lambda d: d["session"].update(target_seconds="ninety"))
        self.assertEqual(problems,
                         ["game-design: /session/target_seconds: expected number, got string"])

    def test_bad_enum(self):
        problems = self.rejected(lambda d: d["provenance"].update(status="approved"))
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("game-design: /provenance/status: "))
        self.assertIn("is not one of", problems[0])

    def test_missing_nested_required(self):
        problems = self.rejected(lambda d: d["provenance"]["produced_by"].pop("role"))
        self.assertEqual(problems, ["game-design: /provenance/produced_by: missing required role"])

    def test_extra_property_where_forbidden(self):
        problems = self.rejected(lambda d: d["session"].update(surprise=True))
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("game-design: /session/surprise: "))

    def test_bad_format(self):
        problems = self.rejected(lambda d: d["provenance"].update(produced_at="yesterday"))
        self.assertEqual(problems, ['game-design: /provenance/produced_at: "yesterday" is not '
                                    'a valid date-time'])

    def test_bad_pattern_on_a_pin(self):
        problems = self.rejected(
            lambda d: d["provenance"]["inputs"][0].update(content_hash="sha256:XYZ"))
        self.assertTrue(problems[0].startswith("game-design: /provenance/inputs/0/content_hash"))

    def test_missing_artifact(self):
        self.assertEqual(CONTRACTS("game-design", None),
                         ["game-design: content must be a JSON object"])
        self.assertIn("no contract", CONTRACTS("not-a-type", self.valid)[0])
        problems = self.rejected(lambda d: d.pop("provenance"), rehash_it=False)
        self.assertEqual(problems, ["game-design: /: missing required provenance"])

    def test_malformed(self):
        for content in (["a", "list"], "text", 7, True):
            self.assertEqual(CONTRACTS("game-design", content),
                             ["game-design: content must be a JSON object"])
        nan = copy.deepcopy(self.valid)
        nan["session"]["target_seconds"] = float("nan")
        self.assertEqual(CONTRACTS("game-design", nan),
                         ["game-design: /session/target_seconds: not JSON - nan is not a "
                          "JSON number"])
        for bad, reason in ((float("inf"), "inf"), ({1, 2}, "set"), (b"x", "bytes"),
                            ((1, 2), "tuple"), (object(), "object")):
            weird = copy.deepcopy(self.valid)
            weird["session"]["x"] = bad
            with self.subTest(value=reason):
                problems = CONTRACTS("game-design", weird)
                self.assertEqual(len(problems), 1)
                self.assertIn("not JSON", problems[0])
        keyed = copy.deepcopy(self.valid)
        keyed["session"][3] = "int key"
        self.assertIn("is not a string", CONTRACTS("game-design", keyed)[0])

    def test_hash_mismatch(self):
        edited = copy.deepcopy(self.valid)
        edited["title_id"] = "something-else"
        self.assertEqual(len(CONTRACTS("game-design", edited)), 1)
        self.assertIn("/provenance/content_hash: does not reproduce",
                      CONTRACTS("game-design", edited)[0])

    def test_artifact_type_mismatch(self):
        wrong = copy.deepcopy(self.valid)
        wrong["provenance"]["artifact_type"] = "title-strategy"
        rehash(wrong)
        self.assertIn("/provenance/artifact_type: is 'title-strategy'",
                      CONTRACTS("game-design", wrong)[0])

    def test_diagnostics_are_capped_but_keep_integrity(self):
        broken = copy.deepcopy(self.valid)
        for index in range(40):
            broken[f"extra_{index:02d}"] = index
        broken["title_id"] = "edited-after-hashing"  # the hash no longer reproduces
        problems = CONTRACTS("game-design", broken)
        self.assertEqual(len(problems), MAX_PROBLEMS + 1)
        self.assertTrue(problems[-1].startswith("... and "))
        self.assertTrue(any("does not reproduce" in p for p in problems))
        self.assertEqual(len(CONTRACTS.problems("game-design", broken)), 41)

    def test_untyped_artifacts_must_be_json(self):
        contracts = ArtifactContracts(untyped=["loose"])
        self.assertEqual(contracts("loose", {"a": 1}), [])
        self.assertEqual(len(contracts("loose", {})), 1)
        self.assertIn("not a JSON number", contracts("loose", {"a": math.inf})[0])

    def test_every_schematized_type_rejects_an_empty_object(self):
        for artifact_type in CONTRACTS.schemas:
            with self.subTest(artifact_type=artifact_type):
                self.assertTrue(any("missing required" in p
                                    for p in CONTRACTS(artifact_type, {})))


# -- 5. lineage --------------------------------------------------------------------------

class Lineage(unittest.TestCase):
    def setUp(self):
        self.strategy = neon("title-strategy")
        self.design = neon("game-design")
        self.report = neon("prototype-report")

    def test_matching_lineage_passes_in_every_accepted_shape(self):
        pin = self.strategy["provenance"]
        self.assertEqual(check_lineage(self.design, {"title-strategy": self.strategy}), [])
        self.assertEqual(check_lineage(self.design, [self.strategy]), [])
        self.assertEqual(check_lineage(self.design, [{
            "artifact_type": "title-strategy", "artifact_id": pin["artifact_id"],
            "content_hash": pin["content_hash"]}]), [])
        ref = ArtifactRef(id="title-strategy", type="title-strategy", version=1,
                          location="x", checksum="y", content_hash=pin["content_hash"])
        self.assertEqual(check_lineage(self.design, {"title-strategy": ref}), [])
        self.assertEqual(check_lineage(self.report, [self.strategy, self.design]), [])

    def test_a_pin_to_a_different_version_is_a_mismatch(self):
        newer = copy.deepcopy(self.strategy)
        newer["positioning"] = "Rewritten after the design was made."
        rehash(newer)
        problems = check_lineage(self.design, {"title-strategy": newer})
        self.assertEqual(len(problems), 1)
        self.assertIn("/provenance/inputs/0: pins title-strategy at", problems[0])
        self.assertIn(newer["provenance"]["content_hash"], problems[0])

    def test_a_consumed_input_that_is_not_pinned(self):
        design = copy.deepcopy(self.design)
        design["provenance"]["inputs"] = []
        problems = check_lineage(design, [self.strategy])
        self.assertEqual(problems, [
            "lineage: /provenance/inputs: does not pin consumed title-strategy "
            f"({self.strategy['provenance']['content_hash']})"])

    def test_a_stale_extra_pin_of_a_consumed_type(self):
        design = copy.deepcopy(self.design)
        stale = dict(design["provenance"]["inputs"][0], content_hash="sha256:" + "0" * 64)
        design["provenance"]["inputs"].append(stale)
        problems = check_lineage(design, [self.strategy])
        self.assertEqual(len(problems), 1)
        self.assertIn("/provenance/inputs/1: pins title-strategy", problems[0])
        self.assertIn("did not consume", problems[0])

    def test_a_pin_with_the_wrong_artifact_id(self):
        design = copy.deepcopy(self.design)
        design["provenance"]["inputs"][0]["artifact_id"] = \
            "wgf:title-strategy:someone-else:20260101-01"
        problems = check_lineage(design, [self.strategy])
        self.assertEqual(len(problems), 1)
        self.assertIn("/provenance/inputs/0/artifact_id", problems[0])

    def test_unverifiable_entries_are_left_alone(self):
        # prototype-report also pins game-design; checking against strategy alone is fine.
        self.assertEqual(check_lineage(self.report, [self.strategy]), [])
        # Consumed artifacts without a content hash (untyped, claims) cannot be pinned.
        self.assertEqual(check_lineage(self.design, {"example": {"topic": "x"}}), [])

    def test_no_provenance(self):
        self.assertEqual(check_lineage({"a": 1}, []),
                         ["lineage: artifact has no provenance object"])
        broken = copy.deepcopy(self.design)
        broken["provenance"]["inputs"] = "none"
        self.assertEqual(check_lineage(broken, []),
                         ["lineage: /provenance/inputs is not an array"])


# -- 6. mock outputs ---------------------------------------------------------------------

class MockOutputs(unittest.TestCase):
    """Everything a --mock run emits is valid under the full validator and its lineage
    closes against what each producing step consumed - including the fail/loop path."""

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-core-contracts-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        config = FactoryConfig({"steps": {"modules": []}, "storage": {"fsync": False}})
        self.api = WorkflowAPI(config=config, store_dir=os.path.join(self.scratch, "store"))

    def audit(self, state):
        by_ref = {}
        for versions in state.artifacts.values():
            for ref in versions:
                by_ref[f"{ref.id}@v{ref.version}"] = ref
        seen = set()
        for versions in state.artifacts.values():
            for ref in versions:
                content = self.api.store.read_artifact(state.run_id, ref)
                seen.add(ref.type)
                with self.subTest(artifact=f"{ref.id}@v{ref.version}"):
                    self.assertEqual(CONTRACTS.problems(ref.type, content), [])
                    self.assertEqual(content_hash(content), ref.content_hash)
            # The newest version was built from what the producer consumed last.
            newest = versions[-1]
            consumed = [by_ref[key] for key in state.steps[newest.produced_by].consumed]
            content = self.api.store.read_artifact(state.run_id, newest)
            with self.subTest(lineage=newest.id):
                self.assertEqual(check_lineage(content, consumed), [])
        return seen

    def test_a_full_mock_run_emits_only_valid_artifacts(self):
        state = self.api.run(RunRequest(mock=True, project_id="contract-probe"))
        self.assertEqual(state.status, RunStatus.COMPLETED)
        seen = self.audit(state)
        declared = {t for step in self.api.definition().steps for t in step.outputs}
        self.assertEqual(seen, declared)

    def test_the_verify_fail_loop_emits_only_valid_artifacts(self):
        state = self.api.run(RunRequest(mock=True, project_id="contract-probe",
                                        mock_plan={"verify": ["fail", "pass"]}))
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.audit(state)
        self.assertGreaterEqual(len(state.artifacts["qa-report"]), 2)


# -- 7. differential against ajv ---------------------------------------------------------

AJV = ["npx", "--yes", "-p", "ajv-cli@5", "-p", "ajv-formats@2", "ajv"]


def _ajv_available():
    if os.environ.get("WGF_SKIP_AJV"):
        return False
    if not shutil.which("npx"):
        return False
    try:
        probe = subprocess.run(AJV + ["help"], capture_output=True, text=True, timeout=120,
                               cwd=ROOT)
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0 and "Validate data file" in probe.stdout


def _seeds():
    """{schema id: [seed documents]} - the worked example, the mock outputs, the reference
    files. Mutants of these are the differential corpus."""
    seeds = {}
    for path, schema_id in workspace_instances():
        seeds.setdefault(schema_id, []).append(read_json(path))
    scratch = tempfile.mkdtemp(prefix="wgf-ajv-seeds-")
    try:
        config = FactoryConfig({"steps": {"modules": []}, "storage": {"fsync": False}})
        api = WorkflowAPI(config=config, store_dir=os.path.join(scratch, "store"))
        state = api.run(RunRequest(mock=True, project_id="ajv-probe",
                                   mock_plan={"verify": ["fail", "pass"]}))
        for versions in state.artifacts.values():
            for ref in versions:
                seeds.setdefault(ref.type, []).append(api.store.read_artifact(state.run_id, ref))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    for path, schema_id in REFERENCE_FILES:
        with open(path, encoding="utf-8") as handle:
            seeds.setdefault(schema_id, []).append(load_yaml(handle.read()))
    return seeds


@unittest.skipUnless(_ajv_available(), "npx/ajv unavailable (offline, or WGF_SKIP_AJV set)")
class AjvDifferential(unittest.TestCase):
    """Same verdict as ajv on every document of a seeded, deterministic mutation corpus.

    One known, deliberate divergence is kept out of the corpus: ajv-formats@2 accepts a
    date-time with no UTC offset, which RFC 3339 does not allow and this validator refuses
    (docs/core-contracts.md)."""

    MUTANTS_PER_SEED = 40

    def test_verdicts_agree_with_ajv(self):
        rng = random.Random(20260924)
        shared_files = sorted(glob.glob(os.path.join(SHARED, "*.schema.json")))
        disagreements = []
        total = 0
        for schema_id, documents in sorted(_seeds().items()):
            path = schema_path(schema_id)
            validator = validator_for(schema_id)
            directory = tempfile.mkdtemp(prefix=f"wgf-ajv-{schema_id}-")
            self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
            corpus = {}
            for number, seed in enumerate(documents):
                corpus[f"seed-{number:02d}"] = ("seed", seed)
                for index, (label, mutant) in enumerate(
                        mutations(seed, self.MUTANTS_PER_SEED, rng)):
                    corpus[f"m-{number:02d}-{index:03d}"] = (label, mutant)
            for name, (_, document) in corpus.items():
                with open(os.path.join(directory, f"{name}.json"), "w",
                          encoding="utf-8") as handle:
                    json.dump(document, handle)
            refs = [f for f in shared_files if os.path.abspath(f) != os.path.abspath(path)]
            command = AJV + ["validate", "-s", path, "-c", "ajv-formats", "--spec=draft2020",
                             "--strict=false", "-d", os.path.join(directory, "*.json")]
            for ref in refs:
                command += ["-r", ref]
            result = subprocess.run(command, capture_output=True, text=True, timeout=300,
                                    cwd=ROOT)
            verdicts = {}
            for line in (result.stdout + result.stderr).splitlines():
                parts = line.rsplit(" ", 1)
                if len(parts) == 2 and parts[1] in ("valid", "invalid") \
                        and parts[0].endswith(".json"):
                    verdicts[os.path.basename(parts[0])[:-len(".json")]] = parts[1] == "valid"
            self.assertEqual(len(verdicts), len(corpus),
                             f"ajv did not judge every {schema_id} file:\n{result.stderr}")
            for name, (label, document) in sorted(corpus.items()):
                total += 1
                ours = not validator.iter_errors(document)
                if ours != verdicts[name]:
                    disagreements.append(f"{schema_id} {name} ({label}): ours="
                                         f"{'valid' if ours else 'invalid'} ajv="
                                         f"{'valid' if verdicts[name] else 'invalid'}")
        self.assertGreater(total, 500)
        self.assertEqual(disagreements, [])


if __name__ == "__main__":
    unittest.main()
