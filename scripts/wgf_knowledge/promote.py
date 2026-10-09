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

Against a 2.1.0 lessons file the draft carries the model's 2.1.0 fields: `domain` (the
candidate's, `--domain`, else the one its category usually is - DOMAIN_OF_CATEGORY),
`principle` and `anti_pattern` (the candidate's, else its summary and its symptom, for the
person to sharpen in review), `classification` (the drafted level's: BLOCKING, REQUIRED,
RECOMMENDATION, or OBSERVATION for an experimental draft - never stronger than the evidence)
and `revision: 1`. A candidate may propose several checks (`proposed_checks`, e.g. the same
rule held on the design and on the build); the level is derived over all of them.

**Evidence strength (K6.4, strength.py).** The draft's classification below REQUIRED never
exceeds what the candidate's evidence strength supports - derived again here from the run
store (`ingest.strength_of` with the verifier and `remeasure`), never read from the stored
record: hypothesis and single-run at most OBSERVATION/HEURISTIC (a measured candidate whose
check is advisory is then drafted experimental, a candidate lesson, never a
RECOMMENDATION), reproduced at most RECOMMENDATION, validated may propose
VALIDATED_PRINCIPLE (`classification=`; an enforced, validated lesson with all three test
stubs and the evidence's `verified` leg from the reproduced pass). BLOCKING and REQUIRED
stay derived from the check tiers exactly as before: strength never raises nor lowers them.
The evidence entry records the strength and why (`strength`). A classification asked for
beyond the evidence is refused.

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

from . import model, strength

LESSONS_PATH = "core/reference/lessons.yaml"
EVIDENCE_PATH = "workspace/lessons/evidence.yaml"
STRONG = ("blocking", "required")
# The domain a lesson of a scorecard line usually is (2.1.0), when the candidate names none.
DOMAIN_OF_CATEGORY = {
    "gameplay": "game-design", "feel": "game-feel", "level_design": "level-design",
    "art_2d": "art-direction", "art_3d": "art-direction", "ui_ux": "ui", "audio": "audio",
    "performance": "performance", "browser": "ux", "technical": "technical",
    "accessibility": "accessibility", "platform_compliance": "technical",
    "publishing_readiness": "technical", "process": "process"}
CLASSIFICATION_OF_LEVEL = {"blocking": "BLOCKING", "required": "REQUIRED",
                           "recommended": "RECOMMENDATION", "experimental": "OBSERVATION"}


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


def _one_line(text):
    return " ".join(str(text).split())


def _folded(key, text):
    lines = textwrap.wrap(" ".join(str(text).split()), width=86, break_on_hyphens=False,
                          break_long_words=False) or [""]
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
    if entry.get("domain"):
        out += [f"    domain: {entry['domain']}",
                f"    classification: {entry['classification']}",
                f"    revision: {entry['revision']}"]
        out += _folded("principle", entry["principle"])
        out += _folded("anti_pattern", entry["anti_pattern"])
    out += _folded("problem", entry["problem"])
    out += _folded("root_cause", entry["root_cause"])
    out += _folded("lesson", entry["lesson"])
    out.append("    scope: " + ("global" if entry["scope"] in ("global", {}) else _flow(entry["scope"])))
    out += [f"    status: {entry['status']}", f"    lifecycle: {entry['lifecycle']}"]
    if entry.get("level"):
        out.append(f"    level: {entry['level']}")
    out.append(f"    introduced: {_flow(entry['introduced'])}")
    if entry.get("validated"):
        out.append(f"    validated: {_flow(entry['validated'])}")
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
    catches, passes = names[:2]
    generalizes = ""
    if len(names) > 2:
        generalizes = f'''

    def {names[2]}(self):
        """Generalization: the check catches the defect in a game other than the one it was
        learned from (another family or render), and passes it fixed."""
        self.fail("write me: replay another game's regressed and fixed builds through the check")'''
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
        self.fail("write me: replay the fixed build through the check and assert it passes"){generalizes}


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


def _evidence_entry(entry_id, candidate, found=None, verified=None):
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
    if verified:
        leg["verified"] = verified
    if found is not None:
        leg["strength"] = {"level": found["strength"], "why": found["why"]}
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
          version=None, today=None, promoted=None, verify=None, domain=None,
          classification=None, remeasure=None):
    """The Draft of one stored candidate (a candidate_record), or PromoteRefused.

    `classification` asks for one (lessons.yaml `classifications`); it is refused beyond
    what the evidence strength supports (strength.allows) or the drafted level allows.
    `remeasure(source)` reads a source's re-measurement again from its run store
    (ingest.remeasurer); without it no repair is re-read, so the strength is hypothesis."""
    from . import ingest
    cid = candidate.get("id")
    # The record is read as stored, so it is checked as stored: a hand edit that breaks the
    # record's shape is not drafted.
    shape = ingest.record_problems(candidate)
    if shape:
        raise PromoteRefused(f"{cid}: the stored candidate is not a candidate record - "
                             + "; ".join(shape[:3]))
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
    # Several proposed checks (the same rule held at two places) are drafted together; an
    # explicit --check replaces them all.
    proposed = [] if (check and check != candidate.get("proposed_check")) else [
        str(c).strip() for c in candidate.get("proposed_checks") or () if str(c).strip()]
    all_checks = list(dict.fromkeys(([check] if check else []) + proposed))
    check = check or (all_checks[0] if all_checks else None)
    wanted = level or candidate.get("proposed_level")
    if wanted is not None and wanted not in model.LEVELS:
        raise PromoteRefused(f"level {wanted!r} is not one of {', '.join(model.LEVELS)}")
    # Derived from the sources, never the record's own `basis` (which a hand edit can set),
    # and each measured source re-verified against the run store: without a verifier nothing
    # is re-verified, so nothing is measured.
    basis = ingest.basis_of(candidate, verify=verify or (lambda source, record: False))
    if wanted in STRONG and basis != "measured":
        raise PromoteRefused(
            f"{cid}: a {wanted} rule holds every build it applies to, and this candidate's "
            "evidence is only subjective (a review's judgment, no measured finding) - a "
            "subjective comment never becomes blocking or required by itself. Draft it "
            "experimental (--level experimental), or ingest a run whose gate measured it")
    unclassified = [c for c in all_checks if c not in (checks or {})]
    classified = bool(all_checks) and not unclassified
    if wanted in STRONG and not classified:
        raise PromoteRefused(
            f"{cid}: a {wanted} rule needs a check that holds it, and "
            f"{', '.join(unclassified) or 'no check'} is not classified in "
            "core/reference/check-tiers.yaml - add the check to its source first")
    # K6.4: the evidence strength, derived again from the run store - never the stored one.
    found = ingest.strength_of(candidate, verify=verify or (lambda source, record: False),
                               remeasure=remeasure)
    evidence_level = found["strength"]
    if classification is not None and classification not in model.CLASSIFICATIONS:
        raise PromoteRefused(f"classification {classification!r} is not one of "
                             f"{', '.join(model.CLASSIFICATIONS)}")
    if classification is not None and not strength.allows(evidence_level, classification):
        raise PromoteRefused(
            f"{cid}: {classification} claims more than its evidence shows - the evidence is "
            f"{evidence_level} ({found['why']}). On {evidence_level} evidence a draft proposes "
            f"at most {strength.ceiling(evidence_level)} (core/reference/evidence-strength.yaml)")
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
    entry = {"id": entry_id, "title": _one_line(_title(candidate, title)), "category": category,
             "problem": _one_line(candidate.get("symptom") or candidate["summary"]),
             "root_cause": _one_line(candidate["root_cause"]),
             "lesson": _one_line(candidate["summary"]),
             "scope": dict(scope if scope is not None else candidate.get("proposed_scope") or {})
             or "global",
             "introduced": {"version": introduced_version, "date": today}}
    notes, files = [], {}
    held = classified and basis == "measured"
    capped = None
    if held:
        # Below REQUIRED, a recommendation needs the repair reproduced (strength.CEILING); a
        # rule the check tiers make blocking or required is theirs, whatever the strength.
        derived = model.derive_level(dict(entry, status="enforced", lifecycle="active",
                                          checks=all_checks), checks)
        final = wanted if wanted and model.level_rank(wanted) > model.level_rank(derived) \
            else derived
        if final == "recommended" and not strength.allows(evidence_level, "RECOMMENDATION"):
            if wanted == "recommended":
                raise PromoteRefused(
                    f"{cid}: a recommended rule needs its repair reproduced, and the evidence "
                    f"is {evidence_level} ({found['why']}). Draft it experimental "
                    "(--level experimental), or ingest the runs that repeated the measurement")
            held = False
            capped = (f"its evidence is {evidence_level}, and a recommendation needs the repair "
                      f"reproduced ({found['why']})")
    if classification in ("RECOMMENDATION", "VALIDATED_PRINCIPLE") and not held:
        raise PromoteRefused(
            f"{cid}: {classification} is a lesson a check holds; this draft is experimental "
            f"({capped or 'its evidence is subjective, or its check is not classified'}) - "
            "OBSERVATION or HEURISTIC")
    validated_draft = classification == "VALIDATED_PRINCIPLE"
    if held:
        derived = model.derive_level(dict(entry, status="enforced", lifecycle="active",
                                          checks=all_checks), checks)
        if wanted and model.level_rank(wanted) < model.level_rank(derived):
            raise PromoteRefused(
                f"{cid}: {', '.join(all_checks)} "
                f"{'is' if len(all_checks) == 1 else 'are'} "
                f"{'/'.join(sorted({checks[c].get('tier') for c in all_checks}))}, so the rule "
                f"derives {derived}; "
                f"a lesson cannot declare it weaker ({wanted}) - a level is weakened only by "
                "moving the check's tier, in a new version of its source file")
        final = wanted if wanted and model.level_rank(wanted) > model.level_rank(derived) \
            else derived
        if classification is not None and final in STRONG and \
                classification != CLASSIFICATION_OF_LEVEL[final]:
            raise PromoteRefused(
                f"{cid}: its checks derive a {final} rule, classified "
                f"{CLASSIFICATION_OF_LEVEL[final]} by their tiers - evidence strength neither "
                f"raises nor lowers it ({classification} asked)")
        if validated_draft and final != "recommended":
            raise PromoteRefused(
                f"{cid}: a VALIDATED_PRINCIPLE is a validated lesson that is not blocking or "
                f"required; its checks derive {final}")
        test_path = f"scripts/tests/test_lesson_{entry_id.lower()}.py"
        names = (f"test_{entry_id}_the_check_fails_the_defect",
                 f"test_{entry_id}_the_check_passes_the_fixed_build")
        if validated_draft:
            names += (f"test_{entry_id}_the_check_generalizes",)
        entry.update(status="enforced", lifecycle="validated" if validated_draft else "active",
                     checks=all_checks,
                     tests={"catches": [f"{test_path}::{names[0]}"],
                            "passes": [f"{test_path}::{names[1]}"],
                            "generalizes": [f"{test_path}::{names[2]}"] if validated_draft
                            else []})
        if validated_draft:
            entry["validated"] = {"version": introduced_version, "date": today}
        if wanted and model.level_rank(wanted) > model.level_rank(derived):
            entry["level"] = wanted
        files[test_path] = _stub(entry, candidate, test_path, names)
        notes.append(f"{entry_id} is drafted enforced and {entry['lifecycle']} at "
                     f"{entry.get('level') or derived} (its checks "
                     + ", ".join(f"{c} {checks[c].get('tier')}" for c in all_checks)
                     + f"); its {len(names)} test stubs fail until written")
    else:
        why = (capped if capped else "its evidence is only subjective" if basis != "measured"
               else f"{', '.join(unclassified)} is not classified in check-tiers.yaml"
               if all_checks else "it proposes no check")
        held_text = (f"the proposed check {', '.join(all_checks)}" if all_checks
                     else "no check proposed yet")
        entry.update(status="gap", lifecycle="candidate",
                     gap=f"nothing holds it yet ({why}): {held_text}. A person confirms it on "
                         "a measured failure and names the check and the test that catches it "
                         "before it holds any build.")
        notes.append(f"{entry_id} is drafted as a candidate (experimental, never blocks): {why}")
    notes.append(f"{entry_id}: evidence strength {found['why']}"
                 + (f"; {len(found['refused'])} measurement(s) refused" if found["refused"]
                    else ""))
    if candidate.get("duplicate_of"):
        notes.append(f"{cid} proposes the check {candidate['duplicate_of']} already names: "
                     "consider strengthening that lesson instead of adding one")
    if model.has_model_2_1(lessons):
        domain = domain or candidate.get("domain") or DOMAIN_OF_CATEGORY.get(category)
        if not domain:
            raise PromoteRefused(f"{cid}: name its --domain (one of "
                                 f"{', '.join(model.DOMAINS)})")
        level_drafted = model.level_of(entry, checks) or "experimental"
        principle = _one_line(candidate.get("principle") or candidate["summary"])
        anti = _one_line(candidate.get("anti_pattern") or candidate.get("symptom")
                         or candidate["summary"])
        chosen = classification or CLASSIFICATION_OF_LEVEL.get(level_drafted, "OBSERVATION")
        fields = {"domain": domain, "classification": chosen,
                  "revision": 1, "principle": principle, "anti_pattern": anti}
        # In the order the file writes them: after the category.
        ordered = {}
        for key, value in entry.items():
            ordered[key] = value
            if key == "category":
                ordered.update(fields)
        entry = ordered
        if not candidate.get("principle"):
            notes.append(f"{entry_id}: its principle and anti_pattern are drafted from the "
                         "candidate's summary and symptom - sharpen them in review")
    # The evidence leg: the strength, and - for a validated draft - the verified leg, the
    # reproduced pass the ledger recorded on the game that raised it.
    verified = None
    if entry.get("lifecycle") == "validated":
        leg_of = next((c for c in found["counted"] if c["level"] == "reproduced"), None)
        if leg_of is None:
            raise PromoteRefused(f"{cid}: no reproduced pass to record as its verified leg")
        verified = {"run": leg_of["run"], "artifact_id": leg_of.get("after_artifact"),
                    "commit": leg_of["after"], "date": today}
    leg = _evidence_entry(entry_id, candidate, found, verified)
    evidence_after = None
    if evidence is not None:
        evidence_after = json.loads(json.dumps(evidence))
        evidence_after.setdefault("lessons", {})
        evidence_after["lessons"] = dict(evidence_after["lessons"] or {}, **{entry_id: leg})
    # The draft holds the model's own rules, or it is not offered.
    after = json.loads(json.dumps(lessons))
    after["lessons"] = list(after.get("lessons") or []) + [entry]
    entry_problems = [p for p in model.lesson_problems(after, checks, vocab, evidence_after)
                      if f" {entry_id}:" in p]
    from wgf_quality import registry
    entry_problems += [p for p in registry.lesson_problems(after, checks, runtime=True,
                                                            evidence=evidence_after)
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
    new_evidence = _evidence_after(evidence_text, f"  {entry_id}: {_yaml_value(leg)}")
    patch = _diff(LESSONS_PATH, lessons_text, new_lessons) \
        + _diff(EVIDENCE_PATH, evidence_text, new_evidence) \
        + "".join(_diff(path, None, text) for path, text in sorted(files.items()))
    return Draft(entry, leg, patch, dict({LESSONS_PATH: new_lessons, EVIDENCE_PATH: new_evidence},
                                         **files), notes)
