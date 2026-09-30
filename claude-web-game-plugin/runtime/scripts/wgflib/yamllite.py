"""A reader for the subset of YAML this repository actually contains.

The Factory ships no toolchain and no dependencies, which is a deliberate constraint: core/
must stay consumable by a provider that cannot execute anything, and a lockfile in a
markdown-and-JSON repository is permanent maintenance surface. But the lifecycle machines,
the gates, the roles and the reference data are all YAML, and anything that evaluates a
guard has to read them. check-integrity.py met that need with regular expressions; a state
machine runner cannot.

So: a parser for the subset in use, and a differential test against a real YAML
implementation (scripts/tests/test_yamllite.py, which checks every YAML file in both
repositories against the `yaml` package in web-game-template). The subset is

    block mappings and sequences        key: value / - item
    flow mappings and sequences         {a: 1, b: 2} / [a, b]
    block scalars                       | and > with - + chomping
    quoted and plain scalars            'a', "a", a
    null / true / false, ints, floats
    comments and blank lines

and explicitly not anchors, aliases, tags, multiple documents, complex keys, or flow
collections spanning lines. Encountering one raises rather than guessing, because a parser
that silently misreads a machine file produces a lifecycle that is subtly not the one in
the file - which is worse than not reading it at all.

The named risk: this breaks if someone writes YAML outside the subset. check-integrity.py
loads every YAML file through this module for exactly that reason, so the failure surfaces
on the command people already run, not midway through a transition.
"""

import re

__all__ = ["load", "load_file", "YamlError"]


class YamlError(ValueError):
    """The input is outside the subset this reader supports, or is malformed."""

    def __init__(self, message, line=None):
        super().__init__(f"line {line}: {message}" if line else message)
        self.line = line


class _Line:
    __slots__ = ("col", "text", "no")

    def __init__(self, col, text, no):
        self.col = col
        self.text = text
        self.no = no

    def is_item(self):
        return self.text == "-" or self.text.startswith("- ")


_INT = re.compile(r"^[-+]?[0-9]+$")
_FLOAT = re.compile(r"^[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)(?:[eE][-+]?[0-9]+)?$")
_BLOCK_HEADER = re.compile(r"^([|>])([-+]?)$")


def _quoted_spans(text):
    """The character ranges covered by quoted scalars.

    A quote only opens a quoted scalar where a value may begin - the start of the line, or
    just after `: `, `- `, `[`, `{` or `,`. Anywhere else it is an ordinary character, which
    is the difference between reading `portal's editorial bar` as a scalar and reading it as
    an unterminated string that swallows the rest of the line.
    """
    spans = []
    at_value_start = True
    index = 0
    while index < len(text):
        char = text[index]

        if char in " \t":
            index += 1
            continue

        if at_value_start and char in "'\"":
            start = index
            index += 1
            while index < len(text):
                if text[index] == "\\" and char == '"':
                    index += 2
                    continue
                if text[index] == char:
                    if char == "'" and text[index + 1 : index + 2] == "'":
                        index += 2
                        continue
                    break
                index += 1
            spans.append((start, min(index, len(text) - 1)))
            at_value_start = False
            index += 1
            continue

        if char in ",[{":
            at_value_start = True
        elif char == ":" and text[index + 1 : index + 2] in ("", " ", "\t"):
            at_value_start = True
        elif char == "-" and start_of_item(text, index):
            at_value_start = True
        else:
            at_value_start = False
        index += 1
    return spans


def start_of_item(text, index):
    """True when the `-` at `index` is a block sequence marker rather than a minus sign."""
    return text[:index].strip() == "" and text[index + 1 : index + 2] in ("", " ")


def _outside(spans, index):
    return not any(start <= index <= end for start, end in spans)


def _strip_comment(text):
    """Remove a trailing comment.

    A `#` only starts a comment at the start of the line or after whitespace; `a#b` is the
    scalar `a#b`, which is why this cannot be a split on the character alone.
    """
    spans = _quoted_spans(text)
    for index, char in enumerate(text):
        if char == "#" and (index == 0 or text[index - 1] in " \t") and _outside(spans, index):
            return text[:index]
    return text


def _scan(text):
    """Split the document into content lines, remembering raw lines for block scalars."""
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = []
    for number, original in enumerate(raw, 1):
        if original.strip().startswith("%"):
            raise YamlError("directives are outside the supported subset", number)
        if original.strip() in ("---", "..."):
            if lines:
                raise YamlError("multiple documents are outside the supported subset", number)
            continue
        stripped = _strip_comment(original).rstrip()
        if not stripped.strip():
            continue
        col = len(stripped) - len(stripped.lstrip())
        if "\t" in stripped[:col]:
            raise YamlError("tab used for indentation", number)
        lines.append(_Line(col, stripped.strip(), number))
    return lines, raw


