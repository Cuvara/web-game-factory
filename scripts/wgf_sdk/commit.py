"""The sdk step's one side effect on history: a keyed commit of its integration.

    before    HEAD is the prototype-report's commit, or a descendant made only by this
              run's sdk commits (a retry or a resume); the tree holds no change the
              integration does not own
    after     the integration's files, and only those, committed once, keyed by the
              idempotency key in a `Wgf-Sdk-Key` trailer; re-executing the same visit
              finds its commit instead of making another; no change, no commit
    never     push, fetch, amend, reset or touch a remote

Git runs through the step's integration runner (runner.CommandRunner: `run(argv, cwd,
timeout) -> CommandResult | None`), adapted to wgf_develop.repository.GitRepo, whose keyed
commit mechanism this reuses with the sdk's trailer. What may sit between develop's commit
and sdk's is decided by wgf_verification/lineage.py - the rule verify and release apply.
"""

import json
import os

from wgf_develop.repository import GitError, GitRepo
from wgf_verification.lineage import (CODE, SDK_KEY_TRAILER, is_placeholder, same_commit,
                                      sdk_commits_between)

from . import integrate

__all__ = ["SdkGit", "Ledger", "CommitRefused", "INTEGRATION_PATHS", "SDK_KEY_TRAILER",
           "prepare", "commit"]

# Every path the integration phase may write (integrate.py). A dirty path outside these was
# not made by this step, and is not committed by it.
INTEGRATION_PATHS = frozenset(integrate.OWNED_FILES + integrate.SEAM_FILES
                              + (integrate.PLAN_FILE, integrate.WIRING_FILE))

_TAIL = 800


class CommitRefused(Exception):
    """The checkout is not in a state this step may build on or commit. BLOCKED."""


class _Result:
    """A CommandResult as wgf_develop.repository.GitRepo reads one."""

    def __init__(self, result):
        self.returncode = None if result is None else result.returncode
        self.output = "" if result is None else (result.stdout or "")
        self.error = "" if result is None else (result.stderr or "")

    @property
    def ok(self):
        return self.returncode == 0

    def tail(self, limit=_TAIL):
        text = self.output + self.error
        return (text or ("git is not installed" if self.returncode is None else ""))[-limit:]


class _Adapter:
    def __init__(self, runner):
        self._runner = runner

    def run(self, argv, cwd, timeout=None, **_):
        return _Result(self._runner.run(list(argv), cwd, timeout or 120))


class SdkGit(GitRepo):
    def __init__(self, root, runner, author=None):
        super().__init__(root, _Adapter(runner), author=author, trailer=SDK_KEY_TRAILER)

    def call(self, *args):
        """(ok, stdout): the shape wgf_verification.lineage reads git through."""
        result = self._git(*args, check=False)
        return result.ok, result.output

    def base_of(self, head, trusted, depth=50):
        """HEAD with the ledger's sdk commits peeled off: where a standalone sdk run began."""
        ok, out = self.call("log", f"-n{depth}", "--format=%H", head)
        if not ok:
            raise CommitRefused(f"cannot read the history of {head[:12]}")
        for sha in out.split():
            if sha not in trusted:
                return sha
        raise CommitRefused(f"no commit below {head[:12]} that this run's sdk step did not make")

    def own_commits(self, base, head, trusted):
        """The sdk step's commits in base..head, oldest first; refuses anything else there.

        A commit is the sdk step's only when the ledger in the run directory records its
        sha - never because of its trailer: the key is derived from the run id, which every
        developer command is given, so a trailer can be forged by anyone who can commit."""
        if same_commit(base, head):
            return []
        commits, problem = sdk_commits_between(self.call, base, head)
        if problem:
            raise CommitRefused(f"{CODE}: {problem}")
        foreign = [sha for sha, keys in commits if sha not in trusted or not keys]
        if foreign:
            raise CommitRefused(
                f"{CODE}: the checkout's HEAD {head[:12]} is not the prototype-report's commit "
                f"{base[:12]}: {len(foreign)} commit(s) between them were not made by this "
                f"run's sdk step ({', '.join(s[:12] for s in foreign)}) - whatever their "
                "trailers say. Integrating on top of them would ship code nobody reviewed; "
                "check out the prototype commit, or re-run develop and review, then resume.")
        return [sha for sha, _ in commits]

    def status(self):
        """[(xy, path)] from `git status --porcelain`, untracked files included."""
        out = self._git("status", "--porcelain", "--untracked-files=all").output
        return [(line[:2], line[3:].strip('"')) for line in out.splitlines() if line.strip()]

    def foreign_changes(self):
        """Uncommitted paths the integration does not own."""
        return sorted(p for p in self.dirty_paths() if p.strip('"') not in INTEGRATION_PATHS)

    def restore(self, changes):
        """Put integration paths back to HEAD: tracked ones checked out, untracked removed."""
        tracked = [path for xy, path in changes if xy != "??"]
        if tracked:
            self._git("checkout", "HEAD", "--", *tracked)
        for xy, path in changes:
            if xy == "??":
                full = os.path.join(self.root, *path.split("/"))
                if os.path.isfile(full):
                    os.remove(full)


