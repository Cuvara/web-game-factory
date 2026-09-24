// The game's platform wiring, integrated.
//
// Written into the game repository by the Factory's `sdk` workflow step. It replaces, as a
// whole file, the default wiring the `develop` step provided at the same path, with the same
// exports, so src/main.ts and the game's calls do not change: createGamePlatform() boots
// through bootPlatform (substitute adapters, degradation instead of a blank page), and
// createGameIntegration() installs PlatformGameplay - the integration plan generated from
// the game-design - behind the game's own GameIntegration seam.
//
// Built only on the template's own API: createPlatform's options are exactly what the
// template's boot passes (platformOptions(entry) + virtual:platform-config), so per-title
// portal settings from game.config.yaml reach the adapter unchanged.

import type { Game } from "@wgf/game-core";
import type { Platform } from "@wgf/platform-sdk";
import platformConfig from "virtual:platform-config";
import { platformOptions, primaryPlatform } from "../core/config.js";
import type { GameIntegration } from "../game/integration.js";
import { PlatformGameIntegration } from "./game-integration.js";
import {
  PlatformGameplay,
  bootPlatform,
  installGameplay,
  type BootedPlatform,
  type GameplayAudio,
  type GameplayTracker,
} from "./gameplay.js";
import { INTEGRATION_PLAN } from "./integration-plan.js";

/** The game's audio, as far as the platform is concerned: silence it and give it back. */
export type GameAudio = GameplayAudio;
/** Where gameplay events go: structurally the `track` of @wgf/analytics-sdk's Analytics. */
export type GameTracker = GameplayTracker;

export interface GameIntegrationOptions {
  /** Silenced for every ad and every portal pause. Without it, only the game loop pauses. */
  readonly audio?: GameAudio;
  /** Receives gameplay events on platforms that do not measure play themselves. */
  readonly tracker?: GameTracker;
}

let booted: BootedPlatform | null = null;

/** Create and initialize the platform game.config.yaml targets, through the integration. */
export async function createGamePlatform(): Promise<Platform> {
  const primary = primaryPlatform();
  booted = await bootPlatform(primary.id, {
    options: { ...platformOptions(primary), y8: platformConfig.y8 },
    plan: INTEGRATION_PLAN,
  });
  // The adapter's initialize() rejected: play on without it rather than show a blank page,
  // and leave the reason where the verify suite can see it.
  if (booted.degraded) console.warn("platform degraded", booted.degraded);
  return booted.platform;
}

/** The integration seam the game calls, wired to `platform` through the integration plan. */
export function createGameIntegration(
  game: Game,
  platform: Platform,
  options: GameIntegrationOptions = {},
): GameIntegration {
  installGameplay(
    new PlatformGameplay(game, platform, INTEGRATION_PLAN, {
      target: booted?.target ?? primaryPlatform().id,
      ...(options.audio ? { audio: options.audio } : {}),
      ...(options.tracker ? { tracker: options.tracker } : {}),
    }),
  );
  return new PlatformGameIntegration();
}
