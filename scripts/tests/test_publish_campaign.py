"""The campaign package: every portal field and medium from the shipped store listing, and
the per-portal media check run before anything is uploaded (wgf_publish.campaign)."""

import copy
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from campaign_fixture import (PACKAGE_DIR, png_bytes, placeholder_png,  # noqa: E402
                              write_campaign)
from wgf_publish import campaign  # noqa: E402
from wgf_publish import common  # noqa: E402
from wgf_publish.adapters import ConsoleAdapter, Job  # noqa: E402
from wgf_publish.adapters.console import resolve_value  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

PROFILE = os.path.join(HERE, "fixtures", "publish", "publication", "generic-web.yaml")
TEXT = {
    "en": {"title": "Fixture Game", "short_description": "Merge towers.",
           "long_description": "Merge matching towers to build stronger ones.",
           "controls": "Drag to merge.", "tags": ["merge", "casual"], "categories": ["Puzzle"],
           "features": [{"text": "Twelve courses", "source": "content"},
                        {"text": "One-touch play", "source": "controls"}],
           "subtitle": "Merge and hold", "promo": ["Merge now"]},
    "ru": {"title": "Фикстура", "short_description": "Объединяй башни.",
           "long_description": "Объединяй одинаковые башни, строй сильнее.",
           "controls": "Перетащи.", "tags": ["слияние"], "categories": ["Головоломки"],
           "features": [{"text": "Двенадцать трасс", "source": "content"}],
           "age_rating": "12+"},
}


class CampaignCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wgf-campaign-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.release_dir = os.path.join(self.tmp, "release", "r1")
        os.makedirs(self.release_dir)

    def ship(self, **kw):
        listing = os.path.join(self.release_dir, "listing")
        if os.path.isdir(listing):
            shutil.rmtree(listing)
        kw.setdefault("text", TEXT)
        write_campaign(self.release_dir, "generic-web", **kw)
        return campaign.load(self.release_dir, "generic-web")

    def video(self, seconds=10.0, width=160, height=90, fmt="webm"):
        from test_listing import make_mp4, make_webm
        path = os.path.join(self.tmp, f"v.{fmt}")
        (make_webm if fmt == "webm" else make_mp4)(path, duration_s=seconds, width=width,
                                                   height=height)
        with open(path, "rb") as handle:
            return handle.read(), fmt, width, height, seconds

    def codes(self, findings, status="FAIL"):
        return sorted({f["code"] for f in findings if f["status"] == status})


