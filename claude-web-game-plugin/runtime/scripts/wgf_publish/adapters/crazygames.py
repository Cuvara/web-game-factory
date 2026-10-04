"""CrazyGames developer portal adapter - a selector map that is a HYPOTHESIS.

Nobody has run this against developer.crazygames.com: the publication profile says
`status: unverified` and `automation_terms: unverified`, so the publish step stops
HUMAN_REQUIRED before this adapter is reached. When a person has established that the
portal's terms permit automated console use and recorded it (factory.publish.platforms.
crazygames.terms_confirmed), the first live runs are made with factory.publish.mode dry-run,
the selectors corrected from the console as it is, and the profile bumped to `verified`.
"""

from .console import ConsoleAdapter

__all__ = ["CrazyGamesAdapter"]


class CrazyGamesAdapter(ConsoleAdapter):
    def selectors(self):
        base = (self.base_url(None) or "https://developer.crazygames.com/").rstrip("/")
        return {
            "logged_in": "[data-testid=developer-dashboard], nav a[href*='/games']",
            "login_form": "form[action*='login'], input[type=password]",
            "captcha": "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], .g-recaptcha",
            "two_factor": "input[name*='otp'], input[autocomplete='one-time-code']",
            "drafts_url": f"{base}/games",
            "draft_row": "[data-testid=game-row], tr[data-game-id]",
            "draft_id_attr": "data-game-id",
            "new_draft_url": f"{base}/games/new",
            "name_input": "input[name=name], input[name=title]",
            "file_input": "input[type=file]",
            "upload_button": "button[type=submit]",
            "upload_done": "[data-testid=upload-complete], .upload-complete",
            "upload_error": "[role=alert], .upload-error",
            "draft_id": "[data-testid=game-id]",
            "field_title": "input[name=title]",
            "field_description": "textarea[name=description]",
            "save_button": "button[data-testid=save]",
            "saved": "[data-testid=saved]",
            "submit_button": "button[data-testid=submit-for-review]",
            "submit_done": "[data-testid=review-status]",
            "status_url": f"{base}/games/{{id}}",
            "status_text": "[data-testid=review-status]",
        }
