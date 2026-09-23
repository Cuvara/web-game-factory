// A stand-in for the develop step's default seam implementation, for the sdk module's
// browser e2e only. The develop brief asks for one in src/platform/, built on the
// template's Platform; the sdk step replaces its construction in main.ts. It is written
// the plain way a developer would, so the e2e proves the replacement, not this file.

import type { EventProperties } from "@wgf/analytics-sdk";
import type { Platform } from "@wgf/platform-sdk";
import type { GameIntegration } from "../game/integration.js";

export class DefaultIntegration implements GameIntegration {
  readonly #platform: Platform;

  constructor(platform: Platform) {
    this.#platform = platform;
  }

  gameplayStart(): void {
    this.#platform.gameplayStart();
  }

  gameplayStop(): void {
    this.#platform.gameplayStop();
  }

  canOfferRewarded(_placement: string): boolean {
    return this.#platform.capabilities.ads.includes("rewarded");
  }

  async rewarded(_placement: string): Promise<boolean> {
    return (await this.#platform.showRewarded()).rewarded;
  }

  async interstitial(_placement: string): Promise<void> {
    await this.#platform.showInterstitial();
  }

  track(_event: string, _properties?: EventProperties): void {}

  load(key: string): Promise<string | null> {
    return this.#platform.storage.get(key);
  }

  save(key: string, value: string): Promise<void> {
    return this.#platform.storage.set(key, value);
  }
}