def _key_colon(text):
    """The index of the colon separating `key: value`, or None if this is not a mapping.

    The colon must sit outside any quoted scalar and outside any flow collection, and be
    followed by a space or end of line - `title:design` is a qualified stage id, not a key.
    """
    spans = _quoted_spans(text)
    depth = 0
    for index, char in enumerate(text):
        if not _outside(spans, index):
            continue
        if char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == ":" and depth == 0 and text[index + 1 : index + 2] in ("", " ", "\t"):
            return index
    return None


def _split_key(text, number):
    index = _key_colon(text)
    if index is None:
        raise YamlError(f"expected 'key: value', got {text!r}", number)
    return text[:index].strip(), text[index + 1 :].strip()


def _unquote(text, number):
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    if len(text) >= 2 and text[0] == text[-1] == '"':
        body = text[1:-1]
        out = []
        index = 0
        while index < len(body):
            char = body[index]
            if char == "\\":
                index += 1
                if index >= len(body):
                    raise YamlError("string ends in a backslash", number)
                escape = body[index]
                mapped = {
                    "n": "\n", "t": "\t", "r": "\r", "0": "\0", "b": "\b",
                    '"': '"', "\\": "\\", "/": "/",
                }
                if escape in mapped:
                    out.append(mapped[escape])
                elif escape == "u":
                    out.append(chr(int(body[index + 1 : index + 5], 16)))
                    index += 4
                else:
                    raise YamlError(f"unsupported escape \\{escape}", number)
            else:
                out.append(char)
            index += 1
        return "".join(out)
    return None


def _scalar(text, number):
    """Interpret one plain, quoted or flow scalar."""
    text = text.strip()
    if text == "":
        return None

    unquoted = _unquote(text, number)
    if unquoted is not None:
        return unquoted

    if text[0] in "[{":
        return _flow(text, number)
    if text[0] in "&*!":
        raise YamlError("anchors, aliases and tags are outside the supported subset", number)

    if text in ("null", "Null", "NULL", "~"):
        return None
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    if _INT.match(text):
        return int(text)
    if _FLOAT.match(text):
        return float(text)
    return text


def _flow(text, number):
    value, index = _flow_node(text, 0, number)
    if text[index:].strip():
        raise YamlError(f"trailing content after flow collection: {text[index:]!r}", number)
    return value


def _flow_node(text, index, number):
    while index < len(text) and text[index] in " \t":
        index += 1
    if index >= len(text):
        raise YamlError("flow collection ends early", number)
    if text[index] == "[":
        return _flow_seq(text, index, number)
    if text[index] == "{":
        return _flow_map(text, index, number)
    return _flow_scalar(text, index, number)


def _flow_scalar(text, index, number):
    start = index
    quote = None
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char in ",]}":
            break
        index += 1
    return _scalar(text[start:index], number), index


def _flow_seq(text, index, number):
    items = []
    index += 1
    while True:
        while index < len(text) and text[index] in " \t":
            index += 1
        if index >= len(text):
            raise YamlError("unterminated flow sequence", number)
        if text[index] == "]":
            return items, index + 1
        value, index = _flow_node(text, index, number)
        items.append(value)
        while index < len(text) and text[index] in " \t":
            index += 1
        if index < len(text) and text[index] == ",":
            index += 1
        elif index < len(text) and text[index] == "]":
            return items, index + 1
        elif index >= len(text):
            raise YamlError("unterminated flow sequence", number)


def _flow_map(text, index, number):
    mapping = {}
    index += 1
    while True:
        while index < len(text) and text[index] in " \t":
            index += 1
        if index >= len(text):
            raise YamlError("unterminated flow mapping", number)
        if text[index] == "}":
            return mapping, index + 1

        start = index
        quote = None
        while index < len(text):
            char = text[index]
            if quote:
                if char == quote:
                    quote = None
            elif char in "'\"":
                quote = char
            elif char == ":":
                break
            elif char in ",}":
                raise YamlError("flow mapping entry has no value", number)
            index += 1
        key = _scalar(text[start:index], number)
        index += 1  # the colon

        value, index = _flow_node(text, index, number)
        mapping[key] = value

        while index < len(text) and text[index] in " \t":
            index += 1
        if index < len(text) and text[index] == ",":
            index += 1
        elif index < len(text) and text[index] == "}":
            return mapping, index + 1
        elif index >= len(text):
            raise YamlError("unterminated flow mapping", number)


