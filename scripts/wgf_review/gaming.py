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
                                  findings are about the game (code only added is a note)
    sprite-size-without-collider  a drawn size changed and the same entity's physical size
                                  did not: a draw constant, a draw size scaled from a
                                  collider, an asset frame or an image file made larger

A flag is a review blocker routed back to the visit's owner. The documented way out is a
declaration in the visit's docs/development/report.json `measurement_changes` naming the
flag, with evidence where the flagged change touched (docs/review-module.md): it clears an
unread field the evidence shows is read, and turns any other flag into a declared change the
reviewer judges. The reader is a
git object reader (GitReader over wgflib.isolation.Git), so the same check runs on a live
checkout and replays on any repository's history.
"""

import json
import os
import re
import shutil
import struct
import tarfile
import tempfile

from wgflib import paths
from wgflib.yamllite import load_file

__all__ = ["Vocabulary", "GitReader", "precheck", "precheck_range", "blockers", "words",
           "recorded_visit", "image_size", "PATH", "FLAG_PREFIX", "PATTERNS"]

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
_GIT_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")
_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@ ?(.*)$")
# A JavaScript built-in that names a play-area word without being one: Math.floor.
_BUILTIN = re.compile(r"\bMath\s*\.\s*[A-Za-z_$][\w$]*")
_DECLARED = re.compile(
    r"(?:\b(?:const|let|var|class|interface|type|enum|function)\s+([A-Za-z_$][\w$]*))"
    r"|(?:^\s*(?:(?:export|readonly|static|private|public|protected)\s+)*"
    r"([A-Za-z_$][\w$.]*)\s*\??\s*[:=]\s*[{(\[])")
_IDENT_CHAIN = re.compile(r"[A-Za-z_$][\w$]*(?:\s*\??\.\s*[A-Za-z_$][\w$]*)*")


def words(text):
    """The lower-cased words of identifiers in `text`: snake_case, camelCase, kebab-case and
    dotted names split. `BALL_DRAW` -> ball, draw; `gridTop` -> grid, top."""
    return [w.lower() for w in _WORD.findall(text or "")]


def _code_words(text):
    """The identifier words of a source line's code: comment and built-ins (Math.floor) out."""
    return set(words(_BUILTIN.sub(" ", _code(text))))


