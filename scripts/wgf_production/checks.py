"""Judging production quality from what the playability bot recorded, the manifest and the design.

`judge(records, manifest, design, rules, frames_dirs)` -> checks (dicts per
production-quality-report.schema.json). `records` is {project: {test: record}} as the bot
wrote them (scripts/wgf_playability/bot.spec.ts); `frames_dirs` is {project: directory of its
frames}. Nothing here plays the game or trusts the game's own account of its art beyond what
the bot saw: an asset is loaded when the page fetched its file, an entity is drawn from an
asset when the probe names one and the asset is in the runtime manifest the page fetched, a
control's size, colours and style are what the browser computed.

Every check carries `route`: `assets` when an asset itself must be made again (missing, a
placeholder, failing its own quality checks), `develop` when the game's use of assets or its
UI must change. Bars: core/reference/production-quality.yaml.
"""

import os
import statistics

from wgf_assets.raster import RasterError, decode_png

__all__ = ["judge", "contrast_ratio", "required_assets", "served_paths"]

ASSETS, DEVELOP = "assets", "develop"


def _check(cid, ok, summary, route, *, project=None, required=True, measured=None,
           expected=None, assets=None, frames=None, status=None):
    entry = {"id": cid, "status": status or ("PASS" if ok else ("FAIL" if required else "WARNING")),
             "required": required, "summary": summary, "route": route}
    if project:
        entry["project"] = project
    if measured is not None:
        entry["measured"] = measured
    if expected is not None:
        entry["expected"] = expected
    if assets:
        entry["assets"] = sorted(set(assets))
    if frames:
        entry["frames"] = list(frames)
    return entry


# -- colour ------------------------------------------------------------------------------

def _channel(value):
    c = value / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(rgb):
    r, g, b = (_channel(v) for v in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground, background):
    """WCAG 2.x contrast ratio of two sRGB colours (0-255 channels), 1-21."""
    a, b = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return round((a + 0.05) / (b + 0.05), 2)


def _over(color, background):
    """A possibly translucent colour [r, g, b, a] composited over an opaque background."""
    alpha = color[3] if len(color) > 3 else 1
    return [round(c * alpha + b * (1 - alpha)) for c, b in zip(color[:3], background[:3])]


