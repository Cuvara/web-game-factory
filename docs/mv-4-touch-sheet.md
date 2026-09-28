# MV-4 real-touch observation sheet

For criterion B of [mv-4-plan.md](mv-4-plan.md). One sheet per device. It is filled in by the
person holding the handset; nothing here can be filled in from an emulator, which is the reason
the sheet exists — hit-target size, touch latency and browser gesture collisions are the
failures device emulation reproduces least.

```
session_id:
date:
build_sha256:
served_from:                   # the URL the handset opened, and how it was reached
device:                        # make, model
os:                            # Android version
browser:                       # name and version, from chrome://version
screen:                        # reported CSS pixels x DPR, from the page
measurement_class: real-device
observer:
```

## Per control

One row per interactive element the game exposes, including menu buttons, the pause control and
anything on the game-over screen.

```
- control:                     # what it is
  reachable_one_handed:        # yes | no
  target_ok:                   # yes | no — comfortably hit on the first attempt, three times
  first_touch_acknowledged:    # yes | no — visible feedback on touch-down, not on release
  responds_during_animation:   # yes | no — input taken while something is animating
  double_fire:                 # yes | no — one tap produced two actions
  notes:
```

## Browser gesture collisions

Each of these is a real-device failure mode with no desktop equivalent. Answer from the
handset, during play.

```
pull_to_refresh_reloads:       # yes | no — swiping down during play reloaded the page
back_swipe_leaves_game:        # yes | no — an edge swipe navigated away
double_tap_zooms:              # yes | no
long_press_selects_text:       # yes | no — or opened a context menu
pinch_zooms_the_page:          # yes | no
address_bar_resizes_canvas:    # yes | no — and whether the game recovered
system_gesture_bar_overlaps:   # yes | no — the navigation bar covering a control
```

## Sustained play

```
play_minutes:                  # at least 10, uninterrupted
device_got_hot:                # yes | no
visible_slowdown:              # yes | no — and when it started
battery_start_pct:
battery_end_pct:
audio_played:                  # yes | no
audio_after_silent_switch:     # respected | ignored
call_or_notification_during:   # what happened, and whether the game recovered
screen_lock_and_return:        # what happened, and whether the game recovered
app_switch_and_return:         # what happened, and whether the game recovered
```

## Verdict

```
criterion_b:                   # PASS | FAIL — PASS needs every control operable, no dropped
                               # first touch, and no gesture collision that interrupts play
failures:
  - 
```
