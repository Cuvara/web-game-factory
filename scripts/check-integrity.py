#!/usr/bin/env python3
"""Referential integrity check for core/.

The Factory deliberately ships no validation toolchain — core must stay consumable by a
provider that cannot execute anything, and a Node lockfile in a markdown-and-JSON repository
is permanent maintenance surface. See core/README.md for the conditions under which to
revisit that.

The cost of that decision is that cross-references between the machines, the schemas, the
roles and the binding manifest are unchecked. This script is the cheap substitute: no
dependencies beyond the standard library, and it catches the dangling-reference class that
would otherwise only surface when an agent followed a path that does not exist.

It does NOT validate instances against schemas — use ajv for that:

    npx --yes -p ajv-cli@5 -p ajv-formats@2 ajv validate \\
      -s core/artifacts/<id>.schema.json -r "core/artifacts/shared/*.schema.json" \\
      -c ajv-formats --spec=draft2020 --strict=false -d <instance>.json

Run from the web-game-factory repository root:

    python scripts/check-integrity.py
"""
import glob
import hashlib
import json
import os
import re
import sys

ERRORS = []
WARNINGS = []
NOTES = []


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def load_artifacts():
    """Artifact ids, taken from each schema's x-wgf block. The id must equal the filename
    stem — that invariant is what makes every other reference checkable by grep."""
    ids = set()
    for path in sorted(glob.glob("core/artifacts/*.schema.json")
                       + glob.glob("core/artifacts/shared/*.schema.json")):
        schema = json.loads(read(path))
        meta = schema.get("x-wgf")
        if not meta:
            NOTES.append(f"{path}: no x-wgf block (shared primitive, not an artifact)")
            continue
        ids.add(meta["id"])
        stem = os.path.basename(path).replace(".schema.json", "")
        if meta["id"] != stem:
            ERRORS.append(f"{path}: x-wgf.id '{meta['id']}' != filename stem '{stem}'")
        # The contract version producers write into provenance.schema_version, and the one
        # the engine checks a written artifact's major against (wgflib/provenance.py). Shared
        # schemas with an x-wgf block (claim, reference types) are not produced as workflow
        # artifacts and carry no version.
        if os.path.dirname(path) == "core/artifacts" and not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(meta.get("version") or "")):
            ERRORS.append(f"{path}: x-wgf.version {meta.get('version')!r} is not a semver "
                          "MAJOR.MINOR.PATCH")
    return ids


def check_required_for_gates():
    """x-wgf.required_for_gates is a copy of gates.yaml's required_artifacts, kept on each
    schema so a reader of one contract sees which gates it serves. gates.yaml is the
    authority - it is what a checkpoint checks - so the copy must agree with it exactly."""
    sys.path.insert(0, "scripts")
    from wgflib.yamllite import load_file

    gates = (load_file("core/lifecycle/gates.yaml") or {}).get("gates") or {}
    required = {gate: set(spec.get("required_artifacts") or []) for gate, spec in gates.items()}
    for path in sorted(glob.glob("core/artifacts/*.schema.json")):
        meta = json.loads(read(path)).get("x-wgf") or {}
        declared = set(meta.get("required_for_gates") or [])
        actual = {gate for gate, ids in required.items() if meta.get("id") in ids}
        if declared != actual:
            ERRORS.append(f"{path}: x-wgf.required_for_gates {sorted(declared)} but "
                          f"gates.yaml requires it for {sorted(actual)}")


def load_roles():
    return set(re.findall(r"^  ([a-z][a-z0-9-]*):$", read("core/roles/roles.yaml"), re.M))


