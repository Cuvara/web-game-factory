"""The Factory as it was before Session A taught it L29 - for the knowledge-transfer test.

The cross-session test (scripts/tests/test_knowledge_transfer.py) needs the Factory both
ways: Session A runs on the Factory that did not know the principle yet (so its game can
debut two elements at once, and only a gate's measurement notices), and the control of
Session B runs on it too (so the benefit is shown to come from the knowledge). Nothing is
copied or edited in the repository: this module filters, in memory and in the one process
that installs it, the four Factory files that carry what Session A taught -

    core/reference/lessons.yaml                  the lesson L29
    core/reference/check-tiers.yaml              its build check's tier
    core/reference/content-sufficiency.yaml      its build check
    core/reference/design-consistency-rules.yaml its design rule

- wherever a run reads them: the copies a run pins when it starts (references.collect), the
design rules (wgf_design.consistency.RULES_PATH), the content bars
(wgf_sufficiency.audit.RULES_PATH) and, for `wgf knowledge ingest|promote`, the Factory root
the knowledge CLI reads (a temporary copy of what it reads, cli._root). Every removal is
asserted: if one of those files changes shape, this fails loudly instead of filtering
nothing.

Everything else - the code, every other rule and check, the trace rule - is the Factory as
shipped. Not a test module.
"""

import os
import re
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.dirname(TESTS)
ROOT = os.path.dirname(SCRIPTS)

CHECK = "content.introductions_one_at_a_time"
LESSON = "L29"
FILES = ("core/reference/lessons.yaml", "core/reference/check-tiers.yaml",
         "core/reference/content-sufficiency.yaml",
         "core/reference/design-consistency-rules.yaml")


def _drop_list_item(text, first_line, comment_marker=None):
    """`text` without the YAML list item that starts at `first_line` (and the comment block
    right above it that starts with `comment_marker`), up to the next item or block."""
    lines = text.split("\n")
    start = lines.index(first_line)
    indent = len(first_line) - len(first_line.lstrip())
    end = start + 1
    while end < len(lines):
        line = lines[end]
        stripped = line.lstrip()
        if line.strip() and (len(line) - len(stripped)) <= indent \
                and (stripped.startswith("- ") or not line.startswith(" " * (indent + 1))):
            break
        end += 1
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    if comment_marker:
        top = start
        while top > 0 and lines[top - 1].lstrip().startswith("#"):
            top -= 1
        assert any(comment_marker in l for l in lines[top:start]), comment_marker
        start = top
    return "\n".join(lines[:start] + lines[end:])


def filtered(relpath, data):
    """`data` (bytes) of a Factory file as the pre-L29 Factory had it."""
    if relpath not in FILES:
        return data
    text = data.decode("utf-8")
    if relpath == "core/reference/lessons.yaml":
        out = _drop_list_item(text, f"  - id: {LESSON}")
    elif relpath == "core/reference/check-tiers.yaml":
        out = text.replace(f"      {CHECK}: hard\n", "", 1)
    elif relpath == "core/reference/content-sufficiency.yaml":
        out = re.sub(r"(?ms)^  # 1\.5\.0\. The design rule .*?^  " + re.escape(CHECK)
                     + r": \{[^\n]*\}\n?", "", text, count=1)
    else:
        out = _drop_list_item(text, f"  - id: {CHECK}", comment_marker="2.2.0. A unit")
    assert out != text, f"{relpath}: nothing was filtered"
    if relpath.endswith("lessons.yaml"):
        assert f"id: {LESSON}" not in out, "L29 is still in lessons.yaml"
    else:
        assert not re.search(r"(?m)^\s+(- id: )?" + re.escape(CHECK) + r"\b", out), \
            f"{relpath}: {CHECK} is still declared"
    return out.encode("utf-8")


def _write_filtered(directory, files=FILES):
    """The files (all four by default), filtered, under `directory`; {relpath: path}."""
    out = {}
    for relpath in files:
        with open(os.path.join(ROOT, *relpath.split("/")), "rb") as handle:
            data = filtered(relpath, handle.read())
        target = os.path.join(directory, *relpath.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)
        out[relpath] = target
    return out


def knowledge_root(directory, lesson_only=False):
    """A temporary Factory root holding what the knowledge CLI reads (the registry's files,
    the code its check tiers name, the artifact schemas, the platform profiles, the instance
    evidence), with the four files filtered - or, `lesson_only`, with only L29 taken out of
    lessons.yaml: the Factory once a person has implemented the check a candidate proposes,
    before the lesson is promoted. Returns its path."""
    import sys
    if TESTS not in sys.path:
        sys.path.insert(0, TESTS)
    from test_regression_registry import Sandbox
    root = os.path.join(directory, "factory-without-L29" if lesson_only
                        else "factory-before-L29")
    for relative in Sandbox.FILES:
        target = os.path.join(root, *relative.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(ROOT, *relative.split("/")), target)
    for relative in Sandbox.TREES:
        source = os.path.join(ROOT, *relative.split("/"))
        for current, _dirs, files in os.walk(source):
            if "__pycache__" in current:
                continue
            for name in files:
                if name.endswith(".py"):
                    rel = os.path.relpath(os.path.join(current, name), ROOT)
                    target = os.path.join(root, rel)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.copyfile(os.path.join(current, name), target)
    for relative in Sandbox.DATA_TREES:
        shutil.copytree(os.path.join(ROOT, *relative.split("/")),
                        os.path.join(root, *relative.split("/")))
    _write_filtered(root, FILES[:1] if lesson_only else FILES)
    # The instance evidence did not have L29 either: promote drafts its entry.
    evidence = os.path.join(root, "workspace", "lessons", "evidence.yaml")
    with open(evidence, encoding="utf-8") as handle:
        lines = handle.read().splitlines(keepends=True)
    kept = [line for line in lines if not line.startswith(f"  {LESSON}: ")]
    assert len(kept) == len(lines) - 1, "L29's evidence line was not found"
    with open(evidence, "w", encoding="utf-8", newline="") as handle:
        handle.write("".join(kept))
    return root


def install(directory=None, pins_only=False):
    """Patch this process to read the pre-L29 Factory wherever a run reads those files.
    `pins_only`: only the copies a run pins when it STARTS - a run started on the Factory
    before L29, whose steps then run on today's code and today's live files (what a person
    resuming an old run gets). Returns the directory holding the filtered copies."""
    from wgflib.workflow import references
    from wgf_design import consistency
    from wgf_sufficiency import audit
    directory = directory or tempfile.mkdtemp(prefix="wgf-before-l29-")
    paths = _write_filtered(directory)
    real = references.collect

    def collect(relpaths, root=None):
        return {relpath: filtered(relpath, data)
                for relpath, data in real(relpaths, root).items()}

    references.collect = collect
    if pins_only:
        return directory
    consistency.RULES_PATH = paths["core/reference/design-consistency-rules.yaml"]
    audit.RULES_PATH = paths["core/reference/content-sufficiency.yaml"]
    return directory
