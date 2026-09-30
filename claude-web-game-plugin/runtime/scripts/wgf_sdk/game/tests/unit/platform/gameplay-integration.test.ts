// Gameplay integration against SDK mocks.
//
// Written into the game repository by the Factory's `sdk` workflow step, beside
// src/platform/gameplay.ts. Each top-level describe is one situation a build must survive,
// and its name is what the step reads back into the sdk-report — rename them only together
// with SCENARIOS in the Factory's scripts/wgf_sdk/runner.py.
//
// The mocks are the SDK's own SDK-free adapter with individual members replaced: nothing
// here talks to a portal, and nothing here restates the Platform interface.

import { Game } from "@wgf/game-core";
import { GenericWebPlatform, type Platform } from "@wgf/platform-sdk";
import { describe, expect, it } from "vitest";
import {
  PlatformGameplay,
  bootPlatform,
  type GameplayAudio,
  type IntegrationPlan,
} from "../../../src/platform/gameplay.js";

const PLAN: IntegrationPlan = {
  titleId: "test-title",
  placements: [
    {
      id: "rewarded-game-over",
      kind: "rewarded",
      moment: "game-over",
      trigger: "On death, offer a continue",
      platforms: null,
    },
    {
      id: "interstitial-level-complete",
      kind: "interstitial",
      moment: "level-complete",
      trigger: "Between levels",
      platforms: null,
    },
  ],
  adapterSubstitutes: { gamevui: "generic-web" },
  breakOnContinue: ["poki"],
};

interface Portal {
  readonly platform: Platform;
  readonly calls: string[];
  readonly pausedDuringAd: boolean[];
  emit(event: string): void;
}

/**
 * A portal whose SDK loaded: interstitial and rewarded ads, every reward confirmed, and the
 * adapter's own gameplay state (`gameplayActive`). `overrides` replace members by
 * definition, so members one SDK revision does not declare can still be exercised.
 */
function portal(game: Game, overrides: Record<string, unknown> = {}): Portal {
  const calls: string[] = [];
  const pausedDuringAd: boolean[] = [];
  const listeners = new Map<string, Set<() => void>>();
  let active = false;
  const platform = new GenericWebPlatform({ namespace: "test" });
  const capabilities = { ...platform.capabilities, ads: ["interstitial", "rewarded"] };
  const members: Record<string, unknown> = {
    capabilities,
    // A portal with ads says so when asked. (generic-web itself answers "disabled" for a
    // listed kind: it has no SDK to ask, so this fake has to.)
    adAvailability: (kind: string) =>
      capabilities.ads.includes(kind) ? "available" : "unsupported",
    gameplayStart: () => {
      if (active) return;
      active = true;
      calls.push("gameplayStart");
    },
    gameplayStop: () => {
      if (!active) return;
      active = false;
      calls.push("gameplayStop");
    },
    showRewarded: () => {
      calls.push("rewarded");
      pausedDuringAd.push(game.paused);
      return Promise.resolve({ shown: true, rewarded: true });
    },
    showInterstitial: () => {
      calls.push("interstitial");
      pausedDuringAd.push(game.paused);
      return Promise.resolve({ shown: true });
    },
    on: (event: string, handler: () => void) => {
      const set = listeners.get(event) ?? new Set();
      set.add(handler);
      listeners.set(event, set);
      return () => set.delete(handler);
    },
    ...overrides,
  };
  for (const [name, value] of Object.entries(members)) {
    Object.defineProperty(platform, name, { value, configurable: true });
  }
  Object.defineProperty(platform, "gameplayActive", { get: () => active, configurable: true });
  return {
    platform,
    calls,
    pausedDuringAd,
    emit: (event) => listeners.get(event)?.forEach((handler) => handler()),
  };
}

function audio(): GameplayAudio & { log: string[] } {
  const log: string[] = [];
  return { log, mute: () => void log.push("mute"), unmute: () => void log.push("unmute") };
}

/** Game over -> result -> rewarded offer -> continue, else break -> restart. */
async function gameOverFlow(gameplay: PlatformGameplay, acceptOffer: boolean): Promise<string> {
  gameplay.gameOver({ score: 10 });
  if (gameplay.canOfferReward("game-over") && acceptOffer) {
    if ((await gameplay.offerReward("game-over")).rewarded) {
      gameplay.runStarted({ continued: true });
      return "continued";
    }
  }
  await gameplay.continueFrom("game-over");
  return "restarted";
}

