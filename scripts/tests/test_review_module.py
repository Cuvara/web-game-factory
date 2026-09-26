"""The review module (scripts/wgf_review), unit by unit: the verdict contract, the settings
and the review-report.

The step as a whole - a real reviewer process, the enforced read-only checkout, the routing
of request-changes back to develop - is exercised by test_core_agents and the golden runs.
This file pins the pieces those depend on, where a regression is silent: a verdict the
parser reads charitably is an approval nobody gave, a settings default that drifts changes
what every review is worth, and a report that does not validate stops the run late.

Standard library only. Run from the repository root:

    python -m unittest scripts/tests/test_review_module.py
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from wgf_review import report, settings, verdict  # noqa: E402
from wgf_review.settings import Settings, SettingsError  # noqa: E402
from wgflib import paths  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402

HEAD = "0123456789abcdef0123456789abcdef01234567"
OTHER = "fedcba9876543210fedcba9876543210fedcba98"
NOW = "2026-09-25T10:00:00Z"


def blocker(**overrides):
    item = {"id": "restart-keeps-score", "file": "src/game/state.ts", "line": 42,
            "summary": "restart does not reset the score", "severity": "blocker"}
    item.update(overrides)
    return item


# -- the verdict ---------------------------------------------------------------------------

class VerdictCase(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-review-verdict-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.path = os.path.join(self.scratch, "verdict.json")

    def write(self, data, raw=False):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(data if raw else json.dumps(data))

    def parse(self, data, head=HEAD, raw=False):
        self.write(data, raw)
        return verdict.parse(self.path, head)

    def refused(self, data, fragment, head=HEAD, raw=False):
        parsed, problem = self.parse(data, head, raw)
        self.assertIsNone(parsed, f"accepted: {data!r}")
        self.assertIsNotNone(problem)
        self.assertIn(fragment, problem)
        return problem


class Parse(VerdictCase):
    def test_an_approval_with_no_blockers_is_read(self):
        parsed, problem = self.parse({"verdict": "approve", "commit": HEAD, "blockers": [],
                                      "notes": "clean"})
        self.assertIsNone(problem)
        self.assertEqual(parsed["verdict"], "approve")

    def test_a_request_for_changes_naming_blockers_is_read(self):
        parsed, problem = self.parse({"verdict": "request-changes", "commit": HEAD,
                                      "blockers": [blocker(), blocker(id="b2", file=None)]})
        self.assertIsNone(problem)
        self.assertEqual([b["id"] for b in parsed["blockers"]], ["restart-keeps-score", "b2"])

    def test_line_is_optional(self):
        item = blocker()
        del item["line"]
        parsed, problem = self.parse({"verdict": "request-changes", "commit": HEAD,
                                      "blockers": [item]})
        self.assertIsNone(problem)

    def test_every_severity_the_contract_names_is_accepted(self):
        for severity in verdict.SEVERITIES:
            with self.subTest(severity):
                _, problem = self.parse({"verdict": "request-changes", "commit": HEAD,
                                         "blockers": [blocker(severity=severity)]})
                self.assertIsNone(problem)

    def test_approve_and_request_changes_are_the_only_verdicts(self):
        self.assertEqual(verdict.VERDICTS, ("approve", "request-changes"))
        # skipped and no-verdict are the Factory's, never the reviewer's.
        for word in ("skipped", "no-verdict", "APPROVE", "lgtm", None):
            with self.subTest(word):
                self.refused({"verdict": word, "commit": HEAD, "blockers": []},
                             "verdict must be one of")


class Refusals(VerdictCase):
    """A malformed verdict is never read charitably as an approval."""

    def test_no_file(self):
        parsed, problem = verdict.parse(self.path, HEAD)
        self.assertIsNone(parsed)
        self.assertIn("no verdict file", problem)

    def test_a_file_over_one_mebibyte(self):
        self.refused("{" + " " * (1024 * 1024) + "}", "larger than 1 MiB", raw=True)

    def test_not_json_and_not_an_object(self):
        self.refused("approve", "not JSON", raw=True)
        self.refused(["approve"], "must be a JSON object")
        with open(self.path, "wb") as handle:
            handle.write(b"\xff\xfe{}")
        parsed, problem = verdict.parse(self.path, HEAD)
        self.assertIsNone(parsed)
        self.assertIn("cannot be read", problem)

    def test_keys_the_contract_does_not_have(self):
        self.refused({"verdict": "approve", "commit": HEAD, "blockers": [], "score": 9},
                     "keys the contract does not: score")

    def test_missing_keys(self):
        for key in ("verdict", "commit", "blockers"):
            data = {"verdict": "approve", "commit": HEAD, "blockers": []}
            del data[key]
            with self.subTest(key):
                self.refused(data, f"missing {key!r}")

    def test_the_commit_is_the_full_lowercase_sha_under_review(self):
        for commit in (HEAD[:12], HEAD.upper(), 12, None, ""):
            with self.subTest(commit):
                self.refused({"verdict": "approve", "commit": commit, "blockers": []},
                             "full 40-character lowercase sha")
        problem = self.refused({"verdict": "approve", "commit": OTHER, "blockers": []},
                               "verdict is for")
        self.assertIn(OTHER[:12], problem)
        self.assertIn(HEAD[:12], problem)

    def test_notes_must_be_text(self):
        self.refused({"verdict": "approve", "commit": HEAD, "blockers": [], "notes": ["x"]},
                     "notes must be a string")

    def test_an_approval_cannot_list_blockers(self):
        self.refused({"verdict": "approve", "commit": HEAD, "blockers": [blocker()]},
                     "an approval cannot list blockers")

    def test_a_request_for_changes_must_name_a_blocker(self):
        self.refused({"verdict": "request-changes", "commit": HEAD, "blockers": []},
                     "must name at least one blocker")

    def test_blockers_shape(self):
        base = {"verdict": "request-changes", "commit": HEAD}
        cases = [
            ({"blockers": {"id": "x"}}, "blockers must be a list"),
            ({"blockers": ["x"]}, "blockers[0] must be an object"),
            ({"blockers": [blocker(fix="do it")]}, "blockers[0] has keys the contract does not: fix"),
            ({"blockers": [{k: v for k, v in blocker().items() if k != "summary"}]},
             "blockers[0] is missing 'summary'"),
            ({"blockers": [{k: v for k, v in blocker().items() if k != "file"}]},
             "blockers[0] is missing 'file'"),
            ({"blockers": [blocker(id="  ")]}, "blockers[0].id must be a non-empty string"),
            ({"blockers": [blocker(), blocker()]}, "blockers[1].id 'restart-keeps-score' is not unique"),
            ({"blockers": [blocker(file="")]}, "blockers[0].file must be a repository path or null"),
            ({"blockers": [blocker(file=7)]}, "blockers[0].file must be a repository path or null"),
            ({"blockers": [blocker(file="/etc/passwd")]}, "blockers[0].file must be relative"),
            ({"blockers": [blocker(file="src/../../factory/core")]},
             "blockers[0].file must be relative"),
            ({"blockers": [blocker(summary="")]}, "blockers[0].summary must be a non-empty string"),
            ({"blockers": [blocker(severity="nit")]}, "blockers[0].severity must be one of"),
            ({"blockers": [blocker(line=0)]}, "blockers[0].line must be a positive integer"),
            ({"blockers": [blocker(line=True)]}, "blockers[0].line must be a positive integer"),
            ({"blockers": [blocker(line="12")]}, "blockers[0].line must be a positive integer"),
        ]
        for extra, fragment in cases:
            with self.subTest(fragment):
                self.refused(dict(base, **extra), fragment)

    def test_a_whole_build_finding_and_a_null_line_are_accepted(self):
        # `file` null is a finding about the build as a whole; `line` null says what leaving
        # it out says. Neither is read charitably: the verdict is still a request for
        # changes, with every blocker intact.
        data = {"verdict": "request-changes", "commit": HEAD,
                "blockers": [blocker(id="a", file=None), blocker(id="b", line=None),
                             blocker(id="c", line=12)]}
        parsed, problem = self.parse(data)
        self.assertIsNone(problem)
        self.assertEqual([b["id"] for b in parsed["blockers"]], ["a", "b", "c"])

    def test_the_brief_shows_a_whole_build_finding(self):
        whole = [b for b in verdict.CONTRACT["blockers"] if b.get("file") is None]
        self.assertTrue(whole, "the contract example shows only file-anchored findings")
        self.assertNotIn("line", whole[0])


class FromOutput(unittest.TestCase):
    """The last JSON object on a reviewer's stdout (verdict_from: stdout)."""

    VERDICT = {"verdict": "approve", "commit": HEAD, "blockers": []}

    def test_the_whole_output(self):
        text = json.dumps(self.VERDICT)
        self.assertEqual(json.loads(verdict.from_output(f"\n{text}\n")), self.VERDICT)

    def test_the_last_json_fence_after_quoted_code(self):
        # The acceptance-run regression: a ```ts block before the ```json verdict must not
        # pair its closing fence with the verdict's opening one.
        text = ("I looked at the loop.\n```ts\nconst x = {a: 1};\n```\nSo:\n```json\n"
                + json.dumps({"verdict": "approve", "commit": OTHER, "blockers": []})
                + "\n```\nand finally\n```json\n" + json.dumps(self.VERDICT) + "\n```\n")
        self.assertEqual(json.loads(verdict.from_output(text)), self.VERDICT)

    def test_an_untagged_fence(self):
        text = "verdict:\n```\n" + json.dumps(self.VERDICT, indent=2) + "\n```"
        self.assertEqual(json.loads(verdict.from_output(text)), self.VERDICT)

    def test_the_last_line_that_is_an_object(self):
        text = "thinking...\n{\"note\": \"not it\"}\nmore text\n" + json.dumps(self.VERDICT)
        self.assertEqual(json.loads(verdict.from_output(text)), self.VERDICT)

    def test_nothing_usable(self):
        for text in (None, "", "no verdict here", "[1, 2]", "```json\n{broken\n```"):
            with self.subTest(text):
                self.assertIsNone(verdict.from_output(text))

    def test_nothing_is_repaired(self):
        # What comes back is text for parse(), never a fixed-up object.
        text = "```json\n{\"verdict\": \"approve\", \"commit\": \"x\"}\n```"
        self.assertEqual(verdict.from_output(text), "{\"verdict\": \"approve\", \"commit\": \"x\"}")


