"""The gate-gaming pre-check: what a specialist commit changed that a gate MEASURES, not the game.

A specialist develop visit is briefed with gate findings, each accepted when the gate measures
the next build. Its cheapest pass is often a change to the gate's input instead of the game -
a play area shrunk so the bot reaches a unit in time, a sprite drawn larger than the collider
it still has, content fields no code reads that change a similarity signature. This module
reads the commits under review deterministically, before the reviewer does:

    Vocabulary.load()                     core/reference/gate-gaming.yaml
    precheck_range(reader, base, head)    every specialist commit in base..head, checked
    precheck(reader, commit, specialist)  one commit: hunks classified, patterns flagged
    blockers(result)                      the review blockers a flag becomes

Each hunk of a specialist commit is classified `player-facing`, `measurement-facing`,
`test` or `bookkeeping`, and four patterns are flagged:

    unread-content-field          content data gained a field no game source reads
    play-area-change              bounds, walls or colliders changed in a visit routed for
                                  reach, time or visibility
    probe-path-change             probe-, showcase- or bot-only code changed in a visit whose
                                  findings are about the game
    sprite-size-without-collider  a drawn size changed and the same entity's physical size
                                  did not

A flag is a review blocker routed back to the visit's owner. The documented way out is a
declaration in the visit's docs/development/report.json `measurement_changes` with evidence
the commit holds (docs/review-module.md): it clears an unread field the evidence shows is
read, and turns any other flag into a declared change the reviewer judges. The reader is a
git object reader (GitReader over wgflib.isolation.Git), so the same check runs on a live
checkout and replays on any repository's history.
"""

import json
import os
import re

from wgflib import paths
from wgflib.yamllite import load_file

__all__ = ["Vocabulary", "GitReader", "precheck", "precheck_range", "blockers", "words",
           "PATH", "FLAG_PREFIX", "PATTERNS"]

PATH = os.path.join(paths.REFERENCE, "gate-gaming.yaml")
# Blocker ids of the pre-check, and the prefix a reviewer's own gate-gaming blockers use:
# both are stamped with the visit's dimension so triage routes them back to its owner.
FLAG_PREFIX = "gate-gaming-"
PATTERNS = ("unread-content-field", "play-area-change", "probe-path-change",
            "sprite-size-without-collider")
BRIEF = "docs/development/brief.json"
REPORT = "docs/development/report.json"
# Bounds that keep one review's pre-check proportionate: commits read in one range, and
# locations quoted per flag.
MAX_COMMITS = 30
MAX_WHERE = 6

_WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
_ASSIGN = re.compile(
    r"^\s*(?:export\s+)?(?:(?:const|let|var|readonly|static|private|public|protected)\s+)*"
    r"([A-Za-z_$][\w$.]*)\s*\??\s*(?::\s*[\w$<>\[\]|. ]+?\s*)?[:=]\s*(.+)$")
_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@ ?(.*)$")


def words(text):
    """The lower-cased words of identifiers in `text`: snake_case, camelCase, kebab-case and
    dotted names split. `BALL_DRAW` -> ball, draw; `gridTop` -> grid, top."""
    return [w.lower() for w in _WORD.findall(text or "")]


def _indent(line):
    return len(line) - len(line.lstrip())


def _code(line):
    """A source line without its comment: what runs, not what describes it."""
    stripped = line.strip()
    if stripped.startswith(("//", "/*", "*")):
        return ""
    return line.split("//", 1)[0] if "//" in line and "://" not in line else line


class VocabularyError(ValueError):
    pass


