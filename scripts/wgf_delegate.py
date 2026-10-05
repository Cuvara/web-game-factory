"""Delegating a task to an agent that works in its own worktree, through Orca.

The coordinator of a multi-agent run (a person, or a lead agent) hands one concrete task to
one agent. The agent must work in an isolated checkout, so that parallel agents never share a
working tree; and the checkout must exist *because* an agent works there. A worktree with no
agent in it is a branch nobody is building.

The defect this module exists to prevent (validation run, 2026-10-03): the coordinator started
every worker with `orca orchestration worker-start --worktree current`, which opened the
agent's terminal in the coordinator's own checkout, and told each worker in prose to run
`git worktree add` itself. Every worker then created a worktree Orca did not know about,
edited it through absolute paths from a terminal in the wrong place, and left it behind when
it finished. Orca showed the agents under the coordinator's checkout and the worktrees as
empty; game workers also created extra "fix" worktrees for side tasks no agent of their own
ever ran. Nothing tied a worktree to the agent and the task it existed for.

One supported Orca call does all of it, and is the only one this module makes to start work:

    orca orchestration worker-start --spec <task> --worktree new-top-level --name <name>
        --repo path:<repo> --base-branch <ref> --agent claude --run <run> --json

Orca creates the worktree (branch `<user>/<name>`, under its workspaces directory), starts
the agent's terminal *in* it and delivers the task, in one receipt. `spawn` then refuses to
report success unless the receipt proves all three - a worktree created, an agent terminal
created, the task input accepted - and `worker-show` places the dispatch in that same
worktree.

Every delegation is a sequence of lifecycle events in an append-only ledger, one task id per
sequence (AGENT_REQUESTED, WORKTREE_CREATED, AGENT_SPAWNED, AGENT_STARTED, AGENT_WORKING,
AGENT_COMPLETED, ...). The second defect it prevents (2026-10-05): a spawn whose dispatch Orca
had started - an agent that went on to finish and commit - failed a later git check and
recorded nothing, so the ledger had no trace of a real agent and worktree. Once Orca's receipt
names a dispatch, every failure is recorded (AGENT_UNVERIFIED) with the remedy. A worktree's
existence or its commits never imply an agent state; only Orca's outcome `succeeded` is
completion. `status` derives the live state of one delegation, `audit` says of every worktree
on disk whether an agent is working in it, finished in it, or never did - and UNKNOWN when its
git state cannot be read, never "orphaned".

Paths cross the Windows/WSL boundary: Orca on a WSL host reports `\\\\wsl.localhost\\<distro>\\...`
worktrees to Windows processes, and `/mnt/<d>/...` paths to WSL ones. `to_local` translates
for the host this process runs on, and git on Windows reads a WSL worktree through
`wsl.exe -d <distro> git`.

Standard library only. The orca executable is `WGF_ORCA`, else `ORCA_CLI_COMMAND` (the
launcher Orca names in its terminals, `orca-ide` under WSL), else `orca` on PATH; the ledger
is `WGF_DELEGATION_LEDGER` or `~/.cache/wgf/delegations.jsonl`. See docs/orca-delegation.md.
"""

import datetime as _dt
import functools
import json
import os
import pathlib
import re
import shutil

from wgflib import procs

__all__ = ["DelegationError", "OrcaUnavailable", "Delegation", "spawn", "adopt", "status",
           "audit", "worktrees", "ledger_path", "read_ledger", "delegations", "parse_receipt",
           "preamble", "to_local", "git_argv", "host_kind", "orca_executable", "CLASSES",
           "STATES"]

# The states a worktree can be in, from the coordinator's point of view.
ACTIVE = "ACTIVE AGENT"            # an agent is working in it now
COMPLETED = "COMPLETED WORK"       # an agent finished in it; its commits are pushed or merged
UNFINISHED = "UNFINISHED WORK"     # uncommitted changes, or commits nowhere else, no live agent
ORPHANED = "ORPHANED WORKTREE"     # no agent ever worked in it, nothing in it worth keeping
STALE = "STALE WORKTREE"           # its branch is already merged into the base
AGENT_ORPHANED_WORKTREE = "AGENT ORPHANED"  # a recorded agent's dispatch died unfinished
MAIN = "MAIN CHECKOUT"             # the repository's own working tree
UNKNOWN = "UNKNOWN"                # its git state, or its agent's, cannot be read
CLASSES = (ACTIVE, COMPLETED, UNFINISHED, ORPHANED, STALE, AGENT_ORPHANED_WORKTREE, MAIN,
           UNKNOWN)

# The lifecycle of one delegation, recorded per task id. The worktree's own state is separate:
# WORKTREE_CREATED never implies anything about the agent.
WORKTREE_CREATED = "WORKTREE_CREATED"
AGENT_REQUESTED = "AGENT_REQUESTED"      # worker-start is about to be called
AGENT_SPAWN_FAILED = "AGENT_SPAWN_FAILED"  # Orca refused: no dispatch exists
AGENT_SPAWNED = "AGENT_SPAWNED"          # the receipt proves worktree, agent terminal, task
AGENT_STARTED = "AGENT_STARTED"          # the agent's turn began, in its verified worktree
AGENT_WORKING = "AGENT_WORKING"          # Orca: dispatch live and working
AGENT_COMPLETED = "AGENT_COMPLETED"      # Orca: outcome succeeded
AGENT_FAILED = "AGENT_FAILED"            # Orca: outcome failed
AGENT_CANCELLED = "AGENT_CANCELLED"      # Orca: dispatch cancelled / stopped
AGENT_ORPHANED = "AGENT_ORPHANED"        # dispatch not live, no completion evidence
AGENT_UNVERIFIED = "AGENT_UNVERIFIED"    # a dispatch exists, but what it is doing is unproven
STATES = (WORKTREE_CREATED, AGENT_REQUESTED, AGENT_SPAWN_FAILED, AGENT_SPAWNED, AGENT_STARTED,
          AGENT_WORKING, AGENT_COMPLETED, AGENT_FAILED, AGENT_CANCELLED, AGENT_ORPHANED,
          AGENT_UNVERIFIED)
