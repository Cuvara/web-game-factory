"""The portal registry: every portal game the Factory knows for one title.

One file per title, `workspace/titles/<title-id>/portals.json` under the project
(core/artifacts/portal-registry.schema.json), one entry per platform. It is what keeps a
publish visit from creating a second game for a title on a portal: the find-game phase tries
the recorded id first (`lookup_candidates`), a game created by the Factory has its id read
back and recorded, and a game a person created by hand is linked with `associate`.

    reg = registry.load("my-title")
    reg.lookup_candidates("y8", config_game_id=..., config_app_id=...)
    reg.record("y8", status="DRAFT_CREATED", external_game_id="123",
               association="created-by-factory", by="automation", run_id=run_id)
    reg.record("y8", status="PENDING_REVIEW", by="automation", run_id=run_id,
               evidence=[evidence_item("portal-status", ref, status_text)])

Rules, enforced on every write:

  * a status change follows TRANSITIONS (data, below); anything else raises RegistryError;
  * a status in EVIDENCE_REQUIRED is entered only with evidence of the portal's own status
    text (EVIDENCE_KINDS) given in the same call - never inferred from a click that returned;
  * the `external_game_id` or `app_id` of an existing entry is changed only by a person;
  * every write appends a history item, validates the whole file against the schema, and
    replaces the file atomically with LF line endings.

Entries are independent: recording one platform never touches another. Standard library only.
"""

import copy
import hashlib
import json
import os
import re
from datetime import datetime, timezone

from wgflib import paths
from wgflib.jsonschema_lite import Validator
from wgflib.workflow.contracts import load_registry

__all__ = ["RegistryError", "PortalRegistry", "load", "registry_path", "evidence_item",
           "STATUSES", "TRANSITIONS", "EVIDENCE_REQUIRED", "EVIDENCE_KINDS"]

FILENAME = "portals.json"
SCHEMA = "portal-registry"

STATUSES = ("NOT_CREATED", "DRAFT", "DRAFT_CREATED", "PENDING_REVIEW", "VERIFIED", "REJECTED",
            "PUBLISHED", "BLOCKED", "UNKNOWN")

# Status -> the statuses it may move to. Recording the same status again is not a transition.
# BLOCKED and UNKNOWN may be entered from anywhere and left for any observed status: they say
# what the Factory could not establish, not where the game is.
_OBSERVED = {"DRAFT", "DRAFT_CREATED", "PENDING_REVIEW", "VERIFIED", "REJECTED", "PUBLISHED"}
TRANSITIONS = {
    "NOT_CREATED": {"DRAFT_CREATED", "DRAFT"},
    "DRAFT_CREATED": {"DRAFT", "PENDING_REVIEW"},
    "DRAFT": {"PENDING_REVIEW"},
    "PENDING_REVIEW": {"VERIFIED", "REJECTED", "PUBLISHED"},
    "VERIFIED": {"PUBLISHED"},
    "REJECTED": {"DRAFT"},
    # A later release is a new version of the same game, never a new game.
    "PUBLISHED": {"DRAFT"},
    "BLOCKED": set(_OBSERVED),
    "UNKNOWN": set(_OBSERVED),
}
ANYWHERE = {"UNKNOWN", "BLOCKED"}

# Statuses only the portal can establish.
EVIDENCE_REQUIRED = {"PENDING_REVIEW", "VERIFIED", "PUBLISHED", "REJECTED"}
# Evidence that carries the portal's own status text.
EVIDENCE_KINDS = {"portal-status", "console-text", "api-response"}

# Fields `record` may set. `status`, `evidence` and `history` have their own handling.
FIELDS = ("portal", "game_title", "external_game_id", "app_id", "other_ids", "slug", "url",
          "submission_status", "publication_status", "build_hash", "campaign_hash",
          "release_id", "association", "last_checked_at")
# Identity: changed on an existing entry only by a person.
IDENTITY = ("external_game_id", "app_id")
BY = ("automation", "human")
_ID = re.compile(r"^[a-z][a-z0-9-]*$")


