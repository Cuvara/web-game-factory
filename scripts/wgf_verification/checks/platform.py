"""Platform and policy: SDK integration per target, and the deterministic rules each
platform profile documents.

Everything here is local and deterministic: a platform's own review is not. A PASS on
`policy.assertions:<platform>` means the package satisfies the assertions the pinned profile
writes down; it says nothing about whether the portal will approve it, and the report never
claims otherwise.
"""

import os

from ..model import BLOCKED, FAIL, PASS, WARNING, Check, Evidence

__all__ = ["check_platform", "check_policy"]

AD_FEATURES = ("rewarded", "interstitial", "banner")
RUNTIME_FACTS = "build/runtime-facts.json"
COLLECT_FACTS = "scripts/verify/collect-facts.mjs"
EVALUATE = "scripts/verify/evaluate-assertions.mjs"


def _required(platform):
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
                               path="game.config.yaml")])))
        return out
    for platform in session.platforms:
        out += [session.record(check) for check in _per_platform(session, platform)]
    out.append(session.record(_fallback(session)))
    return out


def _per_platform(session, platform):
    pid = platform["id"]
    required = _required(platform)
    common = {"category": "platform", "required": required, "platform_id": pid}

    # The profile the build is judged by: the pinned version, never the latest.
    profile, source = session.profile(pid)
    pinned = str(platform.get("profile") or "")
    pinned_version = pinned.split("@", 1)[1] if "@" in pinned else None
    if profile is None:
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
                    message=f"{pid}@{profile.get('version')} from {source}",
                    evidence=[Evidence("file", f"profile {pid}@{profile.get('version')}",
                                       path=source)], **common)

    report, entry = _sdk_entry(session, pid)
    if report is None:
        for cid, title in ((f"platform.sdk-init:{pid}", "Platform SDK initializes"),
                           (f"platform.hooks:{pid}", "Platform integration hooks")):
            yield Check(cid, title=title, status=BLOCKED,
                        message="no sdk-report in this run: SDK integration is unverified",
                        evidence=[Evidence("observation", "sdk-report input is missing")],
                        **common)
    else:
        yield _sdk_init(pid, entry, common)
        yield _hooks(session, pid, entry, common)

    yield _local_requirements(session, pid, profile, source, common)


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
    return Check(f"platform.sdk-init:{pid}", title=title, status=PASS if ok else FAIL,
                 message=f"init is {init.get('status')}", evidence=[_feature_evidence(pid, init)],
                 **common)


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
    return Check(f"platform.hooks:{pid}", title=title, status=PASS,
                 message=f"{len(features) - ('init' in features)} hook(s) working or not required",
                 evidence=evidence, **common)


def _local_requirements(session, pid, profile, source, common):
    """Profile requirements that can be decided from the bundle on disk."""
    cid, title = f"platform.requirements:{pid}", "Platform requirements met locally"
    if not session.passed("build.bundle"):
        return session.blocked_by("build.bundle", id=cid, title=title, **common)
    if profile is None:
        return session.blocked_by(f"platform.profile:{pid}", id=cid, title=title, **common)
    requirements = profile.get("requirements") or {}
    locales_dir = os.path.join(session.output_dir, "locales")
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
    for platform in session.platforms:
        out.append(session.record(_assertions(session, platform)))
    return out


def _runtime_facts(session):
    title = "Runtime package facts measured"
    # Always required: every profile asserts on measured facts (https, loading API, perf),
    # and an assertion on a fact nobody measured is a breach, not a pass.
    required = True
    if not session.passed("build.build"):
        return session.blocked_by("build.build", id="policy.runtime-facts", category="policy",
                                  title=title, required=required)
    if not session.has_script("test:verify"):
        return Check("policy.runtime-facts", "policy", title,
                     BLOCKED if required else WARNING, required=required,
                     message="package.json has no test:verify script to measure runtime facts",
                     evidence=[Evidence("file", "no test:verify script", path="package.json")])
    result = session.run(session.script_command("test:verify"), "browser")
    evidence = [Evidence.of_command(result)]
    facts = session.read_json(RUNTIME_FACTS) if result.ok else None
    if facts is not None:
        session.runtime_facts = facts
        perf = (facts.get("package") or {}).get("perf") or {}
        evidence.append(Evidence("file", "measured: " + ", ".join(
            f"{k}={v}" for k, v in sorted(perf.items())), path=RUNTIME_FACTS, data=facts))
        return Check("policy.runtime-facts", "policy", title, PASS, required=required,
                     message="runtime facts measured against the built bundle",
                     evidence=evidence)
    status = BLOCKED if result.unavailable else FAIL
    return Check("policy.runtime-facts", "policy", title, status, required=required,
                 message=result.describe() + ("" if result.ok else "; no runtime facts"),
                 evidence=evidence)


def _assertions(session, platform):
    pid = platform["id"]
    cid, title = f"policy.assertions:{pid}", "Platform profile assertions"
    common = {"category": "policy", "required": _required(platform), "platform_id": pid}
    if not session.passed("build.bundle"):
        return session.blocked_by("build.bundle", id=cid, title=title, **common)
    if not (session.exists(COLLECT_FACTS) and session.exists(EVALUATE)):
        return Check(cid, title=title, status=BLOCKED,
                     message=f"the repository has no {COLLECT_FACTS} / {EVALUATE}",
                     evidence=[Evidence("file", "assertion tooling missing",
                                        path="scripts/verify")], **common)
    facts_out = f"build/facts/{pid}.json"
    results_out = f"build/assertions/{pid}.json"
    collect = session.run(["node", COLLECT_FACTS, "--platform", pid, "--out", facts_out])
    evidence = [Evidence.of_command(collect)]
    if not collect.ok:
        status = BLOCKED if collect.unavailable else FAIL
        return Check(cid, title=title, status=status,
                     message="facts could not be collected: " + collect.describe(),
                     evidence=evidence, **common)
    evaluate = session.run(["node", EVALUATE, "--platform", pid, "--facts", facts_out,
                            "--out", results_out])
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
                             path=results_out, data={"results": results}))
    if blocking:
        return Check(cid, title=title, status=FAIL, evidence=evidence, **common,
                     message="breached: " + ", ".join(
                         f"{r['criterion_id']} (measured {r.get('measured')!r})"
                         for r in blocking))
    if warnings:
        return Check(cid, title=title, status=WARNING, evidence=evidence, **common,
                     message="warnings: " + ", ".join(r["criterion_id"] for r in warnings))
    return Check(cid, title=title, status=PASS, evidence=evidence, **common,
                 message=f"all {len(results)} assertion(s) hold")
