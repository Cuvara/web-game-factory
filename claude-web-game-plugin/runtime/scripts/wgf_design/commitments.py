"""core/reference/brief-commitments.yaml: the counts a brief and a strategy commit to, and the
design's counts against them.

    load()                      the vocabulary, cached per (path, mtime)
    stated(text, source, data)  the commitments one text states: [{quantity, minimum,
                                per_group, words, source}]
    of_strategy(strategy, data) the brief's and the strategy's statements, merged: the largest
                                minimum per (quantity, per_group), with the words behind it
    modes(brief, catalogue, data)  the catalogue modes the brief names: {feature id: words}
    design_counts(design)       what the design plans: units (not optional), groups, the
                                fewest units and climax units in a group, climax units
    view(design, strategy, ...) {"stated", "unmet", "deferred"}: rule brief_commitments_met

A commitment is a minimum. A design that plans more meets it; one that plans fewer, or cuts
a mode the brief asked for, breaches the blocking rule with the brief's own words as the
evidence. Nothing here knows a game, a family or a theme; every word is in the file.
"""

import os
import re

from wgflib import mechanics, paths
from wgflib.yamllite import load_file

__all__ = ["PATH", "load", "stated", "of_strategy", "modes", "design_counts", "view",
           "describe", "clauses", "planned_units"]

PATH = os.path.join(paths.REFERENCE, "brief-commitments.yaml")

_CACHE = {}


def load(path=None):
    """The vocabulary. Raises YamlError on a broken file: a file nobody can read is a failed
    check, never an empty one."""
    path = path or PATH
    stamp = os.stat(path).st_mtime_ns
    hit = _CACHE.get(path)
    if hit is None or hit[0] != stamp:
        hit = (stamp, load_file(path))
        _CACHE[path] = hit
    return hit[1]


def clauses(text):
    """`text` as clauses: parentheses removed, split at `,` `;` `.` `:` (not inside a number),
    each normalized like the lexicon reads text."""
    text = re.sub(r"\([^)]*\)", " ", str(text or ""))
    parts = re.split(r"[,;:]|\.(?!\d)", text)
    return [mechanics.normalize(p) for p in parts if p.strip()]


def _terms(entry):
    """(phrase tuple, plural) for every term of a quantity, the longest first."""
    out = [(tuple(mechanics.normalize(t).split()), False) for t in entry.get("singular") or []]
    out += [(tuple(mechanics.normalize(t).split()), True) for t in entry.get("plural") or []]
    return sorted(out, key=lambda item: -len(item[0]))


def _term_at(words, i, quantities):
    """(quantity, length, plural) of the longest term starting at words[i], or None."""
    best = None
    for qid, entry in quantities.items():
        for phrase, plural in _terms(entry or {}):
            if tuple(words[i:i + len(phrase)]) == phrase and (
                    best is None or len(phrase) > best[1]):
                best = (qid, len(phrase), plural)
    return best


def _number_at(words, i, numbers):
    """(value, length) of the number starting at words[i], or None."""
    if re.fullmatch(r"\d+", words[i]):
        return int(words[i]), 1
    for phrase in sorted(numbers, key=lambda p: -len(p.split())):
        parts = mechanics.normalize(phrase).split()
        if tuple(words[i:i + len(parts)]) == tuple(parts):
            return int(numbers[phrase]), len(parts)
    return None


def _phrases(items):
    return sorted((tuple(mechanics.normalize(p).split()) for p in items or []),
                  key=lambda p: -len(p))


def _ends_with(words, end, phrases):
    return any(len(p) <= end and tuple(words[end - len(p):end]) == p for p in phrases)


def _starts_with(words, start, phrases):
    for p in phrases:
        if tuple(words[start:start + len(p)]) == p:
            return len(p)
    return 0


