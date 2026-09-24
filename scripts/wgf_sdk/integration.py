"""The integration phase of the `sdk` step: the template's platform SDK, wired into the game.

The conformance suite (evidence.py) proves the adapters work. This proves the game uses
them, for exactly what its game-design asks for. For every platform the game targets:

    1. inspect the SDK the game repository carries (inspect_sdk)
    2. read its API - the members of `Platform` - and the adapter the platform resolves to
    3-5. the lifecycle hooks, initialization and capabilities that adapter offers
    6. compare them with what the game-design needs (design.py)
    7. integrate only what is needed: the gameplay layer, a plan generated from the
       design's placements and the game's own seam calls, the boot sequence and the seam
       wiring in main.ts (integrate.py)
    8. with a fallback for every feature that can be missing or fail at runtime

then run the integration's own SDK-mock suite and the typecheck (runner.py). The result is
laid over the conformance result feature by feature (step.py). It implements no SDK and
calls no portal; it does not clone, commit or push.
"""

import os
import re

from wgflib import paths
from wgflib.yamllite import YamlError, load_file

from . import integrate
from .design import classify_trigger, design_placements, required_features
from .inspect_sdk import inspect_sdk
from .runner import SCENARIOS, TEST_FILE, git_state, run_tests

__all__ = ["IntegrationPhase", "PhaseBlocked", "SeamMissing", "FEATURES", "SCHEMA_VERSION"]

SCHEMA_VERSION = "1.1.0"

RUNTIME_AD_KINDS = ("rewarded", "interstitial")

# feature -> what carries it. `api`: Platform members it calls (any member containing
# `api_like` will do instead, for calls the SDK may not have at all). `capability`: the
# adapter's say. `hooks`: game hooks, "a|b" meaning either. `fallback`: what happens without.
FEATURES = {
    "init": {
        "api": ["initialize"], "hooks": ["boot"],
        "fallback": "each adapter degrades inside itself when its portal SDK is blocked or "
                    "slow, and keeps reporting to an SDK that connects late; bootPlatform "
                    "continues on generic-web only if initialize() rejects",
    },
    "loading": {"api": ["reportLoadingProgress", "signalReady"],
                "hooks": ["loading-progress", "game-ready"]},
    "gameplay-lifecycle": {
        "api": ["gameplayStart", "gameplayStop"],
        "hooks": ["run-start", "game-over|level-complete|run-stop"],
    },
    "pause-resume": {
        "api": ["gameplayStart", "gameplayStop"], "hooks": ["platform-binding"],
        "fallback": "the game pauses on a hidden tab and during ads whether or not the portal "
                    "is told",
    },
    "audio-mute": {"hooks": ["platform-binding", "gameplay-audio|audio-mute"]},
    "rewarded": {
        "api": ["showRewarded"], "capability": ("ad", "rewarded"),
        "fallback": "the offer is hidden (canOfferReward is false) and play restarts without "
                    "the reward; nothing is granted unless the portal confirms it",
    },
    "interstitial": {
        "api": ["showInterstitial"], "capability": ("ad", "interstitial"),
        "fallback": "the break is skipped and play continues",
    },
    "banner": {
        "api_like": "banner",
        "fallback": "no banner is rendered and the layout reserves no space for one",
    },
    "iap": {"api_like": "purchase", "fallback": "nothing is offered for purchase"},
    "leaderboards": {
        "api_like": "leaderboard",
        "fallback": "the best score is kept per player through save/load",
    },
    # What the design needs is progress that survives a reload. Cloud saves are how some
    # adapters provide it; local storage is how the others do, and both are working
    # persistence - the note says which one a platform gets.
    "storage": {
        "api": ["storage"], "hooks": ["save", "load"],
        "fallback": "progress is saved through platform.storage to local storage: it survives "
                    "a reload on this device, not a change of device; a failed save or load "
                    "never interrupts play",
    },
    "analytics": {
        "hooks": ["tracker"],
        "fallback": "gameplay events are dropped when no tracker is wired; play is unaffected",
    },
}




