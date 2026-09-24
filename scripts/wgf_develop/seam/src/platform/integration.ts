// The game's platform wiring: the default the Factory's `develop` step provides.
//
// Written into the game repository by the Factory's `develop` step before the game is built,
// and replaced as a whole file by its `sdk` step with the integrated wiring. Game code never
// edits it. src/main.ts gets its platform from createGamePlatform() and its integration seam
// from createGameIntegration(); scenes call the GameIntegration (src/game/integration.ts).
//
// Built only on the template's own API: createPlatform with platformOptions(entry) and
// virtual:platform-config - the template's boot lines, so per-title portal settings from
// game.config.yaml (Game IDs) reach the adapter - withAdBreak from ./bind.ts, and
// @wgf/analytics-sdk with a NullSink until the integration wires a real one.

import { Analytics, NullSink, type EventProperties } from "@wgf/analytics-sdk";
import type { Game } from "@wgf/game-core";
import { createPlatform, type Platform } from "@wgf/platform-sdk";
import platformConfig from "virtual:platform-config";
import { platformOptions, primaryPlatform } from "../core/config.js";
import type { GameIntegration } from "../game/integration.js";
import { withAdBreak } from "./bind.js";

/** The game's audio, as far as the platform is concerned: silence it and give it back. */
export interface GameAudio {
  mute(): void;
  unmute(): void;
}

/** Where gameplay events go: structurally the `track` of @wgf/analytics-sdk's Analytics. */
export interface GameTracker {
  track(name: string, properties?: Record<string, string | number | boolean | null>): void;
}

export interface GameIntegrationOptions {
  /**
   * Silenced by the integrated wiring for every ad and portal pause. This default leaves
   * silence to bindPlatform's onAudioMutedChange, which main.ts wires either way.
   */
  readonly audio?: GameAudio;
  /** Receives the seam's track() calls. Without it they go to a NullSink. */
  readonly tracker?: GameTracker;
}

/** Create and initialize the platform game.config.yaml targets, as the template boots it. */
export async function createGamePlatform(): Promise<Platform> {
  const primary = primaryPlatform();
  const platform = createPlatform(primary.id, {
    ...platformOptions(primary),
    y8: platformConfig.y8,
  });
  await platform.initialize();
  return platform;
}

/** The integration seam the game calls, wired to `platform`. */
export function createGameIntegration(
  game: Game,
  platform: Platform,
  options: GameIntegrationOptions = {},
): GameIntegration {
  return new DefaultGameIntegration(
    game,
    platform,
    options.tracker ?? new Analytics({ sink: new NullSink() }),
  );
}

class DefaultGameIntegration implements GameIntegration {
  readonly #game: Game;
  readonly #platform: Platform;
  readonly #tracker: GameTracker;

  constructor(game: Game, platform: Platform, tracker: GameTracker) {
    this.#game = game;
    this.#platform = platform;
    this.#tracker = tracker;
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
    await withAdBreak(this.#game, this.#platform, () => this.#platform.showInterstitial(), {
      resumeGameplay: false,
    });
  }

  track(event: string, properties?: EventProperties): void {
    this.#tracker.track(event, properties ?? {});
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
