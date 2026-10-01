"""From evidence to claims, platform summaries, screened candidates and one selection.

Pure functions of their inputs: no clock, no filesystem, no network. The step reads the
world and hands it in; everything here is deterministic, which is what lets the tests pin
the output exactly and lets two scans over the same corpus be recognised as the same scan.

The discipline, mechanised:

  * an external observation becomes an `observed` claim, one per statement, carrying its
    source and verbatim excerpt;
  * what the factory's own unverified platform profiles say becomes a `hypothesis` - and
    only for the facts no external source covered;
  * every interpretation (SDK complexity, platform fit, distribution) is a `derived` claim
    naming its parents, never folded into the observation it came from;
  * the catalog's estimates are `hypothesis` claims, and every dimension resting on one is
    screened at the scoring model's hypothesis weight;
  * revenue is not estimated. `revenue_potential` is recorded as unscored, with the reason.

With a brief - the game idea a person started the run with - candidates are ranked by how
well they match it before anything else (`idea_match`): first how many of its words the
archetype's own vocabulary holds - the genre and mechanic are the game - then the dimension
it names ("3D"), which design can still adapt. The screen itself is unchanged. A selection
that holds none of the brief's words, or renders in another dimension than it names, says so
as an `idea-unmatched` gap instead of pretending to fit.
"""

import hashlib
import json
import math
import re

from wgflib import criteria

__all__ = ["ClaimBook", "analyse", "claim_id", "idea_match", "idea_terms", "idea_dimension"]

CONFIDENCE_OBSERVED = 0.85
CONFIDENCE_STALE = 0.6
CONFIDENCE_PROFILE = 0.5
CONFIDENCE_ESTIMATE = 0.4
CONFIDENCE_THESIS = 0.35
CONFIDENCE_DERIVED_MAX = 0.7

FIT_VIABLE = 0.5
REPLAYABILITY = {"low": 0.3, "medium": 0.6, "high": 0.9}
# Saturation constant for turning an observed category size into a competition ratio:
# count / (count + K). An interpretation, so the claim that uses it is derived and says so.
COMPETITION_K = 500
TIER_RANK = {"hypothesis": 0, "derived": 1, "observed": 2}
PLATFORM_FACTS = ("ads.rewarded", "ads.interstitial", "ads.banner", "iap", "max_bundle_mb",
                  "locales_required", "sdk_required", "review_days", "mobile_share",
                  "cloud_saves", "external_requests_restricted")


# -- the brief ---------------------------------------------------------------------------------

_IDEA_WORD = re.compile(r"[a-z0-9][a-z0-9-]*")
# Words that describe any game, or no game: they match nothing, whatever the catalog says.
_IDEA_STOP = frozenset("""
    a an and are as at be by for from game games has have in into is it its of on one or
    player players play plays playing the their them then there they this to where which
    while who with without you your web browser mobile simple casual fun new
""".split())
_DIMENSION_WORDS = {"3d": "3d", "three-dimensional": "3d", "2d": "2d", "two-dimensional": "2d"}


def idea_terms(idea):
    """The brief's content words, lowercased, in order, without repeats or dimension words.
    Whole words only: a brief's "blocks" is not the catalog's "block"."""
    seen = []
    for word in _IDEA_WORD.findall((idea or "").lower()):
        if word in _IDEA_STOP or word in _DIMENSION_WORDS or len(word) < 3 or word in seen:
            continue
        seen.append(word)
    return seen


def idea_dimension(idea):
    """'3d' or '2d' when the brief names exactly one, else None."""
    named = {_DIMENSION_WORDS[w] for w in _IDEA_WORD.findall((idea or "").lower())
             if w in _DIMENSION_WORDS}
    return named.pop() if len(named) == 1 else None


def _vocabulary(archetype):
    words = set()
    for value in ([archetype.get("genre"), archetype.get("subgenre"), archetype.get("title"),
                   archetype.get("core_mechanic")] + list(archetype.get("market_tags") or [])):
        for word in _IDEA_WORD.findall(str(value or "").lower()):
            words.add(word)
            words.update(part for part in word.split("-") if part)
    return words


def idea_match(archetype, idea):
    """{"terms": the brief's words the archetype's vocabulary holds, "dimension": whether its
    rendering is the dimension the brief names (False when it names none)}."""
    vocabulary = _vocabulary(archetype)
    dimension = idea_dimension(idea)
    return {"terms": [t for t in idea_terms(idea) if t in vocabulary],
            "dimension": dimension is not None
            and (archetype.get("rendering") or "2d") == dimension}


def _idea_rank(candidate, dimension):
    """Sort key part: more of the brief's words first, then a shape of the dimension it
    names before one of another."""
    match = candidate.get("idea_match")
    if match is None:
        return (0, 0)
    return (-len(match["terms"]), dimension is not None and not match["dimension"])


class SupportError(ValueError):
    """A derived statistic without a valid count behind it. A share with no denominator is
    a number nobody can check, so it is refused rather than reported."""


