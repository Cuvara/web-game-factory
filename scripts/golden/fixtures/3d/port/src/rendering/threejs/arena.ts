// Binds the ported ArenaView to the template's renderer and aims its camera.
//
// GOLDEN-RUN REPLAY, written by the Factory's golden-run replay developer; not agent-written.
// main.ts gets its renderer from the template's createRenderer, which returns the engine-
// agnostic Renderer. This file, inside src/rendering/threejs/, is the one place that knows it
// is a ThreeRenderer - the engine stays behind this directory. The camera placement is the
// example's (examples/neon-drift-arena/src/main.ts).

import type { Renderer } from "@wgf/game-core";
import type { ThreeRenderer } from "@wgf/three-framework";
import { ArenaView } from "./arena-view.js";

export function createArenaView(renderer: Renderer): ArenaView {
  if (renderer.kind !== "threejs") {
    throw new Error(`Neon Drift Arena draws with Three.js; game.config.yaml says ${renderer.kind}`);
  }
  const three = renderer as ThreeRenderer;
  // The renderer created the camera at (0,0,5) facing -Z; lift and tilt it so the arena
  // reads in perspective.
  three.camera.position.set(0, 4.5, 8);
  three.camera.lookAt(0, 0, -12);
  three.camera.updateProjectionMatrix();
  const view = new ArenaView();
  view.attach(three.scene);
  return view;
}
