"""The `listing-validation` step: may this store listing go to the portals?

    inputs    store-listing (required); game-design, sdk-report, scaffold-record (read when
              present: the facts the copy is re-grounded against, the platforms)
    output    listing-validation-report, on every outcome that judged or could not
    effect    none outside the run directory (the report is also written into the package
              as validation.json)

    PASS      no required check failed                                        SUCCESS
    FAIL      a required check failed that the store-listing step can act on (capture
              again, render again, rewrite): FAILED, route `listing`, not retryable
    BLOCKED   a required check failed that only a person can act on (a locale no writer
              produces, an age rating nobody stated, a format no encoder here writes, a
              profile asking for more than any master), or there is no listing to judge.
              The report says exactly what, per platform
    A requirement a profile leaves null is UNKNOWN: listed, never passed.

The copy is judged against the build (buildfacts.py) at the run's tier (the listing's
`facts.quality`, core/reference/quality-benchmark.yaml `store_listing`):

    grounding.counts.<locale>         every count is the build's measured one
                                      (copy_counts_match_build: an unmeasured count fails)
    metadata.<locale>.controls        the controls text names every input the build accepts
                                      (controls_cover_all_inputs; a locale with no device
                                      words in store-listing.yaml is UNKNOWN)
    metadata.<locale>.full_description  every required locale is a full description
                                      (full_description_per_required_locale)
    metadata.<locale>.subtitle        the subtitle names the game, not only its genre
    metadata.writer                   at the release tier the copywriter agent wrote it
                                      (store-listing.yaml `writer`)
A bar the tier does not state makes its check a warning. Failures are store copy: triage
routes them to the copywriter (core/reference/specialist-routing.yaml).

`validate(listing, run_dir, reference, profiles, facts)` is the pure judge, shared with
scripts/wgf-listing.py.
"""

import datetime
import hashlib
import os
import re

from wgflib import provenance
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep
from wgflib.yamllite import YamlError, load_file

from . import buildfacts, grounding, imaging, media, platforms
from .settings import Settings, SettingsError

__all__ = ["ListingValidationStep", "validate", "FAIL_ROUTE", "REQUIRED_INPUTS", "OPTIONAL_INPUTS"]

REQUIRED_INPUTS = ("store-listing",)
OPTIONAL_INPUTS = ("game-design", "sdk-report", "scaffold-record")
FAIL_ROUTE = "listing"
ROLE = "release"
SECTIONS = ("assets", "metadata", "screenshots", "video", "grounding", "platforms")
# What the store-listing step can do about a failure on its next pass; `configure` and
# `none` need a person.
ACTIONABLE = ("recapture", "rerender", "rewrite")


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Checks:
    def __init__(self):
        self.items = []

    def add(self, check_id, section, ok, summary, *, required=True, measured=None, expected=None,
            platform_id=None, locale=None, files=None, fix="none", unknown=False, warning=False):
        status = "UNKNOWN" if unknown else ("PASS" if ok else ("WARNING" if warning or not required else "FAIL"))
        entry = {"id": check_id, "section": section, "status": status, "required": bool(required),
                 "summary": summary, "fix": fix}
        if platform_id is not None:
            entry["platform_id"] = platform_id
        if locale is not None:
            entry["locale"] = locale
        if measured is not None:
            entry["measured"] = measured
        if expected is not None:
            entry["expected"] = expected
        if files:
            entry["files"] = list(files)
        self.items.append(entry)
        return entry


def _file_ok(record, run_dir):
    """(exists, sha matches, described) for a listing file record."""
    path = os.path.join(run_dir, *str(record.get("path") or "").split("/"))
    if not os.path.isfile(path):
        return False, False, None
    info = media.describe(path)
    return True, media.sha256_of(path) == record.get("sha256"), info


def _aspect_ok(width, height, aspect):
    if not aspect:
        return True
    try:
        a, b = (int(x) for x in str(aspect).split(":"))
    except ValueError:
        return True
    return abs(width / height - a / b) < 0.02