# -- the settings --------------------------------------------------------------------------

class SettingsResolution(unittest.TestCase):
    def test_defaults_are_no_reviewer_and_the_factorys_own_paths_guarded(self):
        resolved = Settings.resolve({})
        self.assertEqual(resolved.kind, "none")
        self.assertEqual(resolved.argv, [])
        self.assertEqual(resolved.verdict_from, "file")
        self.assertEqual((resolved.timeout, resolved.idle_timeout), (1800.0, 600.0))
        self.assertTrue(resolved.fingerprint_ignored)
        self.assertEqual(resolved.guarded_paths,
                         [os.path.normpath(os.path.join(paths.ROOT, p))
                          for p in ("core", "scripts", "bin", "workspace/config")])
        self.assertEqual(Settings.resolve(None).kind, "none")

    def test_resolution_does_not_mutate_the_defaults(self):
        Settings.resolve({"review": {"reviewer": {"kind": "command", "argv": ["r"]},
                                     "guarded_paths": ["x"]}})
        self.assertEqual(settings.DEFAULTS["reviewer"]["kind"], "none")
        self.assertEqual(settings.DEFAULTS["reviewer"]["argv"], [])
        self.assertEqual(settings.DEFAULTS["guarded_paths"],
                         ["core", "scripts", "bin", "workspace/config"])

    def test_config_merges_into_the_defaults_and_the_step_overrides_config(self):
        config = {"review": {"reviewer": {"kind": "command", "argv": ["rev", "{repo}"],
                                          "verdict_from": "stdout"}}}
        resolved = Settings.resolve(config)
        self.assertEqual((resolved.kind, resolved.argv, resolved.verdict_from),
                         ("command", ["rev", "{repo}"], "stdout"))
        # Keys config did not name keep their defaults: the merge is deep.
        self.assertEqual((resolved.timeout, resolved.idle_timeout), (1800.0, 600.0))

        params = {"reviewer": {"timeout_seconds": 60}, "fingerprint_ignored": False,
                  "not_a_setting": True}
        resolved = Settings.resolve(config, params)
        self.assertEqual((resolved.kind, resolved.timeout), ("command", 60.0))
        self.assertFalse(resolved.fingerprint_ignored)
        self.assertNotIn("not_a_setting", resolved.data)

    def test_an_absolute_guarded_path_is_kept(self):
        outside = os.path.abspath(os.sep + os.path.join("srv", "factory-secrets"))
        resolved = Settings.resolve({"review": {"guarded_paths": [outside, "core/"]}})
        self.assertEqual(resolved.guarded_paths,
                         [os.path.normpath(outside), os.path.join(paths.ROOT, "core")])

    def test_idle_timeout_may_be_turned_off(self):
        resolved = Settings.resolve({"review": {"reviewer": {"idle_timeout_seconds": None}}})
        self.assertIsNone(resolved.idle_timeout)

    def test_unusable_settings_are_refused(self):
        cases = [
            ({"reviewer": {"kind": "agent"}}, "kind must be one of"),
            ({"reviewer": {"kind": "command"}}, "argv must be a non-empty list"),
            ({"reviewer": {"kind": "command", "argv": []}}, "argv must be a non-empty list"),
            ({"reviewer": {"kind": "command", "argv": ["rev", 3]}}, "argv must be a non-empty list"),
            ({"reviewer": {"kind": "command", "argv": "rev {repo}"}}, "argv must be a non-empty list"),
            ({"reviewer": {"verdict_from": "stderr"}}, "verdict_from must be file or stdout"),
            ({"reviewer": {"timeout_seconds": "soon"}}, "timeout_seconds must be a number"),
            ({"reviewer": {"timeout_seconds": 0}}, "timeout_seconds must be positive"),
            ({"reviewer": {"timeout_seconds": None}}, "timeout_seconds must be a number"),
            ({"reviewer": {"idle_timeout_seconds": -1}}, "idle_timeout_seconds must be positive"),
            ({"guarded_paths": "core"}, "guarded_paths must be a list"),
            ({"guarded_paths": ["core", 1]}, "guarded_paths must be a list"),
            ({"fingerprint_ignored": "yes"}, "fingerprint_ignored must be true or false"),
        ]
        for review, fragment in cases:
            with self.subTest(fragment=fragment, review=review):
                with self.assertRaises(SettingsError) as caught:
                    Settings.resolve({"review": review})
                self.assertIn(fragment, str(caught.exception))
        self.assertTrue(issubclass(SettingsError, ValueError))


