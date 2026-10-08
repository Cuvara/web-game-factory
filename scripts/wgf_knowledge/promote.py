"""A lesson candidate drafted as a lesson, for a person's pull request (`wgf knowledge promote`).

    draft(candidate, lessons, lessons_text, evidence_text, checks, vocab, ...) -> Draft

A draft is a patch - unified diffs a person applies with `git apply`, reviews and merges -
and never an edit: nothing here writes `core/` or `workspace/`. It holds:

* the lessons.yaml entry, appended, with the file's minor version raised (adding a lesson is
  a minor version, docs/knowledge-enforcement.md);
* the evidence.yaml entry: where the lesson came from (`source.kind`), the candidate it was
  drafted from (`candidate: C-<n>`, which is how the candidate reads as promoted), and the
  runs and reports that showed it;
* for a lesson a check holds, the test stubs its `tests` name - one that must show the check
  FAILS the defect (catches, the negative case) and one that it PASSES the fixed build
  (passes, the positive case). They fail until a person writes them: the regression firewall
  (`wgf knowledge firewall`) holds every active lesson's tests, so a stub never ships green.

What is drafted, from the candidate's evidence:

| Evidence                                  | Draft                                            |
|-------------------------------------------|--------------------------------------------------|
| measured, its proposed check classified   | enforced / active; level derived from the check's |
|                                           | tier, declared only when the proposal is stronger |
| subjective (review comments, judgment),   | gap / candidate: experimental, the proposed check |
| or a check nothing classifies             | named in `gap` - guidance that never blocks       |

Refused (PromoteRefused, exit 1): a rejected or already promoted candidate; one its reporter
said is not systemic; a blocking or required proposal on subjective evidence - a review
comment never becomes a rule that holds a build by itself; a blocking or required proposal
no classified check can hold; a proposal weaker than its check derives (a level is weakened
only by a check's tier, never by a lesson); a draft that would fail the knowledge model's
own integrity rules.
"""

import collections
import datetime
import difflib
import json
import re
import textwrap

from . import model

LESSONS_PATH = "core/reference/lessons.yaml"
EVIDENCE_PATH = "workspace/lessons/evidence.yaml"
STRONG = ("blocking", "required")


class PromoteRefused(Exception):
    """The candidate cannot be drafted as asked; the message says why."""


Draft = collections.namedtuple("Draft", "lesson evidence patch files notes")


def _bump_minor(version):
    major, minor, _ = (int(p) for p in str(version).split("."))
    return f"{major}.{minor + 1}.0"


def _version_key(version):
    try:
        return tuple(int(p) for p in str(version).split("."))
    except ValueError:
        return (0,)


def next_id(lessons):
    numbers = [int(l["id"][1:]) for l in (lessons or {}).get("lessons") or ()
               if isinstance(l, dict) and re.match(r"^L[0-9]+$", str(l.get("id") or ""))]
    return f"L{max(numbers or [0]) + 1}"


def _category(check, lessons, given):
    if given:
        return given
    if not check:
        return None
    source = check.split(":", 1)[0]
    counts = collections.Counter(
        l.get("category") for l in (lessons or {}).get("lessons") or ()
        if isinstance(l, dict) and l.get("category")
        and any(str(c).split(":", 1)[0] == source for c in l.get("checks") or ()))
    return counts.most_common(1)[0][0] if counts else None


def _title(candidate, given):
    if given:
        return given.strip()
    text = str(candidate.get("summary") or "").strip()
    first = re.split(r"(?<=[.;])\s", text, maxsplit=1)[0].rstrip(".;")
    return first if len(first) <= 100 else first[:97].rstrip() + "..."


def _folded(key, text):
    lines = textwrap.wrap(" ".join(str(text).split()), width=86) or [""]
    return [f"    {key}: >-"] + [f"      {line}" for line in lines]


