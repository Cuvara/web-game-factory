"""The judge brief: every frame with its state and viewport, the rubric, the design's visual
identity and the asset roles. Self-contained - the judge reads it and the frames, nothing
else - because the judge runs outside both the Factory and the game checkout."""

import json

from wgflib import quality_bar

from .rubric import CATEGORIES, ROUTES, SEVERITIES, contract, judged_pairs, state_ids

__all__ = ["render_brief", "frame_state", "PROMPT", "PROMPT_STDOUT"]

PROMPT = (
    "You are the visual QA judge for a web game, not its developer or artist. Read {brief} in "
    "full, then look at every PNG frame under {frames_dir} it lists. You are READ-ONLY: do "
    "not create, edit or delete anything except your verdict. Write your verdict, and "
    "nothing else, as one JSON object to {verdict}, exactly in the shape the brief gives."
)

PROMPT_STDOUT = (
    "You are the visual QA judge for a web game, not its developer or artist. Read {brief} in "
    "full, then look at every PNG frame under {frames_dir} it lists. You are READ-ONLY: do "
    "not create, edit or delete any file. End your answer with your verdict as one JSON "
    "object, exactly in the shape the brief gives."
)

# What each frame the playability bot captures shows (scripts/wgf_playability/bot.spec.ts),
# and the rubric state (core/reference/visual-qa-rubric.yaml `states`) it belongs to.
_STATES = (
    ("first-session-1s", "initial", "one second after the page loaded: the first thing a player sees"),
    ("first-session-idle-end", "initial", "after the onboarding grace with no input: the game waiting for the player"),
    ("play-2s", "gameplay", "two seconds into play"),
    ("end-won", "win", "the win screen"),
    ("end-lost", "loss", "the loss screen"),
    # The bot's per-screen frames (Watch.screen: state-<probe state>), each taken when the
    # probe first reported that screen, after its entrance animation settled.
    ("state-title", "initial", "the title screen, before play"),
    ("state-playing", "gameplay", "the first frame of play"),
    ("state-paused", "interaction", "the pause screen, just after the player paused"),
    ("state-won", "win", "the win screen"),
    ("state-lost", "loss", "the loss screen"),
    ("state-retry", "retry", "the first frame after the player chose to retry"),
)


def frame_state(frame_id):
    """(state, description) of a frame captured by the playability bot, from its id."""
    for prefix, state, description in _STATES:
        if frame_id == prefix:
            return state, description
    if frame_id.startswith("act-"):
        rest = frame_id[4:]
        for side in ("before", "after"):
            if rest.endswith("-" + side):
                action = rest[:-len(side) - 1]
                return "interaction", f"just {side} the player's `{action}` action"
    if frame_id.startswith("retry"):
        return "retry", "after the player chose to retry"
    return "unknown", "a frame the bot captured"


def _identity_lines(identity):
    out = []
    if not identity:
        return ["The design gives no visual identity. Judge against the rubric alone; a game "
                "with no deliberate look is not exempt from it."]
    for key in ("concept", "shape_language", "motion", "texture"):
        if identity.get(key):
            out.append(f"- {key.replace('_', ' ')}: {identity[key]}")
    palette = identity.get("palette") or []
    if palette:
        out.append("- palette: " + ", ".join(
            f"`{p.get('token')}` {p.get('hex')} ({p.get('role')})" for p in palette
            if isinstance(p, dict)))
    typography = identity.get("typography") or {}
    if typography:
        out.append("- typography: " + "; ".join(f"{k} {v}" for k, v in typography.items()))
    if identity.get("ui"):
        out.append("- UI rules: " + json.dumps(identity["ui"], sort_keys=True))
    if identity.get("avoid"):
        out.append("- avoid: " + "; ".join(identity["avoid"]))
    primitive = identity.get("primitive_style")
    if isinstance(primitive, dict):
        out.append(f"- primitive_style: YES - the art direction is itself geometric "
                   f"({primitive.get('reason')}). Primitives standing for entities are the "
                   f"style here, not placeholders; judge whether they are finished and "
                   f"readable.")
    else:
        out.append("- primitive_style: NO - a readable entity drawn as a plain cube, sphere, "
                   "capsule, cylinder or rectangle is a placeholder: a blocker.")
    return out


def _asset_lines(design, manifest):
    required = [a for a in (((design or {}).get("build_spec") or {}).get("assets") or [])
                if isinstance(a, dict)]
    items = {i.get("id"): i for i in ((manifest or {}).get("items") or [])
             if isinstance(i, dict) and i.get("id")}
    out = []
    for asset in required:
        line = (f"- `{asset.get('id')}` role {asset.get('role') or 'unspecified'}"
                f" ({asset.get('tier')}): {asset.get('description')}")
        if asset.get("readability"):
            line += f" - must read as: {asset['readability']}"
        item = items.pop(asset.get("id"), None)
        if item is not None:
            line += _item_note(item)
        out.append(line)
    for item_id, item in sorted(items.items()):
        out.append(f"- `{item_id}` role {item.get('role') or 'unspecified'}: "
                   f"{item.get('label') or item.get('type')}{_item_note(item)}")
    return out


