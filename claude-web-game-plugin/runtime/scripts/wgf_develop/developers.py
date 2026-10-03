"""Who writes the game. Two kinds, chosen by `factory.develop.developer.kind`.

    handoff   The brief is written into the game repository and the step waits for a
              person - or an agent host session a person drives - to implement it. Resume
              the run with a decision (`--decision done`) and the module checks the result.
              A failed check waits again with the failures, rather than failing the run:
              the fix is the same person's next edit.

    command   A configured process implements the brief unattended, typically an agent
              host's non-interactive mode. The provider is named in the installation's
              config, never in core. A failed check is a retryable failure, and the next
              attempt's brief carries the failure output.

`argv` placeholders, substituted per element: {brief} (absolute path of brief.md), {repo}
(the checkout), {key} (the idempotency key), {factory} (the Factory root, for host files that
live in the Factory rather than the checkout - an MCP config, a plugin directory - since the
developer's cwd is the checkout) and {prompt} (a one-paragraph instruction to read and
implement the brief). Each value is substituted once, verbatim; nothing is formatted twice.

`timeout_seconds` bounds the whole run; `idle_timeout_seconds` (optional) ends a developer
that has written nothing to stdout or stderr for that long - a hung agent, not a slow one.

The command runs with wgflib.agentenv's allowlisted environment plus
`factory.agents.env_passthrough`, never with the Factory's own.
"""

import inspect
import json
import os

from wgflib import paths
from wgflib import agentenv

from .brief import REPORT_PATH
from .budget import transcript_path
from .repository import ExactEnv

__all__ = ["Outcome", "HandoffDeveloper", "CommandDeveloper", "create_developer",
           "DECLINE_DECISIONS", "PROMPT", "permission_stall"]

DECLINE_DECISIONS = ("reject", "abandon", "cancel", "decline")

PROMPT = (
    "You are the gameplay and UI implementer for this game repository. Read {brief} in full "
    "and implement it in this repository: the complete MVP, every required system, the "
    "integration seam and the tests it names, following the repository's docs/ and the "
    "rules in the brief. Do not edit template-owned paths, do not add an engine, do not "
    "touch platform SDKs, do not commit and do not push. Run the checks the brief lists "
    "until they pass, then write the development report it describes. A refused command "
    "is never a reason to stop: use an allowed alternative, as the brief's 'Your shell' "
    "section says. "
    "Build the content table in the brief exactly, in order, as data in "
    "public/content/units.json; never invent a unit, a mechanic or a difficulty value the "
    "brief does not give. Where the design is silent or contradictory, make the smallest "
    "assumption, record it in report.json design_gaps with the field it concerns, and mark "
    "the unit partial."
)


class Outcome:
    DONE, WAITING, FAILED, DECLINED = "done", "waiting", "failed", "declined"

    def __init__(self, status, message, output_tail=None):
        self.status = status
        self.message = message
        self.output_tail = output_tail


class HandoffDeveloper:
    kind = "handoff"
    retry_on_check_failure = False

    def __init__(self, settings, runner):
        self.settings = settings

    def develop(self, brief_path, checkout, context):
        decision = context.decision or {}
        choice = decision.get("decision")
        if not choice:
            return Outcome(Outcome.WAITING, (
                f"development brief written to {brief_path}. Implement it in {checkout}, "
                f"write {REPORT_PATH} for this visit (\"visit\": "
                f"\"{context.idempotency_key}\"), then resume this run with --decision done "
                f"(or --decision abandon)."
            ))
        if choice in DECLINE_DECISIONS:
            return Outcome(Outcome.DECLINED,
                           f"development declined by {decision.get('decided_by', 'human')}: "
                           f"{decision.get('note') or choice}")
        return Outcome(Outcome.DONE, f"handoff completed ({choice})")


