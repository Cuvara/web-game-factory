# Research V2 test fixtures

FIXTURE data, invented to drive `scripts/tests/test_research_v2.py` deterministically and
offline. Every `source_uri` is under `fixtures.invalid`, every game record says
`"fixture": true`, and every game name starts with `FX`. None of it is market data or a real
gameplay observation; it must never be copied into `workspace/research/`.

- `snapshots/` - portal listings: a Poki puzzle popularity list captured on two dates (for
  the trend), with category counts (for supply and saturation), and a CrazyGames arcade list
- `games/` - teardown records (core/artifacts/shared/game-record.schema.json): three match-3
  games, two lane runners and a merge puzzle, coded on the research vocabulary
