"""The game corpus: every game a scan knows of, coded on the shared research facets.

Research V2's unit is the game. Two kinds of input feed one corpus:

    listings      reference_title facts in portal-listing snapshots (snapshots/*.json). A
                  listing proves a game is shown on a portal, in a named list, on a date - an
                  observation. The list's genre and the snapshot author's genre slug are
                  mapped onto the vocabulary's genre tree; that mapping is an interpretation,
                  so the game's genre coding is a derived claim whose parent is the listing.
    game records  <corpus>/games/*.json (core/artifacts/shared/game-record.schema.json): a
                  teardown - dated sessions (played and timed, a store page, a capture) and
                  the facet codings each supports. An `observed` coding becomes an observed
                  claim quoting its excerpt; an `interpreted` coding (a theme read off a
                  thumbnail) becomes a derived claim whose parent is the session's own
                  observed claim. An interpretation never passes as an observation.

What is refused, mirroring the snapshot rules: a record that does not match its schema
(permanent failure: a broken input), a coding outside the vocabulary or without an excerpt
(a `rejected-observation` / `unmapped-vocabulary` gap), a session dated after the scan.
Fixture records (`fixture: true`) are test data: their claims are tagged `fixture` and the
report says the corpus contains them.

Pure apart from reading the games directory: the step hands in sources, the vocabulary and a
ClaimBook.
"""

import glob
import hashlib
import json
import os
import re
import unicodedata
from datetime import timedelta

from wgflib.jsonschema_lite import Registry, Validator
from wgflib import paths

from .evidence import EvidenceError, Gap, format_time, parse_time

__all__ = ["Corpus", "Game", "game_id_for", "load_records", "CLOCK_SKEW"]

CLOCK_SKEW = timedelta(days=1)
CONFIDENCE_SESSION = 0.85
CONFIDENCE_STALE = 0.6
TIER_RANK = {"observed": 2, "derived": 1}


def _norm(name):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(name or "")).strip().lower())


def game_id_for(name):
    """A stable game id for a listed name. ASCII names slug; any other script adds a short
    digest of the normalized name, so two titles never collide on an empty slug."""
    normalized = _norm(name)
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    if len(slug) < 3 or not normalized.isascii():
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
        slug = f"{slug}-{digest}".strip("-") if slug else digest
    return f"game-{slug[:60].strip('-')}"


class Game:
    def __init__(self, gid, name, fixture=False):
        self.id = gid
        self.name = name
        self.fixture = fixture
        self.depth = "listing"
        self.sessions = 0
        self.listings = []          # {platform, list, list_kind, claim, observed_at}
        self.facets = {}            # facet -> {value, tier, claim_refs}
        self.claim_refs = set()

    @property
    def platforms(self):
        return sorted({entry["platform"] for entry in self.listings if entry["platform"]})

    def code(self, facet, value, tier, claim):
        """Record a coding. A stronger tier replaces a weaker one; at equal tier a deeper
        genre node (more specific) replaces a shallower one; otherwise the first stands and
        the claim is kept as corroboration."""
        self.claim_refs.add(claim)
        current = self.facets.get(facet)
        if current is None or TIER_RANK[tier] > TIER_RANK[current["tier"]]:
            self.facets[facet] = {"value": value, "tier": tier, "claim_refs": [claim]}
            return
        if TIER_RANK[tier] < TIER_RANK[current["tier"]]:
            return
        if current["value"] == value:
            if claim not in current["claim_refs"]:
                current["claim_refs"].append(claim)
            return
        if facet == "genre" and self._deeper(value, current["value"]):
            self.facets[facet] = {"value": value, "tier": tier, "claim_refs": [claim]}

    _vocabulary = None

    def _deeper(self, candidate, current):
        vocabulary = Game._vocabulary
        return vocabulary is not None and current in vocabulary.lineage(candidate) and \
            candidate != current

    def value(self, facet):
        entry = self.facets.get(facet)
        return None if entry is None else entry["value"]

    def to_dict(self):
        out = {
            "id": self.id,
            "name": self.name,
            "depth": self.depth,
            "platforms": self.platforms,
            "listings": [{k: entry[k] for k in ("platform", "list", "list_kind", "claim",
                                                 "observed_at")} for entry in self.listings],
            "facets": {facet: {"value": entry["value"], "tier": entry["tier"],
                               "claim_refs": sorted(entry["claim_refs"])}
                       for facet, entry in sorted(self.facets.items())},
            "claim_refs": sorted(self.claim_refs),
        }
        if self.fixture:
            out["fixture"] = True
        return out


_RECORD_SCHEMA = None


