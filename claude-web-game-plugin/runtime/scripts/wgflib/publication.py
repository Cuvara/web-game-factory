"""Publication readiness: the release and platform-publication guards, computed once.

core/lifecycle/release.machine.yaml and platform-publication.machine.yaml name the guards a
release must clear to be validated and submitted - candidate_frozen, store_metadata_complete,
package_shaped_to_profile, assertions_pass, metadata_and_locales_present, and the quorum
guards all_targeted_validated, required_all_live, none_permanently_rejected. This module is
their computation, shared by two readers so they can never disagree:

  * wgflib.guards, when a person moves a title's cursor with wgf-state.py, or the lifecycle
    bridge does it for a run;
  * the publish module's `platform-validate` step (scripts/wgf_publish), which records each
    verdict in the platform-publication it writes and derives the record's `readiness`.

Every function returns a plain (value, reason, measurements) triple - True (GREEN), False
(RED) or None (UNKNOWN) - never raises for missing data, and reads only what it is handed:
no file, no network, no clock. The guards module wraps the triples in its Verdict; the step
writes them as `guards[]` entries. Standard library only.

Readiness is derived, not asserted:

    BLOCKED         a guard RED, a blocking assertion breached, the package missing
    UNKNOWN         a guard UNKNOWN (not RED): the data was not there to decide
    HUMAN_REQUIRED  every guard GREEN, but publishing here is a person's act: no automated
                    submission method, automated console use not permitted or not verified,
                    the credential nobody captured
    READY           every guard GREEN and an adapter may act
"""

import glob
import os
import re

from . import paths
from .yamllite import YamlError, load_file

__all__ = ["PUBLICATION_DIR", "GUARDS", "RELEASE_GUARDS", "PLATFORM_GUARDS", "QUORUM_GUARDS",
           "READY", "BLOCKED", "HUMAN_REQUIRED", "UNKNOWN", "READINESS",
           "load_publication_profile", "publication_profiles", "candidate_frozen",
           "store_metadata_complete", "metadata_and_locales_present",
           "package_shaped_to_profile", "assertions_pass", "all_targeted_validated",
           "required_all_live", "none_permanently_rejected", "human_reason",
           "unmet_prerequisites", "readiness",
           "idempotency_key", "GuardResult", "DENY_VOCABULARY", "FORBIDDEN_INTENT_WORDS",
           "INTENT_CLASSES", "deny_vocabulary", "flow_problems"]

PUBLICATION_DIR = os.path.join(paths.REFERENCE, "publication")

RELEASE_GUARDS = ("candidate_frozen", "store_metadata_complete")
PLATFORM_GUARDS = ("package_shaped_to_profile", "assertions_pass",
                   "metadata_and_locales_present")
QUORUM_GUARDS = ("all_targeted_validated", "required_all_live", "none_permanently_rejected")
GUARDS = RELEASE_GUARDS + PLATFORM_GUARDS + QUORUM_GUARDS

READY, BLOCKED, HUMAN_REQUIRED, UNKNOWN = "READY", "BLOCKED", "HUMAN_REQUIRED", "UNKNOWN"
READINESS = (READY, BLOCKED, HUMAN_REQUIRED, UNKNOWN)

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class GuardResult(tuple):
    """(value, reason, measurements): True GREEN, False RED, None UNKNOWN."""

    __slots__ = ()

    def __new__(cls, value, reason, **measurements):
        return tuple.__new__(cls, (value, reason, measurements))

    @property
    def value(self):
        return self[0]

    @property
    def reason(self):
        return self[1]

    @property
    def measurements(self):
        return self[2]

    @property
    def symbol(self):
        return {True: "GREEN", False: "RED"}.get(self[0], "UNKNOWN")


def green(reason, **m):
    return GuardResult(True, reason, **m)


def red(reason, **m):
    return GuardResult(False, reason, **m)


def unknown(reason, **m):
    return GuardResult(None, reason, **m)


