"""The 2D asset author: an agent writes an SVG per requirement; the pipeline judges it.

Opt-in, configured under `factory.assets.author` (workspace/config/factory.yaml) or a step's
`with: {author: ...}`:

    author:
      kind: command                # none (default) | command
      argv: [...]                  # the host's non-interactive command; placeholders below
      svg_from: file               # file (default): it writes {output} | stdout: it prints
                                   # the SVG last, and the Factory writes {output}
      timeout_seconds: 600         # wall clock, per file
      idle_timeout_seconds: 300    # no output for this long ends the attempt
      repair_rounds: 2             # how often a rejected file is shown its problems again

`argv` placeholders, substituted per element and never re-formatted: {request} (the request
JSON), {output} (where to write the SVG), {prompt} (a one-paragraph instruction). The
request carries the requirement - id, type, role, dimension, description, readability,
count and variant, spec, size - the design's palette and visual identity, the quality bars
the file is held to (core/reference/asset-quality.yaml), and, when asked again, the
problems with the previous file (`repair`) or the findings that sent the step back
(`notes`).

With `svg_from: stdout` the author needs no write tool at all: the last complete <svg>
element in what it prints (fenced or not) is the file, written at {output} by the Factory
- the way the design author and the 3D model author take stdout. A host that prints no SVG
wrote nothing, as with a missing file.

The author only writes a FILE. The pipeline validates it (format, unsafe constructs) and
judges it (wgf_assets.quality) exactly as it judges a library file; nothing here relaxes a
check. A file that fails is shown to the author with exactly those problems and asked
again, `repair_rounds` times; one still failing after the last is not delivered, and the
requirement falls back to a placeholder that says so.

Like every Factory agent host, it runs through wgflib.procs (its own process tree, killed on
timeout or cancel) with the allowlisted agent environment (wgflib.agentenv) plus
`factory.agents.env_passthrough`.
"""

import json
import os
import re

from wgflib import agentenv, procs

__all__ = ["CommandAuthor", "AuthorError", "AuthorRunFailed", "build_author", "last_svg",
           "KINDS", "SVG_FROM", "MAX_REPAIR_ROUNDS", "AUTHOR_CRAFT"]

KINDS = ("none", "command")
MAX_REPAIR_ROUNDS = 2
SVG_FROM = ("file", "stdout")
DEFAULTS = {"kind": "none", "argv": [], "svg_from": "file", "timeout_seconds": 600,
            "idle_timeout_seconds": 300, "repair_rounds": MAX_REPAIR_ROUNDS}
MAX_BYTES = 1024 * 1024
_SVG_TAG = re.compile(r"<(/?)svg(?=[\s>/])", re.IGNORECASE)

# The craft playbooks (core/craft/) the request's `craft` names, in reading order.
AUTHOR_CRAFT = ("production-art-2d.md", "production-art-and-ui.md")

PROMPT = (
    "You are the 2D artist for this game. Read the request at {request}: one asset the "
    "design needs - its role, description, readability line and spec - with the game's "
    "palette and visual identity. Draw it as one self-contained SVG file at {output}: a "
    "root <svg> with a viewBox, built from several shapes so a first-time player recognises "
    "it at the stated size, using the palette's colours. No scripts, no embedded images, no "
    "references to other files. The craft guides are the request's `craft`: read them "
    "first. Write only the file."
)
PROMPT_STDOUT = (
    "You are the 2D artist for this game. Read the request at {request}: one asset the "
    "design needs - its role, description, readability line and spec - with the game's "
    "palette and visual identity. Draw it as one self-contained SVG: a root <svg> with a "
    "viewBox, built from several shapes so a first-time player recognises it at the stated "
    "size, using the palette's colours. No scripts, no embedded images, no references to "
    "other files. The craft guides are the request's `craft`: read them first. End your "
    "answer with the complete SVG, from <svg to </svg>; print nothing after it."
)
PROMPT_REPAIR = (
    " Your previous file (the request's `repair.previous`) was rejected for the reasons in "
    "`repair.problems`. Write it again with exactly those fixed."
)
PROMPT_NOTES = (
    " The running game was judged and this asset was named in the findings in `notes`: "
    "address them."
)


class AuthorError(ValueError):
    """The author is not configured, or misconfigured. Not retryable."""


class AuthorRunFailed(RuntimeError):
    """The host failed, timed out, went silent or wrote nothing."""


