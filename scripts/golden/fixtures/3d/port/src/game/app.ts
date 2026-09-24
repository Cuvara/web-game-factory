// The game flow for Neon Drift Arena: menu -> playing -> game over -> (ad) -> playing.
//
// GOLDEN-RUN REPLAY. Ported from examples/neon-drift-arena/src/app.ts by the Factory's
// golden-run replay developer; not agent-written code. What the port changed:
//
//   - every platform call goes through the GameIntegration seam (src/game/integration.ts):
//     gameplayStart/Stop, rewarded, interstitial, save/load. The example called
//     platform.showRewarded / showInterstitial inside withAdBreak directly; the seam's
//     default implementation now does that, and the Factory's `sdk` step rewires it without
//     this file changing;
//   - the scene publishes its id and a step counter to #hud (the template's probe contract),
//     has a pause menu, and triggers audio cues.
//
// Determinism lives entirely in the Simulation (game/simulation.ts); this file only routes
// input and lifecycle.

import type { Game, Scene } from "@wgf/game-core";
import type { Audio } from "../audio/audio.js";
import type { GameIntegration } from "./integration.js";
import { Simulation } from "./simulation.js";

export type Phase = "menu" | "playing" | "over";

// Placement ids are string literals at each call to the seam - the ids reported in
// docs/development/report.json - so the integration can read them from the source.

/** What a drawing layer offers the scene. rendering/threejs/arena-view.ts implements it. */
export interface ArenaDrawing {
  sync(sim: Simulation | null): void;
}

export interface AppOptions {
  readonly game: Game;
  readonly integration: GameIntegration;
  readonly view: ArenaDrawing;
  readonly audio: Audio;
  /** The template's probe element: #hud[data-scene], [data-steps]. */
  readonly probe: HTMLElement;
  /** Present a drawn frame (renderer.render()). Separated so the sim can be tested headless. */
  readonly present: () => void;
  /** Called whenever the visible phase or score changes, so a DOM HUD can follow it. */
  readonly onChange?: (view: AppView) => void;
  /** Seed for the run's obstacle stream. Deterministic runs pass a fixed value. */
  readonly seed?: number;
}

export interface AppView {
  readonly phase: Phase;
  readonly score: number;
  readonly best: number;
  readonly paused: boolean;
  /** True at game over while a revive is still on offer (once per run). */
  readonly canRevive: boolean;
}

const SAVE_BEST = "best";

export class App implements Scene {
  readonly id = "neon-drift-arena";

  readonly #o: AppOptions;
  #phase: Phase = "menu";
  #sim: Simulation | null = null;
  #best = 0;
  #reviveUsed = false;
  #seedCounter: number;
  /** Bumped once per fresh run. A generation marker: same value => same run. */
  #runId = 0;
  #steps = 0;

  constructor(options: AppOptions) {
    this.#o = options;
    this.#seedCounter = options.seed ?? 1;
  }

  get phase(): Phase {
    return this.#phase;
  }
  get score(): number {
    return this.#sim?.score ?? 0;
  }
  get best(): number {
    return this.#best;
  }
  get simulation(): Simulation | null {
    return this.#sim;
  }
  get canRevive(): boolean {
    return (
      this.#phase === "over" &&
      !this.#reviveUsed &&
      this.#o.integration.canOfferRewarded("revive-game-over")
    );
  }
  get runId(): number {
    return this.#runId;
  }
  get steps(): number {
    return this.#steps;
  }

