// Input for Tower Merge Rush: pointer and keyboard mapped to game actions.
//
// GOLDEN-RUN REPLAY. Ported from the input block of examples/tower-merge-rush/src/main.ts
// by the Factory's golden-run replay developer; not agent-written code. Rules never read a
// DOM event: this turns them into drop / pause actions, and ignores them while paused.

import { COLUMNS } from "../game/rules.js";

export interface ColumnTarget {
  readonly paused: boolean;
  drop(col: number): void;
  dropAnywhere(): void;
  togglePause(): void;
}

export function columnFromClientX(surface: HTMLElement, clientX: number): number {
  const rect = surface.getBoundingClientRect();
  const ratio = (clientX - rect.left) / Math.max(1, rect.width);
  return Math.min(COLUMNS - 1, Math.max(0, Math.floor(ratio * COLUMNS)));
}

export function bindColumnInput(surface: HTMLElement, target: ColumnTarget): () => void {
  const onPointer = (event: PointerEvent): void => {
    if (target.paused) return;
    target.drop(columnFromClientX(surface, event.clientX));
  };
  const onKey = (event: KeyboardEvent): void => {
    if (event.key === "Escape" || event.key === "p" || event.key === "P") {
      target.togglePause();
      return;
    }
    if (target.paused) return;
    if (event.key >= "1" && event.key <= String(COLUMNS)) {
      target.drop(Number(event.key) - 1);
    } else if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      target.dropAnywhere();
    }
  };
  surface.addEventListener("pointerdown", onPointer);
  window.addEventListener("keydown", onKey);
  return () => {
    surface.removeEventListener("pointerdown", onPointer);
    window.removeEventListener("keydown", onKey);
  };
}