def _stem(word):
    """A word without its plural: `units` and `unit` name one thing."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("es") and word[-3] in "sxz":
        return word[:-2]
    if len(word) > 2 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _related(these, those):
    return bool({_stem(w) for w in these} & {_stem(w) for w in those})


def image_size(data):
    """(width, height) of a PNG, GIF, WebP or JPEG file's bytes, or None."""
    if not data:
        return None
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
            return struct.unpack(">II", data[16:24])
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", data[6:10])
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            chunk = data[12:16]
            if chunk == b"VP8X":
                return (1 + int.from_bytes(data[24:27], "little"),
                        1 + int.from_bytes(data[27:30], "little"))
            if chunk == b"VP8 ":
                w, h = struct.unpack("<HH", data[26:30])
                return w & 0x3FFF, h & 0x3FFF
            if chunk == b"VP8L":
                bits = int.from_bytes(data[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            return None
        if data[:2] == b"\xff\xd8":
            at = 2
            while at + 9 < len(data):
                if data[at] != 0xFF:
                    at += 1
                    continue
                marker = data[at + 1]
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    h, w = struct.unpack(">HH", data[at + 5:at + 9])
                    return w, h
                at += 2 + struct.unpack(">H", data[at + 2:at + 4])[0]
    except struct.error:
        return None
    return None


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

    def is_asset_data(self, path):
        return self._under(path, "asset_data")

    def is_image(self, path):
        return (os.path.splitext(path)[1].lower() in (self.paths.get("image_extensions") or [])
                and not self.is_test(path) and not self.is_bookkeeping(path))

    def w(self, name):
        """A word list of the vocabulary, as a set."""
        return self.words.get(name) or set()

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
        check = set(words(str(source.get("check") or finding.get("id") or "")))
        said = set(words(" ".join(str(x) for x in (
            source.get("check"), finding.get("id"), finding.get("dimension"),
            finding.get("summary")) if x)))
        # `except_checks`: a check whose id names one of these is never of the category (a
        # `ui` check's text size or contrast is not an entity's size on screen).
        return [cid for cid, spec in self.categories.items()
                if said & set((spec or {}).get("words") or [])
                and not check & set((spec or {}).get("except_checks") or [])]

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

    def blob(self, rev, path):
        """The bytes of `path` at `rev`, or None. Through `git archive` into a scratch
        directory: the object reader decodes what git prints as text, which an image is not."""
        scratch = tempfile.mkdtemp(prefix="wgf-gaming-blob-")
        try:
            out = os.path.join(scratch, "blob.tar")
            result = self.git.run("archive", "--format=tar", "-o", out, rev, "--", path,
                                  check=False, raw=True)
            if not result.ok or not os.path.isfile(out):
                return None
            with tarfile.open(out) as tar:
                for member in tar.getmembers():
                    if member.isfile() and member.name == path:
                        handle = tar.extractfile(member)
                        return handle.read() if handle else None
            return None
        except (OSError, tarfile.TarError):
            return None
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

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
            # The header names the file even when no ---/+++ lines follow (a binary file).
            header = _GIT_HEADER.match(line)
            current = {"path": None, "old_path": None, "hunks": [],
                       "header_path": header.group(2) if header else None}
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
        entry["path"] = entry["path"] or entry["old_path"] or entry.pop("header_path", None)
        entry.pop("header_path", None)
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
    """{name: (numbers, line number, text, right-hand side)} of the hunk lines with `op` that
    assign a value."""
    out = {}
    for kind, text, old, new in lines:
        if kind != op:
            continue
        code = _code(text)
        match = _ASSIGN.match(code)
        if not match:
            continue
        out[match.group(1)] = (_NUMBER.findall(match.group(2)), new if op == "+" else old,
                               code.strip(), " ".join(match.group(2).split()))
    return out


def _declared_words(scope):
    """The words of the identifier the enclosing declaration of a line declares: `BALL` of
    `export const BALL = {` above `radius: 12,`. Never its comment."""
    for line in scope[:1]:
        match = _DECLARED.search(_code(line))
        if match:
            return set(words(match.group(1) or match.group(2)))
    return set()


# -- the check -----------------------------------------------------------------------------

class _Commit:
    """One commit's diff and the files the patterns read, from the reader."""

    def __init__(self, reader, vocabulary, commit, base):
        self.reader, self.vocab, self.commit, self.base = reader, vocabulary, commit, base
        self.files = parse_diff(reader.diff(base, commit))
        self.by_path = {entry["path"]: entry for entry in self.files if entry["path"]}
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

    def blob_pair(self, path):
        blob = getattr(self.reader, "blob", None)
        if blob is None:
            return None, None
        return blob(self.base, path), blob(self.commit, path)

    def touched(self, path, starts=None):
        """The new-file line numbers inside the commit's hunks of `path` (those starting at
        `starts`, when given): the lines the change touched and the context it was shown in."""
        out = set()
        for hunk in (self.by_path.get(path) or {}).get("hunks") or []:
            if starts and hunk["new_start"] not in starts:
                continue
            out.update(new for _, _, _, new in hunk["lines"] if new)
        return out

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


def _read_by_source(change, key, owners, content_file):
    """(file, line text) where game source reads `key`, or None. Read means: the key as a
    quoted string; or `.key` / `{ key } =` on a line that reads the path it was added at - the
    identifier before the dot, or a word of the line, names what the key was added under (its
    parent key, `owners`; plural or singular), or, for a key at the top of the file, the
    reading file names the content file. A `.count` on any other object is not a read."""
    quoted = re.compile(r"""(["'`])""" + re.escape(key) + r"\1")
    dotted = re.compile(r"\??\.\s*" + re.escape(key) + r"(?![\w$])")
    destructured = re.compile(r"\{[^{}]*(?<![\w$])" + re.escape(key)
                              + r"(?![\w$])[^{}]*\}\s*=")
    before = re.compile(r"([A-Za-z_$][\w$]*)\s*$")
    top = any(not owner for owner in owners)
    owner_words = set().union(*owners)
    name = os.path.basename(content_file)
    for path, text in change.grep(key):
        code = _code(text)
        if quoted.search(code):
            return path, text.strip()
        accessed = [before.search(code[:m.start()]) for m in dotted.finditer(code)]
        if not accessed and not destructured.search(code):
            continue
        if any(m and _related(words(m.group(1)), owner_words) for m in accessed):
            return path, text.strip()  # `<what it was added under>.key`
        if _related(set(words(code)) - set(words(key)), owner_words):
            return path, text.strip()  # the line reads that path: `data.units[i].key`
        if top and any(name in line for line in change.lines(change.commit, path)):
            return path, text.strip()  # a top-level key, in a file that loads this file
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
            owners = []
            for key_path in where:
                named = [k for k in _shape(key_path)[:-1] if k != "[]"]
                owners.append(frozenset(words(named[-1])) if named else frozenset())
            if _read_by_source(change, key, sorted(set(owners), key=sorted), path):
                continue
            shown = sorted({_dotted(_shape(p)) for p in where})[:MAX_WHERE]
            flags.append({"pattern": "unread-content-field", "file": path, "key": key,
                          "line": _added_line(entry, f'"{key}"'),
                          "hunks": _hunks_with(entry, lambda s, k=f'"{key}"': k in s),
                          "where": f"{path}#{key}",
                          "detail": f"`{key}` (added at {', '.join(shown)}; {len(where)} "
                                    f"place(s)) is read nowhere in game source - not as a "
                                    f"quoted key, nor as a property or a destructured name "
                                    f"of what it was added under"})
    return flags


def _play_area(change):
    """Play area, bounds or colliders changed. A word of `play_area` names it on its own; a
    word of `play_area_context` (floor, margin, top, width, ...) only as what a play-area
    object's value is: a simulation source line that assigns it (`board.margin = 40`, or
    `width: 600` inside `const BOARD = {`), or a content value's key path (a unit's
    `layout.top` is its play space, whatever the key is named). Reading `BOARD.width` to
    place something is not changing it."""
    vocab, flags = change.vocab, []
    terms, context = vocab.w("play_area"), vocab.w("play_area_context")
    objects = vocab.w("play_area_objects")
    data_objects = objects | vocab.w("play_area_data_objects")

    def source_hit(text, render, scope):
        if _code_words(text) & terms:
            return True
        match = None if render else _ASSIGN.match(_BUILTIN.sub(" ", _code(text)))
        if not match:
            return False
        named = set(words(match.group(1)))
        return bool(named & context) and bool((named | _declared_words(scope())) & objects)

    for entry in change.files:
        path = entry["path"]
        if not path or vocab.is_test(path) or vocab.is_bookkeeping(path):
            continue
        hits, first, starts = [], None, []
        if vocab.is_size_data(path):
            before, after = change.json_pair(path)
            old, new = _leaves(before), _leaves(after)
            by_value = not vocab.is_asset_data(path)
            for leaf in sorted(set(old) | set(new)):
                if old.get(leaf) == new.get(leaf):
                    continue
                keys = [k for k in leaf if not k.startswith("[")]
                said = set(words(" ".join(keys)))
                last = set(words(keys[-1])) if keys else set()
                if said & terms or (by_value and last & context and said & data_objects):
                    hits.append(f"`{_dotted(leaf)}` {old.get(leaf)!r} -> {new.get(leaf)!r}")
        elif vocab.is_source(path):
            render = vocab.is_render(path)
            for hunk in entry["hunks"]:
                for op, text, old, new in hunk["lines"]:
                    if op != " " and source_hit(text, render, lambda op=op, old=old, new=new:
                                                change.scope(path, op, old, new)):
                        hits.append(f"{op}{new or old}: `{text.strip()[:100]}`")
                        first = first or (new if op == "+" else None)
                        if hunk["new_start"] not in starts:
                            starts.append(hunk["new_start"])
        if hits:
            if first is None:
                first = next((_added_line(entry, w) for w in sorted(terms)
                              if _added_line(entry, w)), None)
            flags.append({"pattern": "play-area-change", "file": path, "line": first,
                          "hunks": starts,
                          "where": path, "detail": "; ".join(hits[:MAX_WHERE])
                          + (f"; and {len(hits) - MAX_WHERE} more" if len(hits) > MAX_WHERE
                             else "")})
    return flags


def _probe_hunks(change):
    """[(path, hunk, matched words)] of source hunks with a changed line that is probe-,
    showcase- or bot-only: the line itself, the declaration it sits in or that
    declaration's comment names the probe (or the file's path does)."""
    vocab, out = change.vocab, []
    terms = vocab.w("probe")
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
    """A probe hunk that alters code the probe already had (a removed code line) is a flag:
    what it reported of an existing entity changed. One that only adds code - a new entity
    reported, a new showcase state - is a note for the reviewer when the vocabulary says so
    (`additions: note`)."""
    note_additions = (change.vocab.patterns.get("probe-path-change") or {}).get(
        "additions") == "note"
    flags, by_file = [], {}
    for path, hunk, found in _probe_hunks(change):
        alters = any(op == "-" and _code(text).strip() for op, text, _, _ in hunk["lines"])
        line = next((n for op, _, _, n in hunk["lines"] if op == "+"), None)
        by_file.setdefault((path, alters or not note_additions), []).append((hunk, found, line))
    for (path, alters), hunks in by_file.items():
        detail = "; ".join(f"hunk at {h['new_start']} ({', '.join(f)})" for h, f, _ in
                           hunks[:MAX_WHERE])
        flag = {"pattern": "probe-path-change", "file": path, "line": hunks[0][2],
                "hunks": [h["new_start"] for h, _, _ in hunks], "where": path,
                "detail": detail + ("" if alters else
                                    " - code added only, nothing the probe already "
                                    "reported was changed")}
        if not alters:
            flag["note"] = True
        flags.append(flag)
    return flags


def _entity(names, vocab, *extra):
    """The words of `names` that say which entity: size, draw, collider and generic words
    out (and any `extra` word set)."""
    drop = (vocab.w("size") | vocab.w("draw") | vocab.w("collider") | vocab.w("physical_size")
            | vocab.w("generic"))
    for more in extra:
        drop |= more
    return frozenset(w for w in names if w not in drop and not w.isdigit())


def _collider_refs(expression, vocab):
    """The entities whose collider or radius an expression reads: `ball.radius * 5` ->
    {ball}. A width or height is not one (it may be the drawing's own)."""
    physical = vocab.w("collider") | {"radius", "diameter", "rad"}
    out = set()
    for match in _IDENT_CHAIN.finditer(expression or ""):
        said = set(words(match.group(0)))
        if said & physical and not said & vocab.w("draw"):
            entity = _entity(said, vocab)
            if entity:
                out.add(entity)
    return out


def _sized_objects(value, vocab, prefix=(), names=()):
    """{key path: (display width, display height, entity words)} of every object of an asset
    manifest or atlas descriptor with a width/height (or w/h): pixels over its `scale`."""
    out = {}
    if isinstance(value, dict):
        dims = []
        for keys in (("width", "w"), ("height", "h")):
            found = next((value[k] for k in keys if isinstance(value.get(k), (int, float))
                          and not isinstance(value.get(k), bool)), None)
            dims.append(found)
        scale = value.get("scale")
        scale = scale if isinstance(scale, (int, float)) and scale > 0 else 1
        if all(d is not None for d in dims):
            said = set(words(" ".join(list(prefix) + list(names))))
            out[prefix] = (dims[0] / scale, dims[1] / scale,
                           _entity(said, vocab, vocab.w("asset_structure")))
        for key, child in value.items():
            out.update(_sized_objects(child, vocab, prefix + (str(key),), names))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            named = names
            if isinstance(child, dict):
                named = names + tuple(str(child[k]) for k in ("id", "name", "filename")
                                      if isinstance(child.get(k), str))
            out.update(_sized_objects(child, vocab, prefix + (f"[{index}]",), named))
    return out


def _sprite_sizes(change):
    vocab = change.vocab
    size, draw = vocab.w("size"), vocab.w("draw")
    collider, physical_size = vocab.w("collider"), vocab.w("physical_size")
    # drawn: (path, name, stem, line, before, after, hunk, body known);
    # physical: the entities whose collider or physical size changed.
    drawn, physical = [], []
    for entry in change.files:
        path = entry["path"]
        if not path or vocab.is_test(path) or vocab.is_bookkeeping(path):
            continue
        if vocab.is_source(path):
            render = vocab.is_render(path)
            for hunk in entry["hunks"]:
                old, new = _assignments(hunk["lines"], "-"), _assignments(hunk["lines"], "+")
                for name in sorted(set(old) & set(new)):
                    o, n = old[name], new[name]
                    numbers_changed = bool(o[0] and n[0] and o[0] != n[0])
                    if not numbers_changed and o[3] == n[3]:
                        continue
                    named = set(words(name))
                    declared = _declared_words(change.scope(path, "+", None, n[1]))
                    if named & (collider | physical_size) and not render and not named & draw:
                        entity = _entity(named, vocab) or _entity(declared, vocab)
                        if entity:
                            physical.append(entity)
                    elif (named & size and (render or named & draw)) or (named & draw
                                                                          and render):
                        scaled = _collider_refs(n[3], vocab) if o[3] != n[3] else set()
                        for entity in scaled:
                            # Drawn from a collider: a changed factor is a drawing that is no
                            # longer the body's size.
                            drawn.append((path, name, entity, n[1], o[2], n[2],
                                          hunk["new_start"], True))
                        if numbers_changed and not scaled:
                            stem = _entity(named, vocab) or _entity(declared, vocab)
                            drawn.append((path, name, stem, n[1], o[2], n[2],
                                          hunk["new_start"], False))
        elif vocab.is_asset_data(path) and path.endswith(".json"):
            before, after = change.json_pair(path)
            old = _sized_objects(before, vocab)
            for key, (width, height, stem) in _sized_objects(after, vocab).items():
                if key not in old:
                    continue
                was_w, was_h, _ = old[key]
                if width > was_w or height > was_h:
                    drawn.append((path, _dotted(key), stem, None,
                                  f"{_dotted(key)} {was_w:g}x{was_h:g}",
                                  f"{width:g}x{height:g}", None, False))
        elif vocab.is_image(path):
            before, after = (image_size(b) for b in change.blob_pair(path))
            if before and after and (after[0] > before[0] or after[1] > before[1]):
                stem = _entity(set(words(os.path.splitext(os.path.basename(path))[0])), vocab,
                               vocab.w("asset_structure"))
                drawn.append((path, path, stem, None, f"{path} {before[0]}x{before[1]}",
                              f"{after[0]}x{after[1]} (a larger file; a higher-resolution "
                              f"drawing shown at the same size is declared)", None, False))
        elif vocab.is_size_data(path):
            before, after = change.json_pair(path)
            old, new = _leaves(before), _leaves(after)
            for leaf in set(old) & set(new):
                if old[leaf] == new[leaf] or not isinstance(new[leaf], (int, float)):
                    continue
                named = set(words(" ".join(leaf)))
                last = set(words(leaf[-1]))
                if (last & collider or (last & physical_size and vocab.is_content(path))) \
                        and not named & draw:
                    keys = [k for k in leaf if not k.startswith("[")]
                    entity = _entity(last, vocab) or _entity(
                        set(words(keys[-2])) if len(keys) > 1 else set(), vocab)
                    if entity:
                        physical.append(entity)
                elif named & size and (named & draw or leaf[-1] == "scale"):
                    drawn.append((path, _dotted(leaf), _entity(named, vocab), None,
                                  old[leaf], new[leaf], None, False))
    flags = {}
    for path, name, stem, line, before, after, at, body in drawn:
        if not stem:
            continue  # no entity to hold the collider to
        if any(entity and entity <= stem for entity in physical):
            continue  # a collider or physical size of the same entity changed with it
        if not body and not _has_body(change, stem, size | collider, draw):
            continue  # nothing physical to be consistent with (an effect, a backdrop)
        flag = flags.setdefault(path, {"pattern": "sprite-size-without-collider",
                                       "file": path, "line": line, "where": path,
                                       "stems": set(), "detail": [], "hunks": []})
        flag["stems"].update(stem)
        if at is not None and at not in flag["hunks"]:
            flag["hunks"].append(at)
        said = f"`{before}` -> `{after}`"
        if said not in flag["detail"]:
            flag["detail"].append(said)
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
    """The visit's `measurement_changes` entries with a `where`, a `player_effect` and
    evidence lines that exist at the commit. Whether the evidence counts for a flag is
    `_declared`'s: it must be where the flagged change touched."""
    field = (vocab.data.get("declaration") or {}).get("field") or "measurement_changes"
    report = _json(reader.show(commit, REPORT)) or {}
    entries = report.get(field) if isinstance(report, dict) else None
    out = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or entry.get("flag") not in PATTERNS:
            continue
        where = entry.get("where")
        if not isinstance(where, str) or not where.strip():
            continue  # a declaration names what it declares; an empty one declares nothing
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
            out.append({"flag": entry["flag"], "where": where.strip(),
                        "evidence": evidence, "player_effect": player_effect.strip()})
    return out


def _counts(ref, flag, change):
    """Whether one evidence line is where the flagged change touched: a line of the flagged
    file inside a flagged hunk (anywhere the commit changed it, for a flag that names no
    hunk), or a line of game source inside a hunk of the same commit."""
    vocab = change.vocab
    if ref["file"] == flag["file"] and ref["line"] in change.touched(
            flag["file"], set(flag.get("hunks") or []) or None):
        return True
    return vocab.is_source(ref["file"]) and ref["line"] in change.touched(ref["file"])


def _declared(flag, declarations, change):
    vocab = change.vocab
    for entry in declarations:
        if entry["flag"] != flag["pattern"]:
            continue
        where = entry["where"]
        if not (where == flag["where"] or where == flag["file"]
                or flag["where"].startswith(where + "#")):
            continue
        evidence = [ref for ref in entry["evidence"] if _counts(ref, flag, change)]
        if not evidence:
            continue
        entry = dict(entry, evidence=evidence)
        if flag["pattern"] == "unread-content-field":
            # Cleared only by the line that reads it: game source the commit touched, naming
            # the key in code.
            name = re.compile(r"(?<![\w$])" + re.escape(flag["key"]) + r"(?![\w$])")
            if any(vocab.is_source(ref["file"]) and name.search(_code(ref["text"]))
                   for ref in evidence):
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
        if flag.pop("note", False):
            flag["status"] = "noted"  # the reviewer judges it; never a blocker by itself
            continue
        status, entry = _declared(flag, declarations, change)
        flag["status"] = status or "flagged"
        if entry:
            flag["declaration"] = entry
    result["flags"] = flags
    result["hunks"] = _classify(change, [f for f in flags if f["status"] != "cleared"])
    return result


def recorded_visit(develop_brief, prototype):
    """The specialist visit the develop step recorded for the build under review, as
    precheck_range's `recorded`: {base, head, specialist}, or None. `prototype` is the
    prototype-report (its `specialist` and `build_ref.commit_sha`), `develop_brief` the
    visit's docs/development/brief.json (its `baseline_commit`, and its `specialist` block
    when it names the same role - the routed findings in full)."""
    record = (prototype or {}).get("specialist")
    if not isinstance(record, dict) or not record.get("role"):
        return None
    head = ((prototype or {}).get("build_ref") or {}).get("commit_sha")
    base = (develop_brief or {}).get("baseline_commit")
    if not head or not base or base == head:
        return None
    spec = (develop_brief or {}).get("specialist")
    if not (isinstance(spec, dict) and spec.get("role") == record["role"]):
        spec = {"role": record["role"],
                "findings": [{"id": f} for f in record.get("findings") or []
                             if isinstance(f, str)]}
    return {"base": base, "head": head, "specialist": spec}


def precheck_range(reader, base, head, vocabulary=None, recorded=None):
    """Every specialist commit in base..head: {vocabulary, commits: [precheck results],
    truncated, commits_in_range}. A commit is a specialist's when it changes the develop
    brief and that brief names one, or when it is inside the range the develop step recorded
    for a specialist visit (`recorded`, from recorded_visit): a visit whose brief is
    byte-identical to the one before it is still that visit."""
    vocab = vocabulary or Vocabulary.load()
    out = {"vocabulary": vocab.ref, "base": base, "head": head, "commits": [],
           "truncated": False}
    commits = reader.commits(base, head)
    out["commits_in_range"] = len(commits)
    if len(commits) > MAX_COMMITS:
        out["truncated"] = True
        commits = commits[-MAX_COMMITS:]
    in_record = set()
    if recorded and isinstance(recorded.get("specialist"), dict):
        try:
            in_record = set(reader.commits(recorded["base"], recorded["head"]))
        except Exception as exc:  # noqa: BLE001 - a record git cannot read reads nothing
            out["recorded_unreadable"] = (f"{str(recorded.get('base'))[:12]}.."
                                          f"{str(recorded.get('head'))[:12]}: {exc}")[:300]
    for commit in commits:
        specialist, by_record = None, False
        if BRIEF in reader.touched(commit):
            brief = _json(reader.show(commit, BRIEF)) or {}
            specialist = brief.get("specialist") if isinstance(brief, dict) else None
        if commit in in_record:
            specialist, by_record = recorded["specialist"], True
        if not isinstance(specialist, dict):
            continue
        visit = precheck(reader, commit, specialist, vocabulary=vocab)
        if by_record:
            visit["recorded"] = True
        out["commits"].append(visit)
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
