"""Store copy may claim nothing the shipped game does not have.

`check(texts, facts, claims)` reads every text of one locale's copy against the claim
vocabulary in core/reference/store-listing.yaml (`claims`): a term found in a text whose
backing is absent from the facts is a problem of severity `error`. Marketing superlatives
the vocabulary forbids outright (`backed_by: [none]`) are errors too; a few adjectives that
rate rather than describe are warnings. The check is mechanical and runs on every text that
reaches release, whoever wrote it - the Factory's writer, an agent, or a person.

A feature bullet also names its `source` fact; a bullet whose source is not in the facts, or
whose words share nothing with that fact's text, is an error: a bullet about nothing.
"""

import re

__all__ = ["check", "backed", "RATING_WORDS", "content_words"]

RATING_WORDS = ("addictive", "stunning", "amazing", "incredible", "ultimate", "epic",
                "awesome", "unforgettable", "breathtaking", "must-play")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "you", "your", "as", "is",
         "it", "for", "every", "can", "how", "with", "before", "out", "at", "by", "be", "that",
         "this", "into", "from", "when", "then", "than", "its", "are", "one", "each"}


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
