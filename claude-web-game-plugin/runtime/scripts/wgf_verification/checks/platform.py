"""Platform and policy: SDK integration per target, and the deterministic rules each
platform profile documents.

Everything here is local and deterministic: a platform's own review is not. A PASS on
`policy.assertions:<platform>` means the package satisfies the assertions the pinned profile
writes down; it says nothing about whether the portal will approve it, and the report never
claims otherwise.
"""

import os
import re

from wgflib import template_contract as contract

from ..model import BLOCKED, FAIL, PASS, PASS_MOCK, WARNING, Check, Evidence
from ..lineage import same_commit

__all__ = ["check_platform", "check_policy", "sdk_evidence_status", "live_observation",
           "same_commit"]

# An SDK feature is live evidence only when whoever observed it says, in so many words, that
# it was observed on the live portal - and does not also say it was a stand-in. Everything
# else a local run can produce (conformance suites against fake portal SDKs, SDK-mock unit
# suites, a browser with mocked portal scripts) is PASS_MOCK. Platform-agnostic on purpose:
# it reads the observation's wording, never a platform id.
_LIVE = re.compile(r"\blive[- ]portal\b", re.I)
_STAND_IN = re.compile(r"mock|fake|stub|simulat|emulat|not observed on the", re.I)


def live_observation(observed_by):
    text = str(observed_by or "")
    return bool(_LIVE.search(text)) and not _STAND_IN.search(text)


def sdk_evidence_status(features):
    """PASS when every working feature was observed live (or nothing needed observing),
    PASS_MOCK when any working feature was observed only against a stand-in."""
    working = [f for f in features if f.get("status") == "working"]
    if any(not live_observation(f.get("observed_by")) for f in working):
        return PASS_MOCK
    return PASS


AD_FEATURES = ("rewarded", "interstitial", "banner")
RUNTIME_FACTS = contract.RUNTIME_FACTS
COLLECT_FACTS = contract.COLLECT_FACTS
EVALUATE = contract.EVALUATE_ASSERTIONS


def _required(platform, session=None):
    """A platform's own checks are required when its role is - or, with a bundle per
    platform, always: every platform that gets a package must be shippable."""
    if session is not None and session.platform_build_mode is not None:
        return True
    return platform.get("role", "required") == "required"


def _sdk_entry(session, platform_id):
    report = session.inputs.get("sdk-report")
    if report is None:
        return None, None
    for entry in report.get("platforms") or []:
        if entry.get("platform_id") == platform_id:
            return report, entry
    return report, {}


def _declared_ads(session, platform_id):
    """Ad kinds this platform must support: game.config.yaml, plus the design's placements."""
    kinds = set((session.game_config.get("monetization") or {}).get("ad_kinds") or [])
    for placement in ((session.inputs.get("game-design") or {}).get("monetization") or {}) \
            .get("placements") or []:
        if placement.get("kind") in AD_FEATURES and platform_id in (placement.get("platforms")
                                                                   or [platform_id]):
            kinds.add(placement["kind"])
    return sorted(kinds & set(AD_FEATURES))


def check_platform(session):
    out = []
    if not session.platforms:
        out.append(session.record(Check(
            "platform.targets", "platform", "Target platforms declared", FAIL,
            message="game.config.yaml declares no platforms",
            evidence=[Evidence("file", "no platforms in game.config.yaml",
                               path=contract.GAME_CONFIG)])))
        return out
    for platform in session.platforms:
        out += [session.record(check) for check in _per_platform(session, platform)]
    out.append(session.record(_fallback(session)))
    return out


