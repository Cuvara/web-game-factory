"""The `store-listing` step: the verified build's store package, captured from the build.

    inputs    qa-report, verification-report, game-design, scaffold-record (required);
              sdk-report, prototype-report, title-strategy, asset-manifest,
              playability-report, content-sufficiency-report, listing-validation-report,
              triage-report (read when present)
    output    store-listing, on every outcome that could write one
    effect    none in the checkout: the bundle is served read-only; everything lands under
              <run>/store-listing/<visit>-<attempt>/

    SUCCESS   the package is complete: every canonical rendition, enough screenshots, copy
              in every required locale, one rendition per platform. `status: incomplete`
              is also SUCCESS - loudly, with `problems` - so listing-validation can say
              exactly what is missing and whether a person must act (its BLOCKED) or the
              step should try again (its FAIL, route `listing`)
    BLOCKED   a required gate not passed; no checkout, or HEAD not the verified commit, or
              the bundle on disk not the verified one; no browser or no capture configured
              (never a silent pass). The listing, status `blocked`, is still written
    FAILED    the verification did not pass, or names another commit than the qa-report
              (not retryable); the capture broke (retryable, once)
    WAITING   an input is missing

Every file the listing names is written at a deterministic path and recorded with its
sha256 (store-listing.schema.json). See docs/store-listing-module.md.

The copy is held to the build (buildfacts.py): the content-sufficiency report of the listed
build (its commit, or the development commit the sdk commit sits on) gives the counts the
copy may state (`facts.measured`), the probe's inputs while the listing was captured give
the devices its controls text names (`facts.probe_inputs`), and the run's quality tier
(`facts.quality`) the writer - the copywriter agent at the release tier - and the bars.
Re-entered through triage (route `listing`), the copywriter's brief carries the store-copy
findings listing-validation raised.
"""

import datetime
import json
import os
import shutil

from wgflib import checkout as checkout_lock
from wgflib import procs, provenance
from wgflib.yamllite import YamlError, load_file
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep

from wgf_release.lineage import developed_commit
from wgf_release.step import bundle_digest
from wgf_verification.lineage import same_commit
from wgf_verification.session import locate_checkout

from . import brand, buildfacts, capture, grounding, media, package as pkg, platforms
from .copywriter import write_copy
from .facts import extract, font_assets, hero_asset, read_runtime_assets, read_strings
from .settings import Settings, SettingsError

__all__ = ["StoreListingStep", "REQUIRED_INPUTS", "OPTIONAL_INPUTS", "DEFAULT_REQUIRED_GATES"]

REQUIRED_INPUTS = ("qa-report", "verification-report", "game-design", "scaffold-record")
OPTIONAL_INPUTS = ("sdk-report", "prototype-report", "title-strategy", "asset-manifest",
                   "playability-report", "content-sufficiency-report", "listing-validation-report",
                   "triage-report")
# The quality dimension store copy is: the findings of it are the copywriter's.
COPY_DIMENSION = "store-copy"
DEFAULT_REQUIRED_GATES = ("G4",)
ROLE = "release"
DEFAULT_OUTPUT_DIR = "dist"


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Stop(Exception):
    """Ends the step with `result` (a StepResult) after the listing is written."""

    def __init__(self, outcome, message, retryable=False):
        super().__init__(message)
        self.outcome, self.message, self.retryable = outcome, message, retryable