# -- publication profiles --------------------------------------------------------------------

def publication_profiles(extra_dirs=()):
    """{platform id: path} for every publication profile: core's, then any directory in
    `extra_dirs` (a test's fixture portal), later directories winning."""
    found = {}
    for directory in (PUBLICATION_DIR,) + tuple(extra_dirs or ()):
        for path in sorted(glob.glob(os.path.join(directory, "*.yaml"))):
            found[os.path.basename(path)[:-5]] = path
    return found


def load_publication_profile(platform_id, extra_dirs=()):
    """The publication profile for `platform_id`, or None when no file describes it. A file
    that does not parse, or whose id is not the filename stem, raises ValueError."""
    path = publication_profiles(extra_dirs).get(platform_id)
    if path is None:
        return None
    try:
        profile = load_file(path)
    except (YamlError, OSError) as exc:
        raise ValueError(f"{path}: {exc}")
    if not isinstance(profile, dict) or profile.get("id") != platform_id:
        raise ValueError(f"{path}: id {profile.get('id') if isinstance(profile, dict) else None!r}"
                         f" is not the filename stem {platform_id!r}")
    return profile


# -- publication profile flow rules (2.0.0) --------------------------------------------------
#
# What core/artifacts/shared/publication-profile.schema.json cannot say about a console flow,
# checked by scripts/check-integrity.py over core's profiles and available to any reader of a
# profile (profiles_extra included). Kept here, beside the profile loader, because the
# executor that runs profile intents and resolves drift (docs/portal-publishing-architecture.md
# Part 2.6) refuses on the same vocabulary: one list, never two that drift apart.

# Names no adaptive resolution may ever match, in every profile (Part 2.6, check 4). A
# profile's `deny` adds the console's own words for them (translations). Matched case-folded
# at the start of a word: "publish" refuses "Publishing", "pay" refuses "Payout".
DENY_VOCABULARY = ("submit", "publish", "release", "review", "send", "delete", "remove",
                   "cancel", "withdraw", "archive", "accept", "agree", "confirm", "sign", "pay",
                   "price", "tax", "rating", "i own", "licence", "license")

# Intents that may not appear in a flow at all, adaptive or not (Part 2.5): nothing the
# Factory runs cancels a pending review, withdraws or deletes a game, or replaces the build
# under review.
FORBIDDEN_INTENT_WORDS = ("cancel", "withdraw", "delet", "remov", "unpublish", "retract")

INTENT_CLASSES = ("reversible", "irreversible", "human")
_STATE_LISTS = ("submitted_states", "approved_states", "live_states", "rejected_states",
                "pending_states")
_LOCATOR_TEXT = ("name", "label", "placeholder", "text", "testid", "css", "xpath")


def _vocabulary_hit(text, vocabulary):
    """The first word of `vocabulary` that starts a word of `text`, case-folded; or None."""
    folded = str(text).casefold()
    for word in vocabulary:
        if re.search(r"(?<!\w)" + re.escape(str(word).casefold()), folded):
            return word
    return None


def deny_vocabulary(profile):
    """The base deny vocabulary plus the profile's own `deny` words."""
    extra = ((profile or {}).get("submission") or {}).get("deny") or []
    return tuple(DENY_VOCABULARY) + tuple(str(w) for w in extra)