def _video_problems(made, req, run_dir, trailer):
    """What keeps an included video from meeting the platform's own stated bounds - its
    length, file size, resolution and aspect. A bound the profile leaves null is not checked.
    The recording is the run's canonical trailer, so a miss is a capture setting a person
    configures, never something re-rendering would fix."""
    problems = []
    for f in made:
        exists, intact, info = _file_ok(f, run_dir)
        if not exists or not intact:
            problems.append(f"{f['id']} missing or changed")
            continue
        duration = info.get("duration_s") if info.get("duration_s") is not None else trailer.get("duration_s")
        if req.get("max_seconds") is not None and duration is not None and duration > req["max_seconds"]:
            problems.append(f"{f['id']} runs {duration} s > {req['max_seconds']} s")
        if req.get("min_seconds") is not None and duration is not None and duration < req["min_seconds"]:
            problems.append(f"{f['id']} runs {duration} s < {req['min_seconds']} s")
        if (req.get("max_seconds") is not None or req.get("min_seconds") is not None) and duration is None:
            problems.append(f"{f['id']} has no measurable length")
        if req.get("max_mb") is not None and info["bytes"] > req["max_mb"] * 1024 * 1024:
            problems.append(f"{f['id']} is {round(info['bytes'] / 1024 / 1024, 2)} MB > {req['max_mb']} MB")
        width, height = info.get("width"), info.get("height")
        if (req.get("min_width") or req.get("min_height") or req.get("aspect")) and not (width and height):
            problems.append(f"{f['id']} has no measurable resolution")
            continue
        if req.get("min_width") is not None and width < req["min_width"]:
            problems.append(f"{f['id']} is {width} px wide < {req['min_width']}")
        if req.get("min_height") is not None and height < req["min_height"]:
            problems.append(f"{f['id']} is {height} px high < {req['min_height']}")
        if req.get("aspect") and not _aspect_ok(width, height, req["aspect"]):
            problems.append(f"{f['id']} is not {req['aspect']}")
    return problems


