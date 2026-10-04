"""The copy held to what the build measured, not to what the design planned.

Three things the two 2026-10 validation listings got wrong, each a check here and each a
fact the store-listing step records for the writer and the judge
(docs/quality-gap-audit-2026-10.md I-23, WS-9):

    counts     "six courses" when twelve shipped. Every count the copy states before a
               counted noun (core/reference/store-listing.yaml `counts`) must equal what the
               content-sufficiency report of the listed build measured - units shipped,
               groups, climax units - or the modes the design's feature evaluation included.
               A count with no measured fact is refused where the run's tier holds
               quality-benchmark.yaml store_listing.copy_counts_match_build.
    controls   a controls line naming touch only, beside a build that also takes the mouse
               and the keyboard. Every device the design's MVP actions bind, and every one
               the play probe reported while the listing was captured, is named in each
               locale's controls text (`controls`), in that locale's words.
    locales    a required locale whose "description" was the in-game objective line. Every
               required locale carries a full description (`copy.full_description`), and a
               non-English text is grounded on its numbers and ids, not on English words it
               shares with the design.

Nothing here reads a game or a family id: the nouns, device words and bars are reference
data, and the values are the run's own reports.
"""

import os
import re

from wgflib import genre_models, paths
from wgflib.yamllite import YamlError, load_file

__all__ = ["BENCHMARK_PATH", "DEVICES", "store_bars", "resolve_tier", "writer_kind",
           "measured_counts", "feature_decisions", "probe_devices", "required_devices",
           "count_claims", "count_problems", "controls_problems", "full_description_problems",
           "generic_subtitle", "excluded_feature_claims", "numbers_in"]

BENCHMARK_PATH = os.path.join(paths.REFERENCE, "quality-benchmark.yaml")
DEVICES = ("touch", "mouse", "keyboard", "gamepad")
SOURCE = "content-sufficiency-report"
_TOKEN = re.compile(r"[^\W_]+(?:-[^\W_]+)*", re.UNICODE)
_SENTENCE = re.compile(r"[^.!?]+[.!?]", re.UNICODE)
_EN_NUMBERS = {w: n for n, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split())}
_EN_NUMBERS.update({"thirty": 30, "forty": 40, "fifty": 50, "hundred": 100})
# Russian number words decline (шесть, шести, шестью): matched by stem, longest first.
_RU_NUMBER_STEMS = (("двадцат", 20), ("девятнадцат", 19), ("восемнадцат", 18),
                    ("семнадцат", 17), ("шестнадцат", 16), ("пятнадцат", 15),
                    ("четырнадцат", 14), ("тринадцат", 13), ("двенадцат", 12),
                    ("одиннадцат", 11), ("десят", 10), ("девят", 9), ("восем", 8),
                    ("восьм", 8), ("шест", 6), ("пят", 5), ("четыр", 4))
_RU_NUMBER_WORDS = {"два": 2, "две": 2, "двух": 2, "двум": 2, "двумя": 2, "три": 3, "трёх": 3,
                    "трех": 3, "тремя": 3, "семь": 7, "семи": 7, "семью": 7}
# A count of a subset ("the last two courses") is not a count of the whole.
_SUBSET = ("last", "first", "next", "final", "other", "opening", "remaining", "later", "early",
           "top", "последн", "первы", "следующ", "остальн")
# A count followed by one of these counts something else ("ten gems per course").
_BREAK = {"per", "on", "in", "of", "each", "every", "across", "along", "at", "for", "from",
          "to", "with", "and", "or", "на", "в", "по", "из", "для", "с", "за", "и", "или",
          "каждой", "каждую", "каждом", "каждый"}


# -- the run's tier and its bars -------------------------------------------------------------

def load_benchmark(path=None):
    try:
        return load_file(path or BENCHMARK_PATH) or {}
    except (OSError, YamlError, ValueError):
        return {}


