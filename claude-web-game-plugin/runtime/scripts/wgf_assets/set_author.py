"""The 2D author's `set` mode: one session authors every 2D drawing of the design, together.

The per-asset author (author.py, `mode: asset`) asks the host once per drawing: it never sees
the other drawings, nor a render of its own. A coherent set is made the way the reference
game's lead made it - one hand, one style sheet applied to every drawing, iterated while
looking at renders. Configured under `factory.assets.author` like the per-asset author:

    author:
      kind: command
      mode: set                    # asset (default) | set
      argv: [...]                  # placeholders below
      timeout_seconds: 2400        # wall clock, per session
      idle_timeout_seconds: null
      repair_rounds: 1             # further sessions, each shown what still fails

`argv` placeholders: {request} (the set brief, JSON), {out} (the one directory the author
writes: <out>/<variant id>.svg per drawing, plus its style sheet <out>/STYLE.md), {preview}
(the one command it may run: `<python> <wgf_assets/preview.py> <job.json>`), {sheet} (where
that command writes the contact sheet) and {prompt}. A host restricts its writes to {out}
and its shell to exactly {preview} - in Claude Code: `--allowedTools "Edit(/{out}/**)"
"Bash({preview})"` (`//` is an absolute path; an Edit rule covers every file-writing tool).

The brief carries every 2D requirement the author is asked for (role, description,
readability, spec, size, count, the file of each variant, and which are already accepted),
the FULL visual identity (palette, typography, shape language, motion, texture, avoid, ui),
the design's art direction and resolution, the quality bars (per file, and the set's shared
treatment), and the craft guides by absolute path. Drawings accepted on an earlier run are
copied into {out} first, so the author sees them and keeps them unless asked to redo one.

The Factory then judges what is in {out} exactly as the author's preview did
(wgf_assets.preview.review: the per-file quality, variants.distinct, set.consistent, plus the
step's own format validation) and renders the contact sheet. Every drawing that passes is
delivered; while one fails and repair rounds remain, a new session is shown the problems and
the contact sheet. The author never runs anything else: the drawings are data, judged and
rendered by the Factory.
"""

import json
import os
import shlex
import shutil
import sys

from wgflib import agentenv, paths, procs

from . import preview as preview_mod
from .author import AuthorError, AuthorRunFailed

__all__ = ["SetAuthor", "SET_CRAFT", "PLACEHOLDERS"]

PLACEHOLDERS = ("request", "out", "preview", "sheet", "prompt")
DEFAULTS = {"timeout_seconds": 2400, "idle_timeout_seconds": None, "repair_rounds": 1}
# The craft playbooks the brief names, in reading order.
SET_CRAFT = ("production-art-2d.md", "art-direction.md", "game-ui-kit.md",
             "production-art-and-ui.md")
PREVIEW_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preview.py")

PROMPT = (
    "You are the lead 2D artist for this game. Read the brief at {request}: every 2D drawing "
    "the design needs - role, description, readability line, size, variants - with the full "
    "visual identity, the art direction and the quality bars. Read the craft guides it names "
    "(`craft`) first. Author the drawings as ONE coherent set, the way a lead works from one "
    "style sheet: first write {out}/STYLE.md - your style kit as a table (outline width in "
    "displayed px and its colour, shadow treatment, highlight, texture, edges and corners, "
    "the role of each palette colour) - then draw every file the brief lists, each a "
    "self-contained SVG at exactly its path, applying the same kit to every drawing so they "
    "read as one game. Draw every listed file before polishing any one: a file not written "
    "is a failed one, and your turns and budget are bounded. Write only inside {out}. No scripts, no embedded images, no references "
    "to other files; draw lettering as outlined paths (an SVG drawn as an image cannot load "
    "the game's fonts). Then run `{preview}`: it judges every file against the bars and "
    "renders the contact sheet {sheet} - every drawing at its in-game size on the game's "
    "background, small, and the silhouettes of each counted family. Open the sheet with your "
    "file-reading tool and look at it as a first-time player and as an art lead: does each "
    "drawing read at its size, do the variants differ by silhouette, is anything off-style, "
    "muddy or generic, does it match the identity and avoid its avoid list? Fix what you see "
    "and what the preview reports, and run it again, until it reports no problems and you "
    "would ship the sheet. Finish with a short note: what you changed after looking."
)
PROMPT_REPAIR = (
    " This is a further round: your drawings are in {out} as you left them; the brief's "
    "`repair` lists what still fails and the last contact sheet. Fix those first, keep "
    "what passes, and look at the sheet again before you finish."
)
PROMPT_NOTES = (
    " The running game was judged and the requirements with `notes` in the brief were named "
    "in the findings: redraw those, and keep the set consistent."
)


def _python():
    exe = sys.executable or "python3"
    return exe if " " not in exe else "python3"


