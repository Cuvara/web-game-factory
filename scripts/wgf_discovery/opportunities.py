"""The opportunity space: several evidence-backed opportunities per scan, not one pick.

Five generators, each a rule over the corpus, its market cells and its patterns
(core/reference/research-analysis.yaml names which run):

    proven-core-new-axis  a genre node players demonstrably play (demand observed) whose
                          teardown games share a core - with one axis (theme, tone,
                          rendering, fantasy) changed to a value proven, with demand, in
                          another genre and absent from every coded game of this one
    supply-gap            a cell whose demand share exceeds its supply share (both observed)
    pattern-transfer      a pattern prevalent in one genre's games and absent from every coded
                          game of another genre with observed demand
    portal-difference     a genre node in a popularity list on one portal, absent from a
                          popularity list on another that is scoped to include it
    capability-screen     every capability-catalog shape, screened against the portals as
                          before - what the Factory knows how to build

A corpus generator refuses to propose anything whose basis does not rest on an observation:
low supply alone, or a hypothesis alone, never becomes an opportunity. Every opportunity
carries a thesis - a hypothesis claim, confidence <= 0.6 - and the claims it rests on.

Buildability is checked last, against the capability catalog: an opportunity no entry can
build is kept, status `capability-gap`, with what is missing. It is never discarded.
"""

import hashlib
import statistics
from collections import Counter

from .analysis import (ACTED_ON, _idea_rank, archetype_vocabulary, brief_terms,
                       idea_dimension, words_of)

__all__ = ["generate", "rank", "CELL_FACETS"]

CONFIDENCE_THESIS = 0.35
CONFIDENCE_EFFECT = 0.3
# What may transfer between genres: how a game keeps, rewards and monetizes players. A core
# mechanic does not transfer - moving one changes what genre the game is.
TRANSFER_KINDS = ("retention", "progression", "monetization", "ux", "session")
# What an opportunity adopts from its own genre's games: the same kinds.
ADOPT_KINDS = TRANSFER_KINDS
ADOPT_MIN_PREVALENCE = 0.5
ORIGIN_RANK = {"proven-core-new-axis": 0, "supply-gap": 0, "pattern-transfer": 0,
               "portal-difference": 0, "capability-screen": 1}

# opportunity.research.cell facets, in schema order, and the game facet each reads.
CELL_FACETS = ["genre", "family", "mechanics", "gameplay_steps", "core_loop", "controls",
               "theme", "setting", "player_fantasy", "emotional_fantasy", "art_dimension",
               "art_rendering", "art_tone", "art_palette", "camera", "session_band",
               "progression", "difficulty_shape", "retention_hooks"]
GAME_FACET = {"mechanics": "mechanics", "gameplay_steps": "gameplay_steps",
              "controls": "controls", "theme": "theme", "setting": "setting",
              "player_fantasy": "player_fantasy", "emotional_fantasy": "emotional_fantasy",
              "art_dimension": "art_dimension", "art_rendering": "art_rendering",
              "art_tone": "art_tone", "art_palette": "art_palette", "camera": "camera",
              "progression": "progression", "difficulty_shape": "difficulty_shape",
              "retention_hooks": "retention_hooks"}
COST = ("xs", "s", "m", "l", "xl")


def _unknown(reason):
    return {"value": None, "tier": "unknown", "source": "unknown", "reason": reason}


