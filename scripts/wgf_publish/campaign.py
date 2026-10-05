"""The campaign package a portal is filled from: the store listing the release shipped.

Every value a publication profile's intent may name under `listing.` resolves here, from the
store-listing package the release step copied beside its archives (release/<id>/listing/):
the canonical package's own listing.json (what was captured, from which commit and bundle)
and the platform's rendition (listing/platforms/<pid>/listing.json: the files sized for that
portal, the texts cut to its limits). A portal adapter never invents campaign content: a
value the package does not hold is None, and the executor refuses a required field with no
value.

    listing.text.<locale>.<field>    title, subtitle, short_description, long_description |
                                     description, how_to_play | instructions | controls,
                                     feature_bullets | features, tags, categories, promo
                                     (lists joined); keywords / seo_description only where
                                     the copy has them
    listing.<field>                  the same in the primary locale, then any other
    listing.media.<kind>             icon, logo, cover | thumbnail | thumbnails, hero |
                                     hero_image | promo, screenshots, trailer | video |
                                     gameplay_video; `_landscape` / `_portrait` (or
                                     `horizontal_` / `vertical_`) keep one orientation
    listing.media.<locale>.<kind>    the files a locale has of its own, else the shared ones

The rendition's files are used whenever the rendition has the kind (they are what the
portal's profile asked for); the canonical package's only when it has none. The age rating
and content declarations are never a value: they are a person's act on the portal
(`surfaced` reports what the listing states, for the person).

`check_media` is the per-portal media check run before anything is uploaded (the submit
step's prepare; listing-validation runs its provenance and portal-profile part): sizes,
aspect, file type and size, count, per-locale media, video container, length, size and
orientation - from the platform profile's `store_listing` block and the publication
profile's `fields` and upload intents (`accept`, `multiple`). A limit stated as null is
UNKNOWN, reported and never passed as verified. Every screenshot and video must trace to
the capture of the verified build (the canonical listing's commit, the capture record of
the screenshot or the recording, its sha256); a file without that provenance, one captured
from another commit than the shipped build's, or an asset-pipeline placeholder is refused:
`invalid-media`.

`campaign_hash` is one content hash of what reaches the portal: the platform's rendition
texts and the bytes of every file the campaign holds, with the store-listing it came from.
The step records it on the platform-publication (`submission.campaign_hash`) and in the
portal registry (`campaign_hash`), and refuses a shipped listing that is not the
store-listing G6 pinned.
"""

import hashlib
import json
import os
import re

from wgf_listing import media as listing_media
from wgf_listing import platforms as listing_platforms

__all__ = ["Campaign", "load", "from_listing", "text_value", "resolve", "check_media",
           "failures", "surfaced", "MEDIA_KINDS", "TEXT_FIELDS", "PERSON_FIELDS",
           "INVALID_MEDIA"]

INVALID_MEDIA = "invalid-media"
LISTING_DIR = "listing"
CANONICAL = "listing.json"

# Where a listing field's text is in a localeCopy; first non-empty wins.
TEXT_FIELDS = {
    "description": ("long_description", "description", "short_description"),
    "long_description": ("long_description",),
    "short_description": ("short_description",),
    "instructions": ("controls", "instructions"),
    "how_to_play": ("controls", "how_to_play"),
    "controls": ("controls",),
    "feature_bullets": ("features",),
    "features": ("features",),
    "keywords": ("keywords",),
    "seo_description": ("seo_description",),
}
# A person's act on the portal, never filled by automation (reported by `surfaced`).
PERSON_FIELDS = ("age_rating", "content_rating", "content_descriptors", "declarations")

# listing.media.<name> -> the file kinds it takes, in order of preference.
MEDIA_KINDS = {
    "icon": ("icon",), "maskable_icon": ("icon",), "logo": ("logo",),
    "cover": ("thumbnail", "promo"), "thumbnail": ("thumbnail", "promo"),
    "thumbnails": ("thumbnail", "promo"), "covers": ("thumbnail", "promo"),
    "hero": ("promo", "thumbnail"), "hero_image": ("promo", "thumbnail"), "promo": ("promo",),
    "screenshot": ("screenshot",), "screenshots": ("screenshot",),
    "trailer": ("trailer",), "video": ("trailer",), "gameplay_video": ("trailer",),
}
_ORIENTED = re.compile(r"^(?:(horizontal|vertical)_)?(.+?)(?:_(landscape|portrait))?$")
_IMAGE_KINDS = ("icon", "logo", "thumbnail", "promo", "screenshot")
_PLACEHOLDER_NAME = re.compile(r"\.placeholder\.", re.I)
_SHA = re.compile(r"^[0-9a-f]{7,40}$")


