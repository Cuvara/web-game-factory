"""Opportunity -> title strategy. Pure, deterministic, and biased hard toward small titles.

`plan_strategy(opportunity, profiles, title_id, policy)` returns the body of a
title-strategy artifact (everything but provenance) or raises StrategyRefused. It reads
nothing but its arguments, so the same opportunity and profiles always produce the same
strategy - which is what makes it testable, and what lets a G2 reviewer re-derive it.

What it decides, following core/lifecycle/stages/strategy.md:

  platforms     every candidate checked against its profile; incompatible ones recorded
                and left out; exactly one `required`, the best fit for the audience
  monetization  the research hypothesis, reclassified when no platform can carry it, and
                placements cut to what the required platform supports
  scope         estimate -> timebox (7-14 days, refused beyond 21), one control scheme, a
                capped asset budget, reusable template systems, named exclusions
  bet terms     prototype_must_prove, success and kill criteria as criteria-expressions
  honesty       risks carried from the opportunity plus the ones this plan introduces,
                and the assumptions it takes on without checking

It does not approve anything. The result is a draft that waits at G2.
"""

import math
import re

__all__ = ["Policy", "StrategyRefused", "plan_strategy", "PLANNABLE_STATES"]

PLANNABLE_STATES = ("discovered", "scored", "shortlisted", "approved", "promoted")

SCOPE_DAYS = {"xs": 5, "s": 9, "m": 14, "l": 21, "xl": 35}
SCOPE_ORDER = ("xs", "s", "m", "l", "xl")
LEVELS = ("low", "medium", "high")
ASSET_CAP = {"low": 30, "medium": 60, "high": 120}

MONETIZATION_CLASS = {
    "rewarded": "rewarded-led",
    "interstitial": "interstitial-led",
    "banner": "mixed-ads",
    "iap": "iap-led",
    "none": "none",
}
PLACEMENTS = ("rewarded", "interstitial", "banner", "iap")

# Concept keywords that raise technical cost. One category counts once.
TECH_SIGNALS = (
    ("networking", 2, ("multiplayer", "online", "pvp", "co-op", "coop", "real-time versus")),
    ("3d", 1, ("3d",)),
    ("physics", 1, ("physics", "ragdoll", "destruction")),
    ("audio-sync", 1, ("rhythm", "beat", "music")),
    ("procedural", 1, ("procedural", "generated")),
)

CONTROL_SCHEMES = (
    ("one-touch", ("one-touch", "one touch", "one-tap", "one tap", "single tap")),
    ("swipe", ("swipe",)),
    ("drag", ("drag", "slingshot", "pull back")),
    ("keyboard", ("keyboard", "wasd", "arrow keys")),
    ("point-and-click", ("click", "point and", "aim")),
    ("tap", ("tap", "touch")),
)

# (key, exclusion, keywords meaning the concept itself depends on it)
EXCLUSIONS = (
    ("multiplayer", "Multiplayer and any online play — networking multiplies the test surface "
                    "and needs a server nobody has budgeted",
     ("multiplayer", "online", "pvp", "co-op", "coop")),
    ("metagame", "Metagame layers: daily quests, battle pass, login rewards — retention systems "
                 "are validated after the core loop is, not before", ("quest", "daily", "battle pass")),
    ("customization", "Character or skin customization and a cosmetics shop",
     ("skin", "customiz", "cosmetic", "dress-up", "dress up")),
    ("editor", "Level editor or user-generated content", ("editor", "user-generated", "ugc")),
    ("narrative", "Story, cutscenes and dialogue — text multiplies localization cost",
     ("story", "narrative", "cutscene", "dialogue")),
    ("leaderboards", "Leaderboards beyond a personal best", ("leaderboard",)),
    ("content", "A second mode or content set — one proves the loop; more is content, not "
                "validation", ()),
)


class StrategyRefused(ValueError):
    """The opportunity cannot become a rapid-production title as it stands."""


