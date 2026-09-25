"""The `agent` design author: an agent host writes the design draft; the module judges it.

Opt-in. An installation selects it in workspace/config/factory.yaml:

    factory:
      design:
        author: agent
        agent:
          argv: [...]                # the host's non-interactive command; placeholders below
          timeout_seconds: 1800      # wall clock
          idle_timeout_seconds: 600  # no output for this long ends the attempt
          draft_from: file           # file: the agent writes {draft}
                                     # stdout: it prints the draft JSON last

`argv` placeholders, substituted per element and never re-formatted: {request} (the request
JSON: strategy, resolved platforms, title id, and the built-in archetype's draft as a
schema-shaped starting point), {draft} (where to write the draft JSON), {prompt} (a
one-paragraph instruction).

The agent only writes a DRAFT. Everything after it is the design module's, unchanged: platform
absorption and tier derivation (`finalize`), the buildability check and the consistency rules,
including the `descope` route. An agent cannot mark its own homework, and nothing here
relaxes a check to let its draft through.

Outcomes: a draft whose shape is wrong (not JSON, a missing section) is an `AuthorError` -
not retryable, the same draft would come back. A host that fails, times out or goes silent
raises `AgentRunFailed`, which the engine retries like any other transient failure. Not
configured is an `AuthorError`.
"""

import json
import os

from wgflib import procs

from .authors import ArchetypeAuthor, AuthorError, DesignAuthor, register_author

__all__ = ["AgentAuthor", "AgentRunFailed", "REQUIRED_KEYS", "BUILD_SPEC_KEYS"]

# Exactly what the built-in author returns, so `finalize` and `buildability` never meet a
# shape they index into blindly.
REQUIRED_KEYS = ("fantasy", "core_loop", "pillars", "engine", "features", "scope", "session",
                 "retention", "monetization", "progression", "difficulty", "controls", "ux",
                 "art_direction", "audio_direction", "build_spec", "open_questions")
BUILD_SPEC_KEYS = ("mechanics", "controls", "player_goals", "progression", "difficulty",
                   "game_states", "screens", "hud", "menus", "tutorial", "rewards", "failure",
                   "session_flow", "monetization_touchpoints", "assets", "audio", "responsive",
                   "visual_identity")

PROMPT = (
    "You are the game designer for this title. Read the request at {request}: the approved "
    "strategy, the platform profiles, and a starting draft in exactly the shape required. "
    "Improve the design - the core loop, feel, onboarding, difficulty, rewards and failure "
    "feedback, audio and visual identity - within the strategy's scope: never add a feature, "
    "a monetization placement or a platform the strategy did not approve, and keep every key "
    "and id reference valid. Write the complete draft, and nothing else, as JSON to {draft}."
)
PROMPT_STDOUT = (
    "You are the game designer for this title. Read the request at {request}: the approved "
    "strategy, the platform profiles, and a starting draft in exactly the shape required. "
    "Improve the design - the core loop, feel, onboarding, difficulty, rewards and failure "
    "feedback, audio and visual identity - within the strategy's scope: never add a feature, "
    "a monetization placement or a platform the strategy did not approve, and keep every key "
    "and id reference valid. End your answer with the complete draft as one JSON object."
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
        stem = f"{brief.get('visit', 1)}-{brief.get('attempt', 1)}"
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
        request = {"title_id": brief.get("title_id"), "strategy": brief.get("strategy"),
                   "platforms": [{"id": p.id, "role": p.role, "version": p.version,
                                  "profile": p.profile} for p in brief.get("platforms") or []],
                   "starting_draft": starting,
                   "required_keys": list(REQUIRED_KEYS),
                   "required_build_spec_keys": list(BUILD_SPEC_KEYS)}
        with open(request_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(request, handle, indent=2, ensure_ascii=False, default=str)

        values = {"request": request_path, "draft": draft_path}
        stdout_mode = settings["draft_from"] == "stdout"
        values["prompt"] = (PROMPT_STDOUT if stdout_mode else PROMPT).format(**values)
        try:
            command = [part.format(**values) for part in argv]
        except (KeyError, IndexError, ValueError) as exc:
            raise AuthorError(f"factory.design.agent.argv has a placeholder this author does "
                              f"not provide ({exc}); use {{request}}, {{draft}}, {{prompt}}, "
                              f"and double any literal brace") from exc
        result = procs.run(command, cwd=directory, timeout=settings.get("timeout_seconds"),
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
                    draft = json.load(handle)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                raise AuthorError(f"the design draft is not readable JSON: {exc}") from exc
        problems = check_shape(draft)
        if problems:
            raise AuthorError("the design draft does not have the required shape: "
                              + "; ".join(problems[:8]))
        return draft


register_author(AgentAuthor.name, AgentAuthor)
