"""The canonical content hash, checked against its specification and against the other
implementation of it.

The differential test is the one that matters. Release artifacts are hashed in the game
repository by web-game-template/scripts/_shared.mjs and workspace artifacts are hashed here;
a gate that pins a release manifest is comparing a digest produced on one side against a
digest produced on the other. Unit vectors prove this implementation is self-consistent.
Only the differential test proves the two agree, which is the property the system needs.

Run from the web-game-factory repository root:

    python -m unittest discover scripts/tests
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
TEMPLATE_SHARED = os.path.join(ROOT, os.pardir, "web-game-template", "scripts", "_shared.mjs")

sys.path.insert(0, SCRIPTS)

from wgflib.hashing import (  # noqa: E402
    CanonicalizationError,
    content_hash,
    stable_stringify,
)


def artifact(**overrides):
    """A minimal artifact shaped like a real one, for hashing."""
    base = {
        "id": "example",
        "provenance": {
            "artifact_id": "wgf:opportunity:opp-001:20260828-01",
            "artifact_type": "opportunity",
            "content_hash": "sha256:" + "0" * 64,
            "inputs": [],
        },
    }
    base.update(overrides)
    return base


class StableStringify(unittest.TestCase):
    def test_object_keys_sort_by_code_point(self):
        self.assertEqual(stable_stringify({"b": 1, "a": 2}), '{"a":2,"b":1}')
        self.assertEqual(stable_stringify({"B": 1, "a": 2}), '{"B":1,"a":2}')

    def test_array_order_is_preserved(self):
        # List order is meaning in an artifact — kill criteria, changelog, ranked shortlist.
        self.assertEqual(stable_stringify(["b", "a"]), '["b","a"]')

    def test_integral_floats_render_as_integers(self):
        # JSON.stringify(12.0) is "12"; repr(12.0) is "12.0". This is the disagreement most
        # likely to bite, because JSON has one number type and Python has two.
        self.assertEqual(stable_stringify(12.0), "12")
        self.assertEqual(stable_stringify(12), "12")
        self.assertEqual(stable_stringify(-0.0), "0")

    def test_decimals_round_trip(self):
        self.assertEqual(stable_stringify(0.62), "0.62")
        self.assertEqual(stable_stringify(0.1), "0.1")

    def test_literals(self):
        self.assertEqual(stable_stringify(None), "null")
        self.assertEqual(stable_stringify(True), "true")
        self.assertEqual(stable_stringify(False), "false")

    def test_strings_escape_like_json_stringify(self):
        self.assertEqual(stable_stringify('a"b'), '"a\\"b"')
        self.assertEqual(stable_stringify("a\nb"), '"a\\nb"')
        self.assertEqual(stable_stringify("a\u0001b"), '"a\\u0001b"')
        # Non-ASCII stays as itself in both implementations.
        self.assertEqual(stable_stringify("tiếng việt"), '"tiếng việt"')

    def test_exponential_notation_raises_rather_than_diverging(self):
        # Python and JavaScript disagree on both the threshold and the exponent format. A
        # wrong digest is silent, so this is refused instead.
        with self.assertRaises(CanonicalizationError):
            stable_stringify(1e-9)

    def test_nan_and_infinity_are_refused(self):
        for value in (float("nan"), float("inf")):
            with self.assertRaises(CanonicalizationError):
                stable_stringify(value)


class ContentHash(unittest.TestCase):
    def test_own_hash_slot_does_not_affect_the_digest(self):
        one = artifact()
        two = artifact()
        two["provenance"]["content_hash"] = "sha256:" + "f" * 64
        self.assertEqual(content_hash(one), content_hash(two))

    def test_key_order_does_not_affect_the_digest(self):
        one = json.loads('{"a":1,"b":2,"provenance":{"content_hash":""}}')
        two = json.loads('{"b":2,"a":1,"provenance":{"content_hash":""}}')
        self.assertEqual(content_hash(one), content_hash(two))

    def test_content_changes_the_digest(self):
        self.assertNotEqual(content_hash(artifact()), content_hash(artifact(id="other")))

    def test_shape_is_the_one_the_schema_requires(self):
        digest = content_hash(artifact())
        self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")

    def test_artifact_without_provenance_is_refused(self):
        # claim has no provenance block by design; callers skip those rather than hash them.
        with self.assertRaises(CanonicalizationError):
            content_hash({"id": "claim-0a01"})


@unittest.skipUnless(shutil.which("node"), "node is not on PATH")
@unittest.skipUnless(os.path.exists(TEMPLATE_SHARED), "web-game-template is not checked out")
class AgreesWithTheGameRepoImplementation(unittest.TestCase):
    """Differential test against web-game-template/scripts/_shared.mjs."""

    def js_hashes(self, paths):
        script = (
            "const [shared, ...files] = process.argv.slice(1);"
            "import(shared).then(async (m) => {"
            "  const fs = await import('node:fs');"
            "  for (const f of files) {"
            "    console.log(m.contentHash(JSON.parse(fs.readFileSync(f, 'utf8'))));"
            "  }"
            "});"
        )
        shared_url = "file:///" + os.path.abspath(TEMPLATE_SHARED).replace(os.sep, "/")
        result = subprocess.run(
            [shutil.which("node"), "-e", script, shared_url, *paths],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return result.stdout.split()

    def assert_agrees(self, artifacts):
        with tempfile.TemporaryDirectory() as workdir:
            paths = []
            for index, value in enumerate(artifacts):
                path = os.path.join(workdir, f"{index}.json")
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(value, handle)
                paths.append(path)
            expected = self.js_hashes(paths)

        for value, js_digest in zip(artifacts, expected):
            self.assertEqual(content_hash(value), js_digest, msg=json.dumps(value))

    def test_agrees_on_constructed_artifacts(self):
        self.assert_agrees(
            [
                artifact(),
                artifact(nested={"z": [1, 2, {"b": False, "a": None}], "a": "x"}),
                artifact(numbers=[0, -1, 12.0, 0.62, 1000000, -0.5]),
                artifact(text='quote " newline \n tab \t unicode tiếng việt ✓'),
                artifact(empties={"list": [], "obj": {}, "null": None, "str": ""}),
                artifact(ordering=["b", "a", "c"]),
            ]
        )

    def test_agrees_on_every_workspace_artifact(self):
        """The real instances, which is what a gate actually pins."""
        workspace = os.path.join(ROOT, "workspace")
        artifacts = []
        for directory, _dirs, files in os.walk(workspace):
            for name in sorted(files):
                if not name.endswith(".json"):
                    continue
                with open(os.path.join(directory, name), encoding="utf-8") as handle:
                    value = json.load(handle)
                if isinstance(value, dict) and isinstance(value.get("provenance"), dict):
                    artifacts.append(value)

        self.assertTrue(artifacts, "no hashable artifacts found under workspace/")
        self.assert_agrees(artifacts)


if __name__ == "__main__":
    unittest.main()
