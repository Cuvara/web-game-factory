"""Evidence a publication step records: redacted before it is written, hashed where it is a
file, cited by run-relative path (platform-publication.schema.json `evidence[]`)."""

import hashlib
import os

from wgflib import redact

__all__ = ["Evidence", "file_sha256", "relative_to_run", "tail"]

TAIL_LINES, TAIL_CHARS = 40, 4000


def tail(text, lines=TAIL_LINES, chars=TAIL_CHARS):
    if not text:
        return ""
    kept = "\n".join(text.rstrip().splitlines()[-lines:])
    return kept[-chars:]


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def relative_to_run(path, run_dir):
    if not run_dir or not path:
        return path
    try:
        return os.path.relpath(path, run_dir).replace(os.sep, "/")
    except ValueError:  # another drive on Windows
        return path


class Evidence:
    """One entry. Every text field is scrubbed (wgflib.redact) at construction."""

    def __init__(self, kind, summary, *, phase=None, path=None, content_hash=None,
                 command=None, exit_code=None, output_tail=None, data=None):
        self.kind = kind
        self.summary = redact.scrub_text(str(summary))
        self.phase = phase
        self.path = path
        self.content_hash = content_hash
        self.command = redact.scrub_text(command) if command else None
        self.exit_code = exit_code
        self.output_tail = redact.scrub_text(tail(output_tail)) if output_tail else None
        self.data = redact.scrub(data) if data else None

    @classmethod
    def guard(cls, name, result):
        return cls("guard", f"{name}: {result.symbol} - {result.reason}",
                   data={"guard": name, "verdict": result.symbol,
                         **({"measurements": result.measurements} if result.measurements else {})})

    @classmethod
    def file(cls, summary, path, run_dir=None, phase=None, hash_it=True):
        digest = file_sha256(path) if hash_it and os.path.isfile(path) else None
        return cls("file", summary, phase=phase, path=relative_to_run(path, run_dir),
                   content_hash=digest)

    @classmethod
    def screenshot(cls, summary, path, run_dir=None, phase=None):
        return cls("screenshot", summary, phase=phase, path=relative_to_run(path, run_dir),
                   content_hash=file_sha256(path) if os.path.isfile(path) else None)

    @classmethod
    def console_text(cls, summary, text, phase=None):
        return cls("console-text", summary, phase=phase,
                   data={"text": redact.scrub_text(tail(text, 20, 2000))})

    @classmethod
    def of_process(cls, summary, result, phase=None):
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        return cls("command", summary, phase=phase,
                   command=" ".join(os.path.basename(a) if i == 0 else a
                                    for i, a in enumerate(result.argv)),
                   exit_code=result.returncode, output_tail=output or None)

    def to_dict(self):
        out = {"kind": self.kind, "summary": self.summary}
        for key in ("phase", "path", "content_hash", "command", "exit_code", "output_tail",
                    "data"):
            value = getattr(self, key)
            if value is not None and value != "":
                out[key] = value
        return out