def _per_platform(session, platform):
    pid = platform["id"]
    required = _required(platform, session)
    common = {"category": "platform", "required": required, "platform_id": pid}

    yield _build_target(session, pid, common)

    # The profile the build is judged by: the pinned one, by content hash - never the
    # latest, and never a copy that only declares the pinned version.
    profile, source, pin_problems, content_hash = session.profile_identity(pid)
    pinned = str(platform.get("profile") or "")
    pinned_version = pinned.split("@", 1)[1] if "@" in pinned else None
    if pin_problems:
        yield Check(f"platform.profile:{pid}", title="Pinned platform profile", status=FAIL,
                    message=f"game.config.yaml pins {pinned or pid}, but the game's vendored "
                            "profile does not verify by content hash: "
                            + "; ".join(pin_problems),
                    evidence=[Evidence("file", problem, path=contract.platform_profile_path(pid))
                              for problem in pin_problems], **common)
    elif profile is None:
        yield Check(f"platform.profile:{pid}", title="Pinned platform profile", status=BLOCKED,
                    message=f"no profile for {pid} in config/platforms/ or the Factory",
                    evidence=[Evidence("observation", f"profile {pid} not found")], **common)
    elif pinned_version and str(profile.get("version")) != pinned_version:
        yield Check(f"platform.profile:{pid}", title="Pinned platform profile", status=FAIL,
                    message=f"game.config.yaml pins {pinned}, but {source} is version "
                            f"{profile.get('version')}",
                    evidence=[Evidence("file", f"{source} version {profile.get('version')}",
                                       path=source)], **common)
    else:
        yield Check(f"platform.profile:{pid}", title="Pinned platform profile", status=PASS,
                    message=f"{pid}@{profile.get('version')} from {source}"
                            + (f", {content_hash}" if content_hash else ""),
                    evidence=[Evidence("file", f"profile {pid}@{profile.get('version')}",
                                       path=source,
                                       **({"content_hash": content_hash} if content_hash
                                          else {}))], **common)

    report, entry = _sdk_entry(session, pid)
    reported = ((report or {}).get("build_ref") or {}).get("commit_sha")
    if report is None:
        for cid, title in ((f"platform.sdk-init:{pid}", "Platform SDK initializes"),
                           (f"platform.hooks:{pid}", "Platform integration hooks")):
            yield Check(cid, title=title, status=BLOCKED,
                        message="no sdk-report in this run: SDK integration is unverified",
                        evidence=[Evidence("observation", "sdk-report input is missing")],
                        **common)
    elif not same_commit(reported, session.commit):
        # SDK evidence about another commit says nothing about this one.
        for cid, title in ((f"platform.sdk-init:{pid}", "Platform SDK initializes"),
                           (f"platform.hooks:{pid}", "Platform integration hooks")):
            yield Check(cid, title=title, status=BLOCKED,
                        message=f"the sdk-report describes commit {reported or 'unknown'}, "
                                f"not the commit under test {session.commit or 'unknown'}",
                        evidence=[Evidence("artifact", "sdk-report.build_ref.commit_sha = "
                                                       f"{reported or 'missing'}"),
                                  Evidence("reference", "see source.upstream-commits",
                                           check_ref="source.upstream-commits")],
                        **common)
    else:
        yield _sdk_init(pid, entry, common)
        yield _hooks(session, pid, entry, common)

    yield _local_requirements(session, pid, profile, source, common)


def _build_target(session, pid, common):
    """Whether the bundle this platform would ship is its own build. On the pinned contract
    one build boots one adapter (template_contract.build_target). With one target that
    build is the platform's; with several, each platform gets a build of its own
    (platform_builds, build.platform:<id>), made against a config naming it alone - which is
    what makes the template boot its adapter and inject only its head script. The profile
    assertions cannot see which adapter boots (the template's `platform_sdk` fact echoes the
    platform it was asked about), so this check says it."""
    title = "The build targets this platform"
    if session.platform_build_mode is not None:
        build = session.platform_builds.get(pid)
        cid = f"platform.build-target:{pid}"
        if build is None or not build.built:
            return session.blocked_by(f"build.platform:{pid}", id=cid, title=title, **common)
        how = (f"built against {build.config}, whose only platform is {pid}"
               if build.config else f"built by the repository's {contract.SCRIPT_BUILD_PLATFORMS}")
        return Check(cid, title=title, status=PASS,
                     message=f"{build.path}/ boots the {pid} adapter: {how}",
                     evidence=[Evidence("artifact", f"{pid} bundle {build.content_hash}",
                                        path=build.path, content_hash=build.content_hash),
                               Evidence("reference", f"see build.platform:{pid}",
                                        check_ref=f"build.platform:{pid}")], **common)
    target = contract.build_target(session.platforms)
    evidence = [Evidence("file", f"game.config.yaml platforms[]: the build boots {target}",
                         path=contract.GAME_CONFIG)]
    if pid == target:
        return Check(f"platform.build-target:{pid}", title=title, status=PASS,
                     message=f"the bundle boots the {pid} adapter (game.config.yaml's first "
                             "required platform, else its first)",
                     evidence=evidence, **common)
    return Check(f"platform.build-target:{pid}", title=title, status=FAIL,
                 message=f"the one bundle this template contract builds boots {target}, not "
                         f"{pid}: a {pid} package of it would load {target}'s SDK on {pid}. "
                         f"{pid} needs its own build (per-platform builds are template "
                         "contract 2); until then it is not shippable",
                 evidence=evidence, **common)


