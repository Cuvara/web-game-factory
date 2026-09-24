// The flow: start -> playing -> over -> (rewarded continue / double) -> (interstitial) -> start.
//
// GOLDEN-RUN REPLAY. Ported from examples/tower-merge-rush/src/app.ts by the Factory's
// golden-run replay developer; not agent-written code. What the port changed:
//
//   - every platform call goes through the GameIntegration seam (src/game/integration.ts):
//     gameplayStart/Stop, rewarded, interstitial, save/load. The example called
//     platform.showRewarded / withAdBreak directly; the seam's default implementation now
//     does that, and the Factory's `sdk` step rewires it without this file changing.
//   - the scene publishes its id and a step counter to #hud (the template's probe contract);
//   - the personal best is persisted through the seam, and audio cues are triggered.
//
// The pure rules live in game/rules.ts; the Pixi drawing in rendering/pixijs/board-view.ts.

import type { Game, Scene } from "@wgf/game-core";
import type { Audio } from "../audio/audio.js";
import type { GameIntegration } from "./integration.js";
import { MergeGame, type Snapshot } from "./rules.js";

// Placement ids are string literals at each call to the seam - the ids reported in
// docs/development/report.json - so the integration can read them from the source.

const SAVE_BEST = "best";

export interface Hud {
  setState(state: Snapshot["state"]): void;
  setPaused(paused: boolean): void;
  setScore(score: number): void;
  setBest(best: number): void;
  setDropLevel(level: number): void;
  setNote(key: string | null): void;
  setBusy(busy: boolean): void;
  setOver(view: { score: number; canContinue: boolean; canOffer: boolean }): void;
}

/** What a drawing layer offers the scene. rendering/pixijs/board-view.ts implements it. */
export interface BoardDrawing {
  draw(snapshot: Snapshot): void;
}

export interface AppOptions {
  readonly game: Game;
  readonly integration: GameIntegration;
  readonly hud: Hud;
  /** The template's probe element: #hud[data-scene], [data-steps]. */
  readonly probe: HTMLElement;
  readonly view: BoardDrawing;
  readonly audio: Audio;
  readonly present: () => void;
  /** Injected so runs are deterministic in tests. */
  readonly random?: () => number;
}

export class App implements Scene {
  readonly id = "tower-merge-rush";

  readonly #o: AppOptions;
  readonly #merge: MergeGame;
  #continued = false;
  #best = 0;
  #steps = 0;

  constructor(options: AppOptions) {
    this.#o = options;
    this.#merge = new MergeGame(options.random ? { random: options.random } : {});
  }

  /** For the deterministic test hooks. */
  get merge(): MergeGame {
    return this.#merge;
  }
  get best(): number {
    return this.#best;
  }
  get steps(): number {
    return this.#steps;
  }

