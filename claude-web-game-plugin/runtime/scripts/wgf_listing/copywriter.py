"""The store copy: who writes it, from what, within which bounds.

Two writers, one contract (store-listing.schema.json `localeCopy`). Which one writes is the
run's tier's (core/reference/store-listing.yaml `writer`, factory.listing.writer.kind `auto`):
the copywriter agent at the release tier, the template writer for development runs.

    TemplateWriter   the Factory's own: deterministic sentences assembled from the facts and
                     the game's own strings, in English, and in any other locale whose
                     strings the bundle ships (the game's own title and rules text are the
                     grounded copy in that locale). It never translates: a locale with no
                     strings and no agent is a missing deliverable, reported as such.
    CommandWriter    an agent host (factory.listing.writer: kind command, argv with
                     {brief} {output} {prompt} placeholders), run through wgflib.procs with
                     the allowlisted agent environment, read-only, once per locale. Its
                     texts go through the same grounding check; a malformed or ungrounded
                     answer is shown its problems and asked once more, then the template
                     writer's text stands in and the listing says so (`writer.fallback`).
                     It is the copywriter (core/roles/roles.yaml): its brief carries the
                     build's measured counts, every input the build accepts, what a full
                     description is, and - re-entered through triage - the store-copy
                     findings listing-validation raised against the previous copy.

Both are held to the build (buildfacts.py): a count the build did not measure, a controls
text missing an input the build accepts, a required locale without a full description is
refused from the agent and left out of the template's text.

Every text is then fitted to the canonical bounds (core/reference/store-listing.yaml `copy`)
at a sentence or word boundary - never mid-word, never by inventing a shorter claim.
"""

import json
import os
import re

from wgflib import agentenv, procs

from wgf_review.verdict import from_output

from . import buildfacts, grounding
from .facts import genre_label, humanize

__all__ = ["TemplateWriter", "CommandWriter", "fit_text", "fit_list", "write_copy",
           "PROMPT", "PROMPT_STDOUT", "MAX_WRITER_RUNS"]

