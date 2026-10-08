"""The playability step: the build is played from outside before anyone calls it playable.

    prototype-report (commit) + game-design (experience contract) + scaffold-record
      -> clone that commit into scratch, install, build (the game repository's own pnpm)
      -> bot.spec.ts on desktop and mobile viewports, behind the refusing network proxy:
         four fresh first sessions - idle, act, win (oracle), lose and retry (anti-oracle)
      -> analysis.judge: the checks, against build_spec.experience and the bars
      -> playability-report

    PASS      every required check passed on every viewport          SUCCESS
    FAIL      a required check failed: the build is what is wrong    FAILED, route `fail`,
              not retryable - the workflow routes it back to develop, whose next brief
              carries the failed checks and their frames
    BLOCKED   it could not be played here (no browser, the toolchain failed on a commit
              develop built): the environment, not the game          BLOCKED

The real checkout is never touched: the commit is cloned into the run's directory, so nothing
the bot does - a preview server, a build, test output - lands in the tree a reviewer
fingerprints or a developer commits. Every process goes through wgflib.procs; game code runs
with the allowlisted game environment (wgflib.agentenv), and the browser behind a proxy that
refuses every non-local request (wgflib.netguard). The frames stay beside the run as
evidence. This is automation evidence (`measurement_class: automation-bot`): it never stands
in for what first-time players understand.
"""

import copy
import datetime
import hashlib
import json
import os
import shutil
import socket

from wgflib import (agentenv, build_scope, check_strength, checkout, genre_models, paths, procs,
                    provenance)
from wgflib.netguard import BROWSER_BYPASS, BROWSER_PROXY_VAR, RefusingProxy, sandbox_env
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
from wgflib.workflow import references as pinned_references
from wgflib.workflow.quality import run_tier
from wgflib.yamllite import YamlError, load_file
from wgflib.yamllite import load as load_yaml

from wgf_design import commitments, existing, layouts
from wgf_design.content import quality_tier
from wgf_design.experience import load_rules as load_experience_rules

from . import analysis, realism

__all__ = ["PlayabilityStep", "RULES_PATH", "BOT_SPEC", "FAIL_ROUTE", "RECORDS", "PROJECTS"]

HERE = os.path.dirname(os.path.abspath(__file__))
BOT_SPEC = os.path.join(HERE, "bot.spec.ts")
RULES_PATH = os.path.join(paths.REFERENCE, "visual-quality.yaml")
FAIL_ROUTE = "fail"
REQUIRED_INPUTS = ("prototype-report", "game-design", "scaffold-record")
# Seconds a session run plays past the bar it is judged on, so a session that ends on its own
# beat (a new best, a unit cleared) is seen rather than cut off at the bar.
SESSION_MARGIN_S = 45



# The bars a run is held to as it pinned them when it started (new-game
# `pinned_references`): a resume on an updated Factory plays and judges the same way.
RULES_REF = "core/reference/visual-quality.yaml"
REALISM_REF = "core/reference/play-realism.yaml"


def pinned_yaml(context, relpath):
    """A reference file as the run pinned it (the live file for a run that pinned none).
    Raises references.PinError when the run's copy is gone or was edited."""
    text, _digest, _pinned = pinned_references.read(
        relpath, getattr(context, "environment", None), getattr(context, "run_dir", None))
    return load_yaml(text)


def _viewports(path=None, rules=None):
    """((id, width, height, device), ...) - the viewports the bot plays on, from
    core/reference/visual-quality.yaml `viewports` (`rules`: that file already read).
    Never defaulted in code."""
    found = []
    data = rules if rules is not None else load_file(path or RULES_PATH)
    for entry in (data or {}).get("viewports") or []:
        if isinstance(entry, dict) and entry.get("id"):
            found.append((str(entry["id"]), int(entry["width"]), int(entry["height"]),
                          str(entry.get("device") or "Desktop Chrome")))
    if not found:
        raise ValueError(f"{RULES_PATH} lists no viewports")
    return tuple(found)


VIEWPORTS = _viewports()
# (id, width, height) per viewport, as the report lists them.
PROJECTS = tuple(v[:3] for v in VIEWPORTS)
# The bot's records per viewport (bot.spec.ts): <out>/<project>/<name>.json.
RECORDS = ("first-session", "act", "win", "lose", "pause", "traverse", "persist", "session",
           "ramp", "showcase", "survey", "naive", "risk")
# How the survey is run (`survey`), and which entity roles carry a kind (`probe`): read by
# the content-sufficiency step too, which counts what the survey recorded.
SUFFICIENCY_PATH = os.path.join(paths.REFERENCE, "content-sufficiency.yaml")
# The design tiers a run's quality tier builds (`tiers[].builds.design_tiers`).
BENCHMARK_PATH = os.path.join(paths.REFERENCE, "quality-benchmark.yaml")
# Where the content data file of the commit played is kept, under the records directory, for
# the content-sufficiency step (scripts/wgf_sufficiency) to measure the build that was played.
CONTENT_DATA = "public/content/units.json"
CONTENT_COPY = os.path.join("content", "units.json")
_NO_BROWSER = ("Executable doesn't exist", "browserType.launch", "playwright install")
# The control actions that leave a finished unit for the next one. A vocabulary, not a bar: the
# design's own control action ids naming one of these words are added to it.
ADVANCE_ACTIONS = ("next", "continue", "advance", "proceed", "next-level", "next-unit", "play")
# The showcase test's window per viewport, in seconds: only a game whose probe declares the
# optional showcase capability spends it (staging the states where later content's assets are
# drawn, for the production gate). Outside the time budget the other tests share, so a game
# without one plays exactly as before; the process timeout grows by it instead.
SHOWCASE_S = 90

