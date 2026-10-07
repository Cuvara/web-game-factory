"""How much of the accepted build a candidate commit replaced, measured in its repository.

Observed (2026-10-05, both validation games): a run adopted the repository a person had
accepted at G4, wrote a new design, and its greybox rewrote the game wholesale - the 3D
courses cut from 234-440 m to 38-124 m, environment.ts lost 939 lines, the marble's drag
went from 0.6 to 0.15 - and nothing asked anyone. This module makes "replaced" a number:

    measure(git, accepted, candidate, rules)
        {units, files, lines, shares, exceeded, ...}: between the accepted commit and the
        candidate commit, read from git objects, never the working tree -

        units     the accepted content data file's units (core/reference/
                  brief-commitments.yaml existing_content.path) that the candidate removed,
                  or changed: a key the accepted unit had is gone or holds another value.
                  A key the candidate adds is an extension, not a change.
        files     the accepted text files under `roots` the candidate deleted, or rewrote:
                  deleted lines at least `file_rewritten_share` of the file's accepted lines
        lines     the accepted lines under `roots` the candidate deleted

    Shares are of what the accepted commit shipped. A quantity the accepted commit does not
    ship (no content data file) is None - unmeasured, and named - never 0.

`git` is any object with `has_commit(sha)`, `file_at(sha, path)`, `line_counts(sha, roots)`
({path: lines} of the text files under `roots` at `sha`) and `numstat(a, b, roots)`
({path: (added, deleted)} with renames off: a moved file is a deleted one). `Git` below is
the develop module's hardened git (wgflib.procs owns the process).
"""

import json

__all__ = ["Git", "MeasureError", "measure", "unit_changes", "QUANTITIES"]

QUANTITIES = ("units_replaced_share", "files_rewritten_share", "lines_deleted_share")
# The empty tree: `git diff --numstat <EMPTY> <commit>` counts every text file's lines.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


class MeasureError(RuntimeError):
    """The repository cannot answer: a commit is missing, git failed."""


class Git:
    """Reads through wgf_develop.repository.GitRepo: hardened argv, no repository-defined
    command, one owned process per call."""

    def __init__(self, root):
        from wgf_develop.repository import GitRepo, Runner
        self.repo = GitRepo(root, Runner())

    def has_commit(self, sha):
        return self.repo.is_repository() and self.repo.has_commit(sha)

    def file_at(self, sha, path):
        return self.repo.file_at(sha, path)

    def _numstat(self, a, b, roots):
        result = self.repo._git("diff", "--numstat", "--no-renames", "--no-ext-diff",
                                "--no-textconv", a, b, "--", *roots, check=False)
        if not result.ok:
            raise MeasureError(f"git diff --numstat {a[:12]} {b[:12]} failed: "
                               f"{result.tail(400).strip()}")
        out = {}
        for line in result.output.splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3 or parts[0] == "-" or parts[1] == "-":
                continue  # binary
            try:
                out[parts[2]] = (int(parts[0]), int(parts[1]))
            except ValueError:
                continue
        return out

    def line_counts(self, sha, roots):
        return {path: added for path, (added, _deleted)
                in self._numstat(EMPTY_TREE, sha, roots).items()}

    def numstat(self, a, b, roots):
        return self._numstat(a, b, roots)


def _units(text):
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    units = (data or {}).get("units") if isinstance(data, dict) else None
    if not isinstance(units, list):
        return None
    return {str(u.get("id")): u for u in units if isinstance(u, dict) and u.get("id")}


def _changed(old, new):
    """Whether `new` drops or alters anything `old` had: keys it adds are an extension."""
    if isinstance(old, dict):
        if not isinstance(new, dict):
            return True
        return any(key not in new or _changed(value, new[key]) for key, value in old.items())
    if isinstance(old, list):
        if not isinstance(new, list) or len(new) < len(old):
            return True
        return any(_changed(a, b) for a, b in zip(old, new))
    if isinstance(old, bool) or isinstance(new, bool):
        return old is not new
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return float(old) != float(new)
    return old != new


def unit_changes(accepted, candidate):
    """(removed ids, changed ids) of `accepted` ({id: unit}) in `candidate`."""
    removed = sorted(uid for uid in accepted if uid not in candidate)
    changed = sorted(uid for uid in accepted if uid in candidate
                     and _changed(accepted[uid], candidate[uid]))
    return removed, changed


def _share(part, whole):
    return round(part / whole, 4) if whole else None


def measure(git, accepted, candidate, rules):
    """The replacement record. Raises MeasureError when the repository cannot answer."""
    roots = list(rules.get("roots") or ["src"])
    content_path = rules.get("content_path") or "public/content/units.json"
    rewritten_at = float(rules.get("file_rewritten_share", 0.5))
    for sha, what in ((accepted, "accepted"), (candidate, "candidate")):
        if not sha or not git.has_commit(sha):
            raise MeasureError(f"the {what} commit {str(sha)[:12] or '(none)'} is not in the "
                               "checkout")
    out = {"accepted_commit": accepted, "candidate_commit": candidate, "roots": roots,
           "content_path": content_path, "unmeasured": []}

    before = _units(git.file_at(accepted, content_path))
    if before is None:
        out.update(units_accepted=None, units_removed=[], units_changed=[],
                   units_replaced_share=None)
        out["unmeasured"].append(f"units: the accepted commit ships no readable "
                                 f"{content_path}")
    else:
        after = _units(git.file_at(candidate, content_path)) or {}
        removed, changed = unit_changes(before, after)
        out.update(units_accepted=len(before), units_removed=removed, units_changed=changed,
                   units_replaced_share=_share(len(removed) + len(changed), len(before)))

    lines = git.line_counts(accepted, roots)
    stat = git.numstat(accepted, candidate, roots)
    total = sum(lines.values())
    deleted = rewritten = 0
    rewritten_files = []
    for path, count in sorted(lines.items()):
        gone = (stat.get(path) or (0, 0))[1]
        deleted += min(gone, count)
        if count and gone / count >= rewritten_at:
            rewritten += 1
            rewritten_files.append({"path": path, "lines": count, "deleted": gone})
    if not lines:
        out["unmeasured"].append(f"files: the accepted commit ships no text file under "
                                 f"{', '.join(roots)}")
    rewritten_files.sort(key=lambda f: (-f["deleted"], f["path"]))
    out.update(files_accepted=len(lines), files_rewritten=rewritten,
               files_rewritten_share=_share(rewritten, len(lines)),
               rewritten_files=rewritten_files[:20],
               lines_accepted=total, lines_deleted=deleted,
               lines_deleted_share=_share(deleted, total))
    maximum = rules.get("maximum") or {}
    out["maximum"] = {q: maximum.get(q) for q in QUANTITIES if maximum.get(q) is not None}
    out["exceeded"] = [q for q in QUANTITIES if out.get(q) is not None
                       and maximum.get(q) is not None and out[q] > maximum[q]]
    return out
