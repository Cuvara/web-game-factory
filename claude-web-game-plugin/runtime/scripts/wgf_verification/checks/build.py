"""Source and build: which commit is under test, and does it install, build and resolve."""

import os
import re
import shlex

from wgflib.template_contract import SCRIPT_BUILD

from ..model import BLOCKED, FAIL, PASS, WARNING, Check, Evidence
from ..lineage import CODE, lineage_problems

__all__ = ["check_source", "check_build"]

_URL_ATTR = re.compile(r"""\b(?:src|href)\s*=\s*["']([^"']+)["']""", re.I)
_CSS_URL = re.compile(r"""url\(\s*["']?([^"')]+)["']?\s*\)""", re.I)
_JS_ASSET = re.compile(
    r"""["'`]((?:\.{0,2}/)?(?:assets|locales|metadata|audio|images|fonts)/[^"'`\s?#]+\.[A-Za-z0-9]{2,5})["'`]""")
_EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", re.I)


def check_source(session):
    out = []
    head = session.run(["git", "rev-parse", "HEAD"], "git")
    if head.ok and head.stdout.strip():
        session.commit = head.stdout.strip()
        out.append(Check("source.commit", "source", "Commit under test", PASS,
                         message=session.commit,
                         evidence=[Evidence.of_command(head, f"HEAD is {session.commit}")]))
        status = session.run(["git", "status", "--porcelain"], "git")
        changed = [line for line in status.stdout.splitlines() if line.strip()]
        session.dirty = bool(changed) if status.ok else None
        if status.ok and not changed:
            out.append(Check("source.clean-tree", "source", "Working tree matches the commit",
                             PASS, required=False, message="no uncommitted changes",
                             evidence=[Evidence.of_command(status, "working tree is clean")]))
        else:
            summary = (f"{len(changed)} uncommitted change(s): the build is not reproducible "
                       f"from {session.commit[:12]}" if status.ok else status.describe())
            out.append(Check("source.clean-tree", "source", "Working tree matches the commit",
                             WARNING, required=False, message=summary,
                             evidence=[Evidence.of_command(status, summary)]))
    else:
        out.append(Check("source.commit", "source", "Commit under test", BLOCKED,
                         message="the checkout is not a readable git repository; a report "
                                 "that cannot name its commit is not evidence about any build",
                         evidence=[Evidence.of_command(head)]))

    out.append(_upstream_commits(session))
    return out


def _upstream_commits(session):
    """Is the evidence from upstream about the commit being verified, by the lineage rule?

    wgf_verification/lineage.py, docs/core-contracts.md §5: the sdk-report's commit is the
    commit under test; the prototype-report's commit is the one sdk built on; and the
    commits between them are exactly the sdk step's keyed commits. Without an sdk-report,
    the prototype-report's commit is the commit under test.

    Required when there is something to compare: evidence about another commit, or a
    commit nobody reviewed riding between develop's and sdk's, cannot vouch for this build.
    BLOCKED rather than FAIL - the game is not at fault, the evidence is - so the run stops
    for someone to re-run the steps that produce it.
    """
    seen = []
    for artifact_type in ("prototype-report", "sdk-report"):
        content = session.inputs.get(artifact_type)
        if content is None:
            continue
        build_ref = (content or {}).get("build_ref") or {}
        seen.append((artifact_type, build_ref.get("commit_sha")))
        if artifact_type == "sdk-report" and "base_commit_sha" in build_ref:
            seen.append(("sdk-report base", build_ref.get("base_commit_sha")))
    title = "Upstream reports describe this commit"
    if not seen:
        return Check("source.upstream-commits", "source", title, WARNING, required=False,
                     message="no prototype-report or sdk-report in this run to compare",
                     evidence=[Evidence("observation", "no upstream build_ref to compare")])
    if not session.commit:
        return session.blocked_by("source.commit", id="source.upstream-commits",
                                  category="source", title=title)
    evidence = [Evidence("reference", f"{t}.build_ref.commit_sha = {sha or 'missing'}")
                for t, sha in seen]

    def git(*args):
        result = session.run(["git", *args], "git")
        return result.ok, result.stdout

    prototype = session.inputs.get("prototype-report")
    problems = lineage_problems(
        verified=session.commit,
        prototype_commit=((prototype or {}).get("build_ref") or {}).get("commit_sha"),
        has_prototype=prototype is not None,
        sdk_report=session.inputs.get("sdk-report"), git=git,
        run_id=getattr(session, "run_id", None))
    if problems:
        return Check("source.upstream-commits", "source", title, BLOCKED,
                     message=f"{CODE}: " + "; ".join(problems)
                             + f". The evidence does not describe {session.commit[:12]}: "
                               "re-run the steps that produce it at this commit",
                     evidence=evidence)
    return Check("source.upstream-commits", "source", title, PASS,
                 message="the upstream reports follow the commit lineage to the commit under "
                         "test", evidence=evidence)


