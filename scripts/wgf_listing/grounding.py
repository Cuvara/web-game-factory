"""Store copy may claim nothing the shipped game does not have.

`check(texts, facts, claims)` reads every text of one locale's copy against the claim
vocabulary in core/reference/store-listing.yaml (`claims`): a term found in a text whose
backing is absent from the facts is a problem of severity `error`. Marketing superlatives
the vocabulary forbids outright (`backed_by: [none]`) are errors too; a few adjectives that
rate rather than describe are warnings. The check is mechanical and runs on every text that
reaches release, whoever wrote it - the Factory's writer, an agent, or a person.

A feature bullet also names its `source` fact; a bullet whose source is not in the facts, or
whose words share nothing with that fact's text, is an error: a bullet about nothing.

A text the build contradicts is an error too (`contradicted-claim`): a count of content
units other than the one the build ships ("six courses" when the build names twelve), or
"no buttons" when the controls name one. The facts carry the build's own figures where it
has them (facts.py), so a design figure the build outgrew is refused here.
"""

import re

__all__ = ["check", "backed", "RATING_WORDS", "content_words", "contradictions"]

RATING_WORDS = ("addictive", "stunning", "amazing", "incredible", "ultimate", "epic",
                "awesome", "unforgettable", "breathtaking", "must-play")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "you", "your", "as", "is",
         "it", "for", "every", "can", "how", "with", "before", "out", "at", "by", "be", "that",
         "this", "into", "from", "when", "then", "than", "its", "are", "one", "each"}


# Number words, by locale, for counting claims. Russian is matched by stem, since the
# number word declines (шесть, шести, шестью).
_EN_NUMBERS = {w: n for n, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split())}
_RU_NUMBER_STEMS = (("двадцат", 20), ("девятнадцат", 19), ("восемнадцат", 18), ("семнадцат", 17),
                    ("шестнадцат", 16), ("пятнадцат", 15), ("четырнадцат", 14), ("тринадцат", 13),
                    ("двенадцат", 12), ("одиннадцат", 11), ("десят", 10), ("девят", 9),
                    ("восем", 8), ("восьм", 8), ("сем", 7), ("шест", 6), ("пят", 5),
                    ("четыр", 4), ("три", 3), ("трёх", 3), ("трех", 3), ("дв", 2))
# A count of a subset ("the last two courses") is not a count of the whole.
_SUBSET = {"last", "first", "next", "final", "other", "opening", "remaining", "later", "early",
           "последн", "первы", "первых", "следующ", "остальн"}
# A count followed by a preposition counts something else ("ten gems per course").
_BREAK = {"per", "on", "in", "of", "each", "every", "across", "along", "at", "for", "from", "to",
          "with", "and", "or", "на", "в", "по", "из", "для", "с", "за", "и", "или", "каждой",
          "каждую", "каждом"}
_TOKEN = re.compile(r"[^\W_]+(?:-[^\W_]+)*", re.UNICODE)
_NO_BUTTONS = re.compile(r"(?<![a-z])no(?:\s+on-screen)?\s+buttons?(?![a-z])|без\s+кнопок|нет\s+кнопок", re.I)


def _number(token, locale):
    token = token.lower()
    if token.isdigit():
        return int(token)
    if token in _EN_NUMBERS:
        return _EN_NUMBERS[token]
    if (locale or "").startswith("ru") and re.fullmatch(r"[а-яё]+", token):
        for stem, value in _RU_NUMBER_STEMS:
            if token.startswith(stem) and len(token) <= len(stem) + 4 and not (
                    stem == "дв" and token not in ("два", "две", "двух", "двум", "двумя")) and not (
                    stem == "сем" and token not in ("семь", "семи", "семью")) and not (
                    stem == "три" and token not in ("три",)):
                return value
    return None


def _unit_stems(facts, locale):
    """How the unit kind is written in `locale`: the English forms, else the most common
    stem in the game's own strings of that locale at the keys whose English names the
    kind (en "Course {n}" / ru "Трасса {n}" -> "трасс")."""
    kind = str(facts.get("content_unit_kind") or "").lower()
    if not kind:
        return ()
    singular = kind[:-1] if kind.endswith("s") else kind
    if not locale or locale == "en":
        return (singular[:max(4, len(singular) - 1)],)
    strings = facts.get("strings") or {}
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


def contradictions(text, facts, locale=None):
    """[(phrase, why)] for what `text` says that the build contradicts."""
    out = []
    units = facts.get("content_units")
    stems = _unit_stems(facts, locale) if isinstance(units, int) and not isinstance(units, bool) else ()
    if stems:
        tokens = _TOKEN.findall(text or "")
        for index, token in enumerate(tokens):
            value = _number(token, locale)
            if value is None:
                continue
            before = [t.lower() for t in tokens[max(0, index - 2):index]]
            if any(b.startswith(tuple(_SUBSET)) for b in before):
                continue
            window = tokens[index + 1:index + 4]
            for offset, word in enumerate(window):
                low = word.lower()
                if low in _BREAK or low.startswith(tuple(_SUBSET)):
                    break
                if any(low.startswith(stem) or low.split("-")[-1].startswith(stem) for stem in stems):
                    if value != units:
                        phrase = " ".join(tokens[index:index + offset + 2])
                        out.append((phrase, f"the build has {units} {facts.get('content_unit_kind')}"
                                            f" ({(facts.get('sources') or {}).get('content_units', 'facts')})"))
                    break
    controls = facts.get("controls") or {}
    named = " ".join(" ".join(v) if isinstance(v, list) else str(v or "") for v in controls.values()).lower()
    match = _NO_BUTTONS.search(text or "")
    if match and ("button" in named or "кнопк" in named):
        out.append((match.group(0), "the controls name a button"))
    return out


