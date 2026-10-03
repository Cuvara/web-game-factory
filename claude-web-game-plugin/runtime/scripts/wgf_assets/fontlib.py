"""The Factory's font library: every face an identity kit can name, bundled, licensed, ready.

A design's typography names Google Fonts faces under the SIL Open Font License
(wgf_design/identity.py: each kit's display, body and numeric face, and the ALTERNATES a kit
falls back to for a script its own face cannot set). An autonomous run has no network and
no font tool, so the faces ship with the Factory, already built:

    workspace/library/fonts/
      fonts.json                 the index: source repository and commit, the subset table,
                                 and per family its file, weights, subsets, hashes, licence
      <slug>/<slug>.woff2        one WOFF2 per family: a variable font cut to the weight
                                 range the kits use (other axes pinned), or the static face;
                                 subset to the family's latin, latin-ext, cyrillic,
                                 cyrillic-ext, greek and vietnamese characters
      <slug>/OFL.txt             the family's licence, as published beside its sources

`FontProducer` turns a `font` requirement into those files: one per distinct family of the
design's typography, in typography order (display, body, numeric), each recorded with its
CSS family and weight. With fontTools importable it cuts each file further to the subsets the
design's scope.locales need (latin always); without it the library file ships as built. The
family's OFL.txt ships beside the files. Nothing is fetched at run time.

The library is rebuilt only by a maintainer (`python3 scripts/wgf-assets.py fonts build`,
which needs fontTools, Brotli and the network): it downloads each family's sources from the
pinned google/fonts commit, checks them against the recorded hashes when they are known, and
writes the files and the index. `fonts check` verifies the shipped files against the index
with the standard library only. Standard library only at run time.
"""

import hashlib
import io
import json
import os
import re

from wgflib import paths

__all__ = ["LIBRARY_DIR", "INDEX_NAME", "FORMAT", "LICENSE_ID", "SUBSETS", "FontLibrary",
           "FontProducer", "ProducerError", "load", "parse_face", "slug", "kit_faces",
           "subsets_for", "check", "build"]

LIBRARY_DIR = os.path.join(paths.ROOT, "workspace", "library", "fonts")
INDEX_NAME = "fonts.json"
FORMAT = "wgf-font-library"
LICENSE_ID = "OFL-1.1"
SOURCE_REPO = "https://github.com/google/fonts"
# The google/fonts commit the library is built from (read 2026-10-02).
SOURCE_COMMIT = "9710da1eacb3be272583c3224dcb70f9da6eadbb"

# The Google Fonts CSS API's unicode-range per subset: what a subset's file covers.
SUBSETS = {
    "latin": "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, "
             "U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, "
             "U+FEFF, U+FFFD",
    "latin-ext": "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, "
                 "U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, "
                 "U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF",
    "cyrillic": "U+0301, U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116",
    "cyrillic-ext": "U+0460-052F, U+1C80-1C8A, U+20B4, U+2DE0-2DFF, U+A640-A69F, U+FE2E-FE2F",
    "greek": "U+0370-0377, U+037A-037F, U+0384-038A, U+038C, U+038E-03A1, U+03A3-03FF",
    "vietnamese": "U+0102-0103, U+0110-0111, U+0128-0129, U+0168-0169, U+01A0-01A1, "
                  "U+01AF-01B0, U+0300-0301, U+0303-0304, U+0308-0309, U+0323, U+0329, "
                  "U+1EA0-1EF9, U+20AB",
}
SHIPPED_SUBSETS = tuple(SUBSETS)

# Axes other than weight are pinned when a variable family is cut: the kit's voice, fixed.
PINNED_AXES = {
    "Instrument Sans": {"wdth": 100},
    "Archivo": {"wdth": 100},
    "Fraunces": {"SOFT": 100, "WONK": 0, "opsz": 72},
    "Commissioner": {"FLAR": 0, "VOLM": 0, "slnt": 0},
}