def check_support(support, key="?"):
    """The support block of a counting claim, validated: a denominator of at least one, a
    numerator no larger, members that are exactly the numerator, no member also an
    exception, and a frame saying what was counted over."""
    if not isinstance(support, dict):
        raise SupportError(f"{key}: support must be an object")
    numerator, denominator = support.get("numerator"), support.get("denominator")
    members = list(support.get("members") or [])
    exceptions = list(support.get("exceptions") or [])
    for name, value in (("numerator", numerator), ("denominator", denominator)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise SupportError(f"{key}: support.{name} must be an integer, got {value!r}")
    if denominator < 1:
        raise SupportError(f"{key}: a share needs a denominator of at least 1")
    if not 0 <= numerator <= denominator:
        raise SupportError(f"{key}: numerator {numerator} is outside 0..{denominator}")
    if len(set(members)) != numerator:
        raise SupportError(f"{key}: {len(set(members))} members for a numerator of "
                           f"{numerator}")
    if set(members) & set(exceptions):
        raise SupportError(f"{key}: an id is both a member and an exception")
    if exceptions and numerator + len(set(exceptions)) != denominator:
        raise SupportError(f"{key}: members and exceptions do not add up to the denominator")
    if not str(support.get("frame") or "").strip():
        raise SupportError(f"{key}: support names no frame")
    out = {"numerator": numerator, "denominator": denominator, "members": sorted(set(members)),
           "frame": str(support["frame"])}
    if exceptions:
        out["exceptions"] = sorted(set(exceptions))
    if support.get("unknown"):
        out["unknown"] = sorted(set(support["unknown"]))
    return out


def claim_id(*parts):
    digest = hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False)
                            .encode("utf-8")).hexdigest()
    return "claim-" + digest[:10]


def _round(value, places=4):
    return None if value is None else round(float(value), places)


def _yes(value):
    return "yes" if value else "no"


class ClaimBook:
    """Every claim the scan makes, keyed by a deterministic id."""

    def __init__(self, asserted_at, role="research"):
        self.asserted_at = asserted_at
        self.role = role
        self.claims = {}

    def _add(self, cid, body):
        body = dict(body)
        body.update({"id": cid, "asserted_at": self.asserted_at, "asserted_by": self.role,
                     "superseded_by": None})
        self.claims.setdefault(cid, body)
        return cid

    def observed(self, obs, as_of_text):
        source = obs.source
        evidence = {
            "source_uri": source.source_uri,
            "source_kind": source.source_kind,
            "observed_at": as_of_text(source.observed_at),
            "excerpt": obs.excerpt,
        }
        if obs.metric:
            evidence["metric"] = {k: obs.metric[k] for k in ("name", "value", "unit")
                                  if k in obs.metric}
        return self._add(claim_id("observed", source.id, obs.index, obs.statement), {
            "statement": obs.statement,
            "tier": "observed",
            "confidence": CONFIDENCE_OBSERVED if source.fresh else CONFIDENCE_STALE,
            "evidence": [evidence],
            "parents": [],
            "subject": dict(obs.subject),
            "tags": sorted(set(obs.tags) | {source.collector}),
        })

    def hypothesis(self, key, statement, subject, evidence=(), confidence=0.5, tags=()):
        return self._add(claim_id("hypothesis", key, statement), {
            "statement": statement,
            "tier": "hypothesis",
            "confidence": min(confidence, 0.6),
            "evidence": list(evidence),
            "parents": [],
            "subject": subject,
            "tags": sorted(set(tags)),
        })

    def derived(self, key, statement, parents, subject, tags=(), support=None):
        parents = sorted(set(parents))
        if not parents:
            raise ValueError(f"derived claim {key!r} has no parents")
        tags = set(tags)
        if "pattern" in tags and support is None:
            raise ValueError(f"pattern claim {key!r} states no numerator and denominator")
        confidence = min([CONFIDENCE_DERIVED_MAX]
                         + [self.claims[p]["confidence"] for p in parents if p in self.claims])
        body = {
            "statement": statement,
            "tier": "derived",
            "confidence": confidence,
            "evidence": [],
            "parents": parents,
            "subject": subject,
            "tags": sorted(tags),
        }
        if support is not None:
            body["support"] = check_support(support, key)
        return self._add(claim_id("derived", key, statement), body)

    def record(self, cid, body):
        """A claim built elsewhere (a teardown session or coding): kept as built."""
        return self._add(cid, body)

    def tier(self, cid):
        return self.claims[cid]["tier"]

    def rests_on_observation(self, cid, _seen=None):
        """Whether any ancestor of this claim (or the claim itself) is observed."""
        claim = self.claims[cid]
        if claim["tier"] == "observed":
            return True
        seen = _seen if _seen is not None else set()
        for parent in claim["parents"]:
            if parent not in seen:
                seen.add(parent)
                if self.rests_on_observation(parent, seen):
                    return True
        return False

    def closure(self, ids):
        """ids plus every ancestor, so an emitted claim never names a missing parent."""
        out, stack = set(), list(ids)
        while stack:
            cid = stack.pop()
            if cid in out or cid not in self.claims:
                continue
            out.add(cid)
            stack.extend(self.claims[cid]["parents"])
        return out


# -- platforms ------------------------------------------------------------------------------


def _profile_facts(pid, profile):
    capabilities = profile.get("capabilities") or {}
    requirements = profile.get("requirements") or {}
    ads = profile.get("ads") or {}
    formats = capabilities.get("ads") or []
    sdk = any(
        (a.get("check") or {}).get("left") == "package.platform_sdk"
        and (a.get("check") or {}).get("op") == "eq"
        and (a.get("check") or {}).get("right") == pid
        for a in profile.get("assertions") or []
    )
    return {
        "ads.rewarded": "rewarded" in formats or bool(ads.get("rewarded_available")),
        "ads.interstitial": "interstitial" in formats,
        "ads.banner": "banner" in formats or bool(ads.get("banner_available")),
        "iap": bool(capabilities.get("iap")),
        "max_bundle_mb": requirements.get("max_bundle_mb"),
        "locales_required": list(requirements.get("locales_required") or []),
        "sdk_required": sdk,
        "review_days": list((profile.get("review") or {}).get("typical_days") or []),
        "mobile_share": ((profile.get("audience") or {}).get("device_mix") or {}).get("mobile"),
        "cloud_saves": bool(capabilities.get("cloud_saves")),
        "external_requests_restricted": requirements.get("external_requests") == "restricted",
    }


