"""Search existing assets before making new ones.

A library is a directory with an `index.json`: every entry names a file beside it, its kind,
the words it can be found by, and - required, not optional - where it came from and under
what licence. An entry with no licence can still be indexed; it will never be picked for a
build, and the manifest records that it was passed over and why.

    {
      "library": {"id": "studio-common"},
      "assets": [
        {"id": "coin-gold", "kind": "sprite", "path": "sprites/coin.png",
         "tags": ["coin", "currency", "pickup"],
         "license": "CC0-1.0", "source_url": "https://…", "author": "…",
         "attribution": "…", "usage_constraints": []}
      ]
    }

A library may instead (or as well) hold a `library.json` that maps a design's requirements
to files directly - by requirement id, and/or by role for every requirement of that role.
This is how golden fixtures and purchased packs supply real art for a known design:

    {
      "library": {"id": "tower-merge-art"},
      "items": [
        {"requirement": "tile", "files": ["svg/tile-1.svg", "svg/tile-2.svg"],
         "license": "CC0-1.0", "source": "https://…", "author": "…"},
        {"role": "background", "files": ["svg/board.svg"],
         "license": "LicenseRef-studio-owned", "source": "studio art pack 3", "author": "…"}
      ]
    }

`licence` is accepted for `license`; `source` is where it came from (a URL becomes the
origin's source_url, anything else its evidence). A requirement-id entry wins over a role
entry. `files` are relative to the library directory; one per drawing when the requirement
has a `count`.

Libraries are configured as `factory.assets.libraries: [<dir>, …]` (relative to the working
directory) or per step as `with: {libraries: [...]}`.
"""

import json
import os

__all__ = ["AssetLibrary", "LibraryEntry", "LibraryError", "MappedEntry", "open_libraries",
           "match_all"]


class LibraryError(ValueError):
    pass


class LibraryEntry:
    def __init__(self, library, data):
        self.library = library
        self.id = data.get("id")
        self.kind = data.get("kind")
        self.path = data.get("path")
        self.tags = {str(t).lower() for t in data.get("tags") or []}
        self.license = data.get("license")
        self.source_url = data.get("source_url")
        self.author = data.get("author")
        self.vendor = data.get("vendor")
        self.attribution = data.get("attribution")
        self.license_url = data.get("license_url")
        self.evidence = data.get("evidence")
        self.usage_constraints = list(data.get("usage_constraints") or [])

    @property
    def qualified_id(self):
        return f"{self.library.id}:{self.id}"

    def absolute_path(self):
        """The file, refusing anything that escapes the library directory."""
        root = os.path.realpath(self.library.directory)
        path = os.path.realpath(os.path.join(root, self.path or ""))
        if not self.path or os.path.commonpath([root, path]) != root:
            raise LibraryError(f"{self.qualified_id}: path {self.path!r} leaves the library")
        return path

    def score(self, req):
        words = set(self.tags)
        words.update(w for w in (self.id or "").lower().replace("_", "-").split("-") if w)
        return len(words & req.terms)


class MappedEntry:
    """A library.json item: files supplied for a requirement id or a role."""

    def __init__(self, library, data, index):
        self.library = library
        self.requirement = data.get("requirement")
        self.role = data.get("role")
        files = data.get("files")
        if isinstance(files, str):
            files = [files]
        self.files = [f for f in files or [] if isinstance(f, str)]
        self.license = data.get("license") or data.get("licence")
        source = data.get("source") or data.get("source_url")
        is_url = isinstance(source, str) and "://" in source
        self.source_url = source if is_url else None
        self.evidence = data.get("evidence") or (source if source and not is_url else None)
        self.author = data.get("author")
        self.vendor = data.get("vendor")
        self.attribution = data.get("attribution")
        self.license_url = data.get("license_url")
        self.usage_constraints = list(data.get("usage_constraints") or [])
        self.id = self.requirement or f"role-{self.role}-{index}"

    @property
    def qualified_id(self):
        return f"{self.library.id}:{self.id}"

    def absolute_paths(self):
        root = os.path.realpath(self.library.directory)
        out = []
        for relative in self.files:
            path = os.path.realpath(os.path.join(root, relative))
            if os.path.commonpath([root, path]) != root:
                raise LibraryError(f"{self.qualified_id}: path {relative!r} leaves the library")
            out.append((relative, path))
        return out


class AssetLibrary:
    def __init__(self, directory):
        self.directory = os.path.abspath(directory)
        self.entries, self.mapped = [], []
        index = os.path.join(self.directory, "index.json")
        mapping = os.path.join(self.directory, "library.json")
        if not os.path.isfile(index) and not os.path.isfile(mapping):
            raise LibraryError(f"no index.json or library.json in {self.directory}")
        self.id = None
        if os.path.isfile(mapping):
            data = self._load(mapping)
            self.id = (data.get("library") or {}).get("id")
            self.mapped = [MappedEntry(self, e, n) for n, e in enumerate(data.get("items") or [])
                           if isinstance(e, dict) and (e.get("requirement") or e.get("role"))]
        if os.path.isfile(index):
            data = self._load(index)
            self.id = self.id or (data.get("library") or {}).get("id")
            self.entries = [LibraryEntry(self, e) for e in data.get("assets") or []
                            if isinstance(e, dict) and e.get("id") and e.get("kind")]
        self.id = self.id or os.path.basename(self.directory)

    @staticmethod
    def _load(path):
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            raise LibraryError(f"cannot read library index {path}: {exc}")
        if not isinstance(data, dict):
            raise LibraryError(f"library index {path} is not an object")
        return data

    def match(self, req):
        """library.json entries for the requirement: by id first, then by role."""
        by_id = [e for e in self.mapped if e.requirement == req.id]
        by_role = [e for e in self.mapped if not e.requirement and req.role
                   and e.role == req.role]
        return by_id + by_role

    def search(self, req):
        """Entries of the requirement's kind that share at least one term with it, best
        first. Ties keep index order, so the result is deterministic."""
        scored = [(entry.score(req), n, entry) for n, entry in enumerate(self.entries)
                  if entry.kind == req.kind]
        return [entry for score, _, entry in sorted(scored, key=lambda t: (-t[0], t[1]))
                if score > 0]


def open_libraries(directories, base=None):
    """(libraries, problems). A library that cannot be read is a problem, not a crash: the
    pipeline still has placeholders."""
    libraries, problems = [], []
    for directory in directories or []:
        path = directory if os.path.isabs(directory) else os.path.join(base or os.getcwd(),
                                                                       directory)
        try:
            libraries.append(AssetLibrary(path))
        except LibraryError as exc:
            problems.append(str(exc))
    return libraries, problems


def search_all(libraries, req):
    found = []
    for library in libraries:
        found.extend(library.search(req))
    return found


def match_all(libraries, req):
    """Every library's library.json entries for the requirement: all id matches across the
    libraries in order, then all role matches."""
    found = [e for library in libraries for e in library.match(req)]
    return ([e for e in found if e.requirement == req.id]
            + [e for e in found if e.requirement != req.id])