class Space:
    """Everything the generators read, and the book they write claims to."""

    def __init__(self, *, corpus, cells, patterns, benchmarks, candidates, views, book,
                 report_key, scope, backlog=()):
        self.corpus = corpus
        self.vocabulary = corpus.vocabulary
        self.config = corpus.config
        self.cells = cells
        self.patterns = patterns
        self.benchmarks = benchmarks
        self.candidates = candidates
        self.views = views
        self.book = book
        self.report_key = report_key
        self.scope = scope
        self.games = corpus.games
        # Opportunities somebody already acted on (analysis.ACTED_ON): ids are stable across
        # scans, so a proposal already scored, shortlisted or rejected is recognised.
        self.acted_on = {opp.get("id"): opp.get("state") for opp in backlog or ()
                         if opp.get("state") in ACTED_ON}
        popular = {gid for f in corpus.frames.values() if f["list_kind"] == "popularity"
                   for gid in f["titles"]}
        self.demand_listed = popular

    # -- lookups ----------------------------------------------------------------------------

    def games_in(self, node, teardown_only=True):
        out = []
        for game in self.corpus.sorted_games():
            genre = game.value("genre")
            if genre and self.vocabulary.is_within(genre, node) and \
                    (game.depth == "teardown" or not teardown_only):
                out.append(game)
        return out

    def coded_nodes(self, teardown_only=True):
        """Genre nodes some game is coded in directly - not their ancestors, which would
        repeat the same games under a broader name."""
        return sorted({g.value("genre") for g in self.corpus.sorted_games()
                       if g.value("genre") and (g.depth == "teardown" or not teardown_only)})

    def demand_cells(self, node):
        return [c for c in self.cells.values() if c.genre == node and c.demand_observed]

    def candidate_for(self, node):
        """The capability-catalog candidate whose genre node covers `node` (deepest wins)."""
        line = self.vocabulary.lineage(node)
        best, best_rank = None, None
        for candidate in self.candidates:
            covered = candidate["_archetype"].get("genre_node")
            if covered in line:
                rank = line.index(covered)
                if best is None or rank < best_rank or (rank == best_rank and
                                                       candidate["id"] < best["id"]):
                    best, best_rank = candidate, rank
        return best

    def tagged(self, cid, tag):
        return any(tag in (self.book.claims[c].get("tags") or [])
                   for c in self.book.closure([cid]))

    @staticmethod
    def opportunity_id(*parts):
        """Stable across scans: the same proposal (generator, genre node and what makes it
        that proposal) is the same opportunity whatever day or corpus found it, so a pinned
        `select` survives a later scan and the backlog holds each proposal once."""
        key = ":".join(str(p) for p in parts)
        return "opp-" + hashlib.sha256(key.encode()).hexdigest()[:8]

    # -- facet values -----------------------------------------------------------------------

    def from_games(self, games, facet):
        coded = [g for g in games if facet in g.facets]
        if not coded:
            return None
        kind = self.vocabulary.facet(facet)["kind"]
        counts = Counter()
        for g in coded:
            raw = g.facets[facet]["value"]
            for v in (raw if isinstance(raw, list) else [raw]):
                counts[v] += 1
        if kind == "many":
            value = sorted(v for v, n in counts.items() if n * 2 >= len(coded))
            if not value:
                value = [counts.most_common(1)[0][0]]
        else:
            top = max(counts.values())
            value = sorted(v for v, n in counts.items() if n == top)[0]
        refs = sorted({c for g in coded for c in g.facets[facet]["claim_refs"]})
        labels = value if isinstance(value, list) else [value]
        return {"value": value,
                "label": ", ".join(self.vocabulary.label(facet, v) for v in labels)
                + f" ({len(coded)} coded game(s))",
                "tier": "derived", "source": "corpus", "claim_refs": refs[:12]}


def _cell(space, node, games, candidate, overrides, estimate_claim):
    vocabulary = space.vocabulary
    entry = candidate["_archetype"] if candidate else None
    cell = {}
    genre_refs = sorted({c for g in space.games_in(node, teardown_only=False)
                         for c in g.facets.get("genre", {}).get("claim_refs", [])})
    if genre_refs:
        cell["genre"] = {"value": node, "label": vocabulary.genres[node]["label"],
                         "tier": "derived", "source": "corpus", "claim_refs": genre_refs[:12]}
    elif entry:
        cell["genre"] = {"value": node, "label": vocabulary.genres[node]["label"],
                         "tier": "hypothesis", "source": "catalog",
                         "claim_refs": [estimate_claim] if estimate_claim else []}
    else:
        cell["genre"] = {"value": node, "label": vocabulary.genres[node]["label"],
                         "tier": "hypothesis", "source": "market",
                         "claim_refs": [], "reason": "no game in the corpus is coded in it"}
    family = vocabulary.family(node)
    cell["family"] = dict(cell["genre"], value=family, label=vocabulary.genres[family]["label"])
    catalog = {}
    if entry:
        ref = [estimate_claim] if estimate_claim else []
        catalog = {
            "mechanics": entry.get("mechanics") and {"value": sorted(entry["mechanics"]),
                                                     "label": entry["core_mechanic"]},
            "core_loop": {"value": entry["core_loop"], "label": entry["core_loop"]},
            "art_dimension": {"value": entry.get("rendering", "2d")},
            "session_band": {"value": vocabulary.session_band(entry["session_seconds"]),
                             "label": f"{entry['session_seconds']} s estimated"},
        }
        catalog = {k: dict(v, tier="hypothesis", source="catalog", claim_refs=ref)
                   for k, v in catalog.items() if v}
    for facet in CELL_FACETS:
        if facet in ("genre", "family"):
            continue
        if facet in overrides:
            cell[facet] = overrides[facet]
            continue
        value = None
        if facet == "session_band":
            run = [g for g in games if "run_seconds" in g.facets]
            if run:
                seconds = statistics.median(float(g.facets["run_seconds"]["value"]) for g in run)
                value = {"value": vocabulary.session_band(seconds),
                         "label": f"median run {seconds:g} s over {len(run)} game(s)",
                         "tier": "derived", "source": "corpus",
                         "claim_refs": sorted({c for g in run
                                               for c in g.facets["run_seconds"]["claim_refs"]})}
        elif facet == "core_loop":
            value = None
        else:
            value = space.from_games(games, GAME_FACET[facet])
        if value is None and facet in catalog:
            value = catalog[facet]
        cell[facet] = value or _unknown(
            f"no teardown in the corpus codes {facet} for "
            f"{vocabulary.genres[node]['label']}"
            + ("" if games else " (it has no teardown games)"))
    cell["platforms"] = list(overrides.get("_platforms") or [])
    return cell