SETTLED = (AGENT_COMPLETED, AGENT_FAILED, AGENT_CANCELLED)
# A task in one of these has (or may have) an agent on it: spawning it again would start a
# second agent on the same task.
OCCUPIED = (AGENT_SPAWNED, AGENT_STARTED, AGENT_WORKING, AGENT_UNVERIFIED, AGENT_COMPLETED)
_UNSTARTED_STAGES = ("", "turn_start_unobserved", "input_accepted")
_CANCELLED = ("cancelled", "canceled", "stopped")

_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}$")
_UNC = re.compile(r"^[\\/]{2}(?:wsl\.localhost|wsl\$)[\\/]([^\\/]+)(.*)$", re.IGNORECASE)
_MNT = re.compile(r"^/mnt/([a-zA-Z])(/.*)?$")
_DRIVE = re.compile(r"^([a-zA-Z]):(?:[\\/](.*))?$")


class DelegationError(Exception):
    """A delegation that could not be proven to have an agent working in its worktree."""


class OrcaUnavailable(DelegationError):
    """Orca itself could not be asked: no executable, or an answer that is not Orca's."""


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- hosts and paths ----------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def host_kind():
    """Where this process runs: "windows", "wsl" (Linux inside WSL) or "linux"."""
    if os.name == "nt":
        return "windows"
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return "wsl"
    try:
        with open("/proc/sys/kernel/osrelease", encoding="utf-8") as handle:
            if "microsoft" in handle.read().lower():
                return "wsl"
    except OSError:
        pass
    return "linux"


def wsl_location(path, host=None):
    """(distro or None, Linux path) when `path`, as seen from a Windows process, is a file
    inside a WSL distribution: `\\\\wsl.localhost\\<distro>\\...`, `\\\\wsl$\\<distro>\\...`,
    or a POSIX path that is not under /mnt/<drive>. None otherwise (and off Windows)."""
    if (host or host_kind()) != "windows":
        return None
    text = str(path or "")
    match = _UNC.match(text)
    if match:
        return match.group(1), "/" + match.group(2).replace("\\", "/").strip("/")
    posix = text.replace("\\", "/")
    if posix.startswith("/") and not posix.startswith("//") and not _MNT.match(posix):
        return os.environ.get("WSL_DISTRO_NAME") or None, posix
    return None


def to_local(path, host=None):
    """`path` as this host's own tools address it. Under WSL or Linux a WSL UNC path is the
    Linux path it names (and, under WSL, `C:/x` is `/mnt/c/x`); on Windows `/mnt/c/x` is
    `C:/x`. Anything else is returned unchanged."""
    host = host or host_kind()
    text = str(path or "")
    if not text:
        return text
    if host != "windows":
        match = _UNC.match(text)
        if match:
            return "/" + match.group(2).replace("\\", "/").strip("/")
        drive = _DRIVE.match(text)
        if host == "wsl" and drive:
            rest = (drive.group(2) or "").replace("\\", "/").strip("/")
            return f"/mnt/{drive.group(1).lower()}" + (f"/{rest}" if rest else "")
        return text
    match = _MNT.match(text.replace("\\", "/"))
    if match:
        return f"{match.group(1).upper()}:{match.group(2) or '/'}"
    return text


def _norm(path, host=None):
    """A path as a comparable string: translated for this host, forward slashes, no trailing
    slash, case-folded for Windows drive paths (Orca reports `C:/...`, git `C:/...` or
    `c:/...`). On Windows a WSL path compares as the Linux path it names."""
    host = host or host_kind()
    located = wsl_location(path, host)
    if located:
        return located[1].rstrip("/") or "/"
    text = to_local(path, host).replace("\\", "/").rstrip("/")
    return text.lower() if host == "windows" else text


def git_argv(path, args, host=None):
    """The argv that runs `git -C <path> <args>` for this host: through `wsl.exe -d <distro>`
    when this is Windows and the worktree lives inside WSL (Windows git cannot follow a WSL
    worktree's `gitdir: /mnt/...` link)."""
    host = host or host_kind()
    located = wsl_location(path, host)
    if located:
        distro, linux = located
        wsl = shutil.which("wsl.exe") or shutil.which("wsl") or "wsl.exe"
        return [wsl] + (["-d", distro] if distro else []) + ["git", "-C", linux] + list(args)
    return ["git", "-C", to_local(path, host)] + list(args)


def _git(path, *args):
    """(returncode, output) of git in `path`; a git that could not run at all is 127, and a
    failure carries git's own message."""
    proc = procs.run(git_argv(path, args), timeout=120, heartbeat_seconds=0)
    if proc.error is not None or proc.returncode is None:
        return 127, f"git could not run for {path}: {proc.error or proc.status}"
    if proc.returncode != 0:
        return proc.returncode, (proc.tail(5) or f"git exited {proc.returncode}").strip()
    return 0, (proc.stdout or "").strip()


