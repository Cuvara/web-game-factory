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
(the checkout), {key} (the idempotency key) and {prompt} (a one-paragraph instruction to
read and implement the brief).
"""

import os

__all__ = ["Outcome", "HandoffDeveloper", "CommandDeveloper", "create_developer",
           "DECLINE_DECISIONS", "PROMPT"]

DECLINE_DECISIONS = ("reject", "abandon", "cancel", "decline")

PROMPT = (
    "You are the gameplay and UI implementer for this game repository. Read {brief} in full "
    "and implement it in this repository: the complete MVP, every required system, the "
    "integration seam and the tests it names, following the repository's docs/ and the "
    "rules in the brief. Do not edit template-owned paths, do not add an engine, do not "
    "touch platform SDKs, do not commit and do not push. Run the checks the brief lists "
    "until they pass, then write the development report it describes."
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
                f"then resume this run with --decision done (or --decision abandon)."
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
        values = {"brief": brief_path, "repo": checkout, "key": context.idempotency_key}
        values["prompt"] = PROMPT.format(**values)
        argv = [part.format(**values) for part in self.settings.developer["argv"]]
        timeout = float(self.settings.developer.get("timeout_seconds") or 5400)
        context.logger.info("develop command", argv0=os.path.basename(argv[0]),
                            timeout_s=timeout)
        result = self.runner.run(argv, cwd=checkout, timeout=timeout)
        if result.timed_out:
            return Outcome(Outcome.FAILED, f"developer command timed out after {timeout:.0f}s",
                           result.tail())
        if not result.ok:
            return Outcome(Outcome.FAILED, f"developer command exited {result.returncode}",
                           result.tail())
        return Outcome(Outcome.DONE, "developer command completed", result.tail())


def create_developer(settings, runner):
    kinds = {HandoffDeveloper.kind: HandoffDeveloper, CommandDeveloper.kind: CommandDeveloper}
    return kinds[settings.developer["kind"]](settings, runner)
