"""The research vocabulary and analysis configuration, loaded and queried.

core/reference/research-vocabulary.yaml is the shared code every researched game is described
in; core/reference/research-analysis.yaml says when a count is large enough to report. Both
are validated against their schemas on load, because an analysis that quietly reads a
malformed vocabulary counts the wrong things with total confidence.
"""

import hashlib
import json
import os
import re

from wgflib import paths
from wgflib.jsonschema_lite import Registry, Validator
from wgflib.yamllite import load_file

__all__ = ["Vocabulary", "AnalysisConfig", "VocabularyError", "VOCABULARY", "ANALYSIS",
           "MARKET_FACETS"]

VOCABULARY = os.path.join(paths.REFERENCE, "research-vocabulary.yaml")
ANALYSIS = os.path.join(paths.REFERENCE, "research-analysis.yaml")

# Facets that are not game codings but facts about where a game sits in the market. A
# pattern may count them; a teardown may not code them.
MARKET_FACETS = ("platform", "saturation", "session_band")


class VocabularyError(ValueError):
    """The vocabulary or analysis configuration is malformed. Not retryable."""


def _file_hash(path):
    with open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def _validated(path, schema_id):
    document = load_file(path)
    schema_path = os.path.join(paths.ARTIFACTS, "shared", f"{schema_id}.schema.json")
    with open(schema_path, encoding="utf-8") as handle:
        schema = json.load(handle)
    registry = Registry().add_directory(paths.ARTIFACTS)
    errors = [str(e) for e in Validator(schema, registry).iter_errors(document)]
    if errors:
        raise VocabularyError(f"{os.path.basename(path)}: " + "; ".join(errors[:5]))
    return document