def _item_note(item):
    notes = [f"source {item.get('source')}"] if item.get("source") else []
    if item.get("placeholder"):
        notes.append("PLACEHOLDER")
    quality = item.get("quality") or {}
    if quality.get("verdict"):
        notes.append(f"quality check {quality['verdict']}")
    if quality.get("primitive_only"):
        notes.append("built from primitives only")
    return f" [{', '.join(notes)}]" if notes else ""


def _quality_bar(design):
    """The installation's quality-bar frames for the design's dimension (all when unknown)."""
    engine = ((design or {}).get("engine") or {})
    engine = engine.get("type") if isinstance(engine, dict) else engine
    dimension = {"threejs": "3d", "pixijs": "2d", "phaserjs": "2d"}.get(engine)
    return quality_bar.frames(dimension) or quality_bar.frames()


def render_brief(*, title_id, commit, frames, rubric, design=None, manifest=None,
                 quality=None, verdict_path=None, to_stdout=False, previous_problem=None,
                 repair=None):
    """`frames`: [{key, project, id, state, description, viewport, file}] - `key` is the
    frame's id in the verdict (<viewport>/<frame-id>), `file` its path for the judge.
    `repair` ({reply, problems}) makes it a repair round: the judge's own previous reply and
    every validation error come first, then the whole brief again."""
    out = []
    add = out.append
    add(f"# Visual QA brief: {title_id or 'a game'}"
        + (f" at {commit[:12]}" if commit else "") + "\n")
    add("Written by the Factory's visual-qa step. You judge what the frames show; you do not "
        "fix anything, and you judge only what is visible - not what the code may intend.\n")
    if repair:
        add("## Repair your previous verdict\n")
        add("Your previous verdict could not be used. It is below, with every error the "
            "Factory found in it. Return the corrected verdict in full - every key, every "
            "score, every (state, viewport) entry and every answer - exactly in the shape "
            "given at the end of this brief, not only the parts that changed. Fix what the "
            "errors name; keep every judgement the errors do not touch. Where an answer is "
            "missing, look at that state's frames and answer it: `true`, `false`, or `null` "
            "when the frames cannot tell. Never drop a question or a state to make the "
            "verdict pass the check.\n")
        add("Errors:\n")
        for problem in repair["problems"]:
            add(f"- {problem}")
        add("")
        add("Your previous reply, verbatim:\n")
        add("```\n" + repair["reply"] + "\n```\n")
    elif previous_problem:
        add("## Your previous verdict was rejected\n")
        add(f"It could not be used: {previous_problem}. Write it again, exactly in the shape "
            "below.\n")
    add("## The frames\n")
    add("Captured by a bot playing the production build. Each frame's id in your verdict is "
        "the first column, verbatim.\n")
    add("| frame | viewport | state | what it shows | file |")
    add("|---|---|---|---|---|")
    for frame in frames:
        viewport = frame.get("viewport") or {}
        size = frame["project"]
        if viewport:
            size += f" {viewport.get('width')}x{viewport.get('height')} CSS px"
        if frame.get("size"):
            size += f", image {frame['size'][0]}x{frame['size'][1]}"
        add(f"| `{frame['key']}` | {size} | {frame['state']} | {frame['description']} | "
            f"`{frame['file']}` |")
    add("")
    add("Look at every one. A finding about one frame names it; one true of every frame "
        "names none (`frame: null`).\n")
    add("## The game's visual identity\n")
    identity = ((design or {}).get("build_spec") or {}).get("visual_identity")
    add("\n".join(_identity_lines(identity)) + "\n")
    assets = _asset_lines(design, manifest)
    if assets:
        add("## The assets and what they are to the player\n")
        add("Roles player, threat, goal, target and projectile are the readable entities: a "
            "first-time player must recognise each at a glance.\n")
        add("\n".join(assets) + "\n")
    failed = [c for c in ((quality or {}).get("checks") or [])
              if isinstance(c, dict) and c.get("status") == "FAIL"]
    if failed:
        add("## What the production-quality measurements found\n")
        add("Measured from outside; confirm or dismiss each by what the frames show.\n")
        add("\n".join(f"- `{c.get('id')}`: {c.get('summary')}" for c in failed) + "\n")
    bar = _quality_bar(design)
    if bar:
        add("## The quality bar\n")
        add("Frames of finished games this installation holds every game to. Open them first. "
            "Their level of finish - a composed frame with no empty void, one visual language "
            "across art and UI, designed typography, a modelled or drawn cast rather than "
            "shapes - is what a 4 looks like on art_completeness, environment, ui_polish, "
            "typography and consistency, and what `finished-game` means. Their style is not "
            "the bar: judge this game against its own identity, at their level of finish.\n")
        for frame in bar:
            add(f"- `{frame['path']}` ({frame.get('state')}): {frame.get('shows')}")
        add("")
    add("## The rubric\n")
    mean_bar = rubric.get("mean_pass_bar")
    add(f"Score every dimension 0-5. The anchors describe 0, 3 and 5; 1, 2 and 4 lie "
        f"between. Below {rubric['pass_bar']} fails the build"
        + (f", and so does a mean below {mean_bar}" if mean_bar is not None else "")
        + ". Score what you see, not what would pass.\n")
    for name, dimension in rubric["dimensions"].items():
        anchors = dimension.get("anchors") or {}
        add(f"### `{name}`\n")
        add(f"{dimension.get('question')}\n")
        for level in ("0", "3", "5"):
            add(f"- {level}: {anchors.get(level)}")
        add("")
    add("## Per state\n")
    add("Answer every question below for each of these (state, viewport) pairs, from its "
        "frames. `true`/`false`; `null` only when the frames of that state show nothing the "
        "question is about (no text, no button, a 2D game's lighting) - never for \"not "
        "sure\".\n")
    pairs = judged_pairs(rubric, frames)
    add("| state | viewport | frames |")
    add("|---|---|---|")
    for state, viewport in pairs:
        keys = [f"`{f['key']}`" for f in frames if f["state"] == state
                and f["project"] == viewport]
        add(f"| {state} | {viewport} | {', '.join(keys)} |")
    add("")
    missing = [s for s in state_ids(rubric) if s not in {p[0] for p in pairs}]
    if missing:
        add(f"No frame shows: {', '.join(missing)}. Do not answer for "
            f"{'it' if len(missing) == 1 else 'them'}; the report records "
            f"{'it' if len(missing) == 1 else 'them'} as not captured.\n")
    add("Questions (asked of every state unless listed):\n")
    for question in rubric.get("state_questions") or []:
        only = question.get("states")
        fails = "yes" if question["fail_when"] else "no"
        add(f"- `{question['id']}`{' (' + ', '.join(only) + ' only)' if only else ''}: "
            f"{question['ask']} An answer of {fails!r} fails the build.")
    add("")
    look = rubric.get("look") or {}
    add("## The look\n")
    add(f"{look.get('ask')} Answer one of {', '.join(f'`{v}`' for v in look.get('values') or [])}"
        f", with the reason. "
        + " or ".join(f"`{v}`" for v in (look.get("fail_on") if isinstance(
            look.get("fail_on"), list) else [look.get("fail_on")]))
        + " fails the build.\n")
    add("## Blockers\n")
    add("Raise each of these as a finding with `severity: blocker`, whatever your scores. "
        "Use the category and route given.\n")
    for rule in rubric.get("blockers") or []:
        add(f"- `{rule.get('id')}` (category {rule.get('category')}, route "
            f"{rule.get('route')}): {rule.get('rule')}")
    add("")
    add("`major` is a real defect that does not on its own stop the build; `minor` is "
        "polish. Style preferences that the identity does not ask for are not findings.\n")
    add("## Your verdict\n")
    if to_stdout:
        add("End your output with exactly one JSON object - your verdict. Write no file:\n")
    else:
        add(f"Write exactly one JSON object to `{verdict_path}`:\n")
    # Scores are shown as <number 0-5>, not as a quoted example: the calibration run's judge
    # copied a quoted "0..5" placeholder's type and wrote every score as a string.
    shape = (json.dumps(contract(rubric, frames), indent=2)
             .replace('"0..5"', "<number 0-5>")
             .replace('"true | false | null"', "<true | false | null>"))
    add("```json\n" + shape + "\n```\n")
    add("- `scores` has every dimension above and no other, each a JSON number 0-5 (`3`, not "
        "`\"3\"`).")
    add("- `score_reasons` gives, for every dimension, one or two sentences on why it scored "
        "what it did: what you saw, on which entity or element, in which frames. A score "
        "below the bar without a reason cannot be acted on: the artist and the developer "
        "who fix the build read exactly these sentences, beside the frames.")
    add(f"- `severity` is one of {', '.join(SEVERITIES)}; `category` one of "
        f"{', '.join(CATEGORIES)}; `route` one of {', '.join(ROUTES)}: `assets` when an "
        f"asset itself must change, `develop` when the game's use of it (layout, lighting, "
        f"camera, UI code, leftover debug) must.")
    add("- `states` has exactly one entry per (state, viewport) in the per-state table, each "
        "answering exactly the questions asked of that state with JSON `true`, `false` or "
        "`null`.")
    add("- `look` is one of the values above, verbatim.")
    add("- `frame` is a frame id from the table, verbatim, or null. `id` is short "
        "kebab-case and unique.")
    add("- You do not write a pass or fail: the Factory decides it from your scores and "
        "blockers. No other keys. A malformed verdict is discarded, never read as a pass.")
    return "\n".join(out) + "\n"