_AUDIO = re.compile(r"\bAudioContext\b|\bnew Audio\s*\(|howler|@pixi/sound|THREE\.Audio\b|"
                    r"\bAudioListener\b|\bPositionalAudio\b")


def _plays_audio(repo):
    """Whether anything under src/ plays sound. A silent game has nothing to mute."""
    for directory, dirs, files in os.walk(os.path.join(repo, "src")):
        for name in files:
            if name.endswith((".ts", ".js")):
                with open(os.path.join(directory, name), encoding="utf-8") as handle:
                    if _AUDIO.search(handle.read()):
                        return True
    return False


class PhaseBlocked(Exception):
    """The game cannot be integrated without an outside change."""


class SeamMissing(Exception):
    """The build does not boot through the integration seam (wgflib.gameseam). Integrating
    it would write files nothing calls and report an SDK nobody uses; the build goes back to
    whoever broke the develop step's contract. Not retryable: nothing here changes it."""


class IntegrationPhase:
    """One integration of one game repository. `setting(key, default)` reads factory.sdk."""

    def __init__(self, setting, runner):
        self._setting = setting
        self._runner = runner

    def run(self, repo, design, scaffold, title_id):
        """Integrate. Returns {"sdk", "platforms": {id: entry}, "integration", "commit"}."""
        self._has_audio = _plays_audio(repo)
        sdk = inspect_sdk(repo)
        if sdk is None:
            raise PhaseBlocked(f"{repo} has no packages/platform-sdk: it was not created from "
                               f"web-game-template, and this step does not write an SDK")
        try:
            game_config = load_file(os.path.join(repo, "game.config.yaml")) or {}
        except (OSError, YamlError) as exc:
            raise PhaseBlocked(f"game.config.yaml unreadable: {exc}")
        targets = game_config.get("platforms") or []

        notes = [f"SDK inspection: {problem}" for problem in sdk.problems]
        scaffold_ids = [p.get("id")
                        for p in (scaffold.get("game_config") or {}).get("platforms") or []]
        target_ids = [t.get("id") for t in targets]
        if scaffold_ids and scaffold_ids != target_ids:
            notes.append(f"game.config.yaml targets {target_ids}, the scaffold-record recorded "
                         f"{scaffold_ids}; the repository's file was used")

        substitutes = self._substitutes(sdk, target_ids, notes)
        break_on_continue = [t for t in (self._setting("break_on_continue", []) or [])
                             if t in target_ids]
        placements = design_placements(design)
        self._forbid_moments(placements, target_ids)
        declared = (game_config.get("monetization") or {}).get("ad_kinds")
        placement_records, plan_placements = self._placements(placements, declared)
        problems = integrate.seam_problems(repo)
        if problems:
            raise SeamMissing("the build does not boot through the integration seam, so the "
                              "platform SDK cannot be integrated: " + "; ".join(problems))
        seam = integrate.scan_seam(repo)
        self._seam_placements(seam, placements, declared, placement_records, plan_placements)

        # The side effect, convergent: a re-run finds and leaves what it wrote.
        plan = {
            "titleId": title_id,
            "placements": plan_placements,
            "adapterSubstitutes": substitutes,
            "breakOnContinue": break_on_continue,
        }
        source = (design.get("provenance") or {}).get("artifact_id", "the game-design")
        files = integrate.write_owned_files(repo)
        files.append(integrate.write_plan(repo, plan, source))
        files.extend(integrate.write_seam_files(repo))
        files.append(integrate.write_wiring(repo))
        hooks = integrate.scan_hooks(repo)
        self._seam_hooks(seam, plan_placements, hooks)

        if self._setting("run_tests", True):
            tests = run_tests(self._runner, repo,
                              timeout=int(self._setting("test_timeout_s", 600)),
                              typecheck=bool(self._setting("typecheck", True)),
                              touched={f["path"] for f in files if f["action"] != "skipped"})
        else:
            tests = {"status": "not-run", "typecheck": "not-run",
                     "note": "disabled by the step's run_tests setting"}
        tests.setdefault("scenarios", [{"id": s, "status": "not-run"} for s in SCENARIOS])
        commit, repo_state = git_state(self._runner, repo)

        platforms = {
            target.get("id"): self._platform(target, sdk, substitutes, design, placements,
                                             hooks, tests, break_on_continue)
            for target in targets
        }
        wanted_hooks = sorted({alt for r in platforms.values() for f in r["features"]
                               for h in f.get("hooks", []) for alt in h.split("|")})
        integration = {
            "files": files,
            "placements": placement_records,
            "game_hooks": [
                {"hook": h, "wired": h in hooks, **({"locations": hooks[h]} if h in hooks else {})}
                for h in wanted_hooks
            ],
            "tests": tests,
        }
        if repo_state:
            integration["repository_state"] = repo_state
        if notes:
            integration["notes"] = notes
        sdk_record = {"package": sdk.package, "api": list(sdk.members)}
        if sdk.version:
            sdk_record["version"] = sdk.version
        return {"sdk": sdk_record, "platforms": platforms, "integration": integration,
                "commit": commit}

    def _substitutes(self, sdk, target_ids, notes):
        configured = dict(self._setting("adapter_substitutes", {}) or {})
        used = {}
        for platform_id in target_ids:
            substitute = configured.get(platform_id)
            if not substitute:
                continue
            if sdk.adapter(platform_id).implemented:
                notes.append(f"{platform_id} has its own adapter; the configured substitute "
                             f"{substitute} was not used")
            elif not sdk.adapter(substitute).implemented:
                notes.append(f"substitute {substitute} for {platform_id} has no adapter either")
            else:
                used[platform_id] = substitute
        return used

    def _forbid_moments(self, placements, target_ids):
        """Narrow interstitial placements away from platforms that forbid their moment."""
        forbidden = self._setting("interstitial_forbidden_moments", {}) or {}
        for placement in placements:
            if placement.kind != "interstitial" or not placement.moment:
                continue
            barred = [t for t in target_ids if placement.moment in (forbidden.get(t) or [])]
            if not barred:
                continue
            allowed = [t for t in (placement.platforms or target_ids) if t not in barred]
            placement.platforms = allowed
            placement.excluded = barred

    def _placements(self, placements, declared):
        records, plan = [], []
        for placement in placements:
            record = {"id": placement.id, "kind": placement.kind, "trigger": placement.trigger}
            if placement.moment:
                record["moment"] = placement.moment
            reason = None
            if placement.kind not in RUNTIME_AD_KINDS:
                reason = f"the SDK's Platform interface has no call for {placement.kind}"
            elif placement.moment is None:
                reason = ("the trigger matched no gameplay moment (game-over, level-complete, "
                          "pause-menu); restate it in the design")
            elif declared is not None and placement.kind not in declared:
                reason = (f"{placement.kind} is not declared in game.config.yaml "
                          f"monetization.ad_kinds, which release validation checks against")
            if reason is None and placement.platforms == []:
                reason = "every target platform forbids an interstitial at this moment"
            record["integrated"] = reason is None
            if reason:
                record["note"] = reason
            else:
                record["note"] = "moment matched from the trigger's wording"
                if placement.excluded:
                    record["note"] += ("; not on " + ", ".join(placement.excluded) + ", which "
                                       "forbid(s) an interstitial here "
                                       "(factory.sdk.interstitial_forbidden_moments)")
                plan.append(placement.to_plan())
            records.append(record)
        return records, plan

    def _seam_placements(self, seam, placements, declared, records, plan):
        """The game's own placement ids, attached to the design's moments.

        An id is read like a trigger ("revive-after-crash" is a game over); failing that, it
        takes the moment of the design's only placement of its kind. Its platforms and the
        design's wording come from the design placement at that moment.
        """
        for kind, ids in seam["placements"].items():
            design_moments = {p.moment for p in placements if p.kind == kind and p.moment}
            for placement_id, where in sorted(ids.items()):
                moment = classify_trigger(placement_id.replace("-", " ").replace("_", " "))
                how = "matched from the placement id"
                if moment is None and len(design_moments) == 1:
                    moment, how = next(iter(design_moments)), "the design's only " + kind
                source = next((p for p in placements if p.kind == kind and p.moment == moment),
                              None)
                record = {"id": placement_id, "kind": kind,
                          "trigger": source.trigger if source else f"game placement {placement_id}"}
                if moment:
                    record["moment"] = moment
                reason = None
                if moment is None:
                    reason = "the placement id matched no gameplay moment and the design has " \
                             "several of its kind"
                elif source is None:
                    reason = (f"the design places no {kind} at {moment}; the game's call "
                              f"stays a plain natural break")
                elif declared is not None and kind not in declared:
                    reason = (f"{kind} is not declared in game.config.yaml monetization.ad_kinds")
                elif source is not None and source.platforms == []:
                    reason = "every target platform forbids an interstitial at this moment"
                record["integrated"] = reason is None
                record["note"] = reason or (f"the game's seam placement, {how}; called at "
                                            + ", ".join(where))
                records.append(record)
                if reason is None:
                    plan.append({"id": placement_id, "kind": kind, "moment": moment,
                                 "trigger": record["trigger"],
                                 "platforms": source.platforms if source else None})

    @staticmethod
    def _seam_hooks(seam, plan, hooks):
        """Seam calls, read as the hooks they amount to."""
        moments = {(p["kind"], p["id"]): p["moment"] for p in plan}
        for kind, ids in seam["placements"].items():
            for placement_id, where in ids.items():
                moment = moments.get((kind, placement_id))
                if not moment:
                    continue
                names = ([f"can-offer-reward:{moment}", f"offer-reward:{moment}"]
                         if kind == "rewarded" else [f"natural-break:{moment}", "natural-break"])
                for name in names:
                    hooks.setdefault(name, []).extend(where)
        for call, name in (("gameplayStart", "run-start"), ("gameplayStop", "run-stop"),
                           ("save", "save"), ("load", "load")):
            for where in seam["calls"].get(call, []):
                hooks.setdefault(name, []).append(where)

    def _platform(self, target, sdk, substitutes, design, placements, hooks, tests,
                  break_on_continue):
        platform_id = target.get("id")
        profile = str(target.get("profile") or "")
        profile_version = profile.split("@", 1)[1] if "@" in profile else "unknown"
        own = sdk.adapter(platform_id)
        adapter_id = substitutes.get(platform_id, platform_id)
        adapter = sdk.adapter(adapter_id)

        if own.implemented:
            adapter_record = {"status": "implemented", "adapter_id": platform_id}
        elif platform_id in substitutes:
            adapter_record = {"status": "substituted", "adapter_id": adapter_id}
        else:
            adapter_record = {"status": "missing"}
        if adapter.implemented:
            adapter_record["class"] = adapter.class_name
            if adapter.source:
                adapter_record["source"] = adapter.source
            if adapter.portal_sdk:
                adapter_record["portal_sdk"] = adapter.portal_sdk["url"]

        needed = required_features(design, placements, platform_id)
        if platform_id in break_on_continue and adapter.supports_ad("interstitial"):
            needed.setdefault("interstitial", "the portal asks for an ad opportunity each time "
                                              "the player heads back into gameplay "
                                              "(factory.sdk.break_on_continue)")
        for kind in RUNTIME_AD_KINDS:  # offered by the adapter, not asked for by the design
            if adapter.supports_ad(kind) and kind not in needed:
                needed[kind] = None
        features = [self._feature(name, why, adapter, sdk, placements, platform_id, hooks,
                                  tests, platform_id in break_on_continue)
                    for name, why in needed.items()]

        statuses = {f["status"] for f in features}
        if not adapter.implemented:
            status = "not-started"
        elif statuses & {"partial", "not-started"}:
            status = "partial"
        else:
            status = "working"

        report = {"platform_id": platform_id, "profile_version": profile_version,
                  "status": status, "adapter": adapter_record, "features": features}
        note = self._profile_note(platform_id, profile_version, adapter)
        if not adapter.implemented:
            note = ("No adapter for this platform in the game's SDK revision: a build for it "
                    "fails at boot. " + (note or "")).strip()
        elif platform_id in substitutes:
            note = (f"The portal publishes no SDK; builds for it run on the {adapter_id} "
                    f"adapter by configuration (factory.sdk.adapter_substitutes). "
                    + (note or "")).strip()
        if note:
            report["note"] = note
        return report

    def _feature(self, name, why, adapter, sdk, placements, platform_id, hooks, tests,
                 breaks_on_continue):
        spec = FEATURES.get(name, {})
        record = {"feature": name}
        if why is None:
            record["status"] = "not-required"
            record["note"] = "offered by the adapter; the design places none"
            return record
        # Game-side features that apply only where they mean something: a portal that
        # measures play itself needs no events from the game, and a silent game has nothing
        # to mute.
        if name == "analytics" and adapter.capability("analytics") == "platform-provided":
            record["status"] = "not-required"
            record["note"] = (f"{why}; the {adapter.platform_id} adapter reports analytics as "
                              f"platform-provided: the portal measures play itself")
            return record
        if name == "audio-mute" and not self._has_audio:
            record["status"] = "not-required"
            record["note"] = "the game source plays no audio, so there is nothing to mute"
            return record
        record["required_by"] = why

        wanted = list(spec.get("hooks", []))
        if name == "rewarded":
            for p in placements:
                if p.kind == "rewarded" and p.moment and p.applies_to(platform_id):
                    wanted += [f"can-offer-reward:{p.moment}", f"offer-reward:{p.moment}"]
        elif name == "interstitial":
            # continueFrom(moment) takes the break at that moment before play resumes.
            wanted += [f"natural-break:{p.moment}|continue-from:{p.moment}" for p in placements
                       if p.kind == "interstitial" and p.moment and p.applies_to(platform_id)]
            if breaks_on_continue:
                wanted.append("continue-from|natural-break")
        if wanted:
            record["hooks"] = wanted
        if spec.get("fallback"):
            record["fallback"] = spec["fallback"]

        if not adapter.implemented:
            record["status"] = "not-started"
            return record

        missing_api = [m for m in spec.get("api", []) if not sdk.has_member(m)]
        like = spec.get("api_like")
        if like and not any(like in member.lower() for member in sdk.members):
            record["status"] = "unsupported"
            record["note"] = f"the SDK's Platform interface has no {name} call"
            return record
        if missing_api:
            record["status"] = "unsupported"
            record["note"] = "the SDK's Platform interface lacks " + ", ".join(missing_api)
            return record
        capability = spec.get("capability")
        if capability:
            kind, key = capability
            offered = adapter.supports_ad(key) if kind == "ad" else bool(adapter.capability(key))
            if not offered:
                record["status"] = "unsupported"
                record["note"] = (f"the {adapter.platform_id} adapter's capabilities do not "
                                  f"include {key}")
                return record

        unwired = [h for h in wanted if not any(alt in hooks for alt in h.split("|"))]
        if unwired:
            record["status"] = "partial"
            record["note"] = "not called from the game source: " + ", ".join(unwired)
            return record
        if tests["status"] != "passed":
            record["status"] = "partial"
            record["note"] = f"wired, but the integration suite {tests['status']}"
            return record
        record["status"] = "working"
        record["observed_by"] = (f"SDK-mock suite {TEST_FILE} passed; not observed on the "
                                 f"portal")
        if name == "storage" and not adapter.capability("cloudSaves"):
            record["note"] = ("local storage: the adapter has no cloud saves, so progress "
                              "stays on this device")
        return record

    def _profile_note(self, platform_id, profile_version, adapter):
        path = os.path.join(paths.PLATFORMS, f"{platform_id}.yaml")
        try:
            profile = load_file(path) or {}
        except (OSError, YamlError):
            return None
        parts = []
        if profile.get("version") and profile["version"] != profile_version:
            parts.append(f"game.config.yaml pins profile {profile_version}; the Factory's "
                         f"current profile is {profile['version']}.")
        listed = set((profile.get("capabilities") or {}).get("ads") or [])
        offered = set(adapter.capability("ads") or []) if adapter.implemented else set()
        if adapter.implemented and listed != offered:
            parts.append(f"The profile lists ads {sorted(listed)}; the adapter offers "
                         f"{sorted(offered)}. The adapter is what runs.")
        return " ".join(parts) or None