def _describe(key, value):
    labels = {
        "ads.rewarded": "rewarded ads", "ads.interstitial": "interstitial ads",
        "ads.banner": "banner ads", "iap": "in-app purchases",
        "sdk_required": "portal SDK required", "cloud_saves": "cloud saves",
        "external_requests_restricted": "external requests restricted",
    }
    if key in labels:
        return f"{labels[key]} {_yes(value)}"
    if key == "max_bundle_mb":
        return "no bundle limit" if value is None else f"max bundle {value} MB"
    if key == "locales_required":
        return f"required locales {', '.join(value) or 'none'}"
    if key == "review_days":
        return f"review {value[0]}-{value[-1]} days" if value else "review time unknown"
    if key == "mobile_share":
        return f"mobile share {value}"
    return f"{key} {value}"


class PlatformView:
    """What one platform allows and demands: observed facts first, profile to fill gaps."""

    def __init__(self, pid, profile):
        self.id = pid
        self.profile = profile
        self.profile_facts = _profile_facts(pid, profile)
        self.observed = {}          # key -> [(value, claim id)]
        self.categories = {}        # genre slug -> [claim id]
        self.category_counts = {}   # genre slug -> [(count, claim id)]
        self.titles = []            # (name, genre, claim id)
        self.profile_claim = None
        self.discrepancies = []

    def value(self, key):
        if self.observed.get(key):
            return self.observed[key][0][0]
        return self.profile_facts.get(key)

    def support(self, key):
        """Claim ids a value rests on: the observations, else the profile claim."""
        if self.observed.get(key):
            return [cid for _v, cid in self.observed[key]]
        return [self.profile_claim] if self.profile_claim else []

    @property
    def verified(self):
        return self.profile.get("status") == "verified"


def _build_platforms(book, profiles, observations, as_of_text, gaps_out):
    views = {pid: PlatformView(pid, profile) for pid, profile in profiles.items()}

    for obs, cid in observations:
        view = views.get(obs.platform)
        for key, value in obs.facts.items():
            if key == "category":
                slug = str(value.get("genre") or "").strip().lower()
                if view is not None and slug:
                    view.categories.setdefault(slug, []).append(cid)
                    if isinstance(value.get("game_count"), (int, float)) and \
                            not isinstance(value.get("game_count"), bool):
                        view.category_counts.setdefault(slug, []).append(
                            (value["game_count"], cid))
            elif key == "reference_title":
                name = str(value.get("name") or "").strip()
                if view is not None and name:
                    view.titles.append((name, str(value.get("genre") or "").lower(), cid))
            elif key in ("monthly_players", "mobile_support_expected"):
                continue  # recorded as claims; not used for fit
            elif view is not None:
                view.observed.setdefault(key, []).append((value, cid))

    for pid, view in sorted(views.items()):
        profile = view.profile
        uncovered = [k for k in PLATFORM_FACTS if not view.observed.get(k)]
        if uncovered:
            listed = "; ".join(_describe(k, view.profile_facts[k]) for k in uncovered)
            version = profile.get("version", "?")
            status = profile.get("status", "unverified")
            evidence = [{
                "source_uri": profile.get("_path") or f"core/reference/platforms/{pid}.yaml",
                "source_kind": "other",
                "observed_at": as_of_text(None),
                "excerpt": f"id: {pid}, version: {version}, status: {status}",
            }]
            statement = (f"The factory's {status} platform profile {pid}@{version} lists: "
                         f"{listed}.")
            subject = {"platform": pid, "dimension": "platform_fit"}
            if view.verified:
                view.profile_claim = book._add(claim_id("profile", pid, statement), {
                    "statement": statement, "tier": "observed", "confidence": 0.8,
                    "evidence": evidence, "parents": [], "subject": subject,
                    "tags": ["platform-profile"],
                })
            else:
                view.profile_claim = book.hypothesis(
                    ("profile", pid), statement, subject, evidence=evidence,
                    confidence=CONFIDENCE_PROFILE, tags=["platform-profile", "unverified"])
                gaps_out.append(("unverified-profile",
                                 f"{pid}@{version} is unverified; {len(uncovered)} of "
                                 f"{len(PLATFORM_FACTS)} platform facts rest on it alone",
                                 pid))
        for key, values in view.observed.items():
            profile_value = view.profile_facts.get(key)
            for value, _cid in values:
                if profile_value is not None and value != profile_value and not (
                        isinstance(value, list) and sorted(value) == sorted(profile_value)):
                    note = (f"{key}: source says {value!r}, profile {pid}@"
                            f"{profile.get('version')} says {profile_value!r}")
                    if note not in view.discrepancies:
                        view.discrepancies.append(note)
                        gaps_out.append(("profile-discrepancy", note, pid))
    return views


def _sdk_complexity(view):
    score = (1 if view.value("sdk_required") else 0)
    score += (1 if view.value("ads.interstitial") else 0)
    score += (1 if view.value("ads.rewarded") else 0)
    score += (0.5 if view.value("ads.banner") else 0)
    score += (2 if view.value("iap") else 0)
    score += (0.5 if view.value("cloud_saves") else 0)
    return "low" if score <= 2 else "medium" if score <= 4 else "high"