CONFIG = """\
// Generated by the Factory's playability step in a scratch clone. Serves the production
// build under dist/ with the repository's own `pnpm preview`.
import {{ defineConfig, devices }} from "@playwright/test";

const gl = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"];
// The Factory's refusing proxy, handed to the browser itself: Chromium ignores the proxy
// environment variables everywhere but Linux (wgflib.netguard).
const server = process.env["{proxy_var}"];
const proxy = server ? {{ proxy: {{ server, bypass: "{bypass}" }} }} : {{}};

export default defineConfig({{
  testDir: "tests/wgf-play",
  outputDir: "test-results/wgf-play",
  workers: 1,
  // A recording made on a degraded host is made again (visual-quality.yaml `environment`);
  // the bot skips any other retry, so a test that threw still records nothing.
  retries: {retries},
  timeout: 420_000,
  reporter: [["line"]],
  use: {{ baseURL: "http://localhost:{port}", launchOptions: {{ args: gl }}, ...proxy }},
  projects: [
__WGF_PROJECTS__
  ],
  webServer: {{
    command: "pnpm preview --port {port} --strictPort",
    port: {port},
    reuseExistingServer: false,
    timeout: 120_000,
  }},
}});
"""


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _sha256(path):
    with open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def load_rules(path=None):
    return load_file(path or RULES_PATH)


def projects_config(viewports=None):
    """The Playwright `projects` entries of the generated config, one per viewport."""
    lines = []
    for vid, width, height, device in viewports or VIEWPORTS:
        lines.append(f'    {{ name: {json.dumps(vid)}, use: {{ ...devices[{json.dumps(device)}], '
                     f'viewport: {{ width: {width}, height: {height} }} }} }},')
    return "\n".join(lines)


