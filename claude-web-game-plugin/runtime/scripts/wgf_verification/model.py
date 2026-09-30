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

Beside its status every check carries an EVIDENCE STATUS: how strong the evidence behind it
is, in the vocabulary a release carries forward.

    PASS              observed against the real thing: a command's exit code, a test report
                      file, a browser run of the built bundle
    PASS_MOCK         observed only against a stand-in - an SDK feature exercised against a
                      mocked or fake portal SDK. Never reported, summed or promoted as PASS.
    BLOCKED_EXTERNAL  cannot be established from here: it needs an outside party (a portal's
                      own QA or review) and no evidence from that party exists
    UNVERIFIED        not established: blocked by a missing tool or prerequisite, or an
                      optional requirement nobody evidenced (status BLOCKED or WARNING)
    FAIL              evidence shows the requirement does not hold

The status decides routing (FAIL loops to development, BLOCKED stops the run); the evidence
status decides what may be claimed about the build afterwards.
"""

from dataclasses import dataclass, field

__all__ = ["PASS", "FAIL", "BLOCKED", "WARNING", "STATUSES", "CATEGORIES", "Evidence", "Check",
           "verdict_of", "PASS_MOCK", "BLOCKED_EXTERNAL", "UNVERIFIED", "EVIDENCE_STATUSES",
           "evidence_status_of", "overall_evidence_status", "weakest"]

PASS, FAIL, BLOCKED, WARNING = "PASS", "FAIL", "BLOCKED", "WARNING"
STATUSES = (PASS, FAIL, BLOCKED, WARNING)

# Evidence statuses, strongest first. PASS and FAIL are shared with STATUSES on purpose: they
# mean the same thing in both vocabularies.
PASS_MOCK, BLOCKED_EXTERNAL, UNVERIFIED = "PASS_MOCK", "BLOCKED_EXTERNAL", "UNVERIFIED"
EVIDENCE_STATUSES = (PASS, PASS_MOCK, BLOCKED_EXTERNAL, UNVERIFIED, FAIL)
# How a status maps when a check does not say otherwise. A check may only ever WEAKEN this
# (PASS -> PASS_MOCK, BLOCKED -> BLOCKED_EXTERNAL); it is refused if it tries to strengthen it.
_DEFAULT_EVIDENCE = {PASS: PASS, FAIL: FAIL, BLOCKED: UNVERIFIED, WARNING: UNVERIFIED}
_ALLOWED_EVIDENCE = {PASS: (PASS, PASS_MOCK), FAIL: (FAIL,),
                     BLOCKED: (UNVERIFIED, BLOCKED_EXTERNAL),
                     WARNING: (UNVERIFIED, BLOCKED_EXTERNAL, PASS_MOCK)}
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
    # None: derived from `status`. Set only to weaken it - see _ALLOWED_EVIDENCE.
    evidence_status: str = None

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f"check {self.id}: unknown status {self.status!r}")
        if self.evidence_status is not None and self.evidence_status not in EVIDENCE_STATUSES:
            raise ValueError(f"check {self.id}: unknown evidence status "
                             f"{self.evidence_status!r}")
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
            "evidence_status": evidence_status_of(self),
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


def evidence_status_of(check):
    """The check's evidence status: its own if it set one the status allows, else derived.

    Derived on every read rather than stored, because a check's status can be changed after
    construction (a console error turns a passing boot into a failure) and the evidence
    status must follow it - never lag behind as a stale PASS.
    """
    own = check.evidence_status
    if own is not None and own in _ALLOWED_EVIDENCE[check.status]:
        return own
    return _DEFAULT_EVIDENCE[check.status]


def weakest(statuses):
    """The weakest of some evidence statuses; PASS for none."""
    rank = {s: i for i, s in enumerate(EVIDENCE_STATUSES)}
    statuses = [s for s in statuses if s]
    return max(statuses, key=rank.__getitem__) if statuses else PASS


def overall_evidence_status(checks):
    """What the verification as a whole establishes, over its REQUIRED checks.

    FAIL if a required check failed; UNVERIFIED if one could not be established, or
    BLOCKED_EXTERNAL when every one that could not was waiting on an outside party;
    PASS_MOCK when everything passed but something only against a stand-in; else PASS.
    No checks at all establishes nothing: UNVERIFIED.
    """
    required = [evidence_status_of(c) for c in checks if c.required]
    if not checks:
        return UNVERIFIED
    return weakest(required)
