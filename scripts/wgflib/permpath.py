"""Paths an agent host's permission rule can name, and argv rendering that uses them.

Why this is in wgflib (a core change): three step modules (the design agent, the 2D set
author, the 3D model author) restrict an agent's writes to one file or one directory by a
rule in the host's argv, e.g. `Edit(/{draft})`. The placeholder was rendered as the native
path, and the rule only worked where the native path starts with `/`: on POSIX the
template's `/` plus `/home/...` gives `//home/...`, the host's form of an absolute path. On
Windows it gave `/C:\\Users\\...`, which a host that matches Windows paths in POSIX form
(`//c/Users/...`) reads as a path relative to the project and never matches - in a
don't-ask permission mode every write the author made was denied (finding F11).

`rule_path()` is the host-neutral answer: `//` followed by the absolute path in POSIX form,
with a Windows drive letter lower-cased (`C:\\a\\b` -> `//c/a/b`). `format_argv()` renders an
argv template, offering `{<key>_rule}` beside every path placeholder `{<key>}`, and reads the
legacy single-slash form `(/{key}` as `({key_rule}` - identical on POSIX, correct on
Windows - so a project's copy of an older profile keeps working. Standard library only.
"""

import os
import re

__all__ = ["rule_path", "rule_values", "format_argv"]

_DRIVE = re.compile(r"^([A-Za-z]):[\\/]?(.*)$", re.S)


def rule_path(path, *, windows=None):
    """`path` as a permission-rule absolute path: `//` + its POSIX form. `windows` forces
    the platform's reading of `path` (default: this host's)."""
    windows = (os.name == "nt") if windows is None else windows
    text = str(path)
    if windows:
        text = text.replace("\\", "/")
        match = _DRIVE.match(text)
        if match:
            return "//" + match.group(1).lower() + "/" + match.group(2).lstrip("/")
        if text.startswith("//"):          # a UNC path keeps its host
            return text
        return "/" + text if text.startswith("/") else "//" + text
    return "/" + text if text.startswith("/") else "//" + text


def rule_values(values, path_keys, *, windows=None):
    """`values` plus `{key}_rule` for every key of `path_keys` with a non-empty value."""
    out = dict(values)
    for key in path_keys:
        if values.get(key):
            out[key + "_rule"] = rule_path(values[key], windows=windows)
        else:
            out[key + "_rule"] = ""
    return out


def format_argv(argv, values, path_keys, *, windows=None):
    """Render each argv part with `values` and the `{key}_rule` forms of `path_keys`. The
    legacy `(/{key}` (one slash, then the native path) is read as `({key_rule}`. Raises
    what str.format raises on an unknown placeholder or a stray brace."""
    full = rule_values(values, path_keys, windows=windows)
    rendered = []
    for part in argv:
        for key in path_keys:
            part = part.replace("(/{%s}" % key, "({%s_rule}" % key)
        rendered.append(part.format(**full))
    return rendered
