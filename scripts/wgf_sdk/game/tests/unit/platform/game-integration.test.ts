// The game's integration seam against SDK mocks.
//
// Written into the game repository by the Factory's `sdk` workflow step, with
// src/platform/game-integration.ts, when the game declares the seam
// (src/game/integration.ts). The game's own placement ids reach the platform through the
// integration plan; nothing here talks to a portal.

import { Game } from "@wgf/game-core";
import { GenericWebPlatform } from "@wgf/platform-sdk";
import { describe, expect, it } from "vitest";
import { PlatformGameIntegration } from "../../../src/platform/game-integration.js";
import {
  PlatformGameplay,
  installGameplay,
  type IntegrationPlan,
} from "../../../src/platform/gameplay.js";

const PLAN: IntegrationPlan = {
  titleId: "test-title",
  placements: [
    {
      id: "revive-after-crash",
      kind: "rewarded",
      moment: "game-over",
      trigger: "On death, offer a continue",
      platforms: null,
    },
    {
      id: "between-levels",
      kind: "interstitial",
      moment: "level-complete",
      trigger: "Between levels",
      platforms: null,
    },
  ],
  adapterSubstitutes: {},
  breakOnContinue: ["poki"],
};

function install(target: string, reward = true): { calls: string[] } {
  const calls: string[] = [];
  const game = new Game();
  const platform = new GenericWebPlatform({ namespace: "seam" });
  let active = false;
  const members: Record<string, unknown> = {
    capabilities: { ...platform.capabilities, ads: ["interstitial", "rewarded"] },
    gameplayStart: () => void (active || (calls.push("gameplayStart"), (active = true))),
    gameplayStop: () => void (active && (calls.push("gameplayStop"), (active = false))),
    showRewarded: () => {
      calls.push("rewarded");
      return Promise.resolve({ shown: true, rewarded: reward });
    },
    showInterstitial: () => {
      calls.push("interstitial");
      return Promise.resolve({ shown: true });
    },
  };
  for (const [name, value] of Object.entries(members)) {
    Object.defineProperty(platform, name, { value, configurable: true });
  }
  Object.defineProperty(platform, "gameplayActive", { get: () => active, configurable: true });
  installGameplay(new PlatformGameplay(game, platform, PLAN, { target }));
  return { calls };
}

describe("game-seam", () => {
  it("the game's placement ids reach the platform at their planned moments", async () => {
    const { calls } = install("yandex");
    const seam = new PlatformGameIntegration();
    seam.gameplayStart();
    seam.gameplayStop();
    expect(seam.canOfferRewarded("revive-after-crash")).toBe(true);
    expect(await seam.rewarded("revive-after-crash")).toBe(true);
    await seam.interstitial("between-levels");
    expect(calls).toEqual(["gameplayStart", "gameplayStop", "rewarded", "interstitial"]);
  });

  it("an unknown placement is never offered or granted", async () => {
    const { calls } = install("yandex");
    const seam = new PlatformGameIntegration();
    expect(seam.canOfferRewarded("not-in-the-plan")).toBe(false);
    expect(await seam.rewarded("not-in-the-plan")).toBe(false);
    await seam.interstitial("not-in-the-plan");
    expect(calls).toEqual([]);
  });

  it("an unconfirmed reward is not granted", async () => {
    install("yandex", false);
    expect(await new PlatformGameIntegration().rewarded("revive-after-crash")).toBe(false);
  });

  it("Poki gets its break at any natural break the game signals", async () => {
    const { calls } = install("poki");
    await new PlatformGameIntegration().interstitial("not-in-the-plan");
    expect(calls).toEqual(["interstitial"]);
  });

  it("saves and loads raw values, and survives storage failing", async () => {
    install("yandex");
    const seam = new PlatformGameIntegration();
    await seam.save("best", "42");
    expect(await seam.load("best")).toBe("42");
    seam.track("run_start", { level: 1, mode: null });
  });
});
