"""The adapter for the fixture portal (scripts/tests/fixtures/publish/portal.py): the local
console every browser test publishes to, so no real portal is ever contacted by a test."""

from .console import ConsoleAdapter

__all__ = ["FixturePortalAdapter"]


class FixturePortalAdapter(ConsoleAdapter):
    def console_url(self, job):
        return self.base_url(job).rstrip("/") + "/console"

    def selectors(self):
        base = (self.base_url(None) or "").rstrip("/")
        return {
            "logged_in": "#dashboard",
            "login_form": "form#login",
            "captcha": "#captcha",
            "two_factor": "#two-factor",
            "drafts_url": base + "/console",
            "draft_row": "tr.draft",
            "draft_id_attr": "data-id",
            "new_draft_url": base + "/console/new",
            "name_input": "input[name=name]",
            "file_input": "input[type=file]",
            "upload_button": "button#upload",
            "upload_done": "#draft-id",
            "upload_error": "#upload-error",
            "draft_id": "#draft-id",
            "field_title": "input[name=title]",
            "field_short_description": 'textarea[name="short_description[{locale}]"]',
            "field_description": 'textarea[name="description[{locale}]"]',
            "field_controls": "textarea[name=controls]",
            "field_tags": "input[name=tags]",
            "field_categories": "input[name=categories]",
            "save_button": "button#save",
            "saved": "#saved",
            "submit_button": "button#submit",
            "submit_done": "#status",
            "status_url": base + "/console/draft/{id}",
            "status_text": "#status",
        }
