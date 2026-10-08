"""Store copy grounded in the build (WS-9, docs/quality-gap-audit-2026-10.md section 4).

The two 2026-10 validation listings shipped copy a person had to replace (I-23): it stated a
count the build did not have ("six floating-island courses" beside twelve), its controls
line named touch only while the build also took the mouse and the keyboard, the required
`ru` description was the in-game objective line, the cross-locale check passed a Russian
text because it carried English words, and a subtitle said only the genre. Each is a
regression case here, built from the shapes - never from the games:

  * a count is held to the content-sufficiency report of the SAME build (count-mismatch,
    unmeasured-count at the release tier), never to the design's plan;
  * the controls text names every device the design's actions bind and the probe reported;
  * every required locale is a full description at the release tier, and a non-English
    bullet is grounded on its source's numbers, not on shared English words;
  * a genre-only subtitle is refused;
  * at the release tier the copywriter agent writes; the template is for development runs;
  * a correct multi-locale listing written by the copywriter passes;
  * listing-validation's copy failures go through triage to the copywriter: route
    `listing`, one store-listing pass, the brief carrying the findings.

    python -m unittest scripts.tests.test_listing_build
"""

import copy
import json
import os
import sys
import textwrap
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import test_listing as base  # noqa: E402
from wgf_listing import buildfacts, copywriter, facts as facts_mod, grounding  # noqa: E402
from wgf_listing.step import COPY_DIMENSION  # noqa: E402
from wgf_triage import Routing, normalize  # noqa: E402
from wgf_triage.step import TriageStep  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow import StepOutcome  # noqa: E402
from wgflib.workflow.definition import load_definition  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

REFERENCE = load_file(base.REFERENCE)
COUNTS = REFERENCE["counts"]
RELEASE = {"quality": {"tier": "release", "class": "release"}}
RELEASE_BARS = buildfacts.store_bars("release")


def course_design(units=6):
    """The fixture design, planning `units` courses: what the design said, not the build."""
    design = copy.deepcopy(base.DESIGN)
    design["scope"]["content_units"] = units
    design["scope"]["content_unit_kind"] = "course"
    return design


