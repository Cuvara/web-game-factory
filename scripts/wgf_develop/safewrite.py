"""Writing the Factory's own files into the game checkout without following the developer's links.

The develop step writes into the checkout the developer works in: the brief, docs/GDD.md, the
integration seam, docs/development/checks.json. A plain open(path, "w") follows a symbolic
link, and truncates a hard link's shared file: a developer who left `docs/GDD.md ->
<the Factory>/core/...` (or a link to the run's own event log) had the Factory overwrite that
file for it - after the guarded paths were last compared, or before they were first
fingerprinted - with its own permissions, outside any sandbox the developer ran in.

`write_text` refuses a path whose directories inside the checkout are anything but real
directories, and replaces the file's directory entry instead of writing through it: the text
goes to a new file in the same directory, then os.replace renames it over the target. A link
at the target is replaced, never followed, and a hard-linked file elsewhere is left alone.

Nothing else writes the checkout while this runs: the developer's and every check's process
tree has been ended (wgflib.procs) before the step writes here.
"""

import os
import stat
import tempfile

__all__ = ["UnsafeCheckoutPath", "write_text", "regular_file_problem"]


class UnsafeCheckoutPath(Exception):
    """A Factory file's place in the checkout is not a plain file in plain directories."""


def _inside(root, path):
    relative = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
    if relative == os.curdir or relative.startswith(os.pardir + os.sep) or \
            relative == os.pardir or os.path.isabs(relative):
        raise UnsafeCheckoutPath(f"{path} is not inside the checkout {root}")
    return relative.split(os.sep)


def _directories(root, parts):
    """Create the missing directories of `parts[:-1]` under `root`; refuse any that exists
    as a link or as something other than a directory."""
    current = os.path.abspath(root)
    for part in parts[:-1]:
        current = os.path.join(current, part)
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            os.mkdir(current)
            continue
        if stat.S_ISLNK(info.st_mode):
            raise UnsafeCheckoutPath(
                f"{current} is a symbolic link; the Factory does not write through links in "
                f"the checkout")
        if not stat.S_ISDIR(info.st_mode):
            raise UnsafeCheckoutPath(f"{current} is not a directory")
    return current


def write_text(root, path, text):
    """Write `text` (UTF-8, \\n newlines) to `path`, which must be inside the checkout `root`,
    replacing whatever directory entry is there - never writing through it."""
    parts = _inside(root, path)
    directory = _directories(root, parts)
    target = os.path.join(directory, parts[-1])
    try:
        info = os.lstat(target)
    except FileNotFoundError:
        info = None
    if info is not None and stat.S_ISDIR(info.st_mode):
        raise UnsafeCheckoutPath(f"{target} is a directory")
    handle, temporary = tempfile.mkstemp(dir=directory, prefix=".wgf-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target


def regular_file_problem(root, relative):
    """Why `relative` in `root` is not a plain file with a single name, or None when it is
    (or does not exist)."""
    path = os.path.join(root, *relative.split("/"))
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        return "a symbolic link, not the file the Factory renders"
    if not stat.S_ISREG(info.st_mode):
        return "not a regular file"
    if info.st_nlink > 1:
        return "a hard link to another file"
    return None