def _feature_evidence(pid, feature):
    return Evidence("artifact", f"sdk-report {pid}.{feature.get('feature')} = "
                                f"{feature.get('status')}"
                                + (f" (observed by {feature['observed_by']})"
                                   if feature.get("observed_by") else ""))


def _sdk_init(pid, entry, common):
    title = "Platform SDK initializes"
    if not entry:
        return Check(f"platform.sdk-init:{pid}", title=title, status=FAIL,
                     message=f"sdk-report has no entry for {pid}",
                     evidence=[Evidence("artifact", f"sdk-report lists no {pid}")], **common)
    init = next((f for f in entry.get("features") or [] if f.get("feature") == "init"), None)
    if init is None:
        return Check(f"platform.sdk-init:{pid}", title=title, status=FAIL,
                     message=f"sdk-report does not report init for {pid}",
                     evidence=[Evidence("artifact", f"sdk-report {pid} has no init feature")],
                     **common)
    ok = init.get("status") in ("working", "not-required")
    strength = sdk_evidence_status([init]) if ok else None
    return Check(f"platform.sdk-init:{pid}", title=title, status=PASS if ok else FAIL,
                 message=f"init is {init.get('status')}"
                         + (" (observed against a stand-in portal SDK only)"
                            if strength == PASS_MOCK else ""),
                 evidence=[_feature_evidence(pid, init)], evidence_status=strength, **common)


def _hooks(session, pid, entry, common):
    title = "Platform integration hooks"
    if not entry:
        return Check(f"platform.hooks:{pid}", title=title, status=FAIL,
                     message=f"sdk-report has no entry for {pid}",
                     evidence=[Evidence("artifact", f"sdk-report lists no {pid}")], **common)
    features = {f.get("feature"): f for f in entry.get("features") or []}
    evidence = [_feature_evidence(pid, f) for name, f in sorted(features.items())
                if name != "init"]
    problems = [f"{name} is {f.get('status')}" for name, f in sorted(features.items())
                if name != "init" and f.get("status") not in ("working", "not-required")]
    for kind in _declared_ads(session, pid):
        if kind not in features:
            problems.append(f"{kind} ads are declared but the sdk-report has no {kind} feature")
    evidence.append(Evidence("reference", "declared ad kinds: "
                                          + (", ".join(_declared_ads(session, pid)) or "none")))
    if problems:
        return Check(f"platform.hooks:{pid}", title=title, status=FAIL,
                     message="; ".join(problems), evidence=evidence, **common)
    strength = sdk_evidence_status([f for name, f in features.items() if name != "init"])
    return Check(f"platform.hooks:{pid}", title=title, status=PASS,
                 message=f"{len(features) - ('init' in features)} hook(s) working or not required"
                         + (" (observed against stand-in portal SDKs only)"
                            if strength == PASS_MOCK else ""),
                 evidence=evidence, evidence_status=strength, **common)


def _local_requirements(session, pid, profile, source, common):
    """Profile requirements that can be decided from the bundle on disk."""
    cid, title = f"platform.requirements:{pid}", "Platform requirements met locally"
    if not session.passed("build.bundle"):
        return session.blocked_by("build.bundle", id=cid, title=title, **common)
    if profile is None:
        return session.blocked_by(f"platform.profile:{pid}", id=cid, title=title, **common)
    requirements = profile.get("requirements") or {}
    bundle, _env = session.platform_bundle(pid)
    locales_dir = f"{bundle}/locales"
    shipped = sorted(p.rsplit("/", 1)[-1][:-5] for p in session.walk(locales_dir)
                     if p.endswith(".json"))
    evidence = [Evidence("file", f"shipped locales: {', '.join(shipped) or 'none'}",
                         path=locales_dir),
                Evidence("reference", f"{pid} requires locales "
                                      f"{', '.join(requirements.get('locales_required') or [])}",
                         path=source)]
    problems = [f"required locale {loc} is not shipped"
                for loc in requirements.get("locales_required") or [] if loc not in shipped]
    design_locales = ((session.inputs.get("game-design") or {}).get("scope") or {}) \
        .get("locales") or []
    problems += [f"design locale {loc} is not shipped" for loc in design_locales
                 if loc not in shipped]
    if requirements.get("https_only") and session.runtime_facts is not None:
        insecure = ((session.runtime_facts.get("package") or {}).get("insecure_requests"))
        evidence.append(Evidence("file", f"insecure_requests = {insecure}", path=RUNTIME_FACTS))
        if insecure:
            problems.append(f"{insecure} insecure request(s) on an https-only platform")
    if problems:
        return Check(cid, title=title, status=FAIL, message="; ".join(problems),
                     evidence=evidence, **common)
    return Check(cid, title=title, status=PASS, message="locales and transport requirements met",
                 evidence=evidence, **common)


