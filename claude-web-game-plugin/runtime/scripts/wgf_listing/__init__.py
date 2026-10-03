"""The store listing module: a verified build's store package, and its validation.

Registers two step types. Declared in workspace/config/factory.yaml:

    factory:
      steps:
        modules: [wgf_listing]

`store-listing` (release:store-listing) serves the verified bundle locally, plays it through
its play probe in a headless browser on a landscape and a portrait viewport, and writes the
canonical package: screenshots of real play, a gameplay recording, branding composed from
the game's own assets, palette and faces, store copy grounded in the design and the shipped
build, and one rendition per targeted platform under its profile's `store_listing` block
(core/reference/store-listing.yaml). `listing-validation` judges that package: every
required text and file present and within its limits, screenshots real and distinct, the
trailer within bounds or an honest fallback, no unbacked claim, every platform rendition
against its block - unknown requirements reported UNKNOWN, never passed. A failure that the
step can act on routes back to it (`listing`); one only a person can fix blocks.

See step.py, validation.py and docs/store-listing-module.md.
"""

from .step import StoreListingStep
from .validation import ListingValidationStep

__all__ = ["StoreListingStep", "ListingValidationStep", "register"]


def register(registry):
    registry.register(StoreListingStep.type, StoreListingStep)
    registry.register(ListingValidationStep.type, ListingValidationStep)
    return registry
