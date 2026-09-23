// Gameplay integration: where the game's own moments meet the platform abstraction.
//
// Written into the game repository by the Factory's `sdk` workflow step. Game code calls
// the hooks here — a run started, the player died, a level ended, the game saved — and this
// file decides what each moment means on the platform the build is running on, using only
// the `Platform` interface from @wgf/platform-sdk. It never touches a portal SDK, and it
// never assumes a capability: every ad is asked for through the capability list (and
// `adAvailability`, where the SDK has it) first, and every failure resolves to "carry on
// without it".
//
// What each moment does is data, in ./integration-plan.ts, generated from the title's
// game-design placements. Change the design and re-run the step; do not hand-edit the plan.
//
// Portal rules this file carries, each from the portal's own documentation:
//   - gameplay stop on every interruption, start when the player is back in control
//     (Yandex 1.19.3, CrazyGames gameplayStart/Stop, Poki requirements)
//   - audio muted and gameplay paused while an ad plays (Yandex 4.7, CrazyGames adStarted,
//     Poki "mute game audio during advertisement playback")
//   - the portal's own pause (Yandex game_api_pause: launch ad, purchase window) pauses and
//     mutes the game (Yandex 1.19.4)
//   - a reward only on the portal's confirmation (all three)
//   - no rewarded button that cannot work (CrazyGames ads requirements, Poki requirements)
//   - Poki: a commercial break each time the player heads back into gameplay, and no local
//     ad timer ("signal as many opportunities as possible"); driven by `breakOnContinue`

import type { Game } from "@wgf/game-core";
import {
  GenericWebPlatform,
  createPlatform,
  type AdKind,
  type AdResult,
  type Platform,
  type PlatformStorage,
  type RewardedResult,
} from "@wgf/platform-sdk";

/** The gameplay moments a placement can be attached to. */
export type GameplayMoment = "game-over" | "level-complete" | "pause-menu";

export interface PlacementPlan {
  readonly id: string;
  readonly kind: AdKind;
  readonly moment: GameplayMoment;
  /** The design's own words for the moment, kept for whoever reads the plan. */
  readonly trigger: string;
  /** Target platform ids the placement is limited to; null for every platform. */
  readonly platforms: readonly string[] | null;
}

export interface IntegrationPlan {
  readonly titleId: string;
  readonly placements: readonly PlacementPlan[];
  /**
   * Target platform id -> the adapter a build for it runs on, where the portal publishes no
   * SDK of its own. Explicit, so a missing adapter elsewhere still fails loudly at boot.
   */
  readonly adapterSubstitutes: Readonly<Record<string, string>>;
  /**
   * Targets whose portal wants an ad opportunity signalled every time the player heads back
   * into gameplay — a restart, a continue, leaving the pause menu — rather than only where
   * the design placed an interstitial. The portal decides whether an ad actually plays.
   */
  readonly breakOnContinue: readonly string[];
}

/** Why the game is running without the platform it was built for. */
export interface Degradation {
  readonly reason: "init-failed";
  readonly target: string;
  readonly detail: string;
}

export interface BootedPlatform {
  readonly platform: Platform;
  /** The platform id the build targets, which a substituted adapter does not change. */
  readonly target: string;
  /** The adapter standing in for a portal that publishes no SDK, or null. */
  readonly substitutedBy: string | null;
  readonly degraded: Degradation | null;
}

export interface BootOptions {
  readonly namespace: string;
  readonly plan: Pick<IntegrationPlan, "adapterSubstitutes">;
  /** For tests: how a platform is constructed. Defaults to the SDK's registry. */
  readonly create?: (id: string, options: { namespace: string }) => Platform;
  /** For tests: the platform used when the target's adapter breaks its contract. */
  readonly fallback?: (namespace: string) => Platform;
}

/**
 * Create and initialize the build's platform.
 *
 * An id with no adapter still throws, as the registry intends: a build that thinks it has a
 * portal SDK and does not must fail where someone will see it.
 *
 * There is deliberately no timeout here. Every adapter bounds its own waits and degrades
 * inside itself when the portal SDK is blocked or slow — it keeps reporting loading, ready
 * and gameplay to an SDK that connects late. Replacing it on a timer would abandon a working
 * SDK mid-start and lose exactly the calls portals check (Yandex LoadingAPI.ready, CrazyGames
 * gameplayStart). Only an `initialize()` that rejects — which the contract says it never
 * does — falls back to the SDK-free adapter, so that even then the game is playable.
 */
