// The default GameIntegration: the seam from the development brief, wired to the template's
// Platform, withAdBreak and Analytics.
//
// GOLDEN-RUN REPLAY. Written into this repository by the Factory's golden-run replay
// developer (scripts/golden/replay_developer.py), which ports a known-good template example
// into the generated game. It is not agent-written code. The Factory's `sdk` step replaces
// the construction of this class in main.ts with its own PlatformGameIntegration; the game's
// calls do not change.

import { Analytics, NullSink, type EventProperties } from "@wgf/analytics-sdk";
import type { Game } from "@wgf/game-core";
import type { Platform } from "@wgf/platform-sdk";
import type { GameIntegration } from "../game/integration.js";
import { withAdBreak } from "./bind.js";

export class DefaultGameIntegration implements GameIntegration {
  readonly #game: Game;
  readonly #platform: Platform;
  readonly #analytics: Analytics;

  constructor(game: Game, platform: Platform, analytics?: Analytics) {
    this.#game = game;
    this.#platform = platform;
    this.#analytics = analytics ?? new Analytics({ sink: new NullSink() });
  }

  gameplayStart(): void {
    if (!this.#game.paused) this.#platform.gameplayStart();
  }

  gameplayStop(): void {
    this.#platform.gameplayStop();
  }

  canOfferRewarded(_placement: string): boolean {
    if (!this.#platform.capabilities.ads.includes("rewarded")) return false;
    const availability = this.#platform.adAvailability?.("rewarded");
    return availability === undefined || availability === "available";
  }

  async rewarded(placement: string): Promise<boolean> {
    if (!this.canOfferRewarded(placement)) return false;
    const result = await withAdBreak(this.#game, this.#platform, () =>
      this.#platform.showRewarded(),
    );
    return result.rewarded === true;
  }

  async interstitial(_placement: string): Promise<void> {
    // The player heads back into a fresh run; the game reports gameplayStart itself.
    await withAdBreak(this.#game, this.#platform, () => this.#platform.showInterstitial(), {
      resumeGameplay: false,
    });
  }

  track(event: string, properties?: EventProperties): void {
    this.#analytics.track(event, properties ?? {});
  }

  async load(key: string): Promise<string | null> {
    try {
      return await this.#platform.storage.get(key);
    } catch {
      return null;
    }
  }

  async save(key: string, value: string): Promise<void> {
    try {
      await this.#platform.storage.set(key, value);
    } catch {
      this.track("save_failed", { key });
    }
  }
}
