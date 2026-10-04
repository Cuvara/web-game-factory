"""core/reference/mechanic-lexicon.yaml: text and design mechanics as mechanic ids.

Read by the strategy step and the design consistency rules, so a brief, a strategy and a
design are compared as the same mechanic ids rather than as the same words:

    load()                  the lexicon, cached per (path, mtime)
    normalize(text)         lower case, `-` `_` `/` as spaces, whitespace collapsed
    ids_in(text, lexicon)   the mechanic ids `text` names: whole words, longest phrase first,
                            a matched span consumed ("goal gate" is an exit, never a gate)
    phrases_in(text, phrases)  the subset of `phrases` that `text` contains, same matching
    mechanic_ids(m, lexicon)   a build_spec mechanic's ids: its id and name, else its
                            description
    kind(id, lexicon)       defining | detail | generic
    stems(text)             the content words of `text`, crudely stemmed - the fallback that
                            lets a mechanic the lexicon does not know count as the brief's
                            when the brief uses its own words

Nothing here knows a game, a family or an archetype; every word is in the lexicon.
"""

import os
import re

from wgflib import paths
from wgflib.yamllite import load_file

__all__ = ["PATH", "load", "normalize", "ids_in", "phrases_in", "mechanic_ids", "kind",
           "stems"]

PATH = os.path.join(paths.REFERENCE, "mechanic-lexicon.yaml")

_CACHE = {}


def load(path=None):
    """The lexicon. Raises YamlError on a broken file: a lexicon nobody can read is a failed
    check, never an empty one."""
    path = path or PATH
    stamp = os.stat(path).st_mtime_ns
    hit = _CACHE.get(path)
    if hit is None or hit[0] != stamp:
        hit = (stamp, load_file(path))
        _CACHE[path] = hit
    return hit[1]


def normalize(text):
    text = str(text or "").lower()
    text = re.sub(r"[-_/]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _pattern(phrase):
    return re.compile(r"(?<![a-z0-9])" + re.escape(normalize(phrase)) + r"(?![a-z0-9])")


def _scan(text, entries):
    """`entries`: (key, phrase) pairs. Returns the keys found, longest phrase first, each
    matched span blanked so a shorter phrase inside it cannot match again."""
    text = normalize(text)
    found = set()
    for key, phrase in sorted(entries, key=lambda e: (-len(normalize(e[1])), e[1])):
        pattern = _pattern(phrase)
        if pattern.search(text):
            found.add(key)
            text = pattern.sub(lambda m: " " * len(m.group(0)), text)
    return found


def _entries(lexicon):
    for mid, entry in sorted(((lexicon or {}).get("mechanics") or {}).items()):
        for word in (entry or {}).get("words") or []:
            yield mid, str(word)


def ids_in(text, lexicon):
    return _scan(text, list(_entries(lexicon)))


def phrases_in(text, phrases):
    return _scan(text, [(str(p), str(p)) for p in phrases or []])


def mechanic_ids(mechanic, lexicon):
    """A build_spec mechanic's ids: from its own id and name, which say what it is; from its
    description only when those name nothing the lexicon knows."""
    own = ids_in(f"{mechanic.get('id', '')} {mechanic.get('name', '')}", lexicon)
    return own or ids_in(mechanic.get("description", ""), lexicon)


def kind(mechanic_id, lexicon):
    entry = ((lexicon or {}).get("mechanics") or {}).get(mechanic_id) or {}
    return entry.get("kind", "defining")


_STOP = frozenset("a an the and or of to in on at by for with from into onto per its it is "
                  "each every one two three".split())


def _stem(word):
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[:-len(suffix)]
    return word


def stems(text):
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", normalize(text))
            if w not in _STOP and len(w) > 2}