export async function bootPlatform(target: string, options: BootOptions): Promise<BootedPlatform> {
  const create = options.create ?? createPlatform;
  const fallback =
    options.fallback ?? ((namespace: string) => new GenericWebPlatform({ namespace }));
  const substitute = options.plan.adapterSubstitutes[target] ?? null;
  const platform = create(substitute ?? target, { namespace: options.namespace });
  try {
    await platform.initialize();
    return { platform, target, substitutedBy: substitute, degraded: null };
  } catch (error) {
    const replacement = fallback(options.namespace);
    await replacement.initialize();
    return {
      platform: replacement,
      target,
      substitutedBy: substitute,
      degraded: {
        reason: "init-failed",
        target,
        detail: error instanceof Error ? error.message : String(error),
      },
    };
  }
}

type Properties = Record<string, string | number | boolean | null>;

/** Where gameplay events go. Structurally the `track` of @wgf/analytics-sdk's Analytics. */
export interface GameplayTracker {
  track(name: string, properties?: Properties): void;
}

/** The game's audio, as far as the platform is concerned: silence it and give it back. */
export interface GameplayAudio {
  mute(): void;
  unmute(): void;
}

export interface PlatformGameplayOptions {
  /** The build's target platform id, from {@link BootedPlatform.target}. */
  readonly target: string;
  readonly tracker?: GameplayTracker;
  /** Muted for every ad and every portal pause. Without it, only the game loop pauses. */
  readonly audio?: GameplayAudio;
  /**
   * A rewarded ad the adapter had already given up on was watched to the end after all
   * (`ad:late-reward`). The reward is owed; the game decides whether it still applies.
   */
  readonly onLateReward?: (moment: GameplayMoment | null) => void;
}

/** What came of a rewarded offer. Grant only when `rewarded` is true. */
export interface RewardOutcome {
  readonly rewarded: boolean;
  /**
   * Why not: the SDK's skip reason ("not-ready" is a portal with no ad right now — say "try
   * again later"; "adblock", "disabled", "unsupported" mean the offer should not have been
   * shown), or "no-placement" where the design placed no reward at this moment.
   */
  readonly reason: string | null;
}

/** The game's side of the platform seam. Scenes call these; nothing else calls Platform. */
export class PlatformGameplay {
  readonly #game: Game;
  readonly #platform: Platform;
  readonly #plan: IntegrationPlan;
  readonly #options: PlatformGameplayOptions;
  readonly #unsubscribe: (() => void)[] = [];
  #inRun = false;
  #inBreak = false;
  #muteHolds = 0;
  #lastRewardMoment: GameplayMoment | null = null;