# -- orca ---------------------------------------------------------------------------------

def orca_executable():
    """WGF_ORCA as given; else ORCA_CLI_COMMAND (the launcher Orca exports into its
    terminals - `orca-ide` from a WSL shell, where `orca` is not on PATH); else `orca`."""
    explicit = os.environ.get("WGF_ORCA")
    if explicit:
        return explicit
    for name in (os.environ.get("ORCA_CLI_COMMAND"), "orca"):
        found = shutil.which(name) if name else None
        if found:
            return found
    raise OrcaUnavailable("orca is not on PATH (set WGF_ORCA, or run where ORCA_CLI_COMMAND "
                          "names the launcher)")


def _orca_name():
    try:
        return os.path.basename(orca_executable())
    except DelegationError:
        return "orca"


def _invoke(args, runner):
    argv = [orca_executable()] + list(args)
    if runner is not None:
        return runner(argv)
    proc = procs.run(argv, timeout=600, heartbeat_seconds=0)
    if proc.error is not None:
        raise OrcaUnavailable(f"{argv[0]} could not run: {proc.error}")
    return proc.returncode, proc.stdout


def _orca(args, runner=None):
    """Run orca with `args`, return its parsed JSON envelope. `runner` replaces wgflib.procs
    in tests: runner(argv) -> (returncode, stdout)."""
    code, out = _invoke(args, runner)
    try:
        envelope = json.loads(out)
    except (TypeError, ValueError):
        raise OrcaUnavailable(f"orca {args[0]} {args[1] if len(args) > 1 else ''}: "
                              f"not JSON (exit {code}): {str(out)[:300]}")
    if code != 0 or not envelope.get("ok", False):
        error = envelope.get("error") or {}
        raise DelegationError(f"orca {' '.join(args[:2])} failed (exit {code}): "
                              f"{error.get('message') or str(out)[:300]}")
    return envelope.get("result") or {}


# -- the ledger ---------------------------------------------------------------------------

def ledger_path():
    override = os.environ.get("WGF_DELEGATION_LEDGER")
    if override:
        return pathlib.Path(override)
    return pathlib.Path.home() / ".cache" / "wgf" / "delegations.jsonl"


def read_ledger(path=None):
    path = pathlib.Path(path or ledger_path())
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
    return entries