class Vocabulary:
    """core/reference/gate-gaming.yaml, read once."""

    def __init__(self, data):
        if not isinstance(data, dict) or not data.get("version"):
            raise VocabularyError(f"{PATH} has no version")
        self.data = data
        self.version = str(data["version"])
        self.paths = data.get("paths") or {}
        self.words = {k: set(v or []) for k, v in (data.get("words") or {}).items()}
        self.categories = data.get("categories") or {}
        self.patterns = data.get("patterns") or {}
        self.rules = list(data.get("rules") or [])
        missing = [p for p in PATTERNS if p not in self.patterns]
        if missing:
            raise VocabularyError(f"{PATH} names no pattern {', '.join(missing)}")

    @classmethod
    def load(cls, path=None):
        try:
            return cls(load_file(path or PATH))
        except OSError as exc:
            raise VocabularyError(f"cannot read {path or PATH}: {exc}") from exc

    @property
    def ref(self):
        return f"gate-gaming@{self.version}"

    # -- paths ---------------------------------------------------------------------------

    def _under(self, path, key):
        return any(path == p or (p.endswith("/") and path.startswith(p))
                   for p in self.paths.get(key) or [])

    def is_test(self, path):
        if any(f"/{p}" in f"/{path}" for p in self.paths.get("tests") or []):
            return True
        return any(m in os.path.basename(path) for m in self.paths.get("test_markers") or [])

    def is_bookkeeping(self, path):
        return self._under(path, "bookkeeping")

    def is_source(self, path):
        return (self._under(path, "source_roots") and not self.is_test(path)
                and os.path.splitext(path)[1] in (self.paths.get("source_extensions") or []))

    def is_content(self, path):
        return self._under(path, "content_data") and path.endswith(".json")

    def is_size_data(self, path):
        return self._under(path, "size_data") and path.endswith(".json")

    def is_render(self, path):
        segments = set()
        for part in path.split("/"):
            segments.update(words(os.path.splitext(part)[0]))
        return bool(segments & set(self.paths.get("render_segments") or []))

    # -- findings ------------------------------------------------------------------------

    def categories_of(self, finding):
        """The categories a routed finding matches, by the words of its check, dimension and
        summary."""
        source = finding.get("source") or {}
        said = set(words(" ".join(str(x) for x in (
            source.get("check"), finding.get("id"), finding.get("dimension"),
            finding.get("summary")) if x)))
        return [cid for cid, spec in self.categories.items()
                if said & set((spec or {}).get("words") or [])]

    def rules_for(self, finding):
        out = []
        for cid in self.categories_of(finding):
            out.extend((self.categories.get(cid) or {}).get("rules") or [])
        return out

    def applies(self, pattern, findings):
        """(applies, reason): whether a pattern watches a visit routed for `findings`."""
        spec = self.patterns.get(pattern) or {}
        excepted = set(spec.get("except_checks") or [])
        if excepted:
            for finding in findings:
                check = (finding.get("source") or {}).get("check") or finding.get("id")
                if set(words(str(check))) & excepted:
                    return False, f"finding `{finding.get('id')}` is about the probe itself"
        watch = spec.get("watch") or []
        if not watch:
            return True, None
        matched = {c for f in findings for c in self.categories_of(f)}
        if matched & set(watch):
            return True, None
        return False, "no routed finding is about " + " or ".join(watch)


class GitReader:
    """Git objects of one repository, through wgflib.isolation.Git (wgflib.procs)."""

    def __init__(self, git):
        self.git = git

    def diff(self, base, commit):
        return self.git.run("diff", "--no-color", "--no-ext-diff", "--no-renames", "-U3",
                            base, commit, "--")

    def show(self, rev, path):
        result = self.git.run("show", f"{rev}:{path}", check=False, raw=True)
        return result.stdout if result.ok else None

    def parent(self, rev):
        result = self.git.run("rev-parse", "--verify", "--quiet", f"{rev}^", check=False,
                              raw=True)
        return result.stdout.strip() if result.ok and result.stdout.strip() else None

    def commits(self, base, head):
        out = self.git.run("rev-list", "--reverse", "--no-merges", f"{base}..{head}")
        return [line.strip() for line in out.splitlines() if line.strip()]

    def touched(self, rev):
        out = self.git.run("diff-tree", "--no-commit-id", "--name-only", "-r", "--root", rev)
        return [line.strip() for line in out.splitlines() if line.strip()]

    def grep(self, rev, word, roots):
        """[(path, text)] of lines at `rev` under `roots` holding `word` as a whole word."""
        result = self.git.run("grep", "-n", "-I", "-w", "-F", "-e", word, rev, "--", *roots,
                              check=False, raw=True)
        out = []
        for line in (result.stdout or "").splitlines() if result.ok else []:
            # <rev>:<path>:<line>:<text>
            parts = line.split(":", 3)
            if len(parts) == 4:
                out.append((parts[1], parts[3]))
        return out


# -- diff parsing --------------------------------------------------------------------------

