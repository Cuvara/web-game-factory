"""The adapter for the fixture portal (scripts/tests/fixtures/publish/portal.py): the local
console every browser test publishes to, so no real portal is ever contacted by a test.

Two things only the fixture may do, both for tests:

  * its dry run creates and uploads to a draft (nothing ever submits it), so a dry run
    exercises the whole flow up to save_draft;
  * `factory.publish.platforms.<id>.test_headless: true` runs the browser headless, and
    `test_human` names a module the runner loads - headless only - as the test's stand-in
    for the person who logs in (as the observer tests do). Every real portal is headed and
    waits for a real person.
"""

from .console import ConsoleAdapter

__all__ = ["FixturePortalAdapter"]


class FixturePortalAdapter(ConsoleAdapter):
    dry_run_uploads = True

    def console_url(self, job):
        return self.base_url(job).rstrip("/") + "/console"

    def browser_mode(self, job):
        headless = bool(self.settings.get("test_headless"))
        return headless, (self.settings.get("test_human") if headless else None)
