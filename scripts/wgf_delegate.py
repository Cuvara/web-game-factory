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
worktree. Each delegation is recorded in a ledger (task, worktree, branch, dispatch,
terminal), so `audit` can say of every worktree on disk whether an agent is working in it,
finished in it, or never did.

Standard library only. The orca executable is `WGF_ORCA` or `orca` on PATH; the ledger is
`WGF_DELEGATION_LEDGER` or `~/.cache/wgf/delegations.jsonl`. See docs/orca-delegation.md.
"""

import datetime as _dt
import json
import os
import pathlib
import re
import shutil

from wgflib import procs

__all__ = ["DelegationError", "Delegation", "spawn", "adopt", "audit", "worktrees", "ledger_path",
           "read_ledger", "parse_receipt", "preamble", "CLASSES"]

# The states a worktree can be in, from the coordinator's point of view.
ACTIVE = "ACTIVE AGENT"            # an agent is working in it now
COMPLETED = "COMPLETED WORK"       # an agent finished in it; its commits are pushed or merged
UNFINISHED = "UNFINISHED WORK"     # uncommitted changes, or commits nowhere else, no live agent
ORPHANED = "ORPHANED WORKTREE"     # no agent ever worked in it, nothing in it worth keeping
STALE = "STALE WORKTREE"           # its branch is already merged into the base
MAIN = "MAIN CHECKOUT"             # the repository's own working tree
UNKNOWN = "UNKNOWN"
CLASSES = (ACTIVE, COMPLETED, UNFINISHED, ORPHANED, STALE, MAIN, UNKNOWN)

_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}$")


class DelegationError(Exception):
    """A delegation that could not be proven to have an agent working in its worktree."""


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(path):
    """A path as a comparable string: forward slashes, no trailing slash, case-folded on
    Windows (Orca reports `C:/...`, git `C:/...` or `c:/...`)."""
    text = str(path or "").replace("\\", "/").rstrip("/")
    return text.lower() if os.name == "nt" else text


def orca_executable():
    exe = os.environ.get("WGF_ORCA") or shutil.which("orca")
    if not exe:
        raise DelegationError("orca is not on PATH (set WGF_ORCA)")
    return exe


def _orca(args, runner=None):
    """Run orca with `args`, return its parsed JSON envelope. `runner` replaces wgflib.procs
    in tests: runner(argv) -> (returncode, stdout)."""
    argv = [orca_executable()] + list(args)
    if runner is None:
        proc = procs.run(argv, timeout=600, heartbeat_seconds=0)
        code, out = proc.returncode, proc.stdout
    else:
        code, out = runner(argv)
    try:
        envelope = json.loads(out)
    except (TypeError, ValueError):
        raise DelegationError(f"orca {args[0]} {args[1] if len(args) > 1 else ''}: "
                              f"not JSON (exit {code}): {str(out)[:300]}")
    if code != 0 or not envelope.get("ok", False):
        error = envelope.get("error") or {}
        raise DelegationError(f"orca {' '.join(args[:2])} failed (exit {code}): "
                              f"{error.get('message') or str(out)[:300]}")
    return envelope.get("result") or {}


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
    """One ledger entry: what was delegated, where, and to which dispatch."""


def parse_receipt(result):
    """From a `worker-start --worktree new-top-level` receipt, the created worktree, the agent
    terminal and the dispatch - or DelegationError naming what the receipt does not prove."""
    effects = result.get("effects") or []
    worktree = next((e for e in effects if e.get("kind") == "worktree"), None)
    terminal = next((e for e in effects
                     if e.get("kind") == "terminal" and e.get("role", "agent") == "agent"), None)
    accepted = next((e for e in effects if e.get("kind") == "dispatch_input"), None)
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
                   f"`orca orchestration worker-show --dispatch {result['dispatchId']}`)"
                   if result.get("dispatchId") else "")
        raise DelegationError("worker-start did not prove an agent working in a new worktree: "
                              + "; ".join(problems) + started)
    worktree_id = worktree.get("id") or ""
    path = worktree_id.split("::", 1)[1] if "::" in worktree_id else worktree_id
    return {"dispatch": result["dispatchId"], "task": result.get("taskId"),
            "run": result.get("runId"), "worktree_id": worktree_id, "worktree": path,
            "terminal": terminal.get("id"), "agent": launch.get("agent")}


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
    down = "[B"
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


def _git(path, *args):
    proc = procs.run(["git", "-C", str(path)] + list(args), timeout=120, heartbeat_seconds=0)
    return proc.returncode, (proc.stdout or "").strip()


def ensure_repo(repo, runner=None):
    """Register `repo` with Orca if it is not yet (a game repository created locally by the
    Factory's init is not): `worker-start --repo path:` needs a registered repository."""
    try:
        _orca(["repo", "show", "--repo", f"path:{repo}", "--json"], runner)
        return False
    except DelegationError:
        _orca(["repo", "add", "--path", str(repo), "--json"], runner)
        return True


def _start(args, runner):
    """worker-start, returning its result even when Orca reports the attempt failed (the
    receipt still names the dispatch, task, worktree and terminal it created)."""
    argv = [orca_executable()] + list(args)
    if runner is None:
        proc = procs.run(argv, timeout=600, heartbeat_seconds=0)
        code, out = proc.returncode, proc.stdout
    else:
        code, out = runner(argv)
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
    worktree = next((e for e in result.get("effects") or [] if e.get("kind") == "worktree"),
                    {}).get("id")
    terminal = next((e for e in result.get("effects") or []
                     if e.get("kind") == "terminal"), {}).get("id")
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
    if not any(e.get("kind") == "terminal" for e in retry.get("effects") or []):
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
        if stage not in ("", "turn_start_unobserved", "input_accepted") or activity == "working":
            return
        sleep(poll_s)
        waited += poll_s
    raise DelegationError(
        f"dispatch {dispatch}: the task was typed into the agent's terminal but the agent never "
        f"started a turn in {wait_s} s (the prompt is likely empty). Stop it with "
        f"`orca orchestration worker-stop --dispatch {dispatch}` and spawn again.")


def spawn(task_id, title, spec, name, repo, base="main", agent="claude", run=None,
          model=None, runner=None, ledger=None, verify_git=True, trust_workspace=False,
          sleep=None):
    """Delegate one task: Orca creates the worktree, starts the agent in it and gives it the
    task. Returns the ledger entry, or raises DelegationError without recording anything
    when the receipt does not prove the agent is working in its new worktree."""
    if not _NAME.match(name or ""):
        raise DelegationError(f"worktree name {name!r}: lowercase letters, digits and '-', "
                              "2-49 characters")
    if not str(spec or "").strip():
        raise DelegationError("a delegation needs a concrete task: the spec is empty")
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
    result = _start(args, runner)
    if result.get("state") == "failed":
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
            result = _recover_trust(result, run, runner, sleep)
        else:
            raise DelegationError(f"dispatch {result['dispatchId']} failed at "
                                  f"{result.get('failedStage')}: {result.get('lastError')}")
    placed = parse_receipt(result)
    _confirm_turn(result, placed["dispatch"], runner, sleep)
    shown = _orca(["orchestration", "worker-show", "--dispatch", placed["dispatch"], "--json"],
                  runner)
    workspace = ((shown.get("projection") or shown).get("workspace") or {}).get("id") or ""
    if _norm(workspace.split("::", 1)[-1]) != _norm(placed["worktree"]):
        raise DelegationError(f"dispatch {placed['dispatch']} runs in {workspace!r}, not in its "
                              f"worktree {placed['worktree']!r}")
    branch = None
    if verify_git:
        code, out = _git(placed["worktree"], "rev-parse", "--abbrev-ref", "HEAD")
        if code != 0:
            raise DelegationError(f"{placed['worktree']} is not a git worktree: {out}")
        branch = out
    entry = Delegation(task_id=task_id, title=title, name=name, repo=repo, base=base,
                       branch=branch, created_at=_now(), **placed)
    _append_ledger(dict(entry), ledger)
    return entry


def adopt(dispatch, task_id, title, name=None, base="main", runner=None, ledger=None):
    """Record a dispatch that already runs in its own Orca-created worktree (a delegation
    whose receipt this module failed to read, or one started by hand with
    `worker-start --worktree new-top-level`). Refuses a dispatch whose terminal sits in a
    main checkout or in no git worktree."""
    shown = _orca(["orchestration", "worker-show", "--dispatch", dispatch, "--json"], runner)
    projection = shown.get("projection") or shown
    workspace = (projection.get("workspace") or {}).get("id") or ""
    path = workspace.split("::", 1)[-1]
    if not path:
        raise DelegationError(f"dispatch {dispatch}: no workspace")
    code, top = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    code2, own = _git(path, "rev-parse", "--path-format=absolute", "--git-dir")
    if code or code2:
        raise DelegationError(f"dispatch {dispatch} runs in {path!r}, not a git worktree")
    if _norm(top) == _norm(own):
        raise DelegationError(f"dispatch {dispatch} runs in a main checkout ({path!r}), "
                              "not in a worktree of its own")
    _, branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    _, repo = _git(path, "rev-parse", "--show-toplevel")
    entry = Delegation(task_id=task_id, title=title, name=name or pathlib.Path(path).name,
                       repo=str(pathlib.Path(top).parent), base=base, branch=branch,
                       created_at=_now(), dispatch=dispatch, task=projection.get("taskId"),
                       run=projection.get("runId"), worktree_id=workspace, worktree=path,
                       terminal=None, agent=(projection.get("provider") or {}).get("id"),
                       adopted=True)
    _append_ledger(dict(entry), ledger)
    return entry


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
    """dispatch id -> {liveness, outcome, workspace path} for a run (or every recorded run)."""
    args = ["orchestration", "worker-list", "--json"] + (["--run", run] if run else [])
    try:
        result = _orca(args, runner)
    except DelegationError:
        return {}
    rows = result.get("workers") or result.get("rows") or []
    fleet = {}
    for row in rows:
        projection = row.get("projection") or row
        dispatch = projection.get("dispatchId")
        if not dispatch:
            continue
        workspace = ((projection.get("workspace") or {}).get("id") or "").split("::", 1)[-1]
        fleet[dispatch] = {"liveness": (projection.get("liveness") or {}).get("verdict"),
                           "outcome": projection.get("outcome"), "workspace": workspace}
    return fleet


def classify(tree, ledger_entries, fleet, base_ref, git=None):
    """The class of one worktree, and why. `git(path, *args)` is injectable for tests."""
    git = git or _git
    path = _norm(tree["path"])
    if tree.get("main"):
        return MAIN, "the repository's own working tree"
    owners = [e for e in ledger_entries if _norm(e.get("worktree")) == path]
    live = [d for d, f in fleet.items()
            if _norm(f.get("workspace")) == path and f.get("liveness") == "live"
            and f.get("outcome") in (None, "in_progress", "ready")]
    _, dirty = git(tree["path"], "status", "--porcelain")
    dirty = bool(dirty.strip())
    if live:
        return ACTIVE, f"dispatch {', '.join(live)} is live in it"
    branch = tree.get("branch")
    ahead = 0
    if branch and base_ref:
        code, out = git(tree["path"], "rev-list", "--count", f"{base_ref}..HEAD")
        ahead = int(out) if code == 0 and out.isdigit() else 0
    elif tree.get("head") and base_ref:
        code, out = git(tree["path"], "rev-list", "--count", f"{base_ref}..HEAD")
        ahead = int(out) if code == 0 and out.isdigit() else 0
    if dirty:
        return UNFINISHED, "uncommitted changes and no live agent"
    if ahead == 0:
        if owners:
            return STALE, f"delegated ({owners[-1].get('task_id')}); nothing beyond {base_ref}"
        return ORPHANED, f"no delegation recorded and nothing beyond {base_ref}"
    pushed = False
    if branch:
        code, out = git(tree["path"], "branch", "-r", "--contains", "HEAD")
        pushed = code == 0 and bool(out.strip())
    settled = [e for e in owners if fleet.get(e.get("dispatch"), {}).get("outcome")
               in ("succeeded", "failed")]
    if pushed:
        who = f"delegation {owners[-1].get('task_id')}" if owners else "no recorded delegation"
        return COMPLETED, f"{ahead} commit(s) beyond {base_ref}, pushed ({who})"
    if settled:
        return UNFINISHED, f"{ahead} commit(s) beyond {base_ref} not pushed; agent settled"
    return UNFINISHED, f"{ahead} commit(s) beyond {base_ref} exist only here"


def audit(repo, run=None, base_ref="origin/main", runner=None, ledger=None, git=None):
    """Every worktree of `repo` with its class: rows of path, branch, head, class, reason,
    task (from the ledger) and dispatch."""
    entries = read_ledger(ledger)
    fleet = _fleet(run, runner)
    # A repository with no remote (a game the Factory's init created locally) has no
    # origin/main: compare against its local branch instead.
    code, _ = (git or _git)(repo, "rev-parse", "--verify", "--quiet", base_ref)
    if code != 0 and base_ref.startswith("origin/"):
        base_ref = base_ref.split("/", 1)[1]
    rows = []
    trees = worktrees(repo)
    for index, tree in enumerate(trees):
        tree = dict(tree, main=(index == 0))
        kind, reason = classify(tree, entries, fleet, base_ref, git)
        owner = next((e for e in reversed(entries)
                      if _norm(e.get("worktree")) == _norm(tree["path"])), {})
        rows.append({"path": tree["path"], "branch": tree.get("branch") or "(detached)",
                     "head": (tree.get("head") or "")[:7], "class": kind, "reason": reason,
                     "task": owner.get("task_id"), "dispatch": owner.get("dispatch")})
    return rows