def _audience(space, games, candidate, platforms, estimate_claim):
    vocabulary = space.vocabulary
    out = {}
    player = space.from_games(games, "audience_type")
    out["player_type"] = player or _unknown(
        "no game in this cell is coded on player type; the audience type is not assumed "
        "(a market descriptor such as casual describes the market, not the player)")
    for key, facet in (("intent", "intent"), ("skill", "skill")):
        out[key] = space.from_games(games, facet) or _unknown(
            f"no game in this cell is coded on {facet}")
    device = space.from_games(games, "device")
    if device is None:
        shares, refs = [], []
        for pid in platforms:
            view = space.views.get(pid)
            if view is not None and view.value("mobile_share") is not None:
                shares.append(float(view.value("mobile_share")))
                refs.extend(view.support("mobile_share"))
        if shares:
            mean = sum(shares) / len(shares)
            value = "mobile" if mean >= 0.8 else "desktop" if mean <= 0.2 else "both"
            device = {"value": value, "label": f"platform mobile share {mean:.0%}",
                      "tier": "hypothesis", "source": "platform",
                      "claim_refs": sorted({r for r in refs if r})}
    out["device"] = device or _unknown("neither the corpus nor the platform profiles state a "
                                       "device split for these platforms")
    out["age_band"] = space.from_games(games, "age_band") or _unknown(
        "no portal in the corpus states an age band for these games; none is inferred")
    run = [g for g in games if "run_seconds" in g.facets]
    if run:
        seconds = statistics.median(float(g.facets["run_seconds"]["value"]) for g in run)
        out["session_behavior"] = {
            "value": vocabulary.session_band(seconds),
            "label": f"median run {seconds:g} s across {len(run)} measured game(s)",
            "tier": "derived", "source": "corpus",
            "claim_refs": sorted({c for g in run for c in g.facets["run_seconds"]["claim_refs"]})}
    elif candidate:
        seconds = candidate["_archetype"]["session_seconds"]
        out["session_behavior"] = {"value": vocabulary.session_band(seconds),
                                   "label": f"{seconds} s, the catalog's estimate",
                                   "tier": "hypothesis", "source": "catalog",
                                   "claim_refs": [estimate_claim] if estimate_claim else []}
    else:
        out["session_behavior"] = _unknown("no run length was measured for this cell")
    regions = sorted({r for pid in platforms
                      for r in ((space.views[pid].profile.get("audience") or {}).get(
                          "primary_regions") or []) if pid in space.views})
    if regions:
        out["regions"] = regions
    return out


def _production(space, cell, games, candidate, estimate_claim):
    """Cost class from what research coded - the rendering style and animation class (each
    with the vocabulary's cost), rigid-body physics, realtime networking - else the catalog's
    unmeasured estimate. The vocabulary's cost classes are not calibrated on shipped titles."""
    vocabulary = space.vocabulary
    drivers, levels, refs = [], [], []
    tier = "unknown"
    coded = {"art_rendering": cell.get("art_rendering"),
             "animation": space.from_games(games, "animation")}
    for facet, values in (("art_rendering", "art_renderings"), ("animation", "animations")):
        fv = coded[facet]
        if fv and fv.get("tier") in ("observed", "derived") and isinstance(fv["value"], str):
            cost = vocabulary.lists[values].get(fv["value"], {}).get("cost")
            if cost:
                levels.append(COST.index(cost))
                drivers.append(f"{vocabulary.label(facet, fv['value'])} costs {cost}")
                refs.extend(fv.get("claim_refs") or [])
                tier = "derived"
    for facet, value, level, what in (("physics_engine", "rigid-body", "m",
                                       "rigid-body physics"),
                                      ("networking", "realtime", "xl", "realtime networking")):
        fv = space.from_games(games, facet)
        if fv and fv["value"] == value:
            levels.append(COST.index(level))
            drivers.append(f"{what} ({fv['label']})")
            refs.extend(fv.get("claim_refs") or [])
            tier = "derived"
    entry = candidate["_archetype"] if candidate else None
    if entry:
        levels.append(COST.index(entry["technical_complexity"]))
        drivers.append(f"catalog estimate: {entry['technical_complexity']} technical, "
                       f"{entry['asset_complexity']} asset complexity (unmeasured)")
        refs.extend([estimate_claim] if estimate_claim else [])
        if tier == "unknown":
            tier = "hypothesis"
        if entry.get("multiplayer"):
            levels.append(COST.index("xl"))
            drivers.append("realtime multiplayer")
    dimension = cell.get("art_dimension", {}).get("value")
    if dimension == "3d":
        drivers.append("3D rendering and assets")
    out = {"dimension": dimension if isinstance(dimension, str) else None,
           "complexity": COST[max(levels)] if levels else "unknown",
           "tier": tier, "drivers": drivers or ["nothing in the corpus or catalog measures it"],
           "estimate_days": entry["dev_speed_days"] if entry else None,
           "asset_cost_usd": entry["asset_cost_usd"] if entry else None}
    if refs:
        out["claim_refs"] = sorted({r for r in refs if r})
    return out