def _verification_risk(view):
    profile = view.profile
    score = 0
    review = view.value("review_days") or []
    if review:
        score += 2 if review[-1] >= 14 else 1 if review[-1] >= 7 else 0
    locales = view.value("locales_required") or []
    if any(loc != "en" for loc in locales):
        score += 1
    if len((profile.get("review") or {}).get("common_rejections") or []) >= 4:
        score += 1
    blocking = [a for a in profile.get("assertions") or [] if a.get("severity") == "blocking"]
    if len(blocking) >= 5:
        score += 1
    if (profile.get("requirements") or {}).get("quality_guidelines") == "enforced":
        score += 1
    return "low" if score <= 1 else "medium" if score <= 3 else "high"


def _platform_claims(book, view):
    parents = set()
    for key in ("sdk_required", "ads.interstitial", "ads.rewarded", "ads.banner", "iap",
                "cloud_saves"):
        parents.update(view.support(key))
    sdk = _sdk_complexity(view)
    sdk_claim = book.derived(
        ("sdk", view.id),
        f"Integrating {view.id} is {sdk} SDK complexity: portal SDK required "
        f"{_yes(view.value('sdk_required'))}, interstitial {_yes(view.value('ads.interstitial'))}, "
        f"rewarded {_yes(view.value('ads.rewarded'))}, banner {_yes(view.value('ads.banner'))}, "
        f"IAP {_yes(view.value('iap'))}.",
        parents, {"platform": view.id, "dimension": "technical_risk"}, tags=["sdk"])

    parents = set()
    for key in ("review_days", "locales_required"):
        parents.update(view.support(key))
    if view.profile_claim:
        parents.add(view.profile_claim)
    risk = _verification_risk(view)
    review = view.value("review_days") or []
    verify_claim = book.derived(
        ("verification", view.id),
        f"Getting a build accepted on {view.id} carries {risk} verification risk "
        f"(review {'-'.join(str(d) for d in review) or 'unknown'} days, required locales "
        f"{', '.join(view.value('locales_required') or []) or 'none'}).",
        parents, {"platform": view.id, "dimension": "time_to_market"}, tags=["verification"])
    return sdk, sdk_claim, risk, verify_claim


def _platform_summary(view, sdk, sdk_claim, risk, verify_claim):
    ads = [f for f in ("interstitial", "rewarded", "banner") if view.value(f"ads.{f}")]
    profile = view.profile
    constraints = {
        "max_bundle_mb": view.value("max_bundle_mb"),
        "locales_required": list(view.value("locales_required") or []),
        "orientation": list((profile.get("requirements") or {}).get("orientation") or []),
        "mobile_share": view.value("mobile_share"),
        "interstitial_min_interval_s": (profile.get("ads") or {}).get(
            "interstitial_min_interval_s"),
        "review_days": list(view.value("review_days") or []),
        "web_exclusive": view.value("web_exclusive"),
    }
    loading = (profile.get("requirements") or {}).get("loading_api")
    if loading:
        constraints["loading_api"] = loading
    refs = set(view.support("ads.rewarded")) | {sdk_claim, verify_claim}
    for key in PLATFORM_FACTS:
        refs.update(view.support(key))
    refs.update(cid for values in view.observed.values() for _value, cid in values)
    summary = {
        "platform": view.id,
        "profile_version": str(profile.get("version", "")),
        "profile_status": str(profile.get("status", "unverified")),
        "monetization": {"ads": ads, "rewarded": bool(view.value("ads.rewarded")),
                         "iap": bool(view.value("iap"))},
        "constraints": constraints,
        "sdk_complexity": sdk,
        "verification_risk": risk,
        "discoverability": {"categories": sorted(view.categories),
                            "reference_titles": len(view.titles)},
        "claim_refs": sorted(r for r in refs if r),
    }
    if view.discrepancies:
        summary["discrepancies"] = list(view.discrepancies)
    return summary


# -- candidates -----------------------------------------------------------------------------


def _fit(archetype, view, sdk, risk):
    """(fit 0..1, blockers, concerns, fact keys read). Blockers are rules a portal enforces;
    concerns are costs. The numbers are the screen's weighting, not a measurement."""
    fit, blockers, concerns, read = 1.0, [], [], set()
    monetization = archetype["monetization"]
    supported = {"rewarded": view.value("ads.rewarded"),
                 "interstitial": view.value("ads.interstitial"),
                 "banner": view.value("ads.banner"), "iap": view.value("iap"), "none": True}
    read.update({"ads.rewarded", "ads.interstitial", "ads.banner", "iap"})
    if not supported.get(monetization["primary"], False):
        blockers.append(f"primary monetization '{monetization['primary']}' is not supported")
        fit -= 0.5
    for extra in monetization.get("secondary") or []:
        if not supported.get(extra, False):
            concerns.append(f"secondary monetization '{extra}' is not supported")
            fit -= 0.05

    limit = view.value("max_bundle_mb")
    read.add("max_bundle_mb")
    if limit is not None and archetype["bundle_mb"] > limit:
        blockers.append(f"estimated bundle {archetype['bundle_mb']} MB exceeds {limit} MB")
        fit -= 0.6
    elif limit is not None and archetype["bundle_mb"] > 0.5 * limit:
        concerns.append(f"estimated bundle {archetype['bundle_mb']} MB is over half the "
                        f"{limit} MB limit")
        fit -= 0.1

    locales = [loc for loc in view.value("locales_required") or [] if loc != "en"]
    read.add("locales_required")
    if locales:
        if archetype.get("text_heavy"):
            concerns.append(f"text-heavy design must be localized into {', '.join(locales)}")
            fit -= 0.2
        else:
            concerns.append(f"requires {', '.join(locales)} localization")
            fit -= 0.05

    mobile = view.value("mobile_share")
    read.add("mobile_share")
    if mobile is not None and mobile >= 0.6 and not archetype.get("mobile_ready"):
        concerns.append("the audience is mostly mobile and the design is not")
        fit -= 0.25
    if archetype.get("rendering") == "3d" and limit is not None and limit <= 50:
        concerns.append("3D on a portal whose limits assume low-end mobile")
        fit -= 0.15
    if archetype.get("needs_cloud_save") and not view.value("cloud_saves"):
        read.add("cloud_saves")
        concerns.append("progress relies on local storage; no portal cloud save")
        fit -= 0.05
    if view.value("web_exclusive"):
        read.add("web_exclusive")
        concerns.append("requires web exclusivity: publishing here rules out other web portals")
        fit -= 0.05
    if archetype.get("multiplayer"):
        concerns.append("realtime multiplayer needs its own server")
        fit -= 0.1
        if view.value("external_requests_restricted"):
            read.add("external_requests_restricted")
            concerns.append("the portal restricts external network requests")
            fit -= 0.15
    if sdk == "high":
        fit -= 0.05
    if risk == "high":
        fit -= 0.1
    elif risk == "medium":
        fit -= 0.03
    return max(0.0, min(1.0, round(fit, 4))), blockers, concerns, read