class Mapping(CampaignCase):
    def test_every_field_in_two_locales(self):
        shipped = self.ship()
        for locale, copy_ in TEXT.items():
            for field, expected in (("title", copy_["title"]),
                                    ("short_description", copy_["short_description"]),
                                    ("long_description", copy_["long_description"]),
                                    ("description", copy_["long_description"]),
                                    ("how_to_play", copy_["controls"]),
                                    ("instructions", copy_["controls"]),
                                    ("controls", copy_["controls"]),
                                    ("tags", ", ".join(copy_["tags"])),
                                    ("categories", ", ".join(copy_["categories"])),
                                    ("feature_bullets", "\n".join(f["text"] for f in copy_["features"]))):
                with self.subTest(locale=locale, field=field):
                    self.assertEqual(campaign.resolve(shipped, f"listing.text.{locale}.{field}"),
                                     ("text", expected))
        self.assertEqual(campaign.resolve(shipped, "listing.text.en.subtitle"), ("text", "Merge and hold"))
        self.assertEqual(campaign.resolve(shipped, "listing.text.en.promo"), ("text", "Merge now"))
        # Only where the copy has them; never derived from something else.
        self.assertEqual(campaign.resolve(shipped, "listing.text.en.keywords"), (None, None))
        self.assertEqual(campaign.resolve(shipped, "listing.text.en.seo_description"), (None, None))
        self.assertEqual(campaign.resolve(shipped, "listing.text.fr.title"), (None, None))
        # The short form: the primary locale, then any other.
        self.assertEqual(campaign.resolve(shipped, "listing.title", primary="ru"), ("text", "Фикстура"))
        self.assertEqual(campaign.resolve(shipped, "listing.subtitle", primary="ru"),
                         ("text", "Merge and hold"))

    def test_the_age_rating_is_surfaced_never_filled(self):
        shipped = self.ship(age_rating="12+")
        self.assertEqual(campaign.resolve(shipped, "listing.text.ru.age_rating"), (None, None))
        self.assertEqual(campaign.surfaced(shipped), {"age_rating": "12+"})

    def test_every_medium_and_the_rendition_before_the_canonical(self):
        shipped = self.ship(trailer=self.video())
        base = os.path.join(self.release_dir, "listing")
        rendition = os.path.join(base, "platforms", "generic-web")
        kind, files = campaign.resolve(shipped, "listing.media.icon")
        self.assertEqual(files, [os.path.join(rendition, "icon.png")])
        for name in ("cover", "thumbnail", "hero", "hero_image"):
            self.assertEqual(campaign.resolve(shipped, f"listing.media.{name}")[1],
                             [os.path.join(rendition, "cover.png")], name)
        self.assertEqual(campaign.resolve(shipped, "listing.media.screenshots")[1],
                         [os.path.join(rendition, "shot-1.png"), os.path.join(rendition, "shot-2.png")])
        for name in ("trailer", "video", "gameplay_video", "trailer_landscape", "horizontal_video"):
            self.assertEqual(campaign.resolve(shipped, f"listing.media.{name}")[1],
                             [os.path.join(rendition, "trailer.webm")], name)
        self.assertEqual(campaign.resolve(shipped, "listing.media.vertical_video"), (None, None))
        self.assertEqual(campaign.resolve(shipped, "listing.media.logo"), (None, None))
        # No rendition icon: the canonical one, never invented.
        shipped = self.ship(icon=False)
        self.assertEqual(campaign.resolve(shipped, "listing.media.icon")[1],
                         [os.path.join(base, "branding", "icon-512x512.png")])
        shipped = self.ship(icon=False, canonical_extra={"branding": {"method": "none", "items": []}})
        self.assertEqual(campaign.resolve(shipped, "listing.media.icon"), (None, None))

    def test_a_platform_image_requirement_names_its_own_rendition(self):
        # CrazyGames asks for three covers (16:9, 2:3, 1:1): each intent names one by the
        # platform block's image id, never the kind (which would hand all three to one input).
        from campaign_fixture import png_bytes
        extra = [(dict(id="cover-2x3", rel="platforms/generic-web/cover-2x3.png", format="png",
                       width=80, height=120, kind="thumbnail", source="thumbnail",
                       requirement="cover-2x3"), png_bytes(80, 120, seed=7))]
        shipped = self.ship(rendition_extra=extra)
        rendition = os.path.join(self.release_dir, "listing", "platforms", "generic-web")
        self.assertEqual(campaign.resolve(shipped, "listing.media.cover-2x3")[1],
                         [os.path.join(rendition, "cover-2x3.png")])
        self.assertEqual(campaign.resolve(shipped, "listing.media.cover-1")[1],
                         [os.path.join(rendition, "cover.png")])
        self.assertEqual(len(campaign.resolve(shipped, "listing.media.cover")[1]), 2)

    def test_a_locales_own_media_else_the_shared(self):
        own = png_bytes(64, 36, seed=90)
        shipped = self.ship(rendition_extra=[({"id": "shot-ru", "kind": "screenshot",
                                               "rel": "platforms/generic-web/shot-ru.png",
                                               "source": "landscape-01-play", "locale": "ru",
                                               "requirement": "screenshots"}, own)])
        ru = campaign.resolve(shipped, "listing.media.ru.screenshots")[1]
        self.assertEqual([os.path.basename(p) for p in ru], ["shot-ru.png"])
        en = campaign.resolve(shipped, "listing.media.screenshots", locale="en")[1]
        self.assertEqual([os.path.basename(p) for p in en], ["shot-1.png", "shot-2.png"])

    def test_the_console_resolves_through_the_campaign(self):
        self.ship()
        job = self.job()
        self.assertEqual(resolve_value("listing.text.<locale>.description", job, "ru"),
                         ("text", TEXT["ru"]["long_description"]))
        self.assertEqual(resolve_value("listing.media.screenshots", job)[0], "files")
        self.assertEqual(resolve_value("listing.media.trailer", job), (None, None))

    def test_missing_optional_is_left_out_missing_required_is_a_problem(self):
        self.ship(cover=False)
        adapter = ConsoleAdapter("generic-web", load_file(PROFILE))
        intents, problems, unfilled = adapter.intents(self.job())
        self.assertEqual(problems, [])
        self.assertEqual(unfilled, ["media.cover"])
        self.ship(icon=False, canonical_extra={"branding": {"method": "none", "items": []}})
        _, problems, _ = adapter.intents(self.job())
        self.assertEqual(problems, ["intent media.icon: the job holds no listing.media.icon"])

    def job(self):
        package = os.path.join(self.release_dir, "generic-web.zip")
        with open(package, "wb") as handle:
            handle.write(b"PK\x05\x06" + b"\0" * 18)
        return Job(platform_id="generic-web", release_id="r1", idempotency_key="k",
                   package_path=package, package={"filename": "generic-web.zip"}, metadata={},
                   checkout=self.tmp, release_dir=self.release_dir, run_dir=self.tmp,
                   scratch_dir=self.tmp, submit=False, env={}, hooks={},
                   listing=common.listing_text(self.tmp, "r1", "generic-web"),
                   platform_profile={"store_listing": {"locales": ["en"]}})