def _fallback(session):
    """The game must still run when no portal SDK is present - which is exactly the local
    browser the gameplay checks ran in. A boot there is the fallback path working."""
    title = "Runs without a portal SDK (fallback)"
    boot = session.results.get("gameplay.boot")
    if boot is None or boot.status == BLOCKED:
        return session.blocked_by("gameplay.boot", id="platform.fallback", category="platform",
                                  title=title)
    evidence = [Evidence("reference", f"gameplay.boot is {boot.status} in a browser with no "
                                      f"portal host", check_ref="gameplay.boot")]
    for pid_entry in ((session.inputs.get("sdk-report") or {}).get("platforms") or []):
        for feature in pid_entry.get("features") or []:
            if feature.get("feature") == "fallback":
                evidence.append(_feature_evidence(pid_entry.get("platform_id"), feature))
    status = PASS if boot.status == PASS else FAIL
    return Check("platform.fallback", "platform", title, status,
                 message="booted without a portal SDK" if status == PASS
                 else "did not boot without a portal SDK", evidence=evidence)


# -- policy ---------------------------------------------------------------------------------

def check_policy(session):
    out = [session.record(_runtime_facts(session))]
    performance = _device_performance(session)
    if performance is not None:
        out.append(session.record(performance))
    for platform in session.platforms:
        checks = _assertions(session, platform)
        for check in checks if isinstance(checks, list) else [checks]:
            out.append(session.record(check))
    return out


def _runtime_facts(session):
    title = "Runtime package facts measured"
    # Always required: every profile asserts on measured facts (https, loading API, perf),
    # and an assertion on a fact nobody measured is a breach, not a pass.
    required = True
    if not session.passed("build.build"):
        return session.blocked_by("build.build", id="policy.runtime-facts", category="policy",
                                  title=title, required=required)
    if not session.has_script(contract.SCRIPT_TEST_VERIFY):
        return Check("policy.runtime-facts", "policy", title,
                     BLOCKED if required else WARNING, required=required,
                     message="package.json has no test:verify script to measure runtime facts",
                     evidence=[Evidence("file", "no test:verify script",
                                        path=contract.PACKAGE_JSON)])
    # Never read a previous run's measurements: the file must be written by this run.
    session.remove(RUNTIME_FACTS)
    result = session.run(session.script_command(contract.SCRIPT_TEST_VERIFY), "browser")
    evidence = [Evidence.of_command(result)]
    facts = session.read_json(RUNTIME_FACTS) if result.ok else None
    if facts is not None:
        session.runtime_facts = facts
        perf = (facts.get("package") or {}).get("perf") or {}
        evidence.append(Evidence("file", "measured: " + ", ".join(
            f"{k}={v}" for k, v in sorted(perf.items())), path=RUNTIME_FACTS, data=facts,
            content_hash=session.file_hash(RUNTIME_FACTS)))
        return Check("policy.runtime-facts", "policy", title, PASS, required=required,
                     message="runtime facts measured against the built bundle",
                     evidence=evidence)
    status = BLOCKED if result.unavailable else FAIL
    return Check("policy.runtime-facts", "policy", title, status, required=required,
                 message=result.describe() + ("" if result.ok else "; no runtime facts"),
                 evidence=evidence)


def _device_performance(session):
    """The runtime facts' performance numbers, labelled for what they are. The template
    measures fps and time to interactive in desktop Chromium under a CPU throttle - a
    stand-in for a low-end device, not a device - so the evidence is PASS_MOCK, never PASS.
    Before, they sat inside the runtime-facts check's PASS (the 2.1.2 production run's
    "60 fps" was read as a device result). Not required: no portal profile of a target
    asserts an fps floor; the strategy's own floor is judged at G4 on device evidence."""
    facts = session.runtime_facts if isinstance(session.runtime_facts, dict) else {}
    perf = (facts.get("package") or {}).get("perf")
    if not perf:
        return None
    measured = ", ".join(f"{k}={v}" for k, v in sorted(perf.items()))
    return Check("policy.device-performance", "policy", "Performance on a real device",
                 PASS, required=False, evidence_status=PASS_MOCK,
                 message=f"{measured}: measured in CPU-throttled desktop Chromium, a proxy for "
                         "a low-end device, not a device; no device measurement in this run",
                 evidence=[Evidence("file", f"proxy measurement: {measured}",
                                    path=RUNTIME_FACTS)])


