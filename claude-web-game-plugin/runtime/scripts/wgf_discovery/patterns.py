"""Cross-game patterns and benchmarks, counted - never inferred.

For each facet pair the analysis configuration names (core/reference/research-analysis.yaml),
and each value `a` of the first facet: of the games coded a, take those also coded on the
second facet at all (the denominator - an uncoded game is not a "no"); for each value `b` they
hold, the games holding it are the numerator. A pattern is reported when the numerator and
denominator reach the configured minimums, as a derived claim carrying both, the member
games, the exceptions and the games in scope but uncoded.

Genre and theme values count up their tree: a game coded match-3 is also a match game and a
puzzle game, which is what lets a family-level pattern exist without a family-level coding.

Patterns are descriptive. "5 of 6 games coded runner offer a rewarded continue" says what the
corpus holds; what adopting it might do is a separate hypothesis claim, made only by an
opportunity that adopts it.

Benchmarks are the same discipline for numbers: per genre node, the median and range of a
measured facet over the teardown games that measured it, with the games named.
"""

import re
import statistics

from .evidence import Gap

__all__ = ["game_values", "extract_patterns", "extract_benchmarks", "facet_summaries",
           "ANALYSIS_SECTIONS"]

# Report sections (research-report `analyses`) and the facets each is a view of.
ANALYSIS_SECTIONS = {
    "genre": ["genre", "descriptor"],
    "gameplay": ["gameplay_steps", "controls", "decision_type", "skill", "randomness"],
    "mechanics": ["mechanics"],
    "theme": ["theme", "setting"],
    "fantasy": ["player_fantasy", "emotional_fantasy"],
    "art": ["art_dimension", "art_rendering", "art_tone", "art_palette", "camera", "animation"],
    "audience": ["audience_type", "intent", "device", "age_band"],
    "session_retention": ["run_seconds", "retry_seconds", "first_failure_seconds",
                          "progression", "difficulty_shape", "difficulty_axes",
                          "retention_hooks"],
    "monetization": ["ad_formats", "ad_triggers", "interstitial_interval_seconds"],
    "ux": ["tutorial", "time_to_first_play_seconds", "time_to_first_reward_seconds",
           "taps_before_play"],
    "production": ["physics_engine", "networking", "unique_assets", "bundle_mb",
                   "orientation"],
}


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")


def game_values(game, facet, vocabulary, cells=None):
    """The set of values `game` holds on `facet`, with the claims they rest on:
    ({value, ...}, [claim ids]). Empty when the game is not coded on it."""
    if facet == "platform":
        values = set(game.platforms)
        claims = [entry["claim"] for entry in game.listings]
        return values, claims
    if facet == "saturation":
        values, claims = set(), []
        genre = game.value("genre")
        for platform in game.platforms:
            cell = (cells or {}).get(f"{genre}@{platform}")
            if cell and cell.saturation.get("status") in ("under-supplied", "balanced",
                                                          "over-supplied"):
                values.add(cell.saturation["status"])
                claims.extend(cell.saturation.get("claim_refs") or [])
        return values, claims
    if facet == "session_band":
        entry = game.facets.get("run_seconds")
        if not entry:
            return set(), []
        return {vocabulary.session_band(entry["value"])}, list(entry["claim_refs"])
    entry = game.facets.get(facet)
    if not entry:
        return set(), []
    value = entry["value"]
    values = set(value) if isinstance(value, list) else {value}
    if facet == "genre":
        values = {node for v in values for node in vocabulary.lineage(v)}
    elif facet == "theme":
        expanded = set()
        for v in values:
            node = v
            while node and node not in expanded:
                expanded.add(node)
                node = vocabulary.entry("theme", node).get("parent")
        values = expanded
    if vocabulary.facet(facet) and vocabulary.facet(facet)["kind"] == "number":
        return set(), []
    return values, list(entry["claim_refs"])


