# Game audio

**Serves** `audio_direction`, `build_spec.audio`, the asset manifest's `sfx`/`music` items,
the `sfx`/`music` kinds in `core/reference/asset-policy.yaml`, the `audio` bars in
`core/reference/asset-quality.yaml`, and the production check `audio.plays`
(`core/reference/production-quality.yaml`).

Many portal players have sound off, and the rest have it on in public. Sound has to be
optional, and worth turning on: it is half of `game-feel.md`'s feedback bar. "Bland and
basic" is the usual verdict on a first build, and it almost always means one of three
things: there is no music at all, the cues are single tones, or everything sits at one level
so nothing reads as important.

## Browser and portal rules (non-negotiable)

- **Nothing sounds before the first user gesture.** Browsers block audio until the player
  interacts; portals reject games that try. Create the audio context early (suspended),
  load and decode in the background, and resume it on the first tap or key. Never try to
  autoplay music on load.
- **The platform outranks the game.** A portal mute setting, an ad break, a hidden tab and
  a window blur all silence the game, and it resumes exactly where it was. The template's
  platform binding (`onAudioMutedChange`) reports all of them in one signal; follow it.
- **A sound toggle is visible on every screen**, the player's choice persists, and it sits
  beside the platform's say, never instead of it.
- **Pause is silence.** Ramp the master gain to zero over ~60 ms (no click), then suspend
  the context so music resumes from the same bar.
- **Ads: stop, not duck.** During an interstitial or rewarded ad the game is silent; a
  rewarded grant can play its reward cue after the ad closes.
- **Measure, don't declare.** Put an `AnalyserNode` after every gain (mute, pause, ducking)
  and report its RMS as the play probe's `audio.level` - the production gate hears the game
  through it, and a muted game must read about zero.

## Music: arrangement, not a loop of beeps

A game's music is a produced piece, short enough to ship, long enough not to grate.

- **Length.** At least 60 s for the main loop (30 s for a title or menu variant). Under
  30 s it repeats audibly inside a first session.
- **Seamless.** Render the piece twice and keep the second pass, so its start carries the
  reverb and delay tails its own end leads into; cut on a bar line at an exact sample count
  (pick a tempo whose bar is a whole number of samples - 120 BPM at 48 kHz, 112.5 BPM at
  48 kHz). A lossy file needs a gapless container: Ogg Opus with a pre-skip covering its
  pre-roll and an end trim on the last page, or MP3 with a LAME/Info gapless record.
- **Layers.** Drums (a synthesized or sampled kick, snare or clap, hats, a shaker or
  percussion), bass, harmony (pads, piano, chords), and a lead or arpeggio on top - with
  sections that change which layers play (groove, verse, chorus, bridge) so the loop has a
  shape. A real chord progression (I-vi-ii-V, i-VI-III-VII, a IV-iv turn), not one chord.
- **Groove.** Swing the off-beat sixteenths 10-20 % for a playful feel; keep them straight
  for driving genres. Fills and a riser into the loop point hide the seam.
- **Mix inside the track.** Sidechain-style ducking of bass and harmony on the kick, one
  shared reverb, a tempo-synced delay on leads and arpeggios, then a mastering chain: low
  cut, a gentle low shelf cut and high shelf lift, a glue compressor, a limiter. Level the
  file to about -16 dBFS RMS with peaks under -1 dBFS.
- **Check the balance with numbers when you cannot listen.** Band energy should fall from
  bass to air: roughly presence 8-12 dB under bass, highs 15-20 dB under, air 25-30 dB
  under. A track whose highs sit 25 dB under its bass sounds muffled; bass far above the
  rest sounds muddy on phones that cannot reproduce it anyway.

### Palette per genre

| Genre / identity | Tempo, feel | Palette |
|---|---|---|
| Bright, playful puzzle (riso, cartoon) | 110-125 BPM, swung | Punchy kick and clap, shaker, plucked round bass, electric piano or ukulele comping, marimba or glockenspiel riff, whistle or pulse lead; major key |
| Synthwave, neon, racing | 100-118 BPM, straight | Four-on-the-floor kick, gated-reverb snare, sixteenth hats, pumping octave saw bass, wide detuned saw pads, ping-pong square arpeggio, saw lead with glide; minor key |
| Chiptune, retro arcade | 130-160 BPM | Pulse and triangle voices, noise drums, fast arpeggios for chords |
| Casual, cozy, idle | 80-100 BPM | Soft pads, felt piano, light percussion or none, long reverb |
| Action, arena | 130-150 BPM | Driving drums, distorted bass, staccato strings or synth stabs, risers |

### Adaptive music

Let the music follow the game without changing tracks:

- **Stems in lock-step.** Ship the loop as a base and an intensity layer of identical length,
  start both at the same `AudioContext` time, and fade the layer with the game's intensity
  (speed, combo, danger), smoothed over half a second.
