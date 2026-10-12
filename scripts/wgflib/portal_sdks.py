"""Portal SDKs in a built bundle: which portals' SDKs a platform's files carry, and whether
its page loads its own - measured from the files, deterministic, standard library only.

Two readers judge the same bundle by the same reference (core/reference/portal-sdks.yaml),
so the scan lives here rather than in either module:

  * the verify step (scripts/wgf_verification/checks/platform.py) scans each platform's
    bundle directory: `platform.foreign-sdk:<id>`, `platform.sdk-loaded:<id>`;
  * platform-validate (scripts/wgf_publish/validate.py) scans the package archive it would
    hand to the portal: guards `portal_sdk_isolated`, `portal_sdk_loaded`.

    scan_directory(dir) / scan_zip(path)   -> Scan: per portal, the signatures found and where
    foreign(scan, platform_id)              -> {portal: [signature (files)]} other than its own
    loader_status(scan, platform_id)        -> (declared, loaded, needs) for its own page script

Nothing here runs a build, a browser or a network request.
"""

import hashlib
import os
import re
import zipfile

from . import paths
from .yamllite import load_file

__all__ = ["REFERENCE", "TEXT_EXTENSIONS", "Reference", "Scan", "load", "scan_directory",
           "isolated_guard", "loaded_guard",
           "scan_zip", "scan_files", "foreign", "loader_status", "describe"]

REFERENCE = os.path.join(paths.REFERENCE, "portal-sdks.yaml")
TEXT_EXTENSIONS = (".html", ".htm", ".js", ".mjs", ".cjs", ".css", ".json", ".map", ".txt",
                   ".xml", ".svg", ".webmanifest")
INDEX_HTML = "index.html"


class Reference:
    """The parsed reference: per portal, compiled signatures and an optional loader."""

    def __init__(self, document, content_hash=None, path=None):
        document = document or {}
        self.version = str(document.get("version") or "")
        self.content_hash = content_hash
        self.path = path
        self.portals = {}
        for pid, entry in (document.get("portals") or {}).items():
            entry = entry if isinstance(entry, dict) else {}
            signatures = []
            for item in entry.get("signatures") or []:
                flags = re.I if item.get("ignore_case") else 0
                signatures.append((str(item["id"]), re.compile(str(item["pattern"]), flags)))
            loader = entry.get("loader") if isinstance(entry.get("loader"), dict) else None
            audit = entry.get("audit") if isinstance(entry.get("audit"), dict) else None
            self.portals[str(pid)] = {"signatures": signatures, "loader": loader,
                                      "audit": audit}

    @property
    def label(self):
        return f"portal-sdks@{self.version}" + (f" ({self.content_hash})"
                                                if self.content_hash else "")

    def loader(self, platform_id):
        return (self.portals.get(platform_id) or {}).get("loader")

    def audit(self, platform_id):
        """The template's own audit of this platform's bundle ({cli, report, check}), or
        None."""
        return (self.portals.get(platform_id) or {}).get("audit")


def load(path=None):
    """The reference at `path` (default core/reference/portal-sdks.yaml)."""
    path = path or REFERENCE
    with open(path, "rb") as handle:
        digest = "sha256:" + hashlib.sha256(handle.read()).hexdigest()
    return Reference(load_file(path), digest, path)


class Scan:
    """What a bundle carries. `found` = {portal: {signature id: [files]}}; `index_html` the
    entry page's text (None when the bundle has none); `files` how many text files were read."""

    def __init__(self, reference, label):
        self.reference = reference
        self.label = label
        self.found = {}
        self.index_html = None
        self.files = 0

    def add(self, name, text):
        self.files += 1
        if name == INDEX_HTML:
            self.index_html = text
        for pid, entry in self.reference.portals.items():
            for sid, pattern in entry["signatures"]:
                if pattern.search(text):
                    self.found.setdefault(pid, {}).setdefault(sid, []).append(name)

    def portals(self):
        return sorted(self.found)


def _is_text(name):
    return name.lower().endswith(TEXT_EXTENSIONS)