def stated(text, source, data=None):
    """The commitments `text` states, in order: [{quantity, minimum, per_group, words,
    source}]. `words` is the span of the text that states it."""
    data = data if data is not None else load()
    quantities = data.get("quantities") or {}
    numbers = data.get("numbers") or {}
    gap = int(data.get("max_gap_words") or 0)
    breakers = {mechanics.normalize(w) for w in data.get("gap_breakers") or []}
    ceilings = _phrases(data.get("not_minimum_before"))
    per_words = _phrases(data.get("per_words"))
    markers = _phrases(data.get("per_group_markers"))
    group_terms = {"groups": quantities.get("groups") or {}}
    found = []

    def per_group_after(words, at):
        """The length of '<per word> <group term>' starting at words[at], else 0."""
        n = _starts_with(words, at, per_words)
        if n and at + n < len(words):
            term = _term_at(words, at + n, group_terms)
            if term:
                return n + term[1]
        return 0

    for clause in clauses(text):
        words = clause.split()
        used = set()
        i = 0
        while i < len(words):
            number = _number_at(words, i, numbers)
            if number is None:
                i += 1
                continue
            value, length = number
            if _ends_with(words, i, ceilings):
                i += length
                continue
            j = i + length
            hit = None
            while j < len(words) and j - (i + length) <= gap:
                term = _term_at(words, j, quantities)
                if term:
                    hit = (j, term)
                    break
                if words[j] in breakers or _number_at(words, j, numbers):
                    break
                j += 1
            if hit is None:
                i += length
                continue
            j, (qid, tlen, _plural) = hit
            end = j + tlen
            per = per_group_after(words, end) if qid != "groups" else 0
            found.append({"quantity": qid, "minimum": value, "per_group": bool(per),
                          "words": " ".join(words[i:end + per]), "source": source})
            used.update(range(j, end + per))
            if qid == "groups" and end + 1 < len(words) and words[end] == "of":
                inner = _number_at(words, end + 1, numbers)
                if inner:
                    found.append({"quantity": "units", "minimum": inner[0], "per_group": True,
                                  "words": " ".join(words[i:end + 1 + inner[1]]),
                                  "source": source})
                    used.update(range(end, end + 1 + inner[1]))
            i = end + per
        # Unnumbered terms: only where the quantity says what one commits.
        for k in range(len(words)):
            if k in used:
                continue
            term = _term_at(words, k, quantities)
            if not term:
                continue
            qid, tlen, plural = term
            unnumbered = (quantities.get(qid) or {}).get("unnumbered") or {}
            minimum = unnumbered.get("plural" if plural else "singular")
            if not minimum or (k > 0 and _number_at(words, k - 1, numbers)):
                continue
            used.update(range(k, k + tlen))
            per = any(tuple(words[m:m + len(p)]) == p and m + len(p) < len(words)
                      and _term_at(words, m + len(p), group_terms)
                      for p in markers for m in range(len(words)))
            found.append({"quantity": qid, "minimum": 1 if per else int(minimum),
                          "per_group": per, "words": clause if per else " ".join(
                              words[max(0, k - 1):k + tlen]), "source": source})
    return found


def _strategy_texts(strategy, data):
    for field in (data.get("sources") or {}).get("strategy") or []:
        node = strategy
        for part in field.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, list):
            for item in node:
                yield field, str(item)
        elif node:
            yield field, str(node)


def of_strategy(strategy, data=None):
    """The brief's and the strategy's commitments, the largest minimum per (quantity,
    per_group), each with the words and source behind it."""
    data = data if data is not None else load()
    strategy = strategy or {}
    every = stated(strategy.get("brief") or "", "brief", data)
    for field, text in _strategy_texts(strategy, data):
        every += stated(text, f"strategy {field}", data)
    best = {}
    for c in every:
        key = (c["quantity"], c["per_group"])
        if key not in best or c["minimum"] > best[key]["minimum"]:
            best[key] = c
    order = {"groups": 0, "units": 1, "climax": 2}
    return sorted(best.values(), key=lambda c: (order.get(c["quantity"], 9), c["per_group"]))