class CheckoutFor(unittest.TestCase):
    def test_default_is_the_factorys_sibling_directory(self):
        self.assertEqual(Settings.resolve({}).checkout_for("demo-game"),
                         os.path.normpath(os.path.join(paths.ROOT, "..", "demo-game")))

    def test_the_one_checkouts_directory_develop_uses(self):
        # wgflib.checkout: one checkouts directory for every step. The deprecated
        # develop.checkouts is read before review.checkouts, so review can no longer be
        # pointed at another tree than the one develop built in; factory.checkouts wins.
        develop = {"develop": {"checkouts": "games"}}
        self.assertEqual(Settings.resolve(develop).checkout_for("demo"),
                         os.path.join(paths.ROOT, "games", "demo"))
        own = dict(develop, review={"checkouts": "/srv/review"})
        self.assertEqual(Settings.resolve(own).checkout_for("demo"),
                         os.path.join(paths.ROOT, "games", "demo"))
        only_review = {"review": {"checkouts": "/srv/review"}}
        self.assertEqual(Settings.resolve(only_review).checkout_for("demo"),
                         os.path.normpath("/srv/review/demo"))
        unified = dict(own, checkouts="/srv/games")
        self.assertEqual(Settings.resolve(unified).checkout_for("demo"),
                         os.path.normpath("/srv/games/demo"))

    def test_a_name_that_is_not_one_directory_entry_is_refused(self):
        resolved = Settings.resolve({})
        for name in ("..", ".", "a/b", "../factory", "a\\b", "", " demo", "x\0y", None):
            with self.subTest(name=name):
                with self.assertRaises(SettingsError):
                    resolved.checkout_for(name)