def _capability(space, node, candidate, dimension):
    vocabulary = space.vocabulary
    label = vocabulary.genres[node]["label"]
    if candidate is None:
        return {"buildable": False, "catalog_entry": None, "design_archetype": None,
                "requires": [],
                "missing": [f"no capability-catalog entry covers {label} ({node})"],
                "reason": f"The Factory has no shape for {label}: nothing in the capability "
                          f"catalog says what it would take to build it."}
    entry = candidate["_archetype"]
    out = {"catalog_entry": candidate["id"],
           "design_archetype": entry.get("design_archetype"),
           "requires": list(entry.get("requires") or [])}
    missing = []
    if "design_archetype" in entry and not entry["design_archetype"]:
        missing.append(entry.get("unavailable") or "no design archetype carries this concept")
    rendering = entry.get("rendering", "2d")
    if isinstance(dimension, str) and dimension in ("2d", "3d") and dimension != rendering:
        missing.append(f"the buildable shape renders {rendering}; this opportunity's art is "
                       f"{dimension}")
    out["buildable"] = not missing
    out["missing"] = missing
    out["reason"] = (f"Built by catalog entry {candidate['id']} (design archetype "
                     f"{entry.get('design_archetype')})." if not missing else
                     f"Not buildable yet through {candidate['id']}: {'; '.join(missing)}.")
    return out


def _monetization(space, node, candidate, platforms):
    placements = []
    line = space.vocabulary.lineage(node)
    for level in line:
        found = [p for p in space.patterns if p["pair"] == "genre-monetization"
                 and p["a"]["value"] == level]
        if found:
            for p in sorted(found, key=lambda p: (-p["prevalence"], p["id"])):
                placements.append({"trigger": p["b"]["value"], "numerator": p["numerator"],
                                   "denominator": p["denominator"], "claim": p["claim"]})
            break
    support = []
    for pid in platforms:
        view = space.views.get(pid)
        if view is None:
            continue
        formats = [f for f in ("rewarded", "interstitial", "banner", "iap")
                   if view.value(f"ads.{f}" if f != "iap" else "iap")]
        refs = set()
        for key in ("ads.rewarded", "ads.interstitial", "ads.banner", "iap"):
            refs.update(r for r in view.support(key) if r)
        support.append({"platform": pid, "formats": formats, "claim_refs": sorted(refs)})
    out = {"placements": placements, "platform_support": support}
    if candidate:
        out["primary"] = candidate["_archetype"]["monetization"]["primary"]
    else:
        formats = Counter(f for g in space.games_in(node) for f in
                          (g.value("ad_formats") or []) if f != "none")
        if formats:
            out["primary"] = sorted(formats, key=lambda f: (-formats[f], f))[0]
    return out


def _adopt(space, node, opportunity_id):
    adopted = []
    for level in space.vocabulary.lineage(node):
        for p in space.patterns:
            if p["kind"] in ADOPT_KINDS and p["a"]["facet"] == "genre" and \
                    p["a"]["value"] == level and p["prevalence"] >= ADOPT_MIN_PREVALENCE:
                adopted.append(p)
        if adopted:
            break
    out = []
    for p in sorted(adopted, key=lambda p: (-p["prevalence"], p["id"]))[:5]:
        effect = space.book.hypothesis(
            ("effect", opportunity_id, p["id"]),
            f"Adopting '{p['b']['value']}' ({p['b']['facet']}), which {p['numerator']} of "
            f"{p['denominator']} comparable games show, may meet the expectation those games "
            f"set. A hypothesis: the corpus shows co-occurrence, not effect.",
            {"pattern": p["id"], "dimension": "retention_potential"},
            confidence=CONFIDENCE_EFFECT, tags=["effect", "pattern-adoption"])
        out.append({"pattern": p["id"], "statement": p["statement"],
                    "numerator": p["numerator"], "denominator": p["denominator"],
                    "claim": p["claim"], "effect_hypothesis": effect})
    return out


def _benchmarks(space, node):
    out = {}
    for level in space.vocabulary.lineage(node):
        for b in space.benchmarks:
            if b["genre"] == level and b["facet"] not in out:
                out[b["facet"]] = {k: b[k] for k in ("facet", "unit", "median", "min", "max",
                                                     "n", "games", "claim")}
    return [out[k] for k in sorted(out)]


def _competitors(space, node):
    out = []
    for game in space.games_in(node, teardown_only=False):
        role = ("leader" if game.id in space.demand_listed else
                "teardown" if game.depth == "teardown" else "listed")
        entry = {"game": game.id, "name": game.name, "role": role, "depth": game.depth,
                 "platforms": game.platforms,
                 "claim_refs": sorted(game.claim_refs)[:8]}
        if game.fixture:
            entry["fixture"] = True
        out.append(entry)
    order = {"leader": 0, "teardown": 1, "listed": 2}
    out.sort(key=lambda c: (order[c["role"]], c["name"].lower()))
    return out[:10]


def _market(space, node, platforms):
    return [space.cells[f"{node}@{pid}"].to_dict() for pid in sorted(platforms)
            if f"{node}@{pid}" in space.cells]