def _normalize(value, spec):
    kind = spec.get("type")
    if value is None:
        return None
    if kind == "ordinal":
        levels = spec.get("levels") or []
        return float(spec["scores"][levels.index(value)]) if value in levels else None
    if kind == "band":
        for band in spec.get("bands") or []:
            if value <= band["max"]:
                return float(band["score"])
        return float(spec["bands"][-1]["score"]) if spec.get("bands") else None
    lo, hi = float(spec["min"]), float(spec["max"])
    transform = (lambda x: math.log1p(max(x, 0.0))) if kind == "log" else (lambda x: x)
    span = transform(hi) - transform(lo)
    if span == 0:
        return None
    return max(0.0, min(1.0, (transform(float(value)) - transform(lo)) / span))


def _weakest(tiers):
    return min(tiers, key=lambda t: TIER_RANK[t]) if tiers else "hypothesis"


def _screen(dimensions, model):
    policy = model.get("evidence_policy") or {}
    multiplier = float(policy.get("hypothesis_weight_multiplier", 0.5))
    total = sum(float(d.get("weight", 0)) for d in model.get("dimensions") or [])
    scored = effective = weighted = evidenced = 0.0
    for dim in dimensions:
        weight = dim.get("weight", 0)
        if dim.get("normalized") is None or not weight:
            continue
        w = weight * (multiplier if dim["tier"] == "hypothesis" else 1.0)
        scored += weight
        effective += w
        weighted += w * dim["normalized"]
        if dim["tier"] != "hypothesis":
            evidenced += weight
    return {
        "score": _round(weighted / effective if effective else 0.0),
        "weight_coverage": _round(scored / total if total else 0.0),
        "evidence_coverage": _round(evidenced / scored if scored else 0.0),
    }


def _vetoes(model, raw):
    results = []
    for veto in model.get("vetoes") or []:
        try:
            result = criteria.evaluate_named(veto, raw)
            entry = {"criterion_id": veto["id"], "breached": bool(result["breached"]),
                     "measured": result.get("measured")}
        except (criteria.Unevaluable, criteria.CriteriaError) as exc:
            entry = {"criterion_id": veto["id"], "breached": None,
                     "note": f"not evaluable: {exc}"}
        results.append(entry)
    return results


# Backlog states that mean somebody already acted on an opportunity. A `discovered` one is
# only a proposal a scan persisted (Research V2 keeps every opportunity it proposes): finding
# it again refreshes it rather than excluding the shape as a duplicate of itself.
ACTED_ON = ("scored", "shortlisted", "approved", "promoted", "parked", "stale", "rejected")


def _backlog_match(archetype, backlog):
    for opp in backlog:
        if opp.get("state") not in ACTED_ON:
            continue
        concept = opp.get("concept") or {}
        same_genre = (concept.get("genre") or "").lower() == archetype["genre"]
        same_kind = ((concept.get("subgenre") or "").lower() == archetype["subgenre"]
                     or (concept.get("core_mechanic") or "").lower()
                     == archetype["core_mechanic"].lower())
        if same_genre and same_kind:
            return {"opportunity_id": opp.get("id"), "state": opp.get("state")}
    return None


