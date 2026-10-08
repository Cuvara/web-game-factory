"""The versions a run's knowledge is judged by, recorded so a run says what it was held to.

    FILES                          {key: Factory-relative path} of the versioned files
    knowledge(read=None, root=None)
                                   {"lessons": "lessons@<v>", "check-tiers": "check-tiers@<v>"}
                                   - the seed a run records at start; raises KnowledgeError
                                   when either file is missing, unreadable, versionless, or
                                   not a knowledge file (no `lessons` list, no `sources`)
    collect(read=None, root=None, workflow=None, platforms=())
                                   every version of a knowledge-contract's `versions`
    factory(root=None)             {"version", "commit"} of the Factory checkout

`read(relpath) -> bytes` reads a Factory file; pass a run's pinned reader to record what the
run pinned rather than the live tree. The git commit is read from the checkout's files
(.git/HEAD and its ref), never by starting a process; an installed runtime has none (null).
"""

import hashlib
import os

from . import model

__all__ = ["FILES", "knowledge", "collect", "factory"]

FILES = {
    "lessons": "core/reference/lessons.yaml",
    "check_tiers": "core/reference/check-tiers.yaml",
    "quality_policy": "core/reference/quality-policy.yaml",
    "quality_benchmark": "core/reference/quality-benchmark.yaml",
    "quality_floor": "core/reference/quality-floor.yaml",
    "genre_models": "core/reference/genre-models.yaml",
}


def _root(root):
    if root:
        return root
    from wgflib import paths
    return paths.ROOT


def _default_reader(root):
    def read(relpath):
        with open(os.path.join(root, *relpath.split("/")), "rb") as handle:
            return handle.read()
    return read


def _parse(data, relpath):
    from wgflib.yamllite import load as load_yaml
    try:
        return load_yaml(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise model.KnowledgeError(f"{relpath} is not readable YAML ({exc})")


def _load(read, key):
    relpath = FILES[key]
    try:
        data = read(relpath)
    except (OSError, LookupError, ValueError) as exc:
        raise model.KnowledgeError(f"{relpath} cannot be read ({exc})")
    if isinstance(data, str):
        data = data.encode("utf-8")
    return data, _parse(data, relpath)


def _sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def knowledge(read=None, root=None):
    """The knowledge versions a run records at start. Refuses (KnowledgeError) what a run
    must not start without: both files readable, versioned, and shaped as knowledge."""
    read = read or _default_reader(_root(root))
    _, lessons = _load(read, "lessons")
    _, tiers = _load(read, "check_tiers")
    if not isinstance(lessons, dict) or not isinstance(lessons.get("lessons"), list):
        raise model.KnowledgeError(f"{FILES['lessons']} has no `lessons` list")
    if not isinstance(tiers, dict) or not isinstance(tiers.get("sources"), dict):
        raise model.KnowledgeError(f"{FILES['check_tiers']} has no `sources`")
    out = {}
    for key, name, data in (("lessons", "lessons", lessons),
                            ("check_tiers", "check-tiers", tiers)):
        version = model.version_of(data)
        if version is None:
            raise model.KnowledgeError(f"{FILES[key]} has no version MAJOR.MINOR.PATCH")
        out[name] = f"{name}@{version}"
    return out


def _git_commit(root):
    """The checkout's HEAD commit from its files, or None (no checkout, a detached runtime,
    anything unreadable)."""
    dot = os.path.join(root, ".git")
    try:
        if os.path.isfile(dot):
            with open(dot, encoding="utf-8") as handle:
                line = handle.read().strip()
            if not line.startswith("gitdir:"):
                return None
            gitdir = line[len("gitdir:"):].strip()
            gitdir = gitdir if os.path.isabs(gitdir) else os.path.join(root, gitdir)
        elif os.path.isdir(dot):
            gitdir = dot
        else:
            return None
        common = gitdir
        commondir = os.path.join(gitdir, "commondir")
        if os.path.isfile(commondir):
            with open(commondir, encoding="utf-8") as handle:
                relative = handle.read().strip()
            common = relative if os.path.isabs(relative) else os.path.join(gitdir, relative)
        with open(os.path.join(gitdir, "HEAD"), encoding="utf-8") as handle:
            head = handle.read().strip()
        if not head.startswith("ref:"):
            return head if len(head) == 40 else None
        ref = head[len("ref:"):].strip()
        for base in (gitdir, common):
            path = os.path.join(base, *ref.split("/"))
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as handle:
                    return handle.read().strip() or None
        packed = os.path.join(common, "packed-refs")
        if os.path.isfile(packed):
            with open(packed, encoding="utf-8") as handle:
                for line in handle:
                    parts = line.strip().split(" ")
                    if len(parts) == 2 and parts[1] == ref:
                        return parts[0]
    except OSError:
        return None
    return None


def factory(root=None):
    root = _root(root)
    try:
        with open(os.path.join(root, "VERSION"), encoding="utf-8") as handle:
            version = handle.read().strip() or None
    except OSError:
        version = None
    return {"version": version, "commit": _git_commit(root)}


def _platform_versions(root, platforms):
    from wgflib.yamllite import load as load_yaml
    out = {}
    for platform in platforms or ():
        path = os.path.join(root, "core", "reference", "platforms", f"{platform}.yaml")
        try:
            with open(path, encoding="utf-8") as handle:
                data = load_yaml(handle.read()) or {}
        except (OSError, ValueError):
            out[platform] = None
            continue
        version = model.version_of(data)
        out[platform] = f"{platform}@{version}" if version else None
    return out


def collect(read=None, root=None, workflow=None, platforms=()):
    """The `versions` block of a knowledge-contract: the Factory's version and commit, the
    lessons and check-tiers versions with their digests, the quality policy, benchmark,
    floor and genre models versions, the workflow, and each targeted platform's profile."""
    root = _root(root)
    read = read or _default_reader(root)
    knowledge(read)                 # refuses what a run must not be judged by
    out = {"factory": factory(root)}
    for key in FILES:
        data, parsed = _load(read, key)
        version = model.version_of(parsed)
        if key in ("lessons", "check_tiers"):
            out[key] = {"version": version, "sha256": _sha(data)}
        else:
            out[key] = version
    out["workflow"] = ({"id": workflow.get("id"), "version": workflow.get("version")}
                       if isinstance(workflow, dict) else None)
    out["platform_profiles"] = _platform_versions(root, platforms)
    return out
