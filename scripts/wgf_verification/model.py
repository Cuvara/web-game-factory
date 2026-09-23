"""The verification vocabulary: a check, its status, and the evidence behind it.

A check is one question about a build ("does it typecheck", "does the game restart after a
game over") with one of four answers:

    PASS     - evidence shows the requirement holds
    FAIL     - evidence shows it does not
    BLOCKED  - it could not be established: no checkout, a missing tool, or a check it
               depends on did not pass. A statement about the verification, not the game.
    WARNING  - evidence shows a problem that does not stop a release, or an optional
               requirement nobody provided evidence for

Every check carries at least one piece of evidence, whatever its status. A PASS with no
evidence is an assertion, and the verification-report schema refuses it.
"""

from dataclasses import dataclass, field

__all__ = ["PASS", "FAIL", "BLOCKED", "WARNING", "STATUSES", "CATEGORIES", "Evidence", "Check",
           "verdict_of"]

PASS, FAIL, BLOCKED, WARNING = "PASS", "FAIL", "BLOCKED", "WARNING"
STATUSES = (PASS, FAIL, BLOCKED, WARNING)
CATEGORIES = ("source", "build", "code", "gameplay", "platform", "assets", "policy")

# How much command output a piece of evidence keeps. Enough to see the failure, not the log.
OUTPUT_TAIL_LINES = 40
OUTPUT_TAIL_CHARS = 4000


def tail(text, lines=OUTPUT_TAIL_LINES, chars=OUTPUT_TAIL_CHARS):
    if not text:
        return ""
    kept = "\n".join(text.rstrip().splitlines()[-lines:])
    return kept[-chars:]


@dataclass
class Evidence:
    kind: str                      # command | file | test | observation | artifact | reference
    summary: str
    command: str = None
    exit_code: int = None
    duration_s: float = None
    output_tail: str = None
    path: str = None
    content_hash: str = None
    check_ref: str = None
    data: dict = None

    def to_dict(self):
        out = {"kind": self.kind, "summary": self.summary}
        for key in ("command", "exit_code", "duration_s", "output_tail", "path", "content_hash",
                    "check_ref", "data"):
            value = getattr(self, key)
            if value is not None and value != "":
                out[key] = value
        return out

    @classmethod
    def of_command(cls, result, summary=None):
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        return cls(
            kind="command",
            summary=summary or result.describe(),
            command=result.display,
            exit_code=result.exit_code,
            duration_s=round(result.duration_s, 3),
            output_tail=tail(output) or None,
        )


@dataclass
class Check:
    id: str
    category: str
    title: str
    status: str
    required: bool = True
    message: str = ""
    evidence: list = field(default_factory=list)
    platform_id: str = None
    # Test counts, when the check ran a suite. Feeds qa-report.suites.
    counts: dict = None

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f"check {self.id}: unknown status {self.status!r}")
        if self.category not in CATEGORIES:
            raise ValueError(f"check {self.id}: unknown category {self.category!r}")
        if not self.evidence:
            raise ValueError(f"check {self.id}: a check without evidence is an assertion")

    @property
    def blocking(self):
        """Stops a release: a required check that did not pass. Warnings never block."""
        return self.required and self.status in (FAIL, BLOCKED)

    def to_dict(self):
        out = {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "status": self.status,
            "required": self.required,
            "message": self.message,
            "evidence": [e.to_dict() for e in self.evidence],
        }
        if self.platform_id:
            out["platform_id"] = self.platform_id
        if self.counts:
            out["counts"] = dict(self.counts)
        return out


def verdict_of(checks):
    """FAIL if a required check failed; else BLOCKED if one could not be verified; else PASS.

    FAIL wins over BLOCKED because a failure is actionable now - development can fix it -
    while a blocked check may well pass once whatever blocked it is fixed.
    """
    required = [c for c in checks if c.required]
    if any(c.status == FAIL for c in required):
        return FAIL
    if any(c.status == BLOCKED for c in required):
        return BLOCKED
    if not checks:
        return BLOCKED
    return PASS