def store_bars(tier, benchmark=None):
    """{bar: value} of quality-benchmark.yaml `store_listing` stated at `tier`: what a
    listing of a run at that tier is held to. {} for a tier that states none."""
    benchmark = load_benchmark() if benchmark is None else benchmark
    out = {}
    for key, entry in ((benchmark or {}).get("store_listing") or {}).items():
        if isinstance(entry, dict) and tier and entry.get(tier) is not None:
            out[key] = entry[tier]
    return out


def resolve_tier(params, environment, design, strategy):
    """(tier, where) the listing is written at: the step's `with: quality_tier`, else the tier
    the run was started with (its quality snapshot), else the design's or the strategy's
    content tier; (None, why) when nothing states one."""
    from wgflib.workflow.quality import run_tier
    from wgf_design.content import quality_tier

    if (params or {}).get("quality_tier"):
        return str(params["quality_tier"]), "the step's with: quality_tier"
    taken = run_tier(environment)
    if taken:
        return taken, "the run's quality snapshot"
    return quality_tier(design, strategy)


def writer_kind(configured, tier, reference):
    """The writer that writes: `template` or `command`. `auto` takes the reference's
    `writer.by_tier` entry for the run's tier."""
    if configured != "auto":
        return configured
    table = (reference or {}).get("writer") or {}
    kind = (table.get("by_tier") or {}).get(tier) if tier else None
    return kind or table.get("default") or "template"


# -- measured facts ------------------------------------------------------------------------

def _dig(value, dotted):
    for part in str(dotted or "").split("."):
        if not part:
            continue
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _count(value, how):
    if how == "length":
        return len(value) if isinstance(value, (list, dict)) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def feature_decisions(design):
    """(included, excluded): the design's features the WS-5 evaluation included (or,
    unevaluated, tiered mvp or post-mvp), and those it deferred or cut, with the reason -
    copy may name the first and never the second."""
    included, excluded = [], []
    for feature in (design or {}).get("features") or []:
        if not isinstance(feature, dict) or not feature.get("id"):
            continue
        evaluation = feature.get("evaluation") if isinstance(feature.get("evaluation"), dict) else {}
        decision = evaluation.get("decision")
        entry = {"id": str(feature["id"]), "name": str(feature.get("name") or feature["id"])}
        if decision in ("later", "cut") or (decision is None and feature.get("tier") == "optional"):
            entry["decision"] = decision or "optional"
            if evaluation.get("reason"):
                entry["reason"] = str(evaluation["reason"])
            excluded.append(entry)
        else:
            included.append(entry)
    return included, excluded


def _kind_word(design, kind_from):
    for source in kind_from or ():
        if str(source).startswith("genre-models:"):
            block = genre_models.for_design(design) or {}
            word = _dig(block, source.split(":", 1)[1])
        else:
            word = _dig(design or {}, source)
        if isinstance(word, str) and word.strip():
            return word.strip().lower()
    return None


def measured_counts(report, design, reference, *, commits):
    """{source, counts: {fact: {value, kind, measured_by}}} from the content-sufficiency report
    when it measured one of `commits` (the listed build, or the development commit it sits
    on); None otherwise - a report of another build says nothing about this one. A check
    that was SKIPPED or BLOCKED measured nothing and gives no count."""
    if not isinstance(report, dict):
        return None
    commit = str(report.get("commit") or "")
    if not commit or not any(c and (commit.startswith(c) or c.startswith(commit))
                             for c in commits if c):
        return None
    checks = {c.get("id"): c for c in report.get("checks") or [] if isinstance(c, dict)}
    included, _excluded = feature_decisions(design)
    counts = {}
    for fact, spec in ((reference or {}).get("counts") or {}).items():
        spec = spec or {}
        by = spec.get("measured_by") or {}
        value, where = None, None
        if by.get("check"):
            check = checks.get(by["check"])
            if check is None or check.get("status") in ("SKIPPED", "BLOCKED"):
                continue
            value = _count(_dig(check.get("measured"), by.get("path")), by.get("count"))
            where = f"{SOURCE}#{by['check']}.measured.{by.get('path')}"
        elif by.get("design") == "features.included":
            pattern = re.compile(r"(?<![a-z])" + re.escape(str(by.get("match") or "")) + r"(?![a-z])", re.I)
            value = sum(1 for f in included if pattern.search(f["id"].replace("-", " "))
                        or pattern.search(f["name"]))
            where = "game-design#features (evaluation: include)"
        if value is None:
            continue
        counts[fact] = {"value": value, "kind": _kind_word(design, spec.get("kind_from")),
                        "measured_by": where}
    provenance = report.get("provenance") or {}
    return {"source": {"artifact_id": provenance.get("artifact_id"),
                       "content_hash": provenance.get("content_hash"),
                       "commit": commit, "quality_tier": report.get("quality_tier"),
                       "verdict": report.get("verdict")},
            "counts": counts}