def parse_diff(text):
    """[{path, old_path, hunks: [{header, old_start, new_start, lines: [(op, text, old, new)]}]}]
    of a unified diff."""
    files, current, hunk = [], None, None
    old_no = new_no = 0
    for line in (text or "").splitlines():
        if line.startswith("diff --git "):
            current = {"path": None, "old_path": None, "hunks": []}
            files.append(current)
            hunk = None
            continue
        if current is None:
            continue
        if hunk is None and line.startswith("--- "):
            name = line[4:].strip()
            current["old_path"] = None if name == "/dev/null" else name[2:]
            continue
        if hunk is None and line.startswith("+++ "):
            name = line[4:].strip()
            current["path"] = None if name == "/dev/null" else name[2:]
            continue
        match = _HUNK.match(line)
        if match:
            old_no, new_no = int(match.group(1)), int(match.group(2))
            hunk = {"header": match.group(3), "old_start": old_no, "new_start": new_no,
                    "lines": []}
            current["hunks"].append(hunk)
            continue
        if hunk is None or not line or line.startswith("\\"):
            continue
        op, body = line[0], line[1:]
        if op == "+":
            hunk["lines"].append(("+", body, None, new_no))
            new_no += 1
        elif op == "-":
            hunk["lines"].append(("-", body, old_no, None))
            old_no += 1
        else:
            hunk["lines"].append((" ", body, old_no, new_no))
            old_no += 1
            new_no += 1
    for entry in files:
        entry["path"] = entry["path"] or entry["old_path"]
    return files


def _added_line(entry, needle):
    """The new-file line number of the first added line of a diff entry holding `needle`."""
    for hunk in entry["hunks"]:
        for op, text, _, new in hunk["lines"]:
            if op == "+" and needle in text:
                return new
    return None


def _hunks_with(entry, test):
    """The new-file start of every hunk with a changed line `test` accepts."""
    return [h["new_start"] for h in entry["hunks"]
            if any(op != " " and test(text) for op, text, _, _ in h["lines"])]


def _json(text):
    try:
        return json.loads(text) if text is not None else None
    except ValueError:
        return None