def build(space, *, origin, node, platforms, basis, summary, identity=(), overrides=None,
          changed_axis=None, candidate=None, opportunity_id=None, adopt_extra=None):
    """One opportunity's research block (the `_`-prefixed keys are internal)."""
    vocabulary = space.vocabulary
    overrides = dict(overrides or {})
    overrides["_platforms"] = platforms
    candidate = candidate if candidate is not None else space.candidate_for(node)
    estimate_claim = None
    if candidate is not None:
        estimate_claim = next((d["claim_refs"][0] for d in candidate["dimensions"]
                               if d["dimension"] == "dev_speed_days" and d["claim_refs"]), None)
    games = space.games_in(node)
    oid = opportunity_id or space.opportunity_id(origin, node, *identity)
    cell = _cell(space, node, games, candidate, overrides, estimate_claim)
    capability = _capability(space, node, candidate, cell["art_dimension"].get("value"))
    rests = [c for c in basis if space.book.rests_on_observation(c)]
    thesis = space.book.hypothesis(
        ("thesis", oid),
        f"{summary} It may be worth testing as a title; nothing here measures that it will "
        f"find players.", {"genre": node, "dimension": "monetization_fit"},
        confidence=CONFIDENCE_THESIS, tags=["thesis", origin])
    adopted = _adopt(space, node, oid)
    for item in adopt_extra or []:
        item = dict(item)
        item["effect_hypothesis"] = space.book.hypothesis(
            ("effect", oid, item["pattern"]),
            f"Carrying over '{item['pattern']}', which {item['numerator']} of "
            f"{item['denominator']} games in its home genre show, may set this game apart. A "
            f"hypothesis: the corpus shows where it occurs, not what it does.",
            {"pattern": item["pattern"], "dimension": "retention_potential"},
            confidence=CONFIDENCE_EFFECT, tags=["effect", "pattern-transfer"])
        adopted = [a for a in adopted if a["pattern"] != item["pattern"]] + [item]
    patterns = {"adopt": adopted}
    if changed_axis:
        patterns["differentiate_on"] = [changed_axis["facet"]]
    facets = [cell[f] for f in CELL_FACETS]
    strong = sum(1 for f in facets if f["tier"] in ("observed", "derived"))
    order = {"observed": 3, "derived": 2, "hypothesis": 1, "unknown": 0}
    weakest = min((f["tier"] for f in facets), key=lambda t: order[t])
    risks = []
    if candidate is not None:
        risks.extend({"description": r["description"], "severity": r["severity"],
                      "claim_refs": [estimate_claim] if estimate_claim else []}
                     for r in candidate["_archetype"].get("risks") or [])
    for pid in platforms:
        c = space.cells.get(f"{node}@{pid}")
        if c is not None and c.saturation.get("status") == "over-supplied":
            risks.append({"description": f"{vocabulary.genres[node]['label']} is over-supplied "
                                         f"on {pid} relative to its demand",
                          "severity": "medium", "claim_refs": c.saturation["claim_refs"]})
    if not capability["buildable"]:
        risks.append({"description": "The Factory cannot build this yet: "
                                     + "; ".join(capability["missing"]), "severity": "high"})
    fixture = any(space.tagged(c, "fixture") for c in basis)
    if fixture:
        risks.append({"description": "Part of its basis is fixture (test) data, not real "
                                     "evidence", "severity": "high"})
    claim_refs = set(basis) | {thesis}
    for f in facets:
        claim_refs.update(f.get("claim_refs") or [])
    block = {
        "research_version": 2,
        "report_id": "rr-" + space.report_key,
        "opportunity_id": oid,
        "origin": origin,
        "status": "eligible",
        "summary": summary,
        "cell": cell,
        "basis": {"claim_refs": sorted(set(basis)), "evidence_backed": bool(rests),
                  "thesis": thesis, "statement": summary},
        "market": _market(space, node, platforms or space.scope),
        "competitors": _competitors(space, node),
        "patterns": patterns,
        "benchmarks": _benchmarks(space, node),
        "monetization": _monetization(space, node, candidate, platforms),
        "production": _production(space, cell, games, candidate, estimate_claim),
        "capability": capability,
        "audience": _audience(space, games, candidate, platforms, estimate_claim),
        "risks": risks,
        "confidence": {"evidence_coverage": round(strong / len(facets), 4),
                       "weakest_tier": weakest,
                       "unknown_facets": [CELL_FACETS[i] for i, f in enumerate(facets)
                                          if f["tier"] == "unknown"],
                       "fixture_evidence": fixture},
        "claim_refs": [],
        "_node": node,
        "_candidate": candidate,
        "_platforms": list(platforms),
    }
    if changed_axis:
        block["changed_axis"] = changed_axis
    if candidate is not None:
        block["screen"] = {"candidate": candidate["id"],
                           "score": candidate["screen"]["score"]}
    for section in ("market", "benchmarks"):
        for item in block[section]:
            for key in ("claim_refs",):
                for side in ("demand", "supply", "saturation", "competition", "trend"):
                    claim_refs.update((item.get(side) or {}).get(key) or [])
            if "claim" in item:
                claim_refs.add(item["claim"])
    for p in patterns["adopt"]:
        claim_refs.update([p["claim"], p["effect_hypothesis"]])
    for c in block["competitors"]:
        claim_refs.update(c["claim_refs"])
    for item in block["monetization"]["placements"]:
        claim_refs.add(item["claim"])
    for item in block["monetization"]["platform_support"]:
        claim_refs.update(item["claim_refs"])
    for value in block["audience"].values():
        if isinstance(value, dict):
            claim_refs.update(value.get("claim_refs") or [])
    claim_refs.update(block["production"].get("claim_refs") or [])
    for r in risks:
        claim_refs.update(r.get("claim_refs") or [])
    block["claim_refs"] = sorted(c for c in claim_refs if c)
    return block


