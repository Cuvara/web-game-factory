// A stand-in for the develop step's gameplay, for the sdk module's browser e2e only.
//
// Copied into a scratch copy of web-game-template by scripts/wgf_sdk/e2e.py; it never
// reaches a real game. It plays a run the way a develop-step scene does — only through the
// seam, src/game/integration.ts, with its own placement ids — and exposes itself on
// `window.__run` so Playwright can drive it.

import type { Game } from "@wgf/game-core";
import type { GameIntegration } from "./integration.js";

export interface RunLoop {
  state: "idle" | "running" | "continued" | "restarted" | "paused";
  score: number;
  offered: boolean;
  start(): void;
  miss(acceptOffer: boolean): Promise<string>;
  clearLevel(): Promise<string>;
  pause(): void;
  resume(): Promise<void>;
  best(): Promise<number>;
}

export function startRunLoop(seam: GameIntegration, game: Game): RunLoop {
  const run: RunLoop = {
    state: "idle",
    score: 0,
    offered: false,
    start() {
      seam.gameplayStart();
      seam.track("run_start");
      run.state = "running";
      run.score = 0;
    },
    async miss(acceptOffer) {
      run.score += 10;
      seam.gameplayStop();
      const best = Number((await seam.load("best")) ?? 0);
      await seam.save("best", String(Math.max(best, run.score)));
      run.offered = seam.canOfferRewarded("revive-after-crash");
      if (run.offered && acceptOffer && (await seam.rewarded("revive-after-crash"))) {
        seam.gameplayStart();
        return (run.state = "continued");
      }
      await seam.interstitial("retry-break");
      seam.gameplayStart();
      return (run.state = "restarted");
    },
    async clearLevel() {
      seam.gameplayStop();
      await seam.interstitial("between-levels");
      seam.gameplayStart();
      return (run.state = "running");
    },
    pause() {
      game.pause("manual");
      seam.gameplayStop();
      run.state = "paused";
    },
    async resume() {
      game.resume("manual");
      seam.gameplayStart();
      run.state = "running";
    },
    async best() {
      return Number((await seam.load("best")) ?? 0);
    },
  };
  (window as unknown as { __run: RunLoop }).__run = run;
  return run;
}