_FACE = re.compile(r"^\s*([^(,]+?)\s*(?:\((\d{3})[^)]*\))?\s*(?:,.*)?$")


class ProducerError(RuntimeError):
    """A producer could not make the asset; the pipeline goes on to the next source."""


def slug(family):
    return re.sub(r"[^a-z0-9]+", "-", (family or "").lower()).strip("-")


def parse_face(text):
    """('Unbounded', 800) from 'Unbounded (800)'; ('Archivo Black', 400) from 'Archivo Black,
    tabular'; (None, None) for nothing."""
    match = _FACE.match(text or "")
    if not match or not match.group(1).strip():
        return None, None
    return match.group(1).strip(), int(match.group(2) or 400)


def kit_faces():
    """{family: sorted weights} every identity kit can name: its own faces, and the
    ALTERNATES it substitutes at the same weight. What the library must hold."""
    from wgf_design.identity import ALTERNATES, KITS
    found = {}
    for kit in KITS.values():
        for key in ("display", "body", "numeric"):
            family, weight = parse_face((kit.get("typography") or {}).get(key))
            if not family:
                continue
            found.setdefault(family, set()).add(weight)
            if family in ALTERNATES:
                found.setdefault(ALTERNATES[family], set()).add(weight)
    return {family: sorted(weights) for family, weights in sorted(found.items())}


def _ranges(spec):
    out = []
    for part in spec.split(","):
        part = part.strip().upper().replace("U+", "")
        if not part:
            continue
        lo, _, hi = part.partition("-")
        out.append((int(lo, 16), int(hi or lo, 16)))
    return out


def codepoints(subsets):
    """The set of code points the named subsets cover."""
    found = set()
    for name in subsets:
        for lo, hi in _ranges(SUBSETS.get(name, "")):
            found.update(range(lo, hi + 1))
    return found


def subsets_for(locales, bars=None):
    """The subsets the locales in scope need: latin always, then each locale's (from
    asset-quality.yaml `fonts.locales`; a locale it does not list adds nothing)."""
    from .quality import load_bars
    bars = bars or load_bars()
    found = ["latin"]
    for locale in locales or []:
        entry = bars.locale(locale) or {}
        for name in entry.get("subsets") or []:
            if name not in found:
                found.append(name)
    return found


class FontLibrary:
    def __init__(self, directory, index):
        self.directory = directory
        self.index = index
        self.families = {name: dict(entry) for name, entry in
                         (index.get("families") or {}).items()}

    def family(self, name):
        """The index entry of a family (case-insensitive), or None."""
        wanted = (name or "").strip().lower()
        for family, entry in self.families.items():
            if family.lower() == wanted:
                return dict(entry, family=family)
        return None

    def names(self):
        return sorted(self.families)

    def path(self, entry, key="file"):
        relative = entry.get(key) or ""
        full = os.path.normpath(os.path.join(self.directory, relative))
        if not full.startswith(os.path.normpath(self.directory) + os.sep):
            raise ProducerError(f"{relative!r} leaves the font library")
        return full

    def read(self, entry, key="file"):
        with open(self.path(entry, key), "rb") as handle:
            return handle.read()


def load(directory=None):
    """The font library, or None when it is absent or its index unreadable."""
    directory = directory or LIBRARY_DIR
    try:
        with open(os.path.join(directory, INDEX_NAME), encoding="utf-8") as handle:
            index = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(index, dict) or index.get("format") != FORMAT:
        return None
    return FontLibrary(directory, index)