def flow_problems(profile):
    """The flow rules a schema cannot state, as a list of messages (empty: none broken).

      * every intent has a class (reversible | irreversible | human), and its id is unique;
      * no intent cancels, withdraws, deletes, removes or unpublishes anything - by its id,
        its accepted names or any locator text;
      * every irreversible intent carries a profile locator ladder and no adaptive `names`,
        and every request_review intent is irreversible;
      * an intent's adaptive `names`, and the `dismissable` overlay names, match nothing in
        the deny vocabulary - such a resolution would be refused, so the profile may not
        offer it;
      * every *_states word is one of `status.states`; a flow with an irreversible intent
        names its `pending_states`, so status_gate can stop before an upload over a pending
        review; an `expect.status_in` names a list the profile fills.
    """
    submission = (profile or {}).get("submission") or {}
    flow = submission.get("flow") or []
    deny = deny_vocabulary(profile)
    problems = []
    seen = set()
    irreversible = False
    status = submission.get("status") or {}
    for index, intent in enumerate(flow):
        if not isinstance(intent, dict):
            problems.append(f"flow[{index}]: not an intent")
            continue
        iid = intent.get("id") or f"flow[{index}]"
        if iid in seen:
            problems.append(f"intent {iid}: id appears twice in the flow")
        seen.add(iid)
        kind = intent.get("class")
        if kind not in INTENT_CLASSES:
            problems.append(f"intent {iid}: no class (one of {', '.join(INTENT_CLASSES)})")
        texts = [iid.replace(".", " ").replace("_", " ")] + list(intent.get("names") or [])
        for locator in intent.get("target") or []:
            if isinstance(locator, dict):
                texts += [str(locator[k]) for k in _LOCATOR_TEXT if locator.get(k)]
        for text in texts:
            hit = _vocabulary_hit(text, FORBIDDEN_INTENT_WORDS)
            if hit:
                problems.append(f"intent {iid}: {text!r} is a {hit}* action - a flow never "
                                f"cancels, withdraws or deletes (no such intent may exist)")
                break
        if kind == "irreversible":
            irreversible = True
            if not intent.get("action") or not [
                    loc for loc in intent.get("target") or [] if isinstance(loc, dict) and loc]:
                problems.append(f"intent {iid}: irreversible without a profile locator ladder "
                                f"(`action` and `target`): it is never resolved adaptively")
            if intent.get("names"):
                problems.append(f"intent {iid}: irreversible intents carry no adaptive `names`")
        if intent.get("phase") == "request_review" and kind != "irreversible":
            problems.append(f"intent {iid}: a request_review intent is irreversible, not {kind}")
        for name in intent.get("names") or []:
            hit = _vocabulary_hit(name, deny)
            if hit:
                problems.append(f"intent {iid}: accepted name {name!r} matches the deny "
                                f"vocabulary ({hit!r}); an adaptive resolution to it would be "
                                f"refused - drop it from `names`")
        listed = (intent.get("expect") or {}).get("status_in")
        if listed and not status.get(listed):
            problems.append(f"intent {iid}: expect.status_in {listed} is empty or missing")
    for name in submission.get("dismissable") or []:
        hit = _vocabulary_hit(name, deny)
        if hit:
            problems.append(f"dismissable {name!r} matches the deny vocabulary ({hit!r})")
    states = list(status.get("states") or [])
    for key in _STATE_LISTS:
        for word in status.get(key) or []:
            if word not in states:
                problems.append(f"status.{key}: {word!r} is not one of status.states")
    if irreversible and not status.get("pending_states"):
        problems.append("the flow requests review but status.pending_states is empty: "
                        "status_gate could not stop before an upload over a pending review")
    return problems


# -- release guards --------------------------------------------------------------------------

def candidate_frozen(manifest):
    """release.machine.yaml: a commit_sha, packages, and a checksum for every package."""
    if not isinstance(manifest, dict):
        return unknown("no release-manifest")
    commit = manifest.get("commit_sha")
    if not isinstance(commit, str) or len(commit) < 7:
        return red("release-manifest names no commit_sha")
    packages = manifest.get("packages") or []
    if not packages:
        return red("release-manifest lists no packages: nothing was built to ship")
    bad = [p.get("filename") or "?" for p in packages
           if not _SHA256.match(str(p.get("checksum") or ""))]
    if bad:
        return red(f"package(s) without a sha256 checksum: {', '.join(bad)}")
    return green(f"commit {commit[:12]}, {len(packages)} package(s) with checksums",
                 commit=commit, packages=len(packages))


