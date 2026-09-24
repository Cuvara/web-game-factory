"""Commit lineage: which commits the evidence of one build may name, and how they relate.

The pipeline is develop -> review -> sdk -> verify -> release. develop commits once per
visit; review reads that commit; sdk may commit its integration on top of it; verify and
release must be about exactly the result. The rule (docs/core-contracts.md §5):

    P  = prototype-report.build_ref.commit_sha       what develop built (and review read)
    B  = sdk-report.build_ref.base_commit_sha        what sdk integrated on
    S  = sdk-report.build_ref.commit_sha             what sdk verified: its commit, or B
    V  = the verified commit (verification-report.commit.sha, qa-report.build_ref)
    H  = the checkout's HEAD when verify / release runs

    1. S == V (== H)        the SDK evidence, the verification and the release are one build
    2. P == B               sdk built on the commit develop made, not on something else
    3. B..S is exactly sdk's commits: S descends from B, `git log B..S` is exactly the
       sdk-report's `sdk_commits` (the record, held by the run and pinned by hash), and
       each of them also carries a `Wgf-Sdk-Key: <run_id>:...` trailer. A trailer alone
       proves nothing: the key derives from the run id, which developers are given
    4. no placeholder anywhere: "unknown", 40 zeros or a missing sha is not a commit

An sdk-report without `base_commit_sha` (schema 1.0/1.1, before sdk committed) is read as
B == S: it claims no commits of its own, so rule 2 becomes P == S.

Anything else - a human or agent commit between develop's and sdk's, sdk evidence about
another commit, history that cannot be read - is a `commit-lineage-mismatch`. When git
cannot be read, the rule is not assumed to hold: it is a problem, not a pass.

This module is pure: callers hand it a `git(*args) -> (ok, stdout)` bound to the checkout,
so the verify and release steps apply the same rule through their own process runners.
"""

import re

__all__ = ["SDK_KEY_TRAILER", "PLACEHOLDERS", "is_placeholder", "same_commit",
           "sdk_commits_between", "lineage_problems", "review_problems", "CODE"]

# The trailer an sdk integration commit is keyed by: `Wgf-Sdk-Key: <run>:<step>:<visit>`.
SDK_KEY_TRAILER = "Wgf-Sdk-Key"
CODE = "commit-lineage-mismatch"
PLACEHOLDERS = ("unknown", "0" * 40)
_SHA = re.compile(r"^[0-9a-f]{7,40}$")


def is_placeholder(sha):
    """True for anything that is not the name of a commit: missing, `unknown`, all zeros."""
    return not sha or not isinstance(sha, str) or sha in PLACEHOLDERS \
        or not _SHA.match(sha) or set(sha) == {"0"}


def same_commit(a, b):
    """Two commit names denote the same commit (either may be abbreviated to 7+ chars)."""
    if not a or not b:
        return False
    if min(len(a), len(b)) < 7:
        return a == b
    return a.startswith(b) or b.startswith(a)


def _short(sha):
    return (sha or "none")[:12]


def sdk_commits_between(git, base, tip):
    """([(sha, [sdk keys])], problem or None): the commits in base..tip, oldest first."""
    ancestor_ok, _ = git("merge-base", "--is-ancestor", base, tip)
    if not ancestor_ok:
        return [], (f"the sdk commit {_short(tip)} does not descend from the commit it was "
                    f"built on ({_short(base)}), or git cannot tell")
    ok, out = git("log", "--reverse", "--format=%H%x00%B%x1e", f"{base}..{tip}")
    if not ok:
        return [], (f"cannot read the history {_short(base)}..{_short(tip)}: refusing rather "
                    "than trusting the reports")
    commits = []
    prefix = f"{SDK_KEY_TRAILER}:"
    for record in (out or "").split("\x1e"):
        sha, _, body = record.strip().partition("\x00")
        if not sha:
            continue
        keys = [line.split(":", 1)[1].strip() for line in body.splitlines()
                if line.strip().startswith(prefix)]
        commits.append((sha.strip(), keys))
    return commits, None


