"""core/reference/asset-policy.yaml, as an object: asset kinds, and licence classification.

The policy is methodology, so it lives in core/ and this module only reads it. The manifest
pins it by id, version and content hash, the same way an evaluation pins its scoring model:
a licence moved from permitted to restricted changes which manifests are shippable, and that
change has to be visible on every manifest classified under the old policy.
"""

import hashlib
import os
from collections import namedtuple

from wgflib import paths
from wgflib.yamllite import load_file

__all__ = ["AssetPolicy", "KindPolicy", "LicenseVerdict", "load_policy", "PolicyError",
           "POLICY_PATH", "GENERATED_LICENSE"]

POLICY_PATH = os.path.join(paths.REFERENCE, "asset-policy.yaml")

# The licence the procedural backend records on what it makes. It is in the policy's
# permitted list; this constant only names it.
GENERATED_LICENSE = "LicenseRef-factory-generated"

LicenseVerdict = namedtuple("LicenseVerdict", "status constraints reason")


class PolicyError(ValueError):
    """The policy file is missing, malformed, or names a kind inconsistently."""


class KindPolicy:
    def __init__(self, kind, data):
        self.kind = kind
        self.manifest_type = data.get("manifest_type") or kind
        self.dimension = data.get("dimension") or "any"
        self.directory = data.get("directory") or kind
        self.formats = list(data.get("formats") or [])
        self.companion = data.get("companion")
        self.placeholder = data.get("placeholder")
        self.max_bytes = data.get("max_bytes")
        self.power_of_two = bool(data.get("power_of_two"))
        self.est_hours = float(data.get("est_hours") or 0)
        self.est_cost = dict(data.get("est_cost") or {})
        self.optimize = list(data.get("optimize") or [])
        if not self.formats:
            raise PolicyError(f"asset kind {kind!r} lists no formats")

    def cost_for(self, source):
        return self.est_cost.get(source, 0)


class AssetPolicy:
    def __init__(self, data, digest=None):
        meta = data.get("policy") or {}
        self.id = meta.get("id") or "asset-policy"
        self.version = str(meta.get("version") or "0.0.0")
        self.content_hash = digest
        self.kinds = {kind: KindPolicy(kind, spec)
                      for kind, spec in (data.get("kinds") or {}).items()}
        self.optimizations = dict(data.get("optimizations") or {})
        self.pipeline = dict(data.get("pipeline") or {})
        licenses = data.get("licenses") or {}
        self.permitted = {entry["id"]: list(entry.get("constraints") or [])
                          for entry in licenses.get("permitted") or []}
        self.restricted = {entry["id"]: entry.get("reason") or "restricted"
                           for entry in licenses.get("restricted") or []}
        if not self.kinds:
            raise PolicyError("asset policy defines no kinds")

    def kind(self, kind):
        try:
            return self.kinds[kind]
        except KeyError:
            raise PolicyError(
                f"unknown asset kind {kind!r}; known: {', '.join(sorted(self.kinds))}")

    def classify_license(self, license_id):
        """`generated`, `verified`, `restricted` or `unknown`, with the constraints it
        imposes. Matching is exact after trimming: `cc-by-4.0` is not `CC-BY-4.0`, because
        an identifier someone typed loosely is an identifier nobody checked."""
        license_id = (license_id or "").strip()
        if not license_id:
            return LicenseVerdict("unknown", [], "no license recorded")
        if license_id == GENERATED_LICENSE:
            return LicenseVerdict("generated", [], None)
        if license_id in self.restricted:
            return LicenseVerdict("restricted", [], self.restricted[license_id])
        if license_id in self.permitted:
            return LicenseVerdict("verified", list(self.permitted[license_id]), None)
        return LicenseVerdict("unknown", [], f"license {license_id!r} is not in the policy")

    def pin(self):
        pin = {"id": self.id, "version": self.version}
        if self.content_hash:
            pin["content_hash"] = self.content_hash
        return pin


def load_policy(path=None):
    path = path or POLICY_PATH
    if not os.path.exists(path):
        raise PolicyError(f"asset policy not found: {path}")
    with open(path, "rb") as handle:
        raw = handle.read()
    data = load_file(path) or {}
    return AssetPolicy(data, digest="sha256:" + hashlib.sha256(raw).hexdigest())