class RegistryError(ValueError):
    """A write the registry refuses. Nothing was written."""


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def registry_path(title_id, titles_dir=None):
    return os.path.join(titles_dir or paths.TITLES, title_id, FILENAME)


def evidence_item(kind, ref, content):
    """An evidence entry for `content` (the status text, or bytes) kept at `ref`."""
    data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    return {"kind": kind, "ref": ref, "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}


_VALIDATOR = None


def _validator():
    global _VALIDATOR
    if _VALIDATOR is None:
        with open(os.path.join(paths.ARTIFACTS, f"{SCHEMA}.schema.json"), encoding="utf-8") as fh:
            _VALIDATOR = Validator(json.load(fh), load_registry())
    return _VALIDATOR


def validate(document):
    """Schema problems of a registry document, as strings; [] when valid."""
    return [str(error) for error in _validator().iter_errors(document)]


def load(title_id, titles_dir=None):
    """The title's registry; empty (nothing written) when the title has none yet."""
    if not isinstance(title_id, str) or not _ID.match(title_id):
        raise RegistryError(f"{title_id!r} is not a title id")
    return PortalRegistry(title_id, registry_path(title_id, titles_dir))


class PortalRegistry:
    def __init__(self, title_id, path):
        self.title_id = title_id
        self.path = path
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                document = json.load(handle)
            problems = validate(document)
            if problems:
                raise RegistryError(f"{path}: not a valid portal registry: {problems[0]}")
            if document["title_id"] != title_id:
                raise RegistryError(f"{path}: holds title {document['title_id']!r}, "
                                    f"not {title_id!r}")
        else:
            document = {"title_id": title_id, "updated_at": _now(), "portals": {}}
        self.document = document

    # -- reading -----------------------------------------------------------------------

    def platforms(self):
        return sorted(self.document["portals"])

    def get(self, platform):
        """A copy of the platform's entry, or None: no game is known there (NOT_CREATED)."""
        entry = self.document["portals"].get(platform)
        return copy.deepcopy(entry) if entry is not None else None

    def status(self, platform):
        entry = self.document["portals"].get(platform)
        return entry["status"] if entry else "NOT_CREATED"

    def lookup_candidates(self, platform, config_game_id=None, config_app_id=None):
        """The ids the find-game phase must try, in order: the registry's game id and app
        id, then game.config.yaml's `game_id` and `app_id` as the caller passes them.
        [{"source": "registry"|"game-config", "field": ..., "id": ...}], without repeats."""
        entry = self.document["portals"].get(platform) or {}
        ordered = [("registry", "external_game_id", entry.get("external_game_id")),
                   ("registry", "app_id", entry.get("app_id")),
                   ("game-config", "game_id", config_game_id),
                   ("game-config", "app_id", config_app_id)]
        seen, found = set(), []
        for source, field, value in ordered:
            if value in (None, "") or str(value) in seen:
                continue
            seen.add(str(value))
            found.append({"source": source, "field": field, "id": str(value)})
        return found

    # -- writing -----------------------------------------------------------------------

    def record(self, platform, *, by, run_id=None, note=None, evidence=(), status=None,
               now=None, **fields):
        """Record what is known of the platform's game, and append one history item.

        `status` None keeps the current one. Raises RegistryError, writing nothing, on an
        unknown field, a transition TRANSITIONS does not allow, a portal-established status
        without status-text evidence in this call, or an automated identity change."""
        if not isinstance(platform, str) or not _ID.match(platform):
            raise RegistryError(f"{platform!r} is not a platform id")
        if by not in BY:
            raise RegistryError(f"by must be one of {BY}, not {by!r}")
        unknown = sorted(set(fields) - set(FIELDS))
        if unknown:
            raise RegistryError(f"unknown field(s) {unknown}")
        if status is not None and status not in STATUSES:
            raise RegistryError(f"unknown status {status!r}")
        if status == "NOT_CREATED":
            raise RegistryError("NOT_CREATED is the absence of an entry; it is never recorded")
        evidence = [dict(item) for item in evidence or ()]
        now = now or _now()

        existing = self.document["portals"].get(platform)
        entry = copy.deepcopy(existing) if existing else {"status": "NOT_CREATED",
                                                          "history": []}
        current = entry["status"]
        target = current if status is None else status

        if target != current and target not in ANYWHERE \
                and target not in TRANSITIONS.get(current, ()):
            raise RegistryError(f"{platform}: {current} -> {target} is not an allowed "
                                f"transition (allowed: "
                                f"{', '.join(sorted(TRANSITIONS.get(current, set()) | ANYWHERE))})")
        if target == "NOT_CREATED":
            raise RegistryError(f"{platform}: a new entry needs a status")
        if target != current and target in EVIDENCE_REQUIRED \
                and not any(item.get("kind") in EVIDENCE_KINDS for item in evidence):
            raise RegistryError(f"{platform}: {target} is established by the portal; record it "
                                f"with the portal's status text as evidence (kind one of "
                                f"{sorted(EVIDENCE_KINDS)}), never inferred")
        if existing and by != "human":
            for field in IDENTITY:
                if field in fields and existing.get(field) not in (None, "") \
                        and fields[field] != existing.get(field):
                    raise RegistryError(f"{platform}: {field} is {existing.get(field)!r}; "
                                        f"only a person changes a recorded portal id "
                                        f"(registry associate)")
        if not existing and fields.get("external_game_id") and "association" not in fields:
            raise RegistryError(f"{platform}: say how the game is known (association)")

        entry.update(fields)
        entry["status"] = target
        if evidence:
            entry["evidence"] = entry.get("evidence", []) + evidence
        entry["history"].append({"at": now, "from": current, "to": target, "by": by,
                                 "run_id": run_id, "note": note})
        self._write(platform, entry, now)
        return copy.deepcopy(entry)

    def associate(self, platform, external_game_id, *, by="human", note, run_id=None,
                  now=None):
        """A person links a portal game - typically one they created by hand - to this title.
        The status becomes UNKNOWN until the portal is read; a changed id also drops the
        submission facts recorded for the old game."""
        if by != "human":
            raise RegistryError("associating a portal game is a person's act (by='human')")
        if not external_game_id or not str(external_game_id).strip():
            raise RegistryError("an external game id is required")
        if not note or not str(note).strip():
            raise RegistryError("say why (note): where the game came from")
        external_game_id = str(external_game_id).strip()
        existing = self.document["portals"].get(platform)
        fields = {"external_game_id": external_game_id, "association": "associated-by-person"}
        status = None
        if not existing or existing.get("external_game_id") != external_game_id:
            status = "UNKNOWN"
            if existing:
                fields.update(submission_status=None, publication_status=None,
                              build_hash=None, campaign_hash=None)
        return self.record(platform, by="human", run_id=run_id, note=note, status=status,
                           now=now, **fields)

    def invalidate_if_changed(self, platform, build_hash=None, campaign_hash=None, *,
                              by="automation", run_id=None, now=None):
        """{field: {"from", "to"}} for each of build_hash / campaign_hash given that differs
        from the entry's. When anything differs the new hashes are recorded and the
        submission status - which described the old build or listing - is cleared; the
        game's status stays as last observed. {} when nothing changed or no game is known."""
        entry = self.document["portals"].get(platform)
        if entry is None:
            return {}
        changed = {}
        for field, value in (("build_hash", build_hash), ("campaign_hash", campaign_hash)):
            if value is not None and entry.get(field) != value:
                changed[field] = {"from": entry.get(field), "to": value}
        if changed:
            self.record(platform, by=by, run_id=run_id, now=now, submission_status=None,
                        note="changed: " + ", ".join(sorted(changed)),
                        **{field: change["to"] for field, change in changed.items()})
        return changed

    def _write(self, platform, entry, now):
        document = copy.deepcopy(self.document)
        document["portals"][platform] = entry
        document["updated_at"] = now
        problems = validate(document)
        if problems:
            raise RegistryError(f"{platform}: the registry would not be valid: "
                                + "; ".join(problems[:3]))
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temporary = f"{self.path}.{os.getpid()}.tmp"
        try:
            with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
        self.document = document