def scan_files(reference, items, label=""):
    """Scan (bundle-relative name, bytes) pairs. Names are forward-slash, relative to the
    bundle root, so `index.html` is the entry page."""
    scan = Scan(reference, label)
    for name, data in sorted(items, key=lambda item: item[0]):
        if _is_text(name):
            scan.add(name, data.decode("utf-8", errors="replace"))
    return scan


def scan_directory(reference, directory, label=None):
    """Scan every text file under `directory` - node_modules too: the package is a zip of the
    whole directory, so whatever it holds ships. A missing directory scans as no files."""
    def items():
        for root, dirnames, filenames in os.walk(directory):
            dirnames[:] = sorted(dirnames)
            for name in sorted(filenames):
                full = os.path.join(root, name)
                if not _is_text(name):
                    continue
                with open(full, "rb") as handle:
                    yield os.path.relpath(full, directory).replace(os.sep, "/"), handle.read()
    return scan_files(reference, list(items()), label or directory)


def scan_zip(reference, path, label=None):
    """Scan a package archive - every text file in it, since every one reaches the portal. A
    single top-level directory holding index.html (a zip of a folder) is treated as the
    bundle root: its files are named relative to it, any file beside it by its own name."""
    with zipfile.ZipFile(path) as archive:
        names = [i.filename for i in archive.infolist() if not i.is_dir()]
        prefix = ""
        if INDEX_HTML not in names:
            tops = {n.split("/", 1)[0] for n in names if "/" in n}
            if len(tops) == 1 and f"{next(iter(tops))}/{INDEX_HTML}" in names:
                prefix = next(iter(tops)) + "/"
        items = [(n[len(prefix):] if prefix and n.startswith(prefix) else n, archive.read(n))
                 for n in names if _is_text(n)]
    return scan_files(reference, items, label or os.path.basename(path))


def foreign(scan, platform_id):
    """{portal: ["signature (file, file)"]} for every portal SDK found other than
    `platform_id`'s own. generic-web has no SDK, so every portal's is foreign to it."""
    out = {}
    for pid, signatures in sorted(scan.found.items()):
        if pid == platform_id:
            continue
        out[pid] = [f"{sid} ({', '.join(files[:3])}{', ...' if len(files) > 3 else ''})"
                    for sid, files in sorted(signatures.items())]
    return out