def _read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _clean(value):
    if isinstance(value, list):
        items = [(v.get("text") if isinstance(v, dict) else v) for v in value]
        items = [str(v).strip() for v in items if v is not None and str(v).strip()]
        return items or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    return value.strip() if isinstance(value, str) and value.strip() else None


def text_value(copy, field):
    """The text of `field` in one locale's copy, or None. Lists are joined: bullets one per
    line, tags and categories with commas. A person's field is never a value."""
    if field in PERSON_FIELDS:
        return None
    for key in TEXT_FIELDS.get(field, (field,)):
        value = _clean((copy or {}).get(key))
        if isinstance(value, list):
            return "\n".join(value) if key == "features" else ", ".join(value)
        if value:
            return value
    return None


def _orientation(record):
    w, h = record.get("width"), record.get("height")
    if not w or not h:
        return None
    return "landscape" if w >= h else "portrait"


def _media_name(name):
    """(kinds, orientation) for a listing.media name, or (None, None)."""
    match = _ORIENTED.match(name or "")
    if not match:
        return None, None
    lead, base, tail = match.groups()
    kinds = MEDIA_KINDS.get(base) or MEDIA_KINDS.get(name)
    if kinds is None:
        return None, None
    orientation = tail or {"horizontal": "landscape", "vertical": "portrait"}.get(lead)
    return kinds, orientation


class Campaign:
    """One platform's campaign: the canonical listing and the platform's rendition, with the
    directory their files are in (`base`: the shipped listing/ directory, or a run's package
    directory) and the package directory their recorded paths start with."""

    def __init__(self, platform_id, canonical, rendition, base, package_dir=None):
        self.platform_id = platform_id
        self.canonical = canonical if isinstance(canonical, dict) else None
        self.rendition = rendition if isinstance(rendition, dict) else None
        self.base = base
        self.package_dir = (package_dir or (self.canonical or {}).get("package_dir") or "").rstrip("/")

    # -- files -------------------------------------------------------------------------

    def path(self, record):
        """The file a record names, under `base`."""
        rel = str((record or {}).get("path") or "")
        marker = self.package_dir + "/" if self.package_dir else None
        if marker and rel.startswith(marker):
            rel = rel[len(marker):]
        elif not marker:
            for top in ("platforms/", "screenshots/", "branding/", "trailer/"):
                at = rel.find(top)
                if at >= 0:
                    rel = rel[at:]
                    break
        return os.path.join(self.base, *[p for p in rel.split("/") if p])

    def rendition_files(self):
        return [f for f in (self.rendition or {}).get("files") or [] if isinstance(f, dict)]

    def canonical_files(self):
        canonical = self.canonical or {}
        out = [dict(f, kind=f.get("kind") or "screenshot") for f in canonical.get("screenshots") or []]
        out += [f for f in (canonical.get("branding") or {}).get("items") or []]
        trailer = canonical.get("trailer") or {}
        if trailer.get("status") == "recorded" and trailer.get("path"):
            out.append({"id": "trailer", "kind": "trailer", "path": trailer["path"],
                        "sha256": trailer.get("sha256"), "bytes": trailer.get("bytes"),
                        "format": trailer.get("container"), "width": trailer.get("width"),
                        "height": trailer.get("height")})
        return [f for f in out if isinstance(f, dict)]

    def media_records(self, name, locale=None):
        """[(record, origin)] for listing.media.<name>: the rendition's when it has the kind,
        else the canonical package's; a locale's own files when it has any, else the shared
        ones (records with no locale). With no locale: the shared ones, else every locale's."""
        found, origin = self.all_media_records(name)
        own = [f for f in found if locale and f.get("locale") == locale]
        shared = [f for f in found if not f.get("locale")]
        chosen = (own or shared) if locale else (shared or found)
        return [(f, origin) for f in chosen]

    def all_media_records(self, name):
        """([record], origin) of listing.media.<name> in every locale. A name that is one of
        the platform's own image requirements (its store_listing block's id, e.g. CrazyGames'
        `cover-2x3`) names exactly the rendition files rendered for it."""
        exact = [f for f in self.rendition_files() if f.get("requirement") == name]
        if exact:
            return exact, "rendition"
        kinds, orientation = _media_name(name)
        for origin, files in (("rendition", self.rendition_files()),
                              ("canonical", self.canonical_files())):
            for kind in kinds or ():
                found = [f for f in files if f.get("kind") == kind]
                if orientation:
                    found = [f for f in found if _orientation(f) in (orientation, None)]
                if found:
                    return found, origin
        return [], None

    def media(self, name, locale=None):
        return [self.path(r) for r, _ in self.media_records(name, locale)]

    # -- texts -------------------------------------------------------------------------

    @property
    def texts(self):
        """{locale: copy}: the rendition's, else the canonical copy's."""
        text = (self.rendition or {}).get("text")
        if isinstance(text, dict) and text:
            return {str(k): v for k, v in text.items() if isinstance(v, dict)}
        locales = ((self.canonical or {}).get("copy") or {}).get("locales") or {}
        return {str(k): v for k, v in locales.items() if isinstance(v, dict)}

    def required_locales(self, platform_profile=None):
        out = list((self.rendition or {}).get("locales_required") or [])
        for locale in listing_platforms.locales_for(platform_profile or {}):
            if locale not in out:
                out.append(locale)
        return out

    # -- the hash ----------------------------------------------------------------------

    def campaign_hash(self):
        """sha256 of the texts and the bytes of every file this platform's campaign holds,
        with the store-listing they came from (canonical JSON)."""
        files = []
        seen = set()
        for record in self.rendition_files() + self.canonical_files():
            path = self.path(record)
            if path in seen:
                continue
            seen.add(path)
            digest = listing_media.sha256_of(path) if os.path.isfile(path) else None
            files.append([str(record.get("kind") or ""), str(record.get("id") or ""),
                          str(record.get("locale") or ""), digest])
        body = {"platform_id": self.platform_id,
                "store_listing": ((self.canonical or {}).get("provenance") or {}).get("content_hash"),
                "text": self.texts, "age_rating": (self.rendition or {}).get("age_rating"),
                "files": sorted(files)}
        text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

    @property
    def listing_hash(self):
        """The content hash the shipped canonical listing carries (the store-listing's)."""
        return ((self.canonical or {}).get("provenance") or {}).get("content_hash")


