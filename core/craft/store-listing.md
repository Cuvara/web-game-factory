# Store listing: the thumbnail is the first onboarding step

Serves `store-listing` (its copy, screenshots and branding), `release-manifest.store_metadata`,
and each platform profile's `store_listing` block. Read with
[`onboarding-and-portal-ux.md`](onboarding-and-portal-ux.md), whose "Store presentation"
section this expands, and `core/lifecycle/stages/store-listing.md`, which is the procedure.

On a portal the listing *is* the acquisition funnel: a player sees a thumbnail among forty,
reads at most one line, and plays or scrolls on. Everything below optimises for one thing -
the player who clicks gets the game the thumbnail promised, and the player who would not
like it does not click. A thumbnail that over-promises lifts clicks and kills retention and
portal approval together.

## Defaults, with reasons

**Every claim is backed, mechanically.** `core/reference/store-listing.yaml` `claims` lists
the words that promise a capability and what in the run's artifacts must back each. The
check runs on every text, whoever wrote it. The default is to write *less*: a description
that says only what the game does is never wrong.

**The first sentence is the verb.** "Drop towers and merge equal levels before the track
fills" beats "An addictive puzzle experience". The verb comes from the design's
`core_loop` and the experience contract's `goal.statement`; the fantasy comes second, if at
all. Controls get one line per device the build accepts - every device
`build_spec.controls.actions` binds and every one the play probe reported while the listing
was captured: a desktop player with a mouse and keys reads a touch-only line as "not for
me".

**Counts are the build's.** "Six courses" is a promise; it is true only if the build ships
six. A number the copy states before a level, world, boss or mode word is the one the
content-sufficiency report measured on the listed build - never the design's plan, which
the build may have outgrown or fallen short of. Without a measured count, state none.
A feature the design's evaluation cut or deferred is never named.

**Screenshots are play, not menus.** The capture plan takes the title screen once and play
three times - early, after the player has acted, late - plus the result screen. Play frames
lead. A frame the readability floors reject (`visual-quality.yaml` `frames`) is a frame a
player cannot read either; a frame that repeats an earlier one adds nothing. Debug,
loading and error states never ship.

**The icon is one subject.** The player entity's asset (the runtime manifest's `player`
role, else an `icon` role asset) over the palette's ground token, readable at 150 px wide,
no text beyond the title. The wordmark is the title in the design's display face - the
same face the game sets its title in, which is what makes the listing and the game one
thing. Where no browser can compose, the icon is a crop of the best play frame, and the
listing says so (`branding.method: frame-derived`).

**The trailer is play, cut to play.** Oracle-driven play for about twenty seconds, from the
first frame of play. A recording that could not be trimmed keeps its leading seconds and
says how many (`trailer.leading_ms`); one that could not be made at all is a frame sequence
labelled `fallback`, never passed off as a video.

**Platform limits are data.** A text is cut to a platform's `max_chars` at a sentence or
word boundary, never mid-word, and never by inventing a shorter claim. An image is
downscaled and cover-cropped from a canonical master, never upscaled. A limit the profile
does not state is UNKNOWN: reported per platform, never guessed at. Reading a portal's form
and filling the profile block in - with the source and its date - is the one manual act
this phase asks for, and it is done once per portal, not once per game.

**Tags come from the vocabulary.** The research vocabulary's genre tree
(`research-vocabulary.yaml`) gives the genre and its ancestors; the design gives the derived
tags (single-player, casual, mobile, one-touch, 2D/3D, high-score). A platform with its own
category list maps these through `store_listing.categories.allowed`.

**Locales are deliverables.** A listing for a platform that requires `ru` carries its texts
in `ru`, or validation fails the platform. The texts a writer cannot produce in a locale are
a missing deliverable, not an English fallback. At a release, every required locale gets a
full description - title, short and long description, controls - written in it: the game's
one-line objective is not a description, and English words carried into a translation to
look grounded are not grounding (a translation is held to its source's numbers and ids).

**The subtitle names the game.** "Puzzle" or "A casual arcade game" says only the genre,
which the category already says: the subtitle says what this game is.

## Failure modes

- **A listing of another build.** Screenshots of a commit that is not the one shipped. The
  step refuses unless the build on disk hashes to the verified bundle.
- **Marketing adjectives.** "Addictive", "stunning", "best": unverifiable, and portals'
  editors read them as a tell. Describe; do not rate.
- **A capability from the SDK that is not in the game.** A platform offers leaderboards;
  the game never calls them. The claim check reads the `sdk-report`, not the profile.
- **Treating UNKNOWN as PASS.** The validation report lists unknowns per platform so that
  a person can read them. A publishing step that ignores them learns the requirement from
  the rejection.