class Hash(CampaignCase):
    def test_stable_and_changes_with_text_or_bytes(self):
        first = self.ship().campaign_hash()
        self.assertEqual(self.ship().campaign_hash(), first)
        self.assertTrue(first.startswith("sha256:"))
        text = copy.deepcopy(TEXT)
        text["ru"]["long_description"] += " Ещё."
        self.assertNotEqual(self.ship(text=text).campaign_hash(), first)
        self.ship()
        with open(os.path.join(self.release_dir, "listing", "platforms", "generic-web", "cover.png"),
                  "wb") as handle:
            handle.write(png_bytes(32, 18, seed=99))
        self.assertNotEqual(campaign.load(self.release_dir, "generic-web").campaign_hash(), first)
        self.assertNotEqual(self.ship(listing_hash="sha256:" + "e" * 64).campaign_hash(), first)


class MediaCheck(CampaignCase):
    """Per portal, before any upload. A null limit is UNKNOWN, never passed."""

    def check(self, shipped, block=None, publication=None, **kw):
        profile = {"store_listing": dict({"status": "verified"}, **(block or {}))} \
            if block is not None else None
        return campaign.check_media(shipped, profile, publication, **kw)

    def test_a_clean_campaign_passes(self):
        findings = self.check(self.ship(), {"screenshots": {"min": 1, "max": 4, "sizes": [{"width": 64, "height": 36}],
                                                            "formats": ["png"], "max_kb": 100}})
        self.assertEqual(self.codes(findings), [])

    def test_images_too_small_wrong_aspect_too_big_wrong_type(self):
        shipped = self.ship()
        block = {"icon": {"id": "icon", "required": True, "sizes": [{"width": 512, "height": 512}],
                          "formats": ["jpg"], "max_kb": 1},
                 "covers": [{"id": "cover-1", "required": True, "aspect": "1:1"}]}
        # The fixture's icon is 16x16 png, about 1 KB: too small, the wrong type.
        self.assertEqual(self.codes(self.check(shipped, block)),
                         ["media-aspect", "media-format", "media-size"])
        block["icon"] = {"id": "icon", "required": True, "max_kb": 1}
        big = png_bytes(200, 200, seed=3)
        shipped = self.ship(icon=False, rendition_extra=[({"id": "icon-big", "kind": "icon",
                                                           "rel": "platforms/generic-web/icon-big.png",
                                                           "requirement": "icon"}, big)])
        self.assertIn("media-too-large", self.codes(self.check(shipped, block)))

    def test_too_many_and_too_few(self):
        shipped = self.ship(shots=3)
        self.assertEqual(self.codes(self.check(shipped, {"screenshots": {"max": 2}})), ["media-count"])
        self.assertEqual(self.codes(self.check(shipped, {"screenshots": {"min": 5}})), ["media-count"])
        publication = {"submission": {"flow": [{"id": "media.shot", "action": "upload",
                                                "value": "listing.media.screenshots"}]}}
        findings = self.check(shipped, None, publication)
        self.assertEqual(self.codes(findings), ["media-count"])  # one input, three files
        publication["submission"]["flow"][0]["multiple"] = True
        self.assertEqual(self.codes(self.check(shipped, None, publication)), [])

    def test_the_publication_profiles_accept_and_formats(self):
        shipped = self.ship()
        publication = {"submission": {"flow": [{"id": "media.icon", "action": "upload",
                                                "value": "listing.media.icon", "accept": ["jpg", "webp"]}],
                                      "fields": {"icon": {"required": True, "formats": ["png"]}}}}
        self.assertEqual(self.codes(self.check(shipped, None, publication)), ["media-format"])
        publication["submission"]["flow"][0]["accept"] = ["image/png"]
        self.assertEqual(self.codes(self.check(shipped, None, publication)), [])
        # A required field the campaign has nothing for.
        publication = {"submission": {"fields": {"logo": {"required": True}}}}
        self.assertEqual(self.codes(self.check(shipped, None, publication)), ["media-missing"])

    def test_per_locale_media(self):
        publication = {"submission": {"fields": {"screenshots": {"required": True, "locales": "per-locale"}}}}
        en_only = png_bytes(64, 36, seed=91)
        shipped = self.ship(shots=0, rendition_extra=[({"id": "shot-en", "kind": "screenshot",
                                                        "rel": "platforms/generic-web/shot-en.png",
                                                        "source": "landscape-01-play", "locale": "en",
                                                        "requirement": "screenshots"}, en_only)])
        findings = self.check(shipped, None, publication, locales=["en", "ru"])
        missing = [f for f in findings if f["code"] == "media-locale-missing"]
        self.assertEqual([f["subject"] for f in missing], ["screenshots:ru"])
        # Shared files serve every locale: reported, not verified, not refused.
        findings = self.check(self.ship(), None, publication, locales=["en", "ru"])
        self.assertEqual(self.codes(findings), [])
        self.assertIn("media-locale-shared", self.codes(findings, "UNKNOWN"))

    def test_video_too_long_wrong_orientation_wrong_container(self):
        shipped = self.ship(trailer=self.video(seconds=40.0, width=160, height=90))
        block = {"video": {"required": True, "formats": ["webm"], "max_seconds": 28,
                           "orientation": ["portrait"]}}
        self.assertEqual(self.codes(self.check(shipped, block)), ["video-duration", "video-orientation"])
        block = {"video": {"required": True, "formats": ["mp4"], "max_seconds": 60}}
        self.assertEqual(self.codes(self.check(shipped, block)), ["media-format"])
        self.assertEqual(self.codes(self.check(self.ship(), {"video": {"required": True}})),
                         ["media-missing"])

    def test_null_limits_are_unknown_never_passed(self):
        shipped = self.ship(trailer=self.video())
        block = {"icon": {"id": "icon", "required": True, "sizes": None, "formats": None},
                 "screenshots": {"min": None}, "video": {"required": False, "max_seconds": None}}
        findings = self.check(shipped, block)
        self.assertEqual(self.codes(findings), [])
        unknown = [f["subject"] for f in findings if f["status"] == "UNKNOWN"]
        self.assertIn("icon", unknown)
        self.assertIn("screenshots", unknown)
        self.assertIn("trailer", unknown)
        findings = self.check(shipped, None, {"submission": {"fields": {
            "trailer": {"required": None, "size": "16:9, up to 28 s, 100 MB"}}}})
        self.assertTrue(any("not checked mechanically" in f["message"] for f in findings
                            if f["status"] == "UNKNOWN"))

    def test_a_placeholder_is_refused(self):
        flat = placeholder_png(64, 36)
        shipped = self.ship(rendition_extra=[({"id": "screenshot-09", "kind": "screenshot",
                                               "rel": "platforms/generic-web/shot-9.png",
                                               "source": "landscape-01-play",
                                               "requirement": "screenshots"}, flat)])
        findings = self.check(shipped, {"screenshots": {"min": 1}})
        self.assertEqual([f["subject"] for f in findings if f["code"] == "placeholder"], ["screenshot-09"])
        # By name, whatever the pixels.
        named = self.ship(rendition_extra=[({"id": "hero", "kind": "promo",
                                             "rel": "platforms/generic-web/hero.placeholder.png"},
                                            png_bytes(40, 20, seed=4))])
        findings = self.check(named, None, {"submission": {"fields": {"hero": {"required": True}}}})
        self.assertIn("placeholder", self.codes(findings))

    def test_capture_provenance(self):
        shipped = self.ship()
        commit = "a" * 40
        self.assertEqual(self.codes(self.check(shipped, {}, shipped_commit=commit)), [])
        self.assertEqual(self.codes(self.check(shipped, {}, shipped_commit="b" * 40)),
                         ["capture-commit-mismatch"])
        # A screenshot whose source is no capture record, or whose capture file changed.
        stray = self.ship(rendition_extra=[({"id": "screenshot-07", "kind": "screenshot",
                                             "rel": "platforms/generic-web/shot-7.png",
                                             "source": "from-the-web", "requirement": "screenshots"},
                                            png_bytes(64, 36, seed=70))])
        findings = self.check(stray, {})
        self.assertEqual([f["subject"] for f in findings if f["code"] == "no-provenance"], ["screenshot-07"])
        shipped = self.ship()
        with open(os.path.join(self.release_dir, "listing", "screenshots", "landscape-01-play.png"), "wb") as h:
            h.write(png_bytes(128, 72, seed=60))
        self.assertEqual(self.codes(self.check(shipped, {})), ["no-provenance"])
        # No capture record at all, a zero commit, a capture that was not the bot's.
        for extra in ({"commit": "0" * 40}, {"capture": {"kind": "none"}},
                      {"measurement_class": "human"}):
            with self.subTest(extra=extra):
                self.assertEqual(self.codes(self.check(self.ship(canonical_extra=extra), {})),
                                 ["no-provenance"])
        os.remove(os.path.join(self.release_dir, "listing", "listing.json"))
        self.assertEqual(self.codes(self.check(campaign.load(self.release_dir, "generic-web"), {})),
                         ["no-provenance"])

    def test_a_changed_rendition_file_is_refused(self):
        shipped = self.ship()
        with open(os.path.join(self.release_dir, "listing", "platforms", "generic-web", "shot-1.png"), "ab") as h:
            h.write(b"tamper")
        self.assertIn("media-changed", self.codes(self.check(shipped, {})))


