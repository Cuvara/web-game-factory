"""Write tech_plan.repo_params.game_config into a project's game.config.yaml, in place.

The file is edited, never regenerated: its comments are the documentation for the fields
around them (the template's bootstrap workflow edits it in place for the same reason), and
everything init does not own - build, verification, publishing, anything a later template
version adds - must survive byte for byte. wgflib.yamllite only reads, so this is a
targeted, line-based rewrite of exactly these fields:

    engine.type                 always
    platforms                   always: the items are replaced, comments in the list kept
    monetization.ad_kinds/.iap  when the plan carries monetization
    game.id / game.name         only when asked (local source: there is no bootstrap to set
                                them; on GitHub, bootstrap.yml sets them from the repository
                                name and init leaves them alone so the two never race)

and then proves itself: the result is parsed back, the written fields must read as the plan
says, and every other top-level key must parse exactly as it did before. A rewrite that
cannot show that raises GameConfigError instead of writing something subtly different.
"""

import json
import re

from wgflib.yamllite import YamlError, load

__all__ = ["GameConfigError", "apply_game_config", "bootstrap_identity", "plain_scalar"]

_TOP = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(.*)$")
_PLAIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@/+-]*$")
_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "~"}


class GameConfigError(ValueError):
    """game.config.yaml cannot be rewritten safely. Not transient."""


def plain_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    if _PLAIN.match(text) and text.lower() not in _RESERVED and text == text.strip() \
            and not re.match(r"^[0-9.+-]+$", text):
        return text
    return json.dumps(text)  # a double-quoted JSON string is a valid YAML scalar


def _flow_list(values):
    return "[" + ", ".join(plain_scalar(v) for v in values) + "]"


def _platform_line(indent, entry):
    return (f"{indent}- {{ id: {plain_scalar(entry['id'])}, "
            f"profile: {plain_scalar(entry['profile'])}, role: {plain_scalar(entry['role'])} }}\n")


def bootstrap_identity(repo_name):
    """(game_id, game_name) exactly as web-game-template's bootstrap.yml derives them."""
    game_id = re.sub(r"[^a-z0-9]+", "-", repo_name.lower()).strip("-")
    game_name = " ".join(w[:1].upper() + w[1:] for w in game_id.replace("-", " ").split())
    return game_id, game_name


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def _is_content(line):
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def _strip_value_comment(text):
    """(value, ' # comment' or '') for the text after a key's colon. Quotes are respected."""
    quote = None
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#" and (index == 0 or text[index - 1] in " \t"):
            return text[:index].rstrip(), " " + text[index:].rstrip("\n").rstrip()
    return text.rstrip("\n").rstrip(), ""


class _Document:
    def __init__(self, text):
        self.lines = text.splitlines(keepends=True)
        if self.lines and not self.lines[-1].endswith("\n"):
            self.lines[-1] += "\n"

    def text(self):
        return "".join(self.lines)

    def section(self, key):
        """(start, end) line indices of a top-level key and its body, or None."""
        start = None
        for index, line in enumerate(self.lines):
            match = _TOP.match(line)
            if match and start is None and match.group(1) == key:
                start = index
            elif match and start is not None:
                return start, index
        return (start, len(self.lines)) if start is not None else None

    def _ensure_section(self, key):
        found = self.section(key)
        if found:
            return found
        if self.lines and self.lines[-1].strip():
            self.lines.append("\n")
        self.lines.append(f"{key}:\n")
        return len(self.lines) - 1, len(self.lines)

    def _child_indent(self, start, end):
        for line in self.lines[start + 1:end]:
            if _is_content(line):
                return " " * _indent(line)
        return "  "

    def set_child(self, section, key, rendered):
        """Set `section.key` to an already-rendered scalar or flow value."""
        start, end = self._ensure_section(section)
        header_value, _ = _strip_value_comment(_TOP.match(self.lines[start]).group(2))
        if header_value:
            raise GameConfigError(f"game.config.yaml `{section}` is not a block mapping")
        indent = self._child_indent(start, end)
        pattern = re.compile(rf"^{re.escape(indent)}{re.escape(key)}:(.*)$", re.S)
        for index in range(start + 1, end):
            match = pattern.match(self.lines[index])
            if not match:
                continue
            _value, comment = _strip_value_comment(match.group(1))
            # A block value beneath the key (a block list, say) goes with the old value.
            last = index
            for probe in range(index + 1, end):
                line = self.lines[probe]
                if _is_content(line):
                    if _indent(line) <= len(indent):
                        break
                    last = probe
            self.lines[index:last + 1] = [f"{indent}{key}: {rendered}{comment}\n"]
            return
        # Absent: after the section's last content line.
        insert = start + 1
        for index in range(start + 1, end):
            if _is_content(self.lines[index]):
                insert = index + 1
        self.lines.insert(insert, f"{indent}{key}: {rendered}\n")

    def set_list(self, section, entries, render):
        """Replace the items of a top-level block sequence; comments inside it stay."""
        start, end = self._ensure_section(section)
        value, comment = _strip_value_comment(_TOP.match(self.lines[start]).group(2))
        if value:
            # `platforms: []` or a flow list on the key line: turn it into a block list.
            self.lines[start] = f"{section}:{comment}\n"
        indent, first, kept = "  ", None, []
        for index in range(start + 1, end):
            line = self.lines[index]
            if _is_content(line):
                if first is None:
                    first = len(kept)
                    indent = " " * _indent(line)
                continue  # an item line, or a continuation of a block-style item
            kept.append(line)
        if first is None:
            # No items: after the section's comments, before the blank lines that end it.
            first = len(kept)
            while first and not kept[first - 1].strip():
                first -= 1
        items = [render(indent, entry) for entry in entries]
        self.lines[start + 1:end] = kept[:first] + items + kept[first:]