class StoreListingStep(WorkflowStep):
    type = "store-listing"
    clock = staticmethod(_utc_now)
    # Replaceable in tests: how the browser capture runs (capture.run_capture's signature).
    capture_runner = staticmethod(capture.run_capture)
    environ = None

    # -- execute ----------------------------------------------------------------------------

    def execute(self, inputs, context):
        try:
            self.settings = Settings.resolve(context.config, self.params)
        except SettingsError as exc:
            return StepResult.failed(str(exc), retryable=False)
        missing = [t for t in REQUIRED_INPUTS if t not in inputs]
        if missing:
            return StepResult.waiting_for_input(
                f"store-listing needs {', '.join(missing)} in the run: there is no verified "
                "build to capture")
        with checkout_lock.StepLease(context) as lease:
            return self._execute(inputs, context, lease)

    def _execute(self, inputs, context, lease):
        loaded = {t: inputs.load(t) for t in REQUIRED_INPUTS + OPTIONAL_INPUTS if t in inputs}
        qa, vr = loaded["qa-report"], loaded["verification-report"]
        design, scaffold = loaded["game-design"], loaded["scaffold-record"]
        title_id = scaffold.get("title_id") or design.get("title_id") or qa.get("title_id") or "untitled"
        commit = str((qa.get("build_ref") or {}).get("commit_sha") or "")
        self._ctx = {"context": context, "inputs": inputs, "title_id": title_id, "commit": commit,
                     "problems": [], "started": self.clock()}
        try:
            reference = load_file(self.settings.reference_path)
        except (OSError, YamlError, ValueError) as exc:
            return StepResult.failed(f"the store listing reference cannot be read: {exc}",
                                     retryable=False)
        self._ctx["reference"] = reference

        # The evidence: a passing verification of one commit, behind the gates.
        required_gates = (self.params or {}).get("required_gates", list(DEFAULT_REQUIRED_GATES))
        if not isinstance(required_gates, list) or not all(isinstance(g, str) for g in required_gates):
            return StepResult.failed("store-listing `with: required_gates` must be a list of gate "
                                     f"ids, not {required_gates!r}", retryable=False)
        unpassed = [g for g in required_gates if g not in (getattr(context, "gates_passed", None) or ())]
        if unpassed:
            return self._blocked(f"{', '.join(unpassed)} has not been passed in this run, or a newer "
                                 "verification superseded its decision: a store listing is made only "
                                 "of a build a person passed. Decide the gate, then resume.")
        if qa.get("verdict") != "pass" or vr.get("verdict") != "PASS":
            return StepResult.failed(
                f"the newest qa-report's verdict is {qa.get('verdict')!r} and the "
                f"verification-report's {vr.get('verdict')!r}: a store listing is made only of a "
                "build that passed verification", retryable=False)
        vr_commit = str((vr.get("commit") or {}).get("sha") or "")
        if len(commit) != 40 or not same_commit(commit, vr_commit):
            return StepResult.failed(
                f"the qa-report names commit {commit[:12] or 'none'} and the verification-report "
                f"{vr_commit[:12] or 'none'}: the listing would be of an unverified build",
                retryable=False)

        # The checkout: HEAD is that commit and the bundle on disk is the verified one.
        env = dict(os.environ if self.environ is None else self.environ)
        root, where = locate_checkout(self.params or {}, context.config, scaffold, env,
                                      section="listing", logger=context.logger)
        if root is None:
            return self._blocked(f"no game checkout to capture: {where.summary}")
        try:
            lease.take(root)
        except checkout_lock.CheckoutLocked as exc:
            return self._blocked(str(exc))
        head = procs.run(["git", "rev-parse", "HEAD"], cwd=root, timeout=30)
        head_sha = (head.stdout or "").strip() if head.ok else ""
        if not head_sha:
            return self._blocked(f"{root} is not a readable git repository: {head.tail(3)}")
        if not same_commit(head_sha, commit):
            return self._blocked(f"the checkout's HEAD is {head_sha[:12]}, but the verified build is "
                                 f"{commit[:12]}: the checkout moved after verification. Check out "
                                 "the verified commit (or re-run verify) and resume.")
        verified = vr.get("build_artifact") or {}
        out_dir = verified.get("path") or DEFAULT_OUTPUT_DIR
        dist = os.path.join(root, out_dir)
        on_disk = bundle_digest(root, out_dir) if os.path.isdir(dist) else None
        if not verified.get("content_hash") or on_disk != verified.get("content_hash"):
            return self._blocked(f"{out_dir}/ in the checkout ({on_disk or 'missing'}) is not the "
                                 f"bundle that was verified ({verified.get('content_hash')}): a "
                                 "listing shows the build that ships. Re-run verify, then resume.")
        self._ctx["build"] = {"bundle_hash": verified["content_hash"], "path": out_dir}

        # Where the package goes: keyed by step and visit, emptied first.
        scratch = os.path.join(context.run_dir, getattr(context, "current_step", None) or "store-listing",
                               f"{getattr(context, 'visit', 1)}-{getattr(context, 'attempt', 1)}")
        shutil.rmtree(scratch, ignore_errors=True)
        package_dir = os.path.join(scratch, "package")
        os.makedirs(package_dir)
        self._ctx.update(scratch=scratch, package_dir=package_dir, root=root, dist=dist)

        previous = loaded.get("listing-validation-report")
        if previous is not None and getattr(context, "entered_by", None):
            context.logger.info("store listing re-entered", entered_by=context.entered_by,
                                failed=(previous.get("failed") or [])[:10])

        try:
            game_config = load_file(os.path.join(root, "game.config.yaml")) or {}
        except (OSError, YamlError, ValueError):
            game_config = {}
        strings = read_strings(dist)
        runtime_assets = read_runtime_assets(dist)
        facts = extract(design, sdk_report=loaded.get("sdk-report"), scaffold=scaffold, strings=strings,
                        runtime_assets=runtime_assets, game_config=game_config,
                        prototype_report=self._report_of_this_build(loaded.get("prototype-report"), root,
                                                                    head_sha, context))
        self._ground_in_build(facts, design, loaded, reference, commit, context)
        self._ctx["facts"] = facts

        targets = platforms.targets(scaffold, self.settings.platforms)
        profiles = {}
        for pid, _role, _version in targets:
            try:
                profiles[pid] = platforms.load_profile(pid)
            except platforms.ProfileError as exc:
                return StepResult.failed(str(exc), retryable=False)
        locales = self._locales(design, profiles, strings)

        if self.settings.capture_kind == "none":
            return self._blocked("factory.listing.capture.kind is `none`: a store listing needs "
                                 "screenshots of the running build, and a listing without them would "
                                 "be a silent pass. Configure the browser capture and resume.")
        try:
            with capture.BundleServer(dist, os.path.join(scratch, "brand")) as server:
                self._ctx["server"] = server
                screenshots, capture_record = self._capture_screens(context, reference, package_dir)
                facts["probe_inputs"] = buildfacts.probe_devices(
                    (self._ctx.get("capture_report") or {}).get("viewports"))
                if facts["probe_inputs"]:
                    facts["sources"]["probe_inputs"] = "capture: play probe inputs[] while captured"
                trailer = self._trailer(capture_record, screenshots, package_dir)
                branding = self._branding(context, reference, facts, design, runtime_assets, screenshots,
                                          package_dir)
                copies, writer = self._copy(context, facts, locales, reference, scratch)
                renditions, derive = self._platforms(targets, profiles, reference, screenshots, branding,
                                                     trailer, copies, package_dir, context)
                self._derive(context, derive, renditions, capture_record)
        except _Stop as stop:
            return self._finish(stop.outcome, stop.message, retryable=stop.retryable)
        for locale, text in copies.items():
            if text is not None:
                pkg.write_json(os.path.join(package_dir, "copy", f"{locale}.json"), text)
        return self._finish("SUCCESS", None, screenshots=screenshots, trailer=trailer, branding=branding,
                            copies=copies, writer=writer, renditions=renditions, capture=capture_record,
                            facts=facts)

    # -- the parts --------------------------------------------------------------------------

    def _locales(self, design, profiles, strings=None):
        """en, every targeted platform's required locales, and every locale of the design's
        scope the bundle ships strings for (grounded copy comes free there)."""
        if self.settings.locales is not None:
            return list(dict.fromkeys(self.settings.locales))
        locales = ["en"]
        for profile in profiles.values():
            for locale in platforms.locales_for(profile):
                if locale not in locales:
                    locales.append(locale)
        scoped = [str(l).lower() for l in (design.get("scope") or {}).get("locales") or [] if isinstance(l, str)]
        for locale in scoped:
            if locale in (strings or {}) and locale not in locales:
                locales.append(locale)
        return locales

    def _problem(self, code, message, severity="error", subject=None):
        self._ctx["problems"].append({"code": code, "severity": severity, "message": message,
                                      "subject": subject})

    def _viewports(self, design, reference):
        if self.settings.viewports:
            return [dict(v) for v in self.settings.viewports]
        sizes = ((reference.get("renditions") or {}).get("screenshots") or {})
        landscape = sizes.get("landscape") or {"width": 1920, "height": 1080}
        portrait = sizes.get("portrait") or {"width": 1080, "height": 1920}
        orientation = ((design.get("build_spec") or {}).get("responsive") or {}).get("orientation")
        both = [{"id": "landscape", "width": int(landscape["width"]), "height": int(landscape["height"]),
                 "mobile": False},
                {"id": "portrait", "width": int(portrait["width"]), "height": int(portrait["height"]),
                 "mobile": True}]
        if orientation == "portrait":
            return [both[1], both[0]]
        return both

    def _run_capture(self, context, job, log_name):
        hooks = context.process_hooks() if hasattr(context, "process_hooks") else {}
        return self.capture_runner(job, checkout=self._ctx["root"], node=self.settings.node,
                                   timeout=self.settings.capture_timeout, config=context.config,
                                   hooks=hooks, log_path=os.path.join(self._ctx["scratch"], log_name))

    def _capture_screens(self, context, reference, package_dir):
        """Screenshots and the recording: served bundle, the capture script, retries with a
        longer play window when too few frames are usable."""
        cap = reference.get("capture") or {}
        shots_spec = (reference.get("renditions") or {}).get("screenshots") or {}
        minimum = int(shots_spec.get("min") or 3)
        retries = int(cap.get("retries") or 0)
        trailer_spec = (reference.get("renditions") or {}).get("trailer") or {}
        design = self._ctx["inputs"].load("game-design")
        viewports = self._viewports(design, reference)
        play_ms = 20000
        chosen, dropped, report = [], [], None
        attempts = 0
        server = self._ctx["server"]
        for attempt in range(1, retries + 2):
            attempts = attempt
            out = os.path.join(self._ctx["scratch"], "capture", str(attempt))
            job = {
                "base_url": server.url, "out": out, "viewports": viewports,
                "scenes": cap.get("scenes") or [],
                "settings": {"play_ms": play_ms, "excluded_states": cap.get("excluded_states") or []},
                "trailer": ({"enabled": True, "seconds": int((cap.get("trailer") or {}).get("seconds") or 20),
                             "width": int(trailer_spec.get("width") or 1280),
                             "height": int(trailer_spec.get("height") or 720)}
                            if self.settings.trailer and attempt == 1 else {"enabled": False}),
                "branding": None, "derive": [],
            }
            context.logger.info("store listing capture", attempt=attempt, play_ms=play_ms,
                                viewports=[v["id"] for v in viewports])
            try:
                result = self._run_capture(context, job, f"capture-{attempt}.log")
            except capture.CaptureFailure as exc:
                if exc.kind == "blocked":
                    raise _Stop("BLOCKED", str(exc))
                raise _Stop("FAILED", str(exc), retryable=True)
            if report is None or result.get("trailer"):
                report = result if report is None else {**report, **{k: v for k, v in result.items()
                                                                       if k != "trailer"}}
                if result.get("trailer"):
                    report["trailer"] = result["trailer"]
            shots = []
            for viewport in result.get("viewports") or []:
                for shot in viewport.get("shots") or []:
                    shots.append({**shot, "viewport": viewport["id"]})
            chosen, dropped = pkg.select_screenshots(shots, reference)
            if not any(v.get("ran") for v in result.get("viewports") or []):
                raise _Stop("BLOCKED", "the build answered no play probe on any viewport "
                                       "(window.__wgf__.play.snapshot()): it cannot be played from "
                                       "outside, so nothing can be captured. See "
                                       + os.path.join(out, "capture.json"))
            if len(chosen) >= minimum:
                break
            context.logger.warning("too few usable screenshots", usable=len(chosen), minimum=minimum,
                                   dropped=[d["reason"] for d in dropped][:6])
            play_ms = int(play_ms * 1.5)
        self._ctx["capture_report"] = report
        self._ctx["capture_attempts"] = attempts
        screenshots = []
        shots_dir = os.path.join(package_dir, "screenshots")
        os.makedirs(shots_dir, exist_ok=True)
        per_viewport = {}
        for entry in chosen:
            per_viewport[entry["viewport"]] = per_viewport.get(entry["viewport"], 0) + 1
            name = f"{entry['viewport']}-{per_viewport[entry['viewport']]:02d}-{entry['scene']}.png"
            target = os.path.join(shots_dir, name)
            shutil.copyfile(entry["file"], target)
            record = pkg.file_record(name[:-4], target, self._ctx["context"].run_dir, kind="screenshot")
            record.update(scene=entry["scene"], viewport=entry["viewport"], state=entry["state"],
                          attempt=attempts, stats=entry["stats"])
            screenshots.append(record)
        if len(screenshots) < minimum:
            self._problem("screenshots-insufficient",
                          f"only {len(screenshots)} usable screenshot(s) after {attempts} capture "
                          f"attempt(s); the package requires {minimum}. Dropped: "
                          + "; ".join(d["reason"] for d in dropped[:6]), subject="screenshots")
        viewports_record = []
        for viewport in (report or {}).get("viewports") or []:
            viewports_record.append({"id": viewport["id"], "width": viewport["width"],
                                     "height": viewport["height"], "mobile": bool(viewport.get("mobile")),
                                     "ran": bool(viewport.get("ran")),
                                     "page_errors": list(viewport.get("errors") or [])[:10]})
        capture_record = {
            "kind": "browser", "attempts": attempts, "browser": (report or {}).get("browser"),
            "network_guard": (report or {}).get("network_guard") or "none",
            "viewports": viewports_record,
            "records_dir": pkg.relative_to(os.path.join(self._ctx["scratch"], "capture"),
                                           self._ctx["context"].run_dir),
            "blocked_reason": None,
        }
        # Branding and derivation run while the server is still up.
        self._ctx["capture_record"] = capture_record
        return screenshots, capture_record

    def _trailer(self, capture_record, screenshots, package_dir):
        report = (self._ctx.get("capture_report") or {}).get("trailer") or {}
        run_dir = self._ctx["context"].run_dir
        trailer_dir = os.path.join(package_dir, "trailer")
        os.makedirs(trailer_dir, exist_ok=True)
        if report.get("file") and os.path.isfile(report["file"]):
            info = media.describe(report["file"])
            container = info["format"] if info["format"] in media.VIDEO_FORMATS else "webm"
            target = os.path.join(trailer_dir, f"trailer.{container}")
            shutil.copyfile(report["file"], target)
            info = media.describe(target)
            entry = {
                "status": "recorded", "reason": None, "path": pkg.relative_to(target, run_dir),
                "sha256": media.sha256_of(target), "bytes": info["bytes"], "container": container,
                "codec": info.get("codec"), "width": info.get("width") or int(report.get("width") or 0) or 1,
                "height": info.get("height") or int(report.get("height") or 0) or 1,
                "duration_s": info.get("duration_s") if info.get("duration_s") is not None else
                round((report.get("played_ms") or 0) / 1000, 3),
                "trimmed": bool(report.get("trimmed")),
                "leading_ms": 0 if report.get("trimmed") else int(report.get("leading_ms") or 0),
                "derived": [],
            }
            for derived in report.get("derived") or []:
                if derived.get("file") and os.path.isfile(derived["file"]):
                    out = os.path.join(trailer_dir, f"trailer.{derived['format']}")
                    shutil.copyfile(derived["file"], out)
                    entry["derived"].append(pkg.file_record(f"trailer-{derived['format']}", out, run_dir,
                                                            kind="trailer", source="trailer"))
            for error in report.get("errors") or []:
                self._problem("trailer-note", error, severity="info", subject="trailer")
            if not entry["trimmed"]:
                self._problem("trailer-untrimmed", "the recording could not be cut to play: it keeps "
                                                   f"{entry['leading_ms']} ms of loading and title screen",
                              severity="warning", subject="trailer")
            return entry
        # Fallback: a deterministic frame sequence from the screenshots, labelled as such.
        reason = "; ".join(report.get("errors") or []) or (
            "no recording was made" if self.settings.trailer else "trailer capture is off")
        frames_dir = os.path.join(trailer_dir, "frames")
        os.makedirs(frames_dir, exist_ok=True)
        frames, storyboard = [], []
        for index, shot in enumerate([s for s in screenshots if s["scene"] != "title"] or screenshots, 1):
            source = os.path.join(run_dir, *shot["path"].split("/"))
            target = os.path.join(frames_dir, f"{index:02d}.png")
            shutil.copyfile(source, target)
            frames.append(pkg.file_record(f"frame-{index:02d}", target, run_dir, kind="frame",
                                          source=shot["id"]))
            storyboard.append({"frame": f"frames/{index:02d}.png", "at_ms": (index - 1) * 2000,
                               "hold_ms": 2000, "scene": shot["scene"]})
        board = os.path.join(trailer_dir, "storyboard.json")
        pkg.write_json(board, {"format": "wgf-storyboard", "version": 1, "frames": storyboard,
                               "reason": reason})
        self._problem("trailer-fallback", f"no gameplay recording: {reason}. A frame sequence stands in "
                                          "(trailer/storyboard.json); it is not a video", severity="warning",
                      subject="trailer")
        return {"status": "fallback", "reason": reason, "storyboard": pkg.relative_to(board, run_dir),
                "frames": frames}

    def _branding(self, context, reference, facts, design, runtime_assets, screenshots, package_dir):
        renditions = reference.get("renditions") or {}
        branding_dir = os.path.join(package_dir, "branding")
        os.makedirs(branding_dir, exist_ok=True)
        run_dir = context.run_dir
        identity = (design.get("build_spec") or {}).get("visual_identity") or {}
        hero_id, hero_url = hero_asset(runtime_assets)
        plays = [s for s in screenshots if s["scene"] != "title"] or screenshots
        frame = plays[0] if plays else None
        brand_dir = os.path.join(self._ctx["scratch"], "brand")
        os.makedirs(brand_dir, exist_ok=True)
        frame_url = None
        if frame is not None:
            shutil.copyfile(os.path.join(run_dir, *frame["path"].split("/")), os.path.join(brand_dir, "hero.png"))
            frame_url = capture.EXTRA_PREFIX + "hero.png"
        page = brand.brand_page(title=facts["title"], identity=identity, renditions=renditions,
                                hero_url=f"/assets/{hero_url}" if hero_url else None, frame_url=frame_url,
                                fonts=font_assets(runtime_assets))
        with open(os.path.join(brand_dir, "brand.html"), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(page)
        shots = brand.brand_shots(renditions)
        page_height = sum(s["height"] + 20 for s in shots)
        items, method = [], "none"
        server = self._ctx.get("server")
        if server is not None and shots:
            job = {"base_url": server.url, "out": os.path.join(self._ctx["scratch"], "capture", "brand"),
                   "viewports": [], "scenes": [], "trailer": {"enabled": False}, "derive": [],
                   "branding": {"url": server.url + capture.EXTRA_PREFIX + "brand.html", "shots": shots,
                                "page_width": 1920, "page_height": max(page_height, 100)}}
            try:
                result = self._run_capture(context, job, "capture-brand.log")
            except capture.CaptureFailure as exc:
                result = {"branding": [], "errors": [str(exc)]}
            for made in result.get("branding") or []:
                target = os.path.join(branding_dir, f"{made['id']}.png")
                shutil.copyfile(made["file"], target)
                items.append(pkg.file_record(made["id"], target, run_dir, kind=_family_kind(made.get("source")),
                                             source=hero_id if made.get("source") == "icon" and hero_id
                                             else (frame["id"] if frame and made.get("source") in
                                                   ("thumbnail", "promo") else "visual-identity")))
            if items:
                method = "browser-composed"
            for error in result.get("errors") or []:
                self._problem("branding-note", error, severity="warning", subject="branding")
        if not items and frame is not None:
            colours = brand.palette_roles(identity)
            for rid, family, path, _w, _h in brand.derive_from_frame(
                    os.path.join(run_dir, *frame["path"].split("/")), renditions, branding_dir, colours["ground"]):
                items.append(pkg.file_record(rid, path, run_dir, kind=_family_kind(family), source=frame["id"]))
            method = "frame-derived" if items else "none"
            self._problem("branding-frame-derived", "the browser could not compose the branding; the "
                                                    "icon, thumbnails and promo are crops of the best "
                                                    "play frame and there is no wordmark",
                          severity="warning", subject="branding")
        # The smaller icons from the 1024 master, whichever way the master was made.
        master = next((i for i in items if i["id"] == "icon-1024"), None)
        if master is not None:
            have_ids = {i["id"] for i in items}
            missing_icons = {"icon": [e for e in renditions.get("icon") or [] if e["id"] not in have_ids]}
            for rid, path, _w, _h in pkg.canonical_icons(os.path.join(run_dir, *master["path"].split("/")),
                                                         missing_icons, branding_dir):
                items.append(pkg.file_record(rid, path, run_dir, kind="icon", source="icon-1024"))
        expected = [e["id"] for family in ("icon", "logo", "thumbnail", "promo")
                    for e in renditions.get(family) or []]
        have = {i["id"] for i in items}
        for rid in expected:
            if rid not in have:
                self._problem("branding-missing", f"canonical rendition {rid} could not be made",
                              severity="error" if not rid.startswith("logo") else "warning", subject=rid)
        return {"method": method, "source_asset": hero_id, "items": items}

    def _ground_in_build(self, facts, design, loaded, reference, commit, context):
        """The run's tier and its store bars, and the counts the build measured: the
        content-sufficiency report of this build only (the listed commit, or the development
        commit it sits on)."""
        tier, where = buildfacts.resolve_tier(self.params, getattr(context, "environment", None),
                                              design, loaded.get("title-strategy"))
        facts["quality"] = {"tier": tier, "where": where, "bars": buildfacts.store_bars(tier)}
        facts["sources"]["quality"] = where
        report = loaded.get("content-sufficiency-report")
        measured = buildfacts.measured_counts(report, design, reference,
                                              commits=[commit, developed_commit(loaded)])
        if measured is not None:
            facts["measured"] = measured
            facts["sources"]["measured"] = (f"content-sufficiency-report "
                                            f"{measured['source'].get('artifact_id')} "
                                            f"({measured['source']['commit'][:12]})")
        elif report is not None:
            context.logger.info("content-sufficiency-report not of this build",
                                report_commit=str(report.get("commit") or "")[:12],
                                listed=commit[:12])

    def _copy_findings(self, inputs, context):
        """The store-copy findings the triage that routed this visit selected (route
        `listing`), for the copywriter's brief; [] on a first pass."""
        if "triage-report" not in inputs or not str(getattr(context, "entered_by", "") or "").endswith(
                ".listing"):
            return []
        report = inputs.load("triage-report") or {}
        selected = report.get("selected") or {}
        if selected.get("route") != "listing":
            return []
        wanted = set(selected.get("findings") or [])
        return [f for f in report.get("findings") or []
                if isinstance(f, dict) and f.get("id") in wanted and f.get("dimension") == COPY_DIMENSION]

    @staticmethod
    def _copywriter():
        """The copywriter's role data (core/roles/roles.yaml through the routing data), or
        None when the routing data cannot be read."""
        try:
            from wgf_triage.routing import Routing
            routing = Routing.load()
            return routing.specialist(routing.owner(COPY_DIMENSION))
        except Exception:  # noqa: BLE001 - the brief is written without the role's words
            return None

    def _report_of_this_build(self, report, root, head_sha, context):
        """The prototype-report when its commit is the listed one or an ancestor of it (the
        sdk step commits after develop), else None: scope deltas of another line of work
        say nothing about this build."""
        commit = ((report or {}).get("build_ref") or {}).get("commit_sha") or ""
        if not commit:
            return None
        if same_commit(commit, head_sha):
            return report
        ancestor = procs.run(["git", "merge-base", "--is-ancestor", commit, head_sha], cwd=root, timeout=30)
        if ancestor.ok:
            return report
        context.logger.info("prototype-report not of this build", report_commit=commit[:12],
                            listed=head_sha[:12])
        return None

    def _supplied(self, locales):
        """{locale: localeCopy} a person wrote under factory.listing.copy_dir, and
        {locale: path}. A file that is not a localeCopy is a problem, never used."""
        directory = self.settings.copy_dir_for(self._ctx.get("title_id"))
        copies, where = {}, {}
        if not directory or not os.path.isdir(directory):
            return copies, where
        for locale in locales:
            path = os.path.join(directory, f"{locale}.json")
            if not os.path.isfile(path):
                continue
            try:
                with open(path, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError) as exc:
                self._problem("copy-supplied-invalid", f"{path}: not readable JSON ({exc})", subject=locale)
                continue
            shape = _supplied_shape(data)
            if shape:
                self._problem("copy-supplied-invalid", f"{path}: {shape}", subject=locale)
                continue
            copies[locale] = data
            where[locale] = path
        return copies, where

    def _copy(self, context, facts, locales, reference, scratch):
        supplied, where = self._supplied(locales)
        self._ctx["supplied"] = where
        findings = self._copy_findings(self._ctx["inputs"], context)
        if findings:
            context.logger.info("copywriter briefed with findings", findings=[f["id"] for f in findings][:10])
        copies, writer = write_copy(facts, [l for l in locales if l not in supplied], reference,
                                    writer_settings=self.settings.writer, workdir=scratch,
                                    logger=context.logger, findings=findings, role=self._copywriter(),
                                    tier=(facts.get("quality") or {}).get("tier"))
        copies = {locale: supplied[locale] if locale in supplied else copies.get(locale) for locale in locales}
        if supplied:
            context.logger.info("store copy supplied by a person", locales=sorted(supplied))
        grounded_problems = []
        for locale, text in copies.items():
            if text is None:
                self._problem("locale-missing", f"no store copy could be written in `{locale}`: configure "
                                                "an agent writer (factory.listing.writer) or ship the "
                                                "game's strings in that locale", subject=locale)
                continue
            for problem in grounding.check(text, facts, reference.get("claims") or [], locale=locale,
                                           counts=reference.get("counts")):
                grounded_problems.append(problem)
                if problem["severity"] == "error":
                    self._problem(problem["code"], problem["message"], subject=problem.get("subject"))
        self._ctx["grounding"] = {"checked": True, "claims_version": str(reference.get("version")),
                                  "problems": grounded_problems}
        return copies, writer

    def _platforms(self, targets, profiles, reference, screenshots, branding, trailer, copies,
                   package_dir, context):
        run_dir = context.run_dir
        masters = [{"id": i["id"], "family": _kind_family(i.get("kind")), "path": os.path.join(run_dir, *i["path"].split("/")),
                    "width": i.get("width") or 1, "height": i.get("height") or 1} for i in branding["items"]]
        canonical = {"masters": masters,
                     "screenshots": [{"id": s["id"], "path": os.path.join(run_dir, *s["path"].split("/")),
                                      "viewport": s["viewport"], "width": s.get("width"), "height": s.get("height")}
                                     for s in screenshots],
                     "trailer": {**trailer, "path": os.path.join(run_dir, *trailer["path"].split("/"))
                                 if trailer.get("path") else None,
                                 "derived": [{**d, "path": os.path.join(run_dir, *d["path"].split("/"))}
                                             for d in trailer.get("derived") or []]}}
        browser_formats = tuple((reference.get("formats") or {}).get("browser") or ()) \
            if self.settings.capture_kind == "browser" and self._ctx.get("server") is not None else ()
        renditions, derive = [], []
        age_rating = (self.params or {}).get("age_rating", ((context.config or {}).get("listing") or {}).get("age_rating"))
        for pid, role, version in targets:
            profile = profiles.get(pid)
            platform = {"platform_id": pid, "role": role, "profile_version": version or
                        str((profile or {}).get("version") or "unknown"),
                        "spec_status": platforms.spec_status(profile)}
            requirements = platforms.requirements(profile, reference)
            entry, jobs = pkg.render_platform(platform, requirements, canonical=canonical, copies=copies,
                                              out_dir=os.path.join(package_dir, "platforms", pid), run_dir=run_dir,
                                              reference=reference, browser_formats=browser_formats,
                                              age_rating=age_rating)
            entry["spec_hash"] = platforms.block_hash(profile)
            renditions.append(entry)
            derive.extend(jobs)
            for problem in entry["unmet"]:
                if problem["severity"] == "error":
                    self._problem(problem["code"], f"{pid}: {problem['message']}", subject=pid)
        return renditions, derive

    def _derive(self, context, derive, renditions, capture_record):
        if not derive:
            return
        server = self._ctx.get("server")
        job = {"base_url": server.url if server else None, "out": os.path.join(self._ctx["scratch"], "capture", "derive"),
               "viewports": [], "scenes": [], "trailer": {"enabled": False}, "branding": None,
               "derive": [{k: v for k, v in d.items() if k != "record"} for d in derive]}
        try:
            result = self._run_capture(context, job, "capture-derive.log")
        except capture.CaptureFailure as exc:
            result = {"derived": [], "errors": [str(exc)]}
        made = {d["id"]: d for d in result.get("derived") or []}
        by_platform = {r["platform_id"]: r for r in renditions}
        for d in derive:
            pid = d["id"].split(":", 1)[0]
            entry = by_platform.get(pid)
            if d["id"] in made and os.path.isfile(d["out"]) and entry is not None:
                record = pkg.file_record(d["record"]["id"], d["out"], context.run_dir, kind=d["record"]["kind"],
                                         source=d["record"]["source"], requirement=d["record"]["requirement"])
                entry["files"].append(record)
            elif entry is not None:
                entry["unmet"].append({"code": "format-unavailable", "severity": "error",
                                       "message": f"{d['record']['id']}.{d['format']} could not be encoded",
                                       "subject": d["record"]["id"]})
                self._problem("format-unavailable", f"{pid}: {d['record']['id']}.{d['format']} could not be "
                                                    "encoded by the browser", subject=pid)
        for error in result.get("errors") or []:
            self._problem("derive-note", error, severity="warning", subject="derive")

    # -- the artifact -----------------------------------------------------------------------

    def _blocked(self, reason):
        self._ctx["problems"].append({"code": "blocked", "severity": "error", "message": reason,
                                      "subject": None})
        return self._finish("BLOCKED", reason)

    def _finish(self, outcome, message, retryable=False, screenshots=(), trailer=None, branding=None,
                copies=None, writer=None, renditions=(), capture=None, facts=None):
        ctx = self._ctx
        context, inputs = ctx["context"], ctx["inputs"]
        now = self.clock()
        problems = list(ctx["problems"])
        errors = [p for p in problems if p["severity"] == "error"]
        if outcome == "BLOCKED":
            status = "blocked"
        elif errors or any(c is None for c in (copies or {}).values()) or not screenshots:
            status = "incomplete"
        else:
            status = "complete"
        package_dir = ctx.get("package_dir")
        locales = {locale: text for locale, text in (copies or {}).items() if text is not None}
        listing = {
            "provenance": provenance.build(
                "store-listing",
                artifact_id=provenance.artifact_id("store-listing", ctx["title_id"], now,
                                                   getattr(context, "execution", 1)),
                produced_by=provenance.producer(ROLE, "ai" if (writer or {}).get("kind") == "command"
                                                and not (writer or {}).get("fallback") else "automation"),
                produced_at=now,
                inputs=provenance.pin_inputs(inputs, REQUIRED_INPUTS + OPTIONAL_INPUTS),
                title_id=ctx["title_id"]),
            "title_id": ctx["title_id"],
            "commit": ctx["commit"] if len(ctx["commit"]) == 40 else "0" * 40,
            "measurement_class": "automation-bot",
            "status": status,
            "package_dir": pkg.relative_to(package_dir, context.run_dir) if package_dir else "",
            "facts": facts or ctx.get("facts") or {"title": ctx["title_id"], "sources": {}},
            "copy": {"locales": locales, "writer": writer or {"kind": "command" if self.settings.writer_kind == "command"
                                                  else "template"},
                     "grounding": ctx.get("grounding") or {"checked": False, "problems": []},
                     **({"supplied": {loc: os.path.abspath(p).replace(os.sep, "/")
                                      for loc, p in ctx["supplied"].items() if loc in locales}}
                        if ctx.get("supplied") else {})},
            "branding": branding or {"method": "none", "items": []},
            "screenshots": list(screenshots),
            "trailer": trailer or {"status": "none", "reason": message},
            "platforms": list(renditions),
            "capture": capture or {"kind": self.settings.capture_kind if hasattr(self, "settings") else "none",
                                   "attempts": 0, "blocked_reason": message if outcome == "BLOCKED" else None},
            "problems": problems,
        }
        if ctx.get("build"):
            listing["build"] = {**ctx["build"], "served_at": getattr(ctx.get("server"), "url", None)}
            if listing["build"]["served_at"] is None:
                del listing["build"]["served_at"]
        workflow = {k: v for k, v in {
            "run_id": getattr(context, "run_id", None), "workflow_id": getattr(context, "workflow_id", None),
            "step_id": getattr(context, "current_step", None), "visit": getattr(context, "visit", None),
            "execution": getattr(context, "execution", None),
            "idempotency_key": getattr(context, "idempotency_key", None)}.items() if v is not None}
        if workflow.get("run_id"):
            listing["workflow"] = workflow
        provenance.seal(listing)
        if package_dir:
            pkg.write_json(os.path.join(package_dir, "listing.json"), listing)
            for rendition in renditions:
                pkg.write_json(os.path.join(context.run_dir, *rendition["listing"].split("/")),
                               {k: v for k, v in rendition.items() if k != "listing"})
        output = ArtifactOutput("store-listing", listing, metadata={
            "status": status, "commit": listing["commit"], "screenshots": len(screenshots),
            "trailer": listing["trailer"]["status"], "branding": listing["branding"]["method"],
            "platforms": [r["platform_id"] for r in renditions], "problems": len(errors),
            "package_dir": listing["package_dir"]})
        if outcome == "BLOCKED":
            context.logger.warning("store listing blocked", reason=message)
            return StepResult("BLOCKED", artifacts=[output], message=message)
        if outcome == "FAILED":
            context.logger.error("store listing failed", error=message)
            return StepResult("FAILED", artifacts=[output], retryable=retryable, error=message)
        summary = (f"store listing {status} for {ctx['commit'][:12]}: {len(screenshots)} screenshot(s), "
                   f"trailer {listing['trailer']['status']}, branding {listing['branding']['method']}, "
                   f"copy in {', '.join(sorted(locales)) or 'no locale'}, "
                   f"{len(renditions)} platform rendition(s)"
                   + (f"; {len(errors)} problem(s): " + "; ".join(p["message"][:90] for p in errors[:4])
                      if errors else "")
                   + f"; package at {listing['package_dir']}")
        if status != "complete":
            context.logger.warning("store listing incomplete", problems=[p["code"] for p in errors][:10])
        return StepResult.success([output], message=summary)


_COPY_TEXT = ("title", "short_description", "long_description")
_COPY_KEYS = {"title", "subtitle", "subtitle_variants", "short_description", "long_description", "features",
              "controls", "tags", "categories", "promo", "age_rating"}


def _supplied_shape(data):
    """What makes a person's copy file not a localeCopy, or None."""
    if not isinstance(data, dict):
        return "not a JSON object"
    unknown = sorted(set(data) - _COPY_KEYS)
    if unknown:
        return f"unknown field(s) {', '.join(unknown)}"
    for field in _COPY_TEXT:
        if not isinstance(data.get(field), str) or not data[field].strip():
            return f"`{field}` must be a non-empty string"
    features = data.get("features")
    if not isinstance(features, list) or not all(
            isinstance(f, dict) and set(f) == {"text", "source"}
            and isinstance(f["text"], str) and isinstance(f["source"], str) for f in features):
        return "`features` must be a list of {text, source}"
    for field in ("subtitle_variants", "tags", "categories", "promo"):
        if field in data and not (isinstance(data[field], list) and all(isinstance(v, str) for v in data[field])):
            return f"`{field}` must be a list of strings"
    if "tags" not in data:
        return "`tags` is required"
    for field in ("subtitle", "controls"):
        if field in data and not isinstance(data[field], str):
            return f"`{field}` must be a string"
    if "age_rating" in data and not (data["age_rating"] is None or isinstance(data["age_rating"], str)):
        return "`age_rating` must be a string or null"
    return None


def _family_kind(family):
    return {"icon": "icon", "logo": "logo", "thumbnail": "thumbnail", "promo": "promo"}.get(family, "thumbnail")


def _kind_family(kind):
    return {"icon": "icon", "logo": "logo", "thumbnail": "thumbnail", "promo": "promo"}.get(kind, "thumbnail")