def _norm(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


class Vocabulary:
    def __init__(self, path=None):
        self.path = path or VOCABULARY
        self.document = _validated(self.path, "research-vocabulary")
        self.version = str(self.document["version"])
        self.file_hash = _file_hash(self.path)
        self.genres = {g["id"]: g for g in self.document["genres"]}
        self.descriptors = {d["id"]: d for d in self.document["descriptors"]}
        self.facets = {f["id"]: f for f in self.document["facets"]}
        self.lists = {name: {v["id"]: v for v in values}
                      for name, values in self.document["vocabularies"].items()}
        self.lists["genres"] = self.genres
        self.lists["descriptors"] = self.descriptors
        self.session_bands = list(self.document["session_bands"])
        self._check()
        self._aliases = {}
        for node in self.document["genres"]:
            for alias in [node["id"], node["label"]] + list(node.get("aliases") or []):
                self._aliases.setdefault(_norm(alias), node["id"])

    def _check(self):
        problems = []
        for facet in self.facets.values():
            if facet["kind"] != "number" and facet["values"] not in self.lists:
                problems.append(f"facet {facet['id']} names unknown values {facet['values']!r}")
        for name, values in self.lists.items():
            for value in values.values():
                parent = value.get("parent")
                if parent and parent not in values:
                    problems.append(f"{name}: {value['id']} has unknown parent {parent!r}")
        for gid in self.genres:
            seen, node = set(), gid
            while node and node in self.genres:
                if node in seen:
                    problems.append(f"genre {gid}: parent cycle")
                    break
                seen.add(node)
                node = self.genres[node].get("parent")
        if problems:
            raise VocabularyError("; ".join(problems))

    # -- genres -----------------------------------------------------------------------------

    def genre_for(self, text):
        """The genre node a portal tag or a snapshot author's slug names, or None."""
        return self._aliases.get(_norm(text))

    def lineage(self, genre_id):
        """[genre_id, parent, ..., family]."""
        out = []
        while genre_id and genre_id in self.genres and genre_id not in out:
            out.append(genre_id)
            genre_id = self.genres[genre_id].get("parent")
        return out

    def family(self, genre_id):
        line = self.lineage(genre_id)
        return line[-1] if line else None

    def is_within(self, genre_id, ancestor):
        return ancestor in self.lineage(genre_id)

    def depth(self, genre_id):
        return len(self.lineage(genre_id))

    # -- facets -----------------------------------------------------------------------------

    def facet(self, facet_id):
        return self.facets.get(facet_id)

    def values(self, facet_id):
        facet = self.facets.get(facet_id)
        return self.lists.get(facet["values"], {}) if facet and facet["kind"] != "number" else {}

    def label(self, facet_id, value):
        if facet_id == "platform" or facet_id == "saturation":
            return str(value)
        if facet_id == "session_band":
            return str(value)
        entry = self.values(facet_id).get(value)
        return entry["label"] if entry else str(value)

    def entry(self, facet_id, value):
        return self.values(facet_id).get(value) or {}

    def check(self, facet_id, value):
        """None when `value` is a valid coding of `facet_id`, else the reason it is not."""
        facet = self.facets.get(facet_id)
        if facet is None:
            return f"unknown facet {facet_id!r}"
        if facet["kind"] == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                return f"facet {facet_id} takes a non-negative number in {facet['unit']}"
            return None
        known = self.values(facet_id)
        items = value if facet["kind"] == "many" else [value]
        if facet["kind"] == "many" and not isinstance(value, list):
            return f"facet {facet_id} takes a list of {facet['values']} ids"
        if facet["kind"] == "one" and not isinstance(value, str):
            return f"facet {facet_id} takes one {facet['values']} id"
        unknown = [v for v in items if v not in known]
        if unknown:
            return f"{', '.join(map(str, unknown))} not in vocabulary {facet['values']}"
        return None

    def session_band(self, seconds):
        for band in self.session_bands:
            if seconds <= band["max_seconds"]:
                return band["id"]
        return self.session_bands[-1]["id"]

    def describe(self):
        return {"version": self.version, "file_hash": self.file_hash}


class AnalysisConfig:
    def __init__(self, path=None):
        self.path = path or ANALYSIS
        self.document = _validated(self.path, "research-analysis")
        self.version = str(self.document["version"])
        self.file_hash = _file_hash(self.path)
        patterns = self.document["patterns"]
        self.min_support = int(patterns["min_support"])
        self.min_denominator = int(patterns["min_denominator"])
        self.pairs = list(patterns["pairs"])
        self.benchmarks = list(patterns["benchmarks"])
        self.lists = self.document["lists"]
        self.market = self.document["market"]
        self.opportunities = self.document["opportunities"]

    def list_kind(self, name, declared=None):
        """popularity | editorial | category for a captured list's name."""
        if declared in ("popularity", "editorial", "category"):
            return declared
        text = _norm(name)
        for kind in ("popularity", "editorial"):
            for marker in self.lists[kind]:
                if re.search(r"(?<![a-z])" + re.escape(_norm(marker)) + r"(?![a-z])", text):
                    return kind
        return "category"

    def check_against(self, vocabulary):
        problems = []
        known = set(vocabulary.facets) | set(MARKET_FACETS)
        for pair in self.pairs:
            for side in ("a", "b"):
                if pair[side] not in known:
                    problems.append(f"pair {pair['id']}: unknown facet {pair[side]!r}")
        for facet in self.benchmarks:
            spec = vocabulary.facet(facet)
            if not spec or spec["kind"] != "number":
                problems.append(f"benchmark {facet!r} is not a numeric facet")
        for axis in self.opportunities["axes"]:
            if axis not in vocabulary.facets:
                problems.append(f"axis {axis!r} is not a facet")
            elif vocabulary.facet(axis)["kind"] != "one":
                problems.append(f"axis {axis!r} holds several values; a proven core changes "
                                f"one value of one axis")
        if problems:
            raise VocabularyError("; ".join(problems))

    def describe(self):
        return {"version": self.version, "file_hash": self.file_hash}