# -- generators ------------------------------------------------------------------------------


def _demand_platforms(space, node):
    return sorted(c.platform for c in space.demand_cells(node))


def _proven_core(space):
    vocabulary, config = space.vocabulary, space.config
    out = []
    axes = list(config.opportunities["axes"])
    cores = [n for n in space.coded_nodes() if vocabulary.depth(n) >= 2]
    for node in cores:
        demand = space.demand_cells(node)
        games = space.games_in(node)
        if not demand or len(games) < config.min_support:
            continue
        for axis in axes:
            coded = [g for g in games if axis in g.facets]
            if len(coded) < config.min_denominator:
                continue
            held = {g.value(axis) for g in coded}
            elsewhere = {}
            for g in space.corpus.sorted_games():
                if g in games or g.depth != "teardown" or g.id not in space.demand_listed:
                    continue
                v = g.value(axis)
                if isinstance(v, str) and v not in held:
                    elsewhere.setdefault(v, []).append(g)
            for value in sorted(elsewhere, key=lambda v: (-len(elsewhere[v]), v)):
                sources = elsewhere[value]
                label = vocabulary.genres[node]["label"]
                vlabel = vocabulary.label(axis, value)
                frame = f"teardown games coded {label} and coded on {axis}"
                absent = space.book.derived(
                    ("absent", node, axis, value),
                    f"0 of {len(coded)} {label} games coded on {axis} use {vlabel} "
                    f"({', '.join(sorted(g.name for g in coded)[:6])}).",
                    sorted({c for g in coded for c in g.facets[axis]["claim_refs"]}),
                    {"genre": node, "facet": axis},
                    support={"numerator": 0, "denominator": len(coded), "members": [],
                             "exceptions": [g.id for g in coded], "frame": frame})
                proven = sorted({c for g in sources for c in g.facets[axis]["claim_refs"]}
                                | {e["claim"] for g in sources for e in g.listings
                                   if e["list_kind"] == "popularity"})
                demand_refs = sorted({r for c in demand for r in c.demand["claim_refs"]})
                basis = demand_refs + proven + [absent]
                summary = (f"A {label} game - a genre players are seen playing "
                           f"({', '.join(sorted(c.platform for c in demand))}) - with its "
                           f"{vocabulary.facet(axis)['label'].lower()} changed to {vlabel}, "
                           f"which popular {', '.join(sorted({vocabulary.genres[g.value('genre')]['label'] for g in sources if g.value('genre')}))} "
                           f"games use ({', '.join(g.name for g in sources[:3])}) and no coded "
                           f"{label} game does.")
                # The new value is what the opportunity proposes to test, not something
                # observed of this genre: a hypothesis, citing where it was seen elsewhere.
                override = {axis: {"value": value, "label": vlabel, "tier": "hypothesis",
                                   "source": "corpus", "claim_refs": proven[:12],
                                   "reason": f"proposed: 0 of {len(coded)} {label} games "
                                             f"use it; popular games elsewhere do"}}
                out.append(dict(
                    origin="proven-core-new-axis", node=node, identity=(axis, value),
                    platforms=_demand_platforms(space, node), basis=basis, summary=summary,
                    overrides=override,
                    changed_axis={"facet": axis, "from": sorted(held), "to": value,
                                  "claim_refs": [absent]},
                    _sort=(axes.index(axis), -len(sources), value),
                    _share=-max(c.demand.get("share") or 0 for c in demand)))
    # Interleave the cores, so the generator's cap spreads over every proven genre instead
    # of filling up with one genre's variations: each core's best first, then each one's
    # second best, and so on.
    by_node = {}
    for proposal in sorted(out, key=lambda p: p["_sort"]):
        by_node.setdefault(proposal["node"], []).append(proposal)
    for node, proposals in by_node.items():
        for index, proposal in enumerate(proposals):
            proposal["_sort"] = (index, proposal.pop("_share"), node) + proposal["_sort"]
    return out


def _supply_gap(space):
    out = []
    for cell in sorted(space.cells.values(), key=lambda c: c.id):
        if cell.saturation.get("status") != "under-supplied" or not cell.demand_observed:
            continue
        label = space.vocabulary.genres[cell.genre]["label"]
        out.append(dict(
            origin="supply-gap", node=cell.genre, platforms=[cell.platform],
            identity=(cell.platform,),
            basis=cell.saturation["claim_refs"] + cell.demand["claim_refs"]
            + cell.supply["claim_refs"],
            summary=(f"{label} on {cell.platform}: {cell.demand['share']:.0%} of popularity-"
                     f"list titles against {cell.supply['share']:.0%} of listed games - "
                     f"more demand than supply."),
            _sort=(-cell.saturation["ratio"], cell.id)))
    return out