# -- the brief and the report --------------------------------------------------------------

class Brief(unittest.TestCase):
    def brief(self, **overrides):
        kwargs = dict(title_id="demo-game", commit=HEAD, baseline=OTHER,
                      design={"core_loop": "merge towers", "scope": {"tiers": {"mvp": [
                          "one level", "restart"]}}},
                      prototype={"proved": [{"question": "does it boot", "verdict": "yes"}]},
                      develop_brief={"review_blockers": [blocker()]},
                      verdict_path="/tmp/run/verdict.json", repo="/games/demo-game")
        kwargs.update(overrides)
        return report.render_brief(**kwargs)

    def test_it_names_the_commit_the_change_and_what_to_fix(self):
        text = self.brief()
        self.assertIn(f"Commit under review: `{HEAD}`", text)
        self.assertIn(f"git diff {OTHER}..{HEAD}", text)
        self.assertIn("Core loop: merge towers", text)
        self.assertIn("- restart", text)
        self.assertIn("- does it boot: yes", text)
        self.assertIn("`restart-keeps-score` (blocker) src/game/state.ts", text)
        self.assertIn(f"`commit` is `{HEAD}`, verbatim", text)

    def test_no_diff_line_without_a_distinct_baseline(self):
        for baseline in (None, HEAD):
            with self.subTest(baseline):
                self.assertNotIn("git diff", self.brief(baseline=baseline))

    def test_the_contract_block_is_the_contract(self):
        text = self.brief()
        block = text.split("```json\n", 1)[1].split("\n```", 1)[0]
        self.assertEqual(json.loads(block), verdict.CONTRACT)

    def test_file_or_stdout(self):
        self.assertIn("Write exactly one JSON object to `/tmp/run/verdict.json`", self.brief())
        text = self.brief(to_stdout=True)
        self.assertIn("Write no file", text)
        self.assertNotIn("/tmp/run/verdict.json", text)

    def test_empty_inputs_render(self):
        text = self.brief(design=None, prototype=None, develop_brief=None, baseline=None)
        self.assertNotIn("## The game", text)
        self.assertNotIn("Blockers the previous review raised", text)

    def test_prompts_carry_their_placeholders(self):
        for placeholder in ("{brief}", "{commit}", "{repo}", "{verdict}"):
            self.assertIn(placeholder, report.PROMPT)
        self.assertNotIn("{verdict}", report.PROMPT_STDOUT)
        self.assertIn("READ-ONLY", report.PROMPT_STDOUT)


