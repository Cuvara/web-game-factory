"""ConsoleAdapter: a portal with no API, driven through its developer console by the direct
Playwright executor (wgf_publish.browser), deterministically.

A subclass supplies the selector map for its portal (`selectors()`), the console URL comes
from the publication profile, and the phases are fixed: authenticate, find_existing, upload
(skipped when the idempotency key is already on a draft), configure, submit (only when the
job says so - once), verify. The executor's result is mapped here into the common outcomes;
the portal's own status words are mapped through the profile's `status` lists (publication
profile 2.0.0; `verification` before).

Selector maps for live portals are hypotheses until a person has run them against the real
console (profile `status: verified`); until then the step never reaches this adapter for
them, because the profile's `automation_terms` is unverified too.
"""

import os

from wgflib import redact

from .. import outcomes
from ..browser import BrowserExecutor
from ..evidence import Evidence
from .base import Publication, PublicationAdapter, utc_now

__all__ = ["ConsoleAdapter"]

PHASES = ("authenticate", "find_existing", "upload", "configure", "submit", "verify")
DEFAULT_TIMEOUTS = {"action": 5000, "navigation": 60000, "upload": 900000}

# Executor phase outcomes -> publication outcomes, for a phase that stopped the run.
_STOPS = {
    "login_required": (outcomes.AUTH_REQUIRED, "login"),
    "captcha": (outcomes.CAPTCHA_REQUIRED, "captcha"),
    "two_factor": (outcomes.HUMAN_REQUIRED, "two-factor"),
    "timeout": (outcomes.RETRYABLE_FAILURE, None),
    "error": (outcomes.PLATFORM_ERROR, None),
}