MAX_WRITER_RUNS = 2
PROMPT = (
    "You write the store listing of a web game you did not make. Read {brief} in full: it "
    "holds every fact you may use and the exact JSON shape to produce. Claim nothing the "
    "facts do not state. You are READ-ONLY: create, edit or delete nothing except your "
    "answer, written as one JSON object to {output}."
)
PROMPT_STDOUT = (
    "You write the store listing of a web game you did not make. Read {brief} in full: it "
    "holds every fact you may use and the exact JSON shape to produce. Claim nothing the "
    "facts do not state. You are READ-ONLY: create, edit or delete no file. End your answer "
    "with the JSON object, exactly in the shape the brief gives."
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# The game's own strings carry no fixed key names: the template ships `title.heading` and
# `hud.objective`, a game may name them `game.title` and `play.objective`. Known keys first,
# then the key whose English text is the design's own objective, then a key named for what
# it holds. A string with a placeholder (`Course {n}`) is a label, never copy.
_TITLE_KEYS = ("title.heading", "boot.title", "title", "game.title", "game.name")
_OBJECTIVE_KEYS = ("hud.objective", "play.objective", "objective")
_RULES_KEYS = ("title.rules", "title.howto", "rules", "howto")
_OBJECTIVE_NAME = re.compile(r"(?:^|[._-])(objective|goal)$", re.I)
_RULES_NAME = re.compile(r"(?:^|[._-])(rules|howto|how_to|instructions)$", re.I)


# -- fitting --------------------------------------------------------------------------------

def fit_text(text, max_chars, min_chars=None):
    """`text` within `max_chars`: whole sentences when they fit, else whole words with an
    ellipsis-free cut; the string is never cut inside a word."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if max_chars is None or len(text) <= max_chars:
        return text
    sentences = _SENTENCE_END.split(text)
    kept = ""
    for sentence in sentences:
        candidate = (kept + " " + sentence).strip()
        if len(candidate) <= max_chars:
            kept = candidate
        else:
            break
    if kept and (min_chars is None or len(kept) >= min_chars):
        return kept
    words = text.split(" ")
    kept = ""
    for word in words:
        candidate = (kept + " " + word).strip()
        if len(candidate) <= max_chars:
            kept = candidate
        else:
            break
    return kept


def fit_list(items, maximum, max_chars=None, allowed=None):
    """At most `maximum` items, each within `max_chars`, each in `allowed` when given,
    de-duplicated in order."""
    out, seen = [], set()
    for item in items or []:
        text = item.get("text") if isinstance(item, dict) else item
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if not text:
            continue
        if allowed is not None and text.lower() not in {str(a).lower() for a in allowed}:
            continue
        if max_chars is not None and len(text) > max_chars:
            text = fit_text(text, max_chars)
            if not text:
                continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({**item, "text": text} if isinstance(item, dict) else text)
        if maximum is not None and len(out) >= maximum:
            break
    return out


# -- the template writer --------------------------------------------------------------------

def _sentence(text):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def _join(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _dedupe_sentences(paragraphs):
    """Drop a sentence whose content words mostly repeat an earlier one (the lose condition
    restating the mechanic that ends the run)."""
    kept, seen = [], []
    for paragraph in paragraphs:
        out = []
        for sentence in _SENTENCE_END.split(paragraph):
            words = grounding.content_words(sentence)
            if words and any(len(words & w) / len(words | w) >= 0.6 for w in seen):
                continue
            seen.append(words)
            out.append(sentence)
        if out:
            kept.append(" ".join(out))
    return kept


def _verb_line(facts):
    """The first sentence: what the player does, from the objective, else the core loop's
    first beat."""
    objective = facts.get("objective")
    if objective:
        return _sentence(objective)
    loop = facts.get("core_loop") or ""
    first = re.split(r"\s*(?:->|→|;|\.)\s*", loop)[0] if loop else ""
    return _sentence(first) if first else ""


def _controls_line(facts):
    """One sentence per device the build accepts: the design's bindings, and for a device
    only the play probe reported, the actions it reported on it."""
    controls = facts.get("controls") or {}
    probed = facts.get("probe_inputs") or {}
    parts = []
    for device, label in (("touch", "Touch"), ("mouse", "Mouse"), ("keyboard", "Keyboard"),
                          ("gamepad", "Gamepad")):
        entries = controls.get(device) or [humanize(a) for a in probed.get(device) or []]
        if entries:
            parts.append(f"{label}: {'; '.join(e.rstrip('.') for e in entries)}.")
    if parts:
        return " ".join(parts)
    return _sentence(controls.get("summary")) if controls.get("summary") else ""


def _genre_words(facts, vocabulary):
    chain = facts.get("genre") or []
    return genre_label(chain[0], vocabulary) if chain else None


def _tags(facts, vocabulary, reference):
    tags = list(facts.get("genre") or [])
    controls = facts.get("controls") or {}
    engine = facts.get("engine") or {}
    target = facts.get("session_target_s")
    rules = {
        "single-player": True,
        "casual": isinstance(target, (int, float)) and target <= 300,
        "mobile": facts.get("orientation") in ("portrait", "both") or bool(controls.get("touch")),
        "one-touch": controls.get("primary_input") == "touch" and len(controls.get("touch") or []) <= 1,
        "3d": engine.get("dimension") == "3d",
        "2d": engine.get("dimension") == "2d",
        "high-score": bool(facts.get("endless")),
    }
    for entry in (reference.get("categories") or {}).get("derived_tags") or []:
        tag = str(entry.get("tag"))
        if rules.get(tag):
            tags.append(tag)
    return tags


def _plain(text):
    return re.sub(r"[\s.!?]+$", "", str(text or "").strip()).lower()


def _string_key(strings, known, named=None, *, english=None, same_as=None):
    """The key of the game's own string for one purpose in `strings` (one locale), or None:
    a known key, else the key whose English string says `same_as` (the design's own
    objective), else the first key, sorted, named for the purpose. Empty strings and
    strings with a placeholder are labels, not copy."""
    def usable(key):
        value = strings.get(key)
        return isinstance(value, str) and value.strip() and "{" not in value

    for key in known:
        if usable(key):
            return key
    if english and same_as:
        for key in sorted(english):
            if _plain(english[key]) == _plain(same_as) and usable(key):
                return key
    if named is not None:
        for key in sorted(strings):
            if named.search(key) and usable(key):
                return key
    return None


def _plural(word):
    word = str(word or "").strip()
    if not word or word.endswith("s"):
        return word
    return word[:-1] + "ies" if word.endswith("y") and word[-2:-1] not in "aeiou" else word + "s"


def _measured_line(facts):
    """The build's own counts, as measured: "12 courses across 3 worlds." - or "" when the
    build's units were not measured."""
    counts = ((facts.get("measured") or {}).get("counts") or {})
    units, groups = counts.get("units") or {}, counts.get("groups") or {}
    kind = units.get("kind") or facts.get("content_unit_kind")
    if not units.get("value") or not kind:
        return ""
    line = f"{units['value']} {_plural(kind) if units['value'] != 1 else kind}"
    if groups.get("value") and groups.get("kind") and groups["value"] > 1:
        line += f" across {groups['value']} {_plural(groups['kind'])}"
    return _sentence(line)


def _without_contradictions(copy, facts, locale, counts=None):
    """The template writer quotes the design; where the build outgrew it ("six courses"
    when twelve ship), a count nothing measured or a feature the design cut, the sentence
    or item is left out, never rewritten."""
    def keep(text):
        if grounding.contradictions(text, facts, locale):
            return False
        return not [p for p in buildfacts.count_problems({"t": text}, facts, counts or {}, locale=locale)
                    + buildfacts.excluded_feature_claims({"t": text}, facts, locale=locale)
                    if p["severity"] == "error"]

    for field, value in list(copy.items()):
        if isinstance(value, str) and value and not keep(value):
            copy[field] = " ".join(s for s in _SENTENCE_END.split(value) if keep(s))
        elif isinstance(value, list):
            copy[field] = [v for v in value if keep(v.get("text") if isinstance(v, dict) else v)
                           or not isinstance(v.get("text") if isinstance(v, dict) else v, str)]
    if isinstance(copy.get("subtitle_variants"), list) and copy.get("subtitle") not in copy["subtitle_variants"]:
        copy["subtitle"] = copy["subtitle_variants"][0] if copy["subtitle_variants"] else ""
    return copy


class TemplateWriter:
    kind = "template"

    def __init__(self, reference, vocabulary=None):
        self.reference = reference or {}
        self.vocabulary = vocabulary

    def write(self, facts, locale="en"):
        """localeCopy for `locale`, or None when nothing grounded can be written in it (no
        English and no strings of that locale)."""
        strings = (facts.get("strings") or {}).get(locale) or {}
        if locale != "en" and not strings:
            return None
        bounds = self.reference.get("copy") or {}
        counts = self.reference.get("counts") or {}
        if locale == "en":
            return _without_contradictions(self._english(facts, bounds), facts, locale, counts)
        copy = self._from_strings(facts, strings, locale, bounds)
        return _without_contradictions(copy, facts, locale, counts) if copy else copy

    def _english(self, facts, bounds):
        title = facts["title"]
        genre = _genre_words(facts, self.vocabulary)
        engine = facts.get("engine") or {}
        verb = _verb_line(facts)
        mechanics = facts.get("mechanics") or []
        features = facts.get("features") or []
        controls_line = _controls_line(facts)
        target = facts.get("session_target_s")

        devices = [d for d in ("touch", "mouse", "keyboard", "gamepad")
                   if (facts.get("controls") or {}).get(d)]
        qualifier = ""
        if genre or engine.get("dimension") or devices:
            head = f"A {genre.lower()}" if genre else "A game"
            if engine.get("dimension"):
                head += f" in {engine['dimension'].upper()}"
            if devices:
                head += ", playable by " + _join(devices)
            qualifier = _sentence(head)
        loop_sentence = (_sentence(re.sub(r"\s*(?:->|→)\s*", ", then ", facts["core_loop"]))
                         if facts.get("core_loop") else "")
        concept_sentence = _sentence(facts["concept"]) if facts.get("concept") else ""
        short_bounds = bounds.get("short_description") or {}
        short = ""
        # The verb first; then, until the canonical minimum is met, the qualifier, the loop
        # and the concept - every sentence a fact, nothing padded.
        for candidate in (verb, qualifier, loop_sentence, concept_sentence):
            if not candidate:
                continue
            joined = (short + " " + candidate).strip()
            if short_bounds.get("max_chars") is None or len(joined) <= short_bounds["max_chars"]:
                short = joined
            elif not short:
                short = fit_text(candidate, short_bounds.get("max_chars"))
            if short_bounds.get("min_chars") is None or len(short) >= short_bounds["min_chars"]:
                break
        short = fit_text(short, short_bounds.get("max_chars"), short_bounds.get("min_chars"))

        paragraphs = [verb]
        if loop_sentence:
            paragraphs.append(loop_sentence)
        if mechanics:
            names = [m.get("description") or m["name"] for m in mechanics[:5]]
            paragraphs.append(_sentence("How it plays: " + " ".join(_sentence(n) for n in names)))
        if facts.get("lose"):
            paragraphs.append(_sentence("The run ends when " + facts["lose"][0].lower() + facts["lose"][1:]))
        if facts.get("win"):
            paragraphs.append(_sentence("You win when " + facts["win"][0].lower() + facts["win"][1:]))
        measured_line = _measured_line(facts)
        if measured_line:
            paragraphs.append(measured_line)
        if controls_line:
            paragraphs.append("Controls. " + controls_line)
        if isinstance(target, (int, float)) and target > 0:
            minutes = max(1, int(round(target / 60)))
            paragraphs.append(_sentence(f"A session takes about {minutes} minute{'s' if minutes != 1 else ''}"))
        if facts.get("visual_style"):
            paragraphs.append(_sentence("Look: " + facts["visual_style"]))
        long_bounds = bounds.get("long_description") or {}
        long = fit_text("  ".join(_dedupe_sentences([p for p in paragraphs if p])),
                        long_bounds.get("max_chars"), long_bounds.get("min_chars"))

        bullets = []
        for mechanic in mechanics:
            text = mechanic.get("description") or mechanic["name"]
            bullets.append({"text": fit_text(_sentence(text).rstrip("."),
                                             (bounds.get("features") or {}).get("max_chars")),
                            "source": f"mechanic:{mechanic['id']}"})
        skip = re.compile(r"telemetry|platform integration|localization|placement|analytics", re.I)
        meta = re.compile(r"build_spec|title strategy|game_states|wired as", re.I)
        for feature in features:
            if skip.search(feature["name"]) or any(b["source"].endswith(":" + feature["id"]) for b in bullets):
                continue
            text = feature.get("description") or feature["name"]
            if meta.search(text):
                text = feature["name"]
            bullets.append({"text": fit_text(_sentence(text).rstrip("."),
                                             (bounds.get("features") or {}).get("max_chars")),
                            "source": f"feature:{feature['id']}"})
        if controls_line:
            bullets.append({"text": fit_text(controls_line.rstrip("."),
                                             (bounds.get("features") or {}).get("max_chars")),
                            "source": "controls:summary" if (facts.get("controls") or {}).get("summary")
                            else next((f"controls:{d}" for d in ("touch", "mouse", "keyboard", "gamepad")
                                       if (facts.get("controls") or {}).get(d)), "controls:summary")})
        features_bounds = bounds.get("features") or {}
        # A thin design (one mechanic, no feature list) still has facts worth a bullet: the
        # objective, the loop, what ends a run, the concept - each its own source.
        used = {b["source"] for b in bullets}
        for source, text in (("objective", facts.get("objective")), ("core_loop", facts.get("core_loop")),
                             ("lose", facts.get("lose")), ("concept", facts.get("concept"))):
            if len(bullets) >= (features_bounds.get("min") or 3):
                break
            if text and source not in used:
                bullets.append({"text": fit_text(_sentence(text).rstrip("."), features_bounds.get("max_chars")),
                                "source": source})
                used.add(source)
        bullets = fit_list(bullets, features_bounds.get("max"), features_bounds.get("max_chars"))

        tags = fit_list(_tags(facts, self.vocabulary, self.reference),
                        (bounds.get("tags") or {}).get("max"))
        chain = facts.get("genre") or []
        categories = fit_list([genre_label(g, self.vocabulary) for g in reversed(chain)][:1]
                              or ([genre] if genre else []),
                              (bounds.get("categories") or {}).get("max"))
        # A subtitle names this game, never only its genre ("Puzzle", "Puzzle in 2D"): the
        # generic ones are left out (store-listing.yaml copy.subtitle_generic_words).
        lead = mechanics[0]["name"] if mechanics and mechanics[0].get("name") else None
        candidates = [
            fit_text(verb.rstrip("."), (bounds.get("subtitle") or {}).get("max_chars")),
            f"{genre}: {lead.lower()}" if genre and lead else None,
            measured_line.rstrip(".") if measured_line else None,
            _sentence(genre).rstrip(".") if genre else None,
            f"{genre} in {engine['dimension'].upper()}" if genre and engine.get("dimension") else None,
        ]
        labels = [genre_label(g, self.vocabulary) for g in facts.get("genre") or []]
        specific = [c for c in candidates if c and not buildfacts.generic_subtitle(
            {"subtitle": c}, facts, self.reference, "en", labels)]
        subtitle_variants = fit_list(specific, (bounds.get("subtitle") or {}).get("variants", 3),
                                     (bounds.get("subtitle") or {}).get("max_chars"))
        promo = fit_list([
            verb.rstrip("."),
            f"{title}: {verb.rstrip('.')[0].lower() + verb.rstrip('.')[1:]}" if verb else None,
            f"{title} - {genre.lower()}" + (f", {controls_line.split('.')[0].lower()}" if controls_line else "")
            if genre else None,
        ], (bounds.get("promo") or {}).get("variants", 3), (bounds.get("promo") or {}).get("max_chars"))
        copy = {
            "title": fit_text(title, (bounds.get("title") or {}).get("max_chars")),
            "subtitle": subtitle_variants[0] if subtitle_variants else "",
            "subtitle_variants": subtitle_variants,
            "short_description": short,
            "long_description": long,
            "features": bullets,
            "controls": fit_text(controls_line, (bounds.get("controls") or {}).get("max_chars")),
            "tags": tags,
            "categories": categories,
            "promo": promo,
            "age_rating": None,
        }
        return copy

    def _from_strings(self, facts, strings, locale, bounds):
        """Copy in a locale from the game's own strings: its title, its rules or objective
        text, its button labels. Grounded by construction; shorter than the English."""
        title_key = _string_key(strings, _TITLE_KEYS)
        title = strings[title_key] if title_key else facts["title"]
        objective_key = _string_key(strings, _OBJECTIVE_KEYS, _OBJECTIVE_NAME,
                                    english=(facts.get("strings") or {}).get("en"), same_as=facts.get("objective"))
        rules_key = _string_key(strings, _RULES_KEYS, _RULES_NAME)
        objective = strings[objective_key] if objective_key else None
        rules = strings[rules_key] if rules_key else None
        if not rules and not objective:
            return None
        verb = _sentence(objective or rules)
        short = fit_text(verb, (bounds.get("short_description") or {}).get("max_chars"))
        long_text = " ".join(_sentence(t) for t in dict.fromkeys([objective, rules]) if t)
        long = fit_text(long_text, (bounds.get("long_description") or {}).get("max_chars"))
        bullets = []
        for key in dict.fromkeys(k for k in (objective_key, rules_key) if k):
            bullets.append({"text": fit_text(_sentence(strings[key]).rstrip("."),
                                             (bounds.get("features") or {}).get("max_chars")),
                            "source": f"string:{locale}:{key}"})
        english = self._english(facts, bounds)
        return {
            "title": fit_text(title, (bounds.get("title") or {}).get("max_chars")),
            "subtitle": "",
            "subtitle_variants": [],
            "short_description": short,
            "long_description": long,
            "features": bullets,
            "controls": "",
            "tags": list(english["tags"]),
            "categories": list(english["categories"]),
            "promo": fit_list([verb.rstrip(".")], 1, (bounds.get("promo") or {}).get("max_chars")),
            "age_rating": None,
        }


# -- the command writer ---------------------------------------------------------------------

def _requirements(facts, locale, reference):
    """What the copy in `locale` must carry, beyond the bounds: the build's measured counts
    (the only counts it may state), every input device the build accepts, a full
    description where the tier asks for one."""
    bars = ((facts.get("quality") or {}).get("bars") or {})
    measured = ((facts.get("measured") or {}).get("counts") or {})
    return {
        "counts": {fact: {"value": c.get("value"), "kind": c.get("kind")} for fact, c in measured.items()},
        "counts_strict": bool(bars.get("copy_counts_match_build")),
        "devices": buildfacts.required_devices(facts),
        "full_description": bool(bars.get("full_description_per_required_locale")),
        "excluded": [f.get("name") for f in facts.get("features_excluded") or []],
    }


def refusals(copy, facts, locale, reference):
    """[str]: what the copywriter's text in `locale` must not ship with, beyond grounding -
    an input the build accepts left out of the controls, a subtitle that names only the
    genre, and, where the tier asks for one, a description that is not full."""
    out = []
    needs = _requirements(facts, locale, reference)
    missing, _checkable = buildfacts.controls_problems(copy, facts, reference.get("controls"), locale)
    if missing:
        out.append(f"controls ({locale}) does not name {', '.join(missing)}: the build accepts "
                   f"{', '.join(needs['devices'])}")
    if needs["full_description"]:
        out.extend(f"{p} ({locale}): every required locale carries a full description"
                   for p in buildfacts.full_description_problems(copy, reference, locale))
    if buildfacts.generic_subtitle(copy, facts, reference, locale):
        out.append(f"subtitle ({locale}) {copy.get('subtitle')!r} names only the genre: say what "
                   "this game is")
    return out


def render_brief(facts, locale, bounds, claims, output_path, to_stdout, previous=None,
                 reference=None, findings=None, role=None):
    shape = {
        "title": "<= %s chars" % (bounds.get("title") or {}).get("max_chars"),
        "subtitle_variants": ["<= %s chars each, %s variants" % (
            (bounds.get("subtitle") or {}).get("max_chars"), (bounds.get("subtitle") or {}).get("variants"))],
        "short_description": "%s-%s chars; the first sentence says what the player does" % (
            (bounds.get("short_description") or {}).get("min_chars"),
            (bounds.get("short_description") or {}).get("max_chars")),
        "long_description": "%s-%s chars" % ((bounds.get("long_description") or {}).get("min_chars"),
                                             (bounds.get("long_description") or {}).get("max_chars")),
        "features": [{"text": "<= %s chars" % (bounds.get("features") or {}).get("max_chars"),
                      "source": "a key of facts.sources, e.g. mechanic:<id> or objective"}],
        "controls": "one line per input device the build accepts, in this locale's words",
        "tags": ["%s-%s tags" % ((bounds.get("tags") or {}).get("min"), (bounds.get("tags") or {}).get("max"))],
        "categories": ["%s-%s" % ((bounds.get("categories") or {}).get("min"), (bounds.get("categories") or {}).get("max"))],
        "promo": ["<= %s chars, %s variants" % ((bounds.get("promo") or {}).get("max_chars"),
                                                 (bounds.get("promo") or {}).get("variants"))],
    }
    reference = reference or {"copy": bounds, "claims": claims}
    needs = _requirements(facts, locale, reference)
    role = role or {}
    lines = [f"# Store copy brief - {facts.get('title')} ({locale})", ""]
    if role.get("focus"):
        lines += [f"You are the {role.get('label') or 'copywriter'}. {role['focus']}", ""]
    lines += [
             "Write the store listing texts for this game in locale `%s`, from the facts below "
             "and nothing else. Every sentence must rest on a fact; a feature bullet names the "
             "fact it comes from in `source`. Describe, do not rate: no superlatives, no claims "
             "the facts do not make. The first sentence of each description says what the "
             "player does." % locale, "",
             "The facts are the build's where the build says something (`sources` names where "
             "each was read): `content_units` and `content_unit_names` are what ships, "
             "`scope_deltas` what the build added, cut or deferred against the design, and "
             "`conflicts` where the design said otherwise. Follow the build; a text the build "
             "contradicts is refused.", "",
             "## What the build measured (the only counts you may state)", ""]
    if needs["counts"]:
        lines += [f"- {fact}: {c['value']}" + (f" ({c['kind']})" if c.get("kind") else "")
                  for fact, c in needs["counts"].items()]
    else:
        lines.append("- nothing was measured on this build: state no count of levels, worlds, "
                     "bosses or modes")
    lines += ["", "A count of anything else the copy states must come from the facts below; "
              "a count the build did not measure is refused" + (" at this tier." if needs["counts_strict"]
                                                               else "."), ""]
    if needs["devices"]:
        lines += ["## Controls", "",
                  "The build accepts: " + ", ".join(needs["devices"]) + ". The `controls` text names "
                  "every one of them, in this locale's own words (facts.controls and "
                  "facts.probe_inputs say what each does).", ""]
    if needs["full_description"]:
        lines += ["## A full description", "",
                  f"This locale ({locale}) is required: title, short_description, long_description "
                  "and controls, all written in it, the long description of several sentences "
                  "within its bounds. Never only the game's objective line. Do not borrow English "
                  "words; the texts are checked against the facts' numbers and ids, not against "
                  "shared words.", ""]
    if needs["excluded"]:
        lines += ["## Not in this build", "",
                  "The design deferred or cut these; never name them: " + ", ".join(needs["excluded"]), ""]
    if findings:
        lines += ["## What listing-validation found in the previous copy (fix every one)", ""]
        for finding in findings:
            lines.append(f"- [{finding.get('id')}] {finding.get('summary')}")
        lines.append("")
    lines += [
             "## Facts (the only material)", "", "```json",
             json.dumps({k: v for k, v in facts.items() if k != "strings"}, indent=2, ensure_ascii=False),
             "```", ""]
    strings = (facts.get("strings") or {}).get(locale)
    if strings:
        lines += ["## The game's own strings in this locale", "", "```json",
                  json.dumps(strings, indent=2, ensure_ascii=False), "```", ""]
    lines += ["## Words that need backing", "",
              "A text using one of these terms must be backed as stated, else it is refused:", ""]
    for claim in claims or []:
        lines.append(f"- {', '.join(claim.get('terms') or [])}: backed by {', '.join(claim.get('backed_by') or [])}")
    lines += ["", "## The shape to produce", "", "```json", json.dumps(shape, indent=2), "```", ""]
    if previous:
        lines += ["## Your previous answer was refused", ""] + [f"- {p}" for p in previous] + [""]
    lines.append("Write the JSON object " + (f"to `{output_path}`." if not to_stdout else
                                             "as the last thing in your answer."))
    return "\n".join(lines) + "\n"


class CommandWriter:
    kind = "command"

    def __init__(self, settings, reference, vocabulary=None, fallback=None, logger=None,
                 findings=None, role=None):
        self.settings = settings            # argv, timeout, idle_timeout, text_from, env_passthrough
        self.reference = reference or {}
        self.findings = list(findings or [])
        self.role = role
        self.vocabulary = vocabulary
        self.fallback = fallback or TemplateWriter(reference, vocabulary)
        self.logger = logger
        self.runs = 0
        self.fell_back = False
        self.problems = []

    def write(self, facts, locale, workdir):
        os.makedirs(workdir, exist_ok=True)
        bounds = self.reference.get("copy") or {}
        claims = self.reference.get("claims") or []
        to_stdout = self.settings.get("text_from") == "stdout"
        previous = None
        for run in range(1, MAX_WRITER_RUNS + 1):
            self.runs += 1
            output = os.path.join(workdir, f"copy-{locale}-{run}.json")
            brief = os.path.join(workdir, f"copy-{locale}-{run}.brief.md")
            log = os.path.join(workdir, f"copy-{locale}-{run}.log")
            with open(brief, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(render_brief(facts, locale, bounds, claims, output, to_stdout, previous,
                                          reference=self.reference, role=self.role,
                                          findings=[f for f in self.findings
                                                    if _finding_locale(f) in (None, locale)]))
            values = {"brief": brief, "output": output}
            values["prompt"] = (PROMPT_STDOUT if to_stdout else PROMPT).format(**values)
            argv = [part.format(**values) for part in self.settings["argv"]]
            env = agentenv.scrubbed(self.settings.get("env_passthrough") or ())
            env.update({"WGF_LISTING_BRIEF": brief, "WGF_LISTING_OUTPUT": output})
            if self.logger is not None:
                self.logger.info("store copy writer", argv0=os.path.basename(argv[0]), locale=locale, run=run)
            result = procs.run(argv, cwd=workdir, env=env, timeout=self.settings.get("timeout_seconds", 600),
                               idle_timeout=self.settings.get("idle_timeout_seconds"), log_path=log)
            if not result.ok:
                previous = [f"the writer did not finish ({result.status}, exit {result.returncode})"]
                self.problems.append(previous[0])
                continue
            if to_stdout:
                extracted = from_output(result.stdout)
                if extracted is not None:
                    with open(output, "w", encoding="utf-8") as handle:
                        handle.write(extracted)
            copy, problems = self._parse(output, facts, bounds, claims, locale)
            if copy is not None:
                return copy
            previous = problems
            self.problems.extend(problems)
            if self.logger is not None:
                self.logger.warning("store copy refused", locale=locale, run=run, problems=problems[:5])
        self.fell_back = True
        return self.fallback.write(facts, locale)

    def _parse(self, path, facts, bounds, claims, locale):
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            return None, [f"no JSON object at {os.path.basename(path)}: {exc}"]
        if not isinstance(data, dict):
            return None, ["the answer is not a JSON object"]
        problems = []
        for field in ("title", "short_description", "long_description"):
            if not isinstance(data.get(field), str) or not data[field].strip():
                problems.append(f"{field} missing or empty")
        if not isinstance(data.get("features"), list) or not data["features"]:
            problems.append("features missing")
        else:
            for index, bullet in enumerate(data["features"]):
                if not isinstance(bullet, dict) or not isinstance(bullet.get("text"), str) \
                        or not isinstance(bullet.get("source"), str):
                    problems.append(f"features[{index}] is not {{text, source}}")
        if problems:
            return None, problems
        copy = {
            "title": fit_text(data["title"], (bounds.get("title") or {}).get("max_chars")),
            "subtitle": "",
            "subtitle_variants": fit_list([v for v in data.get("subtitle_variants") or [] if isinstance(v, str)],
                                          (bounds.get("subtitle") or {}).get("variants", 3),
                                          (bounds.get("subtitle") or {}).get("max_chars")),
            "short_description": fit_text(data["short_description"],
                                          (bounds.get("short_description") or {}).get("max_chars")),
            "long_description": fit_text(data["long_description"],
                                         (bounds.get("long_description") or {}).get("max_chars")),
            "features": fit_list([{"text": b["text"], "source": b["source"]} for b in data["features"]],
                                 (bounds.get("features") or {}).get("max"),
                                 (bounds.get("features") or {}).get("max_chars")),
            "controls": fit_text(data.get("controls") or "", (bounds.get("controls") or {}).get("max_chars")),
            "tags": fit_list([t for t in data.get("tags") or [] if isinstance(t, str)],
                             (bounds.get("tags") or {}).get("max")),
            "categories": fit_list([c for c in data.get("categories") or [] if isinstance(c, str)],
                                   (bounds.get("categories") or {}).get("max")),
            "promo": fit_list([p for p in data.get("promo") or [] if isinstance(p, str)],
                              (bounds.get("promo") or {}).get("variants", 3), (bounds.get("promo") or {}).get("max_chars")),
            "age_rating": data.get("age_rating") if isinstance(data.get("age_rating"), str) else None,
        }
        copy["subtitle"] = copy["subtitle_variants"][0] if copy["subtitle_variants"] else ""
        grounded = grounding.check(copy, facts, claims, locale=locale,
                                   counts=self.reference.get("counts"))
        errors = [p["message"] for p in grounded if p["severity"] == "error"]
        errors += refusals(copy, facts, locale, self.reference)
        if errors:
            return None, errors
        return copy, []


def _finding_locale(finding):
    """The locale a store-copy finding is about (its source `project`, `<platform>/<locale>`
    or `<locale>`), or None for one about every locale."""
    project = str(((finding or {}).get("source") or {}).get("project") or "")
    tail = project.rsplit("/", 1)[-1] if project else ""
    return tail if re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,8})*", tail or "") else None