def _metadata_for(platform_id, manifest, store_metadata):
    metadata = (store_metadata or {}).get(platform_id)
    if metadata is None:
        metadata = ((manifest or {}).get("store_metadata") or {}).get(platform_id)
    return metadata if isinstance(metadata, dict) else None


def metadata_and_locales_present(platform_id, profile, manifest, store_metadata=None):
    """platform-publication.machine.yaml: descriptions, screenshots, icon and the required
    locales for this platform, per its pinned profile. `store_metadata` (a {platform:
    metadata} mapping a person or the release role prepared) is read before the manifest's
    own `store_metadata`."""
    if not isinstance(profile, dict):
        return unknown(f"no platform profile for {platform_id}")
    metadata = _metadata_for(platform_id, manifest, store_metadata)
    if metadata is None:
        return red(f"no store metadata for {platform_id}: release/<id>/store-metadata.json or "
                   f"release-manifest.store_metadata.{platform_id} is missing")
    wants = profile.get("metadata_requirements") or {}
    requirements = profile.get("requirements") or {}
    required_locales = [str(l) for l in requirements.get("locales_required") or []]
    description_locales = [str(l) for l in wants.get("descriptions_locales") or required_locales]
    problems = []
    descriptions = metadata.get("descriptions") or {}
    for locale in description_locales:
        if not str(descriptions.get(locale) or "").strip():
            problems.append(f"no {locale} description")
    minimum = wants.get("screenshots_min") or 0
    shots = metadata.get("screenshots") or []
    if len(shots) < minimum:
        problems.append(f"{len(shots)} screenshot(s), {minimum} required")
    if wants.get("icon_required") and not metadata.get("icon"):
        problems.append("no icon")
    if wants.get("age_rating_required") and not metadata.get("age_rating"):
        problems.append("no age rating")
    included = [str(l) for l in metadata.get("locales_included") or []]
    missing = [l for l in required_locales if l not in included]
    if missing:
        problems.append(f"required locale(s) not included: {', '.join(missing)}")
    if problems:
        return red(f"{platform_id}: " + "; ".join(problems), problems=problems)
    return green(f"{platform_id}: descriptions {', '.join(description_locales) or '-'}, "
                 f"{len(shots)} screenshot(s), locales {', '.join(included) or '-'}")


def store_metadata_complete(manifest, profiles, store_metadata=None):
    """release.machine.yaml (G6's predicate): every REQUIRED platform's metadata and
    required localizations are present. `profiles` is {platform id: platform profile}."""
    if not isinstance(manifest, dict):
        return unknown("no release-manifest")
    targets = [t for t in manifest.get("target_platforms") or [] if t.get("role") == "required"]
    if not targets:
        return red("release-manifest names no required platform")
    problems, checked = [], []
    for target in targets:
        pid = str(target.get("id"))
        result = metadata_and_locales_present(pid, (profiles or {}).get(pid), manifest,
                                              store_metadata)
        if result.value is None:
            return unknown(result.reason)
        if result.value is False:
            problems.append(result.reason)
        checked.append(pid)
    if problems:
        return red("; ".join(problems), platforms=checked)
    return green(f"store metadata complete for {', '.join(checked)}", platforms=checked)


# -- platform guards -------------------------------------------------------------------------