describe("sdk-available", () => {
  it("the template's per-title portal settings reach the adapter unchanged", async () => {
    // platformOptions(entry) carries GameDistribution's and GameMonetize's Game IDs from
    // game.config.yaml; booting with only a namespace started those portals without them.
    const seen: unknown[] = [];
    const options = {
      namespace: "test",
      portalGameId: "gm-title-0001",
      gamedistribution: { gameId: "0123456789abcdef0123456789abcdef" },
      y8: { appId: "y8-app" },
    };
    await bootPlatform("gamemonetize", {
      options,
      plan: PLAN,
      create: (_id, received) => {
        seen.push(received);
        return new GenericWebPlatform({ namespace: received.namespace });
      },
    });
    expect(seen).toEqual([options]);
  });
  it("boots on the target platform without degrading", async () => {
    const game = new Game();
    const { platform } = portal(game);
    const booted = await bootPlatform("yandex", {
      options: { namespace: "test" },
      plan: PLAN,
      create: () => platform,
    });
    expect(booted).toMatchObject({ platform, target: "yandex", substitutedBy: null });
    expect(booted.degraded).toBeNull();
  });

  it("brackets a run with exactly one gameplay start and stop", () => {
    const game = new Game();
    const { platform, calls } = portal(game);
    const gameplay = new PlatformGameplay(game, platform, PLAN, { target: "yandex" });
    gameplay.runStarted();
    gameplay.runStarted();
    gameplay.gameOver();
    gameplay.gameOver();
    expect(calls).toEqual(["gameplayStart", "gameplayStop"]);
  });

  it("gameplay the template started on first input is stopped at game over", () => {
    const game = new Game();
    const { platform, calls } = portal(game);
    const gameplay = new PlatformGameplay(game, platform, PLAN, { target: "poki" });
    platform.gameplayStart(); // bindPlatform's first-input handler
    gameplay.gameOver();
    expect(calls).toEqual(["gameplayStart", "gameplayStop"]);
  });

  it("a level transition shows the planned interstitial, and no other moment does", async () => {
    const game = new Game();
    const { platform, calls } = portal(game);
    const gameplay = new PlatformGameplay(game, platform, PLAN, { target: "yandex" });
    gameplay.levelComplete();
    await gameplay.naturalBreak("level-complete");
    await gameplay.naturalBreak("game-over");
    expect(calls.filter((c) => c === "interstitial")).toHaveLength(1);
  });

  it("Poki gets an ad opportunity before every continue", async () => {
    const game = new Game();
    const { platform, calls } = portal(game);
    const gameplay = new PlatformGameplay(game, platform, PLAN, { target: "poki" });
    gameplay.runStarted();
    gameplay.gameOver();
    await gameplay.continueFrom("game-over");
    expect(calls).toEqual(["gameplayStart", "gameplayStop", "interstitial", "gameplayStart"]);
  });

  it("saves and loads through the platform's storage", async () => {
    const game = new Game();
    const { platform } = portal(game);
    const gameplay = new PlatformGameplay(game, platform, PLAN, { target: "yandex" });
    expect(await gameplay.save("progress", { level: 3 })).toBe(true);
    expect(await gameplay.load("progress", { level: 1 })).toEqual({ level: 3 });
  });

  it("reports gameplay events to the tracker", () => {
    const game = new Game();
    const { platform } = portal(game);
    const events: string[] = [];
    const gameplay = new PlatformGameplay(game, platform, PLAN, {
      target: "yandex",
      tracker: { track: (name) => void events.push(name) },
    });
    gameplay.runStarted();
    gameplay.gameOver();
    expect(events).toEqual(["run_start", "game_over"]);
  });
});

describe("sdk-unavailable", () => {
  it("runs the whole loop on the SDK-free adapter and never requests an ad", async () => {
    const game = new Game();
    const platform = new GenericWebPlatform({ namespace: "test" });
    const gameplay = new PlatformGameplay(game, platform, PLAN, { target: "generic-web" });
    gameplay.runStarted();
    expect(gameplay.canOfferReward("game-over")).toBe(false);
    expect(await gameOverFlow(gameplay, true)).toBe("restarted");
    expect(await gameplay.offerReward("game-over")).toEqual({
      rewarded: false,
      reason: "unsupported",
    });
    expect(platform.usage.adsRequested).toEqual({ interstitial: 0, rewarded: 0, banner: 0 });
    expect(await gameplay.save("progress", { level: 2 })).toBe(true);
    expect(await gameplay.load("progress", { level: 1 })).toEqual({ level: 2 });
  });

  it("a portal without an SDK runs on its configured substitute adapter", async () => {
    const created: string[] = [];
    const booted = await bootPlatform("gamevui", {
      options: { namespace: "test" },
      plan: PLAN,
      create: (id, options) => {
        created.push(id);
        return new GenericWebPlatform({ namespace: options.namespace });
      },
    });
    expect(created).toEqual(["generic-web"]);
    expect(booted).toMatchObject({ target: "gamevui", substitutedBy: "generic-web" });
    expect(booted.degraded).toBeNull();
  });
});