class _Frames:
    """The bot's frames of one viewport, decoded once, for what the DOM cannot tell: the
    colour behind text drawn over the canvas."""

    def __init__(self, directory):
        self.directory = directory
        self.cache = {}

    def image(self, frame_id):
        if frame_id not in self.cache:
            path = os.path.join(self.directory or "", f"{frame_id}.png")
            try:
                with open(path, "rb") as handle:
                    self.cache[frame_id] = decode_png(handle.read())
            except (OSError, RasterError):
                self.cache[frame_id] = None
        return self.cache[frame_id]

    def background(self, frame_id, box, viewport):
        """The dominant colour of the frame inside `box` (CSS px), or None: text covers
        the minority of the pixels of its own bounds."""
        image = self.image(frame_id)
        if image is None or not box or not viewport or not viewport[0]:
            return None
        scale = image.width / float(viewport[0])
        x0, y0 = max(0, int(box[0] * scale)), max(0, int(box[1] * scale))
        x1 = min(image.width, int((box[0] + box[2]) * scale))
        y1 = min(image.height, int((box[1] + box[3]) * scale))
        if x1 <= x0 or y1 <= y0:
            return None
        step = max(1, min(x1 - x0, y1 - y0) // 24)
        buckets = {}
        px = image.pixels
        for y in range(y0, y1, step):
            for x in range(x0, x1, step):
                i = (y * image.width + x) * 4
                rgb = (px[i], px[i + 1], px[i + 2])
                key = tuple(v >> 4 for v in rgb)
                buckets.setdefault(key, []).append(rgb)
        if not buckets:
            return None
        dominant = max(buckets.values(), key=len)
        return [round(statistics.fmean(c[k] for c in dominant)) for k in range(3)]


    def differs(self, frame_id, box, viewport, min_delta):
        """Share of the frame's pixels inside `box` that differ from the frame's dominant
        colour by at least `min_delta` in some channel; None when it cannot be read."""
        image = self.image(frame_id)
        if image is None or not box or not viewport or not viewport[0]:
            return None
        background = self.background(frame_id, [0, 0, viewport[0], viewport[1]], viewport)
        scale = image.width / float(viewport[0])
        x0, y0 = max(0, int(box[0] * scale)), max(0, int(box[1] * scale))
        x1 = min(image.width, int((box[0] + box[2]) * scale))
        y1 = min(image.height, int((box[1] + box[3]) * scale))
        if x1 <= x0 or y1 <= y0 or background is None:
            return None
        step = max(1, min(x1 - x0, y1 - y0) // 32)
        px, total, changed = image.pixels, 0, 0
        for y in range(y0, y1, step):
            for x in range(x0, x1, step):
                i = (y * image.width + x) * 4
                total += 1
                if max(abs(px[i + k] - background[k]) for k in range(3)) >= min_delta:
                    changed += 1
        return round(changed / total, 4) if total else None


# -- assets --------------------------------------------------------------------------------

def required_assets(manifest, design, rules):
    """{id: (requirement or None, manifest item or None)} for every asset the gate requires:
    each design requirement and manifest item of a required tier."""
    tiers = set((rules.get("assets") or {}).get("required_tiers") or ["mvp"])
    skipped = set((rules.get("assets") or {}).get("skipped_statuses") or ["cut"])
    items = {i.get("id"): i for i in (manifest or {}).get("items") or [] if isinstance(i, dict)}
    wanted = {}
    for req in ((design or {}).get("build_spec") or {}).get("assets") or []:
        if isinstance(req, dict) and req.get("tier") in tiers and req.get("id"):
            wanted[req["id"]] = (req, items.get(req["id"]))
    for item_id, item in items.items():
        if item.get("scope_tier") in tiers and item_id not in wanted:
            wanted[item_id] = (None, item)
    return {k: v for k, v in wanted.items() if not (v[1] and v[1].get("status") in skipped)}


def _relative(url):
    while url.startswith("./"):
        url = url[2:]
    return url


def served_paths(item, runtime):
    """URL paths, relative to the served root's `assets/`, that deliver a manifest item:
    from the runtime manifest the page fetched when there is one (its url, data, and its
    atlas), else from the item's delivered files under public/assets/."""
    asset_id = item.get("id")
    entry = ((runtime or {}).get("assets") or {}).get(asset_id) if isinstance(runtime, dict) else None
    paths = set()
    if isinstance(entry, dict):
        for key in ("url", "data"):
            if isinstance(entry.get(key), str):
                paths.add(_relative(entry[key]))
        atlas = ((runtime.get("atlases") or {}).get(entry.get("atlas")) or {})
        for key in ("url", "data"):
            if isinstance(atlas.get(key), str):
                paths.add(_relative(atlas[key]))
    if not paths:
        for f in item.get("files") or []:
            path = (f.get("path") or "").replace("\\", "/")
            if path.startswith("public/assets/"):
                paths.add(path[len("public/assets/"):])
    return paths


def _requirement_ids_for_roles(wanted, roles):
    out = []
    for asset_id, (req, item) in wanted.items():
        role = (req or {}).get("role") or (item or {}).get("role")
        if role in roles:
            out.append(asset_id)
    return out


# -- the checks ----------------------------------------------------------------------------

def _all_records(records):
    for project, tests in records.items():
        for name, record in tests.items():
            if isinstance(record, dict):
                yield project, name, record


def _snapshots(record):
    for s in record.get("samples") or []:
        yield s
    for a in record.get("acted") or []:
        for key in ("before", "after"):
            yield a.get(key)


def _entity_views(tests):
    """Every observation of an entity on one viewport: (id, role, asset, render, has_fields)."""
    for record in tests.values():
        if not isinstance(record, dict):
            continue
        for s in _snapshots(record):
            for e in (s or {}).get("entities") or []:
                if isinstance(e, dict):
                    yield (e.get("id"), e.get("role"), e.get("asset"), e.get("render"),
                           "render" in e)
        for frame in ((record.get("sampled") or {}).get("frames") or []):
            for sample in frame:
                if len(sample) >= 9:
                    yield sample[0], sample[1], sample[7], sample[8], sample[8] is not None
                else:
                    yield sample[0], sample[1], None, None, False


def assets_present(wanted):
    missing, placeholder, quality, ok = [], [], [], []
    for asset_id, (_req, item) in sorted(wanted.items()):
        if item is None or item.get("status") in ("planned",):
            missing.append(asset_id)
        elif item.get("placeholder"):
            placeholder.append(asset_id)
        elif ((item.get("quality") or {}).get("verdict")) != "pass":
            quality.append(asset_id)
        else:
            ok.append(asset_id)
    bad = missing + placeholder + quality
    parts = ([f"no delivered manifest item: {', '.join(missing)}"] if missing else []) \
        + ([f"placeholders: {', '.join(placeholder)}"] if placeholder else []) \
        + ([f"quality not pass: {', '.join(quality)}"] if quality else [])
    return _check("assets.present", not bad and bool(wanted),
                  "; ".join(parts) if bad else (
                      f"{len(ok)} required asset(s) delivered, none a placeholder, all passing "
                      "their quality checks" if wanted else "no required asset in the design or manifest"),
                  ASSETS, measured={"missing": missing, "placeholder": placeholder,
                                    "quality_not_pass": quality, "ok": len(ok)},
                  expected="every required-tier asset: a manifest item, placeholder false, quality.verdict pass",
                  assets=bad)


def assets_loaded(wanted, records, rules):
    not_loaded = set((rules.get("assets") or {}).get("not_loaded_types") or [])
    requests, runtime, recorded = [], None, False
    for _project, _name, record in _all_records(records):
        if "asset_requests" in record:
            recorded = True
            requests += [r for r in record.get("asset_requests") or [] if isinstance(r, dict)]
        if runtime is None and isinstance(record.get("runtime_assets"), dict):
            runtime = record["runtime_assets"]
    if not recorded:
        return _check("assets.loaded", False, "the playability records carry no asset requests: "
                      "they predate the bot that records them; play the build again", DEVELOP,
                      status="BLOCKED")
    fetched = [r["url"] for r in requests if isinstance(r.get("url"), str)
               and r.get("status") is not None and 200 <= r["status"] < 400]
    unfetched, unloadable, judged = [], [], 0
    for asset_id, (_req, item) in sorted(wanted.items()):
        if item is None or item.get("type") in not_loaded:
            continue
        paths = served_paths(item, runtime)
        if not paths:
            unloadable.append(asset_id)  # a reference (a system font stack): no file to fetch
            continue
        judged += 1
        if not any(url.endswith("/assets/" + p) for p in paths for url in fetched):
            unfetched.append(asset_id)
    failed = [r for r in requests if r.get("status") is None or r.get("status", 0) >= 400]
    ok = not unfetched and not failed
    return _check("assets.loaded", ok,
                  (f"every required asset with a file ({judged}) was fetched by the page during play"
                   if ok else "; ".join(
                       ([f"never fetched during play: {', '.join(unfetched)}"] if unfetched else [])
                       + ([f"{len(failed)} asset request(s) failed: {failed[0].get('url')}"]
                          if failed else []))),
                  DEVELOP,
                  measured={"fetched": sorted(set(fetched))[:40], "unfetched": unfetched,
                            "failed_requests": failed[:10], "no_file": unloadable,
                            "runtime_manifest_fetched": runtime is not None},
                  expected="every required asset's file (runtime manifest url/atlas) fetched with a 2xx/3xx",
                  assets=unfetched)


CHAIN = ("exists", "referenced", "loaded", "rendered", "visible")


def assets_runtime(wanted, records, rules, frames_by_project):
    """The asset runtime chain, per required asset: exists (a delivered, non-placeholder
    manifest item with a file) -> referenced (in the runtime manifest the page fetched) ->
    loaded (its file fetched during play) -> rendered (an entity the probe reported names it,
    render asset|composite) -> visible (that entity on screen, visible and at a readable size
    in the per-frame samples, and its box in a state frame is not the frame's background).
    The last two apply to assets of an entity role; the chain stops at the first link that
    fails. Route `assets` when any asset fails at `exists`, else `develop`."""
    asset_roles = set((rules.get("entities") or {}).get("asset_roles") or [])
    renders = set((rules.get("entities") or {}).get("asset_renders") or ["asset", "composite"])
    not_loaded = set((rules.get("assets") or {}).get("not_loaded_types") or [])
    bars = rules.get("visible") or {}
    runtime = next((r["runtime_assets"] for _p, _n, r in _all_records(records)
                    if isinstance(r.get("runtime_assets"), dict)), None)
    fetched = [r["url"] for _p, _n, rec in _all_records(records)
               for r in rec.get("asset_requests") or [] if isinstance(r, dict)
               and isinstance(r.get("url"), str) and r.get("status") is not None
               and 200 <= r["status"] < 400]
    # A counted requirement's drawings are runtime assets of their own (`pieces-3`), listed
    # as `variants` on the requirement's entry (`pieces`): an entity drawn with one is the
    # requirement rendered. The probe stays precise about which drawing it drew.
    parent = {}
    for entry_id, entry in ((runtime or {}).get("assets") or {}).items():
        for variant in (entry or {}).get("variants") or []:
            parent.setdefault(variant, entry_id)
    canon = lambda asset: parent.get(asset, asset)  # noqa: E731
    # What the probe said about each asset id: renders, largest on-screen share, and state
    # frames with the box of an entity drawn with it.
    rendered, largest, boxes = {}, {}, {}
    for project, tests in records.items():
        for eid, _role, asset, render, _has in _entity_views(tests):
            if asset:
                rendered.setdefault(canon(asset), set()).add(render)
        for record in tests.values():
            sampled = (record or {}).get("sampled") or {}
            vw, vh = sampled.get("viewport") or [1, 1]
            area = float(vw * vh) or 1.0
            for frame in sampled.get("frames") or []:
                for sample in frame:
                    if len(sample) < 9 or not sample[7]:
                        continue
                    _i, _r, vis, x, y, w, h = sample[:7]
                    if vis and x + w > 0 and y + h > 0 and x < vw and y < vh:
                        key = canon(sample[7])
                        largest[key] = max(largest.get(key, 0.0), w * h / area)
        for state, ui in _ui_states(tests):
            for e in ui.get("entities") or []:
                if isinstance(e, dict) and e.get("asset") and e.get("visible"):
                    boxes.setdefault(canon(e["asset"]), []).append(
                        (project, ui.get("frame"), [e.get("x"), e.get("y"), e.get("w"), e.get("h")],
                         ui.get("viewport")))
    chain, failures = {}, {}
    for asset_id, (req, item) in sorted(wanted.items()):
        role = (req or {}).get("role") or (item or {}).get("role")
        links = {}
        type_ = (item or {}).get("type") or (req or {}).get("type")
        paths = served_paths(item, runtime) if item else set()
        links["exists"] = bool(item) and not item.get("placeholder") and bool(item.get("files")) \
            and item.get("status") not in ("planned",)
        if type_ not in not_loaded:
            links["referenced"] = isinstance(runtime, dict) and asset_id in (runtime.get("assets") or {})
            links["loaded"] = bool(paths) and any(url.endswith("/assets/" + p)
                                                  for p in paths for url in fetched)
        if role in asset_roles:
            links["rendered"] = bool(rendered.get(asset_id, set()) & renders)
            share = largest.get(asset_id, 0.0)
            seen = []
            for project, frame_id, box, viewport in boxes.get(asset_id, []):
                differs = _Frames(frames_by_project.get(project)).differs(
                    frame_id, box, viewport, bars.get("min_pixel_delta", 24))
                if differs is not None:
                    seen.append(differs)
            links["visible"] = share >= bars.get("min_area_fraction", 0.002) and \
                any(d >= bars.get("min_changed_share", 0.1) for d in seen)
            links["visible_measured"] = {"largest_area_fraction": round(share, 4),
                                         "box_not_background": max(seen) if seen else None}
        failed_at = next((link for link in CHAIN if links.get(link) is False), None)
        chain[asset_id] = dict(links, role=role, failed_at=failed_at)
        if failed_at:
            failures[asset_id] = failed_at
    route = ASSETS if any(f == "exists" for f in failures.values()) else DEVELOP
    return _check("assets.runtime", bool(wanted) and not failures,
                  ("; ".join(f"{a}: fails at {f}" for a, f in sorted(failures.items())[:12])
                   + (f" (+{len(failures) - 12} more)" if len(failures) > 12 else ""))
                  if failures else (f"all {len(wanted)} required assets exist, are referenced, "
                                    "loaded, and - for entity assets - rendered and visible in play"
                                    if wanted else "no required asset in the design or manifest"),
                  route, measured=chain,
                  expected=" -> ".join(CHAIN) + " for every required asset (rendered and visible "
                           f"for roles {', '.join(sorted(asset_roles))})",
                  assets=sorted(failures))


def _readable(project, tests, rules, runtime):
    roles = set((rules.get("entities") or {}).get("readable_roles") or [])
    renders = set((rules.get("entities") or {}).get("asset_renders") or ["asset", "composite"])
    by_entity = {}
    for eid, role, asset, render, has in _entity_views(tests):
        if role not in roles or eid is None:
            continue
        seen = by_entity.setdefault((role, eid), {"assets": set(), "renders": set(), "reported": False})
        if asset:
            seen["assets"].add(asset)
        seen["renders"].add(render)
        seen["reported"] = seen["reported"] or has
    known = set(((runtime or {}).get("assets") or {})) if isinstance(runtime, dict) else None
    unassetted, unknown, primitive, unreported = [], [], [], []
    for (role, eid), seen in sorted(by_entity.items()):
        label = f"{eid} ({role})"
        if not seen["reported"]:
            unreported.append(label)
            continue
        if "primitive" in seen["renders"]:
            primitive.append(label)
        if not seen["assets"] or not (seen["renders"] - {None}) <= renders:
            unassetted.append(label)
        elif known is not None and not seen["assets"] <= known:
            unknown.append(f"{label}: {', '.join(sorted(seen['assets'] - known))}")
    return by_entity, roles, renders, unassetted, unknown, primitive, unreported


def _primitive_style(design):
    style = (((design or {}).get("build_spec") or {}).get("visual_identity") or {}).get("primitive_style")
    return style if isinstance(style, dict) else None


def assets_used(project, tests, wanted, rules, runtime, design=None):
    by_entity, roles, renders, unassetted, unknown, primitive, unreported = \
        _readable(project, tests, rules, runtime)
    style = _primitive_style(design)
    exempt = []
    if style:
        # The art direction is geometric: an entity drawn only as a primitive needs no asset.
        exempt = [label for label in unassetted if label in primitive]
        unassetted = [label for label in unassetted if label not in exempt]
    concerned = _requirement_ids_for_roles(wanted, {r for r, _ in by_entity} or roles)
    if not by_entity:
        return _check("assets.used", False, "no entity of a readable role ("
                      + ", ".join(sorted(roles)) + ") was reported by the probe", DEVELOP,
                      project=project, assets=concerned)
    bad = unreported + unassetted + unknown
    return _check("assets.used", not bad,
                  ("; ".join(([f"the probe reports no asset/render for {', '.join(unreported)}"]
                              if unreported else [])
                             + ([f"not drawn from an asset (render {'|'.join(sorted(renders))} "
                                 f"with an asset id): {', '.join(unassetted)}"] if unassetted else [])
                             + ([f"names an asset not in the runtime manifest: {'; '.join(unknown)}"]
                                if unknown else []))
                   if bad else f"all {len(by_entity)} readable entities are drawn from runtime assets"),
                  DEVELOP, project=project,
                  measured={"entities": len(by_entity), "unreported": unreported,
                            "not_from_asset": unassetted, "unknown_asset": unknown,
                            **({"exempt_primitive_style": exempt} if style else {})},
                  expected=f"every {', '.join(sorted(roles))} entity: asset set, render in {sorted(renders)}",
                  assets=concerned)


def scene_no_primitives(project, tests, wanted, rules, runtime, design):
    by_entity, roles, _renders, _u, _k, primitive, unreported = _readable(project, tests, rules, runtime)
    concerned = _requirement_ids_for_roles(wanted, {r for r, _ in by_entity} or roles)
    style = _primitive_style(design)
    if style:
        return _check("scene.no_primitives", not primitive,
                      ("exempt: the design's visual_identity.primitive_style allows primitives ("
                       f"{style.get('reason')}); "
                       + (f"drawn as primitives: {', '.join(primitive)}" if primitive else
                          "none was drawn as one")),
                      DEVELOP, project=project, required=False,
                      measured={"exempt": True, "reason": style.get("reason"), "primitive": primitive},
                      expected="exempt (visual_identity.primitive_style)")
    bad = primitive + unreported
    return _check("scene.no_primitives", bool(by_entity) and not bad,
                  ("no entity of a readable role was reported" if not by_entity else
                   "; ".join(([f"drawn as engine primitives: {', '.join(primitive)}"] if primitive else [])
                             + ([f"render not reported, so not shown to be other than a primitive: "
                                 f"{', '.join(unreported)}"] if unreported else []))
                   or f"none of {len(by_entity)} readable entities is drawn as a primitive"),
                  DEVELOP, project=project,
                  measured={"primitive": primitive, "unreported": unreported},
                  expected="no readable-role entity with render `primitive`", assets=concerned)


def _ui_states(tests):
    for name, record in tests.items():
        for state, ui in ((record or {}).get("ui") or {}).items():
            if isinstance(ui, dict):
                yield state, ui


def _min_target(design, rules):
    spec = (design or {}).get("build_spec") or {}
    design_px = (((spec.get("visual_identity") or {}).get("ui") or {}).get("min_target_px")
                 or (spec.get("responsive") or {}).get("min_touch_target_px") or 0)
    return max((rules.get("ui") or {}).get("min_target_px", 44), design_px)


def ui_targets(project, tests, design, rules):
    bar = _min_target(design, rules)
    small, measured = [], 0
    for state, ui in _ui_states(tests):
        controls = [(e.get("text") or e.get("tag"), e.get("box")) for e in ui.get("elements") or []]
        controls += [(e.get("id"), [e.get("x"), e.get("y"), e.get("w"), e.get("h")])
                     for e in ui.get("probe_ui") or []]
        for label, box in controls:
            if not box or len(box) < 4:
                continue
            measured += 1
            if box[2] < bar or box[3] < bar:
                small.append(f"{state}: {label!r} {box[2]}x{box[3]} px")
    if not measured:
        return _check("ui.targets", True, "no interactive DOM element or probe ui entity was on "
                      "screen to measure", DEVELOP, project=project, required=False,
                      status="WARNING", expected=f">= {bar} px")
    return _check("ui.targets", not small,
                  f"{len(small)} target(s) under {bar} px: {'; '.join(sorted(set(small))[:6])}"
                  if small else f"all {measured} measured targets are at least {bar} px",
                  DEVELOP, project=project, measured={"small": sorted(set(small))[:20], "measured": measured},
                  expected=f">= {bar} x {bar} CSS px")


def ui_overlap(project, tests, rules):
    floor = (rules.get("ui") or {}).get("min_overlap_px", 16)
    found = []
    for state, ui in _ui_states(tests):
        elements, texts = ui.get("elements") or [], ui.get("texts") or []
        for o in ui.get("overlaps") or []:
            if (o.get("area_px") or 0) < floor:
                continue
            a = elements[o["a"]] if o.get("a") is not None and o["a"] < len(elements) else {}
            if o.get("kind") == "text":
                b = texts[o["text"]] if o.get("text") is not None and o["text"] < len(texts) else {}
            else:
                b = elements[o["b"]] if o.get("b") is not None and o["b"] < len(elements) else {}
            found.append(f"{state}: {a.get('text') or a.get('tag')!r} over "
                         f"{b.get('text') or b.get('tag')!r} ({o.get('area_px')} px)")
    return _check("ui.overlap", not found,
                  f"{len(found)} overlap(s): {'; '.join(found[:5])}" if found else
                  "no interactive element overlaps another or the HUD text",
                  DEVELOP, project=project, measured=found[:20], expected=f"< {floor} px shared area")


def ui_text(project, tests, rules, frames):
    bars = rules.get("ui") or {}
    min_font = bars.get("min_font_px", 12)
    low, small, undetermined, measured = [], [], 0, 0
    for state, ui in _ui_states(tests):
        items = [e for e in ui.get("elements") or [] if (e.get("text") or "").strip()]
        items += [t for t in ui.get("texts") or [] if (t.get("text") or "").strip()]
        for item in items:
            label = f"{state}: {item.get('text')[:30]!r}"
            font = item.get("font_px") or 0
            if font < min_font:
                small.append(f"{label} {font} px")
            color = item.get("color")
            background = item.get("background") or frames.background(
                ui.get("frame"), item.get("box"), ui.get("viewport"))
            if not color or not background:
                undetermined += 1
                continue
            measured += 1
            large = font >= bars.get("large_px", 24) or (
                font >= bars.get("large_bold_px", 18.66) and (item.get("font_weight") or 400) >= 700)
            need = bars.get("min_contrast_large", 3.0) if large else bars.get("min_contrast", 4.5)
            ratio = contrast_ratio(_over(color, background), background)
            if ratio < need:
                low.append(f"{label} {ratio}:1 < {need}:1")
    bad = sorted(set(low)) + sorted(set(small))
    if not measured and not small:
        return _check("ui.text", True, "no DOM text was on screen to measure", DEVELOP,
                      project=project, required=False, status="WARNING",
                      measured={"undetermined": undetermined})
    return _check("ui.text", not bad,
                  f"{len(bad)} text problem(s): {'; '.join(bad[:5])}" if bad else
                  f"all {measured} measured texts meet contrast and size",
                  DEVELOP, project=project,
                  measured={"low_contrast": sorted(set(low))[:20], "too_small": sorted(set(small))[:20],
                            "measured": measured, "undetermined": undetermined},
                  expected={"contrast": f">= {bars.get('min_contrast', 4.5)}:1 (large text "
                                        f">= {bars.get('min_contrast_large', 3.0)}:1)",
                            "font_px": f">= {min_font}"})


def ui_styled(project, tests):
    default = []
    for state, ui in _ui_states(tests):
        for e in ui.get("elements") or []:
            if e.get("ua_default"):
                default.append(f"{state}: <{e.get('tag')}> {(e.get('text') or '')[:30]!r}")
    return _check("ui.styled", not default,
                  f"{len(default)} control(s) in the browser's default style: {'; '.join(sorted(set(default))[:5])}"
                  if default else "no control is drawn in the browser's default style",
                  DEVELOP, project=project, measured=sorted(set(default))[:20],
                  expected="every control's computed style differs from the user-agent default")


def ui_states(project, tests, design, rules):
    bars = rules.get("ui") or {}
    wanted = list(bars.get("required_states") or ["lost", "retry"])
    ex = ((design or {}).get("build_spec") or {}).get("experience") or {}
    if "win" in ex:
        wanted.append(bars.get("win_state", "won"))
    seen = {state: ui.get("frame") for state, ui in _ui_states(tests)}
    missing = [s for s in wanted if s not in seen]
    return _check("ui.states", not missing,
                  f"screens never seen: {', '.join(missing)}" if missing else
                  f"seen: {', '.join(wanted)}",
                  DEVELOP, project=project, measured=sorted(seen), expected=wanted,
                  frames=[seen[s] for s in wanted if seen.get(s)])


def judge(records, manifest, design, rules, frames_dirs):
    """Checks for a build: global asset checks, then each viewport's."""
    wanted = required_assets(manifest, design, rules)
    runtime = next((r["runtime_assets"] for _p, _n, r in _all_records(records)
                    if isinstance(r.get("runtime_assets"), dict)), None)
    checks = [assets_present(wanted), assets_loaded(wanted, records, rules),
              assets_runtime(wanted, records, rules, frames_dirs)]
    for project in sorted(records):
        tests = records[project]
        frames = _Frames(frames_dirs.get(project))
        checks.append(assets_used(project, tests, wanted, rules, runtime, design))
        checks.append(scene_no_primitives(project, tests, wanted, rules, runtime, design))
        if project == "mobile":
            checks.append(ui_targets(project, tests, design, rules))
        checks.append(ui_overlap(project, tests, rules))
        checks.append(ui_text(project, tests, rules, frames))
        checks.append(ui_styled(project, tests))
        checks.append(ui_states(project, tests, design, rules))
    return checks