_SCRIPT = re.compile(r"<script\b[^>]*\bsrc\s*=\s*([\"'])(?P<src>[^\"']+)\1", re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def loader_status(scan, platform_id):
    """(declared, loaded, needs): the script the platform's page must load (None when the
    reference declares none), whether index.html loads it (None without an index.html), and
    what the build must be given for it."""
    loader = scan.reference.loader(platform_id)
    if not loader:
        return None, None, []
    script = str(loader.get("script") or "")
    needs = [str(n) for n in loader.get("needs") or []]
    if scan.index_html is None:
        return script, None, needs
    # A script inside an HTML comment is not loaded.
    sources = [m.group("src") for m in _SCRIPT.finditer(_COMMENT.sub("", scan.index_html))]
    return script, script in sources, needs


def describe(found):
    """One line for foreign(...)'s result."""
    return "; ".join(f"{pid}: {', '.join(items)}" for pid, items in sorted(found.items()))


# -- platform-validate guards ----------------------------------------------------------------
#
# (value, reason, measurements) triples as wgflib.publication's guards: True GREEN, False RED,
# None UNKNOWN. `scan` is the package archive's Scan, or None when the package could not be
# read (no checkout, or its bytes are not the manifest's - package_shaped_to_profile says so).

def isolated_guard(platform_id, scan, verified=None):
    """portal_sdk_isolated: the package carries no other portal's SDK. `verified` is verify's
    platform.foreign-sdk:<id> check for this commit (it may include the template's own audit),
    read when present: a FAIL there is RED here too, a BLOCKED one UNKNOWN (never GREEN)."""
    from . import publication as pub
    if scan is None:
        return pub.unknown(f"{platform_id}: the package was not read, so which portal SDKs it "
                           f"carries is not established")
    if not scan.files:
        return pub.red(f"{platform_id}: the package holds no text file to read "
                       f"({', '.join(TEXT_EXTENSIONS)}), so nothing establishes which portal "
                       f"SDKs it carries - and it has no page to run", foreign=[])
    found = foreign(scan, platform_id)
    if found:
        return pub.red(f"{platform_id}: the package carries other portals' SDKs - "
                       f"{describe(found)} ({scan.reference.label}); a portal refuses a build "
                       f"carrying another portal's SDK. Build it from a template whose build "
                       f"carries only the selected adapter", foreign=sorted(found))
    if verified is not None and verified.get("status") == "FAIL":
        return pub.red(f"{platform_id}: verify's platform.foreign-sdk:{platform_id} failed on "
                       f"this commit: {verified.get('message')}", foreign=["verify"])
    if verified is not None and verified.get("status") == "BLOCKED":
        # Verify could not decide (e.g. the template's own audit, which knows more than this
        # scan, reported nothing): the scan alone is not a clean bill.
        return pub.unknown(f"{platform_id}: verify's platform.foreign-sdk:{platform_id} is "
                           f"BLOCKED on this commit ({verified.get('message')}); the package "
                           f"scan alone found no other portal's SDK, which does not decide it")
    return pub.green(f"{platform_id}: no other portal's SDK in the package "
                     f"({scan.files} text file(s), {scan.reference.label})", foreign=[])


def loaded_guard(platform_id, scan, ids_pending=False):
    """portal_sdk_loaded: the package carries its own portal's SDK - its page loads the script
    the reference declares, else its SDK code is recognised in it. `ids_pending`: the portal
    issues the ids the loader needs only when the game is created, and none is issued yet -
    the submit visit then only creates the game and uploads nothing (docs/publish-module.md,
    create-before-build), so an SDK-less package is GREEN for that visit and RED after it."""
    from . import publication as pub
    if scan is None:
        return pub.unknown(f"{platform_id}: the package was not read, so whether it loads the "
                           f"{platform_id} SDK is not established")
    if platform_id not in scan.reference.portals:
        # Undescribed is not SDK-less: a platform with no SDK declares `signatures: []`.
        return pub.unknown(f"{platform_id}: {scan.reference.label} has no entry for "
                           f"{platform_id}, so what its SDK looks like in a package is not "
                           f"established; add one to core/reference/portal-sdks.yaml")
    script, loaded, needs = loader_status(scan, platform_id)
    if script is not None:
        if loaded:
            return pub.green(f"{platform_id}: index.html loads {script}", loader=script)
        if loaded is None:
            return pub.red(f"{platform_id}: the package has no index.html to load {script}",
                           loader=script)
        if ids_pending and needs:
            return pub.green(f"{platform_id}: index.html does not load {script} - the build "
                             f"was not given {', '.join(needs)}, which the portal issues when "
                             f"the game is created. The submit visit only creates the game and "
                             f"uploads nothing; after it this guard refuses the package until "
                             f"a build given the ids loads the SDK", loader=script, pending=True)
        return pub.red(f"{platform_id}: index.html does not load {script}: the package runs "
                       f"without the {platform_id} SDK and is never uploaded"
                       + (f" (the build must be given {', '.join(needs)}: on the pinned "
                          f"template the ids reach the build through the environment, "
                          f"factory.agents.game_env_passthrough)" if needs else ""),
                       loader=script)
    signatures = (scan.reference.portals.get(platform_id) or {}).get("signatures") or []
    if not signatures:
        return pub.green(f"{platform_id}: {scan.reference.label} recognises no SDK for "
                         f"{platform_id}; nothing to load")
    if platform_id in scan.found:
        return pub.green(f"{platform_id}: the package carries the {platform_id} SDK code "
                         f"({', '.join(sorted(scan.found[platform_id]))})")
    return pub.red(f"{platform_id}: the package carries no {platform_id} SDK code "
                   f"({scan.reference.label}): it would run on {platform_id} without its SDK")
