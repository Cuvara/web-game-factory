"""Read the platform SDK a game repository actually carries.

The SDK is web-game-template's `packages/platform-sdk`, copied into the game at scaffolding.
It is not described anywhere in the Factory, and it changes by template revision: one
revision has a Poki adapter and another does not, one declares `adAvailability` on
`Platform` and another does not. So nothing here assumes; everything is read off the
source in the game repository, the way a person would read it:

    package.json              the SDK package and its version
    src/types.ts              the members of the `Platform` interface - the API game code has
    src/registry.ts           which platform ids construct an adapter, and which throw
    src/adapters/**           each adapter's capabilities constant and portal SDK URL

This is a reader for a known, small, hand-written shape, not a TypeScript parser. Anything it
cannot read is reported as unknown, never guessed.
"""

import json
import os
import re

__all__ = ["SdkInspection", "AdapterInfo", "inspect_sdk", "SDK_DIR"]

SDK_DIR = os.path.join("packages", "platform-sdk")

_LINE_COMMENT = re.compile(r"//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_CASE = re.compile(r'^\s*case\s+"([a-z][a-z0-9-]*)"\s*:')
_RETURN_NEW = re.compile(r"\breturn\s+new\s+([A-Za-z_]\w*)\s*\(")
_IMPORT = re.compile(r'import\s*\{([^}]*)\}\s*from\s*"(\.[^"]+)"')
_MEMBER = re.compile(r"^  (?:readonly\s+)?([A-Za-z_]\w*)\??\s*[(<:]")
_CAPABILITIES_FIELD = re.compile(r"\bcapabilities\s*(?::\s*\w+\s*)?=\s*([A-Z][A-Z0-9_]*)\s*;")
_SDK_URL = re.compile(r'export\s+const\s+([A-Z][A-Z0-9_]*_SDK_URL)\s*=\s*"([^"]*)"')


def _strip_comments(text):
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class AdapterInfo:
    """One platform id as the registry resolves it."""

    def __init__(self, platform_id, class_name=None, source=None, capabilities=None,
                 portal_sdk=None):
        self.platform_id = platform_id
        self.class_name = class_name            # None: the registry throws for this id
        self.source = source                    # repo-relative adapter file
        self.capabilities = capabilities        # dict, or None when unreadable
        self.portal_sdk = portal_sdk            # e.g. {"constant": ..., "url": ...}

    @property
    def implemented(self):
        return self.class_name is not None

    def supports_ad(self, kind):
        return bool(self.capabilities) and kind in (self.capabilities.get("ads") or [])

    def capability(self, name, default=None):
        return (self.capabilities or {}).get(name, default)


class SdkInspection:
    def __init__(self, package, version, members, adapters, problems):
        self.package = package
        self.version = version
        self.members = members                  # Platform interface member names
        self.adapters = adapters                # platform id -> AdapterInfo
        self.problems = problems                # what could not be read

    def has_member(self, name):
        return name in self.members

    def adapter(self, platform_id):
        return self.adapters.get(platform_id) or AdapterInfo(platform_id)


def _platform_members(types_text):
    text = _strip_comments(types_text)
    start = re.search(r"^export interface Platform \{", text, re.M)
    if not start:
        return []
    members = []
    for line in text[start.end():].splitlines():
        if line.startswith("}"):
            break
        match = _MEMBER.match(line)
        if match and match.group(1) not in members:
            members.append(match.group(1))
    return members


def _registry(registry_text):
    """platform id -> constructed class name, or None where the id throws."""
    text = _strip_comments(registry_text)
    body = re.search(r"export function createPlatform\b.*", text, re.S)
    resolved, pending = {}, []
    for line in (body.group(0) if body else "").splitlines():
        case = _CASE.match(line)
        if case:
            pending.append(case.group(1))
            continue
        construct = _RETURN_NEW.search(line)
        if construct and pending:
            for platform_id in pending:
                resolved[platform_id] = construct.group(1)
            pending = []
        elif re.search(r"\bthrow\b", line) and pending:
            for platform_id in pending:
                resolved[platform_id] = None
            pending = []
    imports = {}
    for names, module in _IMPORT.findall(text):
        for name in names.split(","):
            name = name.strip().split(" as ")[-1].strip()
            if name and not name.startswith("type "):
                imports[name] = module
    return resolved, imports


def _literal(value):
    value = value.strip().rstrip(",").strip()
    if value in ("true", "false"):
        return value == "true"
    if value == "null":
        return None
    if value.startswith("[") and value.endswith("]"):
        return re.findall(r'"([^"]*)"', value)
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value


def _capabilities(text, constant):
    """The object literal assigned to `constant`, as a flat dict."""
    match = re.search(r"export\s+const\s+" + re.escape(constant)
                      + r"\s*(?::\s*\w+\s*)?=\s*\{(.*?)\n\};", _strip_comments(text), re.S)
    if not match:
        return None
    result = {}
    for key, value in re.findall(r"^\s*([A-Za-z_]\w*)\s*:\s*(.+?),?\s*$", match.group(1), re.M):
        result[key] = _literal(value)
    return result


def _module_file(sdk_src, module):
    base = os.path.normpath(os.path.join(sdk_src, module))
    for candidate in (base, base[:-3] + ".ts" if base.endswith(".js") else base + ".ts"):
        if os.path.isfile(candidate):
            return candidate
    return None


def _adapter_files(sdk_src):
    root = os.path.join(sdk_src, "adapters")
    for directory, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            if name.endswith(".ts") and not name.endswith(".d.ts"):
                yield os.path.join(directory, name)


def inspect_sdk(repo):
    """Inspect `<repo>/packages/platform-sdk`. Returns None when the game has no SDK."""
    sdk_root = os.path.join(repo, SDK_DIR)
    sdk_src = os.path.join(sdk_root, "src")
    if not os.path.isdir(sdk_src):
        return None
    problems = []

    package, version = "@wgf/platform-sdk", None
    try:
        manifest = json.loads(_read(os.path.join(sdk_root, "package.json")))
        package, version = manifest.get("name", package), manifest.get("version")
    except (OSError, ValueError) as exc:
        problems.append(f"package.json unreadable: {exc}")

    try:
        members = _platform_members(_read(os.path.join(sdk_src, "types.ts")))
    except OSError as exc:
        members = []
        problems.append(f"types.ts unreadable: {exc}")
    if not members:
        problems.append("no `Platform` interface found in types.ts")

    try:
        resolved, imports = _registry(_read(os.path.join(sdk_src, "registry.ts")))
    except OSError as exc:
        resolved, imports = {}, {}
        problems.append(f"registry.ts unreadable: {exc}")

    sources = {path: _read(path) for path in _adapter_files(sdk_src)}
    adapters = {}
    for platform_id, class_name in resolved.items():
        if class_name is None:
            adapters[platform_id] = AdapterInfo(platform_id)
            continue
        path = _module_file(sdk_src, imports[class_name]) if class_name in imports else None
        if path is None:  # imported from somewhere unexpected: find the class instead
            path = next((p for p, t in sources.items()
                         if re.search(r"\bclass\s+" + class_name + r"\b", t)), None)
        text = sources.get(path) or (_read(path) if path else "")
        field = _CAPABILITIES_FIELD.search(_strip_comments(text))
        capabilities = None
        if field:
            constant = field.group(1)
            for candidate in [text, *sources.values()]:
                capabilities = _capabilities(candidate, constant)
                if capabilities is not None:
                    break
        if capabilities is None:
            problems.append(f"capabilities of {class_name} ({platform_id}) not readable")
        # An adapter in a directory of its own may keep its portal SDK URL in a sibling
        # file (crazygames/sdk.ts); one directly under adapters/ has only itself.
        own_dir = os.path.dirname(path) if path else None
        siblings = [] if own_dir in (None, os.path.join(sdk_src, "adapters")) else [
            t for p, t in sources.items() if os.path.dirname(p) == own_dir]
        url = next((m for m in (_SDK_URL.search(t) for t in [text, *siblings]) if m), None)
        adapters[platform_id] = AdapterInfo(
            platform_id,
            class_name=class_name,
            source=os.path.relpath(path, repo).replace(os.sep, "/") if path else None,
            capabilities=capabilities,
            portal_sdk={"constant": url.group(1), "url": url.group(2)} if url else None,
        )
    return SdkInspection(package, version, members, adapters, problems)
