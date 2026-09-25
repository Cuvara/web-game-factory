"""The `release` step: prepare a draft release from a verified commit, and nothing more.

    qa-report + verification-report   ──► may this run release? (lineage.py)
    + sdk-report + prototype-report       one passing verification, the newest, one commit
    checkout                           ──► HEAD is that commit, the tree is clean, and the
                                           bundle on disk is the one that was verified
    game repo `release:package`        ──► release/<release-id>/<platform>.zip + packages.json
    game repo `release:manifest`       ──► release/<release-id>/manifest.json (state draft)
    every package                      ──► checksum recorded and matching; audited (package.py)
                                       ──► release-manifest: the game's manifest, extended with
                                           what it was cleared by; schema-valid; written back
                                           to release/<release-id>/manifest.json

Outcomes (docs/workflow-module-contract.md §7, docs/release-module.md):

    no verification in the run, a dirty checkout or a
    verified dirty tree, a bundle that is not the verified one,
    a required gate (G4) not passed or superseded                BLOCKED: a person acts first
    verification not passed, stale qa-report, commit lineage
    broken, the shipped commit not approved by the newest review
    (`unreviewed`, `review-commit-mismatch`), packaging failed,
    a package that may not ship, a manifest that does not
    validate                                                     FAILED, not retryable
    otherwise                                                    SUCCESS, release-manifest

On refusal nothing is packaged (for evidence refusals) and no release-manifest is returned:
a draft that exists only when its preconditions held is what makes a draft mean something.

The step never pushes, tags, publishes or contacts a portal. Building, publishing and the
G5/G6 gates are later and elsewhere.
"""

import datetime
import json
import os
import re

from wgflib import agentenv, provenance
from wgflib import template_contract as contract
from wgflib.workflow import ArtifactOutput, StepOutcome, StepResult, WorkflowStep
from wgflib.workflow.contracts import ArtifactContracts
from wgflib.yamllite import YamlError, load_file

from wgf_verification.checks.platform import same_commit
from wgf_verification.session import locate_checkout

from .lineage import (BLOCKED, DEFAULT_REQUIRED_GATES, FAILED, Refusal, checkout_lineage,
                      commit_lineage, evidence_refusals, review_status)
from .package import RULES, audit_package, file_sha256
from .runner import ReleaseRunner, describe

__all__ = ["ReleaseStep", "SCHEMA_VERSION", "ROLE", "bundle_digest"]

SCHEMA_VERSION = provenance.version_of("release-manifest")
ROLE = "release"
READABLE_MAJOR = "1"
RELEASE_ID = re.compile(r"^r([0-9]+)$")
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
DEFAULT_TIMEOUTS = {"git": 30, "package": 900, "manifest": 300}
INPUTS = ("qa-report", "verification-report", "sdk-report", "prototype-report",
          "scaffold-record", "review-report")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def bundle_digest(root, relative):
    """The verification module's digest over a directory: sorted paths and file digests.

    Recomputed here, from the checkout, rather than trusted from the report: it is what ties
    the bytes about to be packaged to the bytes that were verified.
    """
    import hashlib
    base = os.path.join(root, relative)
    outer = hashlib.sha256()
    count = 0
    for directory, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d != "node_modules")
        for name in sorted(filenames):
            full = os.path.join(directory, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            with open(full, "rb") as handle:
                outer.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(handle.read()).digest())
            count += 1
    return ("sha256:" + outer.hexdigest()) if count else None


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-") or "untitled"


_CONTRACTS = []


def _contracts():
    """The engine's artifact contracts (wgflib/workflow/contracts.py), loaded once: the full
    schema through wgflib.jsonschema_lite, plus provenance identity, version and hash."""
    if not _CONTRACTS:
        _CONTRACTS.append(ArtifactContracts())
    return _CONTRACTS[0]


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


class _Refused(Exception):
    def __init__(self, refusals):
        super().__init__("; ".join(r.message for r in refusals))
        self.refusals = refusals


