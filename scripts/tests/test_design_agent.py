"""The `agent` design author (scripts/wgf_design/agent.py), F4.

An agent host improves the archetype's draft; the design module then applies exactly the
checks it applies to any author. The host here is a scripted stand-in (a Python script run
through wgflib.procs), so the tests are deterministic and offline.

    python -m unittest discover scripts/tests
"""

import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import test_design_module as design_tests  # noqa: E402
from wgf_design import AgentAuthor, AgentRunFailed  # noqa: E402
from wgf_design import content as content_rules  # noqa: E402
from wgf_design.agent import BUILD_SPEC_KEYS, REQUIRED_KEYS, check_shape  # noqa: E402
from wgf_design.platforms import load_platforms  # noqa: E402
from wgflib import genre_models  # noqa: E402
from wgflib.workflow.model import ArtifactRef, StepOutcome  # noqa: E402

# The stand-in host. argv: <mode> <request> <draft>. It reads the request, edits the
# starting draft as the mode says, and writes it (or prints it, or misbehaves).
HOST = r'''
import json, os, sys, time
mode, request_path, draft_path = sys.argv[1:4]
if sys.argv[4:]:
    # Anything after the draft: the rendered rest of the argv (a permission rule).
    with open(os.path.join(os.path.dirname(draft_path), "argv.json"), "w") as handle:
        json.dump(sys.argv[4:], handle)
if mode == "env":
    # What the host was given: where the tests look for a leaked secret.
    with open(os.path.join(os.path.dirname(draft_path), "env.json"), "w") as handle:
        json.dump(sorted(os.environ), handle)
    mode = "improve"
with open(request_path, encoding="utf-8") as handle:
    request = json.load(handle)
# A gap repair has no starting draft in the request: the draft file holds it.
draft = request.get("starting_draft")
if mode == "improve" or mode == "stdout":
    draft["fantasy"] = "Improved by the agent: " + draft["fantasy"]
    draft["build_spec"]["failure"]["feedback"] = "Agent-tuned hit-stop, shake and a low thud."
elif mode == "unbuildable":
    # A dangling state exit: exactly what buildability exists to catch.
    draft["build_spec"]["game_states"][0]["exits"][0]["to"] = "nowhere"
elif mode == "missing":
    del draft["build_spec"]["hud"]
elif mode == "invalid-enum":
    # A value the game-design schema does not allow, whatever it is told.
    draft["build_spec"]["controls"]["primary_input"] = "tap"
elif mode == "repairs":
    # Invalid first; given the problems, it fixes exactly them.
    if "repair" in request:
        with open(os.path.join(os.path.dirname(draft_path), "repair.json"), "w") as handle:
            json.dump({"problems": request["repair"]["problems"],
                       "had_previous": request["repair"]["previous_draft"] is not None,
                       "schema": request["schema"]}, handle)
    else:
        draft["build_spec"]["controls"]["primary_input"] = "tap"
elif mode == "cubes":
    # A draft that says nothing about how the game looks; repaired once shown the problems.
    if "repair" in request:
        with open(os.path.join(os.path.dirname(draft_path), "repair.json"), "w") as handle:
            json.dump({"problems": request["repair"]["problems"],
                       "production_art": request["production_art"],
                       "craft": request["craft"]}, handle)
    else:
        for asset in draft["build_spec"]["assets"]:
            for key in ("role", "dimension", "readability"):
                asset.pop(key, None)
        del draft["build_spec"]["visual_identity"]["ui"]
elif mode in ("revise", "revise-repairs"):
    # What a re-entered design was given: the base, the delta, the prompt, the seeded file.
    with open(draft_path, encoding="utf-8") as handle:
        seeded = json.load(handle)
    stem = os.path.basename(draft_path)[:-len(".draft.json")]
    with open(os.path.join(os.path.dirname(draft_path), f"seen-{stem}.json"), "w") as handle:
        json.dump({"starting_draft": request["starting_draft"], "seeded": seeded,
                   "revision": request.get("revision"),
                   "identity_kits": "identity_kits" in request,
                   "repair": request.get("repair"), "rest": sys.argv[4:]}, handle)
    draft = seeded
    if mode == "revise-repairs" and "repair" in request:
        # Fixes exactly the problem, from the revised base the request names.
        draft["build_spec"]["controls"]["primary_input"] = \
            request["starting_draft"]["build_spec"]["controls"]["primary_input"]
    else:
        draft["fantasy"] = "Revised: " + draft["fantasy"]
        if mode == "revise-repairs":
            draft["build_spec"]["controls"]["primary_input"] = "tap"
elif mode == "garbage":
    open(draft_path, "w").write("this is not json")
    sys.exit(0)
elif mode == "fail":
    print("host crashed", file=sys.stderr)
    sys.exit(3)
elif mode == "hang":
    time.sleep(30)
elif mode == "nothing":
    sys.exit(0)
elif mode == "deleted":
    os.remove(draft_path)
    sys.exit(0)
elif mode == "gaps":
    # Repairing a design that was built: the seeded draft is the previous design itself.
    with open(draft_path, encoding="utf-8") as handle:
        seeded = json.load(handle)
    # The request names the previous design by path (the draft file), not a second copy.
    with open(request["previous_design"], encoding="utf-8") as handle:
        previous = json.load(handle)
    with open(request["gaps_file"], encoding="utf-8") as handle:
        gaps_file = json.load(handle)
    with open(os.path.join(os.path.dirname(draft_path), "gaps.json"), "w") as handle:
        json.dump({"gaps": request.get("gaps"), "gaps_file": gaps_file,
                   "first_keys": list(request)[:2],
                   "previous_fantasy": previous.get("fantasy"),
                   "seeded_fantasy": seeded.get("fantasy"),
                   "seeded_keys": sorted(seeded)}, handle)
    draft = seeded
    draft["build_spec"]["content"]["units"][0]["parameters"]["answered"] = 1
elif mode in ("gaps-invalid", "gaps-repairs", "gaps-marked", "gaps-half-marked"):
    # A gap visit: what each round was given, then its answer.
    with open(draft_path, encoding="utf-8") as handle:
        draft = json.load(handle)
    with open(request["previous_design"], encoding="utf-8") as handle:
        previous = json.load(handle)
    stem = os.path.basename(draft_path)[:-len(".draft.json")]
    with open(os.path.join(os.path.dirname(draft_path), f"seen-{stem}.json"), "w") as handle:
        json.dump({"first_key": list(request)[0], "repair": request.get("repair"),
                   "instructions": request.get("instructions"), "draft": draft_path,
                   "seeded": draft, "previous": previous}, handle)
    if mode == "gaps-marked":
        # Every gap is obsolete: nothing to edit, each marked with its reason.
        draft["gaps_answered"] = [{"id": g["id"], "reason": "obsolete since a Factory fix"}
                                  for g in request["gaps"]]
    elif mode == "gaps-half-marked":
        draft["gaps_answered"] = [{"id": "gap-1", "reason": "answered at its field already"},
                                  {"id": "gap-2", "reason": " "}]
    elif "repair" not in request:
        # Answers the gap, and breaks a content value the checks refuse.
        draft["build_spec"]["content"]["units"][0]["parameters"]["answered"] = 1
        draft["build_spec"]["controls"]["primary_input"] = "tap"
    elif mode == "gaps-repairs":
        # Shown the problems first, fixes exactly them and keeps the answer.
        draft["build_spec"]["controls"]["primary_input"] = \
            previous["build_spec"]["controls"]["primary_input"]
    else:
        # gaps-invalid on a repair round: sees every gap answered and edits nothing.
        sys.exit(0)
elif mode == "edit-in-place":
    # Edits the seeded file rather than reproducing the request's starting draft.
    with open(draft_path, encoding="utf-8") as handle:
        draft = json.load(handle)
    draft["fantasy"] = "Edited in place: " + draft["fantasy"]
elif mode == "truncated":
    # What a host whose reply overflowed its output limit returns: the tail of the draft.
    print("```json\n" + json.dumps(draft)[-3000:] + "\n```\nThat completes the draft.")
    sys.exit(0)
if mode == "stdout":
    print("Here is the design.\n```json\n" + json.dumps(draft) + "\n```")
else:
    with open(draft_path, "w", encoding="utf-8") as handle:
        json.dump(draft, handle)
'''


