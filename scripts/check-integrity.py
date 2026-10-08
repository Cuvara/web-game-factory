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


# The x-wgf `producer` of an artifact a gate emits (decision-record.schema.json), rather than
# one stage's: see check_contract_roles.
GATE_PRODUCER = "gate"


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

      * every type a step outputs names the step's stage as its x-wgf `producer`, or lists
        it in its x-wgf `updated_by` (a record one stage creates and a later one advances:
        platform-publication at release:validating, then release:submitting);
      * every type a step takes as input lists the step's stage in its x-wgf `consumers`.

    An artifact whose x-wgf `producer` is `gate` (GATE_PRODUCER: the decision-record) is
    produced at whatever stage a gate sits, by the step that decides the gate. So:

      * a step outputs a gate-produced type only if it names a gate (`with: gate`);
      * a step that names a gate outputs every gate-produced type - a gate that emits no
        decision-record is not auditable.

    Driven by the definition alone - no step type or id is named here. A step with no
    inputs or outputs is checked for what it has. Untyped artifacts have no x-wgf block and
    are left to the untyped-artifact report above. Returns the problems it appended, for
    tests."""
    meta = load_contract_meta() if meta is None else meta
    found = []
    gate_produced = sorted(aid for aid, block in meta.items()
                           if block.get("producer") == GATE_PRODUCER)
    for step in definition.steps:
        gate = (getattr(step, "params", None) or {}).get("gate")
        if gate:
            for aid in gate_produced:
                if aid not in (step.outputs or ()):
                    found.append(f"{path}: step '{step.id}' decides gate {gate} but does not "
                                 f"output '{aid}' (x-wgf producer '{GATE_PRODUCER}')")
        if not step.stage:
            continue
        for aid in step.outputs or ():
            block = meta.get(aid)
            if block is not None and block.get("producer") == GATE_PRODUCER:
                if not gate:
                    found.append(f"{path}: step '{step.id}' outputs '{aid}', which only a "
                                 f"step deciding a gate produces (x-wgf producer "
                                 f"'{GATE_PRODUCER}'), but names no gate")
                continue
            if (block is not None and block.get("producer") != step.stage
                    and step.stage not in (block.get("updated_by") or ())):
                found.append(f"{path}: step '{step.id}' outputs '{aid}' at stage "
                             f"'{step.stage}', but its x-wgf producer is "
                             f"'{block.get('producer')}' and updated_by does not name "
                             f"the stage")
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


def check_binding_workflows(roles):
    """Every workflow entry point in adapter-binding.yaml `workflows:` runs a real workflow.

    `runs` is a core/ path to `<id>.workflow.yaml` whose definition has that id, and the
    entry's informational `gates` are exactly the gates that workflow's human checkpoints
    name, and every group it `continues` is one of that workflow's `groups` - so the surface
    can neither point at a missing workflow nor describe gates or groups the workflow does
    not have. The workflow file stays the authority; this only checks the
    pointer."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from wgflib.workflow.definition import DefinitionError, load_definition
    from wgflib.yamllite import YamlError, load as load_yaml

    where = "adapter-binding.yaml"
    try:
        binding = load_yaml(read("core/bindings/adapter-binding.yaml")) or {}
    except YamlError as exc:
        ERRORS.append(f"{where}: {exc}")
        return []
    entries = binding.get("workflows") or []
    if not isinstance(entries, list):
        ERRORS.append(f"{where}: `workflows` must be a list")
        return []
    if entries and "workflow" not in (binding.get("surface_kinds") or {}):
        ERRORS.append(f"{where}: `workflows` listed but surface kind 'workflow' is not declared")
    ids = []
    for entry in entries:
        wid = entry.get("id") if isinstance(entry, dict) else None
        if not wid:
            ERRORS.append(f"{where}: workflow entry without an id: {entry!r}")
            continue
        if wid in ids:
            ERRORS.append(f"{where}: workflow '{wid}' listed twice")
        ids.append(wid)
        role = entry.get("role")
        if role is not None and role not in roles:
            ERRORS.append(f"{where}: workflow '{wid}' names unknown role '{role}'")
        runs = entry.get("runs")
        if not runs or not isinstance(runs, str):
            ERRORS.append(f"{where}: workflow '{wid}' has no `runs` path")
            continue
        if not runs.startswith("core/"):
            ERRORS.append(f"{where}: workflow '{wid}' runs '{runs}', which is not under core/")
            continue
        if os.path.basename(runs) != f"{wid}.workflow.yaml":
            ERRORS.append(f"{where}: workflow '{wid}' runs '{runs}'; expected a file named "
                          f"'{wid}.workflow.yaml'")
            continue
        if not os.path.isfile(runs):
            ERRORS.append(f"{where}: workflow '{wid}' runs missing file '{runs}'")
            continue
        try:
            definition = load_definition(runs)
        except (DefinitionError, YamlError) as exc:
            ERRORS.append(f"{where}: workflow '{wid}' runs '{runs}', which does not load: {exc}")
            continue
        if definition.id != wid:
            ERRORS.append(f"{where}: workflow '{wid}' runs '{runs}', whose workflow id is "
                          f"'{definition.id}'")
        declared = entry.get("gates") or []
        actual = [step.params["gate"] for step in definition.steps
                  if step.type == "human-checkpoint" and step.params.get("gate")]
        if sorted(set(declared)) != sorted(set(actual)) or len(declared) != len(set(declared)):
            ERRORS.append(f"{where}: workflow '{wid}' lists gates {declared}; '{runs}' has "
                          f"human checkpoints on {sorted(set(actual))}")
        continues = entry.get("continues") or []
        if not isinstance(continues, list):
            ERRORS.append(f"{where}: workflow '{wid}' `continues` must be a list of group names")
            continues = []
        for group in continues:
            if group not in definition.groups:
                ERRORS.append(f"{where}: workflow '{wid}' continues '{group}', which is not a "
                              f"group of '{runs}' ({', '.join(sorted(definition.groups)) or '-'})")
    return ids


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
    check_template_adapters(directory, profiles)
    return profiles


