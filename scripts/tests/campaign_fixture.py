"""A shipped campaign for publish tests: release/<id>/listing/ as the release step leaves it.

    listing/listing.json                         the canonical store-listing (capture record:
                                                 commit, bot, browser; screenshots, branding,
                                                 trailer with their sha256)
    listing/screenshots/*.png                    the canonical captures
    listing/branding/icon-512x512.png            the canonical icon
    listing/platforms/<pid>/listing.json         the platform's rendition: files sized for the
    listing/platforms/<pid>/{icon,cover,shot-N}  portal, texts per locale

Every image has real, varied pixels (never a placeholder's flat colour), so the media check
judges what the test changes and nothing else.
"""

import hashlib
import json
import os
import struct
import zlib

PACKAGE_DIR = "store-listing/1-1/package"
COMMIT = "a" * 40


def png_bytes(width, height, seed=0):
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            row.extend(((x * 7 + seed * 31) % 256, (y * 5 + x * 3 + seed) % 256,
                        (x * y + seed * 13) % 256, 255))
        rows.append(bytes(row))

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def placeholder_png(width, height, colour=(200, 80, 40)):
    """The assets step's procedural placeholder: flat colour, 1px border of half its value."""
    from wgf_assets import encoders
    return encoders.png(width, height, colour)


def sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)


def _record(file_id, rel, data, fmt, width=None, height=None, **extra):
    record = {"id": file_id, "path": f"{PACKAGE_DIR}/{rel}", "sha256": sha(data),
              "bytes": len(data), "format": fmt}
    if width:
        record.update(width=width, height=height)
    record.update({k: v for k, v in extra.items() if v is not None})
    return record


def write_campaign(release_dir, platform_id="generic-web", *, text=None, commit=COMMIT,
                   listing_hash=None, shots=2, shot_size=(64, 36), icon=True, cover=True,
                   trailer=None, rendition_extra=(), canonical_extra=None, age_rating=None):
    """Write the shipped campaign; returns (canonical, rendition) as written.

    `trailer`: None, or bytes of a recorded video (container from `trailer_format`).
    `rendition_extra`: more rendition file records [(record kwargs, bytes)] (rel path in
    `rel`)."""
    base = os.path.join(release_dir, "listing")
    text = text or {"en": {"title": "Fixture Game", "short_description": "Merge towers.",
                           "long_description": "Merge matching towers.", "features": [],
                           "tags": ["merge"]}}
    canonical_shots, files = [], []
    for n in range(1, shots + 1):
        data = png_bytes(shot_size[0] * 2, shot_size[1] * 2, seed=n)
        rel = f"screenshots/landscape-{n:02d}-play.png"
        _write(os.path.join(base, *rel.split("/")), data)
        canonical_shots.append(_record(f"landscape-{n:02d}-play", rel, data, "png",
                                       shot_size[0] * 2, shot_size[1] * 2, scene="play",
                                       viewport="landscape", state="playing"))
        small = png_bytes(shot_size[0], shot_size[1], seed=n + 50)
        rel = f"platforms/{platform_id}/shot-{n}.png"
        _write(os.path.join(base, *rel.split("/")), small)
        files.append(_record(f"screenshot-{n:02d}", rel, small, "png", shot_size[0], shot_size[1],
                             kind="screenshot", source=f"landscape-{n:02d}-play",
                             requirement="screenshots"))
    branding = []
    icon_master = png_bytes(32, 32, seed=7)
    _write(os.path.join(base, "branding", "icon-512x512.png"), icon_master)
    branding.append(_record("icon-512x512", "branding/icon-512x512.png", icon_master, "png", 32, 32,
                            kind="icon", source="player"))
    if icon:
        data = png_bytes(16, 16, seed=8)
        _write(os.path.join(base, "platforms", platform_id, "icon.png"), data)
        files.append(_record("icon-16x16", f"platforms/{platform_id}/icon.png", data, "png", 16, 16,
                             kind="icon", source="icon-512x512", requirement="icon"))
    if cover:
        data = png_bytes(32, 18, seed=9)
        _write(os.path.join(base, "platforms", platform_id, "cover.png"), data)
        files.append(_record("cover-32x18", f"platforms/{platform_id}/cover.png", data, "png", 32, 18,
                             kind="thumbnail", source="thumbnail-1280x720", requirement="cover-1"))
    trailer_record = {"status": "none", "reason": "not recorded in this fixture"}
    if trailer is not None:
        data, fmt, width, height, duration = trailer
        _write(os.path.join(base, "trailer", f"trailer.{fmt}"), data)
        trailer_record = {"status": "recorded", "path": f"{PACKAGE_DIR}/trailer/trailer.{fmt}",
                          "sha256": sha(data), "bytes": len(data), "container": fmt,
                          "width": width, "height": height, "duration_s": duration,
                          "trimmed": True, "leading_ms": 0}
        _write(os.path.join(base, "platforms", platform_id, f"trailer.{fmt}"), data)
        files.append(_record("trailer", f"platforms/{platform_id}/trailer.{fmt}", data, fmt,
                             width, height, kind="trailer", source="trailer", requirement="video"))
    for kwargs, data in rendition_extra:
        kwargs = dict(kwargs)
        rel = kwargs.pop("rel")
        _write(os.path.join(base, *rel.split("/")), data)
        files.append(_record(kwargs.pop("id"), rel, data, kwargs.pop("format", "png"), **kwargs))
    rendition = {"platform_id": platform_id, "profile_version": "2.1.0", "role": "required",
                 "spec_status": "verified", "dir": f"{PACKAGE_DIR}/platforms/{platform_id}",
                 "files": files, "text": text, "locales_required": sorted(text)[:1],
                 "age_rating": age_rating, "unmet": []}
    canonical = {
        "provenance": {"artifact_type": "store-listing",
                       "content_hash": listing_hash or "sha256:" + "c" * 64},
        "title_id": "fixture-game", "commit": commit, "measurement_class": "automation-bot",
        "status": "complete", "package_dir": PACKAGE_DIR,
        "copy": {"locales": text}, "branding": {"method": "browser-composed", "items": branding},
        "screenshots": canonical_shots, "trailer": trailer_record,
        "platforms": [dict(rendition, listing=f"{PACKAGE_DIR}/platforms/{platform_id}/listing.json")],
        "capture": {"kind": "browser", "attempts": 1}, "problems": [],
    }
    canonical.update(canonical_extra or {})
    os.makedirs(os.path.join(base, "platforms", platform_id), exist_ok=True)
    with open(os.path.join(base, "listing.json"), "w", encoding="utf-8") as handle:
        json.dump(canonical, handle, ensure_ascii=False)
    with open(os.path.join(base, "platforms", platform_id, "listing.json"), "w",
              encoding="utf-8") as handle:
        json.dump(rendition, handle, ensure_ascii=False)
    return canonical, rendition
