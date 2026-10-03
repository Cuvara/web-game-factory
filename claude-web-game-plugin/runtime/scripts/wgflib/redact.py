"""Redaction: secrets never reach events.jsonl, an artifact, a log tail or a message.

Two mechanisms, applied together by `scrub`:

  * literal values a step registered (`register(value)`): a portal session cookie the
    publish step read from its environment, a storage-state file's contents. Anything that
    contains the value, or its URL-encoded or JSON-escaped form, has it replaced. Values
    shorter than MIN_LENGTH are not registered: replacing every "ok" in a log is noise, not
    protection;
  * patterns of things that are secrets by shape, whoever wrote them: Authorization and
    Cookie headers, bearer tokens, `token=`/`password=`/`secret=` assignments in text or
    JSON, API keys of the common vendor shapes, JSON web tokens, private key blocks.

`scrub(value)` walks dicts, lists and strings and returns a copy with REPLACEMENT in place
of each secret; keys named like a secret (TOKEN, SECRET, PASSWORD, COOKIE, AUTH, ...) have
their whole value replaced, whatever it is. `scrub_text(text)` is the string case.

Why here, in the kernel: the workflow event bus (wgflib/workflow/events.py) is the one
channel every step's messages, logger lines and progress reports go through on their way to
events.jsonl and the terminal, so a step that forgets is still covered. Artifacts are
scrubbed by the step that writes them, before sealing (a hash over scrubbed content is the
hash of what was written); a module that handles a credential calls `scrub` on every piece
of evidence it records. Redaction is text matching: it is the last line, not the first -
the first is an allowlisted environment (wgflib/agentenv.py) and a secret that is never
printed. Standard library only.
"""

import json
import re
import threading
from urllib.parse import quote

__all__ = ["REPLACEMENT", "MIN_LENGTH", "register", "forget", "registered", "scrub",
           "scrub_text", "secret_key"]

REPLACEMENT = "[REDACTED]"
MIN_LENGTH = 8

_lock = threading.Lock()
_values = []  # (literal, [forms...]) longest first, so a value inside another goes first

# A key whose value is a secret whatever it looks like.
_SECRET_KEY = re.compile(r"token|secret|passw(or)?d|credential|cookie|session[-_]?(id|state)?$"
                         r"|authorization|api[-_]?key|private[-_]?key|storage[-_]?state|bearer",
                         re.I)
# Keys that only sound like secrets: a `key` in a key-value pair, a `token` count.
_NOT_SECRET_KEY = re.compile(r"^(idempotency[-_]key|routing[-_]key|limit[-_]key|key|keys|"
                             r"max_turns|max_tokens|tokens?_used|token_count|input_tokens|"
                             r"output_tokens|public[-_]key)$", re.I)

_PATTERNS = [
    # Headers, in logs or request dumps.
    re.compile(r"(?i)(authorization\s*[:=]\s*)(\S.*?)(?=$|[\r\n])"),
    re.compile(r"(?i)((?:set-)?cookie\s*[:=]\s*)(\S.*?)(?=$|[\r\n])"),
    re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9\-._~+/]+=*)"),
    # key=value in text, query strings and dotenv: token=..., password=..., secret=...
    re.compile(r"(?i)\b((?:access[_-]?|refresh[_-]?|auth[_-]?|api[_-]?|session[_-]?)?"
               r"(?:token|secret|passw(?:or)?d|api[_-]?key|credentials?)\s*[=:]\s*)"
               r"([^\s&;,\"']{4,})"),
    # "token": "value" in JSON.
    re.compile(r"(?i)(\"(?:[a-z_-]*(?:token|secret|passw(?:or)?d|cookie|api[_-]?key|"
               r"storage[_-]?state)[a-z_-]*)\"\s*:\s*\")([^\"]{4,})(\")"),
    # Vendor-shaped keys and tokens.
    re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\b(xox[abposr]-[A-Za-z0-9-]{10,})\b"),
    re.compile(r"\b([rs]k_(?:live|test)_[A-Za-z0-9]{10,})\b"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{20,})\b"),
    re.compile(r"\b(eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]


def secret_key(name):
    """True when a mapping key names a secret by convention (its whole value is replaced)."""
    text = str(name)
    if _NOT_SECRET_KEY.match(text):
        return False
    return bool(_SECRET_KEY.search(text))


def _forms(value):
    forms = {value}
    forms.add(quote(value, safe=""))
    forms.add(json.dumps(value)[1:-1])  # the JSON-escaped body, without its quotes
    return sorted(forms, key=len, reverse=True)


def register(value):
    """Register a literal secret value. Short, empty and non-string values are ignored and
    False is returned; registering the same value twice is harmless."""
    if not isinstance(value, str) or len(value) < MIN_LENGTH or not value.strip():
        return False
    with _lock:
        if any(literal == value for literal, _ in _values):
            return True
        _values.append((value, _forms(value)))
        _values.sort(key=lambda entry: len(entry[0]), reverse=True)
    return True


def forget(value=None):
    """Forget one registered value, or every one (tests)."""
    with _lock:
        if value is None:
            _values.clear()
        else:
            _values[:] = [entry for entry in _values if entry[0] != value]


def registered():
    with _lock:
        return [literal for literal, _ in _values]


def scrub_text(text):
    """`text` with every registered value and every secret-shaped span replaced."""
    if not isinstance(text, str) or not text:
        return text
    with _lock:
        values = list(_values)
    for _literal, forms in values:
        for form in forms:
            if form in text:
                text = text.replace(form, REPLACEMENT)
    for pattern in _PATTERNS:
        if pattern.groups == 0:
            text = pattern.sub(REPLACEMENT, text)
        elif pattern.groups == 1:
            text = pattern.sub(REPLACEMENT, text)
        elif pattern.groups == 2:
            text = pattern.sub(lambda m: m.group(1) + REPLACEMENT, text)
        else:
            text = pattern.sub(lambda m: m.group(1) + REPLACEMENT + m.group(3), text)
    return text


def scrub(value):
    """A copy of `value` (str, dict, list, tuple, or anything JSON-like) with secrets
    replaced. Non-container, non-string values are returned as they are."""
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if secret_key(key) and item not in (None, "", REPLACEMENT):
                out[key] = REPLACEMENT
            else:
                out[key] = scrub(item)
        return out
    if isinstance(value, (list, tuple)):
        scrubbed = [scrub(item) for item in value]
        return scrubbed if isinstance(value, list) else tuple(scrubbed)
    return value