def _pattern_transfer(space):
    vocabulary, config = space.vocabulary, space.config
    minimum = float(config.opportunities["transfer_min_prevalence"])
    out = []
    coded = set(space.coded_nodes())
    targets = sorted({c.genre for c in space.cells.values() if c.demand_observed
                      and vocabulary.depth(c.genre) >= 2 and c.genre in coded})
    for p in space.patterns:
        if p["kind"] not in TRANSFER_KINDS or p["a"]["facet"] != "genre" or \
                p["prevalence"] < minimum or vocabulary.depth(p["a"]["value"]) < 2 or \
                p["a"]["value"] not in coded:
            continue
        home, facet, value = p["a"]["value"], p["b"]["facet"], p["b"]["value"]
        for node in targets:
            if vocabulary.is_within(node, home) or vocabulary.is_within(home, node):
                continue
            games = space.games_in(node)
            measured = [g for g in games if facet in g.facets]
            if len(measured) < config.min_denominator:
                continue
            holders = [g for g in measured if value in (g.value(facet) if isinstance(
                g.value(facet), list) else [g.value(facet)])]
            if holders:
                continue
            label = vocabulary.genres[node]["label"]
            frame = f"teardown games coded {label} and coded on {facet}"
            absent = space.book.derived(
                ("absent", node, facet, value),
                f"0 of {len(measured)} {label} games coded on {facet} have "
                f"{vocabulary.label(facet, value)}.",
                sorted({c for g in measured for c in g.facets[facet]["claim_refs"]}),
                {"genre": node, "facet": facet},
                support={"numerator": 0, "denominator": len(measured), "members": [],
                         "exceptions": [g.id for g in measured], "frame": frame})
            demand = space.demand_cells(node)
            out.append(dict(
                origin="pattern-transfer", node=node, identity=(facet, value),
                platforms=_demand_platforms(space, node),
                basis=[p["claim"], absent] + sorted({r for c in demand
                                                     for r in c.demand["claim_refs"]}),
                summary=(f"{label} with {vocabulary.label(facet, value)} ({facet}) carried "
                         f"over from {vocabulary.genres[home]['label']}, where "
                         f"{p['numerator']} of {p['denominator']} games have it; no coded "
                         f"{label} game does."),
                adopt_extra=[{"pattern": p["id"], "statement": p["statement"],
                              "numerator": p["numerator"], "denominator": p["denominator"],
                              "claim": p["claim"]}],
                _sort=(-p["prevalence"], node, p["id"])))
    return out


def _portal_difference(space):
    vocabulary = space.vocabulary
    out = []
    frames = [f for f in space.corpus.frames.values() if f["list_kind"] == "popularity"]
    coded = set(space.coded_nodes(teardown_only=False))
    nodes = sorted({c.genre for c in space.cells.values() if c.demand_observed
                    and vocabulary.depth(c.genre) >= 2 and c.genre in coded})
    for node in nodes:
        present = sorted({c.platform for c in space.demand_cells(node)})
        for platform in sorted(space.scope):
            if platform in present:
                continue
            scoped = [f for f in frames if f["platform"] == platform and f["scope"]
                      and vocabulary.is_within(node, f["scope"])]
            if not scoped:
                continue
            titles = sorted({g for f in scoped for g in f["titles"]})
            members = [g for g in titles if space.games[g].value("genre")
                       and vocabulary.is_within(space.games[g].value("genre"), node)]
            if members or not titles:
                continue
            label = vocabulary.genres[node]["label"]
            frame = (f"titles in {len(scoped)} popularity list(s) on {platform} scoped to "
                     f"include {label}: " + "; ".join(f"'{f['list']}'" for f in scoped))
            absent = space.book.derived(
                ("portal-absent", node, platform, frame),
                f"0 of {len(titles)} {frame} are {label}. A captured sample, not the whole "
                f"portal.",
                sorted({c for f in scoped for c in f["claim_refs"]}),
                {"genre": node, "platform": platform, "cell": f"{node}@{platform}"},
                support={"numerator": 0, "denominator": len(titles), "members": [],
                         "exceptions": titles, "frame": frame})
            demand_refs = sorted({r for c in space.demand_cells(node)
                                  for r in c.demand["claim_refs"]})
            out.append(dict(
                origin="portal-difference", node=node, platforms=[platform],
                identity=(platform,),
                basis=demand_refs + [absent],
                summary=(f"{label} is in popularity lists on {', '.join(present)} but absent "
                         f"from the {len(titles)} popular titles captured on {platform}."),
                _sort=(node, platform)))
    return out


GENERATORS = {
    "proven-core-new-axis": _proven_core,
    "supply-gap": _supply_gap,
    "pattern-transfer": _pattern_transfer,
    "portal-difference": _portal_difference,
}


def _from_candidate(space, candidate):
    entry = candidate["_archetype"]
    node = entry.get("genre_node") or space.vocabulary.genre_for(entry.get("subgenre")) \
        or space.vocabulary.genre_for(entry.get("genre"))
    if node is None:
        return None
    viable = list(candidate["_viable"])
    summary = (f"{entry['title']}: a shape in the capability catalog, screened against "
               f"{', '.join(space.scope)} at {candidate['screen']['score']:.2f}"
               + (f", with observed market presence on "
                  f"{', '.join(candidate['market_signal']['platforms'])}"
                  if candidate["market_signal"]["observed"] else
                  ", with no observed market presence (estimates only)") + ".")
    basis = list(candidate["claim_refs"])
    block = build(space, origin="capability-screen", node=node,
                  platforms=viable or [f["platform"] for f in candidate["platform_fit"][:1]],
                  basis=basis, summary=summary, candidate=candidate,
                  opportunity_id=candidate["opportunity_id"])
    block["basis"]["evidence_backed"] = bool(candidate["market_signal"]["observed"])
    if candidate["status"] == "excluded" and not candidate["exclusion_reason"].startswith(
            "not buildable"):
        block["status"] = "excluded"
        block["exclusion_reason"] = candidate["exclusion_reason"]
    elif not block["capability"]["buildable"]:
        block["status"] = "capability-gap"
    return block