class DescriptionPropagation(CampaignCase):
    """listing -> release (store_metadata) -> job -> console field, per locale."""

    def test_every_locales_description_reaches_the_manifest_and_the_portal_field(self):
        from wgf_listing import package as listing_package
        from wgf_listing import platforms as listing_platforms
        from wgf_release.step import ReleaseStep
        run_dir = os.path.join(self.tmp, "run")
        package_dir = os.path.join(run_dir, *PACKAGE_DIR.split("/"))
        # The store-listing step's rendition for a platform that requires only en: ru, which
        # the copy has, is carried too.
        profile = {"store_listing": {"status": "verified", "title": {"required": True},
                                     "locales": ["en"]}}
        reqs = listing_platforms.requirements(profile, {})
        entry, _ = listing_package.render_platform(
            {"platform_id": "generic-web"}, reqs, canonical={"masters": [], "screenshots": []},
            copies=copy.deepcopy(TEXT), out_dir=os.path.join(package_dir, "platforms", "generic-web"),
            run_dir=run_dir, reference={})
        self.assertEqual(sorted(entry["text"]), ["en", "ru"])
        listing = {"provenance": {"artifact_id": "store-listing-x", "content_hash": "sha256:" + "c" * 64},
                   "package_dir": PACKAGE_DIR, "platforms": [entry], "status": "complete",
                   "trailer": {"status": "none"}, "branding": {"method": "none"}, "screenshots": []}
        listing_package.write_json(os.path.join(package_dir, "platforms", "generic-web", "listing.json"),
                                   {k: v for k, v in entry.items() if k != "listing"})

        class Ref:
            content_hash = "sha256:" + "c" * 64

        class Inputs:
            refs = {"store-listing": Ref()}

        class Context:
            pass

        context = Context()
        context.run_dir = run_dir
        checkout = os.path.join(self.tmp, "game")
        store_metadata, _ = ReleaseStep.__new__(ReleaseStep)._ship_listing(checkout, "r1", {"store-listing": listing},
                                                        Inputs(), context)
        self.assertEqual(store_metadata["generic-web"]["descriptions"],
                         {"en": TEXT["en"]["long_description"], "ru": TEXT["ru"]["long_description"]})
        release_dir = common.release_dir(checkout, "r1")
        package = os.path.join(release_dir, "generic-web.zip")
        with open(package, "wb") as handle:
            handle.write(b"PK\x05\x06" + b"\0" * 18)
        job = Job(platform_id="generic-web", release_id="r1", idempotency_key="k", package_path=package,
                  package={"filename": "generic-web.zip"}, metadata=store_metadata["generic-web"],
                  checkout=checkout, release_dir=release_dir, run_dir=run_dir, scratch_dir=run_dir,
                  submit=False, env={}, hooks={}, listing=common.listing_text(checkout, "r1", "generic-web"),
                  platform_profile=profile)
        profile_ = load_file(PROFILE)
        profile_["submission"]["flow"] = [i for i in profile_["submission"]["flow"]
                                          if not str(i.get("value") or "").startswith("listing.media")]
        intents, problems, _ = ConsoleAdapter("generic-web", profile_).intents(job)
        self.assertEqual(problems, [])
        fills = {i["locale"]: i["value"] for i in intents if i["id"] == "field.description"}
        self.assertEqual(fills, {"en": TEXT["en"]["long_description"],
                                 "ru": TEXT["ru"]["long_description"]})


if __name__ == "__main__":
    unittest.main()
