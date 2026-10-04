"""Platform publication adapters: where everything platform-specific lives.

    resolve(platform_id, profile, settings) -> PublicationAdapter

An adapter turns one release package plus one publication profile
(core/reference/publication/<id>.yaml) into one publication attempt, and maps whatever the
portal did into the common outcome vocabulary (wgf_publish.outcomes). The pipeline calls
`adapter.publish(job)` and reads a `Publication`; it never sees a selector, a URL or a
portal's own status word.

Methods, preferred in this order (the profile's `submission.method`):

    api / cli    the portal's own documented tool. No shipped profile documents an upload
                 API and no adapter drives a CLI yet, so these stop HUMAN_REQUIRED with the
                 packaged release for a person to run the tool with.
    console      the profile's console flow, run by the intent runner (ConsoleAdapter; no
                 selector lives in code). A person logs in, live, in the headed window it
                 opens. Allowed only when the profile says the portal permits automated use
                 of its console, or a person recorded that finding in
                 factory.publish.platforms.<id>.terms_confirmed.
    email        a person sends the package (ManualAdapter, reason manual-submission).
    manual       nothing to submit (generic-web), or a portal nobody automates.

`settings.adapter` (factory.publish.platforms.<id>.adapter) names another adapter for a
platform - how a test points a platform at the fixture portal; otherwise the platform id is
the adapter id, a console platform with no adapter of its own runs on ConsoleAdapter when its
profile has a flow, and one without a flow is HUMAN_REQUIRED.
"""

from .base import Job, ManualAdapter, Publication, PublicationAdapter
from .console import ConsoleAdapter
from .crazygames import CrazyGamesAdapter
from .fixture import FixturePortalAdapter
from .yandex import YandexAdapter

__all__ = ["resolve", "REGISTRY", "Job", "Publication", "PublicationAdapter", "ManualAdapter",
           "ConsoleAdapter"]

REGISTRY = {
    "fixture-portal": FixturePortalAdapter,
    "crazygames": CrazyGamesAdapter,
    "yandex": YandexAdapter,
}


def resolve(platform_id, profile, settings=None):
    """The adapter for `platform_id` under its publication `profile` and the installation's
    `settings` (factory.publish.platforms.<id>). Never raises: a platform nothing drives
    gets ManualAdapter, which stops HUMAN_REQUIRED and says why."""
    settings = settings or {}
    method = ((profile or {}).get("submission") or {}).get("method")
    name = settings.get("adapter") or platform_id
    adapter = REGISTRY.get(name)
    if method == "console" and adapter is not None and issubclass(adapter, ConsoleAdapter):
        return adapter(platform_id, profile, settings)
    if method == "console" and adapter is None and ((profile or {}).get("submission") or {}).get("flow"):
        return ConsoleAdapter(platform_id, profile, settings)
    manual = ManualAdapter(platform_id, profile, settings)
    manual.method = method or "manual"
    return manual