def package_shaped_to_profile(platform_id, profile, package, on_disk):
    """platform-publication.machine.yaml: bundle size and SDK wiring match the pinned profile.
    `package` is the manifest's entry for this platform; `on_disk` says whether the file was
    found and its sha256 equals the checksum (True/False), or None when nobody looked."""
    if package is None:
        return red(f"the release-manifest has no package for {platform_id}: the release's "
                   f"one bundle boots another platform (template contract build_target); "
                   f"{platform_id} ships only from a build of its own (verify and release, "
                   f"one bundle per platform)")
    if on_disk is False:
        return red(f"{package.get('filename')} is not in the checkout, or its bytes do not "
                   f"match the manifest's checksum")
    if not isinstance(profile, dict):
        return unknown(f"no platform profile for {platform_id}")
    limit = (profile.get("requirements") or {}).get("max_bundle_mb")
    size = package.get("size_mb")
    if limit is not None and isinstance(size, (int, float)) and size > limit:
        return red(f"{package.get('filename')} is {size} MB; {platform_id} allows {limit}",
                   size_mb=size, max_bundle_mb=limit)
    if on_disk is None:
        return unknown(f"{package.get('filename')}: the checkout was not read, so the bytes "
                       f"the manifest describes were not seen")
    return green(f"{package.get('filename')} {size} MB"
                 + (f" within {limit} MB" if limit is not None else "")
                 + ", bytes match the manifest", size_mb=size, max_bundle_mb=limit)


def assertions_pass(platform_id, results):
    """platform-publication.machine.yaml: every blocking assertion of the pinned profile
    holds. `results` are criterionResult dicts (`criterion_id`, `breached`, `severity`?) as
    verify's policy.assertions check recorded them; None when none were recorded."""
    if results is None:
        return unknown(f"no assertion results for {platform_id}: verify recorded no "
                       f"policy.assertions:{platform_id} evidence for this commit")
    blocking = [r.get("criterion_id") for r in results
                if r.get("breached") and r.get("severity", "blocking") == "blocking"]
    if blocking:
        return red(f"{platform_id}: blocking assertion(s) breached: {', '.join(blocking)}",
                   breached=blocking)
    warnings = [r.get("criterion_id") for r in results
                if r.get("breached") and r.get("severity", "blocking") != "blocking"]
    return green(f"{platform_id}: {len(results)} assertion(s) hold"
                 + (f"; warnings: {', '.join(warnings)}" if warnings else ""),
                 assertions=len(results), warnings=warnings)


# -- quorum guards ---------------------------------------------------------------------------

def _states(publications):
    return {p.get("platform_id"): p.get("state") for p in publications or [] if isinstance(p, dict)}


def all_targeted_validated(manifest, publications):
    if not isinstance(manifest, dict):
        return unknown("no release-manifest")
    states = _states(publications)
    targets = [str(t.get("id")) for t in manifest.get("target_platforms") or []]
    missing = [t for t in targets if t not in states]
    if missing:
        return unknown(f"no platform-publication yet for {', '.join(missing)}")
    not_validated = [t for t in targets if states[t] not in ("validated", "submitted",
                                                             "in-review", "live")]
    if not_validated:
        return red("not validated: " + ", ".join(f"{t} ({states[t]})" for t in not_validated))
    return green(f"validated: {', '.join(targets)}")


def required_all_live(manifest, publications):
    if not isinstance(manifest, dict):
        return unknown("no release-manifest")
    states = _states(publications)
    required = [str(t.get("id")) for t in manifest.get("target_platforms") or []
                if t.get("role") == "required"]
    missing = [t for t in required if t not in states]
    if missing:
        return unknown(f"no platform-publication yet for {', '.join(missing)}")
    not_live = [t for t in required if states[t] != "live"]
    if not_live:
        return red("not live: " + ", ".join(f"{t} ({states[t]})" for t in not_live))
    return green(f"live: {', '.join(required)}")


def none_permanently_rejected(manifest, publications):
    if not isinstance(manifest, dict):
        return unknown("no release-manifest")
    states = _states(publications)
    required = [str(t.get("id")) for t in manifest.get("target_platforms") or []
                if t.get("role") == "required"]
    rejected = [t for t in required if states.get(t) == "rejected"]
    if rejected:
        return red(f"rejected: {', '.join(rejected)}")
    return green("no required platform rejected")


# -- readiness -------------------------------------------------------------------------------

