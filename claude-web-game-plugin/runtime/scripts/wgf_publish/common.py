"""What the two publish steps share: settings, the checkout, the release directory, the
platform profiles, the record they both write."""

import datetime
import json
import os

from wgflib import agentenv, paths, provenance, publication, redact
from wgflib import template_contract as contract
from wgflib.workflow import ArtifactOutput
from wgflib.workspace import WorkspaceError, load_platform_profile
from wgflib.yamllite import YamlError

# The one checkout precedence every step uses (docs/checkouts.md); re-exported for the steps.
from wgf_verification.session import locate_checkout

from .evidence import Evidence, file_sha256

__all__ = ["ARTIFACT", "ROLE", "MODES", "Settings", "utc_now", "profile_for",
           "publication_profile_for", "release_dir", "package_on_disk", "store_metadata",
           "listing_text",
           "assertion_results", "record", "output_name", "read_json", "same_commit",
           "locate_checkout", "evidence_dicts"]

ARTIFACT = "platform-publication"
ROLE = "release"
MODES = ("dry-run", "live")
STORE_METADATA = "store-metadata.json"
# The store listing the release step ships beside its packages (wgf_release LISTING_DIR), and
# each platform's rendition inside it (wgf_listing: platforms/<id>/listing.json).
LISTING_DIR = "listing"


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def same_commit(a, b):
    a, b = str(a or ""), str(b or "")
    return bool(a) and bool(b) and (a == b or a.startswith(b) or b.startswith(a))


class Settings:
    """factory.publish, with the step's `with:` over it. Every key is optional.

        mode              dry-run (default) | live. live also needs WGF_PUBLISH_LIVE=1 in the
                          Factory's environment: production submission is opted into twice.
        env_passthrough   the credential variables the publish step may read (session.py)
        profiles_extra    directories with more publication profiles (tests: the fixture)
        platforms         {platform id: {terms_confirmed, adapter, console_url}}
        timeouts          {action, navigation, upload} ms for the console executor
    """

    def __init__(self, config, params, environ=None):
        section = dict(((config or {}).get("publish") or {}))
        section.update(params or {})
        self.data = section
        self.environ = os.environ if environ is None else environ

    def get(self, key, default=None):
        return self.data.get(key, default)

    @property
    def mode(self):
        mode = self.data.get("mode", "dry-run")
        if mode not in MODES:
            raise ValueError(f"factory.publish.mode must be one of {', '.join(MODES)}, not "
                             f"{mode!r}")
        return mode

    @property
    def live(self):
        """True only when the configuration says live AND the environment confirms it."""
        return self.mode == "live" and str(self.environ.get("WGF_PUBLISH_LIVE", "")) == "1"

    @property
    def profiles_extra(self):
        extra = self.data.get("profiles_extra") or []
        if not isinstance(extra, list) or not all(isinstance(e, str) for e in extra):
            raise ValueError("factory.publish.profiles_extra must be a list of directories")
        return [os.path.join(paths.PROJECT, e) if not os.path.isabs(e) else e for e in extra]

    def platform(self, platform_id):
        platforms = self.data.get("platforms") or {}
        if not isinstance(platforms, dict):
            raise ValueError("factory.publish.platforms must be a mapping of platform ids")
        entry = platforms.get(platform_id) or {}
        if not isinstance(entry, dict):
            raise ValueError(f"factory.publish.platforms.{platform_id} must be a mapping")
        return entry

    @property
    def timeouts(self):
        return dict(self.data.get("timeouts") or {})

    def game_env(self, config):
        """The environment for the browser run: game-code allowlist, never the Factory's."""
        return agentenv.game_code_env(config, self.environ)


def profile_for(platform_id):
    try:
        return load_platform_profile(platform_id)
    except (WorkspaceError, YamlError):
        return None


def publication_profile_for(platform_id, settings):
    try:
        return publication.load_publication_profile(platform_id, settings.profiles_extra)
    except ValueError:
        return None


def release_dir(checkout, release_id):
    return os.path.join(checkout, *contract.release_path(release_id))


def package_on_disk(checkout, release_id, package):
    """(path, True/False/None): the package file and whether its bytes match the manifest's
    checksum; None when there is no checkout to look in."""
    if not checkout or not package:
        return None, None
    path = os.path.join(release_dir(checkout, release_id), str(package.get("filename") or ""))
    if not os.path.isfile(path):
        return path, False
    return path, file_sha256(path) == package.get("checksum")


def store_metadata(checkout, release_id, manifest):
    """{platform id: store metadata}: release/<id>/store-metadata.json in the checkout (what
    a person or the release role prepared), else the manifest's own store_metadata."""
    found = {}
    if checkout:
        data = read_json(os.path.join(release_dir(checkout, release_id), STORE_METADATA))
        if isinstance(data, dict):
            found.update({k: v for k, v in data.items() if isinstance(v, dict)})
    for pid, metadata in ((manifest or {}).get("store_metadata") or {}).items():
        found.setdefault(pid, metadata)
    return found


def listing_text(checkout, release_id, platform_id):
    """{locale: copy}: the texts of the platform's rendition in the store listing the release
    shipped (release/<id>/listing/platforms/<pid>/listing.json, store-listing's `localeCopy`:
    title, short and long description, controls, tags, categories), or {} when the release
    shipped none."""
    if not checkout:
        return {}
    data = read_json(os.path.join(release_dir(checkout, release_id), LISTING_DIR, "platforms",
                                  str(platform_id), "listing.json"))
    text = data.get("text") if isinstance(data, dict) else None
    return {str(k): v for k, v in text.items() if isinstance(v, dict)} if isinstance(text, dict) else {}


def assertion_results(verification, manifest, platform_id):
    """The pinned profile's assertion results verify recorded for this platform and this
    commit (policy.assertions:<pid> evidence data), else None."""
    if not isinstance(verification, dict):
        return None
    commit = (verification.get("commit") or {}).get("sha")
    if not same_commit(commit, (manifest or {}).get("commit_sha")):
        return None
    for check in verification.get("checks") or []:
        if check.get("id") != f"policy.assertions:{platform_id}":
            continue
        for evidence in check.get("evidence") or []:
            results = (evidence.get("data") or {}).get("results")
            if isinstance(results, list):
                return results
        if check.get("status") == "PASS":
            return []  # it passed without recording the list: nothing breached
        return None
    return None


def output_name(platform_id):
    return f"{ARTIFACT}-{platform_id}"


def record(body, *, inputs, context, title_id, sequence):
    """A sealed, scrubbed platform-publication from `body` (everything but provenance)."""
    produced_at = utc_now()
    slug = title_id or context.project_id or "release"
    body = redact.scrub(body)
    artifact = {"provenance": provenance.build(
        ARTIFACT,
        artifact_id=provenance.artifact_id(ARTIFACT, f"{slug}-{body.get('platform_id')}",
                                           produced_at, sequence),
        produced_by=provenance.producer(ROLE),
        produced_at=produced_at,
        inputs=provenance.pin_inputs(inputs),
        title_id=title_id or None,
        status="final")}
    artifact.update(body)
    provenance.seal(artifact)
    return ArtifactOutput(ARTIFACT, artifact, name=output_name(body.get("platform_id")),
                          metadata={"platform_id": body.get("platform_id"),
                                    "state": body.get("state"),
                                    "readiness": body.get("readiness"),
                                    "outcome": body.get("outcome")})


def evidence_dicts(entries):
    return [e.to_dict() if isinstance(e, Evidence) else e for e in entries]