def _leaves(value, prefix=()):
    """{concrete path: scalar} of every leaf; indices kept."""
    out = {}
    if isinstance(value, dict):
        for key, child in value.items():
            out.update(_leaves(child, prefix + (str(key),)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            out.update(_leaves(child, prefix + (f"[{index}]",)))
    else:
        out[prefix] = value
    return out


def _dotted(path):
    return ".".join(path).replace(".[", "[")


def _assignments(lines, op):
    """{name: (numbers, line number, text)} of the hunk lines with `op` that assign a number."""
    out = {}
    for kind, text, old, new in lines:
        if kind != op:
            continue
        code = _code(text)
        match = _ASSIGN.match(code)
        if not match:
            continue
        numbers = _NUMBER.findall(match.group(2))
        if numbers:
            out[match.group(1)] = (numbers, new if op == "+" else old, code.strip())
    return out


# -- the check -----------------------------------------------------------------------------

class _Commit:
    """One commit's diff and the files the patterns read, from the reader."""

    def __init__(self, reader, vocabulary, commit, base):
        self.reader, self.vocab, self.commit, self.base = reader, vocabulary, commit, base
        self.files = parse_diff(reader.diff(base, commit))
        self._grep, self._text = {}, {}

    def grep(self, word):
        if word not in self._grep:
            roots = [r.rstrip("/") or "." for r in self.vocab.paths.get("source_roots") or []]
            self._grep[word] = [(p, t) for p, t in self.reader.grep(self.commit, word, roots)
                                if self.vocab.is_source(p)]
        return self._grep[word]

    def lines(self, rev, path):
        key = (rev, path)
        if key not in self._text:
            self._text[key] = (self.reader.show(rev, path) or "").splitlines()
        return self._text[key]

    def json_pair(self, path):
        return _json(self.reader.show(self.base, path)), _json(self.reader.show(self.commit, path))

    def scope(self, path, op, old, new):
        """The lines that say what a changed line belongs to: its enclosing declaration (the
        nearest line above it indented less) and the comment directly above that."""
        rev, number = (self.base, old) if op == "-" else (self.commit, new)
        lines = self.lines(rev, path)
        if not number or number > len(lines):
            return []
        indent = _indent(lines[number - 1])
        out, at = [], number - 2
        while at >= 0 and (not lines[at].strip() or _indent(lines[at]) >= indent):
            at -= 1
        if at < 0:
            return out
        out.append(lines[at])
        at -= 1
        while at >= 0 and lines[at].strip().startswith(("//", "/*", "*", "*/")):
            out.append(lines[at])
            at -= 1
        return out


def _read_by_source(change, key, parents):
    """(file, line text) where game source reads `key`, or None. Read means: the key as a
    quoted string, `<parent>.key` for a parent object the key was added under (any `.key`
    when it sits in an array element or at the top), or the key destructured on one line.
    `parents` is [(parent key or None, in an array element)]."""
    quoted = re.compile(r"""(["'`])""" + re.escape(key) + r"\1")
    loose = any(parent is None or in_array for parent, in_array in parents)
    owners = sorted({parent for parent, in_array in parents if parent and not in_array})
    dotted = re.compile(
        (r"\." if loose or not owners else
         r"\b(?:" + "|".join(re.escape(o) for o in owners) + r")\s*\??\.")
        + r"\s*" + re.escape(key) + r"\b")
    destructured = re.compile(r"\{[^{}]*\b" + re.escape(key) + r"\b[^{}]*\}\s*=")
    for path, text in change.grep(key):
        code = _code(text)
        if quoted.search(code) or dotted.search(code) or destructured.search(code):
            return path, text.strip()
    return None


def _shape(path):
    """A concrete key path's shape: indices as `[]`."""
    return tuple("[]" if k.startswith("[") and k.endswith("]") else k for k in path)


def _concrete_keys(value, prefix=()):
    """Every dict key's concrete path, array indices kept: a key added to one more element
    of an array is an added key, though another element already had it."""
    out = set()
    if isinstance(value, dict):
        for key, child in value.items():
            path = prefix + (str(key),)
            out.add(path)
            out |= _concrete_keys(child, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            out |= _concrete_keys(child, prefix + (f"[{index}]",))
    return out


def _unread_fields(change):
    flags = []
    for entry in change.files:
        path = entry["path"]
        if not path or not change.vocab.is_content(path):
            continue
        before, after = change.json_pair(path)
        if after is None:
            continue
        added = sorted(_concrete_keys(after) - _concrete_keys(before))
        by_key = {}
        for key_path in added:
            if re.match(r"^[A-Za-z_$][\w$]*$", key_path[-1]):
                by_key.setdefault(key_path[-1], []).append(key_path)
        for key, where in sorted(by_key.items()):
            parents = set()
            for key_path in where:
                shape = _shape(key_path)
                named = [k for k in shape[:-1] if k != "[]"]
                parents.add((named[-1] if named else None,
                             len(shape) >= 2 and shape[-2] == "[]"))
            if _read_by_source(change, key, sorted(parents, key=str)):
                continue
            shown = sorted({_dotted(_shape(p)) for p in where})[:MAX_WHERE]
            flags.append({"pattern": "unread-content-field", "file": path, "key": key,
                          "line": _added_line(entry, f'"{key}"'),
                          "hunks": _hunks_with(entry, lambda s, k=f'"{key}"': k in s),
                          "where": f"{path}#{key}",
                          "detail": f"`{key}` (added at {', '.join(shown)}; {len(where)} "
                                    f"place(s)) is read nowhere in game source - not as a "
                                    f"quoted key, a property of the object it was added "
                                    f"to, or a destructured name"})
    return flags


def _play_area(change):
    vocab, flags = change.vocab, []
    terms = vocab.words.get("play_area") or set()
    for entry in change.files:
        path = entry["path"]
        if not path or vocab.is_test(path) or vocab.is_bookkeeping(path):
            continue
        hits, first = [], None
        if vocab.is_size_data(path):
            before, after = change.json_pair(path)
            old, new = _leaves(before), _leaves(after)
            for leaf in sorted(set(old) | set(new)):
                if old.get(leaf) != new.get(leaf) and set(words(" ".join(leaf))) & terms:
                    hits.append(f"`{_dotted(leaf)}` {old.get(leaf)!r} -> {new.get(leaf)!r}")
        elif vocab.is_source(path):
            for hunk in entry["hunks"]:
                for op, text, old, new in hunk["lines"]:
                    if op == " ":
                        continue
                    found = set(words(_code(text))) & terms
                    if found:
                        hits.append(f"{op}{new or old}: `{text.strip()[:100]}`")
                        first = first or (new if op == "+" else None)
        if hits:
            if first is None:
                first = next((_added_line(entry, w) for w in sorted(terms)
                              if _added_line(entry, w)), None)
            flags.append({"pattern": "play-area-change", "file": path, "line": first,
                          "hunks": _hunks_with(entry, lambda s: bool(
                              set(words(_code(s))) & terms)),
                          "where": path, "detail": "; ".join(hits[:MAX_WHERE])
                          + (f"; and {len(hits) - MAX_WHERE} more" if len(hits) > MAX_WHERE
                             else "")})
    return flags


def _probe_hunks(change):
    """[(path, hunk, matched words)] of source hunks with a changed line that is probe-,
    showcase- or bot-only: the line itself, the declaration it sits in or that
    declaration's comment names the probe (or the file's path does)."""
    vocab, out = change.vocab, []
    terms = vocab.words.get("probe") or set()
    for entry in change.files:
        path = entry["path"]
        if not path or not vocab.is_source(path):
            continue
        in_path = set(words(path)) & terms
        for hunk in entry["hunks"]:
            found = set(in_path)
            for op, text, old, new in hunk["lines"]:
                if op == " ":
                    continue
                said = [text] + change.scope(path, op, old, new)
                found |= set(words(" ".join(said))) & terms
            if found and any(op != " " for op, _, _, _ in hunk["lines"]):
                out.append((path, hunk, sorted(found)))
    return out


def _probe_paths(change):
    flags, by_file = [], {}
    for path, hunk, found in _probe_hunks(change):
        line = next((n for op, _, _, n in hunk["lines"] if op == "+"), None)
        by_file.setdefault(path, []).append((hunk, found, line))
    for path, hunks in by_file.items():
        detail = "; ".join(f"hunk at {h['new_start']} ({', '.join(f)})" for h, f, _ in
                           hunks[:MAX_WHERE])
        flags.append({"pattern": "probe-path-change", "file": path, "line": hunks[0][2],
                      "hunks": [h["new_start"] for h, _, _ in hunks],
                      "where": path, "detail": detail})
    return flags


def _sprite_sizes(change):
    vocab = change.vocab
    size, draw = vocab.words.get("size") or set(), vocab.words.get("draw") or set()
    collider, generic = vocab.words.get("collider") or set(), vocab.words.get("generic") or set()
    drawn, physical = [], []  # drawn: (path, name, stem, line, before, after); physical: words
    for entry in change.files:
        path = entry["path"]
        if not path or vocab.is_test(path) or vocab.is_bookkeeping(path):
            continue
        if vocab.is_source(path):
            render = vocab.is_render(path)
            for hunk in entry["hunks"]:
                old, new = _assignments(hunk["lines"], "-"), _assignments(hunk["lines"], "+")
                for name in set(old) & set(new):
                    if old[name][0] == new[name][0]:
                        continue
                    named = set(words(name))
                    context = (named | set(words(new[name][2])) | set(words(hunk["header"]))
                               | set(words(" ".join(change.scope(path, "+", None,
                                                                  new[name][1])))))
                    if named & collider or (named & size and not render and not named & draw):
                        physical.append(context)
                    elif (named & size and (render or named & draw)) or (named & draw
                                                                          and render):
                        stem = named - size - draw - collider - generic
                        drawn.append((path, name, stem, new[name][1], old[name][2],
                                      new[name][2], hunk["new_start"]))
        elif vocab.is_size_data(path):
            before, after = change.json_pair(path)
            old, new = _leaves(before), _leaves(after)
            for leaf in set(old) & set(new):
                if old[leaf] == new[leaf] or not isinstance(new[leaf], (int, float)):
                    continue
                named = set(words(" ".join(leaf)))
                if named & collider or (named & size and vocab.is_content(path)
                                        and not named & draw):
                    physical.append(named)
                elif named & size and (named & draw or leaf[-1] == "scale"):
                    stem = named - size - draw - collider - generic
                    drawn.append((path, _dotted(leaf), stem, None, old[leaf], new[leaf],
                                  None))
    flags = {}
    for path, name, stem, line, before, after, at in drawn:
        if not stem:
            continue  # no entity to hold the collider to
        if any(stem & context for context in physical):
            continue  # the entity's physical size changed with it
        if not _has_body(change, stem, size | collider, draw):
            continue  # nothing physical to be consistent with (an effect, a backdrop)
        flag = flags.setdefault(path, {"pattern": "sprite-size-without-collider",
                                       "file": path, "line": line, "where": path,
                                       "stems": set(), "detail": [], "hunks": []})
        flag["stems"].update(stem)
        if at is not None and at not in flag["hunks"]:
            flag["hunks"].append(at)
        flag["detail"].append(f"`{before}` -> `{after}`")
    out = []
    for flag in flags.values():
        flag["detail"] = ("; ".join(flag["detail"][:MAX_WHERE])
                          + " - the simulation gives " + ", ".join(sorted(flag.pop("stems")))
                          + " a physical size, and no collider or physical size of it "
                            "changed in the commit")
        out.append(flag)
    return out


def _has_body(change, stem, physical_words, draw_words):
    """Whether simulation source (not drawing code) gives an entity named by `stem` a
    physical size or a collider: a line naming it beside a size or collider word."""
    for word in sorted(stem):
        for path, text in change.grep(word):
            if change.vocab.is_render(path):
                continue
            said = set(words(_code(text)))
            if word in said and said & physical_words and not said & draw_words:
                return True
    return False


def _classify(change, flags):
    """[{file, hunk, class, reasons}] of every hunk in the commit. A hunk is
    measurement-facing when a flag names it (a flag that cannot say which hunk - a JSON
    value no added line holds - names its whole file) or it is a probe-only path."""
    vocab = change.vocab
    flagged = {}
    for flag in flags:
        for at in flag.get("hunks") or [None]:
            flagged.setdefault((flag["file"], at), set()).add(flag["pattern"])
    probe = {(p, h["new_start"]) for p, h, _ in _probe_hunks(change)}
    out = []
    for entry in change.files:
        path = entry["path"] or ""
        for hunk in entry["hunks"] or [{"new_start": 0}]:
            at = hunk.get("new_start")
            reasons = flagged.get((path, at), set()) | flagged.get((path, None), set())
            if vocab.is_bookkeeping(path):
                kind, reasons = "bookkeeping", set()
            elif vocab.is_test(path):
                kind, reasons = "test", set()
            elif reasons:
                kind = "measurement-facing"
            elif (path, at) in probe:
                kind, reasons = "measurement-facing", {"probe-path"}
            else:
                kind = "player-facing"
            out.append({"file": path, "hunk": at, "class": kind, "reasons": sorted(reasons)})
    return out


def _declarations(reader, commit, vocab, change):
    """The visit's `measurement_changes` entries whose evidence exists at the commit."""
    field = (vocab.data.get("declaration") or {}).get("field") or "measurement_changes"
    report = _json(reader.show(commit, REPORT)) or {}
    entries = report.get(field) if isinstance(report, dict) else None
    out = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or entry.get("flag") not in PATTERNS:
            continue
        evidence = []
        for ref in entry.get("evidence") or []:
            if not isinstance(ref, dict) or not isinstance(ref.get("file"), str):
                continue
            line = ref.get("line")
            text = reader.show(commit, ref["file"])
            if text is None or not isinstance(line, int) or isinstance(line, bool) \
                    or not 1 <= line <= len(text.splitlines()):
                continue
            evidence.append({"file": ref["file"], "line": line,
                             "text": text.splitlines()[line - 1].strip()[:200]})
        player_effect = entry.get("player_effect")
        if evidence and isinstance(player_effect, str) and player_effect.strip():
            out.append({"flag": entry["flag"], "where": str(entry.get("where") or ""),
                        "evidence": evidence, "player_effect": player_effect.strip()})
    return out


def _declared(flag, declarations, vocab):
    for entry in declarations:
        if entry["flag"] != flag["pattern"]:
            continue
        where = entry["where"]
        if where and not (where == flag["where"] or flag["where"].startswith(where + "#")
                          or where == flag["file"]):
            continue
        if flag["pattern"] == "unread-content-field":
            # Cleared only by the line that reads it: game source naming the key.
            if any(vocab.is_source(e["file"]) and flag["key"] in e["text"]
                   for e in entry["evidence"]):
                return "cleared", entry
            continue
        return "declared", entry
    return None, None


def precheck(reader, commit, specialist, base=None, vocabulary=None):
    """One specialist commit: {commit, base, owner, dimension, findings, hunks, flags,
    skipped}. `specialist` is the commit's brief `specialist` block."""
    vocab = vocabulary or Vocabulary.load()
    base = base or reader.parent(commit)
    findings = [f for f in (specialist or {}).get("findings") or [] if isinstance(f, dict)]
    result = {"commit": commit, "base": base, "owner": (specialist or {}).get("role"),
              "dimension": next((f.get("dimension") for f in findings if f.get("dimension")),
                                None),
              "findings": [f.get("id") for f in findings], "hunks": [], "flags": [],
              "skipped": {}}
    if not base:
        result["skipped"]["*"] = "the commit has no parent to compare with"
        return result
    change = _Commit(reader, vocab, commit, base)
    checks = {"unread-content-field": _unread_fields, "play-area-change": _play_area,
              "probe-path-change": _probe_paths,
              "sprite-size-without-collider": _sprite_sizes}
    flags = []
    for pattern in PATTERNS:
        applies, why = vocab.applies(pattern, findings)
        if not applies:
            result["skipped"][pattern] = why
            continue
        flags.extend(checks[pattern](change))
    declarations = _declarations(reader, commit, vocab, change) if flags else []
    for flag in flags:
        status, entry = _declared(flag, declarations, vocab)
        flag["status"] = status or "flagged"
        if entry:
            flag["declaration"] = entry
    result["flags"] = flags
    result["hunks"] = _classify(change, [f for f in flags if f["status"] != "cleared"])
    return result


def precheck_range(reader, base, head, vocabulary=None):
    """Every specialist commit in base..head: {vocabulary, commits: [precheck results]}. A
    commit is a specialist's when it changes the develop brief and that brief names one."""
    vocab = vocabulary or Vocabulary.load()
    out = {"vocabulary": vocab.ref, "base": base, "head": head, "commits": [],
           "truncated": False}
    commits = reader.commits(base, head)
    if len(commits) > MAX_COMMITS:
        out["truncated"] = True
        commits = commits[-MAX_COMMITS:]
    for commit in commits:
        if BRIEF not in reader.touched(commit):
            continue
        brief = _json(reader.show(commit, BRIEF)) or {}
        specialist = brief.get("specialist") if isinstance(brief, dict) else None
        if not isinstance(specialist, dict):
            continue
        out["commits"].append(precheck(reader, commit, specialist, vocabulary=vocab))
    return out


def blockers(result, vocabulary=None):
    """The review blockers the flags in a precheck_range result become: one per visit,
    pattern and file, `dimension` the visit's own so triage routes it back to the same
    owner."""
    vocab = vocabulary or Vocabulary.load()
    out, seen = [], {}
    for visit in (result or {}).get("commits") or []:
        grouped = {}
        for flag in visit.get("flags") or []:
            if flag.get("status") == "flagged":
                grouped.setdefault((flag["pattern"], flag["file"]), []).append(flag)
        for (pattern, path), flags in grouped.items():
            spec = vocab.patterns.get(pattern) or {}
            n = seen[pattern] = seen.get(pattern, 0) + 1
            blocker = {
                "id": f"{FLAG_PREFIX}{pattern}-{n}",
                "file": path,
                "summary": (f"Gate gaming ({pattern}) in {visit['commit'][:12]}, a "
                            f"{visit.get('owner') or 'specialist'} visit routed for "
                            + ", ".join(f"`{f}`" for f in visit.get("findings") or [])
                            + f": {spec.get('summary')} - "
                            + "; ".join(f["detail"] for f in flags) + ". Fix the "
                            "player-facing cause the finding describes. If the player "
                            "experiences this change, declare it in docs/development/"
                            "report.json `measurement_changes` with evidence "
                            "(docs/review-module.md)."),
                "severity": "blocker",
            }
            line = next((f["line"] for f in flags if f.get("line")), None)
            if line:
                blocker["line"] = line
            if visit.get("dimension"):
                blocker["dimension"] = visit["dimension"]
            out.append(blocker)
    return out


def visit_dimension(result):
    """The dimension of the newest specialist visit in a precheck_range result, or None."""
    for visit in reversed((result or {}).get("commits") or []):
        if visit.get("dimension"):
            return visit["dimension"]
    return None
