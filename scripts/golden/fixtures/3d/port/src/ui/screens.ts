// The DOM overlay for Neon Drift Arena: score HUD plus the menu, pause and crash screens.
// Every string comes from the locale table (public/locales/<locale>.json).
//
// GOLDEN-RUN REPLAY. Ported from examples/neon-drift-arena (index.html and the paintHud
// block of src/main.ts) by the Factory's golden-run replay developer; not agent-written.

import type { I18n } from "../core/i18n.js";
import type { AppView } from "../game/app.js";

export interface ScreenActions {
  play(): void;
  revive(): Promise<boolean>;
  restart(): void;
  pause(): void;
  resume(): void;
}

export class Screens {
  readonly #i18n: I18n;
  readonly #hud: HTMLElement;
  readonly #score: HTMLElement;
  readonly #best: HTMLElement;
  readonly #menu: HTMLElement;
  readonly #pause: HTMLElement;
  readonly #pauseBtn: HTMLElement;
  readonly #over: HTMLElement;
  readonly #overScore: HTMLElement;
  readonly #overBest: HTMLElement;
  readonly #revive: HTMLButtonElement;
  readonly #note: HTMLElement;

  constructor(root: HTMLElement, i18n: I18n, actions: ScreenActions) {
    this.#i18n = i18n;
    const t = (key: string): string => i18n.t(key);
    root.innerHTML = `
      <div id="score-hud" hidden>
        <span>${t("hud.score")} <b id="score">0</b></span>
        <span>${t("hud.best")} <b id="best">0</b></span>
      </div>
      <button id="pause" class="pause" hidden>${t("hud.pause")}</button>
      <div id="menu" class="screen" data-screen="start">
        <h1>${t("title.heading")}</h1>
        <p>${t("title.rules")}</p>
        <button id="play">${t("title.play")}</button>
      </div>
      <div id="paused" class="screen" data-screen="pause" hidden>
        <h1>${t("pause.heading")}</h1>
        <button id="resume">${t("pause.resume")}</button>
      </div>
      <div id="over" class="screen" data-screen="over" hidden>
        <h1>${t("over.heading")}</h1>
        <p>${t("over.score")} <b id="over-score">0</b></p>
        <p>${t("over.best")} <b id="over-best">0</b></p>
        <div class="note" id="note"></div>
        <button id="revive" class="secondary" hidden>${t("over.revive")}</button>
        <button id="restart">${t("over.restart")}</button>
      </div>`;

    const find = <T extends HTMLElement>(id: string): T => {
      const found = root.querySelector<T>(`#${id}`);
      if (!found) throw new Error(`ui is missing #${id}`);
      return found;
    };
    this.#hud = find("score-hud");
    this.#score = find("score");
    this.#best = find("best");
    this.#menu = find("menu");
    this.#pause = find("paused");
    this.#pauseBtn = find("pause");
    this.#over = find("over");
    this.#overScore = find("over-score");
    this.#overBest = find("over-best");
    this.#revive = find<HTMLButtonElement>("revive");
    this.#note = find("note");

    find("play").addEventListener("click", () => actions.play());
    find("resume").addEventListener("click", () => actions.resume());
    this.#pauseBtn.addEventListener("click", () => actions.pause());
    find("restart").addEventListener("click", () => {
      this.#note.textContent = "";
      actions.restart();
    });
    this.#revive.addEventListener("click", () => {
      void actions.revive().then((granted) => {
        if (!granted) this.#note.textContent = this.#i18n.t("note.no-ad");
      });
    });
  }

  paint(v: AppView): void {
    this.#score.textContent = String(v.score);
    this.#best.textContent = String(v.best);
    this.#hud.hidden = v.phase === "menu";
    this.#pauseBtn.hidden = v.phase !== "playing" || v.paused;
    this.#menu.hidden = v.phase !== "menu";
    this.#pause.hidden = !(v.paused && v.phase === "playing");
    this.#over.hidden = v.phase !== "over";
    this.#overScore.textContent = String(v.score);
    this.#overBest.textContent = String(v.best);
    this.#revive.hidden = !v.canRevive;
  }
}