def _flow(value):
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {_flow(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_flow(v) for v in value) + "]"
    return str(value)


def _entry_text(entry):
    out = [f"  - id: {entry['id']}", f"    title: {json.dumps(entry['title'])}",
           f"    category: {entry['category']}"]
    out += _folded("problem", entry["problem"])
    out += _folded("root_cause", entry["root_cause"])
    out += _folded("lesson", entry["lesson"])
    out.append("    scope: " + ("global" if not entry["scope"] else _flow(entry["scope"])))
    out += [f"    status: {entry['status']}", f"    lifecycle: {entry['lifecycle']}"]
    if entry.get("level"):
        out.append(f"    level: {entry['level']}")
    out.append(f"    introduced: {_flow(entry['introduced'])}")
    if entry.get("checks"):
        out.append(f"    checks: {_flow(entry['checks'])}")
    if entry.get("tests"):
        out.append("    tests:")
        for kind in model.TEST_KINDS:
            refs = entry["tests"].get(kind) or []
            if not refs:
                out.append(f"      {kind}: []")
                continue
            out.append(f"      {kind}:")
            out += [f"        - {ref}" for ref in refs]
    if entry.get("gap"):
        out += _folded("gap", entry["gap"])
    return "\n".join(out) + "\n"


def _stub(entry, candidate, test_path, names):
    sources = "\n".join(
        f"    - run {s.get('run')}: {s.get('artifact_type')} {s.get('artifact_id')} "
        f"v{s.get('version')} ({s.get('report_hash')}), commit {s.get('commit')}"
        for s in candidate.get("sources") or ())
    catches, passes = names
    return f'''"""{entry['id']}: {entry['title']}

Drafted by `wgf knowledge promote {candidate['id']}` from the lesson candidate it names; the
tests below are STUBS that fail until a person writes them. The regression firewall
(`wgf knowledge firewall`, the Core Acceptance Suite's KNOWLEDGE category) runs them for every
active lesson, so this lesson cannot ship with them unwritten.

The check that holds it: {', '.join(entry.get('checks') or [])}. Replay the evidence the
candidate was seen in - the reports, not a description of them:
{sources}

    python -m unittest {test_path.replace('/', '.')[:-3]}
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


class Lesson{entry['id']}(unittest.TestCase):
    def {catches}(self):
        """The negative case: on the build that showed the defect, the check FAILS."""
        self.fail("write me: replay the failing evidence through the check and assert it fails")

    def {passes}(self):
        """The positive case: on the fixed or accepted build, the same check PASSES."""
        self.fail("write me: replay the fixed build through the check and assert it passes")


if __name__ == "__main__":
    unittest.main()
'''


def _diff(path, old, new):
    if old is None:
        lines = new.splitlines(True)
        return (f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n"
                f"+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n"
                + "".join("+" + line for line in lines))
    body = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        fromfile=f"a/{path}", tofile=f"b/{path}", n=3))
    return f"diff --git a/{path} b/{path}\n" + body


def _lessons_after(text, entry_text, version):
    new, count = re.subn(r"(?m)^version: *[0-9]+\.[0-9]+\.[0-9]+ *$",
                         f"version: {_bump_minor(version)}", text, count=1)
    if not count:
        raise PromoteRefused(f"{LESSONS_PATH} has no `version:` line")
    return new.rstrip("\n") + "\n\n" + entry_text


def _evidence_after(text, line):
    return text.rstrip("\n") + "\n" + line + "\n"


def _evidence_entry(entry_id, candidate):
    sources = candidate.get("sources") or []
    kind = "review" if all(s.get("artifact_type") == "review-report" for s in sources) \
        else "run"
    runs = sorted({s.get("run") for s in sources if s.get("run")})
    refs = sorted({f"{s.get('run')}/{s.get('artifact_id')}/v{s.get('version')}"
                   for s in sources})
    leg = {"source": {"kind": kind, "run": runs[0] if len(runs) == 1 else None,
                      "date": (sources[0].get("date") or "")[:10] or None},
           "candidate": candidate["id"], "games": [], "evidence": refs}
    first = next((s for s in sources if s.get("commit")), None)
    if first:
        leg["discovered"] = {"run": first.get("run"), "commit": first.get("commit")}
    return leg


def _yaml_value(value):
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {_yaml_value(v)}" for k, v in value.items()
                               if v is not None) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_yaml_value(v) for v in value) + "]"
    text = str(value)
    if re.match(r"^[A-Za-z0-9][A-Za-z0-9 ._/@-]*$", text) and ": " not in text:
        return text
    return json.dumps(text)