class Policy:
    """The envelope a strategy must fit. Overridable per workflow step (`with:`)."""

    FIELDS = {
        "min_timebox_days": 7,
        "target_timebox_days": 14,
        "max_timebox_days": 21,
        "max_platforms": 3,
        "default_session_seconds": 180,
        "min_session_seconds": 60,
        "max_session_seconds": 300,
        "sessions_per_day_target": 3,
        "max_prototype_iterations": 2,
    }

    def __init__(self, **overrides):
        unknown = sorted(set(overrides) - set(self.FIELDS))
        if unknown:
            raise StrategyRefused(f"unknown strategy policy keys: {', '.join(unknown)}")
        for key, default in self.FIELDS.items():
            value = overrides.get(key, default)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                raise StrategyRefused(f"strategy policy {key} must be a positive number")
            setattr(self, key, value)
        if not (self.min_timebox_days <= self.target_timebox_days <= self.max_timebox_days):
            raise StrategyRefused("strategy policy needs min <= target <= max timebox days")

    @classmethod
    def from_params(cls, params):
        return cls(**dict(params or {}))


# -- helpers ------------------------------------------------------------------------------


def _text(*parts):
    return " ".join(p for p in parts if isinstance(p, str)).lower()


def _has(text, keywords):
    return any(re.search(r"(?<![a-z0-9])" + re.escape(k), text) for k in keywords)


def _sentence(value):
    value = (value or "").strip().rstrip(".")
    return value[:1].upper() + value[1:] if value else value


def _placement_supported(profile, placement):
    capabilities = profile.get("capabilities") or {}
    ads = profile.get("ads") or {}
    if placement == "rewarded":
        return bool(ads.get("rewarded_available"))
    if placement == "interstitial":
        return "interstitial" in (capabilities.get("ads") or [])
    if placement == "banner":
        return bool(ads.get("banner_available"))
    if placement == "iap":
        return bool(capabilities.get("iap"))
    return placement == "none"


# -- the plan -----------------------------------------------------------------------------