def check(directory=None):
    """Problems with the shipped library: every family a kit names is there, every file and
    licence exists with its recorded size and hash. [] when it holds."""
    library = load(directory)
    if library is None:
        return [f"no font library index at {os.path.join(directory or LIBRARY_DIR, INDEX_NAME)}"]
    problems = []
    for family, weights in kit_faces().items():
        entry = library.family(family)
        if entry is None:
            problems.append(f"{family}: an identity kit names it and the library lacks it")
            continue
        lo, hi = entry.get("weights") or [0, 0]
        missing = [w for w in weights if not lo <= w <= hi]
        if missing:
            problems.append(f"{family}: weight(s) {missing} named by a kit are outside the "
                            f"file's {lo}-{hi}")
    for family, entry in sorted(library.families.items()):
        for key, digest_key, size_key in (("file", "sha256", "bytes"),
                                          ("license_file", "license_sha256", None)):
            try:
                data = library.read(entry, key)
            except (OSError, ProducerError) as exc:
                problems.append(f"{family}: {key}: {exc}")
                continue
            if entry.get(digest_key) and hashlib.sha256(data).hexdigest() != entry[digest_key]:
                problems.append(f"{family}: {entry.get(key)} does not match its recorded hash")
            if size_key and entry.get(size_key) != len(data):
                problems.append(f"{family}: {entry.get(key)} is {len(data)} bytes, recorded "
                                f"{entry.get(size_key)}")
        if entry.get("license") != LICENSE_ID:
            problems.append(f"{family}: licence {entry.get('license')!r} is not {LICENSE_ID}")
    return problems


def _subset_with_fonttools(data, subsets):
    """WOFF2 bytes of `data` cut to `subsets`, or None when fontTools is not importable."""
    try:
        from fontTools import subset as ft_subset
        from fontTools.ttLib import TTFont
    except ImportError:
        return None
    font = TTFont(io.BytesIO(data))
    options = ft_subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.notdef_outline = True
    options.hinting = False
    subsetter = ft_subset.Subsetter(options)
    subsetter.populate(unicodes=sorted(codepoints(subsets)))
    subsetter.subset(font)
    out = io.BytesIO()
    font.flavor = "woff2"
    font.save(out)
    return out.getvalue()


class FontProducer:
    """A `font` requirement from the Factory font library: the design's typography faces."""

    id = "font-library"
    source = "library"
    varies = False  # a face is a fixed file: a gate sending it back gets the same bytes

    def __init__(self, library, typography, locales=(), *, subset=True):
        self.library = library
        self.typography = dict(typography or {})
        self.locales = list(locales or [])
        self.subset = subset

    def faces(self):
        """[{family, weights, roles}] of the typography, distinct families in order."""
        out = []
        for key in ("display", "body", "numeric"):
            family, weight = parse_face(self.typography.get(key))
            if not family:
                continue
            for face in out:
                if face["family"].lower() == family.lower():
                    face["roles"].append(key)
                    if weight not in face["weights"]:
                        face["weights"].append(weight)
                    break
            else:
                out.append({"family": family, "weights": [weight], "roles": [key]})
        return out

    def supports(self, req):
        return req.kind == "font" and self.library is not None and bool(self.faces())

    def produce(self, req):
        faces = self.faces()
        unknown = [f["family"] for f in faces if self.library.family(f["family"]) is None]
        if unknown:
            raise ProducerError(f"the font library has no {', '.join(unknown)} (it holds "
                                f"{', '.join(self.library.names())})")
        wanted = max(1, req.count)
        if len(faces) < wanted:
            raise ProducerError(f"{req.id} counts {wanted} files and the typography names "
                                f"{len(faces)} famil{'y' if len(faces) == 1 else 'ies'}")
        faces = faces[:wanted]
        needed = subsets_for(self.locales)
        files, extra, notes, sources = [], [], [], []
        for face in faces:
            entry = self.library.family(face["family"])
            data = self.library.read(entry)
            shipped = [s for s in entry.get("subsets") or [] if s in needed]
            lacking = [s for s in needed if s not in (entry.get("subsets") or [])]
            cut = None
            if self.subset and shipped and set(shipped) != set(entry.get("subsets") or []):
                try:
                    cut = _subset_with_fonttools(data, shipped)
                except Exception:  # a subsetter bug falls back to the library's own file
                    cut = None
            lo, hi = entry.get("weights") or [400, 400]
            outside = [w for w in face["weights"] if not lo <= w <= hi]
            weight = f"{lo}" if lo == hi else f"{lo} {hi}"
            files.append({"data": cut or data, "format": "woff2", "family": entry["family"],
                          "weight": weight})
            extra.append((f"LICENSE-{slug(entry['family'])}.txt",
                          self.library.read(entry, "license_file")))
            note = (f"{entry['family']} {weight.replace(' ', '-')} "
                    f"({'/'.join(face['roles'])})")
            if outside:
                note += f", asked for weight {'/'.join(map(str, outside))}: nearest shipped"
            notes.append(note)
            sources.append({"family": entry["family"], "file": entry.get("file"),
                            "sha256": entry.get("sha256"),
                            "subsets": shipped if cut else entry.get("subsets"),
                            "subset_here": bool(cut), "lacking": lacking,
                            "source_url": entry.get("source_url"),
                            "copyright": entry.get("copyright")})
        first = self.library.family(faces[0]["family"])
        attribution = "; ".join(s["copyright"] for s in sources if s.get("copyright")) or \
            "; ".join(f"{s['family']} (SIL Open Font License 1.1)" for s in sources)
        origin = {"kind": "library", "library_id": f"factory-fonts:{slug(first['family'])}"
                  if len(sources) == 1 else "factory-fonts",
                  "source_url": first.get("source_url") or SOURCE_REPO,
                  "author": "; ".join(dict.fromkeys(
                      self.library.family(f["family"]).get("designer") or "Google Fonts"
                      for f in faces)),
                  "attribution": attribution,
                  "license_url": "https://openfontlicense.org"}
        return {"files": files, "extra": extra, "license": LICENSE_ID, "origin": origin,
                "notes": "Faces, in file order: " + "; ".join(notes)
                         + ". Each file's OFL.txt ships beside it as LICENSE-<family>.txt.",
                "metadata": {"producer": self.id, "library_commit":
                             self.library.index.get("source", {}).get("commit"),
                             "subsets": needed, "faces": sources},
                "author": f"builtin:{self.id}",
                "done": ["font-subset"] if all(s["subset_here"] for s in sources) else []}


