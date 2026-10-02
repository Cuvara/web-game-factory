"""The `agent` design author: an agent host writes the design draft; the module judges it.

Opt-in. An installation selects it in workspace/config/factory.yaml:

    factory:
      design:
        author: agent
        agent:
          argv: [...]                # the host's non-interactive command; placeholders below
          timeout_seconds: 1800      # wall clock
          idle_timeout_seconds: 600  # no output for this long ends the attempt
          draft_from: file           # file: the agent edits {draft}, seeded with the
                                     # starting (or, on a repair, the previous) draft
                                     # stdout: it prints the draft JSON last

`argv` placeholders, substituted per element and never re-formatted: {request} (the request
JSON: strategy, resolved platforms, title id, and the built-in archetype's draft as a
schema-shaped starting point), {draft} (where to write the draft JSON), {prompt} (a
one-paragraph instruction).

The agent only writes a DRAFT. Everything after it is the design module's, unchanged: platform
absorption and tier derivation (`finalize`), the buildability check and the consistency rules,
including the `descope` route. An agent cannot mark its own homework, and nothing here
relaxes a check to let its draft through.

The host runs with the allowlisted agent environment (wgflib.agentenv), exactly as the
developer and the reviewer do: nothing of the Factory's own environment beyond the
allowlist and `factory.agents.env_passthrough` (where the host's credential is named).

Outcomes: a draft whose shape is wrong (not JSON, a missing section) is an `AuthorError` -
not retryable, the same draft would come back. A draft that is well-shaped but makes an
invalid design - a value the game-design schema does not allow, a state machine buildability
refuses - is shown to the agent with exactly those problems and the previous draft, and
asked again (the design step's `MAX_REPAIR_ROUNDS`); every round is judged like the first,
and one still invalid after the last fails the step, not retryably. The request names the
schema (`schema`) so the agent can keep to it in the first place. A host that fails, times out or goes silent
raises `AgentRunFailed`, which the engine retries like any other transient failure. Not
configured is an `AuthorError`.
"""

import json
import os

from wgflib import agentenv, paths, procs

from .authors import ArchetypeAuthor, AuthorError, DesignAuthor, register_author
from .depth import load_rules as load_depth_rules
from .experience import load_rules

__all__ = ["AgentAuthor", "AgentRunFailed", "REQUIRED_KEYS", "BUILD_SPEC_KEYS"]

# Exactly what the built-in author returns, so `finalize` and `buildability` never meet a
# shape they index into blindly.
REQUIRED_KEYS = ("fantasy", "core_loop", "pillars", "engine", "features", "scope", "session",
                 "retention", "monetization", "progression", "difficulty", "controls", "ux",
                 "art_direction", "audio_direction", "build_spec", "open_questions")
BUILD_SPEC_KEYS = ("mechanics", "controls", "player_goals", "progression", "difficulty",
                   "game_states", "screens", "hud", "menus", "tutorial", "rewards", "failure",
                   "session_flow", "monetization_touchpoints", "assets", "audio", "responsive",
                   "visual_identity", "experience")

PROMPT = (
    "You are the game designer for this title. Read the request at {request}: the approved "
    "strategy, the platform profiles, and a starting draft in exactly the shape required. "
    "Improve the design - the core loop, feel, onboarding, difficulty, rewards and failure "
    "feedback, audio and visual identity - within the strategy's scope: never add a feature, "
    "a monetization placement or a platform the strategy did not approve, and keep every key "
    "and id reference valid. {draft} already holds the starting draft (when you are asked "
    "again, your previous draft): edit that file in place, a section at a time, so it stays "
    "one valid JSON object of the required shape. Do not print the draft."
)
PROMPT_STDOUT = (
    "You are the game designer for this title. Read the request at {request}: the approved "
    "strategy, the platform profiles, and a starting draft in exactly the shape required. "
    "Improve the design - the core loop, feel, onboarding, difficulty, rewards and failure "
    "feedback, audio and visual identity - within the strategy's scope: never add a feature, "
    "a monetization placement or a platform the strategy did not approve, and keep every key "
    "and id reference valid. End your answer with the complete draft as one JSON object."
)

# Appended when the strategy carries a brief - the person's own game idea. The brief is
# read from the request, never formatted into the prompt: it is the person's text.
PROMPT_BRIEF = (
    " The strategy carries the person's game idea as `brief` (also the request's `brief`): "
    "design the game it describes - its mechanic, fantasy, controls and dimension - and "
    "treat the starting draft as a schema-shaped starting point, not as the game."
)
# Appended always: what the module checks the draft against, so the agent is not left to
# discover the consistency rules by failing them. It changes no rule.
PROMPT_CONCEPT = (
    " The module then holds the draft to the strategy's `concept`: every mechanic its "
    "core_mechanic and core_loop state must appear in your core_loop, MVP features or MVP "
    "controls, and you may add no mechanic the strategy does not state."
)