describe("sdk-init-failure", () => {
  it("an initialize that rejects continues on the SDK-free adapter", async () => {
    const failing = new GenericWebPlatform({ namespace: "test" });
    failing.initialize = (): Promise<void> => Promise.reject(new Error("sdk.js blocked"));
    const booted = await bootPlatform("yandex", {
      options: { namespace: "test" },
      plan: PLAN,
      create: () => failing,
    });
    expect(booted.platform).not.toBe(failing);
    expect(booted.platform.id).toBe("generic-web");
    expect(booted.degraded).toMatchObject({ reason: "init-failed", target: "yandex" });
    expect(booted.degraded?.detail).toContain("sdk.js blocked");
  });

  it("the degraded game still completes a game-over loop", async () => {
    const failing = new GenericWebPlatform({ namespace: "test" });
    failing.initialize = (): Promise<void> => Promise.reject(new Error("no SDK"));
    const booted = await bootPlatform("poki", {
      options: { namespace: "test" },
      plan: PLAN,
      create: () => failing,
    });
    const game = new Game();
    const gameplay = new PlatformGameplay(game, booted.platform, PLAN, { target: booted.target });
    gameplay.runStarted();
    expect(await gameOverFlow(gameplay, true)).toBe("restarted");
    expect(game.paused).toBe(false);
  });
});

describe("ad-unavailable", () => {
  it("hides the rewarded offer when the adapter has no rewarded ads", () => {
    const game = new Game();
    const { platform } = portal(game, {
      capabilities: { ...new GenericWebPlatform({ namespace: "t" }).capabilities, ads: [] },
    });
    const gameplay = new PlatformGameplay(game, platform, PLAN, { target: "gamevui" });
    expect(gameplay.canOfferReward("game-over")).toBe(false);
  });

  it("hides the rewarded offer when ads are disabled or blocked", () => {
    const game = new Game();
    for (const availability of ["disabled", "adblock", "unsupported"]) {
      const { platform } = portal(game, { adAvailability: () => availability });
      const gameplay = new PlatformGameplay(game, platform, PLAN, { target: "yandex" });
      expect(gameplay.canOfferReward("game-over")).toBe(false);
    }
  });

  it("hides the offer when the adapter reports its portal SDK did not load", () => {
    const game = new Game();
    for (const unreachable of [
      { sdkAvailable: false },
      { sdkState: "unavailable" },
      { mode: "unavailable" },
      { mode: "disabled" },
    ]) {
      // An SDK revision without adAvailability, where these flags are all there is.
      const { platform } = portal(game, { ...unreachable, adAvailability: undefined });
      const gameplay = new PlatformGameplay(game, platform, PLAN, { target: "yandex" });
      expect(gameplay.canOfferReward("game-over")).toBe(false);
    }
  });

  it("no fill says so, so the game can say 'try again later'", async () => {
    const game = new Game();
    const { platform } = portal(game, {
      showRewarded: () => Promise.resolve({ shown: false, rewarded: false, reason: "not-ready" }),
    });
    const gameplay = new PlatformGameplay(game, platform, PLAN, { target: "crazygames" });
    expect(await gameplay.offerReward("game-over")).toEqual({
      rewarded: false,
      reason: "not-ready",
    });
  });

  it("an SDK that throws from an ad call does not break the loop", async () => {
    const game = new Game();
    const { platform } = portal(game, {
      showRewarded: () => Promise.reject(new Error("sdk crashed")),
      showInterstitial: () => Promise.reject(new Error("sdk crashed")),
    });
    const gameplay = new PlatformGameplay(game, platform, PLAN, { target: "poki" });
    gameplay.runStarted();
    expect(await gameOverFlow(gameplay, true)).toBe("restarted");
    expect(game.paused).toBe(false);
    expect(gameplay.inputEnabled).toBe(true);
  });

  it("a placement limited to other platforms is not offered here", async () => {
    const game = new Game();
    const { platform } = portal(game);
    const limited: IntegrationPlan = {
      ...PLAN,
      placements: PLAN.placements.map((p) => ({ ...p, platforms: ["crazygames"] })),
    };
    const gameplay = new PlatformGameplay(game, platform, limited, { target: "yandex" });
    expect(gameplay.canOfferReward("game-over")).toBe(false);
    expect((await gameplay.offerReward("game-over")).reason).toBe("no-placement");
  });
});