class AgentCase(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-design-agent-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.host = os.path.join(self.scratch, "host.py")
        with open(self.host, "w", encoding="utf-8") as handle:
            handle.write(HOST)

    def config(self, mode, **agent):
        settings = {"argv": [sys.executable, self.host, mode, "{request}", "{draft}"],
                    "timeout_seconds": 60, "idle_timeout_seconds": None}
        settings.update(agent)
        return {"design": {"author": "agent", "agent": settings}}

    def brief(self, **extra):
        """The brief the design step hands an author, with this attempt's run directory."""
        strategy = design_tests.load_strategy()
        brief = {"title_id": strategy["title_id"], "strategy": strategy,
                 "platforms": load_platforms(strategy, None), "params": {},
                 "config": {}, "run_dir": os.path.join(self.scratch, "run"),
                 "visit": 1, "attempt": 1}
        brief.update(extra)
        return brief

    def request_of(self, stem="1-1"):
        path = os.path.join(self.scratch, "run", "design", f"{stem}.request.json")
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def run_design(self, config):
        context = design_tests.FakeContext(config)
        context.run_dir = os.path.join(self.scratch, "run")
        context.visit, context.attempt = 1, 1
        step = design_tests.FixedClockStep(design_tests.FakeDefinition())
        return step.execute(design_tests.FakeInputs(design_tests.load_strategy()), context)


class AnAgentImprovesTheDraft(AgentCase):
    def test_the_improved_draft_becomes_the_design(self):
        result = self.run_design(self.config("improve"))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        design = result.artifacts[0].content
        self.assertTrue(design["fantasy"].startswith("Improved by the agent: "))
        self.assertEqual(design["build_spec"]["failure"]["feedback"],
                         "Agent-tuned hit-stop, shake and a low thud.")
        self.assertEqual(design["provenance"]["produced_by"]["actor"], "ai")
        self.assertEqual(result.artifacts[0].metadata["author"], "agent")
        # The module still did everything after the draft.
        self.assertEqual(design["consistency"]["status"], "pass")
        self.assertTrue(design["build_spec"]["sdk_touchpoints"])

    def test_the_kits_offered_can_set_every_locale_in_scope(self):
        # A live run chose a kit whose display face (Fraunces) has no Cyrillic for a
        # Yandex-required title, and the prompt told it to keep the kit's faces.
        from wgf_design.agent import _kits
        kits = _kits(["en", "ru"])
        self.assertEqual(kits["paper-diorama"]["typography"]["display"].split(" (")[0],
                         "Playfair Display")
        faces = [kit["typography"].get(k) or "" for kit in kits.values()
                 for k in ("display", "body", "numeric")]
        self.assertFalse([f for f in faces if f.startswith("Fraunces")])

    def test_the_request_carries_the_strategy_platforms_and_a_starting_draft(self):
        self.run_design(self.config("improve"))
        with open(os.path.join(self.scratch, "run", "design", "1-1.request.json")) as handle:
            request = json.load(handle)
        self.assertEqual(request["title_id"], design_tests.load_strategy()["title_id"])
        strategy_platforms = {p["id"] for p in design_tests.load_strategy()["platform_set"]}
        self.assertEqual({p["id"] for p in request["platforms"]}, strategy_platforms)
        self.assertTrue(all(p["profile"] for p in request["platforms"]))
        self.assertTrue(set(REQUIRED_KEYS) <= set(request["starting_draft"]))
        self.assertEqual(request["required_keys"], list(REQUIRED_KEYS))

    def test_a_read_only_host_can_print_the_draft(self):
        result = self.run_design(self.config("stdout", draft_from="stdout"))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertTrue(result.artifacts[0].content["fantasy"].startswith("Improved"))


    def test_the_write_rule_names_the_draft_absolutely_on_every_host_os(self):
        # F11: `Edit(/{draft})` rendered `Edit(/C:\...)` on Windows, which the host reads
        # as project-relative, so every write was denied. Both forms now render the rule.
        from wgflib import permpath
        config = self.config("improve")
        config["design"]["agent"]["argv"] += ["Edit({draft_rule})", "Edit(/{draft})"]
        result = self.run_design(config)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        drafts = [os.path.join(root, name) for root, _, names in os.walk(self.scratch)
                  for name in names if name.endswith(".draft.json")]
        with open(os.path.join(os.path.dirname(drafts[0]), "argv.json"),
                  encoding="utf-8") as handle:
            rendered = json.load(handle)
        rule = "Edit(" + permpath.rule_path(drafts[0]) + ")"
        self.assertEqual(rendered, [rule, rule])
        self.assertTrue(rule.startswith("Edit(//"))
        self.assertNotIn("\\", rule)


class TheModuleStillJudges(AgentCase):
    def test_an_unbuildable_draft_fails_exactly_as_any_author_would(self):
        result = self.run_design(self.config("unbuildable"))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("not buildable", result.error)
        self.assertEqual(result.artifacts, [])

    def test_an_invalid_draft_is_shown_its_problems_and_repaired(self):
        """Found by the dogfood run: an agent draft used enum values the schema does not allow
        and the step failed with no second look. The step shows the agent exactly what made
        the design invalid and asks again; the result is checked like the first."""
        result = self.run_design(self.config("repairs"))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        with open(os.path.join(self.scratch, "run", "design", "repair.json"), encoding="utf-8") as h:
            repair = json.load(h)
        self.assertTrue(any("primary_input" in p for p in repair["problems"]), repair)
        self.assertTrue(repair["had_previous"])
        self.assertTrue(repair["schema"].endswith("game-design.schema.json"))
        self.assertTrue(os.path.isfile(repair["schema"]))

    def test_the_repair_prompt_itself_lists_the_problems(self):
        """K5 fresh-session experiment: the request holding `repair` is hundreds of kilobytes
        and real agents never found the key; the prompt names the problems itself."""
        config = self.config("repairs")
        config["design"]["agent"]["argv"].append("{prompt}")
        result = self.run_design(config)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        with open(os.path.join(self.scratch, "run", "design", "argv.json"),
                  encoding="utf-8") as handle:
            prompt = json.load(handle)[0]
        self.assertIn("The problems to fix: (1) ", prompt)
        self.assertIn("primary_input", prompt.split("The problems to fix:")[1])

    def test_a_draft_that_states_no_production_art_is_shown_what_to_state(self):
        """The production art and UI are held like the experience contract: an agent draft that
        leaves the developer to draw cubes is shown the named problems, and the bars and the
        craft guide are in its request from the first round."""
        result = self.run_design(self.config("cubes"))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        with open(os.path.join(self.scratch, "run", "design", "repair.json"), encoding="utf-8") as h:
            repair = json.load(h)
        text = "\n".join(repair["problems"])
        self.assertIn("visual_identity.ui is missing", text)
        self.assertIn("state its role and dimension", text)
        self.assertEqual(repair["production_art"]["ui"]["min_target_px"], 44)
        self.assertTrue(os.path.isfile(repair["craft"]), repair["craft"])

    def test_request_carries_genre_model_constraints_and_rules(self):
        """The agent designs the content, so it gets what the content is held to: the genre
        family itself, the rule ids, the variety bars, the session profile and the craft
        guide - and the content shape research coded, when the strategy carries one."""
        constraints = {"family": {"value": "arcade", "label": "Arcade / action",
                                  "tier": "derived", "source": "corpus",
                                  "claim_refs": ["claim-x"]}}
        strategy = design_tests.variant(research={
            "research_version": 2, "design_constraints": constraints,
            "capability": {"buildable": True, "design_archetype": "lane-runner",
                           "catalog_entry": "endless-runner", "reason": "FIXTURE",
                           "missing": []},
            "art": {}, "theme": {"theme": {}, "setting": {}},
            "fantasy": {"player": {}, "emotional": {}}, "patterns": {"adopt": []}})
        AgentAuthor().draft(self.brief(strategy=strategy,
                                      config=self.config("improve")))
        request = self.request_of()
        family = genre_models.load()["families"]["arcade"]

        self.assertEqual(request["genre_model"]["unit_kinds"], family["unit_kinds"])
        self.assertEqual([a["id"] for a in request["genre_model"]["axes"]],
                         [a["id"] for a in family["axes"]])
        self.assertEqual(request["genre_model"]["units"], family["units"])
        self.assertNotIn("seed", request["genre_model"])

        self.assertEqual([r["id"] for r in request["content_rules"]["rules"]],
                         [rule_id for rule_id, _ in content_rules.RULES])
        self.assertTrue(all(r["meaning"] for r in request["content_rules"]["rules"]))
        self.assertEqual(request["content_rules"]["variety"]["acceptance_min_items"],
                         family.get("variety", {}).get(
                             "acceptance_min_items",
                             genre_models.load()["variety"]["acceptance_min_items"]))
        self.assertEqual(request["content_rules"]["session_profile"]["name"], "casual")
        self.assertEqual(request["content_rules"]["session_profile"]["max_unit_s"],
                         genre_models.load()["session_profiles"]["casual"]["max_unit_s"])
        self.assertEqual(request["design_constraints"], constraints)
        self.assertTrue(os.path.isfile(request["content_craft"]), request["content_craft"])
        # The starting draft already states the content: the agent improves a design, not a
        # loop and the word "harder".
        self.assertTrue(request["starting_draft"]["build_spec"]["content"]["units"])

    def test_request_carries_the_quality_tier_and_its_bars(self):
        """At release the agent is told the tier, the strategy's budget and the benchmark's
        bars, so the units are written to the measure content.tier_* applies."""
        budget = {"units": 12, "designed_play_s": 300}
        concept = dict(design_tests.load_strategy().get("concept") or {})
        concept["content_model"] = {"family": "arcade", "source": "default",
                                    "quality_tier": "release", "budget": budget}
        strategy = design_tests.variant(concept=concept)
        AgentAuthor().draft(self.brief(strategy=strategy, config=self.config("improve")))
        tier = self.request_of()["content_rules"]["tier"]
        self.assertEqual(tier["quality_tier"], "release")
        self.assertEqual(tier["budget"], budget)
        bars = content_rules.load_benchmark()["content"]
        self.assertEqual(tier["benchmark"]["elements"]["min_distinct"],
                         bars["elements"]["min_distinct"]["release"])
        self.assertEqual(tier["rules"], list(content_rules.TIER_RULES))

    def test_the_prompt_names_the_content_rules(self):
        from wgf_design.agent import PROMPT_CONTENT
        for rule_id, _meaning in content_rules.RULES:
            self.assertIn(rule_id, PROMPT_CONTENT)
        self.assertIn("content_craft", PROMPT_CONTENT)

    def test_shape_check_requires_genre_and_content(self):
        self.assertIn("genre", REQUIRED_KEYS)
        for key in ("content", "mastery"):
            self.assertIn(key, BUILD_SPEC_KEYS)
        problems = check_shape({"build_spec": {}})
        self.assertIn("missing 'genre'", problems)
        self.assertIn("build_spec is missing 'content'", problems)
        self.assertIn("build_spec is missing 'mastery'", problems)
        whole = design_tests.run_step(design_tests.load_strategy()).artifacts[0].content
        draft = {key: whole[key] for key in REQUIRED_KEYS}
        self.assertEqual(check_shape(draft), [])
        del draft["build_spec"]["content"]
        self.assertEqual(check_shape(draft), ["build_spec is missing 'content'"])

    def test_gaps_seed_from_the_previous_design(self):
        """A prototype report named gaps in the design. The agent starts from the design they
        were found in - not from a fresh draft - and answers each at its own field."""
        previous = design_tests.run_step(design_tests.load_strategy()).artifacts[0].content
        gaps = [{"field": "build_spec.content.units[seg-opening].parameters",
                 "question": "What row gap does the opening segment use?"}]
        draft = AgentAuthor().draft(self.brief(config=self.config("gaps"), gaps=gaps,
                                               previous_design=previous))
        with open(os.path.join(self.scratch, "run", "design", "gaps.json"),
                  encoding="utf-8") as handle:
            seen = json.load(handle)
        self.assertEqual([(g["id"], g["field"], g["question"]) for g in seen["gaps"]],
                         [("gap-1", gaps[0]["field"], gaps[0]["question"])])
        self.assertEqual(seen["gaps_file"]["gaps"], seen["gaps"])
        self.assertEqual(seen["first_keys"], ["gaps", "gaps_file"])
        self.assertEqual(seen["previous_fantasy"], previous["fantasy"])
        # The file the agent edits is the previous design, without what the module owns.
        self.assertEqual(seen["seeded_fantasy"], previous["fantasy"])
        self.assertNotIn("provenance", seen["seeded_keys"])
        self.assertNotIn("consistency", seen["seeded_keys"])
        self.assertEqual(check_shape(draft), [])
        self.assertEqual(
            draft["build_spec"]["content"]["units"][0]["parameters"]["answered"], 1)
        request = self.request_of("1-1-gaps")
        self.assertEqual(request["gaps"], seen["gaps"])
        # The design the gaps were found in is a file of its own, not the draft the agent edits:
        # a repair round's draft is not that design.
        self.assertNotEqual(request["previous_design"], request["draft"])
        with open(request["previous_design"], encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["fantasy"], previous["fantasy"])
        # A gap repair keeps the identity it has: no kits are offered, and the strategy is a
        # file of its own.
        self.assertNotIn("identity_kits", request)
        self.assertNotIn("starting_draft", request)
        with open(request["strategy"], encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), design_tests.load_strategy())
        from wgf_design.agent import PROMPT_GAPS
        self.assertIn("`gaps`", PROMPT_GAPS)

    def large_strategy_gaps(self):
        """The 2D validation run's design visit 5 (2026-10-04): a strategy and previous design
        large enough that the request ran to 12,778 lines, with the gaps after both."""
        previous = design_tests.run_step(design_tests.load_strategy()).artifacts[0].content
        strategy = design_tests.load_strategy()
        strategy["notes"] = ["market note %d: %s" % (n, "x" * 200) for n in range(400)]
        gaps = [{"field": "build_spec.content.units[w1-l2].success",
                 "question": "How does a tracking bot clear level 2 in under 40 s?",
                 "severity": "minor", "assumed": "The rebound rule is kept exactly."},
                {"field": "build_spec.content.units", "question": "Three worlds, not one",
                 "severity": "blocking", "observed": 12, "bar": 32,
                 "finding": "content-sufficiency:units"}]
        return strategy, previous, gaps

    def test_a_large_request_puts_the_gaps_first(self):
        strategy, previous, gaps = self.large_strategy_gaps()
        AgentAuthor().draft(self.brief(config=self.config("gaps"), gaps=gaps,
                                       previous_design=previous, strategy=strategy))
        path = os.path.join(self.scratch, "run", "design", "1-1-gaps.request.json")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        request = json.loads(text)
        self.assertEqual(list(request)[:5],
                         ["gaps", "gaps_file", "instructions", "draft", "previous_design"])
        # The first bytes an agent pages are the gaps: ids, fields, observed against bar.
        head = text[:4096]
        for gap_id, gap in zip(("gap-1", "gap-2"), gaps):
            self.assertIn(f'"id": "{gap_id}"', head)
            self.assertIn(json.dumps(gap["field"]), head)
            self.assertIn(json.dumps(gap["question"]), head)
        self.assertIn('"observed": 12', head)
        self.assertIn('"bar": 32', head)
        self.assertEqual(list(request["gaps"][1])[:6],
                         ["id", "field", "question", "severity", "observed", "bar"])
        # The bulk is referenced, not inlined: neither the strategy nor the previous design
        # is in the request, so it is smaller than the strategy alone.
        self.assertLess(len(text), len(json.dumps(strategy)) + len(json.dumps(previous)))
        self.assertNotIn("market note 399", text)
        self.assertEqual(request["strategy"],
                         os.path.join(os.path.dirname(path), "1-1-gaps.strategy.json"))

    def test_the_prompt_names_the_gap_file_first(self):
        strategy, previous, gaps = self.large_strategy_gaps()
        config = self.config("gaps")
        config["design"]["agent"]["argv"].append("{prompt}")
        AgentAuthor().draft(self.brief(config=config, gaps=gaps, previous_design=previous,
                                       strategy=strategy))
        directory = os.path.join(self.scratch, "run", "design")
        with open(os.path.join(directory, "argv.json"), encoding="utf-8") as handle:
            prompt = json.load(handle)[0]
        gaps_file = os.path.join(directory, "1-1-gaps.gaps.json")
        self.assertTrue(prompt.startswith("This visit repairs 2 design gap(s)"), prompt[:200])
        self.assertIn(gaps_file, prompt[:600])
        self.assertTrue(os.path.isfile(gaps_file))
        # A gap repair is not asked to choose a new look.
        from wgf_design.agent import PROMPT_ART_KIT
        self.assertNotIn(PROMPT_ART_KIT, prompt)

    def test_gaps_left_unanswered_fail_naming_each_gap(self):
        from wgf_design import AuthorError
        strategy, previous, gaps = self.large_strategy_gaps()
        with self.assertRaises(AuthorError) as caught:
            AgentAuthor().draft(self.brief(config=self.config("nothing"), gaps=gaps,
                                           previous_design=previous, strategy=strategy))
        message = str(caught.exception)
        self.assertIn("unchanged", message)
        self.assertIn("none of the 2 design gap(s) it was given is answered", message)
        self.assertIn("gap-1 at build_spec.content.units[w1-l2].success", message)
        self.assertIn("gap-2 at build_spec.content.units", message)
        self.assertIn("1-1-gaps.gaps.json", message)

    def test_a_triage_gap_carries_what_was_observed_against_the_bar(self):
        from wgf_design.step import triage_gaps
        gaps = triage_gaps({
            "selected": {"route": "design", "findings": ["quality-gate:content-units"]},
            "findings": [{"id": "quality-gate:content-units", "dimension": "content",
                          "summary": "12 units", "measured": 12, "bar": 32,
                          "source": {"producer": "quality-report"},
                          "task": {"change": "more units", "acceptance": ["32 units"]}}]})
        self.assertEqual((gaps[0]["observed"], gaps[0]["bar"], gaps[0]["finding"]),
                         (12, 32, "quality-gate:content-units"))

    def test_gaps_without_the_previous_design_are_refused(self):
        from wgf_design import AuthorError
        with self.assertRaises(AuthorError) as caught:
            AgentAuthor().draft(self.brief(config=self.config("gaps"),
                                           gaps=[{"field": "x", "question": "y"}]))
        self.assertIn("previous_design", str(caught.exception))

    def test_a_deterministic_author_refuses_design_gaps(self):
        from wgf_design import AuthorError
        from wgf_design.authors import ArchetypeAuthor
        from wgf_design.seed import GenreSeedAuthor
        for author in (ArchetypeAuthor(), GenreSeedAuthor()):
            with self.assertRaises(AuthorError) as caught:
                author.draft(self.brief(gaps=[{"field": "x", "question": "y"}]))
            self.assertIn("design gaps need the agent author", str(caught.exception))

    def test_the_prompt_names_the_production_art_fields(self):
        from wgf_design.agent import PROMPT_ART
        for field in ("role", "dimension", "readability", "visual_identity.ui", "min_target_px",
                      "primitive_style"):
            self.assertIn(field, PROMPT_ART)

    def test_a_draft_that_stays_invalid_fails_after_the_repair_rounds(self):
        from wgf_design.step import MAX_REPAIR_ROUNDS
        result = self.run_design(self.config("invalid-enum"))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("not a valid game-design", result.error)
        self.assertIn(f"after {MAX_REPAIR_ROUNDS} repair round(s)", result.error)
        self.assertIn("primary_input", result.error)
        rounds = sorted(n for n in os.listdir(os.path.join(self.scratch, "run", "design"))
                        if n.endswith(".request.json"))
        self.assertEqual(len(rounds), MAX_REPAIR_ROUNDS + 1, rounds)

    def test_a_draft_missing_a_section_is_refused_before_finalize(self):
        result = self.run_design(self.config("missing"))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("build_spec is missing 'hud'", result.error)

    def test_a_draft_that_is_not_json_is_refused(self):
        result = self.run_design(self.config("garbage"))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("not readable JSON", result.error)

    def test_no_draft_at_all_is_refused(self):
        result = self.run_design(self.config("deleted"))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("wrote no draft", result.error)

    def test_a_draft_left_as_seeded_is_refused(self):
        result = self.run_design(self.config("nothing"))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("unchanged", result.error)

    def test_the_draft_file_is_seeded_so_the_agent_edits_it_in_place(self):
        result = self.run_design(self.config("edit-in-place"))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertTrue(result.artifacts[0].content["fantasy"].startswith("Edited in place: "))

    def test_a_truncated_stdout_draft_names_the_cause(self):
        result = self.run_design(self.config("truncated", draft_from="stdout"))
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("draft_from: file", result.error)

    def test_the_shape_check_names_every_problem(self):
        self.assertEqual(check_shape([]), ["the draft is not a JSON object"])
        problems = check_shape({"build_spec": {}, "scope": [], "engine": "pixijs",
                                "features": {}})
        self.assertIn("missing 'fantasy'", problems)
        self.assertIn(f"build_spec is missing {BUILD_SPEC_KEYS[0]!r}", problems)
        for needle in ("scope is not an object", "engine is not an object",
                       "features is not a list"):
            self.assertIn(needle, problems)