# Appended always: the finished design is a game-design artifact, validated against its schema.
PROMPT_SCHEMA = (
    " The finished design is validated against the JSON Schema the request names as `schema`:"
    " use only the enum values it allows, and keep every key it requires."
)
# Appended always: the production art and UI the module requires (presentation.py), so a draft
# states how the finished game looks instead of leaving the developer to draw cubes. The bars
# are in the request's `production_art`, read from core/reference/experience-rules.yaml.
PROMPT_ART = (
    " State the finished game's look, not just its rules: every MVP asset in"
    " build_spec.assets has a `role` (what it is to the player: player, threat, goal, target,"
    " projectile, collectible, hazard, environment, background, prop, ui, vfx, icon, font) and"
    " a `dimension` (2d or 3d), and every entity-role asset a `readability` line - what a"
    " first-time player must recognise in it, and at what size or distance. Every thing your"
    " mechanics name that the player must see (the character they control, what threatens it,"
    " what it aims at, what flies) has an MVP asset of that role; in a 3D game the characters"
    " are 3D models. visual_identity.ui gives font_px (body, hud, heading), min_target_px, the"
    " button's fill and text as palette tokens that contrast, its radius, and the surface"
    " token, within the request's `production_art` bars. Set visual_identity.primitive_style"
    " (with a reason) only when the art direction itself is geometric - a character is never"
    " a cube for convenience. The craft guide is the request's `craft`."
)
# Appended always: why a player comes back (depth.py), so a draft states more than one loop.
# The bars are the request's `depth`, read from core/reference/design-depth.yaml.
PROMPT_DEPTH = (
    " State why a player plays longer and returns, in build_spec.depth: the meta_loop above"
    " the run and what it persists (more than a score), a goal_ladder with short, mid and long"
    " goals, a content_schedule of piece, obstacle, power-up, zone or event types introduced"
    " over play (at_s, after_runs), the first_session (target_s equal to"
    " session.first_session_seconds, and the beat it ends on) and the return_hooks. Tier every"
    " entry honestly: an mvp or post-mvp entry names in delivered_by the feature, mechanic,"
    " progression step, reward or hud id that builds it, an mvp entry only an mvp one, and"
    " depth the strategy excludes is optional. The bars are the request's `depth`; the craft"
    " guide is the request's `depth_craft`."
)
# Appended when the step asks again: the previous draft and exactly what made it invalid.
PROMPT_REPAIR = (
    " Your previous draft (the request's `repair.previous_draft`) was invalid for the reasons"
    " in `repair.problems`. Return the complete draft again with exactly those fixed and"
    " nothing else changed."
)

DEFAULTS = {"argv": [], "timeout_seconds": 1800, "idle_timeout_seconds": 600,
            "draft_from": "file"}
_MAX_BYTES = 4 * 1024 * 1024


class AgentRunFailed(RuntimeError):
    """The agent host failed, timed out or went silent. Retryable."""


def _last_json_object(text):
    """The last top-level JSON object in `text` (bare or in a ```json fence), or None."""
    decoder = json.JSONDecoder()
    found = None
    index = 0
    while True:
        start = text.find("{", index)
        if start < 0:
            return found
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            index = start + 1
            continue
        if isinstance(value, dict):
            found = value
        index = end


def check_shape(draft):
    """Problems with the draft's shape - before `finalize` indexes into it."""
    if not isinstance(draft, dict):
        return ["the draft is not a JSON object"]
    problems = [f"missing {key!r}" for key in REQUIRED_KEYS if key not in draft]
    spec = draft.get("build_spec")
    if "build_spec" in draft and not isinstance(spec, dict):
        problems.append("build_spec is not an object")
    elif isinstance(spec, dict):
        problems += [f"build_spec is missing {key!r}" for key in BUILD_SPEC_KEYS
                     if key not in spec]
    if "scope" in draft and not isinstance(draft["scope"], dict):
        problems.append("scope is not an object")
    if "engine" in draft and not isinstance(draft["engine"], dict):
        problems.append("engine is not an object")
    if "features" in draft and not isinstance(draft["features"], list):
        problems.append("features is not a list")
    return problems