def validate(listing, run_dir, reference, profiles, facts=None):
    """The checks over one store-listing. Returns (checks, platform_requirements)."""
    checks = _Checks()
    renditions = reference.get("renditions") or {}
    copy_bounds = reference.get("copy") or {}
    cap = reference.get("capture") or {}
    facts = facts or listing.get("facts") or {}

    # -- assets: the canonical branding --------------------------------------------------
    items = {i["id"]: i for i in (listing.get("branding") or {}).get("items") or []}
    for family in ("icon", "thumbnail", "promo", "logo"):
        for spec in renditions.get(family) or []:
            rid = spec["id"]
            record = items.get(rid)
            required = family != "logo"
            if record is None:
                checks.add(f"assets.{rid}", "assets", False, f"canonical {family} {rid} is missing",
                           required=required, fix="rerender", files=[rid])
                continue
            exists, intact, info = _file_ok(record, run_dir)
            if not exists or not intact:
                checks.add(f"assets.{rid}", "assets", False,
                           f"{rid}: file {'missing' if not exists else 'changed since the listing was written'}",
                           required=required, fix="rerender", files=[rid])
                continue
            size_ok = (info["width"], info["height"]) == (int(spec["width"]), int(spec["height"]))
            checks.add(f"assets.{rid}", "assets", size_ok and info["format"] in media.IMAGE_FORMATS,
                       f"{rid}: {info['format']} {info['width']}x{info['height']}"
                       + ("" if size_ok else f", expected {spec['width']}x{spec['height']}"),
                       required=required, measured={"width": info["width"], "height": info["height"],
                                                    "format": info["format"], "bytes": info["bytes"]},
                       expected={"width": spec["width"], "height": spec["height"]}, fix="rerender",
                       files=[rid])
    method = (listing.get("branding") or {}).get("method")
    checks.add("assets.method", "assets", method == "browser-composed",
               f"branding is {method}" + ("" if method == "browser-composed" else
                                          ": derived from a frame, no wordmark" if method == "frame-derived"
                                          else ": nothing was made"),
               required=method == "none", warning=method == "frame-derived", fix="recapture")

    # -- metadata: the canonical copy ---------------------------------------------------
    locales = (listing.get("copy") or {}).get("locales") or {}
    # A locale a person wrote (copy.supplied) is fixed by that person, not by another pass.
    supplied = (listing.get("copy") or {}).get("supplied") or {}
    if not locales:
        checks.add("metadata.locales", "metadata", False, "the listing carries no copy in any locale",
                   fix="rewrite")
    for locale, text in sorted(locales.items()):
        fix = "configure" if locale in supplied else "rewrite"
        for field in ("title", "short_description", "long_description"):
            value = text.get(field) or ""
            bounds = copy_bounds.get(field) or {}
            maximum, minimum = bounds.get("max_chars"), bounds.get("min_chars")
            present = bool(value.strip())
            over = maximum is not None and len(value) > maximum
            under = minimum is not None and len(value) < minimum
            # A text that is too long or missing fails everywhere; one shorter than the
            # canonical minimum fails in English and is a warning in a locale written from the
            # game's own strings, which say what they say.
            checks.add(f"metadata.{locale}.{field}", "metadata", present and not over and not under,
                       f"{field} ({locale}): {len(value)} chars"
                       + ("" if present and not over and not under else
                          (" (empty)" if not present else f", bounds {minimum}-{maximum}")),
                       locale=locale, measured=len(value), expected={"min_chars": minimum, "max_chars": maximum},
                       required=(not present) or over or locale == "en", fix=fix)
        features = text.get("features") or []
        fb = copy_bounds.get("features") or {}
        ok = (fb.get("min") is None or len(features) >= fb["min"]) and (fb.get("max") is None or len(features) <= fb["max"]) \
            and all(len(f.get("text") or "") <= (fb.get("max_chars") or 10**6) for f in features)
        checks.add(f"metadata.{locale}.features", "metadata", ok,
                   f"{len(features)} feature bullet(s) ({locale})", locale=locale, measured=len(features),
                   expected={"min": fb.get("min"), "max": fb.get("max"), "max_chars": fb.get("max_chars")},
                   required=locale == "en", fix=fix)
        tags = text.get("tags") or []
        tb = copy_bounds.get("tags") or {}
        ok = (tb.get("min") is None or len(tags) >= tb["min"]) and (tb.get("max") is None or len(tags) <= tb["max"])
        checks.add(f"metadata.{locale}.tags", "metadata", ok, f"{len(tags)} tag(s) ({locale})",
                   locale=locale, measured=len(tags), expected={"min": tb.get("min"), "max": tb.get("max")},
                   fix=fix)
        if copy_bounds.get("first_sentence_names_the_verb"):
            first = re.split(r"(?<=[.!?])\s+", (text.get("short_description") or "").strip())[0]
            starts_with_filler = bool(re.match(r"^(a|an|the|this|welcome|experience|enjoy)\b", first, re.I))
            checks.add(f"metadata.{locale}.first_sentence", "metadata", not starts_with_filler,
                       f"the short description opens with {first[:60]!r}"
                       + ("" if not starts_with_filler else ": it should name what the player does"),
                       locale=locale, required=False, fix=fix)

    # -- screenshots ------------------------------------------------------------------------
    shots = listing.get("screenshots") or []
    shots_spec = renditions.get("screenshots") or {}
    minimum, maximum = int(shots_spec.get("min") or 0), shots_spec.get("max")
    checks.add("screenshots.count", "screenshots", len(shots) >= minimum and (maximum is None or len(shots) <= maximum),
               f"{len(shots)} screenshot(s)", measured=len(shots), expected={"min": minimum, "max": maximum},
               fix="recapture")
    bars = cap.get("frame_bars") or {}
    distinct = cap.get("distinct") or {}
    excluded = set(cap.get("excluded_states") or ())
    seen_paths = []
    for shot in shots:
        sid = shot.get("id")
        exists, intact, info = _file_ok(shot, run_dir)
        if not exists or not intact:
            checks.add(f"screenshots.{sid}.file", "screenshots", False,
                       f"{sid}: file {'missing' if not exists else 'changed since capture'}", fix="recapture",
                       files=[sid])
            continue
        path = os.path.join(run_dir, *shot["path"].split("/"))
        state_ok = shot.get("state") not in excluded
        try:
            mean, contrast, lit = imaging.frame_stats(path, bars.get("lit_luminance", 64))
            readable = (lit >= bars.get("min_lit_share", 0.01) and mean <= bars.get("max_mean_luminance", 225)
                        and contrast >= bars.get("min_contrast", 18))
        except Exception:  # noqa: BLE001
            mean = contrast = lit = None
            readable = False
        same = None
        for earlier in seen_paths:
            if earlier[1] != shot.get("viewport"):
                continue
            try:
                if imaging.changed_fraction(earlier[0], path, distinct.get("min_pixel_delta", 24)) \
                        < distinct.get("min_changed_fraction", 0.05):
                    same = earlier[2]
                    break
            except Exception:  # noqa: BLE001
                pass
        seen_paths.append((path, shot.get("viewport"), sid))
        ok = state_ok and readable and same is None
        checks.add(f"screenshots.{sid}", "screenshots", ok,
                   f"{sid}: {shot.get('scene')} on {shot.get('viewport')}, state {shot.get('state')}, "
                   f"{info['width']}x{info['height']}"
                   + ("" if state_ok else " (an excluded state)") + ("" if readable else " (not readable)")
                   + ("" if same is None else f" (indistinct from {same})"),
                   measured={"mean_luminance": mean, "contrast": contrast, "lit_share": lit,
                             "width": info["width"], "height": info["height"]},
                   expected=bars, fix="recapture", files=[sid])

    # -- video ------------------------------------------------------------------------------
    trailer = listing.get("trailer") or {}
    tspec = renditions.get("trailer") or {}
    video_required_by = [p["platform_id"] for p in listing.get("platforms") or []
                         if any(r["kind"] == "video" and r.get("required") for r in
                                platforms.requirements(profiles.get(p["platform_id"]), reference))]
    if trailer.get("status") == "recorded":
        exists, intact, info = _file_ok(trailer, run_dir)
        if not exists or not intact:
            checks.add("video.file", "video", False, "the trailer file is missing or changed", fix="recapture")
        else:
            duration = info.get("duration_s") if info.get("duration_s") is not None else trailer.get("duration_s")
            in_bounds = duration is not None and (tspec.get("min_seconds") is None or duration >= tspec["min_seconds"]) \
                and (tspec.get("max_seconds") is None or duration <= tspec["max_seconds"])
            size_ok = tspec.get("max_mb") is None or info["bytes"] <= tspec["max_mb"] * 1024 * 1024
            checks.add("video.trailer", "video", in_bounds and size_ok and info["format"] in media.VIDEO_FORMATS,
                       f"{info['format']} {info.get('width')}x{info.get('height')}, {duration} s, "
                       f"{round(info['bytes'] / 1024 / 1024, 2)} MB" + ("" if trailer.get("trimmed") else
                                                                     f", untrimmed ({trailer.get('leading_ms')} ms lead)"),
                       measured={"duration_s": duration, "bytes": info["bytes"], "format": info["format"],
                                 "width": info.get("width"), "height": info.get("height")},
                       expected={"min_seconds": tspec.get("min_seconds"), "max_seconds": tspec.get("max_seconds"),
                                 "max_mb": tspec.get("max_mb"), "container": tspec.get("container")},
                       fix="recapture", files=["trailer"])
            checks.add("video.trimmed", "video", bool(trailer.get("trimmed")),
                       "the recording starts at play" if trailer.get("trimmed") else
                       f"the recording keeps {trailer.get('leading_ms')} ms before play", required=False,
                       fix="configure")
    elif trailer.get("status") == "fallback":
        checks.add("video.trailer", "video", False,
                   f"no video: a frame sequence stands in ({trailer.get('reason')})",
                   required=bool(video_required_by), fix="configure",
                   measured={"frames": len(trailer.get("frames") or [])},
                   expected={"required_by": video_required_by})
    else:
        checks.add("video.trailer", "video", False, "no trailer", required=bool(video_required_by),
                   fix="recapture", expected={"required_by": video_required_by})

    # -- the copy against the build ---------------------------------------------------------
    _build_checks(checks, listing, reference, profiles, facts, locales, supplied)

    # -- grounding: every text that reaches a platform --------------------------------------
    claims = reference.get("claims") or []
    counts = reference.get("counts")
    problems_total = 0
    for locale, text in sorted(locales.items()):
        found = grounding.check(text, facts, claims, locale=locale, counts=counts)
        problems = [p for p in found if p["severity"] == "error" and not p["code"].endswith("-count")
                    and p["code"] != "count-mismatch"]
        problems_total += len(problems)
        checks.add(f"grounding.{locale}", "grounding", not problems,
                   ("no unbacked claim" if not problems else "; ".join(p["message"][:120] for p in problems[:4]))
                   + (f" (supplied: {supplied[locale]})" if locale in supplied and problems else ""),
                   locale=locale, measured=len(problems), fix="configure" if locale in supplied else "rewrite")
        counted = [p for p in found if p["code"] in ("count-mismatch", "unmeasured-count")]
        if counted or ((facts.get("measured") or {}).get("counts")):
            failing = [p for p in counted if p["severity"] == "error"]
            checks.add(f"grounding.counts.{locale}", "grounding", not counted,
                       ("every count the copy states is the build's"
                        if not counted else "; ".join(p["message"][:160] for p in counted[:4])),
                       locale=locale, measured=[p["message"][:160] for p in counted[:8]] or None,
                       expected={f: c.get("value") for f, c in
                                 ((facts.get("measured") or {}).get("counts") or {}).items()},
                       warning=not failing,
                       fix="configure" if locale in supplied else "rewrite")
    for rendition in listing.get("platforms") or []:
        for locale, text in sorted((rendition.get("text") or {}).items()):
            problems = [p for p in grounding.check(text, facts, claims, locale=locale,
                                                   where=f"{rendition['platform_id']} copy", counts=counts)
                        if p["severity"] == "error"]
            if problems:
                checks.add(f"grounding.{rendition['platform_id']}.{locale}", "grounding", False,
                           "; ".join(p["message"][:120] for p in problems[:4]),
                           platform_id=rendition["platform_id"], locale=locale,
                           fix="configure" if locale in supplied else "rewrite")
    if not locales:
        checks.add("grounding.copy", "grounding", False, "nothing to ground: no copy", fix="rewrite")

    # -- platforms --------------------------------------------------------------------------
    platform_results = []
    for rendition in listing.get("platforms") or []:
        pid = rendition["platform_id"]
        profile = profiles.get(pid)
        reqs = platforms.requirements(profile, reference)
        failed, unknown, warnings = [], [], []
        files = {f.get("requirement"): [] for f in rendition.get("files") or []}
        for f in rendition.get("files") or []:
            files.setdefault(f.get("requirement"), []).append(f)
        # A required locale no copy could be written in leaves its texts and lists empty; that
        # is the locale's gap, which only a person closes (ship the strings, configure a
        # writer). Rewriting cannot, so those checks are not routed back to the listing.
        no_copy = sorted(r["locale"] for r in reqs if r["kind"] == "locale"
                         and r["locale"] not in (rendition.get("text") or {}))
        gap = f" (no copy in required locale {', '.join(no_copy)})" if no_copy else ""
        empty_fix = "configure" if no_copy else "rewrite"
        for req in reqs:
            cid = f"platforms.{pid}.{req['id']}"
            if req["kind"] == "locale":
                present = req["locale"] in (rendition.get("text") or {})
                entry = checks.add(cid, "platforms", present,
                                   f"{pid}: texts in {req['locale']} {'present' if present else 'missing'}",
                                   platform_id=pid, locale=req["locale"], fix="configure")
            elif req["kind"] == "text":
                present_any = any(isinstance((t or {}).get(req["field"]), str) and (t or {}).get(req["field"]).strip()
                                  for t in (rendition.get("text") or {}).values())
                if not req.get("required") and not present_any:
                    continue
                if req.get("max_chars") is None:
                    entry = checks.add(cid, "platforms", present_any,
                                       f"{pid}: {req['field']} {'present' if present_any else 'missing' + gap}; the "
                                       "profile states no length limit (UNKNOWN)",
                                       platform_id=pid, unknown=present_any, fix="configure" if present_any else empty_fix)
                    if present_any:
                        unknown.append(req["id"])
                else:
                    over = [loc for loc, t in (rendition.get("text") or {}).items()
                            if len((t or {}).get(req["field"]) or "") > req["max_chars"]]
                    entry = checks.add(cid, "platforms", present_any and not over,
                                       f"{pid}: {req['field']} within {req['max_chars']} chars"
                                       + (f"; over in {', '.join(over)}" if over else "")
                                       + ("" if present_any else "; missing" + gap),
                                       platform_id=pid, expected={"max_chars": req["max_chars"]},
                                       fix="rewrite" if present_any else empty_fix)
            elif req["kind"] == "list":
                counts = {loc: len((t or {}).get(req["field"]) or []) for loc, t in (rendition.get("text") or {}).items()}
                worst = min(counts.values()) if counts else 0
                if not req.get("required") and worst == 0:
                    continue
                ok = (req.get("min") is None or worst >= req["min"]) and (req.get("max") is None or max(counts.values() or [0]) <= req["max"])
                if not req["known"]:
                    entry = checks.add(cid, "platforms", worst > 0,
                                       f"{pid}: {req['field']} {'present' if worst > 0 else 'missing' + gap}; "
                                       "the profile states no bound (UNKNOWN)",
                                       platform_id=pid, unknown=worst > 0, fix="configure" if worst > 0 else empty_fix)
                    if worst > 0:
                        unknown.append(req["id"])
                else:
                    entry = checks.add(cid, "platforms", ok, f"{pid}: {req['field']} {counts}" + ("" if counts else gap),
                                       platform_id=pid, measured=counts,
                                       expected={"min": req.get("min"), "max": req.get("max")},
                                       fix="rewrite" if counts else empty_fix)
            elif req["kind"] == "image":
                made = files.get(req["image_id"]) or []
                if req.get("required") is False:
                    continue
                if not made:
                    unmet_here = [u for u in rendition.get("unmet") or [] if u.get("subject") == req["image_id"]]
                    entry = checks.add(cid, "platforms", False,
                                       f"{pid}: {req['image_id']} not rendered"
                                       + (": " + unmet_here[0]["message"] if unmet_here else ""),
                                       platform_id=pid, required=req.get("required") is not False,
                                       fix="configure" if unmet_here else "rerender", files=[req["image_id"]])
                else:
                    problems = []
                    for f in made:
                        exists, intact, info = _file_ok(f, run_dir)
                        if not exists or not intact:
                            problems.append(f"{f['id']} missing or changed")
                            continue
                        if req.get("sizes") and (info["width"], info["height"]) not in [tuple(s) for s in req["sizes"]]:
                            problems.append(f"{f['id']} is {info['width']}x{info['height']}")
                        if req.get("aspect") and not _aspect_ok(info["width"], info["height"], req["aspect"]):
                            problems.append(f"{f['id']} is not {req['aspect']}")
                        if req.get("formats") and info["format"] not in [("jpg" if x == "jpeg" else x) for x in req["formats"]]:
                            problems.append(f"{f['id']} is {info['format']}, not {'/'.join(req['formats'])}")
                        if req.get("max_kb") and info["bytes"] > req["max_kb"] * 1024:
                            problems.append(f"{f['id']} is {info['bytes'] // 1024} KB > {req['max_kb']} KB")
                    if not req["known"] and not problems:
                        entry = checks.add(cid, "platforms", True,
                                           f"{pid}: {req['image_id']} rendered at the canonical size; the profile "
                                           "states no size (UNKNOWN)", platform_id=pid, unknown=True,
                                           fix="configure", files=[f["id"] for f in made])
                        unknown.append(req["id"])
                    else:
                        entry = checks.add(cid, "platforms", not problems,
                                           f"{pid}: {req['image_id']} " + ("ok" if not problems else "; ".join(problems)),
                                           platform_id=pid, fix="rerender", files=[f["id"] for f in made])
            elif req["kind"] == "screenshots":
                made = files.get("screenshots") or []
                if req.get("required") is False:
                    continue
                if req.get("required") is None and not req["known"]:
                    entry = checks.add(cid, "platforms", bool(made), f"{pid}: {len(made)} screenshot(s); the profile "
                                                                     "states no requirement (UNKNOWN)",
                                       platform_id=pid, unknown=True, fix="configure")
                    unknown.append(req["id"])
                    continue
                problems = []
                if req.get("min") is not None and len(made) < req["min"]:
                    problems.append(f"{len(made)} < {req['min']}")
                if req.get("max") is not None and len(made) > req["max"]:
                    problems.append(f"{len(made)} > {req['max']}")
                for f in made:
                    exists, intact, info = _file_ok(f, run_dir)
                    if not exists or not intact:
                        problems.append(f"{f['id']} missing or changed")
                        continue
                    if req.get("sizes") and (info["width"], info["height"]) not in [tuple(s) for s in req["sizes"]]:
                        problems.append(f"{f['id']} is {info['width']}x{info['height']}")
                    if req.get("formats") and info["format"] not in [("jpg" if x == "jpeg" else x) for x in req["formats"]]:
                        problems.append(f"{f['id']} is {info['format']}")
                    if req.get("max_kb") and info["bytes"] > req["max_kb"] * 1024:
                        problems.append(f"{f['id']} over {req['max_kb']} KB")
                entry = checks.add(cid, "platforms", not problems,
                                   f"{pid}: {len(made)} screenshot(s)" + ("" if not problems else "; " + "; ".join(problems)),
                                   platform_id=pid, measured=len(made),
                                   expected={"min": req.get("min"), "max": req.get("max"), "sizes": req.get("sizes")},
                                   fix="recapture" if any("<" in p for p in problems) else "rerender")
            elif req["kind"] == "video":
                made = files.get("video") or []
                if req.get("required") is None and not req["known"]:
                    entry = checks.add(cid, "platforms", True, f"{pid}: video requirement not stated (UNKNOWN)",
                                       platform_id=pid, unknown=True, fix="configure")
                    unknown.append(req["id"])
                    continue
                if not req.get("required") and not made:
                    continue
                unmet_here = [u for u in rendition.get("unmet") or [] if u.get("subject") == "video"]
                problems = _video_problems(made, req, run_dir, trailer)
                detail = (unmet_here[0]["message"] if unmet_here else "; ".join(problems))
                entry = checks.add(cid, "platforms", bool(made) and not unmet_here and not problems,
                                   f"{pid}: video {'included' if made else 'missing'}"
                                   + (": " + detail if detail else ""),
                                   platform_id=pid, required=bool(req.get("required")), fix="configure",
                                   expected={k: req.get(k) for k in ("min_seconds", "max_seconds", "max_mb",
                                                                     "min_width", "min_height", "aspect")
                                             if req.get(k) is not None} or None)
            elif req["kind"] == "age_rating":
                if not req.get("required"):
                    continue
                stated = bool(rendition.get("age_rating")) or any(
                    (t or {}).get("age_rating") for t in (rendition.get("text") or {}).values())
                entry = checks.add(cid, "platforms", stated,
                                   f"{pid}: age rating {'stated' if stated else 'missing (factory.listing.age_rating)'}",
                                   platform_id=pid, fix="configure")
            elif req["kind"] == "naming":
                bad = [u for u in rendition.get("unmet") or [] if u.get("code") == "file-name"]
                entry = checks.add(cid, "platforms", not bad, f"{pid}: file names match {req['pattern']!r}"
                                   if not bad else bad[0]["message"], platform_id=pid, fix="rerender")
            else:
                continue
            if entry["status"] == "FAIL":
                failed.append(cid)
            elif entry["status"] == "WARNING":
                warnings.append(cid)
        for unmet in rendition.get("unmet") or []:
            if unmet.get("severity") == "warning":
                warnings.append(f"{pid}:{unmet.get('code')}")
        platform_results.append({"platform_id": pid, "profile_version": rendition.get("profile_version") or "unknown",
                                 "role": rendition.get("role") or "required",
                                 "spec_status": rendition.get("spec_status") or "absent",
                                 "status": "FAIL" if failed else "PASS", "failed": failed, "unknown": unknown,
                                 "warnings": warnings})
    if not listing.get("platforms"):
        checks.add("platforms.none", "platforms", False, "the listing has no platform rendition", fix="rerender")
    return checks.items, platform_results