class SetAuthor:
    """The configured set-mode host. `author(brief, job, work_dir, judge)` runs the rounds."""

    kind = "command"
    mode = "set"

    def __init__(self, settings, config=None):
        self.settings = dict(DEFAULTS)
        self.settings.update(settings or {})
        argv = self.settings.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise AuthorError("factory.assets.author.argv is not configured (a non-empty list "
                              "of strings); the set author has nothing to run")
        rounds = self.settings.get("repair_rounds")
        if not isinstance(rounds, int) or isinstance(rounds, bool) or not 0 <= rounds <= 5:
            raise AuthorError("factory.assets.author.repair_rounds must be an integer 0..5")
        if (settings or {}).get("svg_from") == "stdout":
            raise AuthorError("factory.assets.author: mode set writes files (one per drawing); "
                              "svg_from: stdout is the per-asset mode's")
        self._format(argv, {k: "" for k in PLACEHOLDERS})
        self.argv = argv
        self.repair_rounds = rounds
        try:
            self.env = agentenv.scrubbed(agentenv.passthrough(config or {}))
        except ValueError as exc:
            raise AuthorError(str(exc)) from exc

    @staticmethod
    def _format(argv, values):
        try:
            return [part.format(**values) for part in argv]
        except (KeyError, IndexError, ValueError) as exc:
            raise AuthorError(
                f"factory.assets.author.argv has a placeholder the set author does not "
                f"provide ({exc}); use " + ", ".join("{%s}" % p for p in PLACEHOLDERS)
                + ", and double any literal brace") from exc

    @property
    def label(self):
        return "author:set"

    # -- one session -------------------------------------------------------------------------

    def _session(self, brief, job_path, layout, round_, notes):
        request_path = os.path.join(layout["root"], f"request-{round_}.json")
        with open(request_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(brief, handle, indent=2, ensure_ascii=False, sort_keys=True)
        preview = " ".join(shlex.quote(p) for p in (_python(), PREVIEW_SCRIPT, job_path))
        values = {"request": request_path, "out": layout["out"], "preview": preview,
                  "sheet": layout["sheet"]}
        prompt = PROMPT.format(**values)
        if brief.get("repair"):
            prompt += PROMPT_REPAIR.format(**values)
        if notes:
            prompt += PROMPT_NOTES
        values["prompt"] = prompt
        command = self._format(self.argv, values)
        log_path = os.path.join(layout["root"], f"session-{round_}.log")
        result = procs.run(command, cwd=layout["root"], env=self.env,
                           timeout=self.settings.get("timeout_seconds"),
                           idle_timeout=self.settings.get("idle_timeout_seconds"),
                           log_path=log_path, heartbeat_seconds=15.0)
        if not result.ok:
            raise AuthorRunFailed(
                f"the set author {os.path.basename(command[0])} ended "
                f"{'timed out' if result.timed_out or result.idle_timed_out else 'with exit ' + str(result.returncode)}"
                f"{'; ' + result.error if result.error else ''}; log: {log_path}")
        return log_path

    def author(self, brief, job, layout, judge, *, notes=False, logger=None):
        """Run sessions until every drawing passes `judge()` or the rounds are spent.
        Returns (review, [round record]). `judge()` -> preview.review()'s result; it renders
        the contact sheet. A failed host ends the rounds with what is in `out` judged."""
        job_path = layout["job"]
        preview_mod.write_job(job_path, job)
        rounds, review = [], None
        for round_ in range(self.repair_rounds + 1):
            try:
                log = self._session(brief, job_path, layout, round_, notes)
                error = None
            except AuthorRunFailed as exc:
                log, error = None, str(exc)
            review = judge()
            failing = {vid: r["problems"] for vid, r in review["files"].items() if r["problems"]}
            sheet = review.get("sheet")
            if sheet and os.path.isfile(sheet):
                kept = os.path.join(layout["root"], f"sheet-{round_}.png")
                shutil.copyfile(sheet, kept)
                sheet = kept
            rounds.append({"round": round_, "log": log, "error": error, "sheet": sheet,
                           "failing": sorted(failing), "warnings": review.get("warnings")})
            if logger:
                logger.info("set authored", round=round_, failing=len(failing),
                            files=len(review["files"]), error=error)
            # A host that ended early (its turn or budget bound, a timeout) after drawing
            # something gets the next round like any other; one that drew nothing is done.
            if not failing or (error and not any(r["exists"] for r in review["files"].values())):
                break
            brief = dict(brief, repair={
                "round": round_ + 1,
                "problems": {vid: problems[:12] for vid, problems in failing.items()},
                "contact_sheet": sheet,
                "passing": sorted(set(review["files"]) - set(failing)),
                **({"previous_session": error} if error else {})})
        return review, rounds


def layout_for(work_dir):
    """The set session's directories: root (Factory-owned: brief, job, logs), out (the only
    place the author writes), preview (renders and the contact sheet)."""
    root = os.path.abspath(os.path.join(work_dir, "author-set"))
    out = os.path.join(root, "out")
    preview = os.path.join(root, "preview")
    return {"root": root, "out": out, "preview": preview, "job": os.path.join(root, "job.json"),
            "sheet": os.path.join(preview, "sheet.png")}


def craft_paths():
    return [os.path.join(paths.CORE, "craft", name) for name in SET_CRAFT
            if os.path.isfile(os.path.join(paths.CORE, "craft", name))]