def draft(candidate, lessons, lessons_text, evidence_text, checks, vocab, evidence=None,
          lesson_id=None, level=None, check=None, category=None, title=None, scope=None,
          version=None, today=None, promoted=None):
    """The Draft of one stored candidate (a candidate_record), or PromoteRefused."""
    cid = candidate.get("id")
    if candidate.get("state") == "rejected":
        raise PromoteRefused(f"{cid} was rejected by a person "
                             f"({(candidate.get('rejected') or {}).get('reason')})")
    if (promoted or {}).get(cid):
        raise PromoteRefused(f"{cid} is already promoted, to {promoted[cid]}")
    systemic = candidate.get("systemic")
    if isinstance(systemic, dict) and systemic.get("value") is False:
        raise PromoteRefused(f"{cid}: its reporter said it is not systemic "
                             f"({systemic.get('why') or 'no reason given'}) - a build's own "
                             "mistake is not a lesson")
    check = (check or candidate.get("proposed_check") or "").strip() or None
    wanted = level or candidate.get("proposed_level")
    if wanted is not None and wanted not in model.LEVELS:
        raise PromoteRefused(f"level {wanted!r} is not one of {', '.join(model.LEVELS)}")
    basis = candidate.get("basis")
    if wanted in STRONG and basis != "measured":
        raise PromoteRefused(
            f"{cid}: a {wanted} rule holds every build it applies to, and this candidate's "
            "evidence is only subjective (a review's judgment, no measured finding) - a "
            "subjective comment never becomes blocking or required by itself. Draft it "
            "experimental (--level experimental), or ingest a run whose gate measured it")
    classified = check is not None and check in (checks or {})
    if wanted in STRONG and not classified:
        raise PromoteRefused(
            f"{cid}: a {wanted} rule needs a check that holds it, and "
            f"{check or 'no check'} is not classified in core/reference/check-tiers.yaml - "
            "add the check to its source first")
    entry_id = lesson_id or next_id(lessons)
    if any(isinstance(l, dict) and l.get("id") == entry_id
           for l in (lessons or {}).get("lessons") or ()):
        raise PromoteRefused(f"{entry_id} is already a lesson; ids are never reused")
    category = _category(check, lessons, category)
    if not category:
        raise PromoteRefused(f"{cid}: name its --category (one of "
                             f"{', '.join((vocab or {}).get('categories') or [])}) - nothing "
                             "infers it from the proposed check")
    introduced_version = version or max(
        [str(l.get("introduced", {}).get("version")) for l in (lessons or {}).get("lessons") or ()
         if isinstance(l, dict) and isinstance(l.get("introduced"), dict)] or ["0.0.0"],
        key=_version_key)
    today = today or datetime.date.today().isoformat()
    entry = {"id": entry_id, "title": _title(candidate, title), "category": category,
             "problem": candidate.get("symptom") or candidate["summary"],
             "root_cause": candidate["root_cause"], "lesson": candidate["summary"],
             "scope": dict(scope if scope is not None else candidate.get("proposed_scope") or {}),
             "introduced": {"version": introduced_version, "date": today}}
    notes, files = [], {}
    held = classified and basis == "measured"
    if held:
        derived = model.derive_level(dict(entry, status="enforced", lifecycle="active",
                                          checks=[check]), checks)
        if wanted and model.level_rank(wanted) < model.level_rank(derived):
            raise PromoteRefused(
                f"{cid}: {check} is {checks[check].get('tier')}, so the rule derives {derived}; "
                f"a lesson cannot declare it weaker ({wanted}) - a level is weakened only by "
                "moving the check's tier, in a new version of its source file")
        test_path = f"scripts/tests/test_lesson_{entry_id.lower()}.py"
        names = (f"test_{entry_id}_the_check_fails_the_defect",
                 f"test_{entry_id}_the_check_passes_the_fixed_build")
        entry.update(status="enforced", lifecycle="active", checks=[check],
                     tests={"catches": [f"{test_path}::{names[0]}"],
                            "passes": [f"{test_path}::{names[1]}"], "generalizes": []})
        if wanted and model.level_rank(wanted) > model.level_rank(derived):
            entry["level"] = wanted
        files[test_path] = _stub(entry, candidate, test_path, names)
        notes.append(f"{entry_id} is drafted enforced and active at "
                     f"{entry.get('level') or derived} (its check {check} is "
                     f"{checks[check].get('tier')}); its two test stubs fail until written")
    else:
        why = ("its evidence is only subjective" if basis != "measured"
               else f"{check} is not classified in check-tiers.yaml" if check
               else "it proposes no check")
        held_text = (f"the proposed check {check}" if check else "no check proposed yet")
        entry.update(status="gap", lifecycle="candidate",
                     gap=f"nothing holds it yet ({why}): {held_text}. A person confirms it on "
                         "a measured failure and names the check and the test that catches it "
                         "before it holds any build.")
        notes.append(f"{entry_id} is drafted as a candidate (experimental, never blocks): {why}")
    if candidate.get("duplicate_of"):
        notes.append(f"{cid} proposes the check {candidate['duplicate_of']} already names: "
                     "consider strengthening that lesson instead of adding one")
    # The draft holds the model's own rules, or it is not offered.
    after = json.loads(json.dumps(lessons))
    after["lessons"] = list(after.get("lessons") or []) + [entry]
    entry_problems = [p for p in model.lesson_problems(after, checks, vocab)
                      if f" {entry_id}:" in p]
    from wgf_quality import registry
    entry_problems += [p for p in registry.lesson_problems(after, checks, runtime=True,
                                                            evidence=evidence)
                       if f" {entry_id}:" in p]
    if entry_problems:
        raise PromoteRefused(f"the draft of {cid} would fail the knowledge model: "
                             + "; ".join(entry_problems))
    entry_text = _entry_text(entry)
    from wgflib.yamllite import load
    read_back = (load("lessons:\n" + entry_text) or {}).get("lessons", [None])[0]
    if read_back != entry:
        raise PromoteRefused(f"the draft of {cid} does not read back as written")
    new_lessons = _lessons_after(lessons_text, entry_text, model.version_of(lessons))
    leg = _evidence_entry(entry_id, candidate)
    new_evidence = _evidence_after(evidence_text, f"  {entry_id}: {_yaml_value(leg)}")
    patch = _diff(LESSONS_PATH, lessons_text, new_lessons) \
        + _diff(EVIDENCE_PATH, evidence_text, new_evidence) \
        + "".join(_diff(path, None, text) for path, text in sorted(files.items()))
    return Draft(entry, leg, patch, dict({LESSONS_PATH: new_lessons, EVIDENCE_PATH: new_evidence},
                                         **files), notes)