- **Filter opening.** A low-pass on the base that opens from ~3.5 kHz to fully open as the
  intensity rises. Do not start below ~2 kHz: the opening seconds then sound broken.
- **Crossfade between states** (title -> play -> result) over 0.8-3 s; a slow fade under a
  result card, a quick one into play.

## Sound effects: designed, not tones

A pure sine beep does not meet the feedback bar. A designed cue has a transient, a body and a
tail, and most good cues are layers:

- **Impacts and drops:** a recorded knock or thud (library), a synthesized sub thump (a sine
  falling 140 -> 50 Hz in ~0.1 s), a short noise click.
- **Pops and merges:** a pitch sweep up into a tuned note, its octave, a mallet sparkle. Tune
  it to the music's key and pitch it up the scale per level or combo step - the player hears
  progress.
- **Stingers** (combo, reward, new best, game over): short phrases in the music's key, so
  they sit on top of a ducked music bed. Rising for success, falling for failure, never the
  same cue for both.
- **Whooshes:** band-passed noise sweeping up and back down; a near miss adds a falling
  "zing". Pan by the side it passed.
- **Engines and hums:** a seamless loop whose partials complete whole cycles in the loop
  (frequencies that are multiples of 1/length), re-pitched with speed (`playbackRate`),
  low-passed and panned with steering.
- **UI:** two quiet clicks (confirm, back), a few milliseconds of transient, nothing
  musical enough to compete with stingers.

### Feedback cues and their timing

| Event | Cue | Timing |
|---|---|---|
| Core verb (tap, drop, jump) | Short, soft, varied | Within one frame of the input; it plays most often, so ±5-10 % pitch variation and a voice limit |
| Success / collect / merge | Bright, rising, tuned | 30-80 ms after the verb, so the verb's own sound is heard first |
| Combo / streak step | The success cue a scale step higher per step, then a stinger | Steps 80-120 ms apart; stinger after the last |
| Near miss | A whoosh, harder than an ordinary pass | When the hazard crosses the player, panned to its side |
| Failure / crash | An impact, then a falling sting | Impact at once; sting 0.5-0.8 s later, music ducked to ~20 % |
| Reward granted, new best | A chime or fanfare | After the ad or the result card appears; music ducked |
| Button | A click | On press |

## Mixing levels

- **Music sits 6-10 dB under the sound effects.** A music bus at ~0.5 linear (-6 dB) under
  SFX peaking near 0 dBFS is a good start.
- **UI < gameplay SFX < stingers.** UI clicks ~0.4, gameplay cues 0.6-0.75, stingers
  0.75-0.9 (linear, after the bus).
- **Duck the music under stingers** to 20-50 % for the sting's length, recovering over
  ~0.25 s. Sidechain-style, not a cut.
- **Limit voices** per cue (3-4): twenty coins collected at once is one bright sound.
- **A master limiter** (threshold ~ -6 dB, fast attack) keeps stacked cues from clipping.
- Trim leading silence on short cues to under 10 ms; they must start instantly.

## Formats and budgets

- **Music:** Ogg Opus (96-128 kb/s stereo) or Ogg Vorbis. Older Safari versions do not
  decode Ogg: where they matter, ship an MP3 or AAC/M4A alternative and pick by
  `canPlayType`. At most `max_bytes` for `music` in
  `asset-policy.yaml` (4 MiB) per file; a 60 s loop at 128 kb/s is about 1 MB.
- **Sound effects:** short, mono, 44.1 kHz. A 16-bit WAV under the `sfx` budget (256 KiB)
  is fine for cues under ~2.5 s and decodes instantly; compress longer ones.
- **Loading:** music and sound load after the game is interactive, never in the critical
  path to the first frame (`web-performance.md`); the cue the first tap needs and the first
  music track first.
- **Every file has a licence and a source** in the library or the manifest, like any asset:
  a CC0 recording records its author and URL; music composed as code records the score and
  the renderer.
- **What the pipeline checks** (`asset-quality.yaml` `audio`): it decodes, its length (music
  at least the bar or the design's stated length, a one-shot at most 6 s), it is not silent,
  a loop meets itself, it is within budget, its licence is recorded. In the running game,
  `audio.plays` requires music audible during play, its file fetched, and silence under the
  platform mute.

## Failure modes

- **No music.** Single tones over silence read as unfinished, whatever the art.
- **Audio as an afterthought.** Cues added after the playtest cannot inform it.
- **The same cue for success and failure.**
- **Music that loops audibly** (a click, a gap, a reverb tail cut off) within the first session.
- **One level for everything.** Nothing reads as important; stingers drown in the music.
- **Sound before the first input, or through an ad.** Portals reject the build.
- **A level declared, not measured.** A probe that reports "playing" while the context is
  suspended tells the gate nothing.