def _narrower(vocabulary, facet, child, parent):
    if facet == "genre":
        return vocabulary.is_within(child, parent)
    node = vocabulary.entry("theme", child).get("parent")
    while node:
        if node == parent:
            return True
        node = vocabulary.entry("theme", node).get("parent")
    return False


def extract_patterns(corpus, cells, book):
    """Returns (patterns, gaps)."""
    vocabulary, config = corpus.vocabulary, corpus.config
    games = corpus.sorted_games()
    patterns, gaps = [], []
    thin = 0
    for pair in config.pairs:
        fa, fb = pair["a"], pair["b"]
        held_a = {g.id: game_values(g, fa, vocabulary, cells) for g in games}
        held_b = {g.id: game_values(g, fb, vocabulary, cells) for g in games}
        values_a = sorted({v for vals, _ in held_a.values() for v in vals}, key=str)
        scopes = {a: frozenset(g.id for g in games if a in held_a[g.id][0]) for a in values_a}
        for a in values_a:
            scope = sorted(scopes[a])
            # A broader genre or theme holding exactly the games of a narrower one would
            # restate its patterns under another name: only the narrowest is counted.
            if fa in ("genre", "theme") and any(
                    other != a and scopes[other] == scopes[a] and _narrower(vocabulary, fa,
                                                                            other, a)
                    for other in values_a):
                continue
            known = [gid for gid in scope if held_b[gid][0]]
            unknown = [gid for gid in scope if not held_b[gid][0]]
            if len(known) < config.min_denominator:
                if len(scope) >= config.min_denominator:
                    thin += 1
                continue
            for b in sorted({v for gid in known for v in held_b[gid][0]}, key=str):
                if fa == fb and a == b:
                    continue
                if fa == "genre" and fb == "genre":
                    continue
                members = [gid for gid in known if b in held_b[gid][0]]
                if len(members) < config.min_support:
                    continue
                exceptions = [gid for gid in known if gid not in members]
                # A facet value implied by the conditioning value is not a pattern: every
                # game coded match-3 is a puzzle game by definition.
                if len(members) == len(known) and fa in ("genre", "theme") and \
                        fb == fa:
                    continue
                pid = f"pat-{pair['id']}-{_slug(a)}-{_slug(b)}"
                la, lb = vocabulary.label(fa, a), vocabulary.label(fb, b)
                frame = (f"games in the corpus coded {fa}={a} and coded on {fb} "
                         f"({len(known)} of {len(scope)} in scope)")
                parents = sorted({c for gid in known for c in held_a[gid][1] + held_b[gid][1]})
                fixture = any(corpus.games[gid].fixture for gid in members)
                statement = (f"{len(members)} of {len(known)} games coded {la} ({fa}) "
                             f"have {lb} ({fb}): {', '.join(corpus.games[g].name for g in members[:6])}"
                             + (f"; not {', '.join(corpus.games[g].name for g in exceptions[:4])}"
                                if exceptions else "")
                             + (f"; {len(unknown)} more not coded on {fb}" if unknown else "")
                             + ". Descriptive: co-occurrence in this corpus, not a cause.")
                subject = {"pattern": pid, "facet": fb}
                if fa == "genre":
                    subject["genre"] = a
                if fa == "theme":
                    subject["theme"] = a
                claim = book.derived(
                    ("pattern", pid, frame), statement, parents, subject,
                    tags=["pattern", pair["kind"]] + (["fixture"] if fixture else []),
                    support={"numerator": len(members), "denominator": len(known),
                             "members": members, "exceptions": exceptions,
                             "unknown": unknown, "frame": frame})
                patterns.append({
                    "id": pid, "pair": pair["id"], "kind": pair["kind"],
                    "statement": statement,
                    "a": {"facet": fa, "value": a}, "b": {"facet": fb, "value": b},
                    "numerator": len(members), "denominator": len(known),
                    "prevalence": round(len(members) / len(known), 4),
                    "members": members, "exceptions": exceptions, "unknown": unknown,
                    "claim": claim,
                })
    if thin:
        gaps.append(Gap("insufficient-support",
                        f"{thin} facet value(s) had games in scope but fewer than "
                        f"{config.min_denominator} coded on the paired facet; no pattern is "
                        f"stated for them"))
    if not patterns:
        gaps.append(Gap("insufficient-support",
                        "no cross-game pattern reached the minimum support "
                        f"({config.min_support} of at least {config.min_denominator} coded "
                        f"games); the corpus needs more coded games"))
    patterns.sort(key=lambda p: (p["pair"], -p["prevalence"], p["id"]))
    return patterns, gaps


