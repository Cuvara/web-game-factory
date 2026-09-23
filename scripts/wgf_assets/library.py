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

Libraries are configured as `factory.assets.libraries: [<dir>, …]` (relative to the working
directory) or per step as `with: {libraries: [...]}`.
"""

import json
import os

__all__ = ["AssetLibrary", "LibraryEntry", "LibraryError", "open_libraries"]


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


class AssetLibrary:
    def __init__(self, directory):
        self.directory = os.path.abspath(directory)
        index = os.path.join(self.directory, "index.json")
        try:
            with open(index, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            raise LibraryError(f"cannot read library index {index}: {exc}")
        self.id = (data.get("library") or {}).get("id") or os.path.basename(self.directory)
        self.entries = [LibraryEntry(self, e) for e in data.get("assets") or []
                        if isinstance(e, dict) and e.get("id") and e.get("kind")]

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