def _record_validator():
    global _RECORD_SCHEMA
    if _RECORD_SCHEMA is None:
        path = os.path.join(paths.ARTIFACTS, "shared", "game-record.schema.json")
        with open(path, encoding="utf-8") as handle:
            schema = json.load(handle)
        _RECORD_SCHEMA = Validator(schema, Registry().add_directory(paths.ARTIFACTS))
    return _RECORD_SCHEMA


def load_records(directory):
    """[(file name, record dict, raw digest)] for every games/*.json, schema-validated.
    A record that is not valid JSON or not a valid game record fails the scan permanently."""
    out = []
    if not os.path.isdir(directory):
        return out
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        with open(path, "rb") as handle:
            raw = handle.read()
        name = os.path.basename(path)
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvidenceError(f"games/{name}: not valid JSON: {exc}")
        errors = [str(e) for e in _record_validator().iter_errors(record)]
        if errors:
            raise EvidenceError(f"games/{name}: not a game record: {'; '.join(errors[:3])}")
        if f"{record['id']}.json" != name:
            raise EvidenceError(f"games/{name}: id {record['id']!r} is not the file stem")
        out.append((name, record, "sha256:" + hashlib.sha256(raw).hexdigest()))
    return out


class Corpus:
    """Games by id, the listing frames they were seen in, and category supply counts."""

    def __init__(self, vocabulary, config, book):
        self.vocabulary = vocabulary
        self.config = config
        self.book = book
        self.games = {}
        self.by_name = {}
        self.frames = {}            # frame id -> {id, platform, list, list_kind, observed_at, titles:[game ids], claim_refs}
        self.supply = []            # {platform, genre, count, claim, name}
        self.gaps = []
        Game._vocabulary = vocabulary

    # -- game records -----------------------------------------------------------------------

    def add_records(self, records, as_of, ttl_days):
        for _name, record, _digest in records:
            self._add_record(record, as_of, ttl_days)

    def _add_record(self, record, as_of, ttl_days):
        vocabulary = self.vocabulary
        rid = record["id"]
        if str(record["vocabulary_version"]).split(".")[0] != vocabulary.version.split(".")[0]:
            self.gaps.append(Gap("unmapped-vocabulary",
                                 f"{rid} is coded against vocabulary {record['vocabulary_version']}"
                                 f", not {vocabulary.version}; its codings cannot be resolved "
                                 f"and the record is skipped", source_id=rid))
            return
        fixture = bool(record.get("fixture"))
        game = self.games.get(rid) or Game(rid, record["name"], fixture)
        game.fixture = game.fixture or fixture
        self.games[rid] = game
        for alias in [record["name"]] + list(record.get("listing_names") or []):
            self.by_name.setdefault(_norm(alias), rid)
        tags = ["teardown"] + (["fixture"] if fixture else [])

        sessions = {}
        for session in record["sessions"]:
            observed = parse_time(session["observed_at"])
            if observed > as_of + CLOCK_SKEW:
                self.gaps.append(Gap("rejected-observation",
                                     f"session {session['id']} is dated "
                                     f"{session['observed_at']}, after the scan; refused",
                                     source_id=rid))
                continue
            fresh = (as_of - observed) <= timedelta(days=ttl_days)
            if not fresh:
                self.gaps.append(Gap("stale-source", f"session {session['id']} observed "
                                     f"{session['observed_at']}, older than {ttl_days} days",
                                     source_id=rid, platform=session.get("platform")))
            evidence = {
                "source_uri": session["source_uri"],
                "source_kind": session["source_kind"],
                "observed_at": format_time(observed),
                "excerpt": session["note"],
                "method": session["method"],
                "session_id": session["id"],
            }
            if session.get("capture_uri"):
                evidence["capture_uri"] = session["capture_uri"]
            how = {"played": "played", "listing": "read the listing of",
                   "store-page": "read the store page of", "screenshot": "captured",
                   "video": "recorded"}[session["method"]]
            detail = ", ".join(x for x in (session.get("viewport"),
                                           f"{session['runs']} runs" if session.get("runs")
                                           else None) if x)
            statement = (f"{session['observer']} {how} {record['name']}"
                         + (f" on {session['platform']}" if session.get("platform") else "")
                         + (f" ({detail})" if detail else "")
                         + f" on {format_time(observed)[:10]}.")
            cid = self.book.record(_cid("session", rid, session["id"]), {
                "statement": statement, "tier": "observed",
                "confidence": CONFIDENCE_SESSION if fresh else CONFIDENCE_STALE,
                "evidence": [evidence], "parents": [],
                "subject": _subject(game=rid, platform=session.get("platform")),
                "tags": sorted(set(tags + ["session", session["method"]])),
            })
            sessions[session["id"]] = (session, evidence, cid, fresh)
            game.claim_refs.add(cid)
            game.sessions += 1
            if session["method"] != "listing":
                game.depth = "teardown"
            if session.get("platform"):
                game.listings.append({"platform": session["platform"],
                                      "list": f"teardown:{session['method']}",
                                      "list_kind": "category", "claim": cid,
                                      "observed_at": format_time(observed)})

        for index, item in enumerate(record["observations"]):
            if item["session"] not in sessions:
                self.gaps.append(Gap("rejected-observation",
                                     f"{rid} observation {index} names unknown or refused "
                                     f"session {item['session']!r}", source_id=rid))
                continue
            facet, value = item["facet"], item["value"]
            problem = self.vocabulary.check(facet, value)
            if problem:
                self.gaps.append(Gap("unmapped-vocabulary",
                                     f"{rid} observation {index}: {problem}; not counted",
                                     source_id=rid))
                continue
            if not item["excerpt"].strip():
                self.gaps.append(Gap("rejected-observation",
                                     f"{rid} observation {index} has no excerpt", source_id=rid))
                continue
            session, evidence, session_claim, fresh = sessions[item["session"]]
            if isinstance(value, list):
                value = sorted(set(value))
            statement = item.get("statement") or self._statement(record["name"], facet, value)
            subject = _subject(game=rid, facet=facet, platform=session.get("platform"),
                               **_facet_subject(facet, value))
            if item["coding"] == "observed":
                coding_evidence = dict(evidence, excerpt=item["excerpt"])
                cid = self.book.record(_cid("coding", rid, index, facet, value), {
                    "statement": statement, "tier": "observed",
                    "confidence": CONFIDENCE_SESSION if fresh else CONFIDENCE_STALE,
                    "evidence": [coding_evidence], "parents": [], "subject": subject,
                    "tags": sorted(set(tags + ["coding"])),
                })
                tier = "observed"
            else:
                cid = self.book.derived(
                    ("coding", rid, index, facet, json.dumps(value)),
                    f"{statement} (interpreted from session {session['id']}: "
                    f"{item['excerpt']})", [session_claim], subject,
                    tags=tags + ["coding", "interpreted"])
                tier = "derived"
            game.code(facet, value, tier, cid)

        for index, note in enumerate(record.get("notes") or []):
            session = sessions.get(note["session"])
            if session is None:
                continue
            cid = self.book.record(_cid("note", rid, index), {
                "statement": note["statement"], "tier": "observed",
                "confidence": CONFIDENCE_SESSION if session[3] else CONFIDENCE_STALE,
                "evidence": [dict(session[1], excerpt=note["excerpt"])], "parents": [],
                "subject": _subject(game=rid), "tags": sorted(set(tags + ["note", note["kind"]])),
            })
            game.claim_refs.add(cid)

    def _statement(self, name, facet, value):
        spec = self.vocabulary.facet(facet)
        if spec["kind"] == "number":
            return f"{name}: {spec['label'].lower()} {value:g} {spec['unit']}."
        values = value if isinstance(value, list) else [value]
        labels = ", ".join(self.vocabulary.label(facet, v) for v in values)
        return f"{name}: {spec['label'].lower()} is {labels}."

    # -- listings ---------------------------------------------------------------------------

    def add_listings(self, observations):
        """observations: [(Observation, observed claim id)] from snapshots. Reads the
        reference_title and category facts; everything else is the platform analysis's."""
        for obs, cid in observations:
            for key, value in obs.facts.items():
                if key == "reference_title":
                    self._listing(obs, cid, value)
                elif key == "category":
                    self._category(obs, cid, value)

    def _listing(self, obs, cid, fact):
        name = str(fact.get("name") or "").strip()
        platform = obs.platform
        if not name or not platform:
            return
        observed_at = format_time(obs.source.observed_at)
        list_name = str(fact.get("list") or "unnamed list")
        kind = self.config.list_kind(list_name, fact.get("list_kind"))
        gid = self.by_name.get(_norm(name)) or game_id_for(name)
        fixture = "fixture" in (obs.tags or []) or "fixtures.invalid" in str(obs.source.source_uri)
        game = self.games.get(gid)
        if game is None:
            game = self.games[gid] = Game(gid, name, fixture)
            self.by_name.setdefault(_norm(name), gid)
        frame_id = f"{platform}|{list_name}|{observed_at[:10]}"
        frame = self.frames.setdefault(frame_id, {
            "id": "frame-" + hashlib.sha256(frame_id.encode()).hexdigest()[:10],
            "platform": platform, "list": list_name, "list_kind": kind,
            "observed_at": observed_at, "titles": [], "claim_refs": [],
            "scope": self._list_scope(list_name)})
        if gid not in frame["titles"]:
            frame["titles"].append(gid)
        if cid not in frame["claim_refs"]:
            frame["claim_refs"].append(cid)
        game.listings.append({"platform": platform, "list": list_name, "list_kind": kind,
                              "claim": cid, "observed_at": observed_at})
        game.claim_refs.add(cid)

        slug = str(fact.get("genre") or "").strip()
        node = self.vocabulary.genre_for(slug) if slug else None
        if slug and node is None:
            self.gaps.append(Gap("unmapped-vocabulary",
                                 f"genre {slug!r} of listed title {name!r} is not in the "
                                 f"research vocabulary; the title is counted without a genre",
                                 source_id=obs.source.id, platform=platform))
        scope = frame["scope"]
        if node is None and scope:
            node = scope
        if node:
            coded = self.book.derived(
                ("listing-genre", gid, cid, node),
                f"{name} is coded {self.vocabulary.genres[node]['label']} ({node}) from its "
                f"listing on {platform} ('{list_name}'"
                + (f", listed genre '{slug}'" if slug else "") + ").",
                [cid], _subject(game=gid, facet="genre", genre=node, platform=platform),
                tags=["coding", "listing"] + (["fixture"] if fixture else []))
            game.code("genre", node, "derived", coded)

    def _list_scope(self, list_name):
        """The genre node a list is scoped to, read from its name ('category:puzzle
        most-popular' -> puzzle; 'category:puzzle merge-puzzles-top' -> merge-puzzle), or
        None for an unscoped list. The most specific node named wins: a list of merge games
        inside the puzzle category is a merge list."""
        text = _norm(list_name).replace("category:", " ").replace("_", " ")
        spaced = [t for t in re.split(r"[\s/|]+", text) if t]
        hyphened = [t for t in re.split(r"[\s/|-]+", text) if t]
        best = None
        for tokens in (spaced, hyphened):
            for size in (3, 2, 1):
                for i in range(len(tokens) - size + 1):
                    node = self.vocabulary.genre_for(" ".join(tokens[i:i + size]))
                    if node and (best is None or self.vocabulary.depth(node) >
                                 self.vocabulary.depth(best)):
                        best = node
        return best

    def _category(self, obs, cid, fact):
        slug = str(fact.get("genre") or "").strip()
        count = fact.get("game_count")
        node = self.vocabulary.genre_for(slug) or self.vocabulary.genre_for(fact.get("name"))
        if node is None:
            self.gaps.append(Gap("unmapped-vocabulary",
                                 f"category {fact.get('name')!r} ({slug!r}) is not in the "
                                 f"research vocabulary; its count is not used",
                                 source_id=obs.source.id, platform=obs.platform))
            return
        if isinstance(count, bool) or not isinstance(count, (int, float)) or not obs.platform:
            return
        self.supply.append({"platform": obs.platform, "genre": node, "count": count,
                            "claim": cid, "name": str(fact.get("name") or slug)})

    # -- views ------------------------------------------------------------------------------

    def finish(self):
        """Gaps that describe the corpus as a whole."""
        fixtures = sorted(g.id for g in self.games.values() if g.fixture)
        if fixtures:
            self.gaps.append(Gap("fixture-evidence",
                                 f"{len(fixtures)} game(s) come from fixture records - test "
                                 f"data, never real evidence: {', '.join(fixtures[:6])}"))
        teardown = [g for g in self.games.values() if g.depth == "teardown"]
        if self.games and not teardown:
            self.gaps.append(Gap("uncoded-facet",
                                 f"all {len(self.games)} games are known only from listings: "
                                 f"genre and platform are coded; how they play (mechanics, "
                                 f"loop, session, theme, art, monetization) is not. Add "
                                 f"teardowns under games/ (core/craft/competitive-teardown.md)"))

    def sorted_games(self):
        return [self.games[g] for g in sorted(self.games)]

    def describe(self):
        games = self.sorted_games()
        return {
            "vocabulary": self.vocabulary.describe(),
            "analysis": self.config.describe(),
            "games": len(games),
            "teardown_games": sum(1 for g in games if g.depth == "teardown"),
            "listing_games": sum(1 for g in games if g.depth == "listing"),
            "fixture_games": sum(1 for g in games if g.fixture),
            "sessions": sum(g.sessions for g in games),
        }


def _cid(*parts):
    digest = hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False,
                                       default=str).encode("utf-8")).hexdigest()
    return "claim-" + digest[:10]


def _subject(**fields):
    return {k: v for k, v in fields.items() if isinstance(v, str) and v}


def _facet_subject(facet, value):
    if not isinstance(value, str):
        return {}
    if facet == "genre":
        return {"genre": value}
    if facet == "theme":
        return {"theme": value}
    if facet in ("player_fantasy", "emotional_fantasy"):
        return {"fantasy": value}
    if facet.startswith("art_") or facet in ("camera", "animation"):
        return {"art": value}
    if facet == "audience_type":
        return {"audience": value}
    return {}