class _Plan:
    def __init__(self, opportunity, profiles, title_id, policy):
        self.opp = opportunity
        self.profiles = profiles
        self.title_id = title_id
        self.policy = policy
        self.concept = opportunity.get("concept") or {}
        self.audience = opportunity.get("audience") or {}
        self.estimates = opportunity.get("estimates") or {}
        self.text = _text(self.concept.get("genre"), self.concept.get("subgenre"),
                          self.concept.get("core_mechanic"), self.concept.get("core_loop"))
        self.risks = []
        self.assumptions = []
        self.decisions = []

    def risk(self, description, severity, mitigation=None, origin="strategy", claims=None):
        entry = {"description": description, "severity": severity, "origin": origin}
        if mitigation:
            entry["mitigation"] = mitigation
        if claims:
            entry["claim_refs"] = list(claims)
        self.risks.append(entry)

    def assume(self, statement, invalidated_by, tier="hypothesis"):
        self.assumptions.append(
            {"statement": statement, "tier": tier, "invalidated_by": invalidated_by})

    # -- checks ---------------------------------------------------------------------------

    def check_opportunity(self):
        state = self.opp.get("state")
        if state not in PLANNABLE_STATES:
            raise StrategyRefused(
                f"opportunity {self.opp.get('id')} is {state!r}; strategy plans only "
                f"{', '.join(PLANNABLE_STATES)}")
        for key in ("genre", "core_mechanic", "core_loop"):
            if not self.concept.get(key):
                raise StrategyRefused(f"opportunity concept has no {key}; nothing to plan")
        if not self.opp.get("candidate_platforms"):
            raise StrategyRefused("opportunity names no candidate platforms")

    # -- scope ----------------------------------------------------------------------------

    def scope(self):
        days = self.estimates.get("dev_speed_days")
        scope = self.estimates.get("scope_complexity")
        if scope not in SCOPE_DAYS:
            scope = None
        if not isinstance(days, (int, float)) or days <= 0:
            days = SCOPE_DAYS[scope or "m"]
            self.assume(f"With no research estimate, a {scope or 'm'}-scope title takes about "
                        f"{days} days", "tech-plan milestones summing past the timebox "
                        "(guard plan_fits_timebox)")
        if scope is None:
            scope = next((s for s in SCOPE_ORDER if days <= SCOPE_DAYS[s]), "xl")

        policy = self.policy
        if scope == "xl" or days > policy.max_timebox_days:
            raise StrategyRefused(
                f"estimated {days} days at scope {scope!r} is outside the rapid-production "
                f"envelope (max {policy.max_timebox_days} days); re-scope the opportunity "
                f"rather than commit to it")

        if days > policy.target_timebox_days:
            timebox = policy.target_timebox_days
            self.decisions.append(
                f"Estimate of {days:g} days exceeds the {timebox}-day target: the timebox is "
                f"held at {timebox} and the MVP is limited to the core loop — design cuts to "
                f"fit, the timebox does not stretch")
            self.risk(f"Scope estimate ({days:g} days) is above the {timebox}-day timebox",
                      "medium", "Design must cut content, not the core loop; G3 checks the "
                                "plan against the timebox (plan_fits_timebox)")
        else:
            timebox = max(policy.min_timebox_days, int(math.ceil(days)))
        self.assume(f"The research estimate of {days:g} development days holds for the MVP "
                    f"as scoped here", "tech-plan milestones summing past the timebox "
                    "(guard plan_fits_timebox)")

        tech_points = {"xs": 0, "s": 0, "m": 1, "l": 2}[scope]
        signals = []
        for name, weight, keywords in TECH_SIGNALS:
            if _has(self.text, keywords):
                tech_points += weight
                signals.append(name)
        self.tech_signals = signals

        cost = self.estimates.get("asset_cost_usd")
        if isinstance(cost, (int, float)):
            asset_points = 0 if cost <= 500 else 1 if cost <= 2000 else 2
        else:
            asset_points = {"xs": 0, "s": 0, "m": 1, "l": 2}[scope]
        if "3d" in signals:
            asset_points += 1

        self.scope_complexity = scope
        self.estimate_days = days
        self.timebox = timebox
        self.technical_points = tech_points
        self.asset_complexity = LEVELS[min(asset_points, 2)]
        self.asset_cost = cost if isinstance(cost, (int, float)) else None

        if "networking" in signals:
            self.risk("The concept depends on online play, which multiplies test surface and "
                      "needs server infrastructure", "high",
                      "Prototype must prove the loop works against a simulated opponent "
                      "before any networking is built")

    def technical_complexity(self, monetization_class):
        points = self.technical_points + (1 if monetization_class in ("iap-led", "hybrid")
                                          else 0)
        return "low" if points == 0 else "medium" if points <= 2 else "high"

    # -- controls, session ----------------------------------------------------------------

    def controls(self):
        text = _text(self.concept.get("core_mechanic"), self.concept.get("core_loop"))
        self.control_scheme = next(
            (scheme for scheme, keywords in CONTROL_SCHEMES if _has(text, keywords)), "tap")
        if self.control_scheme == "keyboard" and self.audience.get("device") in (None, "mobile",
                                                                                 "both"):
            self.risk("Keyboard controls do not exist on the mobile share of the audience",
                      "high", "Map the mechanic to a touch scheme in design, or narrow the "
                              "audience to desktop at G2")
        self.decisions.append(
            f"One control scheme ({self.control_scheme}); no alternative or desktop-specific "
            f"input")

    def session(self):
        policy = self.policy
        target = self.estimates.get("session_seconds")
        if not isinstance(target, (int, float)) or target <= 0:
            target = policy.default_session_seconds
            self.assume(f"A {target}-second session suits this loop (no research estimate)",
                        "median_session_seconds in the prototype playtest")
        if target > policy.max_session_seconds:
            self.decisions.append(
                f"Target session cut from {target:g}s to {policy.max_session_seconds}s: short "
                f"sessions keep content needs small and fit portal play patterns")
            target = policy.max_session_seconds
        target = max(policy.min_session_seconds, int(round(target)))
        first = max(policy.min_session_seconds, int(round(target * 0.75 / 10.0)) * 10)
        self.session_body = {
            "first_session_seconds": min(first, target),
            "target_seconds": target,
            "sessions_per_day_target": policy.sessions_per_day_target,
        }
        self.assume(f"Players sustain a {target}-second session",
                    "median_session_seconds in the prototype playtest or first performance "
                    "review")

    # -- platforms and monetization -------------------------------------------------------

    def platforms(self):
        hypothesis = self.opp.get("monetization_hypothesis") or {}
        primary = hypothesis.get("primary") or "none"
        secondary = [p for p in hypothesis.get("secondary") or [] if p in PLACEMENTS]

        candidates = []
        compatibility = {}
        for platform_id in self.opp.get("candidate_platforms") or []:
            if platform_id in compatibility:
                continue
            profile = self.profiles.get(platform_id)
            if profile is None:
                compatibility[platform_id] = {
                    "id": platform_id, "profile_version": None, "compatible": False,
                    "issues": ["no platform profile in core/reference/platforms/"]}
                self.risk(f"Candidate platform {platform_id!r} has no profile and was left "
                          f"out", "low", "Add a profile before considering it again")
                continue
            candidates.append(platform_id)
        if not candidates:
            raise StrategyRefused("none of the candidate platforms has a platform profile")

        def carriers(placement):
            return [p for p in candidates if _placement_supported(self.profiles[p], placement)]

        if primary != "none" and not carriers(primary):
            fallback = next((p for p in secondary + ["rewarded", "interstitial"]
                             if p != primary and carriers(p)), "none")
            self.risk(f"The research monetization hypothesis ({primary}) is unsupported on "
                      f"every candidate platform; reclassified to {fallback}", "medium",
                      "G2 reviewer confirms the reclassified model still funds the title")
            self.decisions.append(f"Monetization reclassified from {primary} to {fallback}: "
                                  f"no candidate platform can carry {primary}")
            primary = fallback
        self.primary_placement = primary

        compatible = []
        for platform_id in candidates:
            profile = self.profiles[platform_id]
            issues = []
            if profile.get("status") != "verified":
                issues.append("profile figures are unverified")
            ok = primary == "none" or _placement_supported(profile, primary)
            if not ok:
                issues.append(f"no {primary} placements: the primary monetization is "
                              f"unsupported")
            for placement in secondary:
                if placement != primary and not _placement_supported(profile, placement):
                    issues.append(f"no {placement} placements: dropped on this platform")
            compatibility[platform_id] = {"id": platform_id,
                                          "profile_version": str(profile.get("version")),
                                          "compatible": ok, "issues": issues}
            if ok:
                compatible.append(platform_id)
        if not compatible:
            raise StrategyRefused(f"no candidate platform supports {primary} monetization")

        order = {p: i for i, p in enumerate(candidates)}
        ranked = sorted(compatible, key=lambda p: (-self._fit(p, secondary), order[p]))
        required = ranked[0]
        chosen = ranked[:max(1, int(self.policy.max_platforms))]
        dropped = [p for p in ranked if p not in chosen]
        self.required = required
        self.chosen = [p for p in candidates if p in chosen]
        self.dropped = dropped

        placements = [primary] if primary != "none" else []
        placements += [p for p in secondary if p not in placements
                       and _placement_supported(self.profiles[required], p)]
        self.placements = placements
        cls = MONETIZATION_CLASS[primary]
        if cls == "rewarded-led" and "iap" in placements:
            cls = "hybrid"
        self.monetization = {"class": cls, "placements": placements}
        rationale = hypothesis.get("rationale")
        if rationale:
            self.monetization["rationale"] = rationale
        if primary != "none":
            self.assume(f"{_sentence(primary)} placements monetize this loop the way research "
                        f"expects", f"{primary} opt-in or fill rate in the first performance "
                                    f"review")

        for platform_id in candidates:
            entry = compatibility[platform_id]
            entry["sdk"] = self._sdk(self.profiles[platform_id])
            entry["constraints"] = self._constraints(self.profiles[platform_id])
            if platform_id in dropped:
                entry["issues"].append(f"left out: at most {int(self.policy.max_platforms)} "
                                       f"platforms per title")
        self.compatibility = list(compatibility.values())

        for platform_id in self.chosen:
            profile = self.profiles[platform_id]
            if profile.get("status") != "verified":
                self.assume(f"The {profile.get('name', platform_id)} profile "
                            f"(v{profile.get('version')}) matches the portal's current rules",
                            "a validation failure or rejection citing a rule the profile does "
                            "not state")
        required_profile = self.profiles[required]
        interval = (required_profile.get("ads") or {}).get("interstitial_min_interval_s")
        if "interstitial" in placements and isinstance(interval, (int, float)) and \
                self.session_body["target_seconds"] < interval:
            self.risk(f"The {self.session_body['target_seconds']}s session is shorter than "
                      f"{required_profile.get('name', required)}'s {interval:g}s interstitial "
                      f"interval: at most one interstitial per session", "low",
                      "Interstitials go between sessions only; revenue rests on the primary "
                      "placement")
        locales = self._locales()
        if [locale for locale in locales if locale != "en"]:
            self.risk(f"Required locales {', '.join(locales)} must be localized by a person, "
                      f"not machine-translated", "medium",
                      "Keep in-game text to a short string table")

    def _fit(self, platform_id, secondary):
        profile = self.profiles[platform_id]
        regions = set(self.audience.get("regions") or [])
        primary_regions = set((profile.get("audience") or {}).get("primary_regions") or [])
        mix = (profile.get("audience") or {}).get("device_mix") or {}
        device = self.audience.get("device") or "both"
        device_fit = 0.5 if device == "both" else float(mix.get(device) or 0)
        supported = sum(1 for p in secondary if _placement_supported(profile, p))
        return 2 * len(regions & primary_regions) + device_fit + 0.25 * supported

    def _sdk(self, profile):
        capabilities = profile.get("capabilities") or {}
        requirements = profile.get("requirements") or {}
        has_ads = bool(capabilities.get("ads"))
        if not has_ads and requirements.get("loading_api") != "required":
            return {"id": "none", "features": []}
        features = ["init"]
        if requirements.get("loading_api") == "required":
            features.append("loading-progress")
        if has_ads:
            features.append("gameplay-start-stop")
        for placement in self.placements:
            if _placement_supported(profile, placement):
                features.append(placement)
        if has_ads and self.placements:
            features.append("pause-audio-during-ads")
        if capabilities.get("cloud_saves"):
            features.append("cloud-save")
        return {"id": profile["id"], "features": features}

    def _constraints(self, profile):
        requirements = profile.get("requirements") or {}
        ads = profile.get("ads") or {}
        constraints = []
        if requirements.get("locales_required"):
            constraints.append(f"Locales required: {', '.join(requirements['locales_required'])}")
        if requirements.get("max_bundle_mb"):
            constraints.append(f"Bundle at most {requirements['max_bundle_mb']} MB")
        if "interstitial" in self.placements and ads.get("interstitial_min_interval_s"):
            constraints.append(
                f"Interstitials at least {ads['interstitial_min_interval_s']}s apart")
        if requirements.get("loading_api") == "required":
            constraints.append("Loading progress reported through the SDK")
        if requirements.get("https_only"):
            constraints.append("HTTPS only")
        if requirements.get("external_requests") == "restricted":
            constraints.append("External requests only to declared domains")
        if requirements.get("no_external_links"):
            constraints.append("No external links")
        return constraints

    def _locales(self):
        locales = []
        for platform_id in self.chosen:
            for locale in (self.profiles[platform_id].get("requirements") or {}).get(
                    "locales_required") or []:
                if locale not in locales:
                    locales.append(locale)
        return locales

    def _bundle_mb(self):
        sizes = [(self.profiles[p].get("requirements") or {}).get("max_bundle_mb")
                 for p in self.chosen]
        sizes = [s for s in sizes if isinstance(s, (int, float))]
        return min(sizes) if sizes else None

    # -- the artifact body ----------------------------------------------------------------

    def body(self):
        concept = self.concept
        opp = self.opp
        required_profile = self.profiles[self.required]
        genre = concept.get("subgenre") or concept.get("genre")
        mobile = self.audience.get("device") in (None, "mobile", "both")

        replay = self._replayability()
        concept_body = {
            "genre": concept["genre"],
            "core_mechanic": concept["core_mechanic"],
            "core_loop": concept["core_loop"],
            "gameplay_direction": (
                f"{_sentence(genre)} built on {concept['core_mechanic']}. A session is a short "
                f"run: {concept['core_loop']}. Difficulty comes from one data-driven ramp, "
                f"not hand-built levels."),
            "control_scheme": self.control_scheme,
            "replayability": replay,
        }
        if concept.get("subgenre"):
            concept_body["subgenre"] = concept["subgenre"]

        platform_set = []
        for platform_id in self.chosen:
            profile = self.profiles[platform_id]
            name = profile.get("name", platform_id)
            if platform_id == self.required:
                rationale = (f"Primary: best audience fit among compatible candidates"
                             f"{self._fit_reason(profile)}; the title is not shippable "
                             f"without it.")
            else:
                rationale = (f"Secondary: {name} is compatible from the same build; not "
                             f"required to ship.")
            platform_set.append({"id": platform_id, "profile_version":
                                 str(profile.get("version")),
                                 "role": "required" if platform_id == self.required
                                 else "optional", "rationale": rationale})

        audience = {"type": self.audience.get("type") or "casual",
                    "device": self.audience.get("device") or "both"}
        if self.audience.get("regions"):
            audience["regions"] = list(self.audience["regions"])
        audience["player_description"] = (
            f"A {audience['type']} player on {'a phone' if audience['device'] == 'mobile' else 'a desktop browser' if audience['device'] == 'desktop' else 'phone or desktop'}"
            f" who wants to be playing within seconds, in sessions of about "
            f"{self.session_body['target_seconds'] // 60 or 1} minute"
            f"{'s' if self.session_body['target_seconds'] >= 120 else ''}.")

        mvp = [
            f"Core loop: {concept['core_loop']}",
            f"A single {self.control_scheme} control: {concept['core_mechanic']}",
            "One content set with a data-driven difficulty ramp",
            "Score and personal best, persisted"
            + (" through the platform's cloud save" if "cloud-save" in
               self._sdk(required_profile)["features"] else " locally"),
        ]
        if "rewarded" in self.placements:
            mvp.append("A rewarded placement at a natural moment in the loop "
                       "(continue or bonus), never forced")
        if "interstitial" in self.placements:
            mvp.append("Interstitials between sessions only, never inside one")
        sdk = self._sdk(required_profile)
        if sdk["id"] != "none":
            mvp.append(f"{required_profile.get('name', self.required)} SDK: "
                       f"{', '.join(sdk['features'])}")
        locales = self._locales()
        if locales:
            mvp.append(f"Localization: {', '.join(locales)}")

        out_of_scope = []
        for key, exclusion, keywords in EXCLUSIONS:
            if keywords and _has(self.text, keywords):
                self.risk(f"The concept depends on something rapid production would exclude "
                          f"({key}); it stays in scope and carries the cost", "medium",
                          "Design keeps the smallest version of it that serves the core loop")
                continue
            out_of_scope.append(exclusion)
        if self.monetization["class"] not in ("iap-led", "hybrid"):
            out_of_scope.append("An IAP economy or premium currency")
        if audience["device"] == "mobile":
            out_of_scope.append("A desktop-specific control scheme")
        if self.dropped:
            out_of_scope.append(f"Platforms beyond the set: {', '.join(self.dropped)} — "
                                f"platform sprawl multiplies compliance work")
        incompatible = [c["id"] for c in self.compatibility if not c["compatible"]]
        if incompatible:
            out_of_scope.append(f"Incompatible candidate platforms: {', '.join(incompatible)} "
                                f"(see platform_compatibility)")

        bundle = self._bundle_mb()
        must_prove = [
            f"A first-time player understands the {self.control_scheme} control without "
            f"instruction",
            f"The core loop produces an unforced desire to retry within one "
            f"{self.session_body['target_seconds']}-second session",
        ]
        for risk in opp.get("risks") or []:
            if risk.get("severity") == "high" and risk.get("description"):
                must_prove.append(f"This risk is contained: {_sentence(risk['description'])}")
        if "rewarded" in self.placements:
            must_prove.append("The rewarded placement reads as a favour rather than an "
                              "interruption")
        if mobile:
            must_prove.append("It holds 30 fps on a mid-range mobile browser"
                              + (f" inside a {bundle:g} MB bundle" if bundle else ""))

        retention = {"casual": 0.25, "midcore": 0.3, "core": 0.35}[audience["type"]]
        success = [
            {"id": "d1_retention", "label": "D1 retention",
             "when": {"left": "d1_retention", "op": "gte", "right": retention},
             "rationale": "Below this a short-session title without a metagame has no path to "
                          "sustained portal traffic.", "severity": "blocking"},
            {"id": "session_length", "label": "Median session near target",
             "when": {"left": "median_session_seconds", "op": "gte",
                      "right": self.session_body["first_session_seconds"]},
             "rationale": "Shorter than this and the placements the monetization model counts "
                          "on never get a chance to show.", "severity": "warning"},
        ]
        kill = [
            {"id": "control_not_understood", "label": "First-time players do not understand "
             "the control", "when": {"left": "first_time_understood_share", "op": "lt",
                                      "right": 0.6},
             "rationale": "The title is scoped around one control scheme and no tutorial. If "
                          "that scheme needs teaching, the scope assumption is wrong.",
             "severity": "blocking"},
            {"id": "no_retry_pull", "label": "Players do not retry unprompted",
             "when": {"left": "unprompted_retry_share", "op": "lt", "right": 0.5},
             "rationale": "Replay is the retention system here, in place of content. Without "
                          "immediate retry there is neither retention nor an ad moment.",
             "severity": "blocking"},
            {"id": "prototype_overran", "label": "The prototype consumed most of the timebox",
             "when": {"left": "prototype_elapsed_days", "op": "gt",
                      "right": int(math.ceil(self.timebox * 0.6))},
             "rationale": "A prototype that needs more than 60% of the timebox is evidence the "
                          "scope does not fit it, and production would overrun by more.",
             "severity": "blocking"},
        ]
        if mobile:
            kill.append({
                "id": "mobile_performance_floor", "label": "Unplayable on mid-range mobile",
                "when": {"left": "midrange_mobile_fps", "op": "lt", "right": 30},
                "rationale": "Most portal traffic for this audience is mobile; below 30 fps a "
                             "reaction-driven loop reads as the game's fault, not the "
                             "player's.", "severity": "blocking"})

        for risk in opp.get("risks") or []:
            if not risk.get("description"):
                continue
            high = risk.get("severity") == "high"
            self.risk(risk["description"], risk.get("severity") or "medium",
                      "Named in prototype_must_prove; answered before production" if high
                      else "Tracked into design", origin="opportunity",
                      claims=risk.get("claim_refs"))
        self.assume(f"The audience research describes ({audience['type']}, "
                    f"{audience['device']}) is the audience {required_profile.get('name', self.required)} "
                    f"delivers", "platform analytics device and region split after launch",
                    tier="derived")

        tech = self.technical_complexity(self.monetization["class"])
        systems = [
            "Template boot flow: loading, menu, play, result",
            "Template platform SDK adapter: one interface, one implementation per platform",
            f"Input handler for the {self.control_scheme} scheme only",
            "Score and personal-best persistence",
            "Data-driven difficulty ramp",
        ]
        if self.placements:
            systems.append("Ad-break service honouring the strictest interstitial interval, "
                           "pausing audio and input")
        if [locale for locale in locales if locale != "en"]:
            systems.append("Localization string table")
        cap = ASSET_CAP[self.asset_complexity]
        decisions = list(self.decisions) + [
            f"One required platform ({self.required}); every other platform is optional",
            f"Replay comes from a system ({replay.split(':')[0].lower()}), not from more "
            f"content",
            f"Asset budget capped at {cap} unique assets ({self.asset_complexity} asset "
            f"complexity)",
        ]
        production = {
            "scope_complexity": self.scope_complexity,
            "technical_complexity": tech,
            "asset_complexity": self.asset_complexity,
            "estimate_days": self.estimate_days,
            "asset_budget": {"max_unique_assets": cap},
            "reusable_systems": systems,
            "scope_decisions": decisions,
        }
        if self.asset_cost is not None:
            production["asset_budget"]["estimated_cost_usd"] = self.asset_cost
        if tech == "high":
            self.risk(f"High technical complexity ({', '.join(self.tech_signals) or 'scope'}) "
                      f"in a {self.timebox}-day timebox", "high",
                      "Prototype the riskiest system first; G4 kills on prototype_overran")

        claims = opp.get("claim_refs") or []
        why = (f"{opp.get('title', opp.get('id'))} offers {(concept.get('fantasy') or concept['core_loop']).rstrip('.')}. "
               f"The opportunity rests on {opp.get('hypothesis') or 'an unstated hypothesis'}"
               + (f" and cites {', '.join(claims)}" if claims else ", with no claims cited")
               + f". {required_profile.get('name', self.required)} is primary"
               + f"{self._fit_reason(required_profile)}.")

        return {
            "title_id": self.title_id,
            "opportunity_id": opp["id"],
            "one_liner": f"A {genre} game where the player uses {concept['core_mechanic']}.",
            "why_this_opportunity": why,
            "platform_set": platform_set,
            "audience": audience,
            "monetization": self.monetization,
            "session": self.session_body,
            "timebox_days": self.timebox,
            "mvp": mvp,
            "out_of_scope": out_of_scope,
            "prototype_must_prove": must_prove,
            "success_criteria": success,
            "kill_criteria": kill,
            "sunset_floor": {"metric": "d1_retention", "value": round(retention / 2, 3),
                             "consecutive_reviews": 2},
            "max_prototype_iterations": int(self.policy.max_prototype_iterations),
            "rollback_threshold": "critical",
            "concept": concept_body,
            "production_scope": production,
            "platform_compatibility": self.compatibility,
            "risks": self.risks,
            "assumptions": self.assumptions,
        }

    def _fit_reason(self, profile):
        regions = sorted(set(self.audience.get("regions") or [])
                         & set((profile.get("audience") or {}).get("primary_regions") or []))
        parts = []
        if regions:
            parts.append(f"audience regions {', '.join(regions)}")
        if self.primary_placement != "none":
            parts.append(f"supports {self.primary_placement} placements")
        return f" ({'; '.join(parts)})" if parts else ""

    def _replayability(self):
        loop = _text(self.concept.get("core_loop"), self.concept.get("core_mechanic"))
        if _has(loop, ("procedural", "random", "endless", "generated")):
            return ("Procedural variation: every run differs, so replay needs no new content")
        if _has(loop, ("personal best", "high score", "score", "combo", "best")):
            return ("Score chase: short runs, a personal best to beat, and immediate retry")
        return ("Mastery ramp: short levels on one difficulty curve, each with a best result "
                "to improve on")


def plan_strategy(opportunity, profiles, title_id, policy=None):
    """The body of a title-strategy for `opportunity`. Raises StrategyRefused."""
    if not isinstance(opportunity, dict):
        raise StrategyRefused("opportunity content is not a JSON object")
    plan = _Plan(opportunity, profiles, title_id, policy or Policy())
    plan.check_opportunity()
    plan.scope()
    plan.controls()
    plan.session()
    plan.platforms()
    return plan.body()