def _candidate(book, archetype, views, platform_info, model, backlog, report_key):
    aid = archetype["id"]
    tags = set(archetype.get("market_tags") or [])
    subject = {"genre": archetype["genre"], "mechanic": archetype["subgenre"]}
    monetization = archetype["monetization"]

    estimate = book.hypothesis(
        ("estimate", aid),
        f"The factory's catalog estimates a {archetype['title']} prototype at "
        f"{archetype['dev_speed_days']} dev days, ${archetype['asset_cost_usd']} assets, "
        f"{archetype['technical_complexity']} technical and {archetype['asset_complexity']} "
        f"asset complexity, {archetype['session_seconds']} s sessions and a "
        f"{archetype['bundle_mb']} MB bundle. Unmeasured.",
        dict(subject, dimension="dev_speed_days"), confidence=CONFIDENCE_ESTIMATE,
        tags=["estimate", "catalog"])
    priors_claim = book.hypothesis(
        ("priors", aid),
        f"Unmeasured catalog priors for {archetype['title']}: " + ", ".join(
            f"{k} {v}" for k, v in sorted((archetype.get("priors") or {}).items())) + ".",
        dict(subject, dimension="retention_potential"), confidence=CONFIDENCE_ESTIMATE,
        tags=["estimate", "catalog"])

    # Platform fit, one derived claim for all platforms.
    fits, fit_parents = [], {estimate}
    for pid in sorted(views):
        view = views[pid]
        sdk, sdk_claim, risk, verify_claim = platform_info[pid]
        fit, blockers, concerns, read = _fit(archetype, view, sdk, risk)
        support = {sdk_claim, verify_claim}
        for key in read:
            support.update(view.support(key))
        fit_parents |= support
        entry = {"platform": pid, "fit": fit, "blockers": blockers,
                 "claim_refs": sorted(s for s in support if s)}
        if concerns:
            entry["concerns"] = concerns
        fits.append(entry)
    fits.sort(key=lambda f: (-f["fit"], f["platform"]))
    fit_claim = book.derived(
        ("fit", aid, report_key),
        f"{archetype['title']} platform fit: " + "; ".join(
            f"{f['platform']} {f['fit']:.2f}" + (f" (blocked: {f['blockers'][0]})"
                                                   if f["blockers"] else "")
            for f in fits) + ".",
        fit_parents, dict(subject, dimension="platform_fit"), tags=["platform-fit"])
    for f in fits:
        f["claim_refs"] = sorted(set(f["claim_refs"]) | {fit_claim})
    best = [f["fit"] for f in fits[:2]]
    platform_fit = sum(best) / len(best) if best else 0.0
    fit_tier = "derived" if book.rests_on_observation(fit_claim) else "hypothesis"
    viable = [f for f in fits if f["fit"] >= FIT_VIABLE and not f["blockers"]]

    # Market signal. A category listing in any of the archetype's tags helps it be found; a
    # reference title only counts when it is the archetype's own kind of game - a generic
    # "puzzle" hit is not evidence that players want block puzzles in particular.
    specific = tags - {archetype["genre"], "casual"} or tags
    refs, market_claims, reference_titles = [], [], []
    present_on = []
    for pid in sorted(views):
        view = views[pid]
        hits = [cid for slug, ids in view.categories.items() if slug in tags for cid in ids]
        titles = [(name, cid) for name, genre, cid in view.titles if genre in specific]
        refs.extend(hits)
        for name, cid in titles:
            market_claims.append(cid)
            if name not in reference_titles:
                reference_titles.append(name)
        if hits or titles:
            present_on.append(pid)
    any_listing = any(view.categories or view.titles for view in views.values())
    distribution = None
    distribution_claim = None
    if any_listing:
        parents = refs + market_claims or [
            cid for view in views.values()
            for cid in [c for ids in view.categories.values() for c in ids]
            + [c for _n, _g, c in view.titles]]
        distribution = len(present_on) / len(views)
        distribution_claim = book.derived(
            ("distribution", aid, report_key),
            f"Among the listings this scan observed, {archetype['title']}-type games "
            f"({', '.join(sorted(specific))}) appear on {len(present_on)} of {len(views)} "
            f"scoped platforms{' (' + ', '.join(present_on) + ')' if present_on else ''}.",
            parents, dict(subject, dimension="distribution_potential"), tags=["market"])
    competition = None
    competition_claim = None
    counts = [(count, cid) for view in views.values()
              for slug, pairs in view.category_counts.items() if slug in tags
              for count, cid in pairs]
    if counts:
        competition = sum(c / (c + COMPETITION_K) for c, _ in counts) / len(counts)
        competition_claim = book.derived(
            ("competition", aid, report_key),
            f"Observed category sizes for {archetype['title']} ({', '.join(str(c) for c, _ in counts)} "
            f"titles) put competition at {competition:.2f} on a count/(count+{COMPETITION_K}) "
            f"scale.",
            [cid for _, cid in counts], dict(subject, dimension="competition"),
            tags=["market"])

    thesis = book.hypothesis(
        ("thesis", aid, report_key),
        f"A {archetype['title']} built for {', '.join(f['platform'] for f in viable) or 'the scoped portals'} "
        f"can ship inside the factory's timebox and monetize through {monetization['primary']} "
        f"placements without breaching any of those portals' rules.",
        dict(subject, dimension="monetization_fit"), confidence=CONFIDENCE_THESIS,
        tags=["thesis"])

    # Dimensions, in the scoring model's vocabulary and with its weights and normalizers.
    priors = archetype.get("priors") or {}
    rewarded_share = (sum(1 for pid in views if {
        "rewarded": views[pid].value("ads.rewarded"),
        "interstitial": views[pid].value("ads.interstitial"),
        "banner": views[pid].value("ads.banner"), "iap": views[pid].value("iap"),
        "none": True}.get(monetization["primary"])) / len(views)) if views else 0.0
    review_max = [views[f["platform"]].value("review_days")[-1] for f in viable
                  if views[f["platform"]].value("review_days")]
    ttm = archetype["dev_speed_days"] + (sum(review_max) / len(review_max) if review_max else 0)
    raw = {
        "revenue_potential": (None, "hypothesis", [], "no attributable revenue evidence; the "
                              "research step does not estimate revenue"),
        "platform_fit": (platform_fit, fit_tier, [fit_claim], None),
        "dev_speed_days": (archetype["dev_speed_days"], "hypothesis", [estimate], None),
        "monetization_fit": (priors.get("monetization_fit", 0) * rewarded_share, "hypothesis",
                             [priors_claim, fit_claim], None),
        "retention_potential": (priors.get("retention_potential"), "hypothesis", [priors_claim], None),
        "scope_complexity": (archetype["technical_complexity"], "hypothesis", [estimate], None),
        "technical_risk": (priors.get("technical_risk"), "hypothesis", [priors_claim], None),
        "asset_cost": (archetype["asset_cost_usd"], "hypothesis", [estimate], None),
        "session_quality": (priors.get("session_quality"), "hypothesis", [priors_claim], None),
        "competition": ((competition, "derived", [competition_claim], None) if competition_claim
                        else (None, "hypothesis", [], "no observed category sizes")),
        "replayability": (REPLAYABILITY.get(archetype["replayability"]), "hypothesis",
                          [estimate], None),
        "performance_risk": (priors.get("performance_risk"), "hypothesis", [priors_claim], None),
        "time_to_market": (ttm, _weakest(["hypothesis", fit_tier]), [estimate, fit_claim], None),
        "iterability": (priors.get("iterability"), "hypothesis", [priors_claim], None),
        "distribution_potential": ((distribution, "derived", [distribution_claim], None)
                                   if distribution_claim else
                                   (None, "hypothesis", [], "no category listings observed")),
    }
    weights = {d["id"]: d for d in model.get("dimensions") or []}
    dimensions = []
    for dim_id, (value, tier, claim_refs, reason) in raw.items():
        spec = weights.get(dim_id)
        normalized = _normalize(value, spec["normalize"]) if (spec and value is not None) else None
        entry = {"dimension": dim_id, "value": _round(value) if isinstance(value, float) else value,
                 "normalized": _round(normalized), "weight": float(spec["weight"]) if spec else 0.0,
                 "tier": tier, "claim_refs": sorted(c for c in claim_refs if c)}
        if reason:
            entry["reason"] = reason
        elif not spec:
            entry["reason"] = "reported, not weighted by the scoring model"
        dimensions.append(entry)

    screen = _screen(dimensions, model)
    veto_context = {d["dimension"]: d["value"] for d in dimensions if d["value"] is not None}
    veto_context["revenue_potential_tier"] = "hypothesis"
    screen["vetoes"] = _vetoes(model, veto_context)

    match = _backlog_match(archetype, backlog)
    claim_refs = {estimate, priors_claim, fit_claim, thesis} | set(refs) | set(market_claims)
    for extra in (distribution_claim, competition_claim):
        if extra:
            claim_refs.add(extra)
    concept = {
        "genre": archetype["genre"],
        "subgenre": archetype["subgenre"],
        "core_mechanic": archetype["core_mechanic"],
        "fantasy": archetype["fantasy"],
        "core_loop": archetype["core_loop"],
        "reference_titles": reference_titles[:6],
    }
    profile = {
        "session_seconds": archetype["session_seconds"],
        "replayability": archetype["replayability"],
        "retention_design": archetype.get("retention_design", ""),
        "technical_complexity": archetype["technical_complexity"],
        "asset_complexity": archetype["asset_complexity"],
        "dev_speed_days": archetype["dev_speed_days"],
        "asset_cost_usd": archetype["asset_cost_usd"],
        "bundle_mb": archetype["bundle_mb"],
        "rendering": archetype.get("rendering", "2d"),
        "text_heavy": bool(archetype.get("text_heavy")),
        "multiplayer": bool(archetype.get("multiplayer")),
        "mobile_ready": bool(archetype.get("mobile_ready")),
        "monetization": {k: monetization[k] for k in ("primary", "secondary", "rationale")
                         if k in monetization},
    }
    return {
        "id": aid,
        "opportunity_id": "opp-" + hashlib.sha256(f"{report_key}:{aid}".encode()).hexdigest()[:8],
        "concept": concept,
        "profile": profile,
        "platform_fit": fits,
        "dimensions": dimensions,
        "screen": screen,
        "backlog_match": match,
        "market_signal": {
            "observed": bool(present_on),
            "platforms": present_on,
            "reference_titles": len(reference_titles),
            "claim_refs": sorted(set(refs) | set(market_claims)),
        },
        "status": "considered",
        "claim_refs": sorted(claim_refs),
        "_thesis": thesis,
        "_viable": [f["platform"] for f in viable],
        "_archetype": archetype,
    }