  /** Read the saved best score. Part of loading, before the title screen is interactive. */
  async load(): Promise<void> {
    const saved = Number(await this.#o.integration.load(SAVE_BEST));
    this.#best = Number.isFinite(saved) && saved > 0 ? Math.floor(saved) : 0;
  }

  // --- Scene ------------------------------------------------------------------------------

  enter(): void {
    this.#o.probe.dataset["scene"] = this.id;
    this.#render();
  }

  render(): void {
    this.#render();
  }

  // A merge game changes state only on input; the fixed-step loop still ticks, and the step
  // counter is the probe's proof that the loop runs (it stops while the game is paused).
  update(): void {
    this.#steps += 1;
    this.#o.probe.dataset["steps"] = String(this.#steps);
  }

  pause(): void {
    this.#o.audio.setPaused(true);
  }

  resume(): void {
    this.#o.audio.setPaused(false);
  }

  // --- Player actions ---------------------------------------------------------------------

  /** The first input starts a run; every later input during play drops a piece. */
  drop(col: number): void {
    if (this.#o.game.paused) return;
    this.#o.audio.unlock();
    if (this.#merge.state === "start") {
      this.#merge.begin();
      this.#syncGameplay();
    }
    if (this.#merge.state !== "playing") return;

    const result = this.#merge.dropAt(col);
    if (!result.placed) return;
    this.#o.audio.play(result.merges > 0 ? "merge" : "tap");
    if (result.over) void this.#onOver();
    this.#render();
  }

  /** A plain tap with no column drops into the first open column. */
  dropAnywhere(): void {
    const col = this.#merge.state === "playing" ? this.#merge.firstOpenColumn() : 0;
    this.drop(col ?? 0);
  }

  /** Rewarded "continue": clear the board and play on, keeping the score. Once per run. */
  async continue(): Promise<boolean> {
    if (this.#merge.state !== "over" || this.#continued) return false;
    const granted = await this.#rewarded(() => this.#o.integration.rewarded("continue-game-over"));
    if (granted) {
      this.#continued = true;
      this.#merge.continueRun();
      this.#syncGameplay();
      this.#o.hud.setNote(null);
      this.#render();
      return true;
    }
    this.#reportAdMiss();
    return false;
  }

  /** Rewarded "double score": doubles the final score. Granted only on a confirmed reward. */
  async doubleScore(): Promise<boolean> {
    if (this.#merge.state !== "over") return false;
    const granted = await this.#rewarded(() =>
      this.#o.integration.rewarded("double-score-game-over"),
    );
    if (granted) {
      this.#merge.doubleScore();
      await this.#recordBest();
      this.#showOver();
      this.#o.hud.setNote(null);
      this.#render();
      return true;
    }
    this.#reportAdMiss();
    return false;
  }

  /**
   * Another run: the natural break an interstitial may use. The seam resolves whether or not
   * an ad played, so an unfilled ad never blocks the restart.
   */
  async restart(): Promise<void> {
    this.#o.hud.setBusy(true);
    try {
      await this.#o.integration.interstitial("restart-game-over");
    } finally {
      this.#o.hud.setBusy(false);
    }
    this.#merge.reset();
    this.#continued = false;
    this.#o.hud.setNote(null);
    this.#syncGameplay();
    this.#render();
  }

  /** The pause menu: the game stops, gameplay is reported stopped, audio goes silent. */
  pauseMenu(): void {
    if (this.#merge.state !== "playing" || this.#o.game.paused) return;
    this.#o.game.pause("manual");
    this.#o.integration.gameplayStop();
    this.#o.hud.setPaused(true);
  }

  resumeMenu(): void {
    if (!this.#o.game.paused) return;
    this.#o.game.resume("manual");
    this.#o.hud.setPaused(false);
    this.#syncGameplay();
  }

  // --- Internals --------------------------------------------------------------------------

  async #onOver(): Promise<void> {
    this.#syncGameplay();
    this.#o.audio.play("over");
    this.#o.integration.track("run_over", { score: this.#merge.score, merges: this.#merge.merges });
    await this.#recordBest();
    this.#showOver();
  }

  #showOver(): void {
    this.#o.hud.setOver({
      score: this.#merge.score,
      canContinue: !this.#continued,
      canOffer: this.#o.integration.canOfferRewarded("continue-game-over"),
    });
    this.#o.hud.setBest(this.#best);
  }

  async #recordBest(): Promise<void> {
    if (this.#merge.score <= this.#best) return;
    this.#best = this.#merge.score;
    await this.#o.integration.save(SAVE_BEST, String(this.#best));
  }

  async #rewarded(offer: () => Promise<boolean>): Promise<boolean> {
    this.#o.hud.setBusy(true);
    try {
      const granted = await offer();
      if (granted) this.#o.audio.play("reward");
      return granted;
    } finally {
      this.#o.hud.setBusy(false);
    }
  }

  #reportAdMiss(): void {
    this.#o.hud.setNote("note.no-ad");
    this.#render();
  }

  /** Report gameplay running exactly while a run is on screen and the game is not paused. */
  #syncGameplay(): void {
    const running = this.#merge.state === "playing" && !this.#o.game.paused;
    if (running) this.#o.integration.gameplayStart();
    else this.#o.integration.gameplayStop();
  }

  #render(): void {
    const snapshot = this.#merge.snapshot();
    this.#o.hud.setState(snapshot.state);
    this.#o.hud.setScore(snapshot.score);
    this.#o.hud.setBest(this.#best);
    this.#o.hud.setDropLevel(snapshot.dropLevel);
    this.#o.view.draw(snapshot);
    this.#o.present();
  }
}