def check_template_adapters(directory, profiles):
    """The lock's platform_adapters is the pinned template's adapter registry: the list
    strategy and tech-plan refuse every other platform by. A profile without an adapter at the
    pin is allowed - it describes a portal before the template can build for it - and named
    as a note, because no title can target it until a person releases a template carrying the
    adapter and moves the pin."""
    from wgflib import template

    try:
        lock = template.load_lock()
        adapters = template.platform_adapters(lock)
    except template.TemplateError as exc:
        ERRORS.append(f"template pin: {exc}")
        return
    if template.expected_commit(lock) != lock["commit"]:
        NOTES.append("platform adapters not compared: WGF_TEMPLATE_COMMIT points away from "
                     "the lock, whose platform_adapters describe its own commit")
        return
    found = template.registry_adapter_ids(directory)
    if found is None:
        # test_template_contract's drift test requires the registry at the pin; a checkout
        # without one is not a template this list can be held against.
        NOTES.append("platform adapters not compared: the template checkout has no adapter "
                     "registry (KNOWN_PLATFORM_IDS)")
        return
    if sorted(found) != sorted(adapters):
        ERRORS.append(f"workspace/config/template.lock.json platform_adapters "
                      f"{sorted(adapters)} is not the pinned template's adapter registry "
                      f"{sorted(found)}")
    for pid in sorted(set(profiles) - set(found)):
        NOTES.append(f"platform '{pid}' has a profile but no SDK adapter at the pinned template: "
                     "strategy and tech-plan refuse it until a template release carrying it "
                     "is pinned")


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