def modes(brief, catalogue, data=None):
    """{feature id: the brief's words} for every catalogue feature of a commitment kind the
    brief names."""
    data = data if data is not None else load()
    kinds = set((data.get("modes") or {}).get("feature_kinds") or [])
    out = {}
    for entry in (catalogue or {}).get("features") or []:
        if not isinstance(entry, dict) or entry.get("kind") not in kinds:
            continue
        hit = sorted(mechanics.phrases_in(brief or "", entry.get("terms")))
        if hit:
            out[entry["id"]] = hit[0]
    return out


def planned_units(design):
    spec = (design or {}).get("build_spec") or {}
    content = spec.get("content") if isinstance(spec.get("content"), dict) else {}
    return [u for u in content.get("units") or []
            if isinstance(u, dict) and u.get("tier") != "optional"]


def design_counts(design):
    """What the design plans, over its units not tiered optional."""
    units = planned_units(design)
    groups = {}
    for unit in units:
        if unit.get("group"):
            groups.setdefault(str(unit["group"]), []).append(unit)
    climax = [u for u in units if u.get("purpose") == "climax"]
    return {"units": len(units), "groups": len(groups),
            "units_per_group": min((len(m) for m in groups.values()), default=0),
            "climax": len(climax),
            "climax_per_group": min((sum(1 for u in m if u.get("purpose") == "climax")
                                     for m in groups.values()), default=0)}


def describe(c):
    label = {"groups": "groups", "units": "units", "climax": "climax units"}.get(
        c["quantity"], c["quantity"])
    return (f"{label}{' per group' if c['per_group'] else ''} >= {c['minimum']} "
            f"(\"{c['words']}\", {c['source']})")


def _tier(design, strategy):
    content = ((design or {}).get("build_spec") or {}).get("content") or {}
    tier = content.get("quality_tier") if isinstance(content, dict) else None
    model = ((strategy or {}).get("concept") or {}).get("content_model") or {}
    return tier or model.get("quality_tier")


def view(design, strategy, data=None, catalogue=None):
    """{"stated": [...], "unmet": [...], "deferred": [...]}: every commitment the brief and
    strategy state, the ones the design does not meet - each with what the design plans - and,
    at a tier the counts do not bind (`counts_hold_at_tiers`), the unmet counts reported
    instead of breached."""
    data = data if data is not None else load()
    if catalogue is None:
        from .features import load_catalogue
        catalogue = load_catalogue()
    tier = _tier(design, strategy)
    binds = tier in (data.get("counts_hold_at_tiers") or [])
    counts = design_counts(design)
    stated_out, unmet, deferred = [], [], []
    for c in of_strategy(strategy, data):
        key = c["quantity"] + ("_per_group" if c["per_group"] else "")
        planned = counts.get(key, 0)
        stated_out.append(describe(c))
        if planned < c["minimum"]:
            (unmet if binds else deferred).append(f"{describe(c)}: the design plans {planned}")
    keeps = {"include"}
    if tier not in ((data.get("modes") or {}).get("include_at_tiers") or []):
        keeps.add("later")
    features = {f.get("catalogue"): f for f in (design or {}).get("features") or []
                if isinstance(f, dict) and f.get("catalogue")}
    for fid, words in sorted(modes((strategy or {}).get("brief") or "", catalogue,
                                   data).items()):
        stated_out.append(f"mode {fid} (\"{words}\", brief)")
        feature = features.get(fid)
        decision = ((feature or {}).get("evaluation") or {}).get("decision")
        if feature is None:
            unmet.append(f"mode {fid} (\"{words}\", brief): the design has no feature for it")
        elif decision not in keeps or (decision == "include"
                                       and feature.get("tier") == "optional"):
            unmet.append(f"mode {fid} (\"{words}\", brief): the design's feature "
                         f"{feature.get('id')} is {decision or 'not evaluated'} "
                         f"(tier {feature.get('tier')}); the brief asked for it"
                         + (f" and tier {tier} builds it" if decision == "later" else ""))
    return {"stated": stated_out, "unmet": unmet, "deferred": deferred, "tier": tier}