def generate(space):
    """Every opportunity, as research blocks. Returns (opportunities, refused) - `refused`
    lists generator proposals dropped for not resting on an observation."""
    config = space.config
    enabled = list(config.opportunities["generators"])
    limit = int(config.opportunities["max_per_generator"])
    out, refused, seen = [], [], set()
    for name in enabled:
        if name not in GENERATORS:
            continue
        proposals = sorted(GENERATORS[name](space), key=lambda p: p["_sort"])
        kept = 0
        for proposal in proposals:
            proposal.pop("_sort")
            key = (proposal["origin"], proposal["node"], tuple(proposal.get("identity") or ()))
            if key in seen:
                continue
            if not any(space.book.rests_on_observation(c) for c in proposal["basis"]):
                refused.append(proposal["summary"])
                continue
            if kept >= limit:
                break
            seen.add(key)
            kept += 1
            block = build(space, **proposal)
            block["_order"] = len(out)
            if block["opportunity_id"] in space.acted_on:
                block["status"] = "excluded"
                block["exclusion_reason"] = (f"already in the backlog as "
                                             f"{space.acted_on[block['opportunity_id']]}")
            elif not block["capability"]["buildable"]:
                block["status"] = "capability-gap"
            else:
                candidate = block["_candidate"]
                usable = [p for p in block["_platforms"] if p in candidate["_viable"]]
                if candidate["status"] == "excluded" and not \
                        candidate["exclusion_reason"].startswith("not buildable"):
                    block["status"] = "excluded"
                    block["exclusion_reason"] = (f"its buildable shape {candidate['id']} is "
                                                 f"excluded: {candidate['exclusion_reason']}")
                elif not usable:
                    block["status"] = "excluded"
                    block["exclusion_reason"] = (
                        f"{candidate['id']} is not viable on "
                        f"{', '.join(block['_platforms']) or 'any target platform'}")
                else:
                    block["_platforms"] = usable
                    block["cell"]["platforms"] = usable
            out.append(block)
    if "capability-screen" in enabled:
        for candidate in space.candidates:
            block = _from_candidate(space, candidate)
            if block is not None:
                block["_order"] = len(out)
                out.append(block)
    return out, refused


def _vocabulary_words(space, block):
    """(defining, descriptive) words of an opportunity, as analysis.brief_terms reads them:
    its genre lineage and its shape's names define it; its cell's facets and the shape's
    mechanic sentence describe it."""
    vocabulary = space.vocabulary
    node = block["_node"]
    defining = []
    for n in vocabulary.lineage(node):
        g = vocabulary.genres[n]
        defining += [g["id"], g["label"]] + list(g.get("aliases") or [])
    descriptive = []
    for facet in ("mechanics", "theme", "setting", "player_fantasy", "art_tone",
                  "art_rendering"):
        fv = block["cell"].get(facet) or {}
        values = fv.get("value")
        for v in (values if isinstance(values, list) else [values]):
            if isinstance(v, str):
                descriptive += [v, vocabulary.label(GAME_FACET.get(facet, facet), v)]
    defining, descriptive = words_of(defining), words_of(descriptive)
    candidate = block.get("_candidate")
    if candidate:
        shape_defining, shape_descriptive = archetype_vocabulary(candidate["_archetype"])
        defining |= shape_defining
        descriptive |= shape_descriptive
    return defining, descriptive


def rank(space, opportunities, idea=None):
    """Order the selectable opportunities; returns them, best first. Selectable: eligible
    (buildable, not excluded). The rule, in order: closest to the brief; resting on observed
    demand when any does; generated from the corpus before a bare catalog shape; more of its
    cell resting on observed or derived claims; the buildable shape's screen score; the
    order generators run in (core/reference/research-analysis.yaml) and propose."""
    dimension = idea_dimension(idea) if idea else None
    eligible = [o for o in opportunities if o["status"] == "eligible"]
    for block in opportunities:
        if idea:
            defining, descriptive = _vocabulary_words(space, block)
            built = (block["production"].get("dimension")
                     or (block.get("_candidate") or {}).get("_archetype", {}).get("rendering"))
            block["brief_match"] = {"terms": brief_terms(idea, defining, descriptive),
                                    "dimension": dimension is not None and built == dimension}
    backed = any(o["basis"]["evidence_backed"] for o in eligible)

    def key(o):
        match = o.get("brief_match")
        idea_key = _idea_rank({"idea_match": match}, dimension) if match is not None else (0, 0)
        return (idea_key, backed and not o["basis"]["evidence_backed"],
                ORIGIN_RANK[o["origin"]], -o["confidence"]["evidence_coverage"],
                -(o.get("screen") or {}).get("score", 0.0), o.get("_order", 0),
                o["opportunity_id"])
    return sorted(eligible, key=key)
