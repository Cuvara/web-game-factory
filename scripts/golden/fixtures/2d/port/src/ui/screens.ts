// The DOM overlay for Tower Merge Rush: in-run HUD plus the title, pause and game-over
// screens. Every string comes from the locale table (public/locales/<locale>.json).
//
// GOLDEN-RUN REPLAY. Ported from examples/tower-merge-rush/src/main.ts (DomUi) by the
// Factory's golden-run replay developer; not agent-written code.

import type { I18n } from "../core/i18n.js";
import type { Hud } from "../game/app.js";
import { COLUMNS, type State } from "../game/rules.js";

export interface ScreenActions {
  begin(): void;
  continue(): void;
  double(): void;
  restart(): void;
  pause(): void;
  resume(): void;
}

export class Screens implements Hud {
  readonly #root: HTMLElement;
  readonly #i18n: I18n;
  readonly #hud: HTMLElement;
  readonly #score: HTMLElement;
  readonly #best: HTMLElement;
  readonly #drop: HTMLElement;
  readonly #start: HTMLElement;
  readonly #pause: HTMLElement;
  readonly #over: HTMLElement;
  readonly #overScore: HTMLElement;
  readonly #overBest: HTMLElement;
  readonly #note: HTMLElement;
  readonly #pauseBtn: HTMLButtonElement;
  readonly #continueBtn: HTMLButtonElement;
  readonly #doubleBtn: HTMLButtonElement;
  readonly #restartBtn: HTMLButtonElement;

  constructor(root: HTMLElement, i18n: I18n, actions: ScreenActions) {
    this.#root = root;
    this.#i18n = i18n;
    const t = (key: string): string => i18n.t(key);
    root.innerHTML = `
      <div class="hud" data-role="hud" hidden>
        <span data-role="score"></span>
        <span data-role="best"></span>
        <span class="spacer"></span>
        <span data-role="drop"></span>
      </div>
      <button class="pause" data-action="pause" hidden>${t("hud.pause")}</button>
      <section class="screen" data-screen="start" data-role="start">
        <h1>${t("title.heading")}</h1>
        <p data-role="rules">${t("title.rules").replace("1-7", `1-${COLUMNS}`)}</p>
        <button data-action="play">${t("title.play")}</button>
      </section>
      <section class="screen" data-screen="pause" data-role="pause" hidden>
        <h1>${t("pause.heading")}</h1>
        <button data-action="resume">${t("pause.resume")}</button>
      </section>
      <section class="screen" data-screen="over" data-role="over" hidden>
        <h1>${t("over.heading")}</h1>
        <p data-role="over-score"></p>
        <p data-role="over-best"></p>
        <p class="note" data-role="note"></p>
        <div class="row">
          <button class="ad" data-action="continue">${t("over.continue")}</button>
          <button class="ad secondary" data-action="double">${t("over.double")}</button>
        </div>
        <button data-action="restart">${t("over.restart")}</button>
      </section>`;

    const find = <T extends HTMLElement>(selector: string): T => {
      const found = root.querySelector<T>(selector);
      if (!found) throw new Error(`ui is missing ${selector}`);
      return found;
    };
    this.#hud = find('[data-role="hud"]');
    this.#score = find('[data-role="score"]');
    this.#best = find('[data-role="best"]');
    this.#drop = find('[data-role="drop"]');
    this.#start = find('[data-role="start"]');
    this.#pause = find('[data-role="pause"]');
    this.#over = find('[data-role="over"]');
    this.#overScore = find('[data-role="over-score"]');
    this.#overBest = find('[data-role="over-best"]');
    this.#note = find('[data-role="note"]');
    this.#pauseBtn = find('[data-action="pause"]');
    this.#continueBtn = find('[data-action="continue"]');
    this.#doubleBtn = find('[data-action="double"]');
    this.#restartBtn = find('[data-action="restart"]');

    find('[data-action="play"]').addEventListener("click", actions.begin);
    find('[data-action="resume"]').addEventListener("click", actions.resume);
    this.#pauseBtn.addEventListener("click", actions.pause);
    this.#continueBtn.addEventListener("click", actions.continue);
    this.#doubleBtn.addEventListener("click", actions.double);
    this.#restartBtn.addEventListener("click", actions.restart);
  }

  setState(state: State): void {
    this.#start.hidden = state !== "start";
    this.#over.hidden = state !== "over";
    this.#hud.hidden = state === "start";
    this.#pauseBtn.hidden = state !== "playing";
    this.#root.dataset["screen"] = state;
  }
  setPaused(paused: boolean): void {
    this.#pause.hidden = !paused;
  }
  setScore(score: number): void {
    this.#score.textContent = `${this.#i18n.t("hud.score")} ${score}`;
  }
  setBest(best: number): void {
    this.#best.textContent = `${this.#i18n.t("hud.best")} ${best}`;
    this.#overBest.textContent = `${this.#i18n.t("over.best")} ${best}`;
  }
  setDropLevel(level: number): void {
    this.#drop.textContent = `${this.#i18n.t("hud.next")} ${level}`;
  }
  setNote(key: string | null): void {
    this.#note.textContent = key ? this.#i18n.t(key) : "";
  }
  setBusy(busy: boolean): void {
    this.#continueBtn.disabled = busy;
    this.#doubleBtn.disabled = busy;
    this.#restartBtn.disabled = busy;
  }
  setOver(view: { score: number; canContinue: boolean; canOffer: boolean }): void {
    this.#overScore.textContent = `${this.#i18n.t("over.score")} ${view.score}`;
    this.#continueBtn.hidden = !view.canContinue || !view.canOffer;
    this.#doubleBtn.hidden = !view.canOffer;
  }
}