def check_publication_profiles(directory=os.path.join("core", "reference", "publication"),
                               platforms_dir=os.path.join("core", "reference", "platforms")):
    """Publication profiles (2.0.0): the id is the filename stem and names a platform profile,
    and the console flow keeps the rules the schema cannot state - no cancel, withdraw or
    delete intent; every irreversible intent has a profile locator ladder; every intent has
    a class; adaptive names and dismissable overlays outside the deny vocabulary; the status
    words consistent (wgflib.publication.flow_problems). Returns the profiles checked."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from wgflib.publication import flow_problems
    from wgflib.yamllite import YamlError, load_file

    checked = []
    for path in sorted(glob.glob(os.path.join(directory, "*.yaml"))):
        stem = os.path.basename(path)[:-5]
        try:
            profile = load_file(path)
        except (OSError, YamlError, ValueError) as exc:
            ERRORS.append(f"{path}: does not parse: {exc}")
            continue
        if not isinstance(profile, dict) or profile.get("id") != stem:
            ERRORS.append(f"{path}: id is not the filename stem {stem!r}")
            continue
        if not os.path.isfile(os.path.join(platforms_dir, f"{stem}.yaml")):
            ERRORS.append(f"{path}: no platform profile {platforms_dir}/{stem}.yaml")
        for problem in flow_problems(profile):
            ERRORS.append(f"{path}: {problem}")
        checked.append(stem)
    return checked


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


def check_plugin_version():
    """The Claude plugin is released with the Factory, so its manifest version is VERSION.
    The host detects plugin updates by that field alone: a stale one means an installed
    plugin never updates. The marketplace entry carries no version of its own - the
    manifest's would silently win over it, leaving two numbers that can disagree."""
    release = read("VERSION").strip()
    manifest = json.loads(read("claude-web-game-plugin/.claude-plugin/plugin.json"))
    if manifest.get("version") != release:
        ERRORS.append(f"claude-web-game-plugin/.claude-plugin/plugin.json: version "
                      f"'{manifest.get('version')}' is not VERSION '{release}'")
    for entry in json.loads(read(".claude-plugin/marketplace.json")).get("plugins", []):
        if "version" in entry:
            ERRORS.append(f".claude-plugin/marketplace.json: plugin '{entry.get('name')}' "
                          "sets a version; plugin.json is the only place it lives")


def check_plugin_runtime():
    """The Claude plugin ships the Factory runtime (claude-web-game-plugin/runtime/), because
    an installed plugin is a copy of its own directory and nothing else. The bundle must be
    the source's runtime closure byte for byte (scripts/build-plugin-runtime.py), or an
    installed plugin runs a Factory this repository no longer is."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "build_plugin_runtime", os.path.join("scripts", "build-plugin-runtime.py"))
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    for problem in builder.check(builder.DEFAULT_DEST, root="."):
        ERRORS.append(f"{builder.DEFAULT_DEST}: {problem} (run scripts/gen-adapters.sh)")


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


# The ref the knowledge is compared with (WGF_KNOWLEDGE_BASE overrides it): see
# knowledge_base.
KNOWLEDGE_BASE = "origin/main"


def _git(*args):
    """(returncode, stdout bytes) of a git command in the working directory; (None, b"")
    when git cannot run."""
    import subprocess
    try:
        done = subprocess.run(["git", *args], capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return None, b""
    return done.returncode, done.stdout


def _commit(ref):
    code, out = _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return out.decode("utf-8", "replace").strip() if code == 0 and out.strip() else None


def knowledge_base(ref=None):
    """(commit, why): the commit the knowledge is compared with - the merge base of `ref`
    (WGF_KNOWLEDGE_BASE, else KNOWLEDGE_BASE) and HEAD: a pull request's base, a push's
    previous tip. A base that IS HEAD (a push to the base branch itself, a run on it) is
    HEAD's first parent, never HEAD compared with itself. (None, why) when there is none."""
    ref = ref or os.environ.get("WGF_KNOWLEDGE_BASE") or KNOWLEDGE_BASE
    head = _commit("HEAD")
    target = _commit(ref)
    if head is None or target is None:
        return None, f"{ref} is not a commit in this checkout"
    code, out = _git("merge-base", target, head)
    base = out.decode("utf-8", "replace").strip() if code == 0 and out.strip() else target
    if base == head:
        base = _commit("HEAD^")
        if base is None:
            return None, "HEAD has no parent to compare with"
    return base, f"{ref} ({base[:12]})"


def _at(commit, relative):
    """("ok", bytes) | ("absent", None) | ("error", why) for a file at `commit`."""
    code, _ = _git("cat-file", "-e", f"{commit}:{relative}")
    if code is None:
        return "error", "git cannot run"
    if code != 0:
        return "absent", None
    code, out = _git("show", f"{commit}:{relative}")
    return ("ok", out) if code == 0 else ("error", f"git show {commit}:{relative} failed")


