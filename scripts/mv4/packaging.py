"""MV-4 criterion G: what the release actually packages, and what is inside each package.

    python scripts/mv4/packaging.py --checkout DIR --release mv4-r1 --out DIR

Runs the game repository's own packaging and manifest scripts, then audits the result against
what the Factory says should ship:

* the build target - the one platform this contract's single bundle boots
  (`wgflib.template_contract.build_target`, the pinned template's own rule);
* every package the repository produced, its recorded checksum against the bytes on disk, and
  its entry in checksums.txt;
* whether two packages are the same bytes, which is the question behind platform exclusivity:
  one bundle packaged under three names is one artifact, not three;
* which portal SDK each package's bundle actually references, read out of the archive with the
  template's own signature list. A package named for one portal whose bundle references
  another portal's SDK would boot the wrong SDK there.

It states no legal conclusion. Portal terms are recorded separately, as quotations with their
source; this file is only what the bytes are.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from wgflib import procs, template_contract as contract, yamllite  # noqa: E402

SIGNATURES = "packages/platform-sdk/sdk-signatures.json"
TEXT = re.compile(rb"[\x20-\x7e]{4,}")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def payload_digest(zip_path):
    """A hash of what the archive contains, independent of archive metadata: every entry's
    name and bytes, in name order. Two archives with the same payload digest ship the same
    game, whatever their filenames or timestamps say."""
    digest = hashlib.sha256()
    with zipfile.ZipFile(zip_path) as archive:
        for name in sorted(archive.namelist()):
            digest.update(name.encode("utf-8"))
            digest.update(archive.read(name))
    return "sha256:" + digest.hexdigest()


def sdk_references(zip_path, signatures):
    """Which portals' SDK signatures appear in the archive's own bytes, or None when the
    repository ships no signature list to scan against - which is not the same as none."""
    if not signatures:
        return None
    found = {}
    with zipfile.ZipFile(zip_path) as archive:
        blob = b"".join(archive.read(name) for name in sorted(archive.namelist())
                        if name.endswith((".js", ".mjs", ".html")))
    strings = b"\n".join(TEXT.findall(blob)).decode("ascii", "replace")
    for platform_id, needles in signatures.items():
        hits = [needle for needle in needles if isinstance(needle, str) and needle in strings]
        if hits:
            found[platform_id] = hits
    return found


def audit(checkout, release_id, package_result, manifest_result):
    config = yamllite.load_file(os.path.join(checkout, contract.GAME_CONFIG))
    platforms = config.get("platforms") or []
    target = contract.build_target(platforms)
    root = os.path.join(checkout, contract.RELEASE_ROOT, release_id)

    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "release": release_id,
        "declared_platforms": [{"id": p.get("id"), "role": p.get("role")} for p in platforms],
        "build_target": target,
        "build_target_rule": "template contract 1.0.0: one bundle, booting the first platform "
                             "whose role is exactly `required`, else the first",
        "commands": {"release:package": package_result, "release:manifest": manifest_result},
        "packages": [],
        "findings": [],
    }
    if not os.path.isdir(root):
        report["findings"].append(f"no release directory at {contract.RELEASE_ROOT}/{release_id}")
        return report

    listed_path = os.path.join(root, contract.RELEASE_PACKAGES)
    listed = []
    if os.path.isfile(listed_path):
        with open(listed_path, encoding="utf-8") as handle:
            listed = json.load(handle)
    else:
        report["findings"].append(f"{contract.RELEASE_PACKAGES} was not written")

    checksums = {}
    checksums_path = os.path.join(root, contract.RELEASE_CHECKSUMS)
    if os.path.isfile(checksums_path):
        with open(checksums_path, encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) == 2:
                    checksums[parts[1].lstrip("*")] = parts[0]

    signatures = {}
    signature_path = os.path.join(checkout, SIGNATURES)
    if os.path.isfile(signature_path):
        with open(signature_path, encoding="utf-8") as handle:
            signatures = json.load(handle)

    for entry in listed:
        path = os.path.join(root, entry.get("filename") or "")
        record = {"platform_id": entry.get("platform_id"), "filename": entry.get("filename"),
                  "recorded_checksum": entry.get("checksum"), "exists": os.path.isfile(path)}
        if not record["exists"]:
            report["findings"].append(f"{entry.get('filename')} is listed but not on disk")
            report["packages"].append(record)
            continue
        record["actual_checksum"] = sha256_file(path)
        record["checksum_matches"] = record["actual_checksum"] == entry.get("checksum")
        record["checksums_txt"] = checksums.get(entry.get("filename"))
        record["checksums_txt_matches"] = (
            record["checksums_txt"] is not None
            and record["actual_checksum"].split(":", 1)[1] == record["checksums_txt"])
        record["payload_digest"] = payload_digest(path)
        record["size_bytes"] = os.path.getsize(path)
        record["sdk_signatures_in_bundle"] = sdk_references(path, signatures)
        if record["sdk_signatures_in_bundle"] is None:
            record["sdk_signatures_note"] = (
                f"{SIGNATURES} is not in this repository, so which portal SDK the bundle "
                "references was not scanned")
        record["is_build_target"] = entry.get("platform_id") == target
        if not record["checksum_matches"]:
            report["findings"].append(f"{entry.get('filename')}: recorded checksum does not "
                                      "match the bytes on disk")
        if not record["checksums_txt_matches"]:
            report["findings"].append(f"{entry.get('filename')}: checksums.txt does not match "
                                      "the bytes on disk")
        report["packages"].append(record)

    by_payload = {}
    for record in report["packages"]:
        by_payload.setdefault(record.get("payload_digest"), []).append(record["platform_id"])
    report["identical_payloads"] = {digest: ids for digest, ids in by_payload.items()
                                    if digest and len(ids) > 1}
    report["target_packaged"] = any(r.get("is_build_target") for r in report["packages"])
    report["non_target_packaged"] = [r["platform_id"] for r in report["packages"]
                                     if not r.get("is_build_target")]
    if report["non_target_packaged"]:
        report["findings"].append(
            "the repository's own packaging produced a package for "
            f"{report['non_target_packaged']}, which this build does not target. The Factory's "
            "release step prunes exactly these (2.2.0, MV-3); what the repository's script does "
            "on its own is recorded here because a game repository can be released from its own "
            "workflow.")

    manifest_path = os.path.join(root, contract.RELEASE_MANIFEST)
    if os.path.isfile(manifest_path):
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        named = sorted(p.get("platform_id") for p in (manifest.get("packages") or []))
        report["manifest"] = {
            "version": manifest.get("version"),
            "platforms_named": named,
            "matches_packages": named == sorted(r["platform_id"] for r in report["packages"]),
        }
        if not report["manifest"]["matches_packages"]:
            report["findings"].append("the manifest names packages the release directory "
                                      "does not contain, or the other way round")
    else:
        report["manifest"] = None
        report["findings"].append("no manifest was written")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--checkout", required=True)
    parser.add_argument("--release", default="mv4-r1")
    parser.add_argument("--out", required=True)
    parser.add_argument("--skip-run", action="store_true",
                        help="audit a release directory that already exists")
    args = parser.parse_args(argv)

    version = (yamllite.load_file(os.path.join(args.checkout, contract.GAME_CONFIG))
               .get("game") or {}).get("version") or "0.1.0"

    def run(script, extra=()):
        result = procs.run(["pnpm", "run", script, "--release", args.release, *extra],
                           cwd=args.checkout, timeout=1800, stderr_to_stdout=True)
        return {"script": script, "status": result.status, "returncode": result.returncode,
                "ok": result.ok, "tail": result.tail(20)}

    package_result = manifest_result = {"skipped": True}
    if not args.skip_run:
        package_result = run(contract.SCRIPT_RELEASE_PACKAGE)
        manifest_result = run(contract.SCRIPT_RELEASE_MANIFEST, ("--version", version))

    report = audit(args.checkout, args.release, package_result, manifest_result)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "packaging.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(json.dumps({k: v for k, v in report.items() if k != "packages"}, indent=2))
    for record in report["packages"]:
        print(f"  {record['platform_id']:14} target={record.get('is_build_target')} "
              f"checksum_ok={record.get('checksum_matches')} "
              f"sdk={sorted(record.get('sdk_signatures_in_bundle') or {})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