# -- building the library (maintainers; fontTools, Brotli and the network) ---------------------

def _fetch(url):
    import urllib.request
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def _metadata(text):
    """(designer, copyright, [(style, weight, filename)], {axis: (lo, hi)}, [subset]) of a
    google/fonts METADATA.pb (text protobuf)."""
    designer = (re.search(r'^designer: "([^"]*)"', text, re.M) or [None, None])[1]
    fonts = []
    for block in re.findall(r"fonts \{(.*?)\n\}", text, re.S):
        style = (re.search(r'style: "(\w+)"', block) or [None, "normal"])[1]
        weight = int((re.search(r"weight: (\d+)", block) or [None, 400])[1])
        filename = re.search(r'filename: "([^"]+)"', block).group(1)
        copyright_ = (re.search(r'copyright: "((?:[^"\\]|\\.)*)"', block) or [None, None])[1]
        fonts.append((style, weight, filename, copyright_))
    axes = {tag: (float(lo), float(hi)) for tag, lo, hi in re.findall(
        r'tag: "(\w+)"\s*min_value: ([\d.-]+)\s*max_value: ([\d.-]+)', text)}
    subsets = re.findall(r'subsets: "([^"]+)"', text)
    return designer, fonts, axes, subsets


def _directory_name(family):
    return re.sub(r"[^a-z0-9]", "", family.lower())