def unmet_prerequisites(profile, settings=None, entry=None):
    """The profile's `prerequisites` that apply and that no person has recorded in
    factory.publish.platforms.<id>.prerequisites_confirmed. `entry` is the release's
    game.config.yaml platform entry, or None when unknown: then every prerequisite applies,
    so an unknown is never read as satisfied."""
    confirmed = set((settings or {}).get("prerequisites_confirmed") or ())
    unmet = []
    for item in (profile or {}).get("prerequisites") or ():
        if not isinstance(item, dict) or item.get("id") in confirmed:
            continue
        when = item.get("when") or {}
        # An entry without a key is at the profile's default, which the tech plan never
        # writes (hosting): a `when` naming a value matches only an entry that states it.
        if entry is not None and any(entry.get(key) != value for key, value in when.items()):
            continue
        unmet.append(item)
    return unmet


def human_reason(profile, settings=None, credential_present=None, entry=None):
    """Why publishing on this platform is a person's act, or None when an adapter may act.
    `settings` is factory.publish.platforms.<id> (terms_confirmed, prerequisites_confirmed);
    `credential_present` whether the named credential variable is set (None: not checked);
    `entry` the release's game.config.yaml platform entry, for prerequisites limited by
    `when` (None: unknown, so every prerequisite applies)."""
    submission = (profile or {}).get("submission") or {}
    method = submission.get("method")
    if profile is None:
        return ("no-automated-method", "no publication profile describes how this portal is "
                                       "reached (core/reference/publication/)")
    if method in ("email", "manual"):
        return ("manual-submission", f"submission to this portal is {method}: a person does it")
    if method in ("api", "cli") and not submission.get("api"):
        return ("no-automated-method", f"method {method} without a documented tool")
    if method == "console":
        terms = submission.get("automation_terms")
        confirmed = bool((settings or {}).get("terms_confirmed"))
        if terms == "prohibited":
            return ("terms-unconfirmed", "the portal's terms prohibit automated use of its "
                                         "console: a person submits")
        if terms != "permitted" and not confirmed:
            return ("terms-unconfirmed", "whether the portal's terms permit automated use of "
                                         "its console is not established; a person records the "
                                         "finding in factory.publish.platforms.<id>."
                                         "terms_confirmed, or submits by hand")
    unmet = unmet_prerequisites(profile, settings, entry)
    if unmet:
        first = unmet[0]
        what = "; ".join(f"prerequisite {item.get('id')}: {str(item.get('note') or '').strip()}"
                         for item in unmet)
        return (first.get("reason") or "legal",
                f"{what} - a person does it and records it in factory.publish.platforms.<id>."
                f"prerequisites_confirmed")
    if method in ("api", "cli") and not (settings or {}).get("adapter"):
        # The portal's own tool exists; no adapter drives it in this Factory yet.
        return ("no-automated-method", f"the portal's {method} ({(submission.get('api') or {}).get('tool') or 'tool'}) "
                                       f"is the supported way in; no adapter drives it here, "
                                       f"so a person runs it with the packaged release")
    credential = submission.get("credential") or {}
    if credential.get("kind", "none") != "none" and credential_present is False:
        return ("credential-missing", f"{credential.get('env')} is not set: capture the "
                                      f"session first ({credential.get('capture') or 'see the publication profile'})")
    return None


def readiness(guard_results, human=None):
    """The record's readiness from its guard results ({name: GuardResult}) and
    `human_reason`'s answer."""
    values = [r.value for r in guard_results.values()]
    if any(v is False for v in values):
        return BLOCKED
    if any(v is None for v in values):
        return UNKNOWN
    if human is not None:
        return HUMAN_REQUIRED
    return READY


def idempotency_key(run_id, manifest_hash, platform_id):
    """Deterministic for (run, release manifest, platform): the same release published again
    from the same run finds its own draft; another manifest never collides with it."""
    import hashlib
    digest = hashlib.sha256(f"{run_id}|{manifest_hash}|{platform_id}".encode()).hexdigest()
    return f"wgf-{platform_id}-{digest[:16]}"