def _append_ledger(entry, path=None):
    path = pathlib.Path(path or ledger_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def record(task_id, state, ledger=None, **fields):
    """Append one lifecycle event for `task_id`. Fields that are None are left out."""
    if state not in STATES:
        raise ValueError(f"unknown lifecycle state {state!r}")
    event = {"task_id": task_id, "state": state, "at": _now()}
    event.update({k: v for k, v in fields.items() if v is not None})
    _append_ledger(event, ledger)
    return event


# Per-event detail that describes the event, not the delegation.
_EVENT_ONLY = ("state", "at", "error", "reason", "orca", "remedy")


def delegations(entries):
    """task id -> the delegation folded from its events, in first-recorded order: every field
    last recorded, `state` (the latest agent state), `worktree_state`, `history`. A new
    AGENT_REQUESTED for the same task starts a new attempt (the history is kept). A line
    written before lifecycle events existed is read as AGENT_SPAWNED."""
    folded = {}
    for entry in entries:
        task = entry.get("task_id")
        if not task:
            continue
        state = entry.get("state") or (AGENT_SPAWNED if entry.get("dispatch") else None)
        at = entry.get("at") or entry.get("created_at")
        current = folded.get(task)
        if current is None or state == AGENT_REQUESTED:
            history = current["history"] if current else []
            current = folded[task] = Delegation(task_id=task, state=None, worktree_state=None,
                                                history=history)
        for key, value in entry.items():
            if key not in _EVENT_ONLY and value is not None:
                current[key] = value
        current["history"].append({"state": state, "at": at})
        if state == WORKTREE_CREATED:
            current["worktree_state"] = state
        elif state:
            current["state"] = state
            current["updated_at"] = at
            current.pop("last_error", None)
        if entry.get("error"):
            current["last_error"] = entry["error"]
    return folded


def _find(ident, ledger=None):
    folded = delegations(read_ledger(ledger))
    if ident in folded:
        return folded[ident]
    for found in reversed(list(folded.values())):
        if found.get("dispatch") == ident:
            return found
    raise DelegationError(f"no delegation recorded for {ident!r} (a task id or a dispatch id)")


def preamble(task_id, name, base, repo):
    """What every delegated agent is told before its task, whatever the task. The task text
    follows it verbatim."""
    return f"""# Delegated task {task_id}

You were started by Orca INSIDE your own isolated git worktree, created for this task alone
(name `{name}`, branched from `{base}` of {repo}). Your current working directory IS that
worktree. Rules that hold whatever the task says:

- Work only in your current working directory. Do not create other worktrees or clones, do not
  edit any other checkout (other agents and live runs use them), do not switch branches.
- Implement the task, run the relevant tests, and commit your work on your current branch
  (LF line endings). Uncommitted work counts as not done.
- Do not push, open pull requests, or create repositories: the coordinator integrates.
- Stop only processes you started, by PID (`taskkill /PID <pid> /T /F` or `kill <pid>`). Never
  kill by image name (`taskkill /IM`, `pkill`, `killall`): other agents' runs share this machine.
- Report with the orchestration commands in your preamble: progress at milestones, and exactly
  one `worker_done` naming the commit SHA(s), the files changed, the tests run with their results,
  and anything left undone. `--outcome failed` if you could not finish.

---

"""


class Delegation(dict):
    """One delegation: what was delegated, where, to which dispatch, and its state."""


def _effect(result, kind, role=None):
    for effect in result.get("effects") or []:
        if effect.get("kind") == kind and (role is None or effect.get("role", role) == role):
            return effect
    return None


def _path_of(worktree_id):
    worktree_id = str(worktree_id or "")
    return worktree_id.split("::", 1)[1] if "::" in worktree_id else worktree_id


def parse_receipt(result):
    """From a `worker-start --worktree new-top-level` receipt, the created worktree, the agent
    terminal and the dispatch - or DelegationError naming what the receipt does not prove."""
    worktree = _effect(result, "worktree")
    terminal = _effect(result, "terminal", "agent")
    accepted = _effect(result, "dispatch_input")
    problems = []
    if not result.get("dispatchId"):
        problems.append("no dispatch")
    if not worktree:
        problems.append("no worktree effect")
    elif not str(worktree.get("action") or "").startswith("created"):
        # Orca reports "created" or "created_top_level"; "reused" is someone else's checkout.
        problems.append(f"worktree was {worktree.get('action')!r}, not created for this task")
    if not terminal:
        problems.append("no agent terminal")
    if not accepted or accepted.get("state") != "accepted":
        problems.append("task input not accepted by the agent terminal")
    launch = (result.get("launch") or {}).get("effective") or {}
    if launch and not launch.get("agent"):
        problems.append("no agent launched")
    if problems:
        started = (f" (dispatch {result['dispatchId']} WAS started: inspect it with "
                   f"`{_orca_name()} orchestration worker-show --dispatch "
                   f"{result['dispatchId']}`)" if result.get("dispatchId") else "")
        raise DelegationError("worker-start did not prove an agent working in a new worktree: "
                              + "; ".join(problems) + started)
    worktree_id = worktree.get("id") or ""
    return {"dispatch": result["dispatchId"], "task": result.get("taskId"),
            "run": result.get("runId"), "worktree_id": worktree_id,
            "worktree": _path_of(worktree_id), "terminal": terminal.get("id"),
            "agent": launch.get("agent")}


TRUST_BLOCK = "agent-trust-workspace"


def _screen(terminal, runner=None):
    result = _orca(["terminal", "read", "--terminal", terminal, "--screen", "--json"], runner)
    term = result.get("terminal") or result
    return [str(line) for line in (term.get("tail") or term.get("lines") or [])]


def _selected(lines, label):
    """Whether the dialog's highlighted (marked) option is `label`: the selected row starts
    with a marker glyph, the others with spaces."""
    for line in lines:
        if label in line:
            return not line.lstrip(" ").startswith(label)
    return False


def accept_trust(terminal, runner=None, sleep=None, attempts=6):
    """Answer Claude Code's first-run 'Is this a project you trust?' dialog with 'Yes, I trust
    this folder' in `terminal` - only ever called when the coordinator passed
    `--trust-workspace` for a repository it owns. Returns True once the dialog is gone."""
    import time
    sleep = sleep or time.sleep
    down = "[B"
    for _ in range(attempts):
        lines = _screen(terminal, runner)
        if not any("Yes, I trust this folder" in line for line in lines[-6:]):
            return True
        if _selected(lines[-6:], "Yes, I trust this folder"):
            _orca(["terminal", "send", "--terminal", terminal, "--enter", "--json"], runner)
        else:
            _orca(["terminal", "send", "--terminal", terminal, "--text", down, "--json"], runner)
        sleep(2)
    return not any("Yes, I trust this folder" in line for line in _screen(terminal, runner)[-6:])


def ensure_repo(repo, runner=None):
    """Register `repo` with Orca if it is not yet (a game repository created locally by the
    Factory's init is not): `worker-start --repo path:` needs a registered repository."""
    try:
        _orca(["repo", "show", "--repo", f"path:{repo}", "--json"], runner)
        return False
    except OrcaUnavailable:
        raise
    except DelegationError:
        _orca(["repo", "add", "--path", str(repo), "--json"], runner)
        return True


def _start(args, runner):
    """worker-start, returning its result even when Orca reports the attempt failed (the
    receipt still names the dispatch, task, worktree and terminal it created)."""
    code, out = _invoke(args, runner)
    try:
        envelope = json.loads(out)
    except (TypeError, ValueError):
        raise DelegationError(f"orca worker-start: not JSON (exit {code}): {str(out)[:300]}")
    result = envelope.get("result") or {}
    if not result.get("dispatchId"):
        error = envelope.get("error") or {}
        raise DelegationError(f"orca worker-start failed (exit {code}): "
                              f"{error.get('message') or str(out)[:300]}")
    return result


def _recover_trust(result, run, runner, sleep=None):
    """The agent stopped at Claude Code's workspace-trust dialog: accept it in the agent's
    own terminal, then deliver the same task to that terminal as a retry of the failed
    dispatch. Returns the retry's receipt."""
    worktree = (_effect(result, "worktree") or {}).get("id")
    terminal = (_effect(result, "terminal") or {}).get("id")
    if not (worktree and terminal and result.get("taskId")):
        raise DelegationError("trust recovery: the failed receipt names no worktree/terminal/task")
    if not accept_trust(terminal, runner, sleep):
        raise DelegationError(f"trust recovery: the trust dialog in {terminal} did not close")
    args = ["orchestration", "worker-start", "--task", result["taskId"], "--terminal", terminal,
            "--worktree", f"id:{worktree}", "--retry-of", result["dispatchId"], "--json"]
    if run:
        args += ["--run", run]
    retry = _start(args, runner)
    # A retry onto a live terminal launches nothing: the agent is the one the first attempt
    # launched (observed live: launch.effective carries no agent on the retry).
    retry["launch"] = result.get("launch") or retry.get("launch")
    # The retry reuses the worktree this task's first attempt created.
    for effect in retry.get("effects") or []:
        if effect.get("kind") == "worktree":
            effect["action"] = "created_top_level"
            effect["id"] = worktree
        if effect.get("kind") == "dispatch_input" and effect.get("state") == "turn_unobserved":
            effect["state"] = "accepted"
    if not _effect(retry, "terminal"):
        retry.setdefault("effects", []).append({"kind": "terminal", "role": "agent",
                                                "id": terminal})
    return retry


def _confirm_turn(result, dispatch, runner=None, sleep=None, wait_s=150, poll_s=10):
    """The agent must have STARTED working on the task, not merely had it typed at it.
    Observed live: a receipt with the input 'accepted' but turnStart unobserved, and the
    agent sitting at an empty prompt two hours later. Orca reports the turn as observed in
    the receipt, or later on the dispatch's worker stage; wait for either, else refuse."""
    import time
    sleep = sleep or time.sleep
    if result.get("turnStart") == "observed" or "turn_started" in (result.get("stages") or []):
        return
    waited = 0
    while waited <= wait_s:
        info = _orca(["orchestration", "worker-show", "--dispatch", dispatch, "--json"], runner)
        worker = info.get("worker") or {}
        stage = str(worker.get("stage") or "")
        activity = str(((info.get("projection") or {}).get("stage") or {}).get("activity") or "")
        if stage not in _UNSTARTED_STAGES or activity == "working":
            return
        sleep(poll_s)
        waited += poll_s
    raise DelegationError(
        f"dispatch {dispatch}: the task was typed into the agent's terminal but the agent never "
        f"started a turn in {wait_s} s (the prompt is likely empty)")


def _remedy(task_id, dispatch, title=None):
    orca = _orca_name()
    return (f"Inspect it with `{orca} orchestration worker-show --dispatch {dispatch}`; then "
            f"either record it once it is proven - `wgf-delegate adopt --dispatch {dispatch} "
            f"--task-id {task_id} --title {json.dumps(title or task_id)}` - or stop it with "
            f"`{orca} orchestration worker-stop --dispatch {dispatch}`")


def spawn(task_id, title, spec, name, repo, base="main", agent="claude", run=None,
          model=None, runner=None, ledger=None, verify_git=True, trust_workspace=False,
          sleep=None, role=None):
    """Delegate one task: Orca creates the worktree, starts the agent in it and gives it the
    task. Returns the delegation. Raises DelegationError when it cannot be proven - after
    recording AGENT_SPAWN_FAILED (Orca started nothing) or AGENT_UNVERIFIED (a dispatch
    exists: the error names it and the remedy). Nothing is recorded only for a task refused
    before Orca was asked."""
    if not _NAME.match(name or ""):
        raise DelegationError(f"worktree name {name!r}: lowercase letters, digits and '-', "
                              "2-49 characters")
    if not str(spec or "").strip():
        raise DelegationError("a delegation needs a concrete task: the spec is empty")
    previous = delegations(read_ledger(ledger)).get(task_id)
    if previous and previous.get("state") in OCCUPIED:
        raise DelegationError(
            f"task {task_id} is already delegated (dispatch {previous.get('dispatch')}, "
            f"{previous.get('state')}): run `wgf-delegate status {task_id}`, or give the new "
            "task its own id")
    repo = str(pathlib.Path(repo).resolve())
    ensure_repo(repo, runner)
    args = ["orchestration", "worker-start",
            "--spec", preamble(task_id, name, base, repo) + spec,
            "--task-title", title,
            "--worktree", "new-top-level", "--name", name,
            "--repo", f"path:{repo}", "--base-branch", base,
            "--setup", "skip", "--agent", agent, "--json"]
    if model:
        args += ["--model", model]
    if run:
        args += ["--run", run]
    record(task_id, AGENT_REQUESTED, ledger, title=title, role=role, name=name, repo=repo,
           base=base, agent=agent, run=run)
    try:
        result = _start(args, runner)
    except DelegationError as exc:
        record(task_id, AGENT_SPAWN_FAILED, ledger, error=str(exc))
        raise
    # From here a dispatch exists: whatever fails is recorded with it.
    seen = {"dispatch": result.get("dispatchId"),
            "terminal": (_effect(result, "terminal") or {}).get("id"),
            "worktree_id": (_effect(result, "worktree") or {}).get("id")}
    first = seen["dispatch"]
    try:
        created = _effect(result, "worktree")
        if created and str(created.get("action") or "").startswith("created"):
            record(task_id, WORKTREE_CREATED, ledger, worktree_id=created.get("id"),
                   worktree=_path_of(created.get("id")), dispatch=seen["dispatch"])
        if result.get("state") == "failed":
            result = _failed_start(result, run, runner, sleep, trust_workspace)
            seen.update(dispatch=result.get("dispatchId"),
                        terminal=(_effect(result, "terminal") or {}).get("id") or seen["terminal"])
        placed = parse_receipt(result)
        seen.update(dispatch=placed["dispatch"], terminal=placed["terminal"],
                    worktree_id=placed["worktree_id"])
        retry_of = first if placed["dispatch"] != first else None
        record(task_id, AGENT_SPAWNED, ledger, retry_of=retry_of, **placed)
        _confirm_turn(result, placed["dispatch"], runner, sleep)
        shown = _orca(["orchestration", "worker-show", "--dispatch", placed["dispatch"],
                       "--json"], runner)
        workspace = ((shown.get("projection") or shown).get("workspace") or {}).get("id") or ""
        if _norm(_path_of(workspace)) != _norm(placed["worktree"]):
            raise DelegationError(f"dispatch {placed['dispatch']} runs in {workspace!r}, not in "
                                  f"its worktree {placed['worktree']!r}")
        branch = None
        if verify_git:
            code, out = _git(placed["worktree"], "rev-parse", "--abbrev-ref", "HEAD")
            if code != 0:
                raise DelegationError(f"{placed['worktree']} is not a readable git worktree "
                                      f"from this host ({host_kind()}): {out}")
            branch = out
        record(task_id, AGENT_STARTED, ledger, branch=branch, dispatch=placed["dispatch"])
    except Exception as exc:  # noqa: BLE001 - a started dispatch is never left unrecorded
        remedy = _remedy(task_id, seen["dispatch"], title)
        record(task_id, AGENT_UNVERIFIED, ledger, error=str(exc), remedy=remedy,
               worktree=_path_of(seen["worktree_id"]) or None, **seen)
        raise DelegationError(f"{exc}\nAGENT_UNVERIFIED recorded for task {task_id} "
                              f"(dispatch {seen['dispatch']}, terminal {seen['terminal']}, "
                              f"worktree {seen['worktree_id']}). {remedy}.") from exc
    return _find(task_id, ledger)


def _failed_start(result, run, runner, sleep, trust_workspace):
    """A receipt in state `failed`: recover a workspace-trust block when allowed, else
    raise with Orca's own reason."""
    blocked = str(result.get("lastError") or "") + str(result.get("failedStage") or "")
    shown_fail = ""
    if TRUST_BLOCK not in blocked:
        try:
            info = _orca(["orchestration", "worker-show", "--dispatch",
                          result["dispatchId"], "--json"], runner)
            shown_fail = str((info.get("dispatch") or {}).get("lastFailure") or "")
        except DelegationError:
            shown_fail = ""
    if TRUST_BLOCK in blocked + shown_fail:
        if not trust_workspace:
            raise DelegationError(
                f"dispatch {result['dispatchId']}: the agent stopped at Claude Code's "
                "workspace-trust dialog in its new worktree. For a repository you own, "
                "rerun with --trust-workspace (it answers the dialog in the agent's own "
                "terminal and retries the task there), or confirm the dialog in that "
                "terminal yourself.")
        return _recover_trust(result, run, runner, sleep)
    raise DelegationError(f"dispatch {result['dispatchId']} failed at "
                          f"{result.get('failedStage')}: {result.get('lastError')}")


# -- the live state of a delegation -------------------------------------------------------

def dispatch_info(dispatch, runner=None):
    """Orca's view of one dispatch: found, stage, activity, outcome, liveness, workspace.
    A dispatch Orca does not know is `found: False`; Orca itself unreachable raises
    OrcaUnavailable (that is not evidence about the agent)."""
    try:
        shown = _orca(["orchestration", "worker-show", "--dispatch", dispatch, "--json"], runner)
    except OrcaUnavailable:
        raise
    except DelegationError as exc:
        return {"found": False, "error": str(exc)}
    projection = shown.get("projection") or shown
    worker = shown.get("worker") or {}
    record_ = shown.get("dispatch") or {}
    return {"found": True,
            "stage": worker.get("stage") or record_.get("stage"),
            "activity": (projection.get("stage") or {}).get("activity"),
            "outcome": projection.get("outcome") or record_.get("outcome"),
            "liveness": (projection.get("liveness") or {}).get("verdict"),
            "dispatch_state": record_.get("state") or record_.get("status"),
            "workspace": _path_of((projection.get("workspace") or {}).get("id"))}


def derive_state(info, previous=None):
    """(state, reason) from Orca's view of a dispatch. Only an Orca outcome settles a
    delegation: `succeeded` is AGENT_COMPLETED - commits in the worktree are not."""
    if not info.get("found"):
        return AGENT_ORPHANED, f"Orca knows no such dispatch ({info.get('error')})"
    outcome = str(info.get("outcome") or "").lower()
    if outcome == "succeeded":
        return AGENT_COMPLETED, "Orca outcome succeeded"
    if outcome == "failed":
        return AGENT_FAILED, "Orca outcome failed"
    if outcome in _CANCELLED or str(info.get("dispatch_state") or "").lower() in _CANCELLED:
        return AGENT_CANCELLED, f"dispatch {outcome or info.get('dispatch_state')}"
    liveness = info.get("liveness")
    if liveness == "live":
        if info.get("activity") == "working" or str(info.get("stage") or "") \
                not in _UNSTARTED_STAGES:
            return AGENT_WORKING, f"dispatch live (stage {info.get('stage')})"
        keep = previous if previous in (AGENT_SPAWNED, AGENT_STARTED) else AGENT_SPAWNED
        return keep, "dispatch live; no turn observed yet"
    if not liveness:
        return AGENT_UNVERIFIED, "Orca reported no liveness verdict for the dispatch"
    return AGENT_ORPHANED, (f"dispatch {liveness}, no completion evidence "
                            f"(outcome {outcome or 'none'})")


def git_evidence(path, base, git=None):
    """What the worktree holds: readable, commits beyond `base` (SHAs), uncommitted changes.
    An unreadable worktree is `readable: False` with git's reason - never empty."""
    git = git or _git
    if not path:
        return {"readable": False, "reason": "no worktree recorded"}
    code, out = git(path, "status", "--porcelain")
    if code != 0:
        return {"readable": False, "reason": out or f"git status exited {code}"}
    dirty = bool(out.strip())
    code, log = git(path, "log", "--format=%H", f"{base}..HEAD")
    if code != 0:
        return {"readable": False, "reason": log or f"git log exited {code}"}
    return {"readable": True, "commits": log.split(), "dirty": dirty}


def status(ident, runner=None, ledger=None, git=None):
    """The live state of one delegation (by task id or dispatch id), from Orca's worker-show
    and the worktree's git; a changed state or evidence is appended to the ledger. Returns
    {task_id, dispatch, previous, state, reason, orca, git, recorded}."""
    orca_executable()
    found = _find(ident, ledger)
    task_id, dispatch = found["task_id"], found.get("dispatch")
    report = {"task_id": task_id, "dispatch": dispatch, "previous": found.get("state"),
              "worktree": found.get("worktree"), "recorded": False}
    if not dispatch:
        report.update(state=found.get("state"), reason="no dispatch was ever started",
                      orca=None, git=None)
        return report
    info = dispatch_info(dispatch, runner)
    state, reason = derive_state(info, found.get("state"))
    if (state in (AGENT_WORKING, AGENT_SPAWNED, AGENT_STARTED) and info.get("workspace")
            and found.get("worktree")
            and _norm(info["workspace"]) != _norm(found["worktree"])):
        state, reason = AGENT_UNVERIFIED, (f"dispatch runs in {info['workspace']!r}, not in "
                                           f"its worktree {found['worktree']!r}")
    evidence = git_evidence(found.get("worktree"), found.get("base") or "main", git)
    report.update(state=state, reason=reason, orca=info, git=evidence)
    commits = evidence.get("commits") if evidence.get("readable") else None
    dirty = evidence.get("dirty") if evidence.get("readable") else None
    changed = (state != found.get("state")
               or (commits is not None and commits != found.get("commits"))
               or (dirty is not None and dirty != found.get("dirty")))
    if changed:
        record(task_id, state, ledger, dispatch=dispatch, reason=reason, commits=commits,
               dirty=dirty, git_unreadable=None if evidence.get("readable")
               else evidence.get("reason"),
               orca={k: info.get(k) for k in ("stage", "activity", "outcome", "liveness")})
        report["recorded"] = True
    return report


def adopt(dispatch, task_id, title, name=None, base="main", runner=None, ledger=None,
          role=None, git=None):
    """Record a dispatch that already runs in its own Orca-created worktree (a delegation
    whose spawn ended AGENT_UNVERIFIED, or one started by hand with `worker-start --worktree
    new-top-level`), then its current state. Refuses a dispatch whose terminal sits in a main
    checkout or in no git worktree. A WSL worktree path is read through the host's
    translation."""
    git = git or _git
    shown = _orca(["orchestration", "worker-show", "--dispatch", dispatch, "--json"], runner)
    projection = shown.get("projection") or shown
    workspace = (projection.get("workspace") or {}).get("id") or ""
    path = _path_of(workspace)
    if not path:
        raise DelegationError(f"dispatch {dispatch}: no workspace")
    previous = delegations(read_ledger(ledger)).get(task_id)
    if previous and previous.get("state") in OCCUPIED and previous.get("dispatch") != dispatch:
        raise DelegationError(f"task {task_id} is already delegated to dispatch "
                              f"{previous.get('dispatch')} ({previous.get('state')})")
    code, top = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    code2, own = git(path, "rev-parse", "--path-format=absolute", "--git-dir")
    if code or code2:
        raise DelegationError(f"dispatch {dispatch} runs in {path!r}, not a git worktree "
                              f"readable from this host ({host_kind()}): {top if code else own}")
    if _norm(top) == _norm(own):
        raise DelegationError(f"dispatch {dispatch} runs in a main checkout ({path!r}), "
                              "not in a worktree of its own")
    _, branch = git(path, "rev-parse", "--abbrev-ref", "HEAD")
    repo = top.replace("\\", "/").rstrip("/").rsplit("/", 1)[0]
    record(task_id, AGENT_SPAWNED, ledger, title=title, role=role,
           name=name or path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1], repo=repo,
           base=base, branch=branch, dispatch=dispatch, task=projection.get("taskId"),
           run=projection.get("runId"), worktree_id=workspace, worktree=path,
           agent=(projection.get("provider") or {}).get("id"), adopted=True)
    status(task_id, runner, ledger, git)
    return _find(task_id, ledger)