class ReleaseStep(WorkflowStep):
    type = "release"

    # Replaceable in tests: how commands run, what time it is, what the environment holds.
    runner_factory = ReleaseRunner
    clock = staticmethod(utc_now)
    environ = None

    def execute(self, inputs, context):
        for artifact_type, ref in sorted(inputs.refs.items()):
            major = str(ref.schema_version or READABLE_MAJOR).split(".", 1)[0]
            if major != READABLE_MAJOR:
                return StepResult.failed(
                    f"{artifact_type} has schema version {ref.schema_version}; this step "
                    f"reads {READABLE_MAJOR}.x", retryable=False)
        loaded = {t: inputs.load(t) for t in sorted(inputs.refs)}
        settings = dict(((context.config or {}).get("release") or {}))
        settings.update(self.params or {})
        timeouts = dict(DEFAULT_TIMEOUTS)
        timeouts.update(settings.get("timeouts") or {})
        env = dict(os.environ if self.environ is None else self.environ)
        hooks = context.process_hooks() if hasattr(context, "process_hooks") else {}
        # The packaging scripts are game code: the allowlist plus game_env_passthrough, not
        # the Factory's environment. A test's own `environ` is used as given.
        try:
            game_env = (agentenv.game_code_env(context.config, env) if self.environ is None
                        else env)
        except agentenv.ConfigError as exc:
            return StepResult.failed(str(exc), retryable=False)
        runner = self.runner_factory(env=game_env, hooks=hooks)

        # Two policies, each read from exactly one place so neither can be loosened from the
        # other: which gates must be passed is the workflow's (the release step's `with:
        # required_gates`, default G4 - never factory config); whether an unreviewed build
        # may be drafted is the installation's (factory.release.allow_unreviewed, default
        # false - never a workflow's `with:`).
        required_gates = (self.params or {}).get("required_gates", list(DEFAULT_REQUIRED_GATES))
        if not isinstance(required_gates, list) or not all(isinstance(g, str) and g
                                                           for g in required_gates):
            return StepResult.failed("release `with: required_gates` must be a list of gate "
                                     f"ids, not {required_gates!r}", retryable=False)
        allow_unreviewed = ((context.config or {}).get("release") or {}).get(
            "allow_unreviewed", False)
        if not isinstance(allow_unreviewed, bool):
            return StepResult.failed("factory.release.allow_unreviewed must be true or false, "
                                     f"not {allow_unreviewed!r}", retryable=False)
        try:
            refusals = evidence_refusals(
                inputs.refs, loaded, getattr(context, "run_id", None),
                gates_passed=getattr(context, "gates_passed", None) or (),
                required_gates=required_gates, allow_unreviewed=allow_unreviewed)
            if refusals:
                raise _Refused(refusals)
            root, where = locate_checkout(settings, context.config, loaded.get("scaffold-record"),
                                          env, section="release")
            if root is None:
                raise _Refused([Refusal(BLOCKED, "no-checkout", where.summary)])
            head = self._checkout_state(runner, root, loaded, timeouts,
                                        getattr(context, "run_id", None))
            game_config = self._game_config(root)
            release_id = self._release_id(root, head, settings)
            version = self._version(root, game_config, settings)
            self._package(runner, root, release_id, version, settings, timeouts)
            manifest, packages = self._collect(root, release_id, head, loaded, game_config)
            artifact = self._manifest(manifest, packages, release_id, head, root, loaded,
                                      inputs, context, game_config)
        except _Refused as refused:
            return self._refusal(refused.refusals, context)

        path = os.path.join(root, *contract.release_path(release_id, contract.RELEASE_MANIFEST))
        # temp + fsync + rename: a crash never leaves a torn manifest that a later run would
        # read as "no release here" and allocate the next id over.
        temporary = f"{path}.{os.getpid()}.tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(artifact, indent=2, sort_keys=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        evidence = artifact["evidence"]
        context.logger.info("release drafted", release_id=release_id, commit=head,
                            evidence=evidence["status"],
                            packages=[p["filename"] for p in artifact["packages"]])
        platforms = ", ".join(f"{p['platform_id']} {p['evidence_status']}/"
                              f"portal {p['portal_status']}" for p in evidence["platforms"])
        review = evidence["review"]["status"]
        message = (f"release {release_id} drafted at {head[:12]}: {len(artifact['packages'])} "
                   f"package(s), evidence {evidence['status']}"
                   + (f" ({platforms})" if platforms else "")
                   + ("; UNREVIEWED (review skipped; factory.release.allow_unreviewed)"
                      if review == "skipped" else
                      "; UNREVIEWED (no review in this run; factory.release.allow_unreviewed)"
                      if review == "absent" else f"; review approved {head[:12]}")
                   + "; nothing published")
        metadata = {"release_id": release_id, "commit": head, "state": "draft",
                    "evidence_status": evidence["status"], "review": review,
                    "packages": {p["filename"]: p["checksum"] for p in artifact["packages"]}}
        return StepResult.success([ArtifactOutput("release-manifest", artifact,
                                                  metadata=metadata)], message=message)

    # -- refusals ---------------------------------------------------------------------------

    def _refusal(self, refusals, context):
        data = {"refusals": [r.to_dict() for r in refusals]}
        text = "release refused: " + "; ".join(f"[{r.code}] {r.message}" for r in refusals)
        context.logger.warning("release refused", codes=[r.code for r in refusals])
        if any(r.kind == FAILED for r in refusals):
            return StepResult(StepOutcome.FAILED, error=text, retryable=False, data=data)
        return StepResult(StepOutcome.BLOCKED, message=text, data=data)

    # -- the checkout -----------------------------------------------------------------------

    def _git(self, runner, root, timeouts, *args):
        return runner.run(["git", *args], root, timeouts["git"])

    def _checkout_state(self, runner, root, loaded, timeouts, run_id=None):
        refusals = []
        head_result = self._git(runner, root, timeouts, "rev-parse", "HEAD")
        head = (head_result.stdout or "").strip() if head_result.ok else None
        if not head:
            raise _Refused([Refusal(BLOCKED, "no-commit",
                                    f"{root} is not a readable git repository: "
                                    + describe(head_result))])

        def git(*args):
            result = self._git(runner, root, timeouts, *args)
            return result.ok, result.stdout or ""

        refusals.extend(checkout_lineage(loaded, head, git, run_id))
        status = self._git(runner, root, timeouts, "status", "--porcelain",
                           "--untracked-files=all")
        if not status.ok:
            refusals.append(Refusal(BLOCKED, "dirty-checkout", "cannot read the working "
                                                                "tree: " + describe(status)))
        else:
            changed = [line for line in (status.stdout or "").splitlines() if line.strip()]
            if changed:
                refusals.append(Refusal(
                    BLOCKED, "dirty-checkout",
                    f"the checkout has {len(changed)} uncommitted change(s) "
                    f"({'; '.join(c.strip() for c in changed[:5])}): a release is made from a "
                    "commit, not a working tree. Commit or discard them, then re-run verify."))
        verified = (loaded["verification-report"].get("build_artifact") or {})
        out_dir = verified.get("path") or contract.DEFAULT_OUTPUT_DIR
        on_disk = bundle_digest(root, out_dir)
        if on_disk != verified.get("content_hash"):
            refusals.append(Refusal(
                BLOCKED, "bundle-not-verified",
                f"{out_dir}/ in the checkout ({on_disk or 'missing'}) is not the bundle that "
                f"was verified ({verified.get('content_hash')}). Re-run verify, which builds "
                "it, then release."))
        if refusals:
            raise _Refused(refusals)
        return head

    @staticmethod
    def _game_config(root):
        try:
            return load_file(os.path.join(root, contract.GAME_CONFIG)) or {}
        except (OSError, YamlError, ValueError):
            raise _Refused([Refusal(FAILED, "no-game-config",
                                    "the checkout has no readable game.config.yaml")])

    @staticmethod
    def _existing(root):
        """{release id: manifest} for every release/r<n>/ in the checkout."""
        base = os.path.join(root, contract.RELEASE_ROOT)
        found = {}
        for name in (os.listdir(base) if os.path.isdir(base) else []):
            if RELEASE_ID.match(name):
                found[name] = _read_json(os.path.join(base, name, contract.RELEASE_MANIFEST)) or {}
        return found

    def _release_id(self, root, head, settings):
        wanted = settings.get("release_id")
        existing = self._existing(root)
        if wanted:
            if not RELEASE_ID.match(str(wanted)):
                raise _Refused([Refusal(FAILED, "bad-release-id",
                                        f"release_id {wanted!r} must match ^r[0-9]+$")])
            other = existing.get(wanted, {}).get("commit_sha")
            if other and not same_commit(other, head):
                raise _Refused([Refusal(FAILED, "release-id-taken",
                                        f"release/{wanted}/ already holds a release of commit "
                                        f"{other[:12]}; a release id is never reused")])
            return str(wanted)
        # Idempotent: the same commit keeps the release id it was given.
        for rid, manifest in sorted(existing.items()):
            if manifest.get("commit_sha") and same_commit(manifest["commit_sha"], head):
                return rid
        numbers = [int(RELEASE_ID.match(r).group(1)) for r in existing]
        return f"r{max(numbers, default=0) + 1}"

    @staticmethod
    def _version(root, game_config, settings):
        version = settings.get("version") or (game_config.get("game") or {}).get("version") \
            or (_read_json(os.path.join(root, contract.PACKAGE_JSON)) or {}).get("version")
        if not version or not SEMVER.match(str(version)):
            raise _Refused([Refusal(FAILED, "bad-version",
                                    f"no semver version for the release (got {version!r}): set "
                                    "game.version in game.config.yaml or `with: version`")])
        return str(version)

    # -- packaging --------------------------------------------------------------------------

    @staticmethod
    def _script(root, name, *args):
        package = _read_json(os.path.join(root, contract.PACKAGE_JSON)) or {}
        if name not in (package.get("scripts") or {}):
            raise _Refused([Refusal(FAILED, "no-release-script",
                                    f"package.json has no {name} script: the game repository "
                                    "packages its own releases")])
        manager = "npm"
        if os.path.exists(os.path.join(root, contract.PNPM_LOCK)) \
                or str(package.get("packageManager", "")).startswith("pnpm"):
            manager = "pnpm"
        elif os.path.exists(os.path.join(root, "yarn.lock")):
            manager = "yarn"
        return [manager, "run", name] + (["--"] if manager == "npm" else []) + list(args)

    def _package(self, runner, root, release_id, version, settings, timeouts):
        kind = settings.get("kind") or ("initial" if release_id == "r1" else "content")
        steps = (
            ("package", self._script(root, contract.SCRIPT_RELEASE_PACKAGE,
                                     "--release", release_id)),
            ("manifest", self._script(root, contract.SCRIPT_RELEASE_MANIFEST,
                                      "--release", release_id, "--version", version,
                                      "--kind", kind, "--state", "draft")),
        )
        for key, argv in steps:
            result = runner.run(argv, root, timeouts[key])
            if not result.ok:
                kind_ = BLOCKED if result.error else FAILED
                raise _Refused([Refusal(kind_, f"{key}-failed",
                                        describe(result) + ": "
                                        + (result.tail(15) if hasattr(result, "tail") else ""))])

    def _collect(self, root, release_id, head, loaded, game_config):
        """The game's manifest and packages, checked. Refuses anything that may not ship."""
        base = os.path.join(root, *contract.release_path(release_id))
        refusals = []
        self._stamps = set()
        verified_dir = (loaded["verification-report"].get("build_artifact") or {}) \
            .get("path") or contract.DEFAULT_OUTPUT_DIR
        listed = _read_json(os.path.join(base, contract.RELEASE_PACKAGES))
        manifest = _read_json(os.path.join(base, contract.RELEASE_MANIFEST))
        if not isinstance(listed, list) or not listed:
            raise _Refused([Refusal(FAILED, "no-packages",
                                    f"release/{release_id}/packages.json is missing or empty")])
        if not isinstance(manifest, dict):
            raise _Refused([Refusal(FAILED, "invalid-manifest",
                                    f"release/{release_id}/manifest.json is missing or not "
                                    "JSON")])

        packages = []
        for entry in listed:
            filename = str((entry or {}).get("filename") or "")
            path = os.path.join(base, filename)
            if not filename or os.path.basename(filename) != filename or not os.path.isfile(path):
                refusals.append(Refusal(FAILED, "package-missing",
                                        f"packages.json names {filename!r}, which is not a "
                                        f"file in release/{release_id}/"))
                continue
            actual = file_sha256(path)
            if entry.get("checksum") != actual:
                refusals.append(Refusal(FAILED, "checksum-mismatch",
                                        f"{filename}: recorded {entry.get('checksum')}, the file "
                                        f"is {actual}"))
            audit = audit_package(path, os.path.join(root, verified_dir))
            for rule, name, detail in audit["findings"]:
                refusals.append(Refusal(FAILED, "package-content",
                                        f"{filename}: {rule}: {name}"
                                        + (f" ({detail})" if detail else "")))
            self._stamps.add(audit["timestamps"])
            packages.append({
                "platform_id": entry.get("platform_id"), "filename": filename,
                "size_mb": round(os.path.getsize(path) / 1024 / 1024, 3), "checksum": actual,
                "content_digest": audit["content_digest"], "files": audit["files"]})
        zips = sorted(n for n in os.listdir(base) if n.endswith(".zip"))
        unlisted = [n for n in zips if n not in {p["filename"] for p in packages}]
        if unlisted:
            refusals.append(Refusal(FAILED, "package-unlisted",
                                    f"release/{release_id}/ holds archives packages.json does "
                                    f"not list: {', '.join(unlisted)}"))
        targets = [p.get("id") for p in game_config.get("platforms") or [] if isinstance(p, dict)]
        missing = [t for t in targets if t not in {p["platform_id"] for p in packages}]
        if missing:
            refusals.append(Refusal(FAILED, "package-missing",
                                    "no package for target platform(s): " + ", ".join(missing)))

        # The full contract: the whole schema, the provenance identity, the contract's major
        # version and the content hash - the same check the engine applies to the draft.
        problems = _contracts().problems("release-manifest", manifest)
        if manifest.get("release_id") != release_id:
            problems.append(f"$.release_id is {manifest.get('release_id')!r}, not {release_id}")
        if not same_commit(str(manifest.get("commit_sha") or ""), head):
            problems.append(f"$.commit_sha is {manifest.get('commit_sha')!r}, not HEAD {head}")
        if manifest.get("state") != "draft":
            problems.append(f"$.state is {manifest.get('state')!r}, not draft")
        recorded = {p.get("filename"): p.get("checksum") for p in manifest.get("packages") or []}
        for package in packages:
            if recorded.get(package["filename"]) != package["checksum"]:
                problems.append(f"$.packages: {package['filename']} checksum "
                                f"{recorded.get(package['filename'])} is not the file's")
        for problem in problems:
            refusals.append(Refusal(FAILED, "invalid-manifest",
                                    f"release/{release_id}/manifest.json: {problem}"))
        if refusals:
            raise _Refused(refusals)
        return manifest, packages

    # -- the artifact -----------------------------------------------------------------------

    def _reproducibility(self):
        stamps = getattr(self, "_stamps", set())
        if stamps == {"normalized"}:
            return {"archive_bytes": "reproducible",
                    "note": "Every archive entry carries one normalized timestamp: the same "
                            "bundle packages to the same bytes."}
        if "file-mtimes" in stamps:
            return {"archive_bytes": "timestamp-dependent",
                    "note": "Packaged from the verified bundle without rebuilding it, so this "
                            "commit and bundle package to the same bytes again. The archives "
                            "embed each file's modification time, so a fresh build of "
                            "identical content gives a different checksum; content_digest "
                            "does not change."}
        return {"archive_bytes": "unknown"}

    @staticmethod
    def _template(root, scaffold):
        template = {}
        recorded = (scaffold or {}).get("template") or {}
        for key in ("repository", "commit_sha"):
            if recorded.get(key):
                template[key] = recorded[key]
        package = _read_json(os.path.join(root, contract.PACKAGE_JSON)) or {}
        marker = (package.get("wgf") or {}).get("template") if isinstance(package.get("wgf"),
                                                                           dict) else None
        version, source = None, None
        if isinstance(marker, dict) and marker.get("version"):
            version, source = str(marker["version"]), "package.json#wgf.template.version"
        if version is None:
            try:
                with open(os.path.join(root, contract.CHANGELOG), encoding="utf-8") as handle:
                    for line in handle:
                        found = re.match(r"^##\s*\[(\d+\.\d+\.\d+)\]", line)
                        if found:
                            version, source = (found.group(1),
                                               f"{contract.CHANGELOG} (first release heading)")
                            break
            except OSError:
                pass
        if version is None and package.get("version"):
            version, source = str(package["version"]), "package.json#version"
        if version:
            template.update(version=version, source=source)
        return template

    def _manifest(self, game_manifest, packages, release_id, head, root, loaded, inputs,
                  context, game_config):
        qa, vr = loaded["qa-report"], loaded["verification-report"]
        refs = inputs.refs
        produced_at = self.clock()
        title_id = qa.get("title_id") or game_manifest.get("title_id") or "untitled"
        pinned = [{"artifact_id": content["provenance"]["artifact_id"],
                   "artifact_type": artifact_type,
                   "content_hash": refs[artifact_type].content_hash}
                  for artifact_type, content in sorted(loaded.items())
                  if isinstance(content, dict) and isinstance(content.get("provenance"), dict)
                  and refs[artifact_type].content_hash]
        roles = {p.get("id"): p.get("role", "required")
                 for p in game_config.get("platforms") or [] if isinstance(p, dict)}
        platforms = [{
            "platform_id": entry["platform_id"],
            "role": entry.get("role") or roles.get(entry["platform_id"], "required"),
            "readiness": entry.get("readiness"),
            # Carried exactly: a PASS_MOCK stays PASS_MOCK, a missing one is UNVERIFIED.
            "evidence_status": entry.get("evidence_status") or "UNVERIFIED",
            "portal_status": entry.get("portal_status") or "BLOCKED_EXTERNAL",
            "external_approval": "not-claimed",
        } for entry in vr.get("platform_readiness") or []]
        platforms = [{k: v for k, v in p.items() if v is not None} for p in platforms]

        workflow = {k: v for k, v in {
            "run_id": getattr(context, "run_id", None),
            "workflow_id": getattr(context, "workflow_id", None),
            "step_id": getattr(context, "current_step", None),
            "visit": getattr(context, "visit", None),
            "execution": getattr(context, "execution", None),
            "idempotency_key": getattr(context, "idempotency_key", None),
        }.items() if v is not None}

        artifact = {
            "provenance": provenance.build(
                "release-manifest",
                artifact_id=provenance.artifact_id(
                    "release-manifest", _slug(title_id), produced_at,
                    int(RELEASE_ID.match(release_id).group(1))),
                produced_by=provenance.producer(ROLE),
                produced_at=produced_at,
                inputs=pinned,
                schema_version=SCHEMA_VERSION,
                title_id=title_id),
            "release_id": release_id,
            "title_id": title_id,
            "version": game_manifest["version"],
            "kind": game_manifest.get("kind", "content"),
            "state": "draft",
            "commit_sha": head,
            "build_ref": {k: v for k, v in (game_manifest.get("build_ref") or {}).items()
                          if k in ("url", "built_at", "ci_run_url")},
            "packages": packages,
            "target_platforms": game_manifest["target_platforms"],
            "changelog": game_manifest["changelog"],
            "frozen_at": None,
            "evidence": {
                "status": vr["evidence_status"],
                "qa_report": {"artifact_id": qa["provenance"]["artifact_id"],
                              "content_hash": refs["qa-report"].content_hash,
                              "verdict": qa["verdict"],
                              "evidence_status": qa["evidence_status"]},
                "verification_report": {"artifact_id": vr["provenance"]["artifact_id"],
                                        "content_hash": refs["verification-report"].content_hash,
                                        "verdict": vr["verdict"],
                                        "evidence_status": vr["evidence_status"]},
                "commit_lineage": [{"source": s, "commit_sha": sha}
                                   for s, sha in commit_lineage(loaded)]
                                  + [{"source": "checkout", "commit_sha": head}],
                # evidence_refusals has already refused an unreviewed build unless the
                # installation allowed one; here the review is only recorded, UNREVIEWED
                # loudly when that is what it is.
                "review": review_status(refs, loaded, allow_unreviewed=True)[1],
                "bundle_hash": vr["build_artifact"]["content_hash"],
                "platforms": platforms,
                "package_audit": {"status": "PASS", "rules": list(RULES)},
                "reproducibility": self._reproducibility(),
            },
        }
        if not artifact["build_ref"]:
            del artifact["build_ref"]
        if workflow.get("run_id"):
            artifact["workflow"] = workflow
        template = self._template(root, loaded.get("scaffold-record"))
        if template:
            artifact["template"] = template
        source_hash = (game_manifest.get("provenance") or {}).get("content_hash")
        if source_hash:
            artifact["evidence"]["source_manifest_hash"] = source_hash
        provenance.seal(artifact)

        problems = _contracts().problems("release-manifest", artifact)
        if problems:
            raise _Refused([Refusal(FAILED, "invalid-manifest",
                                    "the drafted release-manifest does not validate: " + p)
                            for p in problems])
        return artifact