def lineage_problems(*, verified, prototype_commit, sdk_report, git, run_id=None,
                     has_prototype=None, history=True):
    """[message, ...] naming every way the build's evidence breaks the lineage rule.

    `verified` is the commit under test (verify: HEAD; release: the verification's commit,
    already checked against HEAD). `prototype_commit` is the prototype-report's, or None when
    the run holds none (`has_prototype` False). `sdk_report` is the sdk-report content or
    None. `git(*args) -> (ok, stdout)` runs git in the checkout, or is None when there is no
    checkout to read - which fails the rule whenever it would need to be read.
    `history=False` checks everything the reports alone can show and leaves rule 3 (the
    commits between B and S) to a later call that has the checkout.
    """
    problems = []
    if has_prototype is None:
        has_prototype = prototype_commit is not None
    if is_placeholder(verified):
        return [f"the verified commit is {verified or 'missing'}, which names no commit"]
    if has_prototype and is_placeholder(prototype_commit):
        problems.append(f"the prototype-report names no build commit "
                        f"({prototype_commit or 'missing'}): develop could not establish one")

    if sdk_report is None:
        if has_prototype and not is_placeholder(prototype_commit) \
                and not same_commit(prototype_commit, verified):
            problems.append(f"the prototype-report describes {_short(prototype_commit)}, "
                            f"not the verified commit {_short(verified)}")
        return problems

    build_ref = sdk_report.get("build_ref") or {}
    sdk_commit = build_ref.get("commit_sha")
    if is_placeholder(sdk_commit):
        problems.append(f"the sdk-report names no commit ({sdk_commit or 'missing'})")
        return problems
    if not same_commit(sdk_commit, verified):
        problems.append(f"the sdk-report describes {_short(sdk_commit)}, not the verified "
                        f"commit {_short(verified)}")
    base = build_ref.get("base_commit_sha")
    legacy = "base_commit_sha" not in build_ref
    if legacy:
        base = sdk_commit  # a report from before sdk committed claims no commits of its own
    elif is_placeholder(base):
        problems.append(f"the sdk-report names no base commit ({base or 'missing'})")
        return problems
    if has_prototype and not is_placeholder(prototype_commit) \
            and not same_commit(prototype_commit, base):
        problems.append(
            f"the sdk integration was built on {_short(base)}, but the prototype-report (the "
            f"commit develop made and review read) is {_short(prototype_commit)}")

    listed = build_ref.get("sdk_commits")
    if same_commit(base, sdk_commit):
        if listed:
            problems.append(f"the sdk-report lists sdk commits {', '.join(map(_short, listed))} "
                            f"but its commit is its base {_short(base)}")
        return problems
    if not history:
        return problems
    if git is None:
        problems.append(f"the commits between {_short(base)} and {_short(sdk_commit)} cannot "
                        "be read (no git access): refusing rather than trusting the reports")
        return problems
    commits, problem = sdk_commits_between(git, base, sdk_commit)
    if problem:
        problems.append(problem)
        return problems
    intruders = []
    for sha, keys in commits:
        ours = [k for k in keys if not run_id or k.startswith(f"{run_id}:")]
        if not ours:
            intruders.append(sha)
    if intruders:
        problems.append(
            f"{len(intruders)} commit(s) between the prototype commit {_short(base)} and the "
            f"sdk commit {_short(sdk_commit)} were not made by this run's sdk step (no "
            f"{SDK_KEY_TRAILER} trailer{f' for run {run_id}' if run_id else ''}): "
            + ", ".join(_short(s) for s in intruders)
            + ". Unreviewed code cannot ride along to a release; re-run develop, review, sdk "
              "and verify from the commit that should ship")
    if not isinstance(listed, list):
        # The report is the record: it is held by the run and pinned by hash downstream,
        # where a trailer in git can be written by anyone who can commit.
        problems.append(f"the sdk-report names no sdk_commits between {_short(base)} and "
                        f"{_short(sdk_commit)}: which commits are the sdk step's cannot be "
                        "told from trailers alone")
    else:
        found = [sha for sha, _ in commits]
        if len(found) != len(listed) or any(not any(same_commit(f, l) for l in listed)
                                            for f in found):
            problems.append(f"the sdk-report lists sdk commits "
                            f"[{', '.join(map(_short, listed))}], git has "
                            f"[{', '.join(map(_short, found))}] between {_short(base)} and "
                            f"{_short(sdk_commit)}")
    return problems


def review_problems(review, prototype_commit, prototype_hash=None):
    """(problems, status): may a build with this review-report be released?

    status is `approved`, `skipped` (no reviewer configured: carried as unreviewed, never
    as approved) or `absent` (no review-report in the run). An approval must be of exactly
    the prototype-report's commit - and, when the review pins a prototype-report, of that
    very report.
    """
    if review is None:
        return [], "absent"
    verdict = review.get("verdict")
    if verdict == "skipped":
        return [], "skipped"
    if verdict != "approve":
        return [f"the newest review-report's verdict is {verdict!r}: the build was not "
                "approved"], "not-approved"
    problems = []
    reviewed = review.get("reviewed_commit")
    if is_placeholder(reviewed) or is_placeholder(prototype_commit) \
            or not same_commit(reviewed, prototype_commit):
        problems.append(f"the review approved {_short(reviewed)}, but the prototype-report's "
                        f"commit is {_short(prototype_commit)}: the approval is of another "
                        "build")
    pinned = [p.get("content_hash") for p in
              ((review.get("provenance") or {}).get("inputs") or [])
              if isinstance(p, dict) and p.get("artifact_type") == "prototype-report"]
    if prototype_hash and pinned and prototype_hash not in pinned:
        problems.append("the review-report reviewed an older prototype-report than the run's "
                        "newest")
    return problems, "approved" if not problems else "mismatch"