class ConsoleAdapter(PublicationAdapter):
    method = "console"
    # The listing fields the portal's console has, by metadata key: subclasses extend.
    metadata_fields = ("title", "description")

    def selectors(self):
        """{name: css selector or url}. See browser/console.spec.ts for the names."""
        raise NotImplementedError

    def base_url(self, job):
        """The console's base url: the installation's override, else the profile's."""
        return (getattr(job, "console_url", None) or self.settings.get("console_url")
                or (self.submission.get("console") or {}).get("url"))

    def console_url(self, job):
        """Where `authenticate` opens: the page that shows the console when the session is
        live and the login form when it is not. The base url, unless a subclass knows better."""
        return self.base_url(job)

    def allowed_origins(self, job):
        """The origins the browser may reach: the profile's, plus the console url's own."""
        from urllib.parse import urlsplit
        origins = []
        for url in list((self.submission.get("console") or {}).get("allowed_origins") or [])                 + [self.base_url(job), self.console_url(job)]:
            parts = urlsplit(str(url or ""))
            if not parts.scheme or not parts.netloc:
                continue
            origin = f"{parts.scheme}://{parts.netloc}"
            if origin not in origins:
                origins.append(origin)
        return origins

    def timeouts(self, job):
        out = dict(DEFAULT_TIMEOUTS)
        upload_s = (self.submission.get("console") or {}).get("upload_timeout_s")
        if isinstance(upload_s, int):
            out["upload"] = upload_s * 1000
        out.update({k: int(v) for k, v in (job.timeouts or {}).items() if k in out})
        return out

    def prepare(self, job):
        problems = []
        if not self.base_url(job):
            problems.append("the publication profile names no console url")
        if not job.package_path or not os.path.isfile(job.package_path):
            problems.append(f"the package {job.package.get('filename')} is not on disk")
        limit = (self.submission.get("constraints") or {}).get("upload_max_mb")
        size = job.package.get("size_mb")
        if limit is not None and isinstance(size, (int, float)) and size > limit:
            problems.append(f"{size} MB exceeds the console's {limit} MB upload limit")
        if job.storage_state is None and (self.submission.get("credential") or {}).get(
                "kind", "none") == "storage-state":
            problems.append("no captured session (storage state) for this run")
        return problems

    def metadata(self, job):
        """The listing fields, as strings, scrubbed - the console gets exactly these."""
        out = {}
        for field in self.metadata_fields:
            value = job.metadata.get(field)
            if isinstance(value, dict):  # descriptions keyed by locale: the first required
                value = next(iter(value.values()), "")
            if value:
                out[field] = redact.scrub_text(str(value))
        return out

    def flow(self, job):
        return {
            "console_url": self.console_url(job),
            "allowed_origins": self.allowed_origins(job),
            "storage_state": job.storage_state,
            "output_dir": os.path.join(job.scratch_dir, "frames"),
            "phases": list(PHASES),
            "submit": bool(job.submit),
            "key": job.idempotency_key,
            "package": job.package_path,
            "metadata": self.metadata(job),
            "selectors": {k: v for k, v in self.selectors().items() if v},
            "timeouts": self.timeouts(job),
        }

    def publish(self, job):
        problems = self.prepare(job)
        if problems:
            return Publication(outcomes.BLOCKED, f"{self.platform_id}: " + "; ".join(problems),
                               evidence=[Evidence("observation", p, phase="prepare")
                                         for p in problems],
                               measurement_class="automation-check")
        executor = BrowserExecutor(job.checkout, job.release_dir, job.env, job.hooks,
                                   run_process=job.run_process,
                                   timeout_s=self.timeouts(job)["upload"] // 1000 + 600)
        log = os.path.join(job.scratch_dir, "logs", "console.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        try:
            run = executor.execute(self.flow(job), log_path=log)
            return self._interpret(job, run)
        finally:
            executor.cleanup()

    # -- mapping the executor's result ----------------------------------------------------

    def _interpret(self, job, run):
        evidence = [Evidence.of_process("playwright console run", run.process, phase="run")]
        if run.refused:
            evidence.append(Evidence("observation",
                                     f"{len(run.refused)} request(s) to other origins refused "
                                     f"at the browser", phase="run",
                                     data={"refused": sorted(set(run.refused))[:20]}))
        if run.unavailable:
            return Publication(outcomes.BLOCKED,
                               f"{self.platform_id}: no browser to drive the console with here "
                               f"(playwright install chromium)", evidence=evidence,
                               measurement_class="automation-check")
        phases = run.phases
        draft_id = None
        found = False
        for name in PHASES:
            phase = phases.get(name)
            if phase is None:
                if name in ("submit", "verify") and not phases:
                    break
                continue
            for key in ("screenshot",):
                shot = phase.get(key)
                if shot and os.path.isfile(shot):
                    evidence.append(Evidence.screenshot(f"{name}: the console page", shot,
                                                        job.run_dir, phase=name))
            if phase.get("status_text"):
                evidence.append(Evidence.console_text(f"{name}: status text", phase["status_text"],
                                                      phase=name))
            if phase.get("url"):
                evidence.append(Evidence("observation", f"{name}: at {phase['url']}", phase=name))
            if phase.get("draft_id"):
                draft_id = str(phase["draft_id"])
            if phase.get("found"):
                found = True
            outcome = phase.get("outcome")
            if outcome in _STOPS:
                mapped, reason = _STOPS[outcome]
                detail = phase.get("detail") or outcome
                evidence.append(Evidence("observation", f"{name}: {outcome}: {detail}", phase=name))
                if mapped == outcomes.RETRYABLE_FAILURE and name in ("submit", "verify"):
                    # The submit may have landed: nothing retries it; a person looks.
                    mapped, reason = outcomes.UNKNOWN, "ambiguous-portal-state"
                return Publication(mapped, f"{self.platform_id}: {name}: {detail}",
                                   draft_id=draft_id, found_existing=found,
                                   evidence=evidence, human_reason=reason,
                                   resume_with="wgf decide <run-id> done|abandon"
                                   if mapped in outcomes.HUMAN else None)
        if not phases:
            tail = run.process.tail(8) if hasattr(run.process, "tail") else ""
            return Publication(outcomes.RETRYABLE_FAILURE,
                               f"{self.platform_id}: the console run produced no result "
                               f"({run.process.status}): {tail}", evidence=evidence)
        verify = phases.get("verify") or {}
        status_text = str(verify.get("status_text") or "").strip()
        submitted_phase = phases.get("submit") or {}
        clicked = submitted_phase.get("outcome") == "ok"
        observed = self._classify(status_text, self.submission.get("status") or {})
        verified_state = {"observed": status_text or "(no status text)", "at": utc_now(),
                          "source": f"console status text ({self.selectors().get('status_text')})",
                          **({"url": verify["url"]} if verify.get("url") else {})}
        if not job.submit:
            return Publication(outcomes.DRY_RUN,
                               f"{self.platform_id}: dry run: draft {draft_id or '(none)'} "
                               f"{'found' if found else 'prepared'}, status {status_text!r}; "
                               f"nothing submitted", draft_id=draft_id, found_existing=found,
                               verified_state=verified_state, evidence=evidence)
        if observed == "submitted" or observed == "live":
            state = "submitted" if observed == "submitted" else "live"
            return Publication(outcomes.VERIFIED,
                               f"{self.platform_id}: the console shows {status_text!r} for draft "
                               f"{draft_id or '?'}: {state}", state=state, draft_id=draft_id,
                               found_existing=found, verified_state=verified_state,
                               evidence=evidence, submitted=True)
        if observed == "rejected":
            return Publication(outcomes.REJECTED,
                               f"{self.platform_id}: the console shows {status_text!r}: rejected; "
                               f"a person records the compliance finding", state=None,
                               draft_id=draft_id, verified_state=verified_state,
                               evidence=evidence)
        if clicked:
            # Clicked, acknowledged, but the state read back is not one the profile knows.
            return Publication(outcomes.UNKNOWN,
                               f"{self.platform_id}: submit was clicked but the console shows "
                               f"{status_text!r}, which the publication profile does not map; "
                               f"a person reads the portal before anything else happens",
                               draft_id=draft_id, verified_state=verified_state,
                               evidence=evidence, human_reason="ambiguous-portal-state",
                               resume_with="wgf decide <run-id> done|abandon")
        return Publication(outcomes.PLATFORM_ERROR,
                           f"{self.platform_id}: nothing was submitted and the console shows "
                           f"{status_text!r}", draft_id=draft_id, verified_state=verified_state,
                           evidence=evidence)

    @staticmethod
    def _classify(status_text, status):
        text = status_text.casefold()
        for kind in ("rejected", "live", "submitted"):
            for word in status.get(f"{kind}_states") or []:
                if str(word).casefold() == text:
                    return kind
        return None