class Report(unittest.TestCase):
    PIN = {"artifact_id": "wgf:prototype-report:demo-game:20260925-01",
           "artifact_type": "prototype-report", "content_hash": "sha256:" + "a" * 64}
    ISOLATION = {"checked_paths": 120, "violations": [], "intact": True, "restored": None}

    def build(self, **overrides):
        kwargs = dict(title_id="demo-game", commit=HEAD, baseline=OTHER, verdict="approve",
                      blockers=[], notes="", failure=None,
                      reviewer={"kind": "command", "argv0": "reviewer", "exit_code": 0,
                                "status": "exited", "killed_pids": []},
                      isolation=dict(self.ISOLATION), iteration=1, attempt=1,
                      duration_s=12.34567, timed_out=False, pinned_inputs=[dict(self.PIN)],
                      artifact_seq=3, produced_at=NOW)
        kwargs.update(overrides)
        return report.build_report(**kwargs)

    def assertValid(self, artifact):
        self.assertEqual(ArtifactContracts()("review-report", artifact), [])
        self.assertEqual(artifact["provenance"]["content_hash"], content_hash(artifact))

    def test_every_verdict_the_step_emits_is_schema_valid(self):
        cases = {
            "approve": self.build(),
            "request-changes": self.build(verdict="request-changes", blockers=[blocker()],
                                          notes="one thing"),
            "skipped": self.build(verdict="skipped", reviewer={"kind": "none"},
                                  isolation={"checked_paths": 0, "violations": [],
                                             "intact": True}),
            "no-verdict": self.build(
                verdict="no-verdict", failure={"code": "reviewer-isolation-violation",
                                               "message": "edited src/main.ts",
                                               "retryable": False},
                isolation={"checked_paths": 120, "intact": False, "restored": True,
                           "violations": [{"path": "src/main.ts", "change": "modified",
                                           "scope": "checkout", "sensitive": False}]}),
        }
        for label, artifact in cases.items():
            with self.subTest(label):
                self.assertValid(artifact)
                self.assertEqual(artifact["verdict"], label)

    def test_provenance(self):
        artifact = self.build()
        provenance = artifact["provenance"]
        self.assertEqual(provenance["artifact_id"], "wgf:review-report:demo-game:20260925-03")
        self.assertEqual(provenance["artifact_type"], "review-report")
        self.assertEqual(provenance["schema_version"], report.SCHEMA_VERSION)
        self.assertEqual(provenance["produced_by"], {"role": "architect", "actor": "ai"})
        self.assertEqual(provenance["inputs"], [self.PIN])
        self.assertEqual(provenance["status"], "draft")
        none = self.build(verdict="skipped", reviewer={"kind": "none"})
        self.assertEqual(none["provenance"]["produced_by"]["actor"], "automation")
        # The sequence has two digits in an artifact id; it is clamped, never widened.
        self.assertTrue(self.build(artifact_seq=250)["provenance"]["artifact_id"]
                        .endswith("-99"))

    def test_measured_fields_are_normalised(self):
        artifact = self.build(iteration=0, attempt=-2, duration_s=-5, timed_out=0)
        self.assertEqual((artifact["iteration"], artifact["attempt"], artifact["duration_s"],
                          artifact["timed_out"]), (1, 1, 0.0, False))
        self.assertEqual(self.build()["duration_s"], 12.346)
        self.assertEqual(self.build()["reviewed_at"], NOW)
        self.assertValid(artifact)

    def test_notes_only_when_there_are_some(self):
        self.assertNotIn("notes", self.build(notes=""))
        self.assertNotIn("notes", self.build(notes=None))
        self.assertEqual(self.build(notes="fine")["notes"], "fine")

    def test_the_hash_pins_the_content(self):
        artifact = self.build()
        tampered = json.loads(json.dumps(artifact))
        tampered["verdict"] = "request-changes"
        self.assertNotEqual(content_hash(tampered), artifact["provenance"]["content_hash"])


