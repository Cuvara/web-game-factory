"""Laying the canonical package out, and rendering each platform's listing from it.

    select_screenshots()   which captured frames are screenshots: play first, the title last;
                           nothing in an excluded probe state, nothing below the readability
                           floors, nothing indistinguishable from an earlier one
    canonical_icons()      the smaller icon masters from the 1024 one (pure Python)
    render_platform()      one platform's rendition under its requirement list
                           (platforms.requirements): images resized and cover-cropped from
                           the canonical masters - never upscaled - texts cut to the limits,
                           lists cut and mapped, the trailer when its container is accepted;
                           everything it cannot make is an `unmet` problem, never left out
                           silently
    file_record()          {id, kind, path, sha256, bytes, format, width, height, source}
                           for one file, paths relative to the run directory

Deterministic names throughout (core/reference/store-listing.yaml `package`).
"""

import json
import os
import shutil

from . import imaging, media
from .copywriter import fit_list, fit_text

__all__ = ["select_screenshots", "canonical_icons", "render_platform", "file_record",
           "relative_to", "write_json", "SCENE_ORDER"]

# Play frames lead; the result screen shows the stakes; the title screen comes last.
SCENE_ORDER = ("play-mid", "play-late", "play-early", "result", "title")


def relative_to(path, run_dir):
    return os.path.relpath(path, run_dir).replace(os.sep, "/")


def write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=False)
        handle.write("\n")


def file_record(file_id, path, run_dir, *, kind=None, source=None, requirement=None):
    info = media.describe(path)
    record = {"id": file_id, "path": relative_to(path, run_dir), "sha256": media.sha256_of(path),
              "bytes": info["bytes"], "format": info["format"]}
    if kind:
        record["kind"] = kind
    if info["width"]:
        record["width"], record["height"] = info["width"], info["height"]
    if source:
        record["source"] = source
    if requirement:
        record["requirement"] = requirement
    return record


def select_screenshots(shots, reference, *, maximum=None):
    """From the capture's shots ([{scene, state, file, excluded, viewport}]) the ones that are
    screenshots, in listing order, with why each other was dropped:
    ([{scene, viewport, file, state, stats}], [{file, reason}])."""
    capture = (reference or {}).get("capture") or {}
    bars = capture.get("frame_bars") or {}
    distinct = capture.get("distinct") or {}
    excluded_states = set(capture.get("excluded_states") or ())
    maximum = maximum or ((reference or {}).get("renditions") or {}).get("screenshots", {}).get("max")
    order = {scene: index for index, scene in enumerate(SCENE_ORDER)}
    ordered = sorted(shots, key=lambda s: (order.get(s.get("scene"), 99), s.get("viewport") or ""))
    chosen, dropped = [], []
    for shot in ordered:
        if not os.path.isfile(shot.get("file") or ""):
            dropped.append({"file": shot.get("file"), "reason": "missing"})
            continue
        if shot.get("excluded") or shot.get("state") in excluded_states:
            dropped.append({"file": shot["file"], "reason": f"state {shot.get('state')} is excluded"})
            continue
        try:
            mean, contrast, lit = imaging.frame_stats(shot["file"], bars.get("lit_luminance", 64))
        except Exception as exc:  # noqa: BLE001 - an unreadable frame is dropped, not fatal
            dropped.append({"file": shot["file"], "reason": f"unreadable: {exc}"})
            continue
        if lit < bars.get("min_lit_share", 0.01):
            dropped.append({"file": shot["file"], "reason": f"too dark: {round(lit * 100, 2)}% lit"})
            continue
        if mean > bars.get("max_mean_luminance", 225):
            dropped.append({"file": shot["file"], "reason": f"washed out: mean luminance {mean}"})
            continue
        if contrast < bars.get("min_contrast", 18):
            dropped.append({"file": shot["file"], "reason": f"flat: contrast {contrast}"})
            continue
        same = None
        for earlier in chosen:
            if earlier["viewport"] != shot.get("viewport"):
                continue
            try:
                changed = imaging.changed_fraction(earlier["file"], shot["file"],
                                                   distinct.get("min_pixel_delta", 24))
            except Exception:  # noqa: BLE001
                changed = 1.0
            if changed < distinct.get("min_changed_fraction", 0.05):
                same = earlier
                break
        if same is not None:
            dropped.append({"file": shot["file"], "reason": f"indistinct from {same['scene']} "
                                                            f"({same['viewport']})"})
            continue
        chosen.append({"scene": shot["scene"], "viewport": shot.get("viewport"), "file": shot["file"],
                       "state": shot.get("state"),
                       "stats": {"mean_luminance": mean, "contrast": contrast, "lit_share": lit}})
        if maximum and len(chosen) >= maximum:
            break
    return chosen, dropped