def probe_devices(viewports):
    """{device: [action ids]} the play probe reported while the listing was captured: a
    pointer on a mobile viewport is touch, on a desktop one the mouse; a key is the keyboard."""
    out = {}
    for viewport in viewports or []:
        inputs = (viewport or {}).get("inputs") or {}
        pointer = "touch" if viewport.get("mobile") else "mouse"
        for kind, device in (("pointer", pointer), ("key", "keyboard")):
            for action in inputs.get(kind) or []:
                bucket = out.setdefault(device, [])
                if action not in bucket:
                    bucket.append(str(action))
    return out


def required_devices(facts):
    """The devices the controls text must name: those the design's MVP actions bind and
    those the probe reported, in DEVICES order."""
    controls = (facts or {}).get("controls") or {}
    probed = (facts or {}).get("probe_inputs") or {}
    return [d for d in DEVICES if controls.get(d) or probed.get(d)]


# -- reading a text ------------------------------------------------------------------------

def _number(token, locale):
    token = token.lower()
    if token.isdigit():
        return int(token)
    if token in _EN_NUMBERS:
        return _EN_NUMBERS[token]
    if (locale or "").startswith("ru") and re.fullmatch(r"[а-яё]+", token):
        if token in _RU_NUMBER_WORDS:
            return _RU_NUMBER_WORDS[token]
        for stem, value in _RU_NUMBER_STEMS:
            if token.startswith(stem) and len(token) <= len(stem) + 4:
                return value
    return None


def numbers_in(text, locale=None):
    """Every number `text` states, as digits or (English, Russian) number words."""
    out = set()
    for token in _TOKEN.findall(text or ""):
        for part in token.split("-"):
            value = _number(part, locale)
            if value is not None:
                out.add(value)
    return out


def _derived_stems(facts, locale):
    """The unit kind's word in `locale`, from the game's own strings: the stem shared by
    that locale's strings at the keys whose English names the kind ("Course {n}" /
    "Трасса {n}" -> "трасс")."""
    kind = str((facts or {}).get("content_unit_kind") or "").lower()
    if not kind or not locale or locale == "en":
        return ()
    singular = kind[:-1] if kind.endswith("s") else kind
    strings = (facts or {}).get("strings") or {}
    english, local = strings.get("en") or {}, strings.get(locale) or {}
    counts = {}
    for key, value in english.items():
        if re.search(r"(?<![a-z])" + re.escape(singular), str(value).lower()) and isinstance(local.get(key), str):
            for word in set(_TOKEN.findall(local[key].lower())):
                if len(word) >= 4:
                    counts[word[:5]] = counts.get(word[:5], 0) + 1
    if not counts:
        return ()
    best = max(counts.values())
    return tuple(stem for stem, n in counts.items() if n == best and n >= 2)


def _nouns(facts, counts_ref, locale):
    """{fact: (nouns...)} for `locale`: the reference's words, the design's own kind word for
    the fact (English), and the unit kind's word in the game's own strings."""
    language = (locale or "en").split("-")[0]
    measured = (((facts or {}).get("measured") or {}).get("counts") or {})
    out = {}
    for fact, spec in (counts_ref or {}).items():
        words = [str(w).split()[0].lower() for w in ((spec or {}).get("nouns") or {}).get(language) or []]
        if language == "en":
            kind = (measured.get(fact) or {}).get("kind") or (
                (facts or {}).get("content_unit_kind") if fact == "units" else None)
            if kind:
                words.append(kind.split()[0].lower())
        elif fact == "units":
            words.extend(_derived_stems(facts, locale))
        out[fact] = tuple(dict.fromkeys(w for w in words if w))
    return out