def load(release_dir, platform_id):
    """The campaign the release shipped for `platform_id`, or None when it shipped none."""
    if not release_dir:
        return None
    base = os.path.join(release_dir, LISTING_DIR)
    canonical = _read(os.path.join(base, CANONICAL))
    rendition = _read(os.path.join(base, "platforms", str(platform_id), CANONICAL))
    if canonical is None and rendition is None:
        return None
    if rendition is None and canonical is not None:
        rendition = next((r for r in canonical.get("platforms") or []
                          if isinstance(r, dict) and r.get("platform_id") == platform_id), None)
    return Campaign(platform_id, canonical, rendition, base)


def from_listing(listing, run_dir, platform_id):
    """The campaign of a store-listing artifact still in its run (listing-validation)."""
    rendition = next((r for r in (listing or {}).get("platforms") or []
                      if isinstance(r, dict) and r.get("platform_id") == platform_id), None)
    package_dir = (listing or {}).get("package_dir") or ""
    base = os.path.join(run_dir, *[p for p in package_dir.split("/") if p])
    return Campaign(platform_id, listing, rendition, base, package_dir)


def resolve(campaign, path, locale=None, primary=None, texts=None):
    """("text", str) | ("files", [abs path]) | (None, None) for a `listing.` path. `texts`
    ({locale: copy}, the rendition's as the step read it) stands for the campaign's texts
    when given; with no campaign, media come from nowhere."""
    parts = path.split(".")
    if parts[0] != "listing" or len(parts) < 2:
        return None, None
    if parts[1] == "media":
        if campaign is None or len(parts) not in (3, 4):
            return None, None
        where, name = (parts[2], parts[3]) if len(parts) == 4 else (locale, parts[2])
        files = campaign.media(name, where)
        return ("files", files) if files else (None, None)
    texts = texts or (campaign.texts if campaign is not None else {})
    if parts[1] == "text" and len(parts) == 4:
        order, field = [parts[2]], parts[3]
    elif len(parts) == 2:
        field = parts[1]
        order = []
        for where in [primary or locale, locale] + list(texts):
            if where is not None and where not in order:
                order.append(where)
    else:
        return None, None
    for where in order:
        value = text_value(texts.get(where), field)
        if value:
            return "text", value
    return None, None


