// Binds the ported BoardView to the template's renderer.
//
// GOLDEN-RUN REPLAY, written by the Factory's golden-run replay developer; not agent-written.
// main.ts gets its renderer from the template's createRenderer, which returns the engine-
// agnostic Renderer. This file, inside src/rendering/pixijs/, is the one place that knows it
// is a PixiRenderer - the engine stays behind this directory.

import type { Renderer } from "@wgf/game-core";
import type { PixiRenderer } from "@wgf/pixi-framework";
import { BoardView } from "./board-view.js";

export function createBoardView(renderer: Renderer): BoardView {
  if (renderer.kind !== "pixijs") {
    throw new Error(`Tower Merge Rush draws with PixiJS; game.config.yaml says ${renderer.kind}`);
  }
  return new BoardView((renderer as PixiRenderer).stage);
}