describe("ad-closed-early", () => {
  it("an ad closed before the reward grants nothing and play restarts", async () => {
    const game = new Game();
    const { platform, calls } = portal(game, {
      showRewarded: () => Promise.resolve({ shown: true, rewarded: false }),
    });
    const gameplay = new PlatformGameplay(game, platform, PLAN, { target: "yandex" });
    gameplay.runStarted();
    expect(await gameOverFlow(gameplay, true)).toBe("restarted");
    expect(calls.at(-1)).toBe("gameplayStart");
    expect(game.paused).toBe(false);
  });
});

describe("reward-callback", () => {
  it("a confirmed reward continues the run, paused and muted during the ad", async () => {
    const game = new Game();
    const sound = audio();
    const { platform, calls, pausedDuringAd } = portal(game);
    const gameplay = new PlatformGameplay(game, platform, PLAN, { target: "yandex", audio: sound });
    gameplay.runStarted();
    expect(await gameOverFlow(gameplay, true)).toBe("continued");
    expect(calls).toEqual(["gameplayStart", "gameplayStop", "rewarded", "gameplayStart"]);
    expect(pausedDuringAd).toEqual([true]);
    expect(sound.log).toEqual(["mute", "unmute"]);
    expect(game.paused).toBe(false);
  });

  it("a reward that arrives after the adapter gave up is handed to the game", () => {
    const game = new Game();
    const { platform, emit } = portal(game);
    const owed: (string | null)[] = [];
    new PlatformGameplay(game, platform, PLAN, {
      target: "yandex",
      onLateReward: (moment) => void owed.push(moment),
    });
    emit("ad:late-reward");
    expect(owed).toEqual([null]);
  });
});

describe("pause-resume", () => {
  it("the pause menu stops gameplay and leaving it starts it again", async () => {
    const game = new Game();
    const { platform, calls } = portal(game);
    const gameplay = new PlatformGameplay(game, platform, PLAN, { target: "yandex" });
    gameplay.runStarted();
    gameplay.pause();
    expect(game.paused).toBe(true);
    await gameplay.resume();
    expect(game.paused).toBe(false);
    expect(calls).toEqual(["gameplayStart", "gameplayStop", "gameplayStart"]);
  });

  it("the portal's own pause pauses and mutes the game until it gives the foreground back", () => {
    const game = new Game();
    const sound = audio();
    const { platform, emit } = portal(game);
    new PlatformGameplay(game, platform, PLAN, { target: "yandex", audio: sound });
    emit("foreground:lost");
    expect(game.paused).toBe(true);
    emit("foreground:gained");
    expect(game.paused).toBe(false);
    expect(sound.log).toEqual(["mute", "unmute"]);
  });

  it("a player pause survives the portal giving the foreground back", () => {
    const game = new Game();
    const { platform, emit } = portal(game);
    const gameplay = new PlatformGameplay(game, platform, PLAN, { target: "yandex" });
    gameplay.pause();
    emit("foreground:lost");
    emit("foreground:gained");
    expect(game.paused).toBe(true);
  });

  it("failing storage and a failing tracker never interrupt play", async () => {
    const game = new Game();
    const { platform } = portal(game);
    Object.defineProperty(platform, "storage", {
      value: {
        get: () => Promise.reject(new Error("quota")),
        set: () => Promise.reject(new Error("quota")),
        remove: () => Promise.reject(new Error("quota")),
      },
    });
    const gameplay = new PlatformGameplay(game, platform, PLAN, {
      target: "yandex",
      tracker: {
        track: () => {
          throw new Error("sink down");
        },
      },
    });
    gameplay.runStarted();
    expect(await gameplay.save("progress", { level: 2 })).toBe(false);
    expect(await gameplay.load("progress", { level: 1 })).toEqual({ level: 1 });
    gameplay.gameOver();
  });
});

describe("platform-not-configured", () => {
  it("a platform with no adapter still fails loudly at boot", async () => {
    await expect(
      bootPlatform("crazygames", {
        options: { namespace: "test" },
        plan: PLAN,
        create: (id) => {
          throw new Error(`Platform adapter "${id}" is not implemented yet.`);
        },
      }),
    ).rejects.toThrow(/not implemented/);
  });
});