def build(directory=None, *, commit=SOURCE_COMMIT, fetch=_fetch, log=print):
    """Rebuild the library from google/fonts at `commit`: one WOFF2 per family the kits
    name, its OFL.txt, and the index. Needs fontTools and Brotli. Returns the index."""
    from fontTools import subset as ft_subset
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    directory = directory or LIBRARY_DIR
    os.makedirs(directory, exist_ok=True)
    previous = load(directory)
    known = previous.families if previous else {}
    raw = f"https://raw.githubusercontent.com/google/fonts/{commit}/ofl"
    families = {}
    for family, weights in kit_faces().items():
        folder = _directory_name(family)
        designer, fonts, axes, published = _metadata(
            fetch(f"{raw}/{folder}/METADATA.pb").decode("utf-8"))
        upright = [f for f in fonts if f[0] == "normal"]
        lo, hi = min(weights), max(weights)
        variable = "wght" in axes
        if variable:
            source = upright[0]
        else:
            # A static family: the file of the weight the kits name (one weight per family).
            source = min(upright, key=lambda f: abs(f[1] - lo))
            lo = hi = source[1]
        filename = source[2]
        data = fetch(f"{raw}/{folder}/{filename}")
        digest = hashlib.sha256(data).hexdigest()
        recorded = (known.get(family) or {}).get("source_sha256")
        if recorded and recorded != digest and commit == (previous.index.get("source") or {}
                                                          ).get("commit"):
            raise RuntimeError(f"{family}: {filename} at {commit} does not match its recorded "
                               f"hash {recorded}")
        license_text = fetch(f"{raw}/{folder}/OFL.txt")
        font = TTFont(io.BytesIO(data))
        if variable:
            # Weight cut to the kits' range; every other axis pinned (PINNED_AXES, else its
            # default: None).
            pinned = PINNED_AXES.get(family, {})
            limits = {tag: pinned.get(tag) for tag in axes if tag != "wght"}
            limits["wght"] = lo if lo == hi else (lo, hi)
            font = instancer.instantiateVariableFont(font, limits, updateFontNames=False)
            # Round-trip before subsetting: a partly instanced gvar is read lazily and the
            # subsetter trips over glyphs it has not loaded.
            staged = io.BytesIO()
            font.save(staged)
            font = TTFont(io.BytesIO(staged.getvalue()))
        shipped = [s for s in SHIPPED_SUBSETS if s in published]
        options = ft_subset.Options()
        options.flavor = "woff2"
        options.layout_features = ["*"]
        options.name_IDs = ["*"]
        options.name_languages = ["*"]
        options.notdef_outline = True
        options.hinting = False
        subsetter = ft_subset.Subsetter(options)
        subsetter.populate(unicodes=sorted(codepoints(shipped)))
        subsetter.subset(font)
        out = io.BytesIO()
        font.flavor = "woff2"
        font.save(out)
        woff2 = out.getvalue()
        name = slug(family)
        os.makedirs(os.path.join(directory, name), exist_ok=True)
        with open(os.path.join(directory, name, f"{name}.woff2"), "wb") as handle:
            handle.write(woff2)
        with open(os.path.join(directory, name, "OFL.txt"), "wb") as handle:
            handle.write(license_text)
        families[family] = {
            "file": f"{name}/{name}.woff2", "bytes": len(woff2),
            "sha256": hashlib.sha256(woff2).hexdigest(),
            "weights": [lo, hi], "variable": variable and lo != hi,
            "pinned_axes": PINNED_AXES.get(family) if variable else None,
            "subsets": shipped, "published_subsets": [s for s in published if s != "menu"],
            "license": LICENSE_ID, "license_file": f"{name}/OFL.txt",
            "license_sha256": hashlib.sha256(license_text).hexdigest(),
            "designer": designer, "copyright": source[3],
            "source_url": f"{SOURCE_REPO}/tree/{commit}/ofl/{folder}",
            "source_file": filename, "source_sha256": digest,
            "kit_weights": weights,
        }
        log(f"{family}: {filename} -> {name}.woff2 {len(woff2)} bytes, weights {lo}-{hi}, "
            f"{', '.join(shipped)}")
    index = {"format": FORMAT, "version": 1,
             "source": {"repository": SOURCE_REPO, "commit": commit},
             "license": LICENSE_ID,
             "subsets": SUBSETS,
             "families": families}
    with open(os.path.join(directory, INDEX_NAME), "w", encoding="utf-8") as handle:
        json.dump(index, handle, indent=1, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    return index
