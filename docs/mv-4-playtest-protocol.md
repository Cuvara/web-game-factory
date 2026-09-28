# MV-4 playtest protocol

Two kill criteria set at strategy are statements about people, and no pipeline run produces
them:

1. Fewer than 60% of first-time players understand the control.
2. Fewer than 50% retry without being prompted.

This is the protocol that would produce them, and the protocol for the weaker session that can
be run when no first-time participant is available. The two are kept apart on purpose: a
session run by someone who already knows the game is evidence about the build and about nothing
else, and it never enters either percentage.

## Before any session

Fix these, in writing, before the first participant sees the game. A threshold or a definition
changed after seeing a result is a fitted result.

- **The build.** One artifact, named by its sha256. Every participant plays the same bytes. The
  build is not changed between sessions, and it is not changed to make a criterion pass.
- **The instruction.** Exactly one sentence, identical for every participant: *"Play this."*
  Nothing else is said until the session ends. No pointing, no hints, no answering "what do I
  do?" — "whatever you like" is the only permitted reply.
- **The definitions.**
  - *Understands the control*: within 60 seconds of the first frame, and without being told, the
    participant performs the game's primary action deliberately and repeats it. Discovering it
    by accident and not repeating it is not understanding.
  - *Retries unprompted*: after the first game-over, the participant starts another run without
    being asked to, within 30 seconds, with no comment from the observer.
- **The calculation.** Share = (participants meeting the definition) ÷ (participants who
  reached the relevant point). A participant who never reached game-over is excluded from the
  retry share and the exclusion is recorded. Nothing is rounded in the participant's favour.
- **Privacy.** Record only: a participant number, prior knowledge yes/no, and the observations
  below. No name, no age, no contact details, no recording of the person. Screen capture only,
  and only if the participant agrees.

## Session, first-time participant

1. Hand over the device or the keyboard with the game already loaded and at its first screen.
2. Say the instruction. Start a timer.
3. Say nothing further. Do not react to questions, laughter, or frustration.
4. Observe against the sheet below. Write what happened, not what it meant.
5. End at 5 minutes, or when the participant stops of their own accord.
6. Only afterwards, ask the two debrief questions and write the answers verbatim:
   - "What were you trying to do?"
   - "What made you stop?"

Five participants is the minimum for the criteria to be decidable. Fewer than five: the
criteria stay UNVERIFIED and the sessions are still recorded.

## Session, developer test

Identical, except that the participant already knows the game. The observer and the participant
may be the same person. It answers a different question — does the build hold up in a real play
session, end to end — and its results are recorded under `measurement_class: developer-test`.

It does not enter criterion 1 or criterion 2, in any form, and those criteria remain UNVERIFIED
after it. Its purpose is to find defects, not to estimate what a stranger would do.

## Observation sheet

One per session. Copy it as it stands; leave a field blank rather than guessing.

```
session_id:
date:
build_sha256:
artifact:                      # what was played, and how it was served
device:                        # make, model, OS, browser and version
input:                         # touch | mouse | keyboard | gamepad
measurement_class:             # first-time-player | developer-test
prior_knowledge:               # yes | no — a "yes" makes this a developer test
instruction_given:             # verbatim
observer:

first_60_seconds:
  first_input_at_s:            # seconds from first frame to the first deliberate input
  primary_action_found_at_s:   # blank if never
  primary_action_repeated:     # yes | no
  understood_control:          # yes | no — by the definition above, not by impression
  what_they_tried:             # free text, behaviour only

session:
  runs_played:
  first_game_over_at_s:        # blank if never reached
  retried_unprompted:          # yes | no | n/a (never reached game-over)
  time_to_retry_s:
  total_session_s:
  reached_score:               # the game's own number, if visible

what_went_wrong:               # anything the build did that it should not have
  - 

confusions:                    # moments the participant was visibly lost, with the timestamp
  - 

debrief:
  what_were_you_trying_to_do:  # verbatim
  what_made_you_stop:          # verbatim

notes:
```

## Recording the result

Write each completed sheet to `docs/evidence/mv-4/playtests/<session_id>.yaml` and run
`python scripts/mv4/playtest.py --summarize` to compute the two shares. That script refuses to
count a `developer-test` session towards either criterion, refuses to report a share computed
from fewer than five first-time participants, and prints UNVERIFIED with the reason instead.