class HostFailures(AgentCase):
    def test_a_failing_host_is_retryable(self):
        # Raised out of the step: the engine's runtime retries it like any transient failure.
        with self.assertRaises(AgentRunFailed) as caught:
            self.run_design(self.config("fail"))
        self.assertIn("exit 3", str(caught.exception))

    def test_a_hung_host_is_stopped_and_retryable(self):
        with self.assertRaises(AgentRunFailed) as caught:
            self.run_design(self.config("hang", timeout_seconds=1))
        self.assertIn("timeout", str(caught.exception))

    def test_an_unconfigured_agent_is_refused(self):
        for agent in ({"argv": []}, {"argv": "claude -p"}, {"argv": ["x"], "draft_from": "fd"},
                      {"argv": ["x", "{repo}"]}, {"argv": ["x", '{"inline": 1}']}):
            result = self.run_design({"design": {"author": "agent", "agent": agent}})
            self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))

    def test_the_host_gets_the_allowlisted_agent_environment(self):
        # As the developer and the reviewer: a Factory secret is not the host's to read,
        # and only factory.agents.env_passthrough adds to the allowlist.
        from unittest import mock
        planted = {"WGF_TEST_SECRET_TOKEN": "s3cret", "GH_TOKEN": "gh", "HOST_CRED": "c"}
        with mock.patch.dict(os.environ, planted):
            config = self.config("env")
            config["agents"] = {"env_passthrough": ["HOST_CRED"]}
            result = self.run_design(config)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        with open(os.path.join(self.scratch, "run", "design", "env.json")) as handle:
            names = set(json.load(handle))
        self.assertIn("HOST_CRED", names)
        self.assertFalse({"WGF_TEST_SECRET_TOKEN", "GH_TOKEN"} & names)

    def test_the_default_author_is_still_the_archetype(self):
        result = self.run_design({})
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(result.artifacts[0].metadata["author"], "archetype")
        self.assertEqual(result.artifacts[0].content["provenance"]["produced_by"]["actor"],
                         "automation")
        self.assertEqual(AgentAuthor.actor, "ai")