  /** Read the saved best score. Part of loading, before the menu is interactive. */
  async load(): Promise<void> {
    const saved = Number(await this.#o.integration.load(SAVE_BEST));
    this.#best = Number.isFinite(saved) && saved > 0 ? Math.floor(saved) : 0;
    this.#emit();
  }

  // --- Scene ----------------------------------------------------------------------------

  enter(): void {
    this.#o.probe.dataset["scene"] = this.id;
  }

  update(stepMs: number): void {
    this.#steps += 1;
    this.#o.probe.dataset["steps"] = String(this.#steps);
    if (this.#phase !== "playing" || !this.#sim) return;
    const before = this.#sim.score;
    const stillRunning = this.#sim.tick(stepMs);
    if (!stillRunning) {
      void this.#endRun();
      return;
    }
    if (Math.floor(this.#sim.score / 10) > Math.floor(before / 10)) this.#o.audio.play("score");
    this.#emit();
  }

  render(): void {
    this.#o.view.sync(this.#phase === "menu" ? null : this.#sim);
    this.#o.present();
  }

  pause(): void {
    this.#o.audio.setPaused(true);
    this.#emit();
  }

  resume(): void {
    this.#o.audio.setPaused(false);
    this.#emit();
  }

  // --- Player actions -------------------------------------------------------------------

  /** Begin a run from the menu. */
  play(): void {
    if (this.#phase !== "menu" || this.#o.game.paused) return;
    this.#o.audio.unlock();
    this.#o.audio.play("tap");
    this.#startRun();
  }

  /** Steer the current run: -1 left, +1 right, 0 coast. No effect outside a run or paused. */
  steer(direction: number): void {
    if (this.#o.game.paused) return;
    this.#sim?.steer(direction);
  }

  /** Watch a rewarded ad to continue this run once. Granted only on a confirmed reward. */
  async revive(): Promise<boolean> {
    const sim = this.#sim;
    if (this.#phase !== "over" || this.#reviveUsed || !sim) return false;
    const granted = await this.#o.integration.rewarded("revive-game-over");
    if (granted && sim.revive()) {
      this.#reviveUsed = true;
      // Continue the SAME deterministic run; the sim cleared the obstacles on top of us.
      this.#phase = "playing";
      this.#o.audio.play("reward");
      this.#o.integration.gameplayStart();
      this.#emit();
      return true;
    }
    // No reward (declined, no fill, unsupported): stay on the game-over screen.
    this.#emit();
    return false;
  }

  /** A fresh run after game over, at the natural break an interstitial may use. */
  async restart(): Promise<void> {
    if (this.#phase !== "over") return;
    await this.#o.integration.interstitial("restart-game-over");
    this.#startRun();
  }

  /** Back to the menu without an ad. */
  toMenu(): void {
    this.#phase = "menu";
    this.#sim = null;
    this.#emit();
  }

  /** The pause menu: the loop stops, gameplay is reported stopped, audio goes silent. */
  pauseMenu(): void {
    if (this.#phase !== "playing" || this.#o.game.paused) return;
    this.#o.game.pause("manual");
    this.#o.integration.gameplayStop();
    this.#emit();
  }

  resumeMenu(): void {
    if (!this.#o.game.paused) return;
    this.#o.game.resume("manual");
    if (this.#phase === "playing" && !this.#o.game.paused) this.#o.integration.gameplayStart();
    this.#emit();
  }

  // --- Internals ------------------------------------------------------------------------

  #startRun(): void {
    this.#sim = new Simulation({ seed: this.#seedCounter++ });
    this.#reviveUsed = false;
    this.#runId += 1;
    this.#phase = "playing";
    this.#o.integration.gameplayStart();
    this.#emit();
  }

  async #endRun(): Promise<void> {
    this.#phase = "over";
    this.#o.integration.gameplayStop();
    this.#o.audio.play("over");
    const score = this.#sim?.score ?? 0;
    this.#o.integration.track("run_over", { score });
    if (score > this.#best) {
      this.#best = score;
      await this.#o.integration.save(SAVE_BEST, String(score));
    }
    this.#emit();
  }

  #emit(): void {
    this.#o.onChange?.({
      phase: this.#phase,
      score: this.score,
      best: this.#best,
      paused: this.#o.game.paused,
      canRevive: this.canRevive,
    });
  }
}