def canonical_icons(master_path, renditions, out_dir):
    """Every icon rendition smaller than the master, downscaled from it. Returns
    [(id, path, w, h)]."""
    master = imaging.read_png(master_path)
    made = []
    for entry in (renditions or {}).get("icon") or []:
        w, h = int(entry["width"]), int(entry["height"])
        path = os.path.join(out_dir, f"{entry['id']}.png")
        if (w, h) == (master.width, master.height):
            if os.path.abspath(path) != os.path.abspath(master_path):
                shutil.copyfile(master_path, path)
        elif w <= master.width and h <= master.height:
            imaging.write_png(path, imaging.fit(master, w, h, "cover"))
        else:
            continue
        made.append((entry["id"], path, w, h))
    return made


def _aspect_matches(width, height, aspect):
    if not aspect:
        return True
    try:
        a, b = (int(x) for x in str(aspect).split(":"))
    except ValueError:
        return True
    return abs(width / height - a / b) < 0.02


def _master_for(requirement, masters):
    """The canonical master a platform image is rendered from: by family, then by aspect."""
    family = requirement.get("source") or "thumbnail"
    candidates = [m for m in masters if m["family"] == family]
    if not candidates:
        candidates = [m for m in masters if m["family"] == "thumbnail"] or list(masters)
    wanted_aspect = requirement.get("aspect")
    sizes = requirement.get("sizes") or []
    if not wanted_aspect and sizes:
        wanted_aspect = imaging.aspect_of(*sizes[0])
    if wanted_aspect:
        matching = [m for m in candidates if _aspect_matches(m["width"], m["height"], wanted_aspect)]
        if matching:
            candidates = matching
    return max(candidates, key=lambda m: m["width"] * m["height"]) if candidates else None


def _format_for(requirement, browser_formats):
    """(format, available): the first accepted format the package can write."""
    formats = requirement.get("formats")
    if not formats:
        return "png", True
    for fmt in formats:
        fmt = "jpg" if fmt == "jpeg" else fmt
        if fmt == "png":
            return "png", True
        if fmt in browser_formats:
            return fmt, True
    return formats[0], False