def _noun_fact(word, nouns, language):
    low = word.lower().split("-")[-1]
    for fact, words in nouns.items():
        for noun in words:
            stem = noun[:-1] if language == "en" and noun.endswith("s") and len(noun) > 4 else noun
            slack = 3 if language == "en" else 5
            if low == noun or (low.startswith(stem) and len(low) - len(stem) <= slack):
                return fact
    return None


def count_claims(text, facts, counts_ref, locale=None):
    """[(phrase, fact, value)]: every count of a counted noun `text` states."""
    language = (locale or "en").split("-")[0]
    nouns = _nouns(facts, counts_ref, locale)
    if not any(nouns.values()):
        return []
    tokens = _TOKEN.findall(text or "")
    out = []
    for index, token in enumerate(tokens):
        head, _, tail = token.partition("-")
        value = _number(head, locale) if tail else _number(token, locale)
        if value is None:
            continue
        before = [t.lower() for t in tokens[max(0, index - 2):index]]
        if any(b.startswith(_SUBSET) for b in before):
            continue
        # The noun phrase after the number, up to a preposition: its head - the last counted
        # noun in it - is what is counted ("six floating-island courses" counts courses).
        window = ([tail] if tail else []) + tokens[index + 1:index + 4]
        head_fact, head_at = None, None
        for offset, word in enumerate(window):
            low = word.lower()
            if low in _BREAK or low.startswith(_SUBSET):
                break
            fact = _noun_fact(word, nouns, language)
            if fact:
                head_fact, head_at = fact, offset
        if head_fact:
            span = tokens[index:index + head_at + (1 if tail else 2)]
            out.append((" ".join(span), head_fact, value))
    return out


def _texts(copy):
    out = []
    for field, value in (copy or {}).items():
        if isinstance(value, str):
            out.append((field, value))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                text = item.get("text") if isinstance(item, dict) else item
                if isinstance(text, str):
                    out.append((f"{field}[{index}]", text))
    return out


def count_problems(copy, facts, counts_ref, *, locale=None, where="copy", strict=None):
    """[problem] for every count `copy` states that is not the build's measured count:
    `count-mismatch` (error) when the build measured another value, `unmeasured-count` when
    nothing measured it (error when `strict`, the tier's copy_counts_match_build; else a
    warning). `strict` None reads the facts' own quality bars."""
    if strict is None:
        strict = bool((((facts or {}).get("quality") or {}).get("bars") or {}).get("copy_counts_match_build"))
    measured = (((facts or {}).get("measured") or {}).get("counts") or {})
    problems = []
    for field, text in _texts(copy):
        for phrase, fact, value in count_claims(text, facts, counts_ref, locale):
            entry = measured.get(fact)
            label = f"{where} {field}" + (f" ({locale})" if locale else "")
            if entry is not None and entry.get("value") == value:
                continue
            if entry is not None:
                problems.append({
                    "code": "count-mismatch", "severity": "error", "subject": field,
                    "message": f"{label} says {phrase!r}, but the build has {entry['value']} "
                               f"{entry.get('kind') or fact} ({entry.get('measured_by')})"})
            else:
                problems.append({
                    "code": "unmeasured-count", "severity": "error" if strict else "warning",
                    "subject": field,
                    "message": f"{label} says {phrase!r}, a count of {fact} nothing measured on "
                               f"this build (no {SOURCE} of the listed commit counts it)"})
    return problems


