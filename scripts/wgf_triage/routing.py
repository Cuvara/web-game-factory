"""The routing data: who owns a dimension, in which order specialists visit, where they work.

Reads core/reference/specialist-routing.yaml (owners, visit order, producer tables) and
core/roles/roles.yaml (each specialist's focus, craft playbooks and writable scope). Both
are data: a new owner or playbook is an edit there, never here.

    routing = Routing.load()
    routing.owner("environment-3d")       -> "environment-artist"
    routing.groups(findings)              -> [{owner, route, label, findings, ...}] in order
    routing.specialist("level-designer")  -> {"role", "label", "focus", "reads", "writes"}

A group's `label` is what the triage step returns as its route: the route itself for
`design`, `assets` and `listing`, and the owner's role id for `develop` - the workflow maps
each specialist's label to develop (core/workflows/new-game.workflow.yaml).
"""

import hashlib
import os

from wgflib import paths
from wgflib.yamllite import load_file

__all__ = ["Routing", "RoutingError", "ROUTING_PATH", "ROLES_PATH", "DEVELOP"]

ROUTING_PATH = os.path.join(paths.REFERENCE, "specialist-routing.yaml")
ROLES_PATH = os.path.join(paths.CORE, "roles", "roles.yaml")
DEVELOP = "develop"
# Routes whose step does one pass over every finding routed to it, whoever owns each.
WHOLE_PASS = ("design", "assets", "listing")
_SEVERITY_ORDER = {"blocker": 0, "major": 1, "minor": 2}


class RoutingError(ValueError):
    """The routing data is inconsistent: a dimension with no owner or two, an unknown role."""


def _sha256(path):
    with open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


class Routing:
    def __init__(self, data, roles, *, path=None, content_hash=None):
        self.data = data or {}
        self.roles = (roles or {}).get("roles") or {}
        self.path = path
        self.content_hash = content_hash
        self.version = str(self.data.get("version") or "")
        self.dimensions = tuple(self.data.get("dimensions") or ())
        self.default_dimension = self.data.get("default_dimension") or "gameplay"
        self.route_order = tuple(self.data.get("route_order") or ("design", "assets", DEVELOP))
        self.specialists = [s for s in self.data.get("specialists") or [] if isinstance(s, dict)]
        self.order = [s.get("role") for s in self.specialists]
        self._owner = {}
        for spec in self.specialists:
            for dimension in spec.get("dimensions") or ():
                self._owner.setdefault(dimension, []).append(spec.get("role"))

    @classmethod
    def load(cls, path=None, roles_path=None):
        path = path or ROUTING_PATH
        roles_path = roles_path or ROLES_PATH
        routing = cls(load_file(path), load_file(roles_path), path=path,
                      content_hash=_sha256(path))
        problems = routing.problems()
        if problems:
            raise RoutingError("; ".join(problems))
        return routing

    def problems(self):
        """[] when every dimension has exactly one owner, every owner is a role with a
        charter, and every playbook a specialist reads exists."""
        out = []
        for dimension in self.dimensions:
            owners = self._owner.get(dimension) or []
            if len(owners) != 1:
                out.append(f"dimension {dimension!r} has {len(owners)} owners ({owners})")
        for dimension in self._owner:
            if dimension not in self.dimensions:
                out.append(f"specialists name dimension {dimension!r}, which is not listed")
        if self.default_dimension not in self.dimensions:
            out.append(f"default_dimension {self.default_dimension!r} is not a dimension")
        for role in self.order:
            spec = self.roles.get(role)
            if not isinstance(spec, dict):
                out.append(f"specialist {role!r} is not a role in core/roles/roles.yaml")
                continue
            for playbook in spec.get("reads") or ():
                if not os.path.isfile(os.path.join(paths.ROOT, *playbook.split("/"))):
                    out.append(f"role {role!r} reads {playbook!r}, which does not exist")
        for word, table in (self.data.get("by_engine_dimension") or {}).items():
            for value in (table or {}).values():
                if value not in self.dimensions:
                    out.append(f"by_engine_dimension.{word} names {value!r}, not a dimension")
        return out

    # -- lookups ---------------------------------------------------------------------

    def producer(self, kind):
        return (self.data.get("producers") or {}).get(kind) or {}

    def resolve_word(self, word, engine_dimension="2d"):
        """A dimension for a producer table's value: itself when it is one, else its
        `by_engine_dimension` entry for the design's dimension; None otherwise."""
        if word in self.dimensions:
            return word
        table = (self.data.get("by_engine_dimension") or {}).get(word)
        if isinstance(table, dict):
            return table.get(engine_dimension) or table.get("2d")
        return None

    def owner(self, dimension):
        owners = self._owner.get(dimension) or self._owner.get(self.default_dimension) or []
        return owners[0] if owners else "gameplay"

    def route_of(self, owner):
        for spec in self.specialists:
            if spec.get("role") == owner:
                return spec.get("route") or DEVELOP
        return DEVELOP

    def specialist(self, owner):
        """The specialist's brief data from roles.yaml: label, focus, reads, writes."""
        spec = self.roles.get(owner) or {}
        return {"role": owner, "label": spec.get("label") or owner,
                "focus": " ".join(str(spec.get("focus") or spec.get("responsibility")
                                      or "").split()),
                "reads": list(spec.get("reads") or ()),
                "writes": list(spec.get("writes") or ())}

    @staticmethod
    def label(owner, route):
        return owner if route == DEVELOP else route

    # -- grouping --------------------------------------------------------------------

    def groups(self, findings):
        """The findings grouped by (route, owner), in visit order: by route_order, then by
        the specialists' order. Within a group, most severe first. A design, assets or
        listing group is one group whatever its owners: one design revision, one assets
        pass, one store-listing pass (which captures, renders and rewrites what its findings
        name, and briefs its copywriter with the store-copy ones)."""
        buckets = {}
        for finding in findings:
            route = finding.get("route") or DEVELOP
            owner = finding.get("owner") or self.owner(finding.get("dimension"))
            key = (route, None if route in WHOLE_PASS else owner)
            buckets.setdefault(key, []).append(finding)

        def rank(key):
            route, owner = key
            r = self.route_order.index(route) if route in self.route_order else len(
                self.route_order)
            o = self.order.index(owner) if owner in self.order else len(self.order)
            return (r, o, owner or "")

        out = []
        for key in sorted(buckets, key=rank):
            route, owner = key
            members = sorted(buckets[key], key=lambda f: (
                _SEVERITY_ORDER.get(f.get("severity"), 3), f.get("id")))
            if owner is None:
                # design / assets / listing: named for the owner of its most severe finding.
                owner = members[0].get("owner") or self.owner(members[0].get("dimension"))
            spec = self.specialist(owner)
            group = {"owner": owner, "route": route, "label": self.label(owner, route),
                     "findings": [f["id"] for f in members]}
            if route == DEVELOP:
                group["playbooks"] = spec["reads"]
                group["writable_paths"] = spec["writes"]
            out.append(group)
        return out