def sufficiency(commit, *, shipped=12, groups=3, climax=3, tier="release"):
    """A content-sufficiency report of `commit`: what the build measured."""
    names = [f"w{g + 1}" for g in range(groups)]
    return base.seal("content-sufficiency-report", {
        "title_id": "fixture-game", "commit": commit, "measurement_class": "automation-bot",
        "quality_tier": tier, "generation_mode": "authored",
        "checks": [
            {"id": "content.units_shipped", "status": "PASS", "required": True,
             "summary": f"the build ships all {shipped} unit(s) the design owes",
             "measured": {"owed": shipped, "shipped": shipped, "missing": []}},
            {"id": "content.groups", "status": "PASS", "required": True, "summary": "groups",
             "measured": {"build": {"groups": {n: shipped // groups for n in names}, "idle": []},
                          "design": {"groups": {n: shipped // groups for n in names}, "idle": []}}},
            {"id": "content.climax", "status": "PASS", "required": True, "summary": "climax",
             "measured": {"build": {"climax_units": [f"c{i}" for i in range(climax)]},
                          "design": {"climax_units": [f"c{i}" for i in range(climax)]}}},
            {"id": "content.playtime", "status": "SKIPPED", "required": False,
             "summary": "no bar"}],
        "findings": [], "failed": [], "routes": [], "skipped_checks": [], "blocked_reason": None,
        "verdict": "PASS"}, schema_version="1.0.1")


def measured_facts(design=None, strings=None, tier="release", commit="a" * 40, report=None):
    design = design or course_design()
    facts = facts_mod.extract(design, strings=strings or {"en": {"title.heading": "Fixture Game"}})
    facts["quality"] = {"tier": tier, "where": "test", "bars": buildfacts.store_bars(tier)}
    measured = buildfacts.measured_counts(report or sufficiency(commit), design, REFERENCE, commits=[commit])
    if measured is not None:
        facts["measured"] = measured
    return facts


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class ProbeCapture(base.FakeCapture):
    """The fake capture, with the inputs the play probe reported per viewport: the desktop
    viewport took a key and a pointer, the mobile one a pointer."""

    def __call__(self, job, **kw):
        report = super().__call__(job, **kw)
        for viewport in report.get("viewports") or []:
            viewport["inputs"] = ({"pointer": ["switch"]} if viewport.get("mobile")
                                  else {"pointer": ["switch"], "key": ["switch", "pause"]})
        return report


# -- 1. counts -------------------------------------------------------------------------------

class Counts(unittest.TestCase):
    def test_measured_counts_come_from_the_report_of_this_build_only(self):
        design = course_design()
        measured = buildfacts.measured_counts(sufficiency("b" * 40), design, REFERENCE, commits=["b" * 40])
        self.assertEqual({f: c["value"] for f, c in measured["counts"].items()},
                         {"units": 12, "groups": 3, "climax": 3, "modes": 0})
        self.assertEqual(measured["counts"]["units"]["kind"], "course")
        self.assertEqual(measured["source"]["commit"], "b" * 40)
        # Another build's report says nothing about this one.
        self.assertIsNone(buildfacts.measured_counts(sufficiency("c" * 40), design, REFERENCE,
                                                     commits=["b" * 40, "d" * 40]))
        # The development commit the sdk commit sits on is the same build.
        self.assertIsNotNone(buildfacts.measured_counts(sufficiency("d" * 40), design, REFERENCE,
                                                        commits=["b" * 40, "d" * 40]))

    def test_six_courses_beside_twelve_measured_is_refused_in_every_locale(self):
        # I-23: the design planned six courses, the build shipped twelve; the copy said six.
        facts = measured_facts()
        en = {"title": "Fixture Game", "short_description": "Six floating-island courses to roll through.",
              "long_description": "Roll across 3 worlds. Ten gems per course; the last two courses ask for stars.",
              "features": [], "tags": []}
        found = [p for p in grounding.check(en, facts, [], locale="en", counts=COUNTS)
                 if p["code"] == "count-mismatch"]
        self.assertEqual(len(found), 1, found)
        self.assertIn("'Six floating-island courses'", found[0]["message"])
        self.assertIn("the build has 12 course", found[0]["message"])
        self.assertIn("content.units_shipped", found[0]["message"])
        ru = {"title": "Fixture Game", "short_description": "Шесть небесных трасс.",
              "long_description": "Двенадцать уровней в трёх мирах.", "features": [], "tags": []}
        found = [p["message"] for p in grounding.check(ru, facts, [], locale="ru", counts=COUNTS)
                 if p["code"] == "count-mismatch"]
        self.assertEqual(len(found), 1, found)
        self.assertIn("Шесть небесных трасс", found[0])

    def test_a_count_nothing_measured_fails_at_release_and_warns_in_development(self):
        en = {"title": "Fixture Game", "short_description": "Twelve courses.", "long_description": "x",
              "features": [], "tags": []}
        release = facts_mod.extract(course_design())
        release["quality"] = {"tier": "release", "bars": RELEASE_BARS}
        found = buildfacts.count_problems(en, release, COUNTS, locale="en")
        self.assertEqual([(p["code"], p["severity"]) for p in found], [("unmeasured-count", "error")])
        development = facts_mod.extract(course_design())
        found = buildfacts.count_problems(en, development, COUNTS, locale="en")
        self.assertEqual([(p["code"], p["severity"]) for p in found], [("unmeasured-count", "warning")])

    def test_a_cut_feature_is_never_named(self):
        design = course_design()
        design["features"].append({"id": "time-trial", "name": "Time trial", "tier": "optional",
                                   "description": "Race the clock.",
                                   "evaluation": {"decision": "cut", "reason": "no clock UI in scope"}})
        facts = measured_facts(design)
        found = grounding.check({"title": "x", "short_description": "Race in time trial mode.",
                                 "long_description": "y", "features": [], "tags": []}, facts, [],
                                locale="en", counts=COUNTS)
        self.assertIn("excluded-feature", [p["code"] for p in found])
        # The template writer quotes the design, and leaves out a sentence naming it.
        design["build_spec"]["mechanics"][1]["description"] = ("Hits raise the combo. "
                                                               "Time trial races the clock.")
        facts = measured_facts(design)
        copies, _ = copywriter.write_copy(facts, ["en"], REFERENCE)
        self.assertNotIn("time trial", json.dumps(copies["en"]).lower())
        self.assertIn("Hits raise the combo", copies["en"]["long_description"])

    def test_the_template_writes_the_measured_count_and_never_the_planned_one(self):
        design = course_design()
        design["build_spec"]["mechanics"][0]["description"] = ("Six sky courses of lanes to clear. "
                                                               "One tap switches lanes on the beat.")
        facts = measured_facts(design)
        copies, _ = copywriter.write_copy(facts, ["en"], REFERENCE)
        en = copies["en"]
        self.assertNotIn("Six sky courses", json.dumps(en))
        self.assertIn("12 courses across 3 worlds.", en["long_description"])
        self.assertEqual([p for p in grounding.check(en, facts, REFERENCE["claims"], locale="en", counts=COUNTS)
                          if p["severity"] == "error"], [])


# -- 2. controls -----------------------------------------------------------------------------

class Controls(unittest.TestCase):
    def test_a_controls_line_naming_touch_only_misses_the_mouse_and_keyboard(self):
        # The design binds every action on touch, mouse and keyboard.
        facts = measured_facts()
        missing, checkable = buildfacts.controls_problems({"controls": "Touch: tap anywhere."}, facts,
                                                          REFERENCE["controls"], "en")
        self.assertTrue(checkable)
        self.assertEqual(missing, ["mouse", "keyboard"])
        missing, _ = buildfacts.controls_problems(
            {"controls": "Touch: tap. Mouse: click. Keyboard: Space."}, facts, REFERENCE["controls"], "en")
        self.assertEqual(missing, [])
        ru = {"controls": "Касание: нажмите на экран. Мышь: щелчок. Клавиатура: пробел."}
        self.assertEqual(buildfacts.controls_problems(ru, facts, REFERENCE["controls"], "ru"), ([], True))
        # A language with no device words cannot be checked: said so, never passed.
        self.assertEqual(buildfacts.controls_problems({"controls": "x"}, facts, REFERENCE["controls"], "vi"),
                         ([], False))

    def test_a_device_only_the_probe_reported_is_required_and_written(self):
        design = course_design()
        for action in design["build_spec"]["controls"]["actions"]:
            action["keyboard"] = ""
        facts = measured_facts(design)
        self.assertEqual(buildfacts.required_devices(facts), ["touch", "mouse"])
        facts["probe_inputs"] = buildfacts.probe_devices([
            {"mobile": False, "inputs": {"key": ["switch"], "pointer": ["switch"]}},
            {"mobile": True, "inputs": {"pointer": ["switch"]}}])
        self.assertEqual(facts["probe_inputs"], {"mouse": ["switch"], "keyboard": ["switch"], "touch": ["switch"]})
        self.assertEqual(buildfacts.required_devices(facts), ["touch", "mouse", "keyboard"])
        copies, _ = copywriter.write_copy(facts, ["en"], REFERENCE)
        self.assertIn("Keyboard: Switch", copies["en"]["controls"])


# -- 3. locales ------------------------------------------------------------------------------

class Locales(unittest.TestCase):
    def test_an_objective_line_is_not_a_full_description(self):
        objective_only = {"title": "Fixture Game", "short_description": "Нажимайте в такт.",
                          "long_description": "Нажимайте в такт.", "controls": "", "features": [], "tags": []}
        problems = buildfacts.full_description_problems(objective_only, REFERENCE, "ru")
        self.assertIn("controls is empty", problems)
        self.assertTrue(any("under 200" in p for p in problems), problems)
        self.assertIn("long_description is the short description again", problems)

    def test_a_translated_bullet_is_grounded_on_numbers_not_on_shared_english_words(self):
        facts = measured_facts()
        # LEAD 33: a Russian bullet shares no word with its English source - that is a
        # translation, not a problem; carrying English words to pass is not needed.
        ok = {"title": "x", "short_description": "y", "long_description": "z", "tags": [],
              "features": [{"text": "Одно касание меняет полосу в такт", "source": "mechanic:lane-switch"}]}
        self.assertEqual([p for p in grounding.check(ok, facts, [], locale="ru", counts=COUNTS)
                          if p["severity"] == "error"], [])
        bad = dict(ok, features=[{"text": "Пять касаний меняют полосу", "source": "mechanic:lane-switch"}])
        self.assertEqual([p["code"] for p in grounding.check(bad, facts, [], locale="ru", counts=COUNTS)],
                         ["bullet-number-unbacked"])
        # In English the shared-word rule still holds.
        unrelated = dict(ok, features=[{"text": "Fly a spaceship", "source": "mechanic:lane-switch"}])
        self.assertEqual([p["code"] for p in grounding.check(unrelated, facts, [], locale="en", counts=COUNTS)],
                         ["bullet-unrelated"])


# -- 4. the subtitle -------------------------------------------------------------------------

class Subtitle(unittest.TestCase):
    def test_a_genre_only_subtitle_is_generic_and_the_template_never_writes_one(self):
        facts = measured_facts()
        for generic in ("Rhythm", "A casual arcade game", "Rhythm in 2D"):
            self.assertTrue(buildfacts.generic_subtitle({"subtitle": generic}, facts, REFERENCE, "en",
                                                        ["Rhythm", "Arcade"]), generic)
        self.assertFalse(buildfacts.generic_subtitle({"subtitle": "Tap on the beat to switch lanes"},
                                                     facts, REFERENCE, "en"))
        copies, _ = copywriter.write_copy(facts, ["en"], REFERENCE)
        self.assertTrue(copies["en"]["subtitle"])
        self.assertFalse(buildfacts.generic_subtitle(copies["en"], facts, REFERENCE, "en", ["Rhythm", "Arcade"]))


# -- 5. through the steps --------------------------------------------------------------------

COPYWRITER = textwrap.dedent('''\
    import json, re, sys
    brief, out = sys.argv[1], sys.argv[2]
    text = open(brief, encoding="utf-8").read()
    with open(out + ".brief", "w", encoding="utf-8") as handle:
        handle.write(text)
    locale = re.search(r"\\((\\w+)\\)\\n", text).group(1)
    if locale == "ru":
        copy = {"title": "Fixture Game", "subtitle_variants": ["Ритм-игра о смене полос"],
                "short_description": "Нажимайте в такт, чтобы менять полосу и держать комбо живым.",
                "long_description": ("Нажимайте в такт, чтобы менять полосу. Каждое точное попадание поднимает "
                                     "множитель комбо. Пропущенные ворота заканчивают забег, а новая попытка "
                                     "начинается одним касанием. В игре 12 трасс в 3 мирах. Касание, мышь и "
                                     "клавиатура работают одинаково."),
                "features": [{"text": "Одно касание меняет полосу", "source": "mechanic:lane-switch"},
                             {"text": "Комбо растёт с каждым точным попаданием", "source": "mechanic:combo"},
                             {"text": "Пропуск ворот заканчивает забег", "source": "mechanic:gate-miss"}],
                "controls": "Касание: нажмите на экран. Мышь: щелчок. Клавиатура: пробел.",
                "tags": ["rhythm", "casual", "2d"], "categories": ["Arcade"], "promo": ["Держите ритм"]}
    else:
        copy = {"title": "Fixture Game", "subtitle_variants": ["Switch lanes on the beat"],
                "short_description": "Tap on the beat to switch lanes and keep the combo alive.",
                "long_description": ("Tap on the beat to switch lanes. Every hit on the beat raises the combo "
                                     "multiplier. A missed gate ends the run, and a retry is one tap away. "
                                     "12 courses across 3 worlds. Touch, mouse and keyboard all play."),
                "features": [{"text": "One tap switches lanes on the beat", "source": "mechanic:lane-switch"},
                             {"text": "Hits on the beat raise the combo multiplier", "source": "mechanic:combo"},
                             {"text": "A missed gate ends the run", "source": "mechanic:gate-miss"}],
                "controls": "Touch: tap anywhere. Mouse: click anywhere. Keyboard: Space.",
                "tags": ["rhythm", "casual", "2d"], "categories": ["Arcade"], "promo": ["Keep the beat"]}
    json.dump(copy, open(out, "w", encoding="utf-8"), ensure_ascii=False)
''')


@unittest.skipUnless(base.HAS_GIT, "git is not installed")
class ThroughTheSteps(base.ListingCase):
    def setUp(self):
        super().setUp()
        self.image_sizes_unstated()
        self.game = base.GameBuild(os.path.join(self.scratch, "ru-build"), strings={
            "en": {"title.heading": "Fixture Game", "hud.objective": "Tap on the beat to switch lanes."},
            "ru": {"title.heading": "Fixture Game", "hud.objective": "Нажимайте в такт, чтобы менять полосу."}})
        self.writer = os.path.join(self.scratch, "copywriter.py")
        with open(self.writer, "w", encoding="utf-8") as handle:
            handle.write(COPYWRITER)

    def evidence(self, design=None, report=True):
        artifacts = self.game.evidence(platforms=[{"id": "yandex", "profile": "yandex@1.3.0", "role": "required"}],
                                       design=design or course_design())
        if report:
            artifacts["content-sufficiency-report"] = sufficiency(self.game.head)
        return artifacts

    def config(self, writer=True):
        config = {"listing": {"age_rating": {"default": "12+"}}}
        if writer:
            config["listing"]["writer"] = {"kind": "auto", "argv": [sys.executable, self.writer, "{brief}", "{output}"],
                                           "timeout_seconds": 60}
        return config

    def release_context(self, **kw):
        context = self.context(**kw)
        context.environment = dict(RELEASE)
        return context

    def listing(self, writer=True, artifacts=None, context=None):
        result, _ = self.capture(fake=ProbeCapture(), artifacts=artifacts or self.evidence(),
                                 context=context or self.release_context(config=self.config(writer)))
        return self.listing_of(result)

    def judge(self, listing):
        artifacts = {"store-listing": listing, "game-design": base.seal("game-design", course_design())}
        context = self.context(step="listing-validation")
        result = base.validation_step().execute(base.Inputs(artifacts), context)
        report = result.artifacts[0].content
        self.assertEqual(base.CONTRACTS.problems("listing-validation-report", report), [])
        return result, report

    def test_a_correct_multi_locale_listing_by_the_copywriter_passes(self):
        listing = self.listing()
        self.assertEqual(listing["copy"]["writer"]["kind"], "command")
        self.assertEqual(listing["copy"]["writer"]["required"], "command")
        self.assertEqual(listing["copy"]["writer"]["role"], "copywriter")
        self.assertFalse(listing["copy"]["writer"]["fallback"])
        self.assertEqual(listing["facts"]["quality"]["tier"], "release")
        self.assertEqual(listing["facts"]["measured"]["counts"]["units"]["value"], 12)
        self.assertEqual(listing["facts"]["probe_inputs"]["keyboard"], ["switch", "pause"])
        self.assertEqual(sorted(listing["copy"]["locales"]), ["en", "ru"])
        result, report = self.judge(listing)
        self.assertEqual(report["failed"], [], [c for c in report["checks"] if c["status"] == "FAIL"])
        self.assertEqual(report["verdict"], "PASS")
        status = {c["id"]: c["status"] for c in report["checks"]}
        for check in ("grounding.counts.en", "grounding.counts.ru", "metadata.en.controls",
                      "metadata.ru.controls", "metadata.ru.full_description", "metadata.writer"):
            self.assertEqual(status.get(check), "PASS", check)
        # The brief told the copywriter the measured counts and every device.
        brief = _read(os.path.join(self.run_dir, "store-listing", "1-1", "writer", "copy-ru-1.json.brief"))
        self.assertIn("- units: 12 (course)", brief)
        self.assertIn("The build accepts: touch, mouse, keyboard", brief)
        self.assertIn("This locale (ru) is required", brief)

    def tamper(self, listing, locale, **fields):
        listing["copy"]["locales"][locale].update(fields)
        listing["provenance"]["content_hash"] = content_hash(listing)
        return listing

    def test_the_four_regressions_fail_as_store_copy(self):
        listing = self.listing()
        self.tamper(listing, "en", short_description="Six floating-island courses to roll through, on the beat.",
                    controls="Touch: tap anywhere.", subtitle="Rhythm")
        self.tamper(listing, "ru", long_description="Нажимайте в такт, чтобы менять полосу и держать комбо живым.",
                    short_description="Нажимайте в такт, чтобы менять полосу и держать комбо живым.")
        result, report = self.judge(listing)
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "listing")
        for check in ("grounding.counts.en", "metadata.en.controls", "metadata.en.subtitle",
                      "metadata.ru.full_description"):
            self.assertIn(check, report["failed"], check)
        # Each is store copy: triage routes it to the copywriter.
        found = normalize("listing-validation-report", report, Routing.load())
        owners = {f["source"]["check"]: (f["dimension"], f["owner"], f["route"]) for f in found}
        for check in ("grounding.counts.en", "metadata.en.controls", "metadata.ru.full_description"):
            self.assertEqual(owners[check], (COPY_DIMENSION, "copywriter", "listing"), check)

    def test_at_release_the_template_writer_blocks_for_a_person(self):
        listing = self.listing(writer=False)
        self.assertEqual(listing["copy"]["writer"], {"kind": "template", "required": "command", "tier": "release"})
        result, report = self.judge(listing)
        self.assertIn("metadata.writer", report["failed"])
        writer_check = next(c for c in report["checks"] if c["id"] == "metadata.writer")
        self.assertEqual(writer_check["fix"], "configure")
        # ru is the game's objective line only: not a full description at release.
        self.assertIn("metadata.ru.full_description", report["failed"])

    def test_in_a_development_run_the_template_writes_and_the_bars_warn(self):
        context = self.context(config=self.config(writer=False))
        context.environment = {"quality": {"tier": "mvp", "class": "development"}}
        listing = self.listing(writer=False, context=context)
        self.assertEqual(listing["copy"]["writer"]["kind"], "template")
        self.assertEqual(listing["copy"]["writer"]["required"], "template")
        _result, report = self.judge(listing)
        status = {c["id"]: c["status"] for c in report["checks"]}
        self.assertEqual(status.get("metadata.ru.full_description"), "WARNING")
        self.assertNotIn("metadata.writer", report["failed"])

    def test_a_report_of_another_build_measures_nothing(self):
        artifacts = self.evidence(report=False)
        artifacts["content-sufficiency-report"] = sufficiency("e" * 40)
        listing = self.listing(artifacts=artifacts, context=self.release_context(config=self.config(writer=False)))
        self.assertNotIn("measured", listing["facts"])

    def test_the_copywriter_route_listing_triage_briefs_the_findings(self):
        # listing-validation FAILS on copy -> listing-triage routes `listing` -> store-listing
        # runs again, its copywriter briefed with the store-copy findings.
        listing = self.listing()
        self.tamper(listing, "en", short_description="Six floating-island courses to roll through, on the beat.")
        _result, report = self.judge(listing)
        self.assertIn("grounding.counts.en", report["failed"])
        definition = load_definition("new-game")
        self.assertEqual(definition.step("listing-validation").on, {"listing": "listing-triage"})
        triage_def = definition.step("listing-triage")
        self.assertEqual((triage_def.type, triage_def.on), ("triage", {"listing": "store-listing"}))
        context = types.SimpleNamespace(entered_by="listing-validation.listing", run_dir=self.run_dir,
                                        logger=base.Logger(), execution=1, visit=1, project_id="fixture-game")
        triage = TriageStep(types.SimpleNamespace(id="listing-triage", params={}, on=dict(triage_def.on)))
        docs = {"game-design": base.seal("game-design", course_design()), "listing-validation-report": report}
        routed = triage.execute(_Seq(docs, {"game-design": 1, "listing-validation-report": 9}), context)
        self.assertEqual(routed.outcome, StepOutcome.SUCCESS, routed.message)
        self.assertEqual(routed.route, "listing")
        triage_report = routed.artifacts[0].content
        self.assertEqual(triage_report["selected"]["route"], "listing")
        copy_ids = [f["id"] for f in triage_report["findings"] if f["owner"] == "copywriter"]
        self.assertIn("listing-validation-report:grounding.counts.en@en", copy_ids)
        # The second store-listing pass, entered through the triage.
        artifacts = self.evidence()
        artifacts["triage-report"] = triage_report
        artifacts["listing-validation-report"] = report
        context = self.release_context(config=self.config(), entered_by="listing-triage.listing", visit=2)
        result, _ = self.capture(fake=ProbeCapture(), artifacts=artifacts, context=context)
        second = self.listing_of(result)
        self.assertIn("listing-validation-report:grounding.counts.en@en", second["copy"]["writer"]["findings"])
        brief = _read(os.path.join(self.run_dir, "store-listing", "2-1", "writer", "copy-en-1.json.brief"))
        self.assertIn("What listing-validation found in the previous copy", brief)
        self.assertIn("listing-validation-report:grounding.counts.en@en", brief)
        self.assertIn("Copywriter", brief)
        # A finding about the en copy is not put in the ru brief.
        brief_ru = _read(os.path.join(self.run_dir, "store-listing", "2-1", "writer", "copy-ru-1.json.brief"))
        self.assertNotIn("grounding.counts.en@en", brief_ru)


class _Seq:
    """Inputs with run-local sequence numbers (the triage step reads which report is newer)."""

    def __init__(self, artifacts, seqs):
        self.contents = dict(artifacts)
        self.refs = {k: types.SimpleNamespace(id=f"{k}-v{seqs.get(k, 1)}", type=k, seq=seqs.get(k, 1),
                                              content_hash=c["provenance"]["content_hash"])
                     for k, c in self.contents.items()}

    def __contains__(self, kind):
        return kind in self.contents

    def load(self, kind):
        return self.contents[kind]


class TheShippedWorkflow(unittest.TestCase):
    """new-game, mock steps, in process: listing-validation's `listing` goes through
    listing-triage to store-listing, and a passing listing still goes straight to release."""

    def setUp(self):
        import shutil
        import tempfile
        self.scratch = tempfile.mkdtemp(prefix="wgf-listing-route-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def test_a_failed_listing_goes_through_triage_to_the_copywriters_pass(self):
        from wgflib.workflow.api import RunRequest, WorkflowAPI
        from wgflib.workflow.config import FactoryConfig
        from wgflib.workflow.model import RunStatus
        api = WorkflowAPI(config=FactoryConfig({"storage": {"fsync": False}}),
                          store_dir=os.path.join(self.scratch, "store"))
        plan = {"listing-validation": ["listing", "success"], "listing-triage": ["listing"]}
        run = api.run(RunRequest(mock=True, mock_plan=plan))
        self.assertEqual((run.status, run.cursor), (RunStatus.WAITING, "prototype-review"), run.message)
        state = api.run(RunRequest(resume=run.run_id, decision="pass", note="criteria hold",
                                   decided_by="human", mock_plan=plan))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        tail = [e["step"] for e in state.trail][-7:]
        self.assertEqual(tail, ["prototype-review", "store-listing", "listing-validation", "listing-triage",
                                "store-listing", "listing-validation", "release"])
        self.assertEqual(state.steps["store-listing"].route_visits.get("listing-triage.listing"), 1)


class TheAutonomousProfile(unittest.TestCase):
    def test_the_profile_configures_the_copywriter_as_the_shipped_example(self):
        import test_autonomous_profile as profile_tests
        from wgflib.yamllite import load
        with open(profile_tests.PROFILE, encoding="utf-8") as handle:
            profile = load(handle.read())
        writer = profile["factory"]["listing"]["writer"]
        self.assertEqual(writer, profile_tests.commented_example("listing", "writer"))
        self.assertEqual(writer["kind"], "command")
        self.assertNotIn("Write", writer["argv"][writer["argv"].index("--tools") + 1])
        with open(profile_tests.SHIPPED, encoding="utf-8") as handle:
            shipped = load(handle.read())
        self.assertEqual(shipped["factory"]["listing"]["writer"]["kind"], "auto")


class OneListingPass(unittest.TestCase):
    def test_every_listing_finding_is_one_store_listing_pass(self):
        routing = Routing.load()
        findings = [{"id": "a", "dimension": "store-copy", "owner": "copywriter", "route": "listing",
                     "severity": "blocker"},
                    {"id": "b", "dimension": "art-2d", "owner": "artist-2d", "route": "listing",
                     "severity": "blocker"}]
        groups = routing.groups(findings)
        self.assertEqual(len(groups), 1)
        self.assertEqual((groups[0]["label"], sorted(groups[0]["findings"])), ("listing", ["a", "b"]))

    def test_the_writer_follows_the_tier(self):
        self.assertEqual(buildfacts.writer_kind("auto", "release", REFERENCE), "command")
        self.assertEqual(buildfacts.writer_kind("auto", "mvp", REFERENCE), "template")
        self.assertEqual(buildfacts.writer_kind("auto", None, REFERENCE), "template")
        self.assertEqual(buildfacts.writer_kind("template", "release", REFERENCE), "template")
        self.assertEqual(RELEASE_BARS, {"min_screenshots": 5, "min_later_content_screenshots": 1,
                                        "trailer_s": [15, 30], "copy_counts_match_build": True,
                                        "full_description_per_required_locale": True,
                                        "controls_cover_all_inputs": True})


if __name__ == "__main__":
    unittest.main()
