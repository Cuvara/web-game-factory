"""Market cells: demand, supply, saturation, competition and trend, kept apart.

A cell is one genre node on one platform. Each signal is its own derived claim with the
count it rests on, because each answers a different question:

    demand       how much of what the portal shows *by popularity* belongs to the cell:
                 titles in popularity-ordered lists captured on that platform. Only a list
                 the portal orders by play is a demand signal; an editorial or category
                 list shows that a game exists, not that it is played.
    supply       how many games the portal lists in the cell (its category count), and the
                 cell's share of its family where the family's count is known too.
    saturation   demand share / supply share. Needs both. Supply with no demand evidence is
                 `insufficient-demand-evidence` - never an opportunity.
    competition  the distinct titles observed in the cell: named competitors, not a score.
    trend        change in demand share across the same list captured on several dates.
                 `insufficient-history` until there are enough dates. Never extrapolated.

Many games is supply, not saturation; few games with no demand evidence is a gap in
evidence, not a gap in the market. Nothing here estimates a number nobody observed.
"""

from .evidence import Gap

__all__ = ["analyse_market", "Cell"]


def _share(numerator, denominator):
    return round(numerator / denominator, 4) if denominator else None


class Cell:
    def __init__(self, genre, platform):
        self.genre = genre
        self.platform = platform
        self.id = f"{genre}@{platform}"
        self.demand = {"status": "unknown"}
        self.supply = {"status": "unknown"}
        self.saturation = {"status": "unknown"}
        self.competition = {"status": "unknown"}
        self.trend = {"status": "insufficient-history"}
        self.demand_members = []

    @property
    def demand_observed(self):
        return self.demand.get("status") == "derived" and self.demand.get("numerator", 0) > 0

    def to_dict(self):
        return {"cell": self.id, "genre": self.genre, "platform": self.platform,
                "demand": self.demand, "supply": self.supply, "saturation": self.saturation,
                "competition": self.competition, "trend": self.trend}