def _assertions(session, platform):
    pid = platform["id"]
    cid, title = f"policy.assertions:{pid}", "Platform profile assertions"
    common = {"category": "policy", "required": _required(platform, session),
              "platform_id": pid}
    if not session.passed("build.bundle"):
        return session.blocked_by("build.bundle", id=cid, title=title, **common)
    if session.platform_build_mode is not None and not session.passed(f"build.platform:{pid}"):
        return session.blocked_by(f"build.platform:{pid}", id=cid, title=title, **common)
    # The facts are measured on this platform's own bundle: with a Factory build, the
    # template's scripts read it through the config it was built against.
    _bundle, env = session.platform_bundle(pid)
    if not (session.exists(COLLECT_FACTS) and session.exists(EVALUATE)):
        return Check(cid, title=title, status=BLOCKED,
                     message=f"the repository has no {COLLECT_FACTS} / {EVALUATE}",
                     evidence=[Evidence("file", "assertion tooling missing",
                                        path=COLLECT_FACTS.rsplit("/", 1)[0])], **common)
    facts_out = contract.facts_path(pid)
    results_out = contract.assertions_path(pid)
    # Results left by an earlier run are not evidence about this one: an evaluation that
    # wrote nothing must not be read as the previous run's clean results.
    session.remove(facts_out)
    session.remove(results_out)
    collect = session.run(["node", COLLECT_FACTS, "--platform", pid, "--out", facts_out],
                          env=env or None)
    evidence = [Evidence.of_command(collect)]
    if not collect.ok:
        status = BLOCKED if collect.unavailable else FAIL
        return Check(cid, title=title, status=status,
                     message="facts could not be collected: " + collect.describe(),
                     evidence=evidence, **common)
    evaluate = session.run(["node", EVALUATE, "--platform", pid, "--facts", facts_out,
                            "--out", results_out], env=env or None)
    evidence.append(Evidence.of_command(evaluate))
    results = session.read_json(results_out)
    if not isinstance(results, list):
        status = BLOCKED if evaluate.unavailable else FAIL
        return Check(cid, title=title, status=status,
                     message="assertions produced no results: " + evaluate.describe(),
                     evidence=evidence, **common)
    session.assertions[pid] = results
    blocking = [r for r in results if r.get("breached") and r.get("severity") == "blocking"]
    warnings = [r for r in results if r.get("breached") and r.get("severity") != "blocking"]
    evidence.append(Evidence("file", f"{len(results)} assertion(s): {len(blocking)} blocking "
                                     f"breach(es), {len(warnings)} warning(s)",
                             path=results_out, data={"results": results},
                             content_hash=session.file_hash(results_out)))
    if not evaluate.ok and not blocking:
        # The evaluator failed without reporting a breach that explains it: its results are
        # not a clean bill.
        status = BLOCKED if evaluate.unavailable else FAIL
        return Check(cid, title=title, status=status, evidence=evidence, **common,
                     message="the evaluator exited non-zero without a blocking breach: "
                             + evaluate.describe())
    if blocking:
        return Check(cid, title=title, status=FAIL, evidence=evidence, **common,
                     message="breached: " + ", ".join(
                         f"{r['criterion_id']} (measured {r.get('measured')!r})"
                         for r in blocking))
    if not warnings:
        return Check(cid, title=title, status=PASS, evidence=evidence, **common,
                     message=f"all {len(results)} assertion(s) hold")
    # A warning-severity breach does not stop a release: the profile says so by its
    # severity. Reported on this check it would, because a required WARNING carries no
    # evidence stronger than UNVERIFIED and a release refuses that - with every target
    # required, any target's warning would. So this check states what its evidence
    # establishes - every blocking assertion holds, measured on this platform's bundle - and
    # the breached warnings go on an optional check of their own, still a WARNING, with the
    # same evidence. yandex_screenshots is one: it counts store screenshots, which
    # store-listing captures after verify and listing-validation judges.
    warned = f"policy.assertion-warnings:{pid}"
    named = ", ".join(f"{r['criterion_id']} (measured {r.get('measured')!r})"
                      for r in warnings)
    return [
        Check(cid, title=title, status=PASS, evidence=evidence, **common,
              message=f"every blocking assertion holds; {len(warnings)} warning-severity "
                      f"breach(es) of {len(results)} assertion(s), reported on {warned}"),
        Check(warned, title="Platform profile assertion warnings",
              status=WARNING, evidence=list(evidence), category="policy", required=False,
              platform_id=pid, message="warning-severity assertion(s) breached: " + named),
    ]
