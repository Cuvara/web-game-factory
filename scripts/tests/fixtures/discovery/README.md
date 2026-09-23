# Discovery test fixtures

Invented, and labelled as such: every `source_uri` is under `fixtures.invalid`. These exist
to drive `scripts/tests/test_discovery.py` deterministically and offline. They are not market
data and must never be copied into `workspace/research/`.

- `corpus/snapshots/` - three evidence snapshots (platform docs and a category listing)
- `corpus/probes.yaml` - live probes, answered by the test's fake fetcher
- `backlog/` - one rejected opportunity, to exercise deduplication