def _block_scalar(raw, start_number, key_col, style, chomp):
    """Gather a `|` or `>` scalar from the raw lines following its header."""
    body = []
    index = start_number  # raw is 0-based, start_number is the 1-based header line
    while index < len(raw):
        line = raw[index]
        if line.strip() == "":
            body.append("")
            index += 1
            continue
        col = len(line) - len(line.lstrip())
        if col <= key_col:
            break
        body.append(line)
        index += 1

    trailing_blanks = 0
    while body and body[-1] == "":
        body.pop()
        trailing_blanks += 1
    if not body:
        return "", index

    indent = min(len(l) - len(l.lstrip()) for l in body if l.strip())
    stripped = [l[indent:] if l.strip() else "" for l in body]

    if style == "|":
        text = "\n".join(stripped)
    else:
        # Folded: blank lines become newlines, and a line that is *more* indented than the
        # block keeps its own line rather than being folded into the previous one.
        out = []
        for line in stripped:
            more_indented = line[:1] in (" ", "\t")
            if line == "":
                out.append(("break", ""))
            elif more_indented:
                out.append(("literal", line))
            else:
                out.append(("fold", line))
        text = ""
        previous = None
        for kind, line in out:
            if previous is None:
                text = line
            elif kind == "break":
                text += "\n"
            elif previous == "break" or kind == "literal" or previous == "literal":
                text += "\n" + line if not text.endswith("\n") else line
            else:
                text += " " + line
            previous = kind

    if chomp == "-":  # strip: no trailing newline at all
        return text, index
    if chomp == "+":  # keep: the final newline plus every blank line that followed
        return text + "\n" * (1 + trailing_blanks), index
    return text + "\n", index  # clip: exactly one trailing newline


class _Parser:
    def __init__(self, lines, raw):
        self.lines = lines
        self.raw = raw
        self.index = 0

    def at_end(self):
        return self.index >= len(self.lines)

    def peek(self):
        return self.lines[self.index]

    def parse_document(self):
        if self.at_end():
            return None
        value = self.parse_block(self.peek().col)
        if not self.at_end():
            line = self.peek()
            raise YamlError(f"unexpected content {line.text!r}", line.no)
        return value

    def parse_block(self, col):
        if self.at_end() or self.peek().col < col:
            return None
        return self.parse_seq(col) if self.peek().is_item() else self.parse_map(col)

    def parse_seq(self, col):
        items = []
        while not self.at_end() and self.peek().col == col and self.peek().is_item():
            line = self.peek()
            content = line.text[2:].strip() if line.text != "-" else ""
            if content == "":
                self.index += 1
                items.append(self.parse_child(col))
            elif _key_colon(content) is None:
                # A plain or flow scalar: `- core/roles/research.md`, `- [a, b]`. Only an
                # item that actually opens a mapping may absorb the lines below it.
                self.index += 1
                items.append(_scalar(self.continued(content, line.col, line.no), line.no))
            else:
                # Re-enter the item's content as a line of its own, indented to where the
                # content actually starts. `- key: value` followed by more keys at that
                # column is then just a mapping, with no special case.
                inner = line.col + 2
                self.lines[self.index] = _Line(inner, content, line.no)
                items.append(self.parse_block(inner))
        return items

    def parse_map(self, col):
        mapping = {}
        while not self.at_end() and self.peek().col == col and not self.peek().is_item():
            line = self.peek()
            key, rest = _split_key(line.text, line.no)
            key = _scalar(key, line.no)

            header = _BLOCK_HEADER.match(rest)
            if header:
                style, chomp = header.groups()
                self.index += 1
                value, consumed_to = _block_scalar(self.raw, line.no, line.col, style, chomp)
                while not self.at_end() and self.peek().no <= consumed_to:
                    self.index += 1
                mapping[key] = value
                continue

            if rest == "":
                self.index += 1
                mapping[key] = self.parse_child(col)
            else:
                self.index += 1
                mapping[key] = _scalar(self.continued(rest, line.col, line.no), line.no)
        return mapping

    def continued(self, text, col, line_no):
        """Absorb the continuation lines of a multi-line plain scalar.

        A plain scalar runs on across lines that are more indented than the key that owns
        it and do not themselves open a mapping or a sequence. Lines fold together with a
        space; a blank line between them folds to a newline instead.

        Quoted and flow scalars are left alone - they have their own continuation rules,
        and nothing in this repository spreads one across lines.
        """
        if text[:1] in ("'", '"', "[", "{"):
            return text

        parts = [text]
        previous = line_no
        while not self.at_end():
            nxt = self.peek()
            if nxt.col <= col or nxt.is_item() or _key_colon(nxt.text) is not None:
                break
            blank_between = any(
                self.raw[number - 1].strip() == ""
                for number in range(previous + 1, nxt.no)
            )
            parts.append(("\n" if blank_between else " ") + nxt.text)
            previous = nxt.no
            self.index += 1
        return "".join(parts)

    def parse_child(self, col):
        """The block that belongs to a key or dash on the line just consumed."""
        if self.at_end():
            return None
        nested = self.peek()
        if nested.col > col:
            return self.parse_block(nested.col)
        # A sequence may sit at the same column as the key that owns it.
        if nested.col == col and nested.is_item():
            return self.parse_seq(col)
        return None


def load(text):
    """Parse a YAML document into Python values."""
    lines, raw = _scan(text)
    return _Parser(lines, raw).parse_document()


def load_file(path):
    with open(path, encoding="utf-8") as handle:
        return load(handle.read())