def render_platform(platform, requirements, *, canonical, copies, out_dir, run_dir, reference,
                    browser_formats=(), age_rating=None):
    """One platform's rendition. `canonical` is the canonical package record: {"masters":
    [{id, family, path, width, height}], "screenshots": [{id, path, viewport, width,
    height}], "trailer": {...}}; `copies` {locale: localeCopy}. Returns (rendition entry
    for the listing, derive jobs for the browser [{id, source, out, width, height, format}])."""
    pid = platform["platform_id"]
    os.makedirs(out_dir, exist_ok=True)
    files, unmet, derive, text = [], [], [], {}
    canonical_copy = (reference or {}).get("copy") or {}

    def problem(code, message, severity="error", subject=None):
        unmet.append({"code": code, "severity": severity, "message": message, "subject": subject})

    required_locales = [r["locale"] for r in requirements if r["kind"] == "locale"]
    for locale in required_locales:
        copy = copies.get(locale)
        if not copy:
            problem("locale-missing", f"{pid} requires the listing texts in `{locale}`, and none "
                                      f"could be written in it (no agent writer, and the build ships "
                                      f"no `{locale}` strings)", subject=locale)
            continue
        cut = json.loads(json.dumps(copy))
        for req in requirements:
            if req["kind"] == "text" and req.get("max_chars"):
                field = req["field"]
                if isinstance(cut.get(field), str):
                    cut[field] = fit_text(cut[field], req["max_chars"])
                elif isinstance(cut.get(field), list):  # promo variants
                    cut[field] = fit_list(cut[field], None, req["max_chars"])
            if req["kind"] == "list":
                field = req["field"]
                allowed = req.get("allowed")
                allowed_map = {a.lower(): a for a in allowed} if isinstance(allowed, list) else None
                items = cut.get(field) or []
                if allowed_map is not None:
                    mapped = [allowed_map[i.lower()] for i in items if i.lower() in allowed_map]
                    if not mapped and items:
                        problem("tags-unmapped", f"{pid}: none of the {field} ({', '.join(items)}) "
                                                 f"is in the portal's vocabulary; map them in the "
                                                 f"profile's store_listing.{field}.allowed",
                                severity="warning", subject=field)
                    items = mapped
                cut[field] = fit_list(items, req.get("max"), req.get("max_chars"))
        rating = (req for req in requirements if req["kind"] == "age_rating")
        for req in rating:
            if req.get("required"):
                value = age_rating.get(pid) or age_rating.get("default") if isinstance(age_rating, dict) else age_rating
                if value:
                    cut["age_rating"] = str(value)
                elif not cut.get("age_rating"):
                    problem("age-rating-missing", f"{pid} requires an age rating and nothing in the "
                                                  f"run states one: set factory.listing.age_rating "
                                                  f"({pid} or default)", subject="age_rating")
        text[locale] = cut
    if not required_locales and copies.get("en"):
        text["en"] = copies["en"]

    masters = canonical.get("masters") or []
    for req in requirements:
        if req["kind"] != "image":
            continue
        if req.get("required") is False:
            continue
        master = _master_for(req, masters)
        if master is None:
            problem("no-master", f"{pid} asks for {req['image_id']} and the canonical package has "
                                 f"no {req.get('source') or 'thumbnail'} master to make it from",
                    severity="error" if req.get("required") else "warning", subject=req["image_id"])
            continue
        fmt, available = _format_for(req, browser_formats)
        if not available:
            problem("format-unavailable", f"{pid} accepts {req['image_id']} only as "
                                          f"{', '.join(req.get('formats') or [])}, which no encoder "
                                          f"here writes", subject=req["image_id"])
            fmt = "png"
        sizes = req.get("sizes") or [None]
        for size in sizes:
            if size is None:
                w, h = master["width"], master["height"]
                if req.get("aspect") and not _aspect_matches(w, h, req["aspect"]):
                    a, b = (int(x) for x in req["aspect"].split(":"))
                    if w / h > a / b:
                        w = int(round(h * a / b))
                    else:
                        h = int(round(w * b / a))
            else:
                w, h = size
            if w > master["width"] or h > master["height"]:
                problem("size-above-master", f"{pid} asks for {req['image_id']} at {w}x{h}, larger than "
                                             f"the {master['id']} master ({master['width']}x"
                                             f"{master['height']}); the package never upscales",
                        subject=req["image_id"])
                continue
            stem = f"{req['image_id']}-{w}x{h}"
            png_path = os.path.join(out_dir, f"{stem}.png")
            image = imaging.read_png(master["path"])
            imaging.write_png(png_path, imaging.fit(image, w, h, "cover"))
            if fmt == "png":
                record = file_record(stem, png_path, run_dir, kind=_kind(req), source=master["id"],
                                     requirement=req["image_id"])
                files.append(record)
            else:
                out = os.path.join(out_dir, f"{stem}.{fmt}")
                derive.append({"id": f"{pid}:{stem}", "source": png_path, "out": out, "width": w,
                               "height": h, "format": fmt, "quality": 0.92,
                               "record": {"id": stem, "kind": _kind(req), "source": master["id"],
                                          "requirement": req["image_id"]}})
            if req.get("max_kb") and os.path.isfile(png_path) and fmt == "png" \
                    and os.path.getsize(png_path) > req["max_kb"] * 1024:
                problem("file-too-large", f"{pid}: {stem}.png is {os.path.getsize(png_path) // 1024} KB, "
                                          f"over the {req['max_kb']} KB limit", subject=stem)

    shots_req = next((r for r in requirements if r["kind"] == "screenshots"), None)
    if shots_req and shots_req.get("required") is not False:
        shots = list(canonical.get("screenshots") or [])
        orientation = shots_req.get("orientation")
        if orientation:
            wanted = set(orientation)
            shots = [s for s in shots if s.get("viewport") in wanted] or shots
        maximum = shots_req.get("max")
        if maximum:
            shots = shots[:maximum]
        fmt, available = _format_for(shots_req, browser_formats)
        if not available:
            problem("format-unavailable", f"{pid} accepts screenshots only as "
                                          f"{', '.join(shots_req.get('formats') or [])}, which no "
                                          f"encoder here writes", subject="screenshots")
            fmt = "png"
        sizes = shots_req.get("sizes")
        for index, shot in enumerate(shots, 1):
            image = imaging.read_png(shot["path"])
            w, h = image.width, image.height
            if sizes:
                fitting = [s for s in sizes if s[0] <= w and s[1] <= h and
                           (s[0] >= s[1]) == (w >= h)] or [s for s in sizes if s[0] <= w and s[1] <= h]
                if not fitting:
                    problem("size-above-master", f"{pid} asks for screenshots at "
                                                 f"{', '.join(f'{a}x{b}' for a, b in sizes)}, larger than "
                                                 f"the captured {w}x{h} frame", subject="screenshots")
                    continue
                w, h = fitting[0]
                image = imaging.fit(image, w, h, "cover")
            elif shots_req.get("aspect") and not _aspect_matches(w, h, shots_req["aspect"]):
                a, b = (int(x) for x in shots_req["aspect"].split(":"))
                if w / h > a / b:
                    w = int(round(h * a / b))
                else:
                    h = int(round(w * b / a))
                image = imaging.fit(image, w, h, "cover")
            stem = f"screenshot-{index:02d}"
            png_path = os.path.join(out_dir, f"{stem}.png")
            imaging.write_png(png_path, image)
            if fmt == "png":
                files.append(file_record(stem, png_path, run_dir, kind="screenshot", source=shot["id"],
                                         requirement="screenshots"))
            else:
                derive.append({"id": f"{pid}:{stem}", "source": png_path, "out": os.path.join(out_dir, f"{stem}.{fmt}"),
                               "width": w, "height": h, "format": fmt, "quality": 0.92,
                               "record": {"id": stem, "kind": "screenshot", "source": shot["id"],
                                          "requirement": "screenshots"}})
        minimum = shots_req.get("min")
        if minimum and len(shots) < minimum:
            problem("screenshots-insufficient", f"{pid} requires at least {minimum} screenshots; the "
                                                f"package has {len(shots)}", subject="screenshots")

    video_req = next((r for r in requirements if r["kind"] == "video"), None)
    trailer = canonical.get("trailer") or {}
    if video_req and video_req.get("required") is not False:
        severity = "error" if video_req.get("required") else "warning"
        if trailer.get("status") == "recorded":
            accepted = video_req.get("formats")
            chosen = None
            options = [(trailer.get("container"), trailer.get("path"))] + [
                (d.get("format"), d.get("path")) for d in trailer.get("derived") or []]
            for fmt, path in options:
                if path and (not accepted or fmt in accepted):
                    chosen = (fmt, path)
                    break
            if chosen:
                out = os.path.join(out_dir, f"trailer.{chosen[0]}")
                shutil.copyfile(chosen[1], out)
                files.append(file_record("trailer", out, run_dir, kind="trailer", source="trailer",
                                         requirement="video"))
            else:
                problem("video-format-unavailable", f"{pid} accepts a video only as "
                                                    f"{', '.join(accepted or [])}; the recording is "
                                                    f"{trailer.get('container')} and no encoder here "
                                                    f"converts it", severity=severity, subject="video")
        elif video_req.get("required"):
            problem("video-missing", f"{pid} requires a video and the package has "
                                     f"{'a frame-sequence fallback, not a video' if trailer.get('status') == 'fallback' else 'none'}",
                    severity=severity, subject="video")

    naming = next((r for r in requirements if r["kind"] == "naming"), None)
    if naming:
        import re
        pattern = re.compile(naming["pattern"])
        for record in files:
            if not pattern.match(os.path.basename(record["path"])):
                problem("file-name", f"{pid}: {os.path.basename(record['path'])} does not match the "
                                     f"portal's file naming rule {naming['pattern']!r}", subject=record["id"])

    listing_path = os.path.join(out_dir, "listing.json")
    entry = {
        "platform_id": pid, "profile_version": platform.get("profile_version") or "unknown",
        "role": platform.get("role") or "required", "spec_status": platform.get("spec_status") or "absent",
        "dir": relative_to(out_dir, run_dir), "listing": relative_to(listing_path, run_dir),
        "files": files, "text": text, "locales_required": required_locales, "unmet": unmet,
    }
    return entry, derive


def _kind(requirement):
    source = requirement.get("source") or "thumbnail"
    return {"icon": "icon", "logo": "logo", "promo": "promo", "screenshot": "screenshot"}.get(source, "thumbnail")