class CommandDeveloper:
    kind = "command"
    retry_on_check_failure = True

    def __init__(self, settings, runner):
        self.settings = settings
        self.runner = runner

    def develop(self, brief_path, checkout, context):
        values = {"brief": brief_path, "repo": checkout, "key": context.idempotency_key,
                  "factory": paths.ROOT}
        values["prompt"] = PROMPT.format(**values)
        argv = [part.format(**values) for part in self.settings.developer["argv"]]
        timeout = float(self.settings.developer.get("timeout_seconds") or 5400)
        idle = self.settings.developer.get("idle_timeout_seconds")
        idle = float(idle) if idle else None
        context.logger.info("develop command", argv0=os.path.basename(argv[0]),
                            timeout_s=timeout, idle_timeout_s=idle)
        kwargs = {}
        if idle is not None and _accepts(self.runner.run, "idle_timeout"):
            kwargs["idle_timeout"] = idle
        # The developer's whole transcript is evidence, not only its failure tail: keep it
        # in the run directory, outside the checkout, one file per visit and attempt.
        log_path = transcript_path(context)
        offset = 0
        if log_path and _accepts(self.runner.run, "log_path"):
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            kwargs["log_path"] = log_path
            offset = os.path.getsize(log_path) if os.path.exists(log_path) else 0
            context.logger.info("develop transcript", log=kwargs["log_path"])
        # An allowlist, not the Factory's environment (wgflib.agentenv): the developer runs
        # arbitrary code in the checkout and gets no token it was not configured to need.
        if _accepts(self.runner.run, "env"):
            kwargs["env"] = ExactEnv(agentenv.scrubbed(
                getattr(self.settings, "env_passthrough", ())))
        result = self.runner.run(argv, cwd=checkout, timeout=timeout, **kwargs)
        if result.timed_out:
            return Outcome(Outcome.FAILED, f"developer command timed out after {timeout:.0f}s",
                           result.tail())
        if getattr(result, "idle_timed_out", False):
            return Outcome(Outcome.FAILED, f"developer command wrote nothing for {idle:.0f}s "
                           f"and was ended", result.tail())
        if not result.ok:
            return Outcome(Outcome.FAILED, f"developer command exited {result.returncode}",
                           result.tail())
        # A session that was refused a command and then changed nothing gave up on its
        # shell (the live runs of 2026-10-03): say so, rather than letting the checks of
        # an unchanged tree be blamed.
        denied, wrote = permission_stall(kwargs.get("log_path"), offset)
        if denied and not wrote:
            first = " ".join(denied[0].split())
            first = first if len(first) <= 120 else first[:117] + "..."
            return Outcome(Outcome.FAILED, (
                f"developer session stopped after {len(denied)} refused tool call(s) "
                f"without changing a file (first refused: `{first}`). A refused command is "
                f"never a reason to stop: use an allowed alternative (the brief's *Your "
                f"shell*)"), result.tail())
        return Outcome(Outcome.DONE, "developer command completed", result.tail())


FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def permission_stall(path, offset=0):
    """(refused, wrote) from a stream-json transcript past `offset`: what each tool call the
    host refused asked for (a command, else a file path, else the tool's name), and whether
    any file tool call succeeded. Lines may carry the transcript's `[stdout] ` prefix; a
    transcript that is missing or not stream-json yields ([], False)."""
    if not path:
        return [], False
    try:
        with open(path, "rb") as handle:
            handle.seek(offset)
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return [], False
    calls, refused, wrote = {}, [], False
    for line in text.splitlines():
        line = line.strip()
        for prefix in ("[stdout] ", "[stderr] "):
            if line.startswith(prefix):
                line = line[len(prefix):].strip()
                break
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        message = event.get("message") if isinstance(event, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                calls[block.get("id")] = (block.get("name"), block.get("input") or {})
            elif block.get("type") == "tool_result":
                name, args = calls.get(block.get("tool_use_id"), (None, {}))
                body = block.get("content")
                if isinstance(body, list):
                    body = " ".join(str(b.get("text", "")) for b in body if isinstance(b, dict))
                if block.get("is_error") and "has been denied" in str(body):
                    refused.append(str(args.get("command") or args.get("file_path")
                                       or name or "?"))
                elif not block.get("is_error") and name in FILE_TOOLS:
                    wrote = True
    return refused, wrote


def _accepts(function, name):
    try:
        parameters = inspect.signature(function).parameters
    except (TypeError, ValueError):
        return False
    return name in parameters or any(p.kind == p.VAR_KEYWORD for p in parameters.values())


def create_developer(settings, runner):
    kinds = {HandoffDeveloper.kind: HandoffDeveloper, CommandDeveloper.kind: CommandDeveloper}
    return kinds[settings.developer["kind"]](settings, runner)
