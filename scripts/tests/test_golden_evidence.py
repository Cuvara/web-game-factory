"""The golden evidence carries the playability numbers: every playability-report version and
the bot's records, copied from a run store. No node, no browser, no golden run."""

import json
import os
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from golden import summary  # noqa: E402
from wgflib.workflow.model import ArtifactRef  # noqa: E402
from wgflib.workflow.store import RunStore  # noqa: E402

RUN_ID = "golden-test-run"


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(content, handle)


class CollectPlayability(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = RunStore(os.path.join(self.tmp.name, "store"), fsync=False)
        self.evidence = os.path.join(self.tmp.name, "evidence")
        run_dir = self.store.run_dir(RUN_ID)
        refs = []
        for version, step in ((1, "greybox-playability"), (2, "playability")):
            location, checksum = self.store.write_artifact(
                RUN_ID, "playability-report", version, {"version": version, "step": step})
            refs.append(ArtifactRef(id="playability-report", type="playability-report",
                                    version=version, location=location, checksum=checksum,
                                    produced_by=step))
        other, checksum = self.store.write_artifact(RUN_ID, "qa-report", 1, {"qa": True})
        out = os.path.join(run_dir, "playability", "1-1", "out")
        _write(os.path.join(out, "settings.json"), {"start_timeout_ms": 30000})
        _write(os.path.join(out, "desktop", "first-session.json"), {"startedAtMs": 6900})
        _write(os.path.join(out, "desktop", "frames", "first-session-1s.json"), {"frame": 1})
        os.makedirs(os.path.join(run_dir, "playability", "1-1", "logs"))
        _write(os.path.join(run_dir, "playability", "1-1", "logs", "bot.json"), {"log": 1})
        # A step that played and crashed before writing its report.
        _write(os.path.join(run_dir, "greybox-playability", "1-2", "out", "mobile",
                            "first-session.json"), {"startedAtMs": 5000})
        # Another step's scratch directory is not playability evidence.
        _write(os.path.join(run_dir, "store-listing", "1-1", "out", "x", "a.json"), {})
        self.state = types.SimpleNamespace(
            run_id=RUN_ID,
            artifacts={"playability-report": refs,
                       "qa-report": [ArtifactRef(id="qa-report", type="qa-report", version=1,
                                                 location=other, checksum=checksum)]},
            steps={"greybox-playability": None, "playability": None, "store-listing": None})

    def test_reports_and_first_session_records_land_in_the_evidence(self):
        copied = summary.collect_playability(self.store, self.state, self.evidence)
        self.assertEqual(sorted(copied), [
            "playability/greybox-playability/1-2/mobile/first-session.json",
            "playability/playability/1-1/desktop/first-session.json",
            "playability/playability/1-1/settings.json",
            "playability/reports/playability-report-v1.json",
            "playability/reports/playability-report-v2.json",
        ])
        with open(os.path.join(self.evidence, "playability", "playability", "1-1", "desktop",
                               "first-session.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"startedAtMs": 6900})
        with open(os.path.join(self.evidence, "playability", "reports",
                               "playability-report-v2.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["step"], "playability")

    def test_a_run_without_playability_copies_nothing(self):
        empty = types.SimpleNamespace(run_id="other-run", artifacts={}, steps={})
        self.assertEqual(summary.collect_playability(self.store, empty, self.evidence), [])
        self.assertFalse(os.path.exists(os.path.join(self.evidence, "playability")))


if __name__ == "__main__":
    unittest.main()