def surfaced(campaign):
    """What a person must state on the portal that the listing has a value for (the age
    rating): shown to the person, never filled."""
    if campaign is None:
        return {}
    rating = (campaign.rendition or {}).get("age_rating") or next(
        (t.get("age_rating") for t in campaign.texts.values() if t.get("age_rating")), None)
    return {"age_rating": rating} if rating else {}


# -- the media check -----------------------------------------------------------------------

def _finding(findings, status, code, subject, message):
    findings.append({"status": status, "code": code, "subject": subject, "message": message})


def _formats(values):
    if values is None:
        return None
    out = []
    for v in values:
        v = str(v).lower().lstrip(".").split("/")[-1]
        out.append({"jpeg": "jpg", "quicktime": "mov"}.get(v, v))
    return out


def _aspect_ok(width, height, aspect):
    try:
        a, b = (int(x) for x in str(aspect).split(":"))
    except ValueError:
        return True
    return abs(width / height - a / b) < 0.02


def looks_like_placeholder(path, record=None):
    """True for an asset pipeline placeholder: a `<id>.placeholder.<ext>` name anywhere in
    the file's name or record, or the procedural backend's image (one flat colour inside a
    1px border of half its value, optionally a checkerboard of it)."""
    names = [os.path.basename(path or "")] + [str((record or {}).get(k) or "")
                                              for k in ("path", "source", "id")]
    if any(_PLACEHOLDER_NAME.search(n) for n in names):
        return True
    if not str(path).lower().endswith(".png") or not os.path.isfile(path):
        return False
    try:
        from wgf_listing import imaging
        image = imaging.read_png(path)
    except Exception:  # noqa: BLE001 - an unreadable PNG is judged elsewhere
        return False
    w, h = image.width, image.height
    if w < 3 or h < 3:
        return False
    px = image.pixels

    def at(x, y):
        i = (y * w + x) * 4
        return tuple(px[i:i + 4])

    inner = at(w // 2, h // 2)
    border = at(0, 0)
    if border[:3] != tuple(c // 2 for c in inner[:3]):
        return False
    colours = set()
    step_x, step_y = max(1, w // 64), max(1, h // 64)
    for y in range(0, h, step_y):
        for x in range(0, w, step_x):
            colours.add(at(x, y))
            if len(colours) > 3:
                return False
    return True


def _capture_problems(campaign, shipped_commit, findings):
    """The canonical listing as a capture record: of a commit, by the bot, from a browser."""
    canonical = campaign.canonical
    if canonical is None:
        _finding(findings, "FAIL", "no-provenance", "capture",
                 "the campaign has no canonical listing.json: nothing records which build its "
                 "screenshots and video were captured from")
        return False
    commit = str(canonical.get("commit") or "")
    ok = True
    if not _SHA.match(commit) or set(commit) == {"0"}:
        _finding(findings, "FAIL", "no-provenance", "capture",
                 f"the listing names no captured commit ({commit[:12] or 'none'})")
        ok = False
    if canonical.get("measurement_class") != "automation-bot" or \
            (canonical.get("capture") or {}).get("kind") != "browser":
        _finding(findings, "FAIL", "no-provenance", "capture",
                 "the listing was not captured by the bot from the running build "
                 f"(measurement_class {canonical.get('measurement_class')}, capture "
                 f"{(canonical.get('capture') or {}).get('kind')})")
        ok = False
    if shipped_commit and ok:
        a, b = commit, str(shipped_commit)
        same = a.startswith(b) or b.startswith(a) if min(len(a), len(b)) >= 7 else a == b
        if not same:
            _finding(findings, "FAIL", "capture-commit-mismatch", "capture",
                     f"the screenshots and video were captured from {commit[:12]}, the shipped "
                     f"build is {b[:12]}: they are not of this build")
            ok = False
    return ok


def _provenance(campaign, record, origin, findings):
    """A screenshot or video traces to its capture record, byte for byte."""
    rid = record.get("id")
    kind = record.get("kind")
    canonical = campaign.canonical or {}
    if origin == "canonical":
        source = record
    elif kind == "screenshot":
        source = next((s for s in canonical.get("screenshots") or []
                       if s.get("id") == record.get("source")), None)
    else:
        trailer = canonical.get("trailer") or {}
        source = None
        if trailer.get("status") == "recorded":
            source = {"path": trailer.get("path"), "sha256": trailer.get("sha256")}
            digest = listing_media.sha256_of(campaign.path(record)) \
                if os.path.isfile(campaign.path(record)) else None
            derived = [d for d in trailer.get("derived") or [] if d.get("sha256") == digest]
            if derived:
                source = derived[0]
    if source is None:
        _finding(findings, "FAIL", "no-provenance", rid,
                 f"{rid}: no capture record of the verified build names its source "
                 f"({record.get('source') or 'none'})")
        return
    path = campaign.path(source)
    if not os.path.isfile(path) or listing_media.sha256_of(path) != source.get("sha256"):
        _finding(findings, "FAIL", "no-provenance", rid,
                 f"{rid}: its capture record's file ({source.get('path')}) is missing or not "
                 f"the bytes captured")


def _check_files(campaign, name, records, limits, findings, *, video=False):
    """Type, size, dimensions, aspect, orientation, duration of each file against `limits`
    (None: not stated, UNKNOWN)."""
    for record, _ in records:
        path = campaign.path(record)
        rid = record.get("id")
        info = listing_media.describe(path)
        fmt = info.get("format")
        formats = limits.get("formats")
        if formats is not None and fmt not in formats:
            _finding(findings, "FAIL", "media-format", rid,
                     f"{name}: {rid} is {fmt}, the portal takes {'/'.join(formats)}")
        max_bytes = limits.get("max_bytes")
        if max_bytes is not None and info["bytes"] > max_bytes:
            _finding(findings, "FAIL", "media-too-large", rid,
                     f"{name}: {rid} is {info['bytes']} bytes, over {max_bytes}")
        width, height = info.get("width"), info.get("height")
        sizes = limits.get("sizes")
        if sizes and (width, height) not in [tuple(s) for s in sizes]:
            _finding(findings, "FAIL", "media-size", rid,
                     f"{name}: {rid} is {width}x{height}, the portal takes "
                     + ", ".join(f"{a}x{b}" for a, b in sizes))
        if limits.get("aspect") and width and height and not _aspect_ok(width, height, limits["aspect"]):
            _finding(findings, "FAIL", "media-aspect", rid,
                     f"{name}: {rid} is {width}x{height}, not {limits['aspect']}")
        for key, op in (("min_width", "<"), ("min_height", "<")):
            bound = limits.get(key)
            value = width if key == "min_width" else height
            if bound is not None and value is not None and value < bound:
                _finding(findings, "FAIL", "media-size", rid,
                         f"{name}: {rid} is {value} px {'wide' if key == 'min_width' else 'high'} "
                         f"{op} {bound}")
        orientation = limits.get("orientation")
        if orientation and width and height:
            actual = "landscape" if width >= height else "portrait"
            if actual not in orientation:
                _finding(findings, "FAIL", "video-orientation" if video else "media-orientation",
                         rid, f"{name}: {rid} is {actual}, the portal takes "
                              f"{'/'.join(orientation)}")
        if video:
            duration = info.get("duration_s")
            if duration is None:
                duration = ((campaign.canonical or {}).get("trailer") or {}).get("duration_s")
            for key in ("min_seconds", "max_seconds"):
                bound = limits.get(key)
                if bound is None:
                    continue
                if duration is None:
                    _finding(findings, "FAIL", "video-duration", rid,
                             f"{name}: {rid} has no measurable length")
                elif (key == "max_seconds" and duration > bound) or \
                        (key == "min_seconds" and duration < bound):
                    _finding(findings, "FAIL", "video-duration", rid,
                             f"{name}: {rid} runs {duration} s, "
                             f"{'over' if key == 'max_seconds' else 'under'} {bound} s")


def _unknown(findings, name, limits, keys):
    missing = [k for k in keys if limits.get(k) is None]
    if missing:
        _finding(findings, "UNKNOWN", "limit-unknown", name,
                 f"{name}: the profile states no {', '.join(missing)}: not verified")


def _count(findings, name, n, minimum=None, maximum=None):
    if minimum is not None and n < minimum:
        _finding(findings, "FAIL", "media-count", name, f"{name}: {n} file(s), the portal asks "
                                                        f"for at least {minimum}")
    if maximum is not None and n > maximum:
        _finding(findings, "FAIL", "media-count", name, f"{name}: {n} file(s), the portal takes "
                                                        f"at most {maximum}")


def _publication_media(publication_profile):
    """[(name, field or {}, intent or {})]: the media the publication profile's fields and
    upload intents name."""
    submission = (publication_profile or {}).get("submission") or {}
    out = {}
    for intent in submission.get("flow") or []:
        value = str(intent.get("value") or "")
        if intent.get("action") == "upload" and value.startswith("listing.media."):
            name = value.split(".")[-1]
            out.setdefault(name, [{}, {}])[1] = intent
    for field_name, field in (submission.get("fields") or {}).items():
        if not isinstance(field, dict) or field.get("human"):
            continue
        listing = str(field.get("listing") or "")
        name = listing.split(".")[-1] if listing.startswith("listing.media.") else field_name
        if name in ("horizontal_video",):
            name = "trailer_landscape"
        elif name in ("vertical_video",):
            name = "trailer_portrait"
        if _media_name(name)[0] is None:
            continue
        out.setdefault(name, [{}, {}])[0] = field
    return [(name, f, i) for name, (f, i) in out.items()]


def check_media(campaign, platform_profile=None, publication_profile=None, *, reference=None,
                shipped_commit=None, locales=None, profile_limits=True):
    """[{status: FAIL | UNKNOWN, code, subject, message}] for the media this platform's
    campaign would upload. `profile_limits` False leaves out the platform profile's own
    size/format/count limits (listing-validation judges those itself)."""
    findings = []
    if campaign is None:
        return findings
    used = []  # (name, records)
    reqs = listing_platforms.requirements(platform_profile or {}, reference or {}) \
        if platform_profile is not None else []
    # -- the platform profile's store_listing block
    for req in reqs:
        kind = req["kind"]
        if kind == "image":
            if req.get("required") is False:
                continue
            records = [(f, "rendition") for f in campaign.rendition_files()
                       if f.get("requirement") == req["image_id"]]
            used.append((req["image_id"], records))
            if not profile_limits:
                continue
            if not records:
                if req.get("required"):
                    _finding(findings, "FAIL", "media-missing", req["image_id"],
                             f"{req['image_id']}: the portal requires it and the campaign has none")
                continue
            limits = {"formats": _formats(req.get("formats")), "sizes": req.get("sizes"),
                      "aspect": req.get("aspect"),
                      "max_bytes": req["max_kb"] * 1024 if req.get("max_kb") else None}
            _check_files(campaign, req["image_id"], records, limits, findings)
            _unknown(findings, req["image_id"], {**limits, "sizes": limits["sizes"] or None},
                     ("sizes", "formats", "max_bytes"))
        elif kind == "screenshots":
            if req.get("required") is False:
                continue
            records = campaign.media_records("screenshots")
            used.append(("screenshots", records))
            if not profile_limits:
                continue
            _count(findings, "screenshots", len(records), req.get("min"), req.get("max"))
            limits = {"formats": _formats(req.get("formats")), "sizes": req.get("sizes"),
                      "aspect": req.get("aspect"), "orientation": req.get("orientation"),
                      "max_bytes": req["max_kb"] * 1024 if req.get("max_kb") else None}
            _check_files(campaign, "screenshots", records, limits, findings)
            _unknown(findings, "screenshots", {**limits, "min": req.get("min"), "max": req.get("max")},
                     ("min", "max", "formats", "max_bytes"))
        elif kind == "video":
            records = campaign.media_records("trailer")
            if req.get("required") is False and not records:
                continue
            used.append(("trailer", records))
            if not profile_limits:
                continue
            if not records:
                if req.get("required"):
                    _finding(findings, "FAIL", "media-missing", "trailer",
                             "trailer: the portal requires a video and the campaign has none")
                elif req.get("required") is None:
                    _finding(findings, "UNKNOWN", "limit-unknown", "trailer",
                             "trailer: the profile does not say whether a video is required")
                continue
            limits = {"formats": _formats(req.get("formats")), "aspect": req.get("aspect"),
                      "min_seconds": req.get("min_seconds"), "max_seconds": req.get("max_seconds"),
                      "min_width": req.get("min_width"), "min_height": req.get("min_height"),
                      "orientation": req.get("orientation"),
                      "max_bytes": int(req["max_mb"] * 1024 * 1024) if req.get("max_mb") is not None else None}
            _check_files(campaign, "trailer", records, limits, findings, video=True)
            _unknown(findings, "trailer", limits, ("formats", "max_seconds", "max_bytes"))
    # -- the publication profile: fields and upload intents
    required_locales = list(locales or campaign.required_locales(platform_profile))
    for name, field, intent in _publication_media(publication_profile):
        records = campaign.media_records(name)
        used.append((name, records))
        required = field.get("required")
        if intent and not intent.get("optional"):
            required = True
        if not records:
            if required:
                _finding(findings, "FAIL", "media-missing", name,
                         f"{name}: the portal asks for it and the campaign has none")
            elif required is None:
                _finding(findings, "UNKNOWN", "limit-unknown", name,
                         f"{name}: the campaign has none; the profile does not say whether the "
                         f"portal requires it")
            continue
        if intent and not intent.get("multiple") and len(records) > 1:
            _finding(findings, "FAIL", "media-count", name,
                     f"{name}: {len(records)} files for an input that takes one")
        _count(findings, name, len(records), field.get("min"), field.get("max_count"))
        accepted = _formats(intent.get("accept")) if intent.get("accept") is not None else None
        formats = _formats(field.get("formats"))
        allowed = [f for f in (accepted or []) if formats is None or f in formats] \
            if accepted is not None else formats
        mine = []
        _check_files(campaign, name, records, {"formats": allowed}, mine,
                     video=records[0][0].get("kind") == "trailer")
        if not intent and not required:
            # Nothing uploads it (no intent) and the portal does not require it: a file it
            # would not take is left out, said so, never a refusal.
            for f in mine:
                f.update(status="UNKNOWN", message=f["message"] + "; optional and no upload "
                                                                  "intent names it: left out")
        findings.extend(mine)
        if allowed is None:
            _finding(findings, "UNKNOWN", "limit-unknown", name,
                     f"{name}: the publication profile states no accepted file type")
        if field and field.get("size"):
            _finding(findings, "UNKNOWN", "limit-unknown", name,
                     f"{name}: the portal states {field['size']!r}, which is not checked "
                     f"mechanically")
        if field.get("locales") == "per-locale" or (intent and intent.get("per_locale")):
            tagged = {r.get("locale") for r in campaign.all_media_records(name)[0]
                      if r.get("locale")}
            if tagged:
                for locale in required_locales:
                    if not campaign.media_records(name, locale):
                        _finding(findings, "FAIL", "media-locale-missing", f"{name}:{locale}",
                                 f"{name}: the portal takes it per locale and the campaign has "
                                 f"none for {locale}")
            elif required_locales:
                _finding(findings, "UNKNOWN", "media-locale-shared", name,
                         f"{name}: the portal takes it per locale; the same captured files "
                         f"serve {', '.join(required_locales)}")
    # -- provenance and placeholders, for every file that would be uploaded
    # Only what would be uploaded needs a capture record: a campaign with no screenshot or
    # video on its way to this portal is not refused for the capture it does not use.
    if any(r.get("kind") in ("screenshot", "trailer") for _, records in used for r, _ in records):
        captured = _capture_problems(campaign, shipped_commit, findings)
    else:
        captured = False
    seen = set()
    for name, records in used:
        for record, origin in records:
            path = campaign.path(record)
            key = (path, record.get("id"))
            if key in seen:
                continue
            seen.add(key)
            rid = record.get("id")
            if not os.path.isfile(path):
                _finding(findings, "FAIL", "media-missing", rid, f"{name}: {rid} is not on disk "
                                                                 f"({record.get('path')})")
                continue
            if record.get("sha256") and listing_media.sha256_of(path) != record["sha256"]:
                _finding(findings, "FAIL", "media-changed", rid,
                         f"{name}: {rid} is not the bytes the listing recorded")
                continue
            if looks_like_placeholder(path, record):
                _finding(findings, "FAIL", "placeholder", rid,
                         f"{name}: {rid} is an asset-pipeline placeholder, not production art "
                         f"or a capture of the build")
                continue
            if captured and record.get("kind") in ("screenshot", "trailer"):
                _provenance(campaign, record, origin, findings)
    return _dedupe(findings)


def _dedupe(findings):
    out, seen = [], set()
    for f in findings:
        key = (f["status"], f["code"], f["subject"], f["message"])
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def failures(findings):
    return [f for f in findings if f["status"] == "FAIL"]