def required_locales(listing, reference, profiles):
    """en, and every locale a targeted platform's profile requires."""
    out = ["en"]
    for rendition in listing.get("platforms") or []:
        for req in platforms.requirements(profiles.get(rendition.get("platform_id")), reference):
            if req["kind"] == "locale" and req["locale"] not in out:
                out.append(req["locale"])
    return out


def _build_checks(checks, listing, reference, profiles, facts, locales, supplied):
    """The copy against the build at the run's tier: the writer, every required locale's
    full description, its controls, its subtitle."""
    bars = ((facts.get("quality") or {}).get("bars") or {})
    tier = (facts.get("quality") or {}).get("tier")
    writer = (listing.get("copy") or {}).get("writer") or {}
    written = [loc for loc in locales if loc not in supplied]
    if writer.get("required") and written:
        wanted, kind = writer["required"], writer.get("kind")
        ok = kind == wanted and not (kind == "command" and writer.get("fallback"))
        why = ("" if ok else
               f": the tier ({tier}) asks for the copywriter agent and no agent writer is configured "
               "(factory.listing.writer: kind command with argv), nor the copy supplied "
               "(factory.listing.copy_dir)" if kind != wanted else
               ": the copywriter's text was refused twice and the template's stands in")
        checks.add("metadata.writer", "metadata", ok,
                   f"the copy in {', '.join(sorted(written))} was written by the {kind} writer"
                   + ("" if kind == wanted else f", the tier asks for {wanted}") + why,
                   measured={"kind": kind, "fallback": bool(writer.get("fallback"))},
                   expected={"kind": wanted, "tier": tier},
                   fix="configure" if kind != wanted else "rewrite")
    required = required_locales(listing, reference, profiles)
    full_bar = bool(bars.get("full_description_per_required_locale"))
    controls_bar = bool(bars.get("controls_cover_all_inputs"))
    devices = buildfacts.required_devices(facts)
    for locale, text in sorted(locales.items()):
        fix = "configure" if locale in supplied else "rewrite"
        if locale in required:
            problems = buildfacts.full_description_problems(text, reference, locale)
            checks.add(f"metadata.{locale}.full_description", "metadata", not problems,
                       f"{locale}: a full description" if not problems else
                       f"{locale} is not a full description: " + "; ".join(problems[:4]),
                       locale=locale, measured=problems or None,
                       expected=(reference.get("copy") or {}).get("full_description"),
                       required=full_bar, fix=fix)
        if devices:
            missing, checkable = buildfacts.controls_problems(text, facts, reference.get("controls"), locale)
            if not checkable:
                checks.add(f"metadata.{locale}.controls", "metadata", False,
                           f"{locale}: no device words for this language in store-listing.yaml "
                           f"`controls`: whether its controls name {', '.join(devices)} is UNKNOWN",
                           locale=locale, unknown=True, fix="configure")
            else:
                checks.add(f"metadata.{locale}.controls", "metadata", not missing,
                           f"{locale}: the controls name {', '.join(devices)}" if not missing else
                           f"{locale}: the controls text does not name {', '.join(missing)}, which "
                           f"the build accepts ({', '.join(devices)})",
                           locale=locale, measured={"missing": missing},
                           expected={"devices": devices}, required=controls_bar, fix=fix)
        if buildfacts.generic_subtitle(text, facts, reference, locale):
            checks.add(f"metadata.{locale}.subtitle", "metadata", False,
                       f"{locale}: the subtitle {text.get('subtitle')!r} names only the genre",
                       locale=locale, fix=fix)