def write_copy(facts, locales, reference, *, writer_settings=None, vocabulary=None, workdir=None,
               logger=None, findings=None, role=None, tier=None):
    """{locale: localeCopy or None}, and the writer record for the listing. The writer is
    `writer_settings.kind`; `auto` is the tier's (store-listing.yaml `writer.by_tier`). A
    command writer with no argv configured cannot run: the template writes, and the record
    says which writer the tier asked for (`required`)."""
    template = TemplateWriter(reference, vocabulary)
    configured = (writer_settings or {}).get("kind", "template")
    wanted = buildfacts.writer_kind(configured, tier, reference)
    kind = wanted if (wanted != "command" or (writer_settings or {}).get("argv")) else "template"
    writer = template
    if kind == "command":
        writer = CommandWriter(writer_settings, reference, vocabulary, fallback=template, logger=logger,
                               findings=findings, role=role)
    out = {}
    for locale in locales:
        if kind == "command":
            out[locale] = writer.write(facts, locale, os.path.join(workdir or ".", "writer"))
        else:
            out[locale] = template.write(facts, locale)
    record = {"kind": kind, "required": wanted}
    if tier:
        record["tier"] = tier
    if findings:
        record["findings"] = [str(f.get("id")) for f in findings if f.get("id")]
    if kind == "command":
        record["role"] = (role or {}).get("role") or "copywriter"
        argv = writer_settings.get("argv") or []
        record.update(argv0=os.path.basename(argv[0]) if argv else None,
                      model=next((argv[i + 1] for i, a in enumerate(argv[:-1]) if a in ("--model", "-m")), None),
                      runs=writer.runs, fallback=writer.fell_back)
    return out, record
