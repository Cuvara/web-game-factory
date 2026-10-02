"""Yandex Games Console adapter - a selector map that is a HYPOTHESIS, like CrazyGames'.

Documented flow (yandex.com/dev/games/doc/en/console/update-game): open the game, open or
create the draft, upload the archive on the Draft tab, Submit for moderation; only one
moderation at a time; `Postpone publication` keeps a verified draft unpublished, which this
adapter sets so publication timing stays a person's. Unverified against the live console and
unreached until a person records the terms finding (publication profile, factory.publish).
"""

from .console import ConsoleAdapter

__all__ = ["YandexAdapter"]


class YandexAdapter(ConsoleAdapter):
    metadata_fields = ("title", "description")

    def selectors(self):
        base = (self.base_url(None) or "https://games.yandex.com/console/").rstrip("/")
        return {
            "logged_in": "[data-testid=console-games], .console__games",
            "login_form": "form[action*='passport'], input[name=login], input[type=password]",
            "captcha": ".captcha, iframe[src*='captcha'], [data-testid=smart-captcha]",
            "two_factor": "input[name*='otp'], input[autocomplete='one-time-code']",
            "drafts_url": f"{base}/games",
            "draft_row": "[data-testid=game-row], .game-row",
            "draft_id_attr": "data-app-id",
            "new_draft_url": f"{base}/games/new",
            "name_input": "input[name=title]",
            "file_input": "input[type=file]",
            "upload_button": "button[data-testid=upload-archive]",
            "upload_done": "[data-testid=archive-uploaded]",
            "upload_error": "[data-testid=archive-error], [role=alert]",
            "draft_id": "[data-testid=app-id]",
            "field_title": "input[name=title]",
            "field_description": "textarea[name=description]",
            "save_button": "button[data-testid=save-draft]",
            "saved": "[data-testid=draft-saved]",
            "submit_button": "button[data-testid=submit-for-moderation]",
            "submit_done": "[data-testid=draft-status]",
            "status_url": f"{base}/games/{{id}}/draft",
            "status_text": "[data-testid=draft-status]",
        }