def check_machines(artifacts, roles, gates):
    for machine in sorted(glob.glob("core/lifecycle/*.machine.yaml")):
        text = read(machine)
        for group in re.findall(
            r"^\s*(?:inputs|outputs|produces|emits|consumes):\s*\[([^\]]*)\]", text, re.M
        ):
            for aid in (a.strip() for a in group.split(",") if a.strip()):
                if aid not in artifacts:
                    ERRORS.append(f"{machine}: unknown artifact '{aid}'")
        for role in re.findall(r"^\s*role:\s*([a-z][a-z0-9-]*)\s*$", text, re.M):
            if role not in roles:
                ERRORS.append(f"{machine}: unknown role '{role}'")
        for proc in re.findall(r"^\s*procedure:\s*(\S+)", text, re.M):
            if not os.path.exists(os.path.join("core/lifecycle", proc)):
                ERRORS.append(f"{machine}: missing procedure '{proc}'")
        for gate in re.findall(r"gate:\s*(G\d+)", text):
            if gate not in gates:
                ERRORS.append(f"{machine}: unknown gate '{gate}'")


def check_workflows(artifacts):
    """core/workflows/*.workflow.yaml parse as runnable definitions, every step's `stage`
    names a real lifecycle state or stage procedure, and every artifact a step consumes or
    produces has a schema - or is listed in the workflow's `untyped_artifacts`, which is the
    visible list of contracts core does not have yet."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from wgflib.machine import MACHINES, load_machine
    from wgflib.workflow.definition import DefinitionError, load_definition
    from wgflib.yamllite import YamlError

    stages = {os.path.basename(p)[:-3] for p in glob.glob("core/lifecycle/stages/*.md")}
    states = {name: set(load_machine(name).states) for name in MACHINES}

    found = sorted(glob.glob("core/workflows/*.workflow.yaml"))
    for path in found:
        try:
            definition = load_definition(path)
        except (DefinitionError, YamlError) as exc:
            ERRORS.append(f"{path}: {exc}")
            continue
        untyped = set(definition.untyped_artifacts)
        for aid in sorted(untyped - artifacts):
            NOTES.append(f"{path}: '{aid}' is untyped - no schema yet, only structure checked")
        for aid in sorted(untyped & artifacts):
            ERRORS.append(f"{path}: '{aid}' is listed as untyped but has a schema")
        for step in definition.steps:
            for aid in step.inputs + step.outputs:
                if aid not in artifacts and aid not in untyped:
                    ERRORS.append(f"{path}: step '{step.id}' names unknown artifact '{aid}'")
            if step.stage:
                machine, stage = step.stage.split(":", 1)
                if machine not in states:
                    ERRORS.append(f"{path}: step '{step.id}' stage names unknown machine "
                                  f"'{machine}'")
                elif stage not in states[machine] and stage not in stages:
                    ERRORS.append(f"{path}: step '{step.id}' stage '{step.stage}' is neither "
                                  f"a state nor a stage procedure")
            gate = step.params.get("gate")
            if gate and not re.search(rf"^  {gate}:", read("core/lifecycle/gates.yaml"), re.M):
                ERRORS.append(f"{path}: step '{step.id}' names unknown gate '{gate}'")
        check_contract_roles(path, definition)
    return found


def load_contract_meta():
    """{artifact id: x-wgf block} for every top-level artifact schema."""
    meta = {}
    for path in sorted(glob.glob("core/artifacts/*.schema.json")):
        block = json.loads(read(path)).get("x-wgf")
        if block and block.get("id"):
            meta[block["id"]] = block
    return meta


def check_contract_roles(path, definition, meta=None):
    """x-wgf says who produces and who consumes an artifact; a workflow step says the same
    thing in `stage`, `outputs` and `inputs`. Two statements of one fact drift unless one is
    checked against the other, so:

      * every type a step outputs names the step's stage as its x-wgf `producer`;
      * every type a step takes as input lists the step's stage in its x-wgf `consumers`.

    Driven by the definition alone - no step type or id is named here. A step with no
    inputs or outputs (a checkpoint) is checked for what it has. Untyped artifacts have no
    x-wgf block and are left to the untyped-artifact report above. Returns the problems it
    appended, for tests."""
    meta = load_contract_meta() if meta is None else meta
    found = []
    for step in definition.steps:
        if not step.stage:
            continue
        for aid in step.outputs or ():
            block = meta.get(aid)
            if block is not None and block.get("producer") != step.stage:
                found.append(f"{path}: step '{step.id}' outputs '{aid}' at stage "
                             f"'{step.stage}', but its x-wgf producer is "
                             f"'{block.get('producer')}'")
        for aid in step.inputs or ():
            block = meta.get(aid)
            if block is not None and step.stage not in (block.get("consumers") or ()):
                found.append(f"{path}: step '{step.id}' takes '{aid}' at stage "
                             f"'{step.stage}', which its x-wgf consumers do not list")
    ERRORS.extend(found)
    return found


def check_bindings(roles):
    text = read("core/bindings/adapter-binding.yaml")
    for path in re.findall(r"^\s*- (core/\S+)$", text, re.M):
        if not os.path.exists(path.rstrip("/")):
            ERRORS.append(f"adapter-binding.yaml: missing path '{path}'")
    for role in re.findall(r"^\s*role:\s*(\S+)", text, re.M):
        # `null` is legitimate: the status command is read-only and has no owning role.
        if role in ("null", "-"):
            continue
        if role not in roles:
            ERRORS.append(f"adapter-binding.yaml: unknown role '{role}'")


def check_charters():
    for charter in re.findall(r"^\s*charter:\s*(\S+)", read("core/roles/roles.yaml"), re.M):
        if not os.path.exists(os.path.join("core/roles", charter)):
            ERRORS.append(f"roles.yaml: missing charter '{charter}'")


def check_templates():
    for path in sorted(glob.glob("core/artifacts/*.schema.json")):
        tmpl = json.loads(read(path)).get("x-wgf", {}).get("template")
        if tmpl and not os.path.exists(os.path.join("core", tmpl)):
            ERRORS.append(f"{path}: missing template '{tmpl}'")


def pinned_template():
    """(directory, None) for a checkout of the pinned template commit that already exists,
    else (None, why). Never clones and never reads the sibling working copy: this check must
    stay fast and must not fail because the pin is not cached or the network is down.
    `python3 scripts/wgf-template.py --path` obtains the checkout."""
    sys.path.insert(0, "scripts")
    from wgflib import template
    try:
        if os.environ.get("WGF_TEMPLATE_DIR"):
            # template.checkout() uses an offered directory as is, or refuses it as drift.
            return template.checkout(), None
        commit = template.expected_commit()
        # The cache location checkout() itself uses; only its fetch step is skipped here.
        cached = os.path.join(template._cache_root(), commit)
        if template.head_of(cached) == commit:
            return cached, None
        return None, f"web-game-template {commit[:12]} is not cached"
    except template.TemplateError as exc:
        return None, str(exc)


def check_platforms():
    """Platform ids in core must match the strings the pinned template's game.config.yaml
    uses — they are the same identifier crossing a repository boundary. Read at the pin,
    never from the sibling working copy, which may stand at any commit."""
    profiles = {os.path.basename(p)[:-5] for p in glob.glob("core/reference/platforms/*.yaml")}
    directory, why = pinned_template()
    if directory is None:
        NOTES.append(f"platform check skipped: pinned template not available ({why}; "
                     "python3 scripts/wgf-template.py --path fetches it)")
        return profiles
    config = os.path.join(directory, "game.config.yaml")
    if not os.path.exists(config):
        ERRORS.append(f"pinned template {directory}: no game.config.yaml")
        return profiles
    for pid in re.findall(r"\{\s*id:\s*([a-z-]+)", read(config)):
        if pid not in profiles:
            ERRORS.append(f"game.config.yaml (pinned template): platform '{pid}' has no "
                          "profile in core")
    check_template_profiles(directory, profiles)
    return profiles


def check_template_profiles(directory, profiles):
    """A profile is identified by id, version and content: a template copy that declares the
    same id@version as a core profile must be byte-identical to it, or one name answers for
    two documents. A divergence is a template-side defect the Factory cannot fix from here
    (init re-vendors the core copy over it), so it is a WARNING, not a failure."""
    from wgflib.yamllite import YamlError, load_file

    for pid in sorted(profiles):
        theirs = os.path.join(directory, "config", "platforms", f"{pid}.yaml")
        if not os.path.isfile(theirs):
            continue
        ours = os.path.join("core", "reference", "platforms", f"{pid}.yaml")
        try:
            versions = [str((load_file(p) or {}).get("version")) for p in (ours, theirs)]
        except (OSError, YamlError, ValueError) as exc:
            WARNINGS.append(f"cannot compare {ours} with the pinned template's copy: {exc}")
            continue
        if versions[0] != versions[1]:
            continue
        digests = []
        for path in (ours, theirs):
            with open(path, "rb") as handle:
                digests.append(hashlib.sha256(handle.read()).hexdigest())
        if digests[0] != digests[1]:
            WARNINGS.append(
                f"{pid}@{versions[0]}: {ours} (sha256:{digests[0]}) differs from the pinned "
                f"template's config/platforms/{pid}.yaml (sha256:{digests[1]}) under the same "
                "version; template-side divergence, init vendors the core copy")


def check_provider_independence():
    """core/ is AI-provider independent. This is the rule the whole adapter split exists to
    protect, and it degrades silently — one convenient mention of a specific runtime and the
    methodology has quietly acquired a dependency."""
    pattern = re.compile(
        r"\b(claude|codex|anthropic|openai|gpt-[0-9]|gemini|copilot)\b", re.I)
    for root, _dirs, files in os.walk("core"):
        for name in files:
            path = os.path.join(root, name)
            for lineno, line in enumerate(read(path).splitlines(), 1):
                if pattern.search(line):
                    ERRORS.append(f"{path}:{lineno}: names an AI provider — core/ must not")


def check_no_readme_only_dirs():
    """core/README.md is the entry point; any OTHER directory whose only content is a
    README.md is a placeholder, and placeholders are how the previous structure drifted."""
    for root, dirs, files in os.walk("core"):
        if root == "core" or dirs:
            continue
        if files and all(f == "README.md" for f in files):
            ERRORS.append(f"{root}: contains only a README.md")


def check_template_pin():
    """workspace/config/template.lock.json names one web-game-template commit, as a full sha.
    Where the sibling checkout stands against it is reported, never silently used: every
    reader goes through scripts/wgflib/template.py, which checks out exactly the pin."""
    sys.path.insert(0, "scripts")
    from wgflib import template
    try:
        lock = template.load_lock()
    except template.TemplateError as exc:
        ERRORS.append(f"template pin: {exc}")
        return None
    state = template.drift(lock)
    if state.get("sibling") and not state.get("sibling_at_pin"):
        NOTES.append(
            f"template drift: sibling web-game-template is at {state.get('sibling_head')}, "
            f"the Factory is pinned to {lock['commit']}"
            + ("" if state.get("sibling_has_pin") else " (not fetched there)")
            + "; readers use a checkout of the pin")
    return lock


def main():
    if not os.path.isdir("core"):
        sys.exit("run from the web-game-factory repository root")

    artifacts = load_artifacts()
    roles = load_roles()
    gates = read("core/lifecycle/gates.yaml")

    check_machines(artifacts, roles, gates)
    check_required_for_gates()
    workflows = check_workflows(artifacts)
    check_bindings(roles)
    check_charters()
    check_templates()
    platforms = check_platforms()
    check_provider_independence()
    check_no_readme_only_dirs()
    pin = check_template_pin()

    print(f"artifacts   {len(artifacts)}")
    print(f"roles       {len(roles)}")
    print(f"platforms   {', '.join(sorted(platforms))}")
    print(f"machines    {len(glob.glob('core/lifecycle/*.machine.yaml'))}")
    print(f"stages      {len(glob.glob('core/lifecycle/stages/*.md'))}")
    print(f"workflows   {len(workflows)}")
    if pin:
        print(f"template    {pin['repository']}@{pin['commit'][:12]} ({pin['ref']})")
    for note in NOTES:
        print(f"note        {note}")
    for warning in WARNINGS:
        print(f"WARNING     {warning}")
    print()

    if ERRORS:
        print(f"FAILED — {len(ERRORS)} problem(s):")
        for err in ERRORS:
            print(f"  - {err}")
        return 1
    print("referential integrity: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