def extract_benchmarks(corpus, book):
    vocabulary, config = corpus.vocabulary, corpus.config
    games = corpus.sorted_games()
    out = []
    nodes = sorted({n for g in games if g.value("genre")
                    for n in vocabulary.lineage(g.value("genre"))})
    for facet in config.benchmarks:
        unit = vocabulary.facet(facet)["unit"]
        for node in nodes:
            scope = [g for g in games if g.depth == "teardown" and g.value("genre")
                     and vocabulary.is_within(g.value("genre"), node)]
            coded = [g for g in scope if facet in g.facets]
            if len(coded) < config.min_support:
                continue
            values = [float(g.facets[facet]["value"]) for g in coded]
            median = round(statistics.median(values), 2)
            members = [g.id for g in coded]
            unknown = [g.id for g in scope if g not in coded]
            label = vocabulary.genres[node]["label"]
            frame = f"teardown games coded {label} that measured {facet}"
            claim = book.derived(
                ("benchmark", node, facet, frame),
                f"Across {len(coded)} {label} games measured ({', '.join(g.name for g in coded[:6])}), "
                f"{vocabulary.facet(facet)['label'].lower()} has median {median:g} {unit} "
                f"(range {min(values):g}-{max(values):g}).",
                sorted({c for g in coded for c in g.facets[facet]["claim_refs"]}),
                {"genre": node, "facet": facet},
                tags=["benchmark"] + (["fixture"] if any(g.fixture for g in coded) else []),
                support={"numerator": len(coded), "denominator": len(coded),
                         "members": members, "unknown": unknown, "frame": frame})
            out.append({"id": f"bm-{_slug(node)}-{_slug(facet)}", "genre": node,
                        "facet": facet, "unit": unit, "median": median,
                        "min": min(values), "max": max(values), "n": len(coded),
                        "games": members, "claim": claim})
    return out


def facet_summaries(corpus, cells):
    vocabulary = corpus.vocabulary
    games = corpus.sorted_games()
    sections = {}
    for section, facets in ANALYSIS_SECTIONS.items():
        rows = []
        for facet in facets:
            spec = vocabulary.facet(facet)
            if spec is None:
                continue
            in_scope = games if facet in ("genre", "descriptor") else \
                [g for g in games if g.depth == "teardown"]
            coded = [g for g in in_scope if facet in g.facets]
            row = {"facet": facet, "games_in_scope": len(in_scope), "coded": len(coded),
                   "values": []}
            if spec["kind"] == "number":
                values = [float(g.facets[facet]["value"]) for g in coded]
                for g in coded:
                    row["values"].append({"value": g.facets[facet]["value"], "games": [g.id]})
                if values:
                    row["benchmark"] = {"median": round(statistics.median(values), 2),
                                        "min": min(values), "max": max(values),
                                        "n": len(values), "unit": spec["unit"]}
            else:
                holders = {}
                for g in coded:
                    raw = g.facets[facet]["value"]
                    for value in (raw if isinstance(raw, list) else [raw]):
                        holders.setdefault(value, []).append(g.id)
                for value in sorted(holders, key=lambda v: (-len(holders[v]), str(v))):
                    row["values"].append({"value": value,
                                          "label": vocabulary.label(facet, value),
                                          "games": holders[value]})
            rows.append(row)
        sections[section] = rows
    return sections