def excluded_feature_claims(copy, facts, *, locale=None, where="copy"):
    """[problem] for a feature the design's evaluation deferred or cut that the copy names
    (by its name, in any locale: a name is an id the build does not ship)."""
    problems = []
    for feature in (facts or {}).get("features_excluded") or []:
        name = str(feature.get("name") or "").strip()
        if len(name) < 4:
            continue
        pattern = re.compile(r"(?<![\w])" + re.escape(name).replace(r"\ ", r"[\s-]+") + r"(?![\w])", re.I)
        for field, text in _texts(copy):
            if pattern.search(text):
                problems.append({
                    "code": "excluded-feature", "severity": "error", "subject": field,
                    "message": f"{where} {field}" + (f" ({locale})" if locale else "")
                               + f" names {name!r}, which the design's feature evaluation "
                                 f"{feature.get('decision')}" + (f": {feature['reason']}" if feature.get("reason") else "")})
                break
    return problems


def controls_problems(copy, facts, controls_ref, locale=None):
    """(missing devices, checkable): the devices the build accepts that the locale's
    controls text does not name. Not checkable when the reference has no words for the
    locale's language - reported, never passed."""
    language = (locale or "en").split("-")[0]
    devices = required_devices(facts)
    if not devices:
        return [], True
    words = (controls_ref or {}).get("devices") or {}
    if not all(language in (words.get(d) or {}) for d in devices):
        return [], False
    text = " ".join(str((copy or {}).get(f) or "") for f in ("controls",)).lower()
    tokens = _TOKEN.findall(text)
    missing = []
    for device in devices:
        stems = [str(w).lower() for w in words[device][language]]
        if not any(t == s or t.startswith(s) for t in tokens for s in stems):
            missing.append(device)
    return missing, True


def full_description_problems(copy, reference, locale=None):
    """[str]: what keeps `copy` from being a full description in its locale - an empty
    required text, a long description under the canonical minimum, of fewer sentences than
    the reference asks, or the short description again."""
    bounds = (reference or {}).get("copy") or {}
    spec = bounds.get("full_description") or {}
    problems = []
    if copy is None:
        return ["no copy"]
    for field in spec.get("fields") or ("title", "short_description", "long_description"):
        if not str(copy.get(field) or "").strip():
            problems.append(f"{field} is empty")
    long_text = re.sub(r"\s+", " ", str(copy.get("long_description") or "")).strip()
    minimum = (bounds.get("long_description") or {}).get("min_chars")
    if long_text and minimum is not None and len(long_text) < minimum:
        problems.append(f"long_description is {len(long_text)} chars, under {minimum}")
    sentences = [s for s in _SENTENCE.findall(long_text + ("" if long_text[-1:] in ".!?" else "."))
                 if s.strip()] if long_text else []
    if long_text and spec.get("min_sentences") and len(sentences) < spec["min_sentences"]:
        problems.append(f"long_description is {len(sentences)} sentence(s), under {spec['min_sentences']}")
    short = re.sub(r"\s+", " ", str(copy.get("short_description") or "")).strip()
    if long_text and short and long_text.rstrip(".!? ").lower() == short.rstrip(".!? ").lower():
        problems.append("long_description is the short description again")
    return problems


def generic_subtitle(copy, facts, reference, locale=None, vocabulary_labels=()):
    """True when the subtitle says nothing about this game: every word in it is a generic
    word, a genre label, a tag or a category."""
    subtitle = str((copy or {}).get("subtitle") or "").strip()
    if not subtitle:
        return False
    language = (locale or "en").split("-")[0]
    generic = (((reference or {}).get("copy") or {}).get("subtitle_generic_words") or {})
    words = {str(w).lower() for w in (generic.get(language) or []) + (generic.get("en") or [])}
    for value in list((copy or {}).get("tags") or []) + list((copy or {}).get("categories") or []) \
            + list((facts or {}).get("genre") or []) + list(vocabulary_labels or ()):
        words.update(t.lower() for t in _TOKEN.findall(str(value).replace("-", " ")))
    tokens = [t.lower() for t in _TOKEN.findall(subtitle.replace("-", " "))]
    return bool(tokens) and all(t in words for t in tokens)
