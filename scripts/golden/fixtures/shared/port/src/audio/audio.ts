// A small audio service with named cues.
//
// GOLDEN-RUN REPLAY. Written into this repository by the Factory's golden-run replay
// developer (scripts/golden/replay_developer.py); not agent-written code. The replayed
// template example has no sound, so this adds the brief's audio hooks: short synthesized
// tones (no audio files, so nothing delays first play), muted until the first input, and
// silent whenever the platform requires it (an ad, a portal mute setting) or the game is
// paused.

export type Cue = "tap" | "merge" | "score" | "over" | "reward";

const TONES: Readonly<Record<Cue, { freq: number; ms: number }>> = {
  tap: { freq: 660, ms: 40 },
  merge: { freq: 880, ms: 90 },
  score: { freq: 990, ms: 60 },
  over: { freq: 220, ms: 260 },
  reward: { freq: 1320, ms: 140 },
};

export class Audio {
  #context: AudioContext | null = null;
  #unlocked = false;
  #platformMuted = false;
  #paused = false;

  /** The first player input unlocks sound; browsers refuse audio before one anyway. */
  unlock(): void {
    this.#unlocked = true;
  }

  /** The platform's say: an ad is playing or the portal's mute setting is on. */
  setPlatformMuted(muted: boolean): void {
    this.#platformMuted = muted;
  }

  setPaused(paused: boolean): void {
    this.#paused = paused;
  }

  get audible(): boolean {
    return this.#unlocked && !this.#platformMuted && !this.#paused;
  }

  play(cue: Cue): void {
    if (!this.audible) return;
    try {
      this.#context ??= new AudioContext();
      const ctx = this.#context;
      const tone = TONES[cue];
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = tone.freq;
      gain.gain.value = 0.05;
      osc.connect(gain).connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + tone.ms / 1000);
    } catch {
      // No audio device, or a browser that refuses: the game plays muted, which every cue
      // already has a visual twin for.
    }
  }
}