  constructor(
    game: Game,
    platform: Platform,
    plan: IntegrationPlan,
    options: PlatformGameplayOptions,
  ) {
    this.#game = game;
    this.#platform = platform;
    this.#plan = plan;
    this.#options = options;
    // The portal taking the foreground by itself — Yandex's game_api_pause around its launch
    // ad or a purchase window. The portal keeps its own gameplay markup across it; the game
    // only has to stop and fall silent.
    this.#listen("foreground:lost", () => {
      this.#game.pause("platform");
      this.#mute();
    });
    this.#listen("foreground:gained", () => {
      this.#game.resume("platform");
      this.#unmute();
    });
    this.#listen("ad:late-reward", () => {
      this.#track("ad_late_reward", { moment: this.#lastRewardMoment });
      this.#options.onLateReward?.(this.#lastRewardMoment);
    });
  }

  get platform(): Platform {
    return this.#platform;
  }

  /** False while an ad break holds the screen. Input handlers check it before acting. */
  get inputEnabled(): boolean {
    return !this.#inBreak;
  }

  /** Stop listening to the platform. */
  dispose(): void {
    for (const off of this.#unsubscribe.splice(0)) off();
  }

  /** The player is in control: a run or level started, a continue was granted. */
  runStarted(properties: Properties = {}): void {
    const wasPlaying = this.#playing;
    this.#inRun = true;
    // The template may already have reported gameplay on the player's first input.
    if (!wasPlaying) this.#platform.gameplayStart();
    this.#track("run_start", properties);
  }

  /**
   * The player chose to play on from `moment` — restart after a game over, next level. The
   * natural break comes first (the interstitial the design placed there, or the portal's own
   * opportunity where it wants one before every continue), then gameplay starts.
   */
  async continueFrom(moment: GameplayMoment, properties: Properties = {}): Promise<void> {
    await this.naturalBreak(moment);
    this.runStarted(properties);
  }

  /** Gameplay stopped for a reason with no moment of its own — a menu, a cutscene. */
  runStopped(properties: Properties = {}): void {
    this.#stopRun();
    this.#track("run_stop", properties);
  }

  /** The run ended — death, time out, loss. Gameplay stops; show the result next. */
  gameOver(properties: Properties = {}): void {
    this.#stopRun();
    this.#track("game_over", properties);
  }

  /** A level was cleared. Gameplay stops until the next {@link runStarted}. */
  levelComplete(properties: Properties = {}): void {
    this.#stopRun();
    this.#track("level_complete", properties);
  }

  /** The player opened the pause menu. */
  pause(): void {
    this.#game.pause("manual");
    if (this.#playing) this.#platform.gameplayStop();
  }

  /** The player left the pause menu, back into the run. */
  async resume(): Promise<void> {
    if (this.#inRun && this.#breakOnContinue) await this.#portalBreak("pause-menu");
    this.#game.resume("manual");
    if (this.#inRun && !this.#game.paused && !this.#playing) this.#platform.gameplayStart();
  }

  /**
   * Whether to show the rewarded offer planned for `moment` at all. False where the design
   * placed none there, the adapter has no rewarded ads, ads are off or blocked — a button
   * that does nothing is a listed rejection cause, so hide it instead.
   */
  canOfferReward(moment: GameplayMoment): boolean {
    const placement = this.#placement("rewarded", moment);
    return placement !== null && this.#adAvailable("rewarded");
  }

  /**
   * The player accepted the rewarded offer at `moment`. Grant the reward only when
   * `rewarded` is true — the portal confirmed it — and never on anything less.
   */
  async offerReward(moment: GameplayMoment): Promise<RewardOutcome> {
    const placement = this.#placement("rewarded", moment);
    if (!placement) return { rewarded: false, reason: "no-placement" };
    if (!this.#adAvailable("rewarded")) return { rewarded: false, reason: "unsupported" };
    this.#lastRewardMoment = moment;
    const result = await this.#break(() =>
      // The contract says showRewarded never throws; a portal SDK can still break that.
      this.#platform
        .showRewarded()
        .catch((): RewardedResult => ({ shown: false, rewarded: false, reason: "error" })),
    );
    this.#track("ad_rewarded", {
      placement: placement.id,
      shown: result.shown,
      rewarded: result.rewarded,
      reason: result.reason ?? null,
    });
    const rewarded = result.shown && result.rewarded;
    return { rewarded, reason: rewarded ? null : (result.reason ?? "not-ready") };
  }

  /**
   * A natural break at `moment`, before play continues: the interstitial the design placed
   * there, or the portal's own ad opportunity where it asks for one before every continue.
   * `null` is a break the game signalled at no planned moment: only the latter applies.
   * Always resolves; play continues after, whether or not an ad played.
   */
  async naturalBreak(moment: GameplayMoment | null): Promise<void> {
    const placement = moment === null ? null : this.#placement("interstitial", moment);
    if (placement) await this.#interstitial(placement.id);
    else if (this.#breakOnContinue) await this.#portalBreak(moment ?? "game-over");
  }

  /** A gameplay event, in the one vocabulary; where it lands is the tracker's wiring. */
  track(name: string, properties: Properties = {}): void {
    this.#track(name, properties);
  }

  /** The moment a placement id from the plan is attached to, or null. */
  momentOf(placementId: string): GameplayMoment | null {
    return this.#plan.placements.find((p) => p.id === placementId)?.moment ?? null;
  }

  /** Persist `data` under `key`. Storage failing must never interrupt play. */
  async save(key: string, data: unknown): Promise<boolean> {
    try {
      await this.#storage.set(key, JSON.stringify(data));
      return true;
    } catch (error) {
      // CrazyGames: the Progress Save toggle off, or over 1 MB. Yandex: over 200 KB.
      this.#track("save_failed", { key, error: error instanceof Error ? error.message : null });
      return false;
    }
  }

  /** Read what {@link save} wrote, or `fallback` when it is missing or unreadable. */
  async load<T>(key: string, fallback: T): Promise<T> {
    try {
      const raw = await this.#storage.get(key);
      return raw === null ? fallback : (JSON.parse(raw) as T);
    } catch {
      return fallback;
    }
  }

  get #storage(): PlatformStorage {
    return this.#platform.storage;
  }

  get #breakOnContinue(): boolean {
    return this.#plan.breakOnContinue.includes(this.#options.target);
  }

  // One truth for "gameplay is running": the adapter's own, where the SDK revision exposes
  // it (template bindPlatform reports the first input straight to the platform); this
  // object's otherwise.
  get #playing(): boolean {
    const active: unknown = Reflect.get(this.#platform, "gameplayActive");
    return typeof active === "boolean" ? active : this.#inRun;
  }

  #placement(kind: AdKind, moment: GameplayMoment): PlacementPlan | null {
    return (
      this.#plan.placements.find(
        (p) =>
          p.kind === kind &&
          p.moment === moment &&
          (p.platforms === null || p.platforms.includes(this.#options.target)),
      ) ?? null
    );
  }

  // The capability list says what the adapter can ever do; whether it can right now (the
  // portal SDK blocked, ads disabled) comes from `adAvailability` where the SDK revision has
  // it. Revisions without it expose the same fact per adapter, and until the interface
  // carries it everywhere this reads those, here and nowhere else: Yandex `sdkAvailable`,
  // Poki `sdkState`, CrazyGames `mode`. None of them is typed, so all are read off the object.
  #adAvailable(kind: AdKind): boolean {
    if (!this.#platform.capabilities.ads.includes(kind)) return false;
    const read = (name: string): unknown => Reflect.get(this.#platform, name);
    const probe = read("adAvailability");
    if (typeof probe === "function") {
      try {
        return probe.call(this.#platform, kind) === "available";
      } catch {
        return false;
      }
    }
    if (read("sdkAvailable") === false) return false;
    if (read("sdkState") === "unavailable") return false;
    const mode = read("mode");
    return mode !== "unavailable" && mode !== "disabled";
  }

  async #interstitial(placement: string): Promise<void> {
    if (!this.#adAvailable("interstitial")) return;
    const result = await this.#break(() =>
      this.#platform.showInterstitial().catch((): AdResult => ({ shown: false, reason: "error" })),
    );
    this.#track("ad_interstitial", {
      placement,
      shown: result.shown,
      reason: result.reason ?? null,
    });
  }

  #portalBreak(moment: GameplayMoment): Promise<void> {
    return this.#interstitial(`portal-${moment}`);
  }

  #stopRun(): void {
    const wasPlaying = this.#playing;
    this.#inRun = false;
    if (wasPlaying) this.#platform.gameplayStop();
  }

  // Gameplay stops for the ad (Yandex lists ads among the interruptions) and resumes only if
  // it was running; the game is paused and muted for the whole break, from before the
  // request, so no frame of audio or input reaches an ad that does start.
  async #break<T>(show: () => Promise<T>): Promise<T> {
    const wasPlaying = this.#playing;
    this.#inBreak = true;
    this.#game.pause("ad");
    this.#mute();
    if (wasPlaying) this.#platform.gameplayStop();
    try {
      return await show();
    } finally {
      this.#game.resume("ad");
      this.#unmute();
      this.#inBreak = false;
      if (wasPlaying && !this.#game.paused) this.#platform.gameplayStart();
    }
  }

  // Mute holds are counted: an ad inside a portal pause must not unmute on its own.
  #mute(): void {
    this.#muteHolds += 1;
    if (this.#muteHolds === 1) this.#options.audio?.mute();
  }

  #unmute(): void {
    if (this.#muteHolds === 0) return;
    this.#muteHolds -= 1;
    if (this.#muteHolds === 0) this.#options.audio?.unmute();
  }

  #listen(event: string, handler: () => void): void {
    const on: unknown = Reflect.get(this.#platform, "on");
    if (typeof on !== "function") return;
    const off: unknown = on.call(this.#platform, event, handler);
    if (typeof off === "function") this.#unsubscribe.push(off as () => void);
  }

  #track(name: string, properties: Properties): void {
    try {
      this.#options.tracker?.track(name, { platform: this.#options.target, ...properties });
    } catch {
      // Analytics must never take the game down with it.
    }
  }
}

let installed: PlatformGameplay | null = null;

/** Make the instance main.ts built reachable from scenes. */
export function installGameplay(gameplay: PlatformGameplay): PlatformGameplay {
  installed = gameplay;
  return gameplay;
}

/** The installed gameplay integration. Throws before main.ts has installed one. */
export function gameplay(): PlatformGameplay {
  if (!installed) throw new Error("PlatformGameplay is not installed; main.ts installs it at boot");
  return installed;
}