# -- the whole analysis ---------------------------------------------------------------------


def buildable(archetype):
    """False only when the catalog says so: `design_archetype: null`. A catalog that does not
    declare the field (an installation's own) makes no claim, and nothing is excluded."""
    return "design_archetype" not in archetype or bool(archetype["design_archetype"])


def analyse(*, sources, profiles, archetypes, model, backlog, as_of_text, report_key,
            max_candidates=8, idea=None, book=None, state=None):
    """Returns (claims, platforms, candidates, selection, gaps). `as_of_text(dt)` formats a
    timestamp; `as_of_text(None)` is the scan's own time. `idea` is the run's brief, or
    None for a blank scan - which leaves every output exactly as it was without one.

    `book` and `state` are for Research V2 (step.py), which continues from where the screen
    stops: `state` receives the observations, platform views, every candidate (before the
    report's cap) and the claim ids the screen references."""
    book = book if book is not None else ClaimBook(as_of_text(None))
    gaps = []

    observations = []
    for source in sources:
        for obs in source.observations:
            observations.append((obs, book.observed(obs, as_of_text)))

    views = _build_platforms(book, profiles, observations, as_of_text, gaps)
    platform_info = {pid: _platform_claims(book, view) for pid, view in views.items()}
    platforms = [_platform_summary(views[pid], *platform_info[pid]) for pid in sorted(views)]

    candidates = [_candidate(book, a, views, platform_info, model, backlog, report_key)
                  for a in archetypes]
    dimension = idea_dimension(idea) if idea else None
    if idea:
        for candidate in candidates:
            candidate["idea_match"] = idea_match(candidate["_archetype"], idea)
    for candidate in candidates:
        breached = [v["criterion_id"] for v in candidate["screen"]["vetoes"] if v["breached"]]
        match = candidate["backlog_match"]
        if breached:
            candidate["status"] = "excluded"
            candidate["exclusion_reason"] = f"veto fired: {', '.join(breached)}"
        elif match:
            candidate["status"] = "excluded"
            candidate["exclusion_reason"] = (f"duplicate of {match['opportunity_id']} "
                                             f"({match['state']}) in the backlog")
        elif not candidate["_viable"]:
            candidate["status"] = "excluded"
            candidate["exclusion_reason"] = "no scoped platform is viable without a blocker"
        elif not buildable(candidate["_archetype"]):
            # The Factory cannot design it: the design module has no archetype that carries
            # this concept's mechanics, so design would fail consistency (cut scope, never
            # relax the rules) whatever a person approved at G2. Kept, like every exclusion.
            candidate["status"] = "excluded"
            candidate["exclusion_reason"] = (
                "not buildable: no design archetype carries this concept's mechanics "
                "(catalog design_archetype is null)")

    # Evidence of demand outranks imagined demand: when the scan observed any listings at all,
    # a candidate nobody was seen playing ranks after every candidate somebody was.
    market_seen = any(c["market_signal"]["observed"] for c in candidates)
    # A brief ranks first among the eligible: the person asked for this game, and the
    # screen then orders the shapes that could carry it.
    candidates.sort(key=lambda c: (c["status"] == "excluded",
                                   _idea_rank(c, dimension),
                                   market_seen and not c["market_signal"]["observed"],
                                   -c["screen"]["score"], c["id"]))
    # Excluded candidates are always kept: a rejection and its reason are evidence, and the
    # next scan should not rediscover the same dead end. The cap applies to the rest.
    eligible = [c for c in candidates if c["status"] != "excluded"][:max(1, max_candidates)]
    kept = eligible + [c for c in candidates if c["status"] == "excluded"]
    selection = None
    if eligible:
        chosen = eligible[0]
        chosen["status"] = "selected"
        runner = eligible[1] if len(eligible) > 1 else None
        brief_note = ""
        if idea:
            matched = list(chosen["idea_match"]["terms"])
            if chosen["idea_match"]["dimension"]:
                matched.insert(0, dimension)
            brief_note = (f"Closest to the brief ({'matched: ' + ', '.join(matched) if matched else 'matched nothing in the catalog'}), then ")
        selection = {
            "candidate_id": chosen["id"],
            "opportunity_id": chosen["opportunity_id"],
            "rationale": (
                brief_note
                + f"{'h' if brief_note else 'H'}ighest screen score ({chosen['screen']['score']:.2f}) of "
                f"{len(eligible)} eligible candidates out of {len(candidates)} considered"
                + (", among those with observed market presence" if market_seen else "")
                + "; "
                + f"viable on {', '.join(chosen['_viable'])}; "
                f"{chosen['screen']['weight_coverage']:.0%} of the scoring model's weight "
                f"scored, {chosen['screen']['evidence_coverage']:.0%} of that on observed or "
                f"derived evidence. "
                + (f"Observed market presence on {', '.join(chosen['market_signal']['platforms'])} "
                   f"(reference titles: {chosen['market_signal']['reference_titles']}). "
                   if chosen["market_signal"]["observed"] else
                   "No observed market presence; ranked on estimates alone. ")
                + "Revenue was not estimated."
                + (f" Runner-up: {runner['id']} ({runner['screen']['score']:.2f})."
                   if runner else "")),
            "runner_up": runner["id"] if runner else None,
        }
        if idea and not chosen["idea_match"]["terms"]:
            wanted = idea_terms(idea)
            gaps.append((
                "idea-unmatched",
                f"the catalog holds no archetype whose genre, tags or mechanic match the brief"
                + (f" ({', '.join(wanted)})" if wanted else "")
                + f"; selected {chosen['id']} as the nearest "
                + (f"{dimension} shape" if chosen["idea_match"]["dimension"] else "shape")
                + " by screen score. The brief is carried verbatim to strategy and design, "
                  "which must realise what the shape does not", None))
        if idea and dimension is not None and not chosen["idea_match"]["dimension"]:
            gaps.append((
                "idea-unmatched",
                f"the brief names {dimension}, and no eligible archetype matching its words "
                f"renders in {dimension}; selected {chosen['id']}, which does not. The brief "
                f"is carried verbatim to design, which chooses the dimension", None))
    if len(candidates) > len(kept):
        gaps.append(("unscored-dimension",
                     f"{len(candidates) - len(kept)} lower-screened eligible candidates were "
                     f"dropped from the report to keep it to {len(eligible)}", None))
    gaps.append(("unscored-dimension",
                 "revenue_potential is not scored: no source in this scan attributes revenue, "
                 "and the research step does not estimate it", None))

    referenced = {cid for _obs, cid in observations}
    for summary in platforms:
        referenced.update(summary["claim_refs"])
    for candidate in kept:
        referenced.update(candidate["claim_refs"])
        for f in candidate["platform_fit"]:
            referenced.update(f["claim_refs"])
        for d in candidate["dimensions"]:
            referenced.update(d["claim_refs"])
    keep_ids = book.closure(referenced)
    claims = [book.claims[cid] for cid in sorted(keep_ids)]
    if state is not None:
        state.update({"observations": observations, "views": views,
                      "platform_info": platform_info, "candidates": candidates,
                      "referenced": referenced})
    return claims, platforms, kept, selection, gaps