def analyse_market(corpus, platforms, book):
    """Returns (frames, cells by id, trend summary, gaps)."""
    vocabulary, config = corpus.vocabulary, corpus.config
    band = float(config.market["saturation_band"])
    min_history = int(config.market["min_history_frames"])
    gaps = []

    games = corpus.games
    frames = sorted(corpus.frames.values(), key=lambda f: (f["platform"], f["list"],
                                                           f["observed_at"]))

    def genre_of(gid):
        return games[gid].value("genre") if gid in games else None

    def within(gid, node):
        genre = genre_of(gid)
        return bool(genre) and vocabulary.is_within(genre, node)

    # Which nodes get a cell on which platform: every node a listed game is coded in, its
    # ancestors, and every node a category count names.
    nodes_on = {pid: set() for pid in platforms}
    for game in games.values():
        genre = game.value("genre")
        if not genre:
            continue
        for platform in game.platforms:
            if platform in nodes_on:
                nodes_on[platform].update(vocabulary.lineage(genre))
    for entry in corpus.supply:
        if entry["platform"] in nodes_on:
            nodes_on[entry["platform"]].update(vocabulary.lineage(entry["genre"]))

    cells = {}
    for platform in sorted(nodes_on):
        popularity = [f for f in frames if f["platform"] == platform
                      and f["list_kind"] == "popularity"]
        # The latest capture of each popularity list is the demand frame; earlier captures
        # of the same list are history, for the trend.
        latest = {}
        for frame in popularity:
            latest[frame["list"]] = frame
        latest_frames = sorted(latest.values(), key=lambda f: f["list"])
        all_frames = [f for f in frames if f["platform"] == platform]
        for node in sorted(nodes_on[platform]):
            cell = Cell(node, platform)
            label = vocabulary.genres[node]["label"]
            # -- demand: over the popularity lists whose scope covers the node, and only
            # those sharing the broadest such scope, so one denominator never mixes a
            # family-wide list with a list of one subgenre.
            covering = [f for f in latest_frames if f["scope"] is None
                        or vocabulary.is_within(node, f["scope"])]
            if covering:
                broadest = min((vocabulary.depth(f["scope"]) if f["scope"] else 0)
                               for f in covering)
                covering = [f for f in covering if (vocabulary.depth(f["scope"])
                                                    if f["scope"] else 0) == broadest]
            current = covering
            titles = sorted({gid for f in current for gid in f["titles"]})
            if titles:
                members = [gid for gid in titles if within(gid, node)]
                frame_text = (f"titles captured from {len(current)} popularity-ordered "
                              f"list(s) on {platform}: "
                              + "; ".join(f"'{f['list']}' {f['observed_at'][:10]}"
                                          for f in current))
                parents = sorted({c for f in current for c in f["claim_refs"]})
                parents += sorted({c for gid in members
                                   for c in games[gid].facets.get("genre", {}).get(
                                       "claim_refs", [])})
                claim = book.derived(
                    ("demand", cell.id, frame_text),
                    f"{len(members)} of {len(titles)} {frame_text} are coded {label}"
                    + (f" ({', '.join(games[g].name for g in members[:6])})" if members
                       else "") + ".",
                    parents, {"genre": node, "platform": platform, "cell": cell.id,
                              "dimension": "distribution_potential"},
                    tags=["market", "demand"],
                    support={"numerator": len(members), "denominator": len(titles),
                             "members": members,
                             "exceptions": [g for g in titles if g not in members],
                             "frame": frame_text})
                cell.demand = {"status": "derived", "numerator": len(members),
                               "denominator": len(titles),
                               "share": _share(len(members), len(titles)),
                               "frame": frame_text, "claim_refs": [claim]}
                cell.demand_members = members
            else:
                cell.demand = {"status": "unknown",
                               "reason": (f"no popularity-ordered list captured on {platform} "
                                          f"covers {label}" if latest_frames else
                                          f"no popularity-ordered list was captured on "
                                          f"{platform}")}
            # -- supply
            counts = [e for e in corpus.supply if e["platform"] == platform
                      and e["genre"] == node]
            if counts:
                entry = counts[-1]
                cell.supply = {"status": "observed", "count": entry["count"],
                               "claim_refs": sorted({e["claim"] for e in counts})}
                family = vocabulary.family(node)
                fam = [e for e in corpus.supply if e["platform"] == platform
                       and e["genre"] == family]
                if family != node and fam and fam[0]["count"]:
                    total = int(fam[0]["count"])
                    part = int(entry["count"])
                    if 0 <= part <= total:
                        frame_text = (f"{platform} category counts: {label} {part} of "
                                      f"{vocabulary.genres[family]['label']} {total}")
                        claim = book.derived(
                            ("supply", cell.id, frame_text),
                            f"{label} is {part} of the {total} games {platform} lists in "
                            f"{vocabulary.genres[family]['label']}.",
                            [entry["claim"], fam[0]["claim"]],
                            {"genre": node, "platform": platform, "cell": cell.id,
                             "dimension": "competition"}, tags=["market", "supply"])
                        cell.supply.update({"status": "derived", "numerator": part,
                                            "denominator": total,
                                            "share": _share(part, total),
                                            "frame": frame_text,
                                            "claim_refs": sorted(set(cell.supply["claim_refs"])
                                                                 | {claim})})
            else:
                cell.supply = {"status": "unknown",
                               "reason": f"no category count for {label} on {platform}"}
            # -- saturation
            # Saturation needs demand that was seen: none of N sampled popular titles is not
            # evidence of low demand, only an absence of evidence of demand.
            dshare = cell.demand.get("share") if cell.demand_observed else None
            sshare = cell.supply.get("share")
            if dshare is not None and sshare:
                ratio = round(dshare / sshare, 4)
                status = ("under-supplied" if ratio >= band else
                          "over-supplied" if ratio <= 1 / band else "balanced")
                claim = book.derived(
                    ("saturation", cell.id, ratio),
                    f"On {platform}, {label} holds {dshare:.0%} of popularity-list titles "
                    f"against {sshare:.0%} of the family's listed games: demand/supply "
                    f"{ratio:.2f}, {status} on a {band:g}x band.",
                    cell.demand["claim_refs"] + cell.supply["claim_refs"],
                    {"genre": node, "platform": platform, "cell": cell.id,
                     "dimension": "competition"}, tags=["market", "saturation"])
                cell.saturation = {"status": status, "ratio": ratio, "claim_refs": [claim]}
            elif cell.supply.get("status") in ("observed", "derived") and \
                    not cell.demand_observed:
                cell.saturation = {
                    "status": "insufficient-demand-evidence",
                    "reason": (f"{platform} lists {label} games (supply) but no "
                               f"popularity-ordered capture shows demand for them; low or "
                               f"high, supply alone is not an opportunity")}
                gaps.append(Gap("insufficient-demand-evidence",
                                f"{cell.id}: supply observed, demand not; no saturation "
                                f"and no opportunity is derived from it", platform=platform))
            else:
                missing = []
                if dshare is None:
                    missing.append("observed demand")
                if not sshare:
                    missing.append("a supply share (the cell's and its family's category "
                                   "counts)")
                cell.saturation = {"status": "unknown",
                                   "reason": "needs " + " and ".join(missing)}
            # -- competition: named titles in the cell, over everything captured
            seen = sorted({gid for f in all_frames for gid in f["titles"]})
            named = [gid for gid in seen if within(gid, node)]
            if seen:
                frame_text = f"titles captured on {platform} in {len(all_frames)} list(s)"
                claim = book.derived(
                    ("competition", cell.id, frame_text),
                    f"{len(named)} of the {len(seen)} {frame_text} are {label}"
                    + (f": {', '.join(games[g].name for g in named[:8])}" if named else "")
                    + ".",
                    sorted({c for f in all_frames for c in f["claim_refs"]}),
                    {"genre": node, "platform": platform, "cell": cell.id,
                     "dimension": "competition"}, tags=["market", "competition"],
                    support={"numerator": len(named), "denominator": len(seen),
                             "members": named,
                             "exceptions": [g for g in seen if g not in named],
                             "frame": frame_text})
                cell.competition = {"status": "derived", "numerator": len(named),
                                    "denominator": len(seen),
                                    "share": _share(len(named), len(seen)),
                                    "frame": frame_text, "claim_refs": [claim]}
            # -- trend
            series = {}
            for frame in popularity:
                series.setdefault(frame["list"], []).append(frame)
            moves = []
            for list_name, captures in sorted(series.items()):
                dates = sorted({f["observed_at"][:10] for f in captures})
                if len(dates) < min_history:
                    continue
                first = min(captures, key=lambda f: f["observed_at"])
                last = max(captures, key=lambda f: f["observed_at"])
                a = [g for g in first["titles"] if within(g, node)]
                b = [g for g in last["titles"] if within(g, node)]
                moves.append((list_name, first, last, a, b))
            if moves:
                list_name, first, last, a, b = moves[0]
                before = _share(len(a), len(first["titles"]))
                after = _share(len(b), len(last["titles"]))
                frame_text = (f"'{list_name}' on {platform}, {first['observed_at'][:10]} "
                              f"vs {last['observed_at'][:10]}")
                claim = book.derived(
                    ("trend", cell.id, frame_text),
                    f"{label} went from {len(a)} of {len(first['titles'])} to {len(b)} of "
                    f"{len(last['titles'])} titles in {frame_text}. Two captures describe a "
                    f"change, not a trajectory.",
                    sorted(set(first["claim_refs"]) | set(last["claim_refs"])),
                    {"genre": node, "platform": platform, "cell": cell.id,
                     "dimension": "distribution_potential"}, tags=["market", "trend"],
                    support={"numerator": len(b), "denominator": len(last["titles"]),
                             "members": b,
                             "exceptions": [g for g in last["titles"] if g not in b],
                             "frame": frame_text})
                cell.trend = {"status": "derived", "numerator": len(b),
                              "denominator": len(last["titles"]), "share": after,
                              "frame": f"{frame_text}; earlier share {before}",
                              "claim_refs": [claim]}
            else:
                cell.trend = {"status": "insufficient-history",
                              "reason": f"no popularity list on {platform} was captured on "
                                        f"{min_history} or more dates"}
            cells[cell.id] = cell

    histories = sum(1 for f in {(f["platform"], f["list"]) for f in frames
                                if f["list_kind"] == "popularity"}
                    if len({x["observed_at"][:10] for x in frames
                            if (x["platform"], x["list"]) == f}) >= min_history)
    if histories:
        trend = {"status": "available", "series": histories,
                 "reason": f"{histories} popularity list(s) captured on {min_history}+ dates"}
    else:
        trend = {"status": "insufficient-history", "series": 0,
                 "reason": f"every popularity list in the corpus was captured on fewer than "
                           f"{min_history} dates; no trend is stated. Capture the same lists "
                           f"again on later dates to measure change."}
        gaps.append(Gap("insufficient-history", trend["reason"]))

    frame_out = [{"id": f["id"], "platform": f["platform"], "list": f["list"],
                  "list_kind": f["list_kind"], "observed_at": f["observed_at"],
                  "titles": len(f["titles"]), "claim_refs": sorted(f["claim_refs"])}
                 for f in frames]
    return frame_out, cells, trend, gaps