def check_build(session):
    out = [_install(session)]
    if session.passed("build.install"):
        out.append(session.record(_build(session)))
    else:
        out.append(session.record(session.blocked_by(
            "build.install", id="build.build", category="build", title="Production build")))
    if session.passed("build.build"):
        out.append(session.record(_bundle(session)))
        out.append(session.record(_asset_resolution(session)))
    else:
        for cid, title in (("build.bundle", "Generated bundle"),
                           ("build.asset-resolution", "Bundle references resolve")):
            out.append(session.record(session.blocked_by(
                "build.build", id=cid, category="build", title=title)))
    return out


def _install(session):
    command = session.install_command()
    result = session.run(command, "install")
    status = PASS if result.ok else (BLOCKED if result.unavailable else FAIL)
    return session.record(Check(
        "build.install", "build", "Dependencies install from the lockfile", status,
        message=result.describe(), evidence=[Evidence.of_command(result)]))


def _build(session):
    configured = (session.game_config.get("build") or {}).get("command")
    command = shlex.split(configured) if configured else session.script_command(SCRIPT_BUILD)
    result = session.run(command, "build")
    status = PASS if result.ok else (BLOCKED if result.unavailable else FAIL)
    return Check("build.build", "build", "Production build", status, message=result.describe(),
                 evidence=[Evidence.of_command(result)])


def _bundle(session):
    out_dir = session.output_dir
    title = "Generated bundle"
    if not os.path.isdir(session.path(out_dir)):
        return Check("build.bundle", "build", title, FAIL,
                     message=f"the build succeeded but produced no {out_dir}/",
                     evidence=[Evidence("file", f"{out_dir}/ does not exist", path=out_dir)])
    digest, count, size = session.digest_tree(out_dir)
    session.build_artifact = {"path": out_dir, "content_hash": digest, "files": count,
                              "bytes": size}
    evidence = [Evidence("artifact", f"{out_dir}/: {count} files, {size} bytes", path=out_dir,
                         content_hash=digest)]
    problems = []
    if not session.exists(out_dir, "index.html"):
        problems.append(f"{out_dir}/index.html is missing: a portal has no entry point")

    size_mb = size / 1024 / 1024
    for platform in session.platforms:
        profile, source = session.profile(platform["id"])
        limit = ((profile or {}).get("requirements") or {}).get("max_bundle_mb")
        if isinstance(limit, (int, float)):
            evidence.append(Evidence("reference", f"{platform['id']} max_bundle_mb = {limit}",
                                     path=source))
            if size_mb > limit:
                problems.append(f"bundle is {size_mb:.2f} MB, over {platform['id']}'s "
                                f"{limit} MB limit")
    if problems:
        return Check("build.bundle", "build", title, FAIL, message="; ".join(problems),
                     evidence=evidence)
    return Check("build.bundle", "build", title, PASS,
                 message=f"{count} files, {size_mb:.2f} MB, entry point present",
                 evidence=evidence)


def _asset_resolution(session):
    """Every local URL the built HTML, CSS and JS name exists in the bundle."""
    out_dir = session.output_dir
    root = session.path(out_dir)
    missing, scanned, references = [], 0, 0
    for rel in session.walk(out_dir):
        ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
        if ext not in ("html", "css", "js", "mjs"):
            continue
        scanned += 1
        with open(session.path(rel), encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        here = os.path.dirname(session.path(rel))
        found = []
        if ext == "html":
            found += [(u, here) for u in _URL_ATTR.findall(text)]
        if ext in ("html", "css"):
            found += [(u, here) for u in _CSS_URL.findall(text)]
        if ext in ("js", "mjs"):
            # String literals in a bundle are resolved against the page, not the script.
            found += [(u, root) for u in _JS_ASSET.findall(text)]
        for url, base in found:
            url = url.split("?", 1)[0].split("#", 1)[0].strip()
            if not url or _EXTERNAL.match(url) or "${" in url:
                continue
            references += 1
            target = os.path.join(root, url.lstrip("/")) if url.startswith("/") else \
                os.path.normpath(os.path.join(base, url))
            if not os.path.exists(target):
                missing.append(f"{rel} -> {url}")

    evidence = [Evidence("file", f"scanned {scanned} HTML/CSS/JS files in {out_dir}/, "
                                 f"{references} local references", path=out_dir)]
    title = "Bundle references resolve"
    if missing:
        evidence.append(Evidence("observation", "unresolved: " + "; ".join(sorted(missing)[:25]),
                                 data={"unresolved": sorted(missing)}))
        return Check("build.asset-resolution", "build", title, FAIL,
                     message=f"{len(missing)} reference(s) point at files not in the bundle",
                     evidence=evidence)
    return Check("build.asset-resolution", "build", title, PASS,
                 message=f"{references} local references, all present", evidence=evidence)