class CommandAuthor:
    kind = "command"

    def __init__(self, settings, config=None):
        self.settings = dict(DEFAULTS)
        self.settings.update(settings or {})
        argv = self.settings.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise AuthorError("factory.assets.author.argv is not configured (a non-empty list "
                              "of strings); the command author has nothing to run")
        rounds = self.settings.get("repair_rounds")
        if not isinstance(rounds, int) or isinstance(rounds, bool) or not 0 <= rounds <= 5:
            raise AuthorError("factory.assets.author.repair_rounds must be an integer 0..5")
        try:
            for part in argv:
                part.format(request="", output="", prompt="")
        except (KeyError, IndexError, ValueError) as exc:
            raise AuthorError(f"factory.assets.author.argv has a placeholder this author does "
                              f"not provide ({exc}); use {{request}}, {{output}}, {{prompt}}, "
                              f"and double any literal brace") from exc
        if self.settings.get("svg_from") not in SVG_FROM:
            raise AuthorError("factory.assets.author.svg_from must be file or stdout")
        self.argv = argv
        self.repair_rounds = rounds
        self.svg_from = self.settings["svg_from"]
        try:
            self.env = agentenv.scrubbed(agentenv.passthrough(config or {}))
        except ValueError as exc:
            raise AuthorError(str(exc)) from exc

    @property
    def label(self):
        return f"author:{self.kind}"

    def write(self, request, output, work_dir, stem):
        """Run the host once for `request`; return the bytes it wrote at `output`."""
        # Absolute: the host runs in work_dir, and the prompt names both paths.
        work_dir, output = os.path.abspath(work_dir), os.path.abspath(output)
        os.makedirs(work_dir, exist_ok=True)
        request_path = os.path.join(work_dir, f"{stem}.request.json")
        log_path = os.path.join(work_dir, f"{stem}.log")
        for stale in (output, log_path):
            if os.path.exists(stale):
                os.remove(stale)
        with open(request_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(request, handle, indent=2, ensure_ascii=False, sort_keys=True)
        values = {"request": request_path, "output": output}
        prompt = (PROMPT_STDOUT if self.svg_from == "stdout" else PROMPT).format(**values)
        if request.get("repair"):
            prompt += PROMPT_REPAIR
        if request.get("notes"):
            prompt += PROMPT_NOTES
        values["prompt"] = prompt
        try:
            command = [part.format(**values) for part in self.argv]
        except (KeyError, IndexError, ValueError) as exc:
            raise AuthorError(f"factory.assets.author.argv has a placeholder this author does "
                              f"not provide ({exc}); use {{request}}, {{output}}, {{prompt}}, "
                              f"and double any literal brace") from exc
        result = procs.run(command, cwd=work_dir, env=self.env,
                           timeout=self.settings.get("timeout_seconds"),
                           idle_timeout=self.settings.get("idle_timeout_seconds"),
                           log_path=log_path, heartbeat_seconds=15.0)
        if not result.ok:
            raise AuthorRunFailed(
                f"the asset author {os.path.basename(command[0])} ended "
                f"{'timed out' if result.timed_out or result.idle_timed_out else 'with exit ' + str(result.returncode)}"
                f"{'; ' + result.error if result.error else ''}; log: {log_path}")
        if self.svg_from == "stdout":
            svg = last_svg(result.stdout or "")
            if svg is None:
                raise AuthorRunFailed(f"the asset author printed no SVG; log: {log_path}")
            data = svg.encode("utf-8")
            if len(data) > MAX_BYTES:
                raise AuthorRunFailed(f"the asset author printed more than {MAX_BYTES} bytes")
            with open(output, "wb") as handle:
                handle.write(data)
            return data
        if not os.path.isfile(output):
            raise AuthorRunFailed(f"the asset author wrote nothing at {output}")
        if os.path.getsize(output) > MAX_BYTES:
            raise AuthorRunFailed(f"the asset author wrote more than {MAX_BYTES} bytes")
        with open(output, "rb") as handle:
            return handle.read()


def last_svg(text):
    """The last complete <svg>...</svg> root element in `text`, or None. Nested <svg>
    elements stay inside their root; a code fence or prose around it is not part of it."""
    found, depth, start = None, 0, None
    for match in _SVG_TAG.finditer(text):
        if match.group(1):
            if depth:
                depth -= 1
                close = text.find(">", match.end())
                if not depth and close >= 0:
                    found = text[start:close + 1]
        else:
            close = text.find(">", match.end())
            if close < 0:
                break
            if text[close - 1] == "/":  # <svg .../>: an element with nothing in it
                if not depth:
                    found = text[match.start():close + 1]
                continue
            if not depth:
                start = match.start()
            depth += 1
    return found


def build_author(settings, config=None):
    """The configured author, or None when `kind` is none/absent. AuthorError when it is
    misconfigured: an installation that asked for an author and gets placeholders silently
    is exactly the failure this exists to prevent."""
    settings = dict(settings or {})
    kind = settings.get("kind") or "none"
    if kind not in KINDS:
        raise AuthorError(f"factory.assets.author.kind must be one of {', '.join(KINDS)}, "
                          f"not {kind!r}")
    if kind == "none":
        return None
    return CommandAuthor(settings, config)