def previous_knowledge(commit):
    """(lessons, checks) at `commit`, each side's own: the lessons file, and its check
    tiers classified against the files they enumerate AS THEY WERE at that commit. lessons
    is None when the commit has no lessons file (it is being introduced). Raises ValueError
    when the files exist but cannot be read."""
    from wgf_quality import registry
    from wgflib.yamllite import load as load_yaml

    state, data = _at(commit, registry.LESSONS_FILE)
    if state == "error":
        raise ValueError(data)
    if state == "absent":
        return None, None
    lessons = load_yaml(data.decode("utf-8"))
    state, data = _at(commit, registry.TIERS_FILE)
    if state != "ok":
        return lessons, None
    tiers = load_yaml(data.decode("utf-8"))

    def reader(relative):
        found, content = _at(commit, relative)
        if found != "ok":
            raise OSError(f"{relative} is not at {commit[:12]}")
        return load_yaml(content.decode("utf-8"))

    checks, _ = registry.classify(tiers, os.getcwd(), reader=reader)
    return lessons, checks


def check_regression_registry():
    """WS-9: every check the reference files and producer tables declare has a tier
    (core/reference/check-tiers.yaml) and a place its result is read (`status_at`), and every
    lesson (core/reference/lessons.yaml) marked enforced or partial points at a classified
    check and a test that exists, a gap says what is missing, and no lesson names a game. A
    new check without a tier fails here.

    The knowledge model (lessons.yaml 2.0.0, docs/knowledge-enforcement.md): every lesson has
    a category, a scope in its vocabularies, a problem, a root cause and a derivable level;
    a declared level is only ever stronger than the derived one; the lifecycle's
    requirements and the exception policy hold. Against the knowledge at the base commit
    (knowledge_base: a pull request's merge base, a push's previous tip) - each side judged
    by its own check tiers - no lesson was deleted, held weaker in a run, stripped of a
    check, narrowed in scope, and the exception policy was not loosened, in place. With
    WGF_KNOWLEDGE_STRICT=1 (CI) a base that cannot be found is an error; a base without a
    lessons file is the change that introduces it, and is allowed."""
    sys.path.insert(0, "scripts")
    from wgf_quality import registry
    from wgf_knowledge import model

    problems = registry.problems(os.getcwd())
    ERRORS.extend(problems)
    data = registry.load(os.getcwd())
    checks, _ = registry.classify(data["tiers"], os.getcwd())
    strict = os.environ.get("WGF_KNOWLEDGE_STRICT") == "1"
    base, why = knowledge_base()
    if base is None:
        (ERRORS if strict else NOTES).append(
            f"lessons: no base to compare the knowledge with ({why})"
            + ("" if strict else " - not compared; CI holds it"))
    else:
        try:
            previous, previous_checks = previous_knowledge(base)
        except (OSError, ValueError) as exc:
            ERRORS.append(f"lessons: the knowledge at {why} cannot be read ({exc})")
        else:
            if previous is None:
                NOTES.append(f"lessons: {registry.LESSONS_FILE} is introduced by this change "
                             f"(none at {why})")
            else:
                ERRORS.extend(model.weakening_problems(
                    previous, data["lessons"], previous_checks or checks, checks))
                NOTES.append(f"lessons: compared with {why}")
    lessons = (data["lessons"] or {}).get("lessons") or []
    return checks, lessons


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
    entry_points = check_binding_workflows(roles)
    check_charters()
    check_templates()
    platforms = check_platforms()
    publication = check_publication_profiles()
    check_provider_independence()
    check_no_readme_only_dirs()
    check_plugin_version()
    check_plugin_runtime()
    pin = check_template_pin()
    tiered, lessons = check_regression_registry()

    print(f"artifacts   {len(artifacts)}")
    print(f"roles       {len(roles)}")
    print(f"platforms   {', '.join(sorted(platforms))}")
    print(f"publication {len(publication)} profile(s)")
    print(f"machines    {len(glob.glob('core/lifecycle/*.machine.yaml'))}")
    print(f"stages      {len(glob.glob('core/lifecycle/stages/*.md'))}")
    print(f"workflows   {len(workflows)}")
    print(f"entry points {', '.join(entry_points) or '-'}")
    print(f"checks      {len(tiered)} tiered, {len(lessons)} lesson(s)")
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