def apply_game_config(text, game_config, identity=None):
    """The new text of game.config.yaml, or raise GameConfigError. `identity` is
    (game_id, game_name) to set too, or None to leave game.id and game.name alone."""
    try:
        before = load(text) or {}
    except YamlError as exc:
        raise GameConfigError(f"game.config.yaml does not parse: {exc}")
    if not isinstance(before, dict):
        raise GameConfigError("game.config.yaml is not a mapping")

    engine = (game_config.get("engine") or {}).get("type")
    platforms = game_config.get("platforms")
    if engine not in ("pixijs", "threejs"):
        raise GameConfigError(f"tech plan engine.type {engine!r} is not pixijs or threejs")
    if not isinstance(platforms, list) or not platforms:
        raise GameConfigError("tech plan game_config.platforms is empty")

    document = _Document(text)
    owned = {"engine", "platforms"}
    document.set_child("engine", "type", plain_scalar(engine))
    document.set_list("platforms", platforms, _platform_line)
    monetization = game_config.get("monetization")
    if isinstance(monetization, dict):
        owned.add("monetization")
        document.set_child("monetization", "ad_kinds",
                           _flow_list(monetization.get("ad_kinds") or []))
        if "iap" in monetization:
            document.set_child("monetization", "iap", plain_scalar(bool(monetization["iap"])))
    if identity:
        owned.add("game")
        document.set_child("game", "id", plain_scalar(identity[0]))
        document.set_child("game", "name", plain_scalar(identity[1]))
    result = document.text()

    try:
        after = load(result) or {}
    except YamlError as exc:
        raise GameConfigError(f"rewritten game.config.yaml does not parse: {exc}")
    expected_platforms = [{"id": p["id"], "profile": p["profile"], "role": p["role"]}
                          for p in platforms]
    problems = []
    if (after.get("engine") or {}).get("type") != engine:
        problems.append("engine.type")
    if after.get("platforms") != expected_platforms:
        problems.append("platforms")
    if isinstance(monetization, dict):
        written = after.get("monetization") or {}
        if written.get("ad_kinds") != list(monetization.get("ad_kinds") or []):
            problems.append("monetization.ad_kinds")
        if "iap" in monetization and written.get("iap") is not bool(monetization["iap"]):
            problems.append("monetization.iap")
    for key in ("engine", "monetization", "game"):
        # Within the sections init writes to, every other field survives.
        old, new = dict(before.get(key) or {}), dict(after.get(key) or {})
        for field in {"engine": ["type"], "monetization": ["ad_kinds", "iap"],
                      "game": ["id", "name"] if identity else []}[key]:
            old.pop(field, None)
            new.pop(field, None)
        if old != new:
            problems.append(f"{key} (other fields)")
    for key in set(before) | set(after):
        if key not in owned | {"game"} and before.get(key) != after.get(key):
            problems.append(key)
    if identity:
        game = after.get("game") or {}
        if (game.get("id"), game.get("name")) != tuple(identity):
            problems.append("game.id/name")
    if problems:
        raise GameConfigError("rewriting game.config.yaml would not read back as intended: "
                              + ", ".join(sorted(set(problems))))
    return result