def _sections(checks):
    out = {}
    for section in SECTIONS:
        mine = [c for c in checks if c["section"] == section]
        if not mine or all(c["status"] == "UNKNOWN" for c in mine):
            out[section] = "UNKNOWN"
        elif any(c["status"] == "FAIL" and c["required"] for c in mine):
            out[section] = "FAIL"
        else:
            out[section] = "PASS"
    return out


class ListingValidationStep(WorkflowStep):
    type = "listing-validation"
    clock = staticmethod(_utc_now)

    def execute(self, inputs, context):
        try:
            settings = Settings.resolve(context.config, self.params)
        except SettingsError as exc:
            return StepResult.failed(str(exc), retryable=False)
        if "store-listing" not in inputs:
            return StepResult.waiting_for_input("listing-validation needs a store-listing in the run")
        listing = inputs.load("store-listing")
        ref = inputs.refs["store-listing"]
        self._ctx = {"context": context, "inputs": inputs, "listing": listing, "ref": ref,
                     "title_id": listing.get("title_id"), "commit": listing.get("commit") or "0" * 40}
        try:
            reference = load_file(settings.reference_path)
        except (OSError, YamlError, ValueError) as exc:
            return StepResult.failed(f"the store listing reference cannot be read: {exc}", retryable=False)
        with open(settings.reference_path, "rb") as handle:
            self._ctx["reference"] = {"version": str(reference.get("version")),
                                      "sha256": "sha256:" + hashlib.sha256(handle.read()).hexdigest()}
        if listing.get("status") == "blocked":
            return self._finish("BLOCKED", [], [], reference,
                                blocked=f"the store-listing is blocked: {(listing.get('capture') or {}).get('blocked_reason') or 'nothing was captured'}")
        profiles = {}
        for rendition in listing.get("platforms") or []:
            try:
                profiles[rendition["platform_id"]] = platforms.load_profile(rendition["platform_id"])
            except platforms.ProfileError as exc:
                return StepResult.failed(str(exc), retryable=False)
        facts = listing.get("facts") or {}
        checks, platform_results = validate(listing, context.run_dir, reference, profiles, facts)
        return self._finish(None, checks, platform_results, reference)

    def _finish(self, outcome, checks, platform_results, reference, blocked=None):
        ctx = self._ctx
        context, listing = ctx["context"], ctx["listing"]
        failed = [c["id"] for c in checks if c["status"] == "FAIL" and c["required"]]
        unknown = [c["id"] for c in checks if c["status"] == "UNKNOWN"]
        warnings = [c["id"] for c in checks if c["status"] == "WARNING"]
        if outcome is None:
            if not failed:
                outcome = "PASS"
            else:
                actionable = any(c.get("fix") in ACTIONABLE for c in checks
                                 if c["status"] == "FAIL" and c["required"])
                outcome = "FAIL" if actionable else "BLOCKED"
                if outcome == "BLOCKED":
                    blocked = ("every failed check needs a person: "
                               + "; ".join(c["summary"][:100] for c in checks
                                           if c["status"] == "FAIL" and c["required"])[:600])
        now = self.clock()
        report = {
            "provenance": provenance.build(
                "listing-validation-report",
                artifact_id=provenance.artifact_id("listing-validation-report", ctx["title_id"], now,
                                                   getattr(context, "execution", 1)),
                produced_by=provenance.producer(ROLE), produced_at=now,
                inputs=provenance.pin_inputs(ctx["inputs"], REQUIRED_INPUTS + OPTIONAL_INPUTS),
                title_id=ctx["title_id"]),
            "title_id": ctx["title_id"],
            "commit": ctx["commit"],
            "listing": {"artifact_id": listing["provenance"]["artifact_id"], "content_hash": ctx["ref"].content_hash,
                        "status": listing.get("status")},
            "verdict": outcome,
            "sections": _sections(checks),
            "checks": checks,
            "platform_requirements": platform_results,
            "failed": failed,
            "unknown": unknown,
            "warnings": warnings,
            "routes": [FAIL_ROUTE] if outcome == "FAIL" else [],
            "blocked_reason": blocked,
            "reference": ctx["reference"],
        }
        workflow = {k: v for k, v in {
            "run_id": getattr(context, "run_id", None), "workflow_id": getattr(context, "workflow_id", None),
            "step_id": getattr(context, "current_step", None), "visit": getattr(context, "visit", None),
            "execution": getattr(context, "execution", None)}.items() if v is not None}
        if workflow.get("run_id"):
            report["workflow"] = workflow
        provenance.seal(report)
        package_dir = listing.get("package_dir")
        if package_dir:
            target = os.path.join(context.run_dir, *package_dir.split("/"), "validation.json")
            if os.path.isdir(os.path.dirname(target)):
                from .package import write_json
                write_json(target, report)
        output = ArtifactOutput("listing-validation-report", report, metadata={
            "verdict": outcome, "failed": len(failed), "unknown": len(unknown), "commit": ctx["commit"],
            "platforms": {p["platform_id"]: p["status"] for p in platform_results}})
        per_platform = ", ".join(f"{p['platform_id']} {p['status']}"
                                 + (f" ({len(p['unknown'])} unknown)" if p["unknown"] else "")
                                 for p in platform_results)
        if outcome == "BLOCKED":
            context.logger.warning("listing validation blocked", reason=blocked, failed=failed[:10])
            return StepResult("BLOCKED", artifacts=[output], message=f"listing validation blocked: {blocked}")
        if outcome == "FAIL":
            context.logger.error("listing validation failed", failed=failed[:10])
            return StepResult("FAILED", route=FAIL_ROUTE, artifacts=[output], retryable=False,
                              error=f"{len(failed)} listing check(s) failed: "
                                    + "; ".join(c["summary"][:90] for c in checks if c["id"] in failed[:5])
                                    + (f" ({per_platform})" if per_platform else ""))
        return StepResult.success([output], message=(
            f"store listing validated for {ctx['commit'][:12]}: {len(checks)} checks, "
            f"{len(unknown)} unknown, {len(warnings)} warning(s)" + (f"; {per_platform}" if per_platform else "")))