# -- audit --------------------------------------------------------------------------------

def worktrees(repo):
    """`git worktree list --porcelain` of `repo` as dicts: path, head, branch (or None)."""
    code, out = _git(repo, "worktree", "list", "--porcelain")
    if code != 0:
        raise DelegationError(f"git worktree list failed in {repo}: {out}")
    found, current = [], {}
    for line in out.splitlines() + [""]:
        if not line.strip():
            if current:
                found.append(current)
            current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current = {"path": value, "head": None, "branch": None, "detached": False}
        elif key == "HEAD":
            current["head"] = value
        elif key == "branch":
            current["branch"] = value.replace("refs/heads/", "", 1)
        elif key == "detached":
            current["detached"] = True
    return found


def _fleet(run, runner=None):
    """dispatch id -> {liveness, outcome, workspace path} for a run (or every recorded run);
    None when Orca cannot be asked."""
    args = ["orchestration", "worker-list", "--json"] + (["--run", run] if run else [])
    try:
        result = _orca(args, runner)
    except DelegationError:
        return None
    rows = result.get("workers") or result.get("rows") or []
    fleet = {}
    for row in rows:
        projection = row.get("projection") or row
        dispatch = projection.get("dispatchId")
        if not dispatch:
            continue
        fleet[dispatch] = {"found": True,
                           "liveness": (projection.get("liveness") or {}).get("verdict"),
                           "outcome": projection.get("outcome"),
                           "workspace": _path_of((projection.get("workspace") or {}).get("id"))}
    return fleet


