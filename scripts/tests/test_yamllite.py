"""The YAML subset reader, checked against a real YAML implementation.

wgflib/yamllite.py exists because the Factory ships no dependencies and the lifecycle
machines are YAML. A hand-written parser is a liability exactly to the degree that it is
untested against the real thing, so this compares it — file by file, over every YAML
document in both repositories — against the `yaml` package already present in
web-game-template's node_modules.

If web-game-template is not checked out, or its dependencies are not installed, the
differential test skips and only the unit vectors run. That is a real reduction in
confidence and is why the skip says so rather than passing quietly.

Run from the web-game-factory repository root:

    python -m unittest discover scripts/tests
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import pinned_template  # noqa: E402

_PINNED, _PINNED_WHY = (pinned_template.with_dependencies() if shutil.which("node")
                        else (None, "node is not on PATH"))
TEMPLATE = _PINNED or ""
YAML_PACKAGE = os.path.join(TEMPLATE, "node_modules", "yaml")

from wgflib.yamllite import YamlError, load, load_file  # noqa: E402


def repo_yaml_files():
    patterns = [
        os.path.join(ROOT, "core", "**", "*.yaml"),
        os.path.join(ROOT, "workspace", "**", "*.yaml"),
        os.path.join(TEMPLATE, "*.yaml"),
        os.path.join(TEMPLATE, "config", "**", "*.yaml"),
        os.path.join(TEMPLATE, ".github", "workflows", "*.yml"),
    ]
    found = []
    for pattern in patterns:
        found.extend(glob.glob(pattern, recursive=True))
    # pnpm-lock.yaml is generated, enormous, and read by pnpm rather than by anything here.
    # Supporting its shape would widen the subset for no consumer.
    return sorted(
        path
        for path in found
        if os.path.isfile(path) and os.path.basename(path) != "pnpm-lock.yaml"
    )


class Scalars(unittest.TestCase):
    def test_plain_types(self):
        parsed = load(
            "a: 1\nb: 1.5\nc: true\nd: false\ne: null\nf: ~\ng: text\nh: 1.0.0\ni: 72h\n"
        )
        self.assertEqual(
            parsed,
            {"a": 1, "b": 1.5, "c": True, "d": False, "e": None, "f": None,
             "g": "text", "h": "1.0.0", "i": "72h"},
        )

    def test_comments_are_stripped_but_hashes_inside_values_are_not(self):
        self.assertEqual(load("a: 1  # trailing\nb: c#d\n"), {"a": 1, "b": "c#d"})

    def test_quoted_scalars_keep_their_content(self):
        self.assertEqual(load("a: 'x: y'\nb: \"1\"\n"), {"a": "x: y", "b": "1"})

    def test_value_containing_a_colon_without_a_space_is_a_scalar(self):
        # `title:design` is a qualified stage id and must not read as a nested mapping.
        self.assertEqual(load("owns: title:design\n"), {"owns": "title:design"})


class Collections(unittest.TestCase):
    def test_block_sequence_of_mappings(self):
        parsed = load("items:\n  - id: a\n    n: 1\n  - id: b\n    n: 2\n")
        self.assertEqual(parsed, {"items": [{"id": "a", "n": 1}, {"id": "b", "n": 2}]})

    def test_sequence_at_the_same_column_as_its_key(self):
        self.assertEqual(load("items:\n- a\n- b\n"), {"items": ["a", "b"]})

    def test_flow_collections(self):
        parsed = load("a: [1, 2]\nb: {x: 1, y: two}\nc: [{p: 1}, {p: 2}]\nd: []\ne: {}\n")
        self.assertEqual(
            parsed,
            {"a": [1, 2], "b": {"x": 1, "y": "two"},
             "c": [{"p": 1}, {"p": 2}], "d": [], "e": {}},
        )

    def test_key_with_no_value_is_null(self):
        self.assertEqual(load("a:\nb: 1\n"), {"a": None, "b": 1})

    def test_nesting(self):
        parsed = load("a:\n  b:\n    c: [1]\n  d: 2\n")
        self.assertEqual(parsed, {"a": {"b": {"c": [1]}, "d": 2}})


class BlockScalars(unittest.TestCase):
    def test_literal_keeps_line_breaks(self):
        self.assertEqual(load("a: |\n  one\n  two\n"), {"a": "one\ntwo\n"})

    def test_folded_joins_lines(self):
        self.assertEqual(load("a: >\n  one\n  two\n"), {"a": "one two\n"})

    def test_folded_blank_line_becomes_a_break(self):
        self.assertEqual(load("a: >\n  one\n\n  two\n"), {"a": "one\ntwo\n"})

    def test_strip_chomping(self):
        self.assertEqual(load("a: >-\n  one\n"), {"a": "one"})


class OutsideTheSubset(unittest.TestCase):
    def test_anchors_are_refused(self):
        with self.assertRaises(YamlError):
            load("a: &anchor 1\nb: *anchor\n")

    def test_multiple_documents_are_refused(self):
        with self.assertRaises(YamlError):
            load("a: 1\n---\nb: 2\n")

    def test_tabs_in_indentation_are_refused(self):
        with self.assertRaises(YamlError):
            load("a:\n\tb: 1\n")


@unittest.skipUnless(shutil.which("node"), "node is not on PATH")
@unittest.skipUnless(
    _PINNED and os.path.isdir(YAML_PACKAGE),
    _PINNED_WHY or "the pinned web-game-template has no node_modules/yaml",
)
class AgreesWithARealYamlParser(unittest.TestCase):
    """Every YAML file in both repositories, parsed both ways and compared."""

    def js_parse(self, paths):
        script = (
            "const [pkg, ...files] = process.argv.slice(1);"
            "import(pkg).then(async (yaml) => {"
            "  const fs = await import('node:fs');"
            "  const out = files.map((f) => yaml.parse(fs.readFileSync(f, 'utf8')));"
            "  process.stdout.write(JSON.stringify(out));"
            "});"
        )
        package_url = "file:///" + YAML_PACKAGE.replace(os.sep, "/") + "/dist/index.js"
        result = subprocess.run(
            [shutil.which("node"), "-e", script, package_url, *paths],
            capture_output=True,
            text=True,
            # Node writes UTF-8; Python would otherwise decode it with the console codepage,
            # which on Windows turns every em dash into a spurious disagreement.
            encoding="utf-8",
            check=True,
        )
        return json.loads(result.stdout)

    def test_every_yaml_file_parses_identically(self):
        paths = repo_yaml_files()
        self.assertTrue(paths, "no YAML files found to compare")

        expected = self.js_parse(paths)
        disagreements = []

        for path, reference in zip(paths, expected):
            display = os.path.relpath(path, os.path.dirname(ROOT)).replace(os.sep, "/")
            try:
                mine = load_file(path)
            except YamlError as exc:
                disagreements.append(f"{display}: refused to parse: {exc}")
                continue
            # Round-trip through JSON so tuples/ints/floats compare on value, the way the
            # reference parser's output arrives.
            if json.loads(json.dumps(mine)) != reference:
                disagreements.append(f"{display}: parsed differently")

        self.assertEqual(
            [], disagreements, "\n" + "\n".join(disagreements) + f"\n({len(paths)} files)"
        )


if __name__ == "__main__":
    unittest.main()
