# Audio

**Serves** `audio_direction`, `build_spec.audio`, the asset manifest's `sfx`/`music` lines,
and the `audio`/`sfx`/`music` kinds in `core/reference/asset-policy.yaml`.

Many portal players have sound off, and the rest have it on in public. Sound has to be
optional, and valuable when it is on: it is half of `game-feel.md`'s feedback bar.

## Browser rules (non-negotiable)

- **Unlock on the first user gesture.** Browsers block audio until the player interacts.
  Create or resume the audio context on the first tap. Never try to autoplay music on load.
- **Muted by default, or muted until first input.** The mute state persists across reloads.
- **A mute toggle is visible on every screen**, and the platform's own mute or volume signal
  wins over it.
- **Silence on pause, tab blur and every ad break**, then resume exactly where it was. The
  platform profiles require it, and players expect it.

## The cue list

Every `build_spec.audio` entry names a `trigger` that matches a real event in the build
spec: a reward id, a failure, a HUD change, a state transition. Minimum set for a prototype:

| Event | Cue |
|---|---|
| Core verb (tap, jump, place) | Short and soft. It plays most often, so it must not fatigue |
| Success / collect | Bright, rising |
| Combo / streak step | The success cue with pitch rising per step |
| Failure | Distinct, lower, not punishing |
| UI confirm / back | Two quiet clicks |
| Reward screen | A brief sting |
| Music | One loop, optional in the prototype; ducked under stingers |

## Mix and variation

- **Relative levels.** UI is quieter than gameplay SFX, and gameplay SFX are quieter than
  stingers. Music sits about 6–10 dB under SFX.
- **Vary what repeats.** Randomise pitch by ±5–10 % (or rotate 2–3 samples) on any cue that
  plays more than once every few seconds.
- **Limit voices.** Cap simultaneous instances per cue, for example 3. Twenty coins collected
  at once is one bright sound, not twenty.
- Short cues start instantly. Trim leading silence to under 10 ms.

## Budget and format

- SFX are short, compressed, mono where possible, and within the `max_bytes` in
  `asset-policy.yaml`. Music is one compressed loop that streams or loads after first play.
- Audio never blocks the first frame (`web-performance.md`).
- Generated tones are placeholders. A pure sine beep does not meet the feedback bar in a
  playtest. At minimum use shaped, procedurally synthesised SFX (an envelope plus noise or
  pitch sweeps), and record their origin and licence like any other asset.

## Failure modes

- **Audio as an afterthought.** Cues added after the playtest cannot inform it.
- **The same cue for success and failure.**
- **Music that loops audibly** within the first session.