class ARevisionStartsFromTheRunsDesign(AgentCase):
    """Found live (2026-10-04, a 2D brick-breaker): the operator grew the strategy's content
    and re-ran the design in the same run, and the agent author started again from the
    archetype's draft - a new identity kit, the strategy's content lost. A re-entry (a new
    visit) revises the run's previous game-design, told what changed in the strategy since it.
    A resumed execution of the same visit is not a re-entry: it continues the repair of its
    own last draft, still naming the same base."""

    GROWN = "32 hand-built levels in 4 worlds of 8, every move on the beat."

    def setUp(self):
        super().setUp()
        self.run_dir = os.path.join(self.scratch, "run")

    def config_with_prompt(self, mode):
        return self.config(mode, argv=[sys.executable, self.host, mode, "{request}", "{draft}",
                                       "{prompt}"])

    def store(self, artifact_id, version, content):
        """`content` written where the engine keeps it; its ArtifactRef."""
        location = f"artifacts/{artifact_id}/v{version}.json"
        path = os.path.join(self.run_dir, *location.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = json.dumps(content, indent=2).encode("utf-8")
        with open(path, "wb") as handle:
            handle.write(payload)
        return ArtifactRef(id=artifact_id, type=artifact_id, version=version, location=location,
                           checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
                           content_hash=content["provenance"]["content_hash"], seq=version)

    def execute(self, config, strategy, visit, previous_outputs=()):
        context = design_tests.FakeContext(config, execution=visit)
        context.run_dir = self.run_dir
        context.visit, context.attempt = visit, 1
        context.previous_outputs = list(previous_outputs)
        step = design_tests.FixedClockStep(design_tests.FakeDefinition())
        return step.execute(design_tests.FakeInputs(strategy), context)

    def first_design(self):
        """Visit 1 by the agent author, stored as the run would hold it: the design and the
        strategy it was made from."""
        strategy = design_tests.load_strategy()
        first = self.execute(self.config("improve"), strategy, 1)
        self.assertEqual(first.outcome, StepOutcome.SUCCESS, first.error)
        self.store("title-strategy", 1, strategy)
        design = first.artifacts[0].content
        return design, self.store("game-design", 1, design)

    def grown_strategy(self):
        strategy = design_tests.load_strategy()
        strategy["one_liner"] = self.GROWN
        return design_tests.rehash(strategy)

    def seen(self, stem):
        with open(os.path.join(self.run_dir, "design", f"seen-{stem}.json"),
                  encoding="utf-8") as handle:
            return json.load(handle)

    def test_a_first_design_starts_from_the_archetype(self):
        result = self.execute(self.config_with_prompt("revise"), design_tests.load_strategy(), 1)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        seen = self.seen("1-1")
        self.assertIsNone(seen["revision"])
        self.assertTrue(seen["identity_kits"])
        self.assertIn("identity_kits", seen["rest"][0])
        self.assertNotIn("REVISION", seen["rest"][0])
        self.assertNotIn("revises", result.artifacts[0].metadata)
        self.assertNotIn("supersedes", result.artifacts[0].content["provenance"])

    def test_a_re_entry_revises_the_previous_design_with_the_strategy_delta(self):
        previous, ref = self.first_design()
        result = self.execute(self.config_with_prompt("revise"), self.grown_strategy(), 2, [ref])
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        seen = self.seen("2-1")
        # A new visit is not the resume of visit 1: no repair of visit 1's last draft.
        self.assertIsNone(seen["repair"])
        # The starting draft is the previous design, identity and content and all - not the
        # archetype's.
        self.assertTrue(seen["starting_draft"]["fantasy"].startswith("Improved by the agent: "))
        self.assertEqual(seen["seeded"], seen["starting_draft"])
        self.assertEqual(seen["starting_draft"]["build_spec"]["visual_identity"],
                         previous["build_spec"]["visual_identity"])
        self.assertEqual(seen["starting_draft"]["build_spec"]["content"],
                         previous["build_spec"]["content"])
        self.assertNotIn("provenance", seen["starting_draft"])
        self.assertNotIn("consistency", seen["starting_draft"])
        self.assertNotIn("tiers", seen["starting_draft"]["scope"])
        self.assertFalse(seen["identity_kits"])
        # The delta: exactly what changed in the strategy, before and after.
        revision = seen["revision"]
        self.assertEqual(revision["revises_version"], 1)
        self.assertEqual(revision["revises"], previous["provenance"]["artifact_id"])
        delta = revision["strategy_delta"]
        self.assertTrue(delta["found"])
        fields = {change["field"]: change for change in delta["changes"]}
        self.assertEqual(list(fields), ["one_liner"])
        self.assertEqual(fields["one_liner"]["after"], self.GROWN)
        self.assertEqual(fields["one_liner"]["before"], design_tests.load_strategy()["one_liner"])
        # The rule: keep everything the change does not require changing.
        prompt = seen["rest"][0]
        self.assertIn("REVISION", prompt)
        self.assertIn("game-design version 1", prompt)
        self.assertIn("strategy_delta", prompt)
        self.assertIn("keep everything the", prompt)
        for kept in ("identity", "palette", "fonts", "assets", "controls", "UI"):
            self.assertIn(kept, prompt)
        self.assertNotIn("identity_kits", prompt)
        # Every other bar is still stated: content, depth and production art.
        for rule_id, _meaning in content_rules.RULES:
            self.assertIn(rule_id, prompt)
        self.assertIn("build_spec.depth", prompt)
        self.assertIn("quality_bar", prompt)
        # The revision records what it revises.
        design = result.artifacts[0].content
        self.assertTrue(design["fantasy"].startswith("Revised: Improved by the agent: "))
        self.assertEqual(design["provenance"]["supersedes"],
                         previous["provenance"]["artifact_id"])
        self.assertEqual(result.artifacts[0].metadata["revises"], 1)
        self.assertIn("revises v1", result.message)
        self.assertEqual(design["build_spec"]["visual_identity"],
                         previous["build_spec"]["visual_identity"])

    def test_repair_rounds_keep_the_revised_base(self):
        previous, ref = self.first_design()
        result = self.execute(self.config_with_prompt("revise-repairs"), self.grown_strategy(),
                              2, [ref])
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        repaired = self.seen("2-1-repair1")
        self.assertTrue(any("primary_input" in p for p in repaired["repair"]["problems"]))
        # The repair round works on the revised draft, and still names its base and delta.
        self.assertTrue(repaired["seeded"]["fantasy"].startswith("Revised: Improved by"))
        self.assertTrue(repaired["starting_draft"]["fantasy"].startswith("Improved by"))
        self.assertEqual(repaired["revision"]["revises_version"], 1)
        self.assertIn("REVISION", repaired["rest"][0])
        self.assertEqual(result.artifacts[0].content["provenance"]["supersedes"],
                         previous["provenance"]["artifact_id"])

    def test_a_resumed_revision_continues_its_own_repair_from_the_same_base(self):
        """#27's resume rule and the revision together: visit 2 fails its repair rounds, and
        the resumed execution of visit 2 repairs visit 2's last draft - not visit 1's design
        afresh, not the archetype - and the request still names the base and the delta."""
        previous, ref = self.first_design()
        failed = self.execute(self.config("invalid-enum"), self.grown_strategy(), 2, [ref])
        self.assertEqual((failed.outcome, failed.retryable), (StepOutcome.FAILED, False))
        self.assertTrue(os.path.isfile(os.path.join(self.run_dir, "design",
                                                    "2-last-draft.json")))
        result = self.execute(self.config_with_prompt("revise-repairs"), self.grown_strategy(),
                              2, [ref])
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        resumed = self.seen("2-1-repair0")
        self.assertTrue(any("primary_input" in p for p in resumed["repair"]["problems"]))
        self.assertEqual(resumed["seeded"]["build_spec"]["controls"]["primary_input"], "tap")
        self.assertEqual(resumed["revision"]["revises_version"], 1)
        self.assertEqual([c["field"] for c in resumed["revision"]["strategy_delta"]["changes"]],
                         ["one_liner"])
        self.assertTrue(resumed["starting_draft"]["fantasy"].startswith("Improved by"))
        self.assertEqual(result.artifacts[0].content["provenance"]["supersedes"],
                         previous["provenance"]["artifact_id"])

    def test_an_unchanged_strategy_still_revises_and_may_stand(self):
        previous, ref = self.first_design()
        result = self.execute(self.config("nothing"), design_tests.load_strategy(), 2, [ref])
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(result.artifacts[0].content["fantasy"], previous["fantasy"])
        self.assertEqual(result.artifacts[0].metadata["revises"], 1)

    def test_a_previous_design_changed_on_disk_is_refused(self):
        _previous, ref = self.first_design()
        with open(os.path.join(self.run_dir, *ref.location.split("/")), "a") as handle:
            handle.write(" ")
        result = self.execute(self.config("revise"), self.grown_strategy(), 2, [ref])
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("changed on disk", result.error)

    def test_the_archetype_author_does_not_revise(self):
        _previous, ref = self.first_design()
        result = self.execute({}, self.grown_strategy(), 2, [ref])
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertNotIn("supersedes", result.artifacts[0].content["provenance"])

    def test_design_gaps_keep_their_own_base_and_are_not_a_revision(self):
        """A design-gap return (#27) starts from the design the gaps were found in and answers
        them; the revision brief is not added on top of it."""
        previous = design_tests.run_step(design_tests.load_strategy()).artifacts[0].content
        gaps = [{"field": "build_spec.content.units[seg-opening].parameters",
                 "question": "What row gap does the opening segment use?"}]
        AgentAuthor().draft(self.brief(
            config=self.config("gaps"), gaps=gaps, previous_design=previous,
            revision={"version": 1, "artifact_id": "x", "design": previous,
                      "strategy_delta": {"found": True, "unchanged": True, "changes": [],
                                         "truncated": False}}))
        request = self.request_of("1-1-gaps")
        self.assertNotIn("revision", request)
        self.assertEqual([g["field"] for g in request["gaps"]], [gaps[0]["field"]])


class AGapVisitIsJudgedAgainstItsBase(AgentCase):
    """Found live (2026-10-05, a 3D run): design visit 2 answered its 15 gaps from greybox
    but failed a content rule after its repair rounds. Resumed, it restarted from that visit's
    last failed draft - which already held the answers - with the gaps first and the problems
    last; the agent reported every gap answered, edited nothing, and the step failed as "left
    the draft unchanged, so none of the 15 design gaps is answered". The draft that answered
    the gaps could not pass, and the round that could repair it was judged on "changed".

    A gap visit is judged against the design the gaps were found in (the game-design the build
    was made against), a repair round of it leads with the validation problems, and a gap made
    obsolete may be marked answered with a reason."""

    GAPS = [{"field": "build_spec.content.units[seg-opening].parameters",
             "question": "What row gap does the opening segment use?", "severity": "blocking"},
            {"field": "build_spec.tutorial", "question": "Which hint shows first?",
             "severity": "minor"}]

    def setUp(self):
        super().setUp()
        self.run_dir = os.path.join(self.scratch, "run")
        self.strategy = design_tests.load_strategy()
        first = design_tests.run_step(self.strategy)
        self.assertEqual(first.outcome, StepOutcome.SUCCESS, first.error)
        self.accepted = first.artifacts[0].content
        location = "artifacts/game-design/v1.json"
        path = os.path.join(self.run_dir, *location.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.accepted, handle)
        self.ref = ArtifactRef(id="game-design", type="game-design", version=1,
                               location=location, checksum="-",
                               content_hash=self.accepted["provenance"]["content_hash"])

    def visit(self, mode, gaps=None):
        """The design step in visit 2, re-entered through `design-gap` with GAPS."""
        report = {"design_gaps": copy.deepcopy(gaps or self.GAPS),
                  "provenance": {"artifact_id": "wgf:prototype-report:mock-title:20261005-01",
                                 "content_hash": "sha256:" + "cd" * 32}}
        context = design_tests.FakeContext(self.config(mode), run_dir=self.run_dir,
                                           previous_outputs=[self.ref], visit=2)
        step = design_tests.FixedClockStep(design_tests.FakeDefinition())
        return step.execute(design_tests.FakeInputs(self.strategy,
                                                    extra={"prototype-report": report}),
                            context)

    def seen(self, stem):
        with open(os.path.join(self.run_dir, "design", f"seen-{stem}.json"),
                  encoding="utf-8") as handle:
            return json.load(handle)

    def base(self):
        return {k: v for k, v in self.accepted.items() if k not in ("provenance", "consistency")}

    def test_a_draft_that_answers_the_gaps_but_is_invalid_is_repaired_problems_first(self):
        result = self.visit("gaps-repairs")
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        repair = self.seen("2-1-gaps-repair1")
        # A validation repair: the problems are the request's first key and the instruction's
        # first sentence, and the draft named is the one holding this visit's answers.
        self.assertEqual(repair["first_key"], "repair")
        self.assertTrue(any("primary_input" in p for p in repair["repair"]["problems"]))
        self.assertTrue(repair["instructions"].startswith("This round repairs the draft"))
        self.assertEqual(repair["repair"]["previous_draft"], repair["draft"])
        self.assertEqual(
            repair["seeded"]["build_spec"]["content"]["units"][0]["parameters"]["answered"], 1)
        # Its base is still the accepted design, not the failed draft.
        self.assertEqual(repair["previous"], self.base())
        design = result.artifacts[0].content
        self.assertEqual(design["build_spec"]["content"]["units"][0]["parameters"]["answered"],
                         1)
        self.assertEqual(design["build_spec"]["controls"]["primary_input"],
                         self.accepted["build_spec"]["controls"]["primary_input"])

    def test_a_repair_round_left_as_seeded_goes_back_to_the_checks_not_unchanged(self):
        from wgf_design.step import MAX_REPAIR_ROUNDS
        result = self.visit("gaps-invalid")
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertNotIn("unchanged", result.error)
        self.assertIn("not a valid game-design", result.error)
        self.assertIn("primary_input", result.error)
        rounds = [n for n in os.listdir(os.path.join(self.run_dir, "design"))
                  if n.endswith(".request.json")]
        self.assertEqual(len(rounds), MAX_REPAIR_ROUNDS + 1, rounds)

    def test_a_resumed_gap_visit_is_judged_against_the_accepted_design(self):
        failed = self.visit("gaps-invalid")
        self.assertEqual(failed.outcome, StepOutcome.FAILED)
        self.assertTrue(os.path.isfile(os.path.join(self.run_dir, "design",
                                                    "2-last-draft.json")))
        # The live case: resumed on the failed draft, the agent edits nothing. That draft
        # answers the gaps (it differs from the accepted design), so it is not "unchanged":
        # the step's checks name its problems again.
        stalled = self.visit("nothing")
        self.assertEqual(stalled.outcome, StepOutcome.FAILED)
        self.assertNotIn("unchanged", stalled.error)
        self.assertIn("primary_input", stalled.error)
        # Resumed with an agent that repairs: the base it is given is the accepted design,
        # and the problems lead.
        result = self.visit("gaps-repairs")
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        resumed = self.seen("2-1-gaps-repair0")
        self.assertEqual(resumed["first_key"], "repair")
        self.assertEqual(resumed["previous"], self.base())
        self.assertNotIn("answered",
                         resumed["previous"]["build_spec"]["content"]["units"][0]["parameters"])
        self.assertEqual(resumed["seeded"]["build_spec"]["controls"]["primary_input"], "tap")
        self.assertEqual(
            result.artifacts[0].content["build_spec"]["content"]["units"][0]["parameters"]
            ["answered"], 1)

    def test_a_draft_unchanged_from_the_accepted_design_still_fails(self):
        result = self.visit("nothing")
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("unchanged, so none of the 2 design gap(s) it was given is answered",
                      result.error)

    def test_obsolete_gaps_marked_answered_with_a_reason_stand_when_the_design_passes(self):
        result = self.visit("gaps-marked")
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertNotIn("gaps_answered", result.artifacts[0].content)
        with open(os.path.join(self.run_dir, "design", "2-gaps-answered.json"),
                  encoding="utf-8") as handle:
            kept = json.load(handle)
        self.assertEqual(kept["answered"], {"gap-1": "obsolete since a Factory fix",
                                            "gap-2": "obsolete since a Factory fix"})

    def test_a_gap_neither_answered_nor_marked_with_a_reason_fails_by_name(self):
        result = self.visit("gaps-half-marked")
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("1 of the 2 design gap(s) it was given are neither answered nor marked",
                      result.error)
        self.assertIn("gap-2 at build_spec.tutorial", result.error)
        self.assertNotIn("gap-1 at", result.error)


class TheStrategyDelta(unittest.TestCase):
    def test_changed_fields_by_path_with_before_and_after(self):
        from wgf_design.revision import strategy_delta
        delta = strategy_delta(
            {"provenance": {"x": 1}, "concept": {"levels": 12, "worlds": 2}, "risks": ["a"],
             "gone": 1},
            {"provenance": {"x": 2}, "concept": {"levels": 32, "worlds": 2},
             "risks": ["a", "b"], "new": 2})
        self.assertEqual(delta["changes"], [
            {"field": "concept.levels", "before": 12, "after": 32},
            {"field": "gone", "before": 1},
            {"field": "new", "after": 2},
            {"field": "risks", "before": ["a"], "after": ["a", "b"]}])
        self.assertFalse(delta["truncated"])
        self.assertTrue(strategy_delta({}, {str(i): i for i in range(5)}, limit=3)["truncated"])


if __name__ == "__main__":
    unittest.main()
