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

from wgf_develop.repository import GitError, GitRepo
from wgf_verification.lineage import (CODE, SDK_KEY_TRAILER, is_placeholder, same_commit,
                                      sdk_commits_between)

from . import integrate

__all__ = ["SdkGit", "CommitRefused", "INTEGRATION_PATHS", "SDK_KEY_TRAILER"]

# Every path the integration phase may write (integrate.py). A dirty path outside these was
# not made by this step, and is not committed by it.
INTEGRATION_PATHS = frozenset(integrate.OWNED_FILES + integrate.SEAM_FILES
                              + (integrate.PLAN_FILE, integrate.MAIN_FILE))

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

    def _run_keys(self, body, run_id):
        prefix = f"{self.trailer}:"
        keys = [line.split(":", 1)[1].strip() for line in body.splitlines()
                if line.strip().startswith(prefix)]
        return [k for k in keys if not run_id or k.startswith(f"{run_id}:")]

    def base_of(self, head, run_id, depth=50):
        """HEAD with this run's sdk commits peeled off: where a standalone sdk run began."""
        ok, out = self.call("log", f"-n{depth}", "--format=%H%x00%B%x1e", head)
        if not ok:
            raise CommitRefused(f"cannot read the history of {head[:12]}")
        for record in out.split("\x1e"):
            sha, _, body = record.strip().partition("\x00")
            if sha and not self._run_keys(body, run_id):
                return sha.strip()
        raise CommitRefused(f"no commit below {head[:12]} that this run's sdk step did not make")

    def own_commits(self, base, head, run_id):
        """This run's sdk commits in base..head, oldest first; refuses anything else there."""
        if same_commit(base, head):
            return []
        commits, problem = sdk_commits_between(self.call, base, head)
        if problem:
            raise CommitRefused(f"{CODE}: {problem}")
        foreign = [sha for sha, keys in commits
                   if not [k for k in keys if not run_id or k.startswith(f"{run_id}:")]]
        if foreign:
            raise CommitRefused(
                f"{CODE}: the checkout's HEAD {head[:12]} is not the prototype-report's commit "
                f"{base[:12]}: {len(foreign)} commit(s) between them were not made by this "
                f"run's sdk step ({', '.join(s[:12] for s in foreign)}). Integrating on top "
                "of them would ship code nobody reviewed; check out the prototype commit, or "
                "re-run develop and review, then resume.")
        return [sha for sha, _ in commits]

    def foreign_changes(self):
        """Uncommitted paths the integration does not own."""
        return sorted(p for p in self.dirty_paths() if p.strip('"') not in INTEGRATION_PATHS)


def prepare(git, prototype_commit, has_prototype, run_id):
    """(head, base, [own commits]) before anything is written, or raise CommitRefused."""
    if not git.is_repository():
        raise CommitRefused(f"{git.root} is not a readable git repository: the commit the "
                            "SDK evidence is about cannot be established")
    head = git.head()
    if is_placeholder(head):
        raise CommitRefused(f"{git.root} has no commit (HEAD unreadable): the commit the SDK "
                            "evidence is about cannot be established")
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
        base = git.base_of(head, run_id)
    own = git.own_commits(base, head, run_id)
    foreign = git.foreign_changes()
    if foreign:
        raise CommitRefused(
            f"the checkout has {len(foreign)} uncommitted change(s) the sdk integration did "
            f"not make ({'; '.join(foreign[:5])}): they would be verified as if committed, "
            "or committed as if integrated. Commit them through develop (and review), or "
            "discard them, then resume.")
    return head, base, own


def commit(git, key, title_id, files, tests):
    """Commit the integration once, keyed; (sha, created). No change: (HEAD, False)."""
    foreign = git.foreign_changes()
    if foreign:
        raise CommitRefused(
            f"the integration run left {len(foreign)} change(s) outside the files it owns "
            f"({'; '.join(foreign[:5])}); nothing was committed. A test or typecheck that "
            "writes into the tree must write only ignored paths.")
    if not git.dirty_paths():
        existing = git.keyed_commit(key)
        return (existing if existing and same_commit(existing, git.head()) else git.head(),
                False)
    written = [f"{f['path']} ({f['action']})" for f in files
               if f.get("action") not in ("unchanged", "skipped")]
    body = (f"Integrates the platform SDK into {title_id}: "
            + (", ".join(written) if written else "integration files") + ".\n"
            f"Integration suite: {tests.get('status')}; typecheck: {tests.get('typecheck')}.")
    try:
        sha, created = git.commit_all("feat(platform): integrate the platform SDK", body, key)
    except GitError as exc:
        raise CommitRefused(f"could not commit the integration: {exc}")
    if git.dirty_paths():
        raise CommitRefused(f"the tree is still dirty after the integration commit "
                            f"{(sha or '')[:12]}: {'; '.join(git.dirty_paths()[:5])}")
    return sha, created