# -- the subject: which commit a review step reviews ---------------------------------------

HAS_GIT = shutil.which("git") is not None

APPROVER = """
import json, sys
verdict_path, commit = sys.argv[1:3]
with open(verdict_path, "w") as handle:
    json.dump({"verdict": "approve", "commit": commit, "blockers": []}, handle)
"""


class _Logger:
    def info(self, *args, **kwargs):
        pass

    debug = warning = error = info


@unittest.skipUnless(HAS_GIT, "git is not installed")
class Subject(unittest.TestCase):
    """`with: subject` points the same step at develop's commit or the sdk commit on top."""

    def setUp(self):
        import subprocess
        self.scratch = tempfile.mkdtemp(prefix="wgf-review-subject-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.repo = os.path.join(self.scratch, "checkouts", "demo")
        os.makedirs(self.repo)

        def git(*args):
            return subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@e.invalid",
                                   *args], cwd=self.repo, check=True, capture_output=True,
                                  text=True).stdout.strip()

        self.git = git
        git("init", "-q", "-b", "main")
        self.commit("src/main.ts", "export {};\n", "develop")
        self.developed = git("rev-parse", "HEAD")
        self.commit("src/platform/gameplay.ts", "export const sdk = 1;\n",
                    "sdk: integrate\n\nWgf-Sdk-Key: run:sdk:1")
        self.integrated = git("rev-parse", "HEAD")
        self.approver = os.path.join(self.scratch, "approver.py")
        with open(self.approver, "w") as handle:
            handle.write(APPROVER)
        self.run_dir = os.path.join(self.scratch, "run")
        os.makedirs(self.run_dir)

    def commit(self, relative, text, message):
        path = os.path.join(self.repo, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def review(self, subject=None, sdk_commit=None, drop=()):
        import types
        from wgf_review.step import ReviewStep
        from wgflib.workflow.model import ArtifactRef
        from wgflib.workflow.step import StepInputs
        contents = {
            "prototype-report": {"title_id": "demo",
                                 "build_ref": {"commit_sha": self.developed}},
            "sdk-report": {"title_id": "demo", "build_ref": {
                "commit_sha": sdk_commit or self.integrated,
                "base_commit_sha": self.developed}, "platforms": []},
            "scaffold-record": {"title_id": "demo", "repository": {"name": "demo"}},
        }
        refs = {t: ArtifactRef(id=t, type=t, version=1, location=f"artifacts/{t}/v1.json",
                               checksum="sha256:0", schema_version="1.0.0")
                for t in contents if t not in drop}
        inputs = StepInputs(refs, lambda ref: contents[ref.type], [])
        config = {"review": {"checkouts": os.path.join(self.scratch, "checkouts"),
                             "guarded_paths": [],
                             "reviewer": {"kind": "command", "timeout_seconds": 30,
                                          "argv": [sys.executable, self.approver,
                                                   "{verdict}", "{commit}"]}}}
        context = types.SimpleNamespace(config=config, run_dir=self.run_dir, visit=1,
                                        attempt=1, execution=1, logger=_Logger())
        params = {} if subject is None else {"subject": subject}
        step_id = "review" if subject is None else "sdk-review"
        step = ReviewStep(types.SimpleNamespace(id=step_id, type="review", params=params,
                                                outputs=["review-report"], inputs=[]))
        return step.execute(inputs, context)

    def test_the_sdk_subject_reviews_the_sdk_commit_against_the_develop_commit(self):
        result = self.review(subject="sdk-report")
        self.assertEqual(result.outcome, "SUCCESS", result.error)
        report_ = result.artifacts[0].content
        self.assertEqual(report_["reviewed_commit"], self.integrated)
        self.assertEqual(report_["baseline_commit"], self.developed)
        with open(os.path.join(self.run_dir, "review", "sdk-review-1-1.brief.md")) as handle:
            brief = handle.read()
        self.assertIn(f"git diff {self.developed}..{self.integrated}", brief)
        self.assertIn("committed on top of the development commit", brief)

    def test_another_run_in_the_checkout_blocks_the_review(self):
        # wgflib.checkout: the checkout must hold still while it is reviewed.
        from wgflib import checkout
        storage = os.path.join(self.scratch, "store")
        self.run_dir = os.path.join(storage, "workflows", "run-mine")
        os.makedirs(self.run_dir)
        other = checkout.acquire(self.repo, "run-other", storage)
        self.addCleanup(other.release)
        result = self.review(subject="sdk-report")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertIn("run-other", result.message or result.error)
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "review")))
        other.release()
        self.assertEqual(self.review(subject="sdk-report").outcome, "SUCCESS")

    def test_the_default_subject_is_the_develop_commit_which_is_no_longer_head(self):
        # After sdk committed, HEAD is the sdk commit: reviewing develop's commit is refused,
        # which is exactly why sdk-review reviews the sdk commit.
        result = self.review()
        self.assertEqual((result.outcome, result.retryable), ("FAILED", False))
        self.assertIn("prototype-report is for", result.error)

    def test_an_sdk_report_for_another_commit_than_head_is_refused(self):
        result = self.review(subject="sdk-report", sdk_commit=self.developed)
        self.assertEqual((result.outcome, result.retryable), ("FAILED", False))
        self.assertIn("sdk-report is for", result.error)

    def test_a_dirty_tree_blocks_the_sdk_review(self):
        with open(os.path.join(self.repo, "src", "main.ts"), "a") as handle:
            handle.write("// uncommitted\n")
        self.assertEqual(self.review(subject="sdk-report").outcome, "BLOCKED")

    def test_without_an_sdk_report_the_sdk_review_waits(self):
        result = self.review(subject="sdk-report", drop=("sdk-report",))
        self.assertEqual(result.outcome, "WAITING_FOR_INPUT")
        self.assertIn("sdk-report", result.message)

    def test_an_unknown_subject_is_refused(self):
        result = self.review(subject="qa-report")
        self.assertEqual((result.outcome, result.retryable), ("FAILED", False))
        self.assertIn("subject", result.error)