def content_words(text):
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) > 2}


def _term_pattern(term):
    escaped = re.escape(term.lower()).replace(r"\ ", r"[\s-]+")
    return re.compile(r"(?<![a-z0-9])" + escaped + r"(?![a-z0-9])", re.I)


def _feature_text(facts):
    parts = []
    for key in ("mechanics", "features"):
        for entry in facts.get(key) or []:
            parts.append(" ".join(str(entry.get(k) or "") for k in ("id", "name", "description")))
    return " ".join(parts).lower()


def backed(backing, facts):
    """Whether one `backed_by` entry holds for `facts`."""
    if backing == "none":
        return False
    kind, _, rest = str(backing).partition(":")
    if kind == "sdk":
        return rest in (facts.get("capabilities") or [])
    if kind == "engine":
        return (facts.get("engine") or {}).get("dimension") == rest
    if kind == "feature":
        return rest.lower() in _feature_text(facts)
    if kind == "design":
        if rest == "endless":
            return bool(facts.get("endless"))
        if rest == "offline":
            return False  # nothing in the run's artifacts observes offline play
        if rest == "scope.content_units":
            return isinstance(facts.get("content_units"), int) and facts["content_units"] > 1
        if rest.startswith("build_spec.controls.actions."):
            device = rest.rsplit(".", 1)[-1]
            return bool((facts.get("controls") or {}).get(device))
        return bool(facts.get(rest.split(".")[-1]))
    return False


def check(texts, facts, claims, *, locale=None, where="copy"):
    """[problem] for the texts of one locale: {"title", "short_description",
    "long_description", "features": [{"text", "source"}], "promo": [...], ...}."""
    problems = []
    joined = []
    for field, value in (texts or {}).items():
        if isinstance(value, str):
            joined.append((field, value))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, str):
                    joined.append((f"{field}[{index}]", item))
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    joined.append((f"{field}[{index}]", item["text"]))
    for claim in claims or []:
        # Longest first, so the most specific phrase is the one reported.
        terms = sorted((t for t in claim.get("terms") or [] if isinstance(t, str)), key=len, reverse=True)
        backings = [b for b in claim.get("backed_by") or [] if isinstance(b, str)]
        holds = any(backed(b, facts) for b in backings) if backings else False
        if holds:
            continue
        for field, text in joined:
            hit = next((t for t in terms if _term_pattern(t).search(text)), None)
            if hit is None:
                continue
            forbidden = backings == ["none"]
            problems.append({
                "code": "unbacked-claim" if not forbidden else "forbidden-claim",
                "severity": "error",
                "message": (f"{where} {field}" + (f" ({locale})" if locale else "")
                            + f" says {hit!r}, which "
                            + ("store copy may never claim" if forbidden else
                               f"nothing in the run's artifacts backs (claim {claim.get('id')}: "
                               f"needs {' or '.join(backings) or 'evidence'})")),
                "subject": field})
    for field, text in joined:
        for phrase, why in contradictions(text, facts, locale):
            problems.append({"code": "contradicted-claim", "severity": "error",
                             "message": f"{where} {field}" + (f" ({locale})" if locale else "")
                                        + f" says {phrase!r}, which the build contradicts: {why}",
                             "subject": field})
    for field, text in joined:
        for word in RATING_WORDS:
            if _term_pattern(word).search(text):
                problems.append({"code": "rating-word", "severity": "warning",
                                 "message": f"{where} {field} rates the game ({word!r}) instead "
                                            f"of describing it", "subject": field})
                break
    # Every feature bullet rests on a fact it shares words with.
    sources = facts.get("sources") or {}
    fact_texts = {}
    for key in ("mechanics", "features"):
        for entry in facts.get(key) or []:
            fact_texts[f"{key[:-1] if key != 'mechanics' else 'mechanic'}:{entry.get('id')}"] = \
                " ".join(str(entry.get(k) or "") for k in ("name", "description"))
    for locale_id, values in (facts.get("strings") or {}).items():
        for key, value in (values or {}).items():
            fact_texts[f"string:{locale_id}:{key}"] = value
    for simple in ("objective", "core_loop", "concept", "controls:summary", "win", "lose",
                   "visual_style"):
        value = facts.get(simple.split(":")[0])
        if isinstance(value, dict):
            value = value.get("summary")
        if isinstance(value, str):
            fact_texts[simple] = value
    for index, bullet in enumerate((texts or {}).get("features") or []):
        if not isinstance(bullet, dict):
            continue
        source = bullet.get("source")
        text = bullet.get("text") or ""
        if source not in sources and source not in fact_texts:
            problems.append({"code": "bullet-without-source", "severity": "error",
                             "message": f"feature bullet {index} names source {source!r}, which "
                                        f"is not a fact of this build", "subject": f"features[{index}]"})
            continue
        reference = fact_texts.get(source, "")
        if reference and not (content_words(text) & content_words(reference)):
            problems.append({"code": "bullet-unrelated", "severity": "error",
                             "message": f"feature bullet {index} shares no word with its source "
                                        f"{source!r}", "subject": f"features[{index}]"})
    return problems