def _owner(path, folded):
    owners = [d for d in folded.values() if d.get("worktree") and _norm(d["worktree"]) == path]
    return owners[-1] if owners else None


def classify(tree, folded, fleet, base_ref, git=None, runner=None):
    """The class of one worktree, and why. `folded` is `delegations(...)`; `fleet` is
    `_fleet(...)` (None: Orca unreachable). `git(path, *args)` is injectable for tests."""
    git = git or _git
    path = _norm(tree["path"])
    if tree.get("main"):
        return MAIN, "the repository's own working tree"
    owner = _owner(path, folded)
    live = [d for d, f in (fleet or {}).items()
            if _norm(f.get("workspace")) == path and f.get("liveness") == "live"
            and f.get("outcome") in (None, "in_progress", "ready")]
    if live:
        return ACTIVE, f"dispatch {', '.join(live)} is live in it"
    code, dirty = git(tree["path"], "status", "--porcelain")
    if code != 0:
        return UNKNOWN, f"git state unreadable from this host ({host_kind()}): {dirty[:200]}"
    dirty = bool(dirty.strip())
    ahead = 0
    if base_ref and (tree.get("branch") or tree.get("head")):
        code, out = git(tree["path"], "rev-list", "--count", f"{base_ref}..HEAD")
        if code != 0 or not out.isdigit():
            return UNKNOWN, f"cannot count commits beyond {base_ref}: {out[:200]}"
        ahead = int(out)
    held = ", ".join(filter(None, ["uncommitted changes" if dirty else "",
                                   f"{ahead} commit(s) beyond {base_ref}" if ahead else ""]))
    if owner and owner.get("dispatch") and owner.get("state") not in SETTLED:
        info = (fleet or {}).get(owner["dispatch"])
        if info is None:
            if fleet is None:
                return UNKNOWN, (f"delegated ({owner['task_id']}, {owner.get('state')}); Orca "
                                 "unreachable, the agent's state is unknown")
            try:
                info = dispatch_info(owner["dispatch"], runner)
            except OrcaUnavailable as exc:
                return UNKNOWN, f"delegated ({owner['task_id']}); {exc}"
        if str(info.get("outcome") or "").lower() not in ("succeeded", "failed") + _CANCELLED:
            if info.get("found") and not info.get("liveness"):
                return UNKNOWN, (f"delegated ({owner['task_id']}); Orca reports no liveness "
                                 f"for {owner['dispatch']}")
            return AGENT_ORPHANED_WORKTREE, (
                f"delegated ({owner['task_id']}) to {owner['dispatch']}, which is "
                f"{info.get('liveness') or 'gone'} with no completion evidence"
                + (f"; holds {held}" if held else "; nothing beyond the base"))
    if dirty:
        return UNFINISHED, "uncommitted changes and no live agent"
    if ahead == 0:
        if owner:
            return STALE, f"delegated ({owner.get('task_id')}); nothing beyond {base_ref}"
        return ORPHANED, f"no delegation recorded and nothing beyond {base_ref}"
    pushed = False
    if tree.get("branch"):
        code, out = git(tree["path"], "branch", "-r", "--contains", "HEAD")
        pushed = code == 0 and bool(out.strip())
    if pushed:
        who = f"delegation {owner.get('task_id')}" if owner else "no recorded delegation"
        return COMPLETED, f"{ahead} commit(s) beyond {base_ref}, pushed ({who})"
    if owner and owner.get("state") in SETTLED:
        return UNFINISHED, f"{ahead} commit(s) beyond {base_ref} not pushed; agent settled"
    return UNFINISHED, f"{ahead} commit(s) beyond {base_ref} exist only here"


def audit(repo, run=None, base_ref="origin/main", runner=None, ledger=None, git=None):
    """Every worktree of `repo` with its class: rows of path, branch, head, class, reason,
    task, dispatch and the delegation's latest lifecycle state (from the ledger)."""
    folded = delegations(read_ledger(ledger))
    fleet = _fleet(run, runner)
    # A repository with no remote (a game the Factory's init created locally) has no
    # origin/main: compare against its local branch instead.
    code, _ = (git or _git)(repo, "rev-parse", "--verify", "--quiet", base_ref)
    if code != 0 and base_ref.startswith("origin/"):
        base_ref = base_ref.split("/", 1)[1]
    rows = []
    for index, tree in enumerate(worktrees(repo)):
        tree = dict(tree, main=(index == 0))
        kind, reason = classify(tree, folded, fleet, base_ref, git, runner)
        owner = _owner(_norm(tree["path"]), folded) or {}
        rows.append({"path": tree["path"], "branch": tree.get("branch") or "(detached)",
                     "head": (tree.get("head") or "")[:7], "class": kind, "reason": reason,
                     "task": owner.get("task_id"), "dispatch": owner.get("dispatch"),
                     "state": owner.get("state")})
    return rows