# -- the brief's gameplay lens and design fidelity (F2) ---------------------------------

COMMIT = "a" * 40
DESIGN = {"core_loop": "Dodge, collect, beat the best.",
          "scope": {"tiers": {"mvp": ["Lane switching"]}}}
BUILD_SPEC = {"sections": {
    "rewards": [{"id": "new-best", "feedback": "Best counter bursts; a short fanfare."}],
    "hud": [{"id": "score", "feedback": "Digits roll rather than jump"},
            {"id": "pause-button"}],
    "failure": {"condition": "Touch an obstacle.",
                "feedback": "Hit-stop for 150 ms, screen shake."},
    "tutorial": {"approach": "diegetic", "rationale": "The first rows teach it."},
}, "not_now": [], "omitted": []}
DEV_PLAN = {"milestones": [{"id": "M1"}], "tasks": [
    {"id": "CORE-001", "title": "Boot", "acceptance_criteria": ["Boots through the seam"]},
    {"id": "GAME-001", "title": "Lanes",
     "acceptance_criteria": ["One input moves one lane", "Moves take 120 ms"]}],
    "later": []}


def brief(develop_brief=None, **kwargs):
    args = dict(title_id="demo", commit=COMMIT, baseline="b" * 40, design=DESIGN,
                prototype={}, develop_brief=develop_brief, verdict_path="/tmp/v.json",
                repo="/tmp/repo")
    args.update(kwargs)
    return report.render_brief(**args)