class AgentAuthor(DesignAuthor):
    name = "agent"
    actor = "ai"
    # The design step shows it what made its draft invalid and asks again (step.py).
    repairs = True

    def draft(self, brief):
        settings = dict(DEFAULTS)
        settings.update(((brief.get("config") or {}).get("design") or {}).get("agent") or {})
        argv = settings.get("argv") or []
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise AuthorError("factory.design.agent.argv is not configured (a non-empty list "
                              "of strings); the agent author has nothing to run")
        if settings.get("draft_from") not in ("file", "stdout"):
            raise AuthorError("factory.design.agent.draft_from must be file or stdout")
        run_dir = brief.get("run_dir")
        if not run_dir:
            raise AuthorError("the design step gave the agent author no run directory")

        directory = os.path.join(run_dir, "design")
        repair = brief.get("repair") or {}
        stem = f"{brief.get('visit', 1)}-{brief.get('attempt', 1)}" + (
            f"-repair{repair['round']}" if repair else "")
        request_path = os.path.join(directory, f"{stem}.request.json")
        draft_path = os.path.join(directory, f"{stem}.draft.json")
        log_path = os.path.join(directory, f"{stem}.log")
        os.makedirs(directory, exist_ok=True)
        for stale in (draft_path, log_path):
            if os.path.exists(stale):
                os.remove(stale)

        # The built-in author's draft is the starting point: the exact shape the module
        # requires, already inside the strategy's scope. The agent improves it.
        starting = ArchetypeAuthor().draft(brief)
        idea = (brief.get("strategy") or {}).get("brief")
        rules = load_rules()
        request = {"title_id": brief.get("title_id"), "strategy": brief.get("strategy"),
                   "platforms": [{"id": p.id, "role": p.role, "version": p.version,
                                  "profile": p.profile} for p in brief.get("platforms") or []],
                   "starting_draft": starting,
                   "required_keys": list(REQUIRED_KEYS),
                   "required_build_spec_keys": list(BUILD_SPEC_KEYS),
                   # What the finished design is validated against: every enum value and
                   # required key. Shared definitions are beside it, under shared/.
                   "schema": os.path.join(paths.ARTIFACTS, "game-design.schema.json"),
                   # The bars the production art and UI are held to (presentation.py), and
                   # the craft guide they come from.
                   "production_art": {key: rules.get(key) for key in ("production_art", "ui")},
                   "craft": os.path.join(paths.CORE, "craft", "production-art-and-ui.md"),
                   # The bars depth is held to (depth.py), and the craft guide behind them.
                   "depth": load_depth_rules(),
                   "depth_craft": os.path.join(paths.CORE, "craft",
                                               "retention-and-progression.md")}
        if idea:
            request["brief"] = idea
        if repair:
            request["repair"] = {"problems": repair.get("problems") or [],
                                 "previous_draft": repair.get("previous_draft")}
        with open(request_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(request, handle, indent=2, ensure_ascii=False, default=str)

        try:
            env = agentenv.scrubbed(agentenv.passthrough(brief.get("config")))
        except ValueError as exc:
            raise AuthorError(str(exc)) from exc
        values = {"request": request_path, "draft": draft_path}
        stdout_mode = settings["draft_from"] == "stdout"
        seed = None
        if not stdout_mode:
            # The agent edits the draft in place rather than reproducing all of it: a full
            # design is tens of kilobytes, more than a host reliably emits in one reply.
            seed = json.dumps((repair.get("previous_draft") if repair else None) or starting,
                              indent=2, ensure_ascii=False, default=str) + "\n"
            with open(draft_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(seed)
        values["prompt"] = (PROMPT_STDOUT if stdout_mode else PROMPT).format(**values)
        if idea:
            values["prompt"] += PROMPT_BRIEF
        values["prompt"] += PROMPT_CONCEPT + PROMPT_SCHEMA + PROMPT_ART + PROMPT_DEPTH
        if repair:
            values["prompt"] += PROMPT_REPAIR
        try:
            command = [part.format(**values) for part in argv]
        except (KeyError, IndexError, ValueError) as exc:
            raise AuthorError(f"factory.design.agent.argv has a placeholder this author does "
                              f"not provide ({exc}); use {{request}}, {{draft}}, {{prompt}}, "
                              f"and double any literal brace") from exc
        result = procs.run(command, cwd=directory, env=env,
                           timeout=settings.get("timeout_seconds"),
                           idle_timeout=settings.get("idle_timeout_seconds"),
                           log_path=log_path, heartbeat_seconds=15.0)
        if not result.ok:
            raise AgentRunFailed(
                f"the design agent {os.path.basename(command[0])} ended {result.status} "
                f"(exit {result.returncode}); log: {log_path}")

        if stdout_mode:
            draft = _last_json_object(result.stdout or "")
            if draft is None:
                raise AuthorError("the design agent printed no JSON object")
        else:
            if not os.path.isfile(draft_path):
                raise AuthorError(f"the design agent wrote no draft at {draft_path}")
            if os.path.getsize(draft_path) > _MAX_BYTES:
                raise AuthorError("the design draft is larger than 4 MiB")
            try:
                with open(draft_path, encoding="utf-8") as handle:
                    text = handle.read()
                draft = json.loads(text)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                raise AuthorError(f"the design draft is not readable JSON: {exc}") from exc
            if text == seed:
                raise AuthorError(f"the design agent left the draft at {draft_path} "
                                  f"unchanged")
        problems = check_shape(draft)
        if problems:
            hint = (" - in stdout mode this is usually a reply cut by the host's output limit; "
                    "use draft_from: file" if stdout_mode else "")
            raise AuthorError("the design draft does not have the required shape: "
                              + "; ".join(problems[:8]) + hint)
        return draft


register_author(AgentAuthor.name, AgentAuthor)