class PlayabilityStep(WorkflowStep):
    type = "playability"
    clock = staticmethod(_utc_now)

    def _run_viewports(self):
        """The viewports of the bars this run pinned (set by execute), else the live file's."""
        return getattr(self, "_viewports", None) or VIEWPORTS

    def _projects(self):
        return tuple(v[:3] for v in self._run_viewports())

    def execute(self, inputs, context):
        missing = [t for t in REQUIRED_INPUTS if t not in inputs]
        if missing:
            return StepResult.waiting_for_input(
                f"playability needs {', '.join(missing)} in the run: there is no build to play")
        design = inputs.load("game-design")
        scaffold = inputs.load("scaffold-record")
        prototype = inputs.load("prototype-report")
        ex = (design.get("build_spec") or {}).get("experience")
        if not isinstance(ex, dict):
            return StepResult.blocked(
                "the game-design has no experience contract (build_spec.experience, game-design "
                "1.5.0): a build is played against it. Run design again.")
        commit = ((prototype.get("build_ref") or {}).get("commit_sha") or "").strip()
        if len(commit) != 40:
            return StepResult.failed("prototype-report names no built commit", retryable=False)
        title_id = scaffold.get("title_id") or prototype.get("title_id") or design.get("title_id")
        repository = scaffold.get("repository") or {}
        try:
            located, _source = checkout.locate(context.config, scaffold, "playability",
                                               self.params, name=repository.get("name") or title_id,
                                               logger=context.logger)
        except checkout.CheckoutError as exc:
            return StepResult.blocked(f"no game checkout to play: {exc}")
        if not os.path.isdir(os.path.join(located, ".git")):
            return StepResult.blocked(f"no game checkout at {located}")

        try:
            rules = pinned_yaml(context, RULES_REF)
            self._viewports = _viewports(rules=rules)
        except pinned_references.PinError as exc:
            return StepResult.blocked(
                f"the visual-quality bars this run started under cannot be read ({exc}): no "
                "build is played against bars edited after the start")
        except (YamlError, ValueError) as exc:
            return StepResult.blocked(f"the visual-quality bars could not be read ({exc})")
        experience_rules = load_experience_rules()
        try:
            # The bars the content, difficulty and depth checks read: design-depth.yaml's
            # `playability` block with the genre family's `qa` overrides.
            qa = genre_models.qa_of(design)
            kinds_required = self._kinds_required(context, design)
            scope_tiers = self._scope_tiers(context, design)
            ramp_required = self._unmeasured_held(context, design, "depth.ramp")
            # Why each timing-sensitive check is not passed when the host never let it be
            # measured (or content.variety when the traverse cut its unit short), per check.
            unmeasured_held = {cid: why for cid in analysis.EVIDENCE
                               if (why := self._unmeasured_held(context, design, cid))}
            ramp_tiers = self._built_tiers(context, design, self.params)
            # The play-realism bars (core/reference/play-realism.yaml): what physics, naive play,
            # level geometry and the console are held to, and how hard at the run's tier.
            realism_rules = pinned_yaml(context, REALISM_REF)
            tier = (run_tier(getattr(context, "environment", None))
                    or quality_tier(design, None)[0])
            strength = realism.strength_for(
                realism_rules, tier,
                held=lambda cid: self._unmeasured_held(context, design, cid))
            accepted, accepted_error = self._accepted_play(self.params)
        except pinned_references.PinError as exc:
            return StepResult.blocked(
                f"the play-realism bars this run started under cannot be read ({exc}): no "
                "build is judged against bars edited after the start")
        except (OSError, YamlError, ValueError) as exc:
            return StepResult.blocked(
                f"the genre model and depth bars could not be read ({exc}): nothing can be held "
                "to them, and no bar is defaulted in code")
        if accepted_error:
            return StepResult.blocked(accepted_error)
        # Keyed by step: a workflow plays more than one build (greybox-playability,
        # playability), each step's visits count from 1, and this directory is emptied
        # first - one shared directory erased the greybox's frames its report cites.
        scratch = os.path.join(context.run_dir,
                               getattr(context, "current_step", None) or "playability",
                               f"{getattr(context, 'visit', 1)}-{getattr(context, 'attempt', 1)}")
        shutil.rmtree(scratch, ignore_errors=True)
        os.makedirs(scratch)
        repo, out, logs = (os.path.join(scratch, d) for d in ("repo", "out", "logs"))
        os.makedirs(logs)
        try:
            blocked = self._prepare(located, commit, repo, logs, context)
            if blocked:
                return self._finish(context, inputs, title_id, commit, [], [], rules, blocked)
            idle_ms = max((experience_rules.get("onboarding") or {}).get("min_grace_s", 10),
                          (ex.get("onboarding") or {}).get("grace", {}).get("seconds") or 0) * 1000
            settings = {
                "idle_ms": int(idle_ms),
                "ack_ms": int(next((a.get("max_ack_ms") for a in ex.get("actions") or []), None)
                              or (experience_rules.get("feedback") or {}).get("max_ack_ms", 100)),
                "win_ms": int((rules.get("budgets") or {}).get("win_s", 180) * 1000),
                "lose_ms": int((rules.get("budgets") or {}).get("lose_s", 90) * 1000),
                "start_timeout_ms": 30000,
                "goal_metric": (ex.get("goal") or {}).get("metric"),
                "has_win": "win" in ex,
                "showcase_ms": SHOWCASE_S * 1000,
            }
            content_settings, truncated, total_s = self._content_settings(design, qa, settings,
                                                                          ramp_tiers)
            settings.update(content_settings)
            settings.update(self._validity_settings(rules, qa, content_settings))
            # An adopted checkout with no content data file: its floor is counted on this
            # play when it is the shipped build (wgf_design/existing.py), and the traverse
            # plays on past the bar's few units to reach what it ships.
            floor, measuring = self._floor_state(design, commit, context)
            if measuring:
                settings["max_units"] = max(settings["max_units"], self._probe_max_units())
            settings.update(self._survey_settings(design, self.params))
            settings.update(self._naive_settings(design, realism_rules, scope_tiers,
                                                 accepted is not None))
            settings.update(self._risk_settings(design, realism_rules, self.params, scope_tiers))
            self._keep_content_data(repo, out)
            blocked = self._play(repo, out, logs, settings, context, total_s,
                                 survey_s=settings["survey_ms"] / 1000.0,
                                 extend_s=settings["ramp_extend_ms"] / 1000.0,
                                 realism_s=self._realism_window_s(settings))
            judged = copy.deepcopy(rules)
            judged["_idle_ms"] = settings["idle_ms"]
            judged["_truncated"] = truncated
            checks, frames, projects, played = [], [], [], {}
            for project, width, height in self._projects():
                records = self._records(os.path.join(out, project))
                played[project] = records
                frames_dir = os.path.join(out, project, "frames")
                errors = sorted({e for r in records.values() for e in r.get("errors") or []})
                projects.append({"id": project, "viewport": {"width": width, "height": height},
                                 "ran": bool(records), "page_errors": errors[:10]})
                if records:
                    checks += analysis.judge(records, frames_dir, design, judged,
                                             experience_rules, project, qa=qa,
                                             kinds_required=kinds_required,
                                             scope_tiers=scope_tiers,
                                             ramp_required=ramp_required,
                                             ramp_tiers=ramp_tiers,
                                             unmeasured_held=unmeasured_held)
                    # Physics, naive play and the console, held as the host allowed them to
                    # be measured (a degraded host never softens a failure).
                    checks += analysis._environment(
                        realism.judge(records, design, realism_rules, project, strength,
                                      self._built_units(design, scope_tiers), accepted),
                        records, rules.get("environment") or {}, unmeasured_held)
                frames += self._frames(frames_dir, project, context.run_dir)
            # The level geometry the played commit declares: once per build, not per viewport.
            checks += self._layout_checks(out, design, realism_rules, strength, scope_tiers)
            # Clearance is a proxy: it blocks only a unit whose clear rate was not measured.
            checks = realism.gate_clearance(checks, strength)
            if not blocked and not any(p["ran"] for p in projects):
                blocked = "the bot produced no records on any viewport; see " + os.path.join(logs, "bot.log")
            records_dir = (os.path.relpath(out, context.run_dir).replace(os.sep, "/")
                           if os.path.isdir(out) else None)
            if measuring and not blocked:
                floor, note = existing.probe_floor(
                    floor, played, commit, step=getattr(context, "current_step", None))
                context.logger.info("existing-content floor", floor=note)
            return self._finish(context, inputs, title_id, commit, checks, frames, rules, blocked,
                                projects, records_dir,
                                floor=floor if existing.measured(floor) else None)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    @staticmethod
    def _floor_state(design, commit, context):
        """(floor, measuring). The probe floor the run already measured, carried unchanged
        (a floor once measured is never measured again); else the design's unmeasured floor,
        with `measuring` true when this visit plays its commit - the shipped build, before any
        developer change; else (None, False): the run adopted nothing, or its floor is counted
        on a content data file."""
        floor = (design or {}).get("existing_content")
        if not isinstance(floor, dict):
            return None, False
        if existing.measured(floor):
            # Counted on the content data file, or on the probe by an earlier visit that a
            # re-entered design recorded: nothing to measure, nothing to carry.
            return (floor if existing.method(floor) == existing.PROBE else None), False
        carried = existing.run_probe_floor(getattr(context, "run_dir", None), floor)
        if carried is not None:
            return carried, False
        at = str((floor.get("source") or {}).get("commit") or "")
        if at and (commit.startswith(at) or at.startswith(commit)):
            return floor, True
        context.logger.warning(
            "the existing-content floor stays unmeasured: this visit does not play the shipped "
            "build", played=commit, shipped=at)
        return floor, False

    @staticmethod
    def _probe_max_units():
        rules = (commitments.load().get("existing_content") or {}).get("probe") or {}
        return int(rules.get("max_units") or 0)

    @staticmethod
    def _scope_tiers(context, design):
        """The design tiers the run builds (wgflib.build_scope): its quality tier's
        quality-benchmark `tiers[].builds.design_tiers` - the tier the design states, else the
        run's. Every unit of them is a design unit the probe may report; at a release tier
        that is the post-mvp units too, which the tech plan planned and the developer built."""
        return build_scope.design_tiers(
            design, run=run_tier(getattr(context, "environment", None)))

    @staticmethod
    def _kinds_required(context, design):
        """Why content.variety fails on a probe that omits entity kinds while a content unit
        is in play, or None when it stays an unmeasured WARNING: the run's quality tier (else
        the design's) against core/reference/quality-policy.yaml rule 5."""
        return PlayabilityStep._unmeasured_held(context, design, "content.variety")

    @staticmethod
    def _built_tiers(context, design, params):
        """The design tiers the build played here carries: the MVP for the greybox
        (`with: {phase: greybox}`), else those the run's quality tier builds
        (core/reference/quality-benchmark.yaml `tiers[].builds.design_tiers`), the MVP when
        the benchmark states none for it."""
        if (params or {}).get("phase") == "greybox":
            return ["mvp"]
        tier = (run_tier(getattr(context, "environment", None))
                or quality_tier(design, None)[0])
        for entry in (load_file(BENCHMARK_PATH) or {}).get("tiers") or []:
            if isinstance(entry, dict) and entry.get("id") == tier:
                tiers = (entry.get("builds") or {}).get("design_tiers")
                if tiers:
                    return [str(t) for t in tiers]
        return ["mvp"]

    @staticmethod
    def _unmeasured_held(context, design, check):
        """Why `check` fails when it measured nothing, or None when it stays an unmeasured
        WARNING: the run's quality tier (else the design's) against
        core/reference/quality-policy.yaml rule 5."""
        tier = (run_tier(getattr(context, "environment", None))
                or quality_tier(design, None)[0])
        strength = check_strength.for_tier(tier)
        steps = ("playability", getattr(context, "current_step", None))
        if not strength.required(check, steps):
            return None
        return (f"at quality tier {tier} a check that measured nothing is not passed "
                f"(core/reference/quality-policy.yaml skipped_checks)")

    # -- what the bot is given ----------------------------------------------------------

    @staticmethod
    def _content_settings(design, qa, settings, ramp_tiers=None):
        """(the CFG the content, persist and session tests read, which of them were cut, the
        viewport's whole time budget in seconds).

        The time budget (design-depth.yaml `playability.time_budget.bot_total_s`) is a hard cap
        per viewport. What the first-session, act, win, lose and pause tests already cost is
        subtracted; whatever is left is shared out between the traverse, persist and session
        windows in proportion to what they asked for, and every check judged from a window that
        was cut is marked `truncated`. A design whose time ramp is read on a mode it includes
        (analysis.time_ramp) asks for `ramp.samples` x `ramp.run_s` more: the ramp test plays
        that many fresh runs of the endless play or mode, and may play whole further samples
        within `ramp.extend_s` while the pooled counts are too few or inside the noise band.
        """
        spec = (design or {}).get("build_spec") or {}
        content, _mode, units = analysis.content_units(design)
        depth = spec.get("depth") or {}
        budget = qa.get("time_budget") or {}
        bars = qa.get("content") or {}
        session_bars = qa.get("session_length") or {}
        ramp_bars = qa.get("ramp") or {}
        ramp = analysis.time_ramp(design, qa, ramp_tiers)
        genre = qa.get("genre") or {}
        target_s = ((depth.get("first_session") or {}).get("target_s") or 0)
        content_applies = content is not None
        depth_applies = bool(depth.get("meta_loop") or depth.get("first_session"))
        on_mode = bool(depth_applies and ramp and ramp["run"] == "mode")
        # The time ramp is read on `ramp.samples` fresh runs of its play, each `run_s` long -
        # the session's endless play or the mode's - in the ramp test, never on the session.
        sampled = bool(depth_applies and ramp)
        planned = int(ramp_bars.get("samples") or 0) if sampled else 0
        asked = {
            "traverse": (budget.get("traverse_s") or 0) * 1000 if content_applies else 0,
            "persist": (budget.get("persist_s") or 0) * 1000 if depth_applies else 0,
            # Never play longer than the bar needs: the check passes at
            # `min_share` x target, so a window of that plus a margin measures everything a
            # `max_multiplier` window would, and the run (and every measurement after it on
            # the same machine) is minutes shorter.
            "session": (min(target_s * (session_bars.get("max_multiplier") or 0),
                            target_s * (session_bars.get("min_share") or 0) + SESSION_MARGIN_S)
                        * 1000 if depth_applies else 0),
            "ramp": planned * (ramp_bars.get("run_s") or 0) * 1000,
        }
        total_s = budget.get("bot_total_s") or 0
        spent = (settings["idle_ms"] + settings["win_ms"] + settings["lose_ms"]
                 + 2 * settings["start_timeout_ms"])
        room = max(0, total_s * 1000 - spent)
        wanted = sum(asked.values())
        scale = min(1.0, room / wanted) if wanted else 1.0
        truncated = {name: bool(ms and scale < 1.0) for name, ms in asked.items()}
        want_units = min(len(units), int(bars.get("min_units_traversed") or 1)) if units else 0
        actions = [a.get("id") for a in ((spec.get("controls") or {}).get("actions") or [])
                   if isinstance(a, dict) and isinstance(a.get("id"), str)
                   and any(word in a["id"].lower() for word in ADVANCE_ACTIONS)]
        session_ms = int(asked["session"] * scale)
        return {
            "content_applies": content_applies,
            "depth_applies": depth_applies,
            "unit_count": len(units),
            "max_units": want_units + 1,
            "traverse_ms": int(asked["traverse"] * scale),
            "persist_ms": int(asked["persist"] * scale),
            "session_target_ms": int(target_s * 1000),
            "session_max_ms": session_ms,
            "window_ms": int(((qa.get("difficulty") or {}).get("endless_window_s") or 0) * 1000),
            "axes": [a["id"] for a in genre_models.axes_of(design)],
            "advance_actions": sorted(set(actions) | set(ADVANCE_ACTIONS)),
            "reset_in_unit": bool(genre.get("reset_in_unit")),
            # The time ramp's run (analysis.time_ramp): `session` or `mode` (the bot enters
            # `ramp_mode` through the probe's play.mode and plays it for ramp_ms), else none.
            "ramp_run": (ramp or {}).get("run") if depth_applies else None,
            "ramp_mode": ramp["mode"] if on_mode else None,
            # Per sample: ramp_ms (the budget's share, split evenly between the planned
            # samples), the pooled-count rule the bot extends on, and the stall bar.
            "ramp_ms": int(asked["ramp"] * scale / planned) if planned else 0,
            "ramp_samples": planned,
            "ramp_noise_z": float(ramp_bars.get("noise_z") or 0) if sampled else 0,
            "ramp_min_inputs": int(ramp_bars.get("min_inputs_per_third") or 0)
                               if sampled else 0,
            "ramp_extend_ms": int((ramp_bars.get("extend_s") or 0) * 1000) if sampled else 0,
            "ramp_stall_ms": int((ramp_bars.get("stall_max_s") or 0) * 1000) if sampled else 0,
        }, truncated, total_s

    @staticmethod
    def _validity_settings(rules, qa, content_settings):
        """The CFG that keeps a measurement honest (visual-quality.yaml `environment` and
        `sample`): the bars a recording's host is judged degraded by, how many attempts a
        recording read by a timing-sensitive check may take (analysis.RETRIED_RECORDS), and how
        long the traverse plays on in a unit it stopped inside while that unit has shown fewer
        new kinds than the family asks (only a family that asks for one, with authored units)."""
        env = rules.get("environment") or {}
        sample = rules.get("sample") or {}
        want_new = int((qa.get("genre") or {}).get("min_new_kinds_per_unit") or 0)
        return {
            "environment": {key: env.get(key) for key in (
                "tick_ms", "stall_ms", "max_stall_ms", "max_stalled_share",
                "max_server_wait_ms", "max_attempts")},
            "retry_records": list(analysis.RETRIED_RECORDS),
            "min_new_kinds": want_new if content_settings.get("content_applies") else 0,
            "variety_extend_ms": (int((sample.get("variety_extend_s") or 0) * 1000)
                                  if want_new and content_settings.get("content_applies") else 0),
        }

    @staticmethod
    def _survey_settings(design, params, path=None):
        """The survey's CFG: every unit the design lists (but `optional` ones) when the step
        is asked for a survey (`with: survey: true`) and the design authors its units; else
        no unit, and the bot records that no survey was asked for."""
        rules = load_file(path or SUFFICIENCY_PATH)
        survey = rules.get("survey") or {}
        probe = rules.get("probe") or {}
        content, mode, _units = analysis.content_units(design)
        listed = [u for u in (content or {}).get("units") or []
                  if isinstance(u, dict) and u.get("id") and u.get("tier") != "optional"]
        listed.sort(key=lambda u: (u.get("index") if isinstance(u.get("index"), int)
                                   else 10 ** 6, str(u.get("id"))))
        asked = bool((params or {}).get("survey")) and mode == "authored"
        return {
            "survey_units": [str(u["id"]) for u in listed] if asked else [],
            "survey_projects": list(survey.get("projects") or []),
            "survey_unit_ms": int((survey.get("unit_s") or 0) * 1000),
            "survey_ms": int((survey.get("total_s") or 0) * 1000) if asked and listed else 0,
            "kind_roles": list(probe.get("kind_roles") or []),
            "not_content_roles": list(probe.get("not_content_roles") or []),
        }

    @staticmethod
    def _naive_settings(design, rules, scope_tiers=None, compare=False):
        """The naive test's CFG (core/reference/play-realism.yaml `naive`): the units it plays
        beside the opening one - the middle and last of the authored units the build carries,
        entered through the probe's unit link - the policies, how they err, and how many times
        each (more than once only to compare clear rates with an accepted build)."""
        naive = rules.get("naive") or {}
        _content, mode, _units = analysis.content_units(design)
        built = PlayabilityStep._built_units(design, scope_tiers)
        extra = (realism.naive_units(built, int(naive.get("units") or 1))
                 if mode == "authored" else [])
        return {
            "naive_units": extra,
            "naive_projects": list(naive.get("projects") or []),
            "naive_run_ms": int((naive.get("run_s") or 0) * 1000),
            "naive_repeats": (int((rules.get("clear_rate") or {}).get("runs") or 1)
                              if compare else 1),
            "naive_policies": {k: list(v or []) for k, v in (naive.get("policies") or {}).items()},
            "naive_jitter_px": float(naive.get("jitter_px") or 0),
            "naive_reaction_ms": int(naive.get("reaction_ms") or 0),
            "naive_error_rate": float(naive.get("error_rate") or 0),
            "naive_seed": int(naive.get("seed") or 1),
        }

    @staticmethod
    def _risk_settings(design, rules, params, scope_tiers=None):
        """The risk test's CFG (play-realism.yaml `risk`), only with `with: risk: true`: the
        units it plays - spread across the authored units the build carries, else play from
        the start (an empty id) - under the game's own oracle policies. Not asked: none."""
        risk = rules.get("risk") or {}
        if not (params or {}).get("risk"):
            return {"risk_units": [], "risk_projects": [], "risk_policies": [],
                    "risk_attempts": 0, "risk_attempt_ms": 0, "risk_ms": 0}
        _content, mode, _units = analysis.content_units(design)
        built = [u.get("id") for u in sorted(PlayabilityStep._built_units(design, scope_tiers),
                                             key=lambda u: (u.get("index") or 0))
                 if isinstance(u, dict) and u.get("id")]
        count = int(risk.get("units") or 0)
        if mode == "authored" and built:
            units = ([built[0]] + realism.naive_units(
                [{"id": b, "index": i} for i, b in enumerate(built)], count))[:count]
        else:
            units = [""]
        return {
            "risk_units": units,
            "risk_projects": list(risk.get("projects") or []),
            "risk_policies": [str(p) for p in risk.get("policies") or []],
            "risk_attempts": int(risk.get("attempts") or 0),
            "risk_attempt_ms": int((risk.get("attempt_s") or 0) * 1000),
            "risk_ms": int((risk.get("total_s") or 0) * 1000),
        }

    @staticmethod
    def _realism_window_s(settings):
        """Seconds the naive and risk tests may take on all their viewports: every unit, under
        at most two policies, as many times as asked, for its run plus a start; the risk test's
        window with a start per attempt. Outside the time budget the other tests share, like
        the showcase: a game plays exactly as long as before, and the process timeout grows."""
        start = settings["start_timeout_ms"] / 1000.0
        units = 1 + len(settings.get("naive_units") or [])
        policies = max([len(v) for v in (settings.get("naive_policies") or {}).values()] or [0])
        per_run = settings.get("naive_run_ms", 0) / 1000.0 + start + 5
        naive = (len(settings.get("naive_projects") or []) * units * policies
                 * int(settings.get("naive_repeats") or 1) * per_run)
        attempts = (len(settings.get("risk_units") or []) * len(settings.get("risk_policies") or [])
                    * int(settings.get("risk_attempts") or 0))
        risk = (len(settings.get("risk_projects") or [])
                * (settings.get("risk_ms", 0) / 1000.0 + attempts * (start + 2) + 60)
                if attempts else 0)
        return naive + risk

    @staticmethod
    def _built_units(design, scope_tiers=None):
        """The design's content units of the tiers this build carries (all of them when the
        tiers are not known)."""
        if scope_tiers:
            return analysis.content_units(design, tuple(scope_tiers))[2]
        return analysis.content_units(design)[2]

    @staticmethod
    def _accepted_play(params):
        """(the accepted build's naive record or clear-rate table, None) from the step's
        `with: accepted_play` - a JSON file, absolute or under the project - else (None,
        None); (None, why) when the file it names cannot be read."""
        named = (params or {}).get("accepted_play")
        if not named:
            return None, None
        path = str(named)
        if not os.path.isabs(path):
            path = os.path.join(paths.PROJECT, path)
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle), None
        except (OSError, ValueError) as exc:
            return None, (f"with: accepted_play names {named}, which cannot be read ({exc}): "
                          "the clear rates cannot be compared with the accepted build")

    @staticmethod
    def _layout_checks(out, design, rules, strength, scope_tiers=None, path=None):
        """level.geometry, level.unit_length and level.clearance over the content data file
        and layout source the played commit ships (copied beside the records)."""
        content_dir = os.path.join(out, os.path.dirname(CONTENT_COPY))
        try:
            with open(os.path.join(out, CONTENT_COPY), encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return []
        contract = load_file(path or SUFFICIENCY_PATH)
        source, _why = layouts.read_source(content_dir, data, contract)
        return realism.judge_layouts(data, rules, strength, source,
                                     PlayabilityStep._built_units(design, scope_tiers),
                                     unit_key=layouts.unit_key(contract))

    @staticmethod
    def _keep_content_data(repo, out, path=None):
        """Copy the commit's content data file beside the records, when it ships one, and the
        layout source it measures unit geometry on (content-sufficiency.yaml `layout.source`,
        or the data file's `layout_source`; only a file under public/content)."""
        source = os.path.join(repo, *CONTENT_DATA.split("/"))
        if not os.path.isfile(source):
            return
        target = os.path.join(out, CONTENT_COPY)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(source, target)
        try:
            with open(source, encoding="utf-8") as handle:
                data = json.load(handle)
            found = layouts.source_of(data, load_file(path or SUFFICIENCY_PATH))
        except (OSError, ValueError, YamlError):
            return
        if not found:
            return
        relative = found[0]
        origin = os.path.join(repo, *layouts.CONTENT_DIR.split("/"), *relative.split("/"))
        if os.path.isfile(origin):
            kept = os.path.join(os.path.dirname(target), *relative.split("/"))
            os.makedirs(os.path.dirname(kept), exist_ok=True)
            shutil.copyfile(origin, kept)

    # -- running ------------------------------------------------------------------------

    def _env(self, context):
        return agentenv.scrubbed(agentenv.game_passthrough(context.config))

    def _run(self, argv, cwd, timeout, log, env=None, context=None):
        result = procs.run(argv, cwd=cwd, timeout=timeout, env=env, log_path=log,
                           stderr_to_stdout=True)
        return result

    def _prepare(self, located, commit, repo, logs, context):
        """None when the commit is cloned, installed and built; else why it is blocked."""
        clone = self._run(["git", "clone", "--quiet", "--no-checkout", located, repo], None, 600,
                          os.path.join(logs, "clone.log"))
        if not clone.ok:
            return f"could not clone {located}: {clone.tail(5)}"
        switch = self._run(["git", "-C", repo, "checkout", "--quiet", "--detach", commit], None,
                           300, os.path.join(logs, "clone.log"))
        if not switch.ok:
            return f"commit {commit} is not in {located}"
        env = self._env(context)
        for argv, name in ((["pnpm", "install", "--frozen-lockfile", "--prefer-offline"], "install"),
                           (["pnpm", "build"], "build")):
            run = self._run(argv, repo, 1800, os.path.join(logs, f"{name}.log"), env=env)
            if not run.ok:
                return (f"`{' '.join(argv)}` failed on {commit[:12]}, which develop built: "
                        f"the environment, not the game ({os.path.join(logs, name + '.log')})")
        return None

    def _play(self, repo, out, logs, settings, context, bot_total_s=0, survey_s=0,
              extend_s=0, realism_s=0):
        """Run the bot. None when it ran (whatever it found); else why it could not."""
        port = _free_port()
        os.makedirs(os.path.join(repo, "tests", "wgf-play"), exist_ok=True)
        shutil.copy(BOT_SPEC, os.path.join(repo, "tests", "wgf-play", "bot.spec.ts"))
        with open(os.path.join(repo, "playwright.wgf-play.config.ts"), "w", encoding="utf-8") as h:
            retries = max(0, int((settings.get("environment") or {}).get("max_attempts") or 1) - 1)
            h.write(CONFIG.format(port=port, proxy_var=BROWSER_PROXY_VAR, bypass=BROWSER_BYPASS,
                                  retries=retries).replace("__WGF_PROJECTS__",
                                                           projects_config(self._run_viewports())))
        config_path = os.path.join(out, "settings.json")
        os.makedirs(out, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump(settings, handle)
        env = self._env(context)
        env.update(WGF_PLAY_OUT=out, WGF_PLAY_CONFIG=config_path)
        guard = RefusingProxy().start()
        env.update(sandbox_env(guard.url))
        # The bot's own budget decides the timeout, not a fixed number: two viewports of
        # bot_total_s and of the showcase (its window, the start before it and the last state
        # it stages), plus the install-free start-up and the report - and the survey's window
        # with a start per unit, on the projects it runs on. The ramp may play further
        # samples past its window (`extend_s`) on each viewport, and starts every sample on a
        # fresh page.
        survey_units = len(settings.get("survey_units") or [])
        ramp_ms = settings.get("ramp_ms") or 0
        ramp_starts = ((settings.get("ramp_samples") or 0)
                       + int((settings.get("ramp_extend_ms") or 0) // ramp_ms)) if ramp_ms else 0
        survey = (len(settings.get("survey_projects") or [])
                  * (survey_s + survey_units * (settings["start_timeout_ms"] / 1000.0 + 2) + 60)
                  if survey_units else 0)
        timeout = int(2 * (bot_total_s or 0) + 2 * (SHOWCASE_S + 45) + 120 + survey
                      + 2 * (extend_s or 0) + 2 * self._again_s(settings)
                      + 2 * ramp_starts * settings["start_timeout_ms"] / 1000.0
                      + (realism_s or 0))
        try:
            run = self._run(["pnpm", "exec", "playwright", "test", "-c",
                             "playwright.wgf-play.config.ts"], repo, timeout,
                            os.path.join(logs, "bot.log"), env=env)
        finally:
            guard.stop()
        if not run.ok and any(marker in (run.output or "") for marker in _NO_BROWSER):
            return "no browser to play the build in here (playwright install chromium)"
        return None

    @staticmethod
    def _again_s(settings):
        """Per viewport, the most the bot may spend making a recording again on a degraded host
        (each retried recording's window and its start, once per further attempt - the ramp's
        every sample, planned and extended, each on a fresh page) and playing on in a unit the
        traverse cut short (on every attempt): nothing on a healthy host whose units show their
        kinds, but the process timeout must allow it."""
        attempts = int((settings.get("environment") or {}).get("max_attempts") or 1)
        ramp_ms = settings.get("ramp_ms") or 0
        ramp_samples = ((settings.get("ramp_samples") or 0)
                        + int((settings.get("ramp_extend_ms") or 0) // ramp_ms)) if ramp_ms else 0
        windows = (settings.get("idle_ms", 0) + settings.get("win_ms", 0)
                   + settings.get("lose_ms", 0) + settings.get("traverse_ms", 0)
                   + 4 * settings.get("start_timeout_ms", 0)
                   + ramp_samples * (ramp_ms + settings.get("start_timeout_ms", 0)))
        # The naive recording is made again on a degraded host too (analysis.RETRIED_RECORDS).
        naive = (bool(settings.get("naive_projects"))
                 * (1 + len(settings.get("naive_units") or []))
                 * max([len(v) for v in (settings.get("naive_policies") or {}).values()] or [0])
                 * int(settings.get("naive_repeats") or 1)
                 * (settings.get("naive_run_ms", 0) + settings.get("start_timeout_ms", 0)))
        return ((attempts - 1) * (windows + naive)
                + attempts * settings.get("variety_extend_ms", 0)) / 1000.0

    @staticmethod
    def _records(directory):
        records = {}
        for name in RECORDS:
            path = os.path.join(directory, f"{name}.json")
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as handle:
                    records[name] = json.load(handle)
        return records

    @staticmethod
    def _frames(frames_dir, project, run_dir):
        found = []
        if not os.path.isdir(frames_dir):
            return found
        for name in sorted(os.listdir(frames_dir)):
            if not name.endswith(".png"):
                continue
            path = os.path.join(frames_dir, name)
            entry = {"id": name[:-4], "project": project,
                     "path": os.path.relpath(path, run_dir).replace(os.sep, "/"),
                     "sha256": _sha256(path)}
            if not name.startswith("act-"):
                try:
                    (entry["mean_luminance"], entry["contrast"],
                     entry["lit_share"]) = analysis.frame_stats(path)
                except Exception:  # a frame that cannot be read is still listed  # noqa: BLE001
                    pass
            found.append(entry)
        return found

    # -- the report ---------------------------------------------------------------------

    def _finish(self, context, inputs, title_id, commit, checks, frames, rules, blocked,
                projects=None, records_dir=None, floor=None):
        failed = sorted({f"{c['project']}:{c['id']}" for c in checks
                         if c["required"] and c["status"] == "FAIL"})
        # A skipped check measured nothing, because the design claims nothing it could measure.
        # Listed once per id with its reason: a reader counting passes subtracts these.
        skipped = []
        for check in checks:
            if check["status"] == "SKIPPED" and check["id"] not in {s["id"] for s in skipped}:
                skipped.append({"id": check["id"], "reason": check["summary"]})
        # A required check the host never let be measured, or whose unit the traverse cut
        # short, is not a defect of the build to send back to develop - and never a pass: the
        # step is BLOCKED for a person (resume on a quieter host) unless a real failure
        # already sends the build back.
        unmeasured = sorted({f"{c['project']}:{c['id']}" for c in checks
                             if c["required"] and c["status"] == "BLOCKED"
                             and isinstance(c.get("measured"), dict)
                             and c["measured"].get("unmeasured")
                             in (analysis.ENVIRONMENT_DEGRADED, analysis.SAMPLE_CUT)})
        if unmeasured and not blocked and not failed:
            blocked = (f"{len(unmeasured)} required playability check(s) could not be measured "
                       f"and are not passed: {', '.join(unmeasured[:8])} - "
                       + "; ".join(sorted({c["summary"] for c in checks
                                           if f"{c['project']}:{c['id']}" in unmeasured})[:3]))
        verdict = "BLOCKED" if blocked else ("FAIL" if failed else "PASS")
        now = self.clock()
        artifact_id = provenance.artifact_id("playability-report", title_id, now,
                                             getattr(context, "execution", 1))
        report = {
            "provenance": provenance.build(
                "playability-report",
                artifact_id=artifact_id,
                produced_by=provenance.producer("qa"), produced_at=now,
                inputs=provenance.pin_inputs(inputs, REQUIRED_INPUTS), title_id=title_id),
            "title_id": title_id,
            "commit": commit,
            "measurement_class": "automation-bot",
            "projects": projects or [{"id": p, "viewport": {"width": w, "height": h}, "ran": False}
                                     for p, w, h in self._projects()],
            "checks": checks,
            "frames": frames,
            "records_dir": records_dir,
            "failed_checks": failed,
            "skipped_checks": skipped,
            "blocked_reason": blocked,
            "verdict": verdict,
        }
        if existing.measured(floor):
            # The adopted build's floor, counted on this play or carried from the visit that
            # counted it; the source names the report it was counted on.
            floor = copy.deepcopy(floor)
            floor["source"].setdefault("report", artifact_id)
            report["existing_content"] = floor
        output = ArtifactOutput("playability-report", provenance.seal(report),
                                metadata={"verdict": verdict, "failed": len(failed),
                                          "skipped": len(skipped), "commit": commit})
        if blocked:
            context.logger.warning("playability blocked", reason=blocked)
            return StepResult("BLOCKED", artifacts=[output], message=blocked)
        if failed:
            summaries = [f"{c['project']}:{c['id']}: {c['summary']}" for c in checks
                         if c["required"] and c["status"] == "FAIL"]
            context.logger.error("the build is not playable from outside", failed=failed)
            return StepResult("FAILED", route=FAIL_ROUTE, artifacts=[output], retryable=False,
                              error=f"{len(failed)} playability check(s) failed: "
                                    + "; ".join(summaries[:6]) + self._skipped_note(skipped))
        return StepResult.success([output], message=(
            f"played {commit[:12]} on {', '.join(p['id'] for p in report['projects'] if p['ran'])}: "
            f"{sum(1 for c in checks if c['status'] == 'PASS')} checks passed"
            + self._skipped_note(skipped)))

    @staticmethod
    def _skipped_note(skipped):
        """A skip is never a pass: the summary names every one of them."""
        if not skipped:
            return ""
        return (f". {len(skipped)} check(s) measured nothing, because the design claims nothing "
                "they measure (not passes): " + ", ".join(s["id"] for s in skipped))