class GameplayLens(unittest.TestCase):
    def test_every_brief_carries_the_lens(self):
        text = brief()
        self.assertIn("### Gameplay lens", text)
        for item in report.GAMEPLAY_LENS:
            self.assertIn(item, text)
        self.assertIn("On an mvp path a failure is a blocker", text)

    def test_the_lens_names_the_defects_players_feel(self):
        lens = " ".join(report.GAMEPLAY_LENS)
        for needle in ("Restart resets everything", "elapsed time", "Pause",
                       "two runs", "data", "allocation", "3 times a second",
                       "user gesture", "@game-over"):
            self.assertIn(needle, lens)

    def test_the_code_checks_and_the_verdict_contract_are_unchanged(self):
        text = brief()
        for needle in ("Defects in the game logic", "tests that assert nothing",
                       "Template rules broken", "Secrets, network calls",
                       "Style preferences are not blockers", "## Your verdict",
                       f"`commit` is `{COMMIT}`, verbatim."):
            self.assertIn(needle, text)
        self.assertEqual(set(verdict.CONTRACT), {"verdict", "commit", "blockers", "notes"})
        self.assertLess(text.index("## Look for"), text.index("### Gameplay lens"))
        self.assertLess(text.index("### Gameplay lens"), text.index("## Your verdict"))


class DesignFidelity(unittest.TestCase):
    def test_the_specified_feedback_and_tasks_are_listed(self):
        text = brief({"build_spec": BUILD_SPEC, "dev_plan": DEV_PLAN})
        self.assertIn("## What the design and plan specified", text)
        for needle in ("rewards `new-best`: Best counter bursts; a short fanfare.",
                       "hud `score`: Digits roll rather than jump",
                       "failure: Hit-stop for 150 ms, screen shake.",
                       "tutorial: diegetic - The first rows teach it.",
                       "`CORE-001` Boot: Boots through the seam",
                       "`GAME-001` Lanes: One input moves one lane; Moves take 120 ms",
                       "design-fidelity blocker"):
            self.assertIn(needle, text)
        self.assertNotIn("pause-button", text)  # a HUD element with no feedback to check
        self.assertLess(text.index("## What the design and plan specified"),
                        text.index("## Look for"))

    def test_only_the_parts_the_brief_carries_are_listed(self):
        text = brief({"build_spec": None, "dev_plan": DEV_PLAN})
        self.assertIn("Development plan tasks", text)
        self.assertNotIn("Feedback and teaching", text)
        text = brief({"build_spec": BUILD_SPEC, "dev_plan": None})
        self.assertIn("Feedback and teaching", text)
        self.assertNotIn("Development plan tasks", text)

    def test_a_brief_from_before_f1_adds_nothing(self):
        for develop_brief in (None, {}, {"review_blockers": []}):
            self.assertNotIn("## What the design and plan specified", brief(develop_brief))



if __name__ == "__main__":
    unittest.main()
