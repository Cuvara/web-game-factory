# Real evidence for the contact checks

`physics.contact_drawn` and `physics.drawn_extent` (`scripts/wgf_playability/realism.py`
`judge_contacts`, `core/reference/play-realism.yaml` `contact`), replayed by
`scripts/tests/test_play_contact.py` `RealRecordings`. REAL: every frame here was drawn by a
build of the 2D validation game (Brick Breaker Worlds, `val-2d/games/brick-breaker-worlds`) and
captured by the playability bot's contact test; nothing was re-measured or edited by hand
beyond the conversions stated below.

## How it was captured (2026-10-10, Windows 11, CPU only, no paid service)

- Each commit was checked out with `git worktree add --detach` into a scratch directory outside
  both repositories, installed with `pnpm install --frozen-lockfile --offline` and built with
  `pnpm build` (all succeeded). The game repository was not changed.
- The bot (`bot.spec.ts` at sha256 `9eac6d29...f848`, this branch's contact test before its
  last refinement - a turn at a surface that moved in the frame after the turn is now also not
  frozen on; the Python side leaves such a capture unread either way) ran with the repository's
  own Playwright against `pnpm preview` (ports 4181/4182), behind the Factory's refusing proxy,
  `--grep contact`, desktop (1280x720) and mobile (Pixel 5). Settings: the 2026-10-05 run's
  `settings.json` (playability visit 10-1) plus `PlayabilityStep._contact_settings`, with the
  window raised to 240 s and 12 captures: the shared host drew 3-7 frames a second (other
  agents' builds; `frame_gaps` in each record), and the stepped clock turns 40 s of that into a
  few seconds of game time.
- `<commit>/`: the build as committed. Its probe reports no `collider`.
- `<commit>-collider/`: the same commit with ONE harness change to the scratch build - the
  probe reports, beside each ball's drawn box, the optional `entities[].collider` the
  play-probe schema already defines: the circle of `BALL.radius` (the constant `sim.ts`
  collides with), projected with the view's own `toScreen` and scale. Nothing drawn or
  simulated changes. The patch (`src/rendering/pixijs/view.ts`, +9 -1, sha256 of the 68a12b7
  diff `b504d560...e43d`):

  ```ts
  const probed = rectOf(entity.id, entity.role, entity, entity.render, entity.asset, entity.kind);
  // wgf-k7 harness: the ball's collider (BALL.radius), as play-probe entities[].collider.
  const ball = session.sim.balls.find((b) => `ball-${b.id}` === entity.id);
  if (ball) {
    const c = this.toScreen(ball.x - BALL.radius, ball.y - BALL.radius);
    const d = 2 * BALL.radius * this.#scale;
    (probed as unknown as Record<string, unknown>)["collider"] = { shape: "circle", x: c.x, y: c.y, w: d, h: d };
  }
  out.push(probed);
  ```

  This is what the game side of the follow-up is: a probe that reports its colliders. Until a
  game does, `physics.drawn_extent` is unmeasured on it (never a pass).

## Conversions (size)

- `contact.json.gz`: the bot's `contact.json` trimmed to the fields the checks read and the run
  facts above (`applies`, `clock`, `frame_ms`, timings, `ended`, `captures`, `passed`,
  `frame_gaps`), gzipped. The `-collider` sets keep their first 6 captures
  (`kept_first_captures`).
- Frames: only the frames a check actually reads (the ones it pins by sha256), each cropped to
  the region it reads (the mover's box at the turn grown by the tolerance and its travel; each
  collider's extent window grown by a quarter collider) and re-encoded as RGBA PNG - pixels
  unchanged; the capture's `clip` moved to the crop. The builder replayed both checks on the
  full recording and on the fixture and refused any difference but the frames' own hashes.
- `manifest.json.gz`: every file with its sha256 (`test_fixtures_are_the_bytes_recorded`).

## What each set shows

| Set | Build | Expected | Measured |
|---|---|---|---|
| `68a12b7/` | regressed head (r11 collider, ball drawn 60, undrawn ceilings) | contact_drawn FAIL | desktop 5 of 10 contacts at nothing drawn (13.2-33.5), mobile 7 of 12 (16.3-16.9); its drawn walls 237-242 |
| `cbac64e/` | the commit that added the undrawn ceilings (H2) | contact_drawn FAIL | desktop 2 of 11 (17.2, 17.5), mobile 3 of 11 (15.8-17.5) |
| `96f5cea/` | accepted r1 | contact_drawn PASS | 6 of 6 per viewport drawn, 172-385 |
| `68a12b7-collider/` | head, collider reported | drawn_extent FAIL (H3) | 2.68 x 2.14 its collider (the 44 -> 60 enlargement of the paper ball) |
| `96f5cea-collider/` | r1, collider reported | drawn_extent FAIL | 1.89-2.05: r1's 42.3 px solid disc over its 22 px collider - over the 1.3 bar `physics.collider_size` already holds; 894b4b8's tuning comment states the same figure |
| `894b4b8-collider/` | r1-forward: r1's art, collider grown to the solid disc (r20) | drawn_extent PASS, contact_drawn PASS | 1.03-1.2 on both viewports |

`drawn_extent` on the sets without a collider is unmeasured (`not-reported`), held as not passed
at the release tier.

## The `-r2` sets: the play-realism 1.2.0 bot (2026-10-12)

Recorded again after the K7 review, with the same scratch builds, settings and harness patch,
by the bot of this branch at the commit that adds these sets (`bot.spec.ts` sha256 `79fa7ac1...7c2c`,
port 4200; `contact.json` carries
`game_ms`): it freezes on turns at moving and composite surfaces too (marked `passing`), keeps a
third frame `contact-<n>-later` as many frames after `-after`, crops `CONTACT_MARGIN` 5 x the
mover's size (at least 120 px), and ends "no mover in play" on game time.

- All 12 captures are kept. Every frame the judge LOADED is kept, cropped to the bounding box of
  the pixels it read in any frame of the capture plus 2 px (a composite's drawn share, which
  reads its whole box in view, is left out of the box; a frame loaded and never read is kept as
  one pixel); the capture's clips moved to the crop. The builder (k7 scratch
  `build_fixtures2.py`) replayed both checks on the full recording and on the fixture and
  refused any difference but the frames' own hashes.

| Set | Expected | Measured |
|---|---|---|
| `68a12b7-collider-r2/` (desktop, mobile) | contact_drawn FAIL, drawn_extent FAIL | 3 + 2 contacts at the undrawn ceiling (4.6-16.7); drawn 2.32-2.33 x its collider across its travel |
| `cbac64e-collider-r2/` (desktop) | contact_drawn FAIL, drawn_extent FAIL | 2 contacts at the undrawn ceiling (16.2); drawn 1.74 x across its travel |
| `96f5cea-collider-r2/` (desktop, mobile) | contact_drawn PASS, drawn_extent FAIL | every contact read drawn; r1's solid disc 1.95-2.04 x its collider across its travel |
| `96f5cea-r2/` (desktop, mobile) | contact_drawn PASS | every contact read drawn, paddles where they went and brick rows along their face among them; no collider: drawn_extent unmeasured |
| `894b4b8-collider-r2/` (desktop, mobile) | contact_drawn PASS, drawn_extent PASS | 1.05-1.06 x across its travel (0.98-1.22 for any `solid_share` 0.3-0.5); the collider against where it touched 0.66-0.92 |

Every drawn contact on these sets read 103-385, every undrawn one 4.6-17.1.