class Ledger:
    """What this sdk step did in this run, kept in the run directory - outside the checkout,
    so nothing that can write to the game repository can write it.

        {"<idempotency key>": {"started": true, "commits": ["<sha>", ...]}}

    `started` is written before the integration touches the checkout, a commit's sha right
    after it is made. A crash between the commit and its entry leaves a commit the ledger
    does not know: the next attempt refuses it (fail closed) rather than trust a trailer.
    """

    def __init__(self, path):
        self.path = path

    def _read(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        os.replace(temporary, self.path)

    def trusted(self):
        return {sha for entry in self._read().values() if isinstance(entry, dict)
                for sha in entry.get("commits") or []}

    def started(self, key):
        return bool((self._read().get(key) or {}).get("started"))

    def start(self, key):
        data = self._read()
        data.setdefault(key, {"started": True, "commits": []})["started"] = True
        self._write(data)

    def add(self, key, sha):
        data = self._read()
        entry = data.setdefault(key, {"started": True, "commits": []})
        if sha not in entry["commits"]:
            entry["commits"].append(sha)
        self._write(data)


def prepare(git, prototype_commit, has_prototype, run_id, ledger=None, key=None):
    """(head, base, [own commits]) before anything is written, or raise CommitRefused.

    Without a ledger (no run directory) nothing between the prototype commit and HEAD is
    trusted, and no uncommitted change is: every such commit or change is refused."""
    if not git.is_repository():
        raise CommitRefused(f"{git.root} is not a readable git repository: the commit the "
                            "SDK evidence is about cannot be established")
    head = git.head()
    if is_placeholder(head):
        raise CommitRefused(f"{git.root} has no commit (HEAD unreadable): the commit the SDK "
                            "evidence is about cannot be established")
    trusted = ledger.trusted() if ledger is not None else set()
    if has_prototype:
        if is_placeholder(prototype_commit):
            raise CommitRefused(f"the prototype-report names no build commit "
                                f"({prototype_commit or 'missing'}); re-run develop so it "
                                "commits its build")
        if not git.has_commit(prototype_commit):
            raise CommitRefused(f"{CODE}: the prototype-report's commit "
                                f"{prototype_commit[:12]} is not in {git.root}")
        base = git.head() if same_commit(prototype_commit, head) else prototype_commit
        if len(base) < 40:
            ok, out = git.call("rev-parse", f"{base}^{{commit}}")
            base = out.strip() if ok and out.strip() else base
    else:
        base = git.base_of(head, trusted)
    own = git.own_commits(base, head, trusted)
    foreign = git.foreign_changes()
    if foreign:
        raise CommitRefused(
            f"the checkout has {len(foreign)} uncommitted change(s) the sdk integration did "
            f"not make ({'; '.join(foreign[:5])}): they would be verified as if committed, "
            "or committed as if integrated. Commit them through develop (and review), or "
            "discard them, then resume.")
    # A dirty file the integration owns is only this visit's own leftover (an attempt that
    # stopped before committing) - and even then it is put back to HEAD and regenerated, so
    # nothing in it survives that the integration did not write. Otherwise it is a hand
    # edit made after review, which the integration would keep and commit as its own.
    owned = [(xy, path) for xy, path in git.status() if path in INTEGRATION_PATHS]
    if owned:
        if ledger is None or not key or not ledger.started(key):
            raise CommitRefused(
                f"the checkout has uncommitted changes to {len(owned)} file(s) the sdk "
                f"integration owns ({'; '.join(p for _, p in owned[:5])}) that no earlier "
                "attempt of this visit made: committing them would pass an unreviewed edit "
                "off as integration. Commit them through develop (and review), or discard "
                "them, then resume.")
        git.restore(owned)
    return head, base, own


def commit(git, key, title_id, files, tests, ledger=None):
    """Commit the integration once, keyed; (sha, created). No change: (HEAD, False).
    The new commit's sha goes into the ledger at once: it is what makes it sdk's."""
    foreign = git.foreign_changes()
    if foreign:
        raise CommitRefused(
            f"the integration run left {len(foreign)} change(s) outside the files it owns "
            f"({'; '.join(foreign[:5])}); nothing was committed. A test or typecheck that "
            "writes into the tree must write only ignored paths.")
    if not git.dirty_paths():
        return git.head(), False
    forged = git.keyed_commit(key)
    if forged and forged not in (ledger.trusted() if ledger is not None else set()):
        raise CommitRefused(
            f"{CODE}: commit {forged[:12]} carries this visit's {SDK_KEY_TRAILER} but the sdk "
            "step did not make it: the trailer is forged. Nothing was committed.")
    written = [f"{f['path']} ({f['action']})" for f in files
               if f.get("action") not in ("unchanged", "skipped")]
    body = (f"Integrates the platform SDK into {title_id}: "
            + (", ".join(written) if written else "integration files") + ".\n"
            f"Integration suite: {tests.get('status')}; typecheck: {tests.get('typecheck')}.")
    try:
        sha, created = git.commit_all("feat(platform): integrate the platform SDK", body, key)
    except GitError as exc:
        raise CommitRefused(f"could not commit the integration: {exc}")
    if created and ledger is not None:
        ledger.add(key, sha)
    if git.dirty_paths():
        raise CommitRefused(f"the tree is still dirty after the integration commit "
                            f"{(sha or '')[:12]}: {'; '.join(git.dirty_paths()[:5])}")
    return sha, created
