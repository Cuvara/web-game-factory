"""What is inside a release package, and whether it may ship.

A package is a zip the game repository's own `release:package` script wrote. The Factory
never builds or rewrites one; it opens it and checks what a portal would receive:

    index.html at the archive root     a portal serves the archive root; nothing else loads
    no sourcemaps (*.map)               they hand the readable source to anyone who unzips it
    no test files                       suites, specs, test configs and reports are not the game
    no environment or secret files      .env, keys, keystores, credential files
    no secret-looking content           private keys and token/credential literals in text
    no unsafe entry names               absolute paths or `..` escape the extraction root

Platform-agnostic: the rules are the same for every target, and none is named here.
"""

import hashlib
import os
import re
import time
import zipfile

__all__ = ["audit_package", "content_digest", "file_sha256", "RULES"]

RULES = (
    "index.html at the archive root",
    "no sourcemaps (*.map)",
    "no test files",
    "no environment or secret files",
    "no secret-looking content",
    "no absolute or parent-relative entry names",
)

_SOURCEMAP = re.compile(r"\.map$", re.I)
_TEST = re.compile(
    r"(^|/)(__tests__|__mocks__|tests?|e2e|specs?|test-results|playwright-report|coverage)/"
    r"|\.(test|spec)\.[cm]?[jt]sx?$"
    r"|(^|/)(playwright|vitest|jest|karma|cypress)(\.[\w-]+)?\.config\.[cm]?[jt]s$", re.I)
_SECRET_FILE = re.compile(
    r"(^|/)\.env(\.[^/]*)?$"
    r"|\.(pem|key|p12|pfx|jks|keystore|ppk)$"
    r"|(^|/)(id_rsa|id_dsa|id_ecdsa|id_ed25519)(\.pub)?$"
    r"|(^|/)(credentials|secrets?|service-account)(\.[\w-]+)?\.(json|ya?ml|txt|ini)$"
    r"|(^|/)\.(npmrc|netrc|pgpass|htpasswd)$", re.I)
# Deliberately specific: a false positive stops a release, so each pattern is a shape that
# is a credential by construction, plus assignments to names that only ever hold one.
_SECRET_CONTENT = (
    ("private key", re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
    ("cloud access key id", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("source-host token", re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b")),
    ("chat bot token", re.compile(rb"\bxox[abposr]-[A-Za-z0-9-]{10,}\b")),
    ("live payment key", re.compile(rb"\b[rs]k_live_[A-Za-z0-9]{16,}\b")),
    ("credential assignment", re.compile(
        rb"(?i)\b(?:api[_-]?secret|secret[_-]?key|client[_-]?secret|access[_-]?token|"
        rb"auth[_-]?token|refresh[_-]?token|private[_-]?key|password|passwd)[\"']?\s*[:=]\s*"
        rb"[\"'][^\"'\s]{12,}[\"']")),
)
_TEXT = re.compile(r"\.(html?|[cm]?js|css|json|txt|xml|svg|ya?ml|md|map|webmanifest|csv|ini|"
                   r"env|conf|cfg)$|(^|/)\.[^/]+$", re.I)
_SCAN_LIMIT = 32 * 1024 * 1024


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def content_digest(entries):
    """sha256 over (name, sha256(bytes)) in name order: what ships, whatever the archive's
    timestamps or compression."""
    outer = hashlib.sha256()
    for name, digest in sorted(entries):
        outer.update(name.encode("utf-8") + b"\0" + digest)
    return "sha256:" + outer.hexdigest()


def _follows_mtime(info, source_dir):
    """Whether an entry's timestamp is its source file's modification time (zip stores local
    time at two-second resolution)."""
    source = os.path.join(source_dir, *info.filename.split("/"))
    try:
        mtime = os.stat(source).st_mtime
    except OSError:
        return None
    try:
        stamped = time.mktime(tuple(info.date_time) + (0, 0, -1))
    except (OverflowError, ValueError):
        return None
    return abs(stamped - mtime) <= 2


def audit_package(path, source_dir=None):
    """{"files", "content_digest", "index_at_root", "findings": [(rule, entry, detail)],
    "timestamps"}. `source_dir` is the bundle the archive was made from: with it, the audit
    can say whether entry timestamps follow the files' modification times ("file-mtimes"),
    which makes the archive bytes change on every rebuild, or are fixed ("normalized")."""
    findings = []
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        return {"files": 0, "content_digest": None, "index_at_root": False,
                "findings": [("readable archive", path, str(exc))], "timestamps": "unknown"}
    entries = []
    stamps = set()
    follows = []
    with archive:
        infos = [i for i in archive.infolist() if not i.is_dir()]
        names = {i.filename for i in infos}
        for info in infos:
            name = info.filename
            if name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name) \
                    or ".." in re.split(r"[\\/]", name):
                findings.append(("no absolute or parent-relative entry names", name, ""))
            if _SOURCEMAP.search(name):
                findings.append(("no sourcemaps (*.map)", name, ""))
            if _TEST.search(name):
                findings.append(("no test files", name, ""))
            if _SECRET_FILE.search(name):
                findings.append(("no environment or secret files", name, ""))
            try:
                data = archive.read(info)
            except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
                findings.append(("readable archive", name, str(exc)))
                continue
            entries.append((name, hashlib.sha256(data).digest()))
            stamps.add(tuple(info.date_time))
            if source_dir:
                follows.append(_follows_mtime(info, source_dir))
            if _TEXT.search(name) and len(data) <= _SCAN_LIMIT:
                for label, pattern in _SECRET_CONTENT:
                    if pattern.search(data):
                        findings.append(("no secret-looking content", name, label))
        index = "index.html" in names
        if not index:
            findings.append(("index.html at the archive root", "index.html",
                             "not at the root" + (" (found nested)" if any(
                                 n.endswith("/index.html") for n in names) else "")))
    return {"files": len(entries), "content_digest": content_digest(entries),
            "index_at_root": index, "findings": findings,
            "timestamps": _timestamps(stamps, follows)}


def _timestamps(stamps, follows):
    if follows and all(follows):
        return "file-mtimes"
    if len(stamps) <= 1:
        return "normalized"
    return "unknown"
