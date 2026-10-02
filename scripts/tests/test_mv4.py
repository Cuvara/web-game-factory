"""The MV-4 evidence harness: what it measures, and what it refuses to call a measurement.

Every test here guards the one rule MV-4 exists for — a weaker class of measurement never
becomes a stronger claim. A desktop proxy is not a device, and the person who built the game is
not a first-time player.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from mv4 import device, g4, playtest  # noqa: E402
from mv4 import session as session_module  # noqa: E402


def capture(**overrides):
    """A well-formed on-device capture: 120 samples at a steady 16.7 ms."""
    base = {
        "device": {"model": "Pixel 6a", "android": "14", "browser": "Chrome/131.0.0.0",
                   "screen": "412x915@2.625"},
        "artifact_sha256": "sha256:" + "ab" * 32,
        "url": "http://192.168.1.20:4173/",
        "sampled_seconds": 60,
        "samples_ms": [16.7] * 120,
    }
    base.update(overrides)
    return base


def write(directory, name, text):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


SHEET = """\
session_id: {sid}
build_sha256: sha256:abc
measurement_class: {klass}
prior_knowledge: {prior}
first_60_seconds:
  understood_control: {understood}
session:
  retried_unprompted: {retried}
"""


class FrameStatistics(unittest.TestCase):
    def test_steady_60_fps(self):
        stats = device.frame_stats([16.7] * 100)
        self.assertAlmostEqual(stats["median_fps"], 59.88, places=1)
        self.assertEqual(stats["frames"], 100)
        self.assertLessEqual(stats["p95_frame_ms"], 17)

    def test_a_stall_shows_in_the_tail_not_in_the_median(self):
        stats = device.frame_stats([16.7] * 99 + [400.0])
        self.assertAlmostEqual(stats["median_fps"], 59.88, places=1)
        self.assertEqual(stats["worst_frame_ms"], 400.0)

    def test_the_worst_one_second_window_is_reported(self):
        # Half the sample at 60 fps, half at 10 fps: the worst window must see the slow half.
        stats = device.frame_stats([16.7] * 60 + [100.0] * 20)
        self.assertLessEqual(stats["worst_1s_fps"], 12)

    def test_no_samples_is_not_a_zero_fps_measurement(self):
        self.assertEqual(device.frame_stats([]), {"frames": 0})


class TheCriterionAVerdict(unittest.TestCase):
    def test_steady_60_fps_passes(self):
        status, failures = device.verdict(device.frame_stats([16.7] * 200))
        self.assertEqual((status, failures), ("PASS", []))

    def test_25_fps_fails_on_the_median(self):
        status, failures = device.verdict(device.frame_stats([40.0] * 200))
        self.assertEqual(status, "FAIL")
        self.assertTrue(any("median" in f for f in failures))

    def test_a_good_median_with_a_bad_tail_still_fails(self):
        status, failures = device.verdict(device.frame_stats([16.7] * 90 + [120.0] * 10))
        self.assertEqual(status, "FAIL")
        self.assertTrue(any("p95" in f for f in failures))


class WithoutADevice(unittest.TestCase):
    def test_detect_reports_a_reason_never_a_failure(self):
        devices, reason = device.detect()
        if devices:
            self.skipTest("a device is attached to this machine")
        self.assertIsInstance(reason, str)
        self.assertTrue(reason)

    def test_the_record_is_unverified_and_says_so(self):
        record = device.unverified("adb is not installed", [])
        self.assertEqual(record["status"], "UNVERIFIED")
        self.assertIsNone(record["measurement_class"])
        self.assertIn("adb", record["reason"])
        self.assertIn("emulated-mobile", record["note"])


class RecordingADeviceMeasurement(unittest.TestCase):
    def ingest(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = write(directory, "capture.json", json.dumps(data))
            return device.record(path)

    def test_a_complete_capture_becomes_a_real_device_measurement(self):
        record = self.ingest(capture())
        self.assertEqual(record["measurement_class"], "real-device")
        self.assertEqual(record["status"], "PASS")
        self.assertEqual(record["device"]["model"], "Pixel 6a")
        self.assertEqual(record["frame_stats"]["frames"], 120)

    def test_an_unfilled_identity_is_refused(self):
        data = capture()
        data["device"]["model"] = "FILL IN: make and model"
        with self.assertRaises(SystemExit) as raised:
            self.ingest(data)
        self.assertIn("identity", str(raised.exception))

    def test_a_missing_identity_field_is_refused(self):
        data = capture()
        del data["device"]["android"]
        with self.assertRaises(SystemExit) as raised:
            self.ingest(data)
        self.assertIn("android", str(raised.exception))

    def test_a_short_sample_is_refused(self):
        with self.assertRaises(SystemExit) as raised:
            self.ingest(capture(samples_ms=[16.7] * 10))
        self.assertIn("60 s", str(raised.exception))

    def test_a_slow_device_is_recorded_as_a_fail_not_dropped(self):
        record = self.ingest(capture(samples_ms=[50.0] * 120))
        self.assertEqual(record["status"], "FAIL")
        self.assertEqual(record["measurement_class"], "real-device")


class ThePlaytestArithmetic(unittest.TestCase):
    def sheets(self, rows):
        directory = tempfile.mkdtemp()
        for index, row in enumerate(rows, 1):
            write(directory, f"s{index}.yaml", SHEET.format(
                sid=f"s{index}", klass=row.get("klass", "first-time-player"),
                prior=row.get("prior", "no"), understood=row.get("understood", "no"),
                retried=row.get("retried", "no")))
        return playtest.summarize(playtest.load(directory))

    def test_a_developer_test_never_enters_a_share(self):
        summary = self.sheets([{"klass": "developer-test", "prior": "yes",
                                "understood": "yes", "retried": "yes"}] * 6)
        self.assertEqual(summary["participants"]["first_time_players"], 0)
        self.assertEqual(summary["participants"]["developer_tests"], 6)
        for entry in summary["criteria"].values():
            self.assertEqual(entry["status"], "UNVERIFIED")
            self.assertIsNone(entry["share"])

    def test_prior_knowledge_wins_over_the_sheets_own_label(self):
        summary = self.sheets([{"klass": "first-time-player", "prior": "yes"}] * 5)
        self.assertEqual(summary["participants"]["developer_tests"], 5)

    def test_fewer_than_five_first_time_players_is_unverified(self):
        summary = self.sheets([{"understood": "yes", "retried": "yes"}] * 4)
        entry = summary["criteria"]["control_not_understood"]
        self.assertEqual(entry["status"], "UNVERIFIED")
        self.assertIn("4 first-time participant", entry["reason"])

    def test_five_first_time_players_produce_both_shares(self):
        summary = self.sheets([{"understood": "yes", "retried": "yes"}] * 3
                              + [{"understood": "no", "retried": "no"}] * 2)
        understood = summary["criteria"]["control_not_understood"]
        self.assertEqual(understood["share"], 0.6)
        self.assertEqual(understood["status"], "NOT_MET")
        retry = summary["criteria"]["no_retry_pull"]
        self.assertEqual(retry["share"], 0.6)
        self.assertEqual(retry["status"], "NOT_MET")

    def test_a_criterion_is_met_when_the_share_is_below_its_threshold(self):
        summary = self.sheets([{"understood": "yes", "retried": "yes"}]
                              + [{"understood": "no", "retried": "no"}] * 4)
        self.assertEqual(summary["criteria"]["control_not_understood"]["status"], "MET")

    def test_a_participant_who_never_reached_game_over_leaves_the_retry_denominator(self):
        summary = self.sheets([{"understood": "yes", "retried": "yes"}] * 3
                              + [{"understood": "yes", "retried": "n/a"}] * 2)
        retry = summary["criteria"]["no_retry_pull"]
        self.assertEqual(retry["denominator"], 3)
        self.assertEqual(retry["excluded_never_reached_game_over"], 2)

    def test_a_mixed_group_counts_only_the_first_time_players(self):
        summary = self.sheets([{"understood": "yes", "retried": "yes"}] * 5
                              + [{"prior": "yes", "understood": "no", "retried": "no"}] * 3)
        self.assertEqual(summary["criteria"]["control_not_understood"]["denominator"], 5)
        self.assertEqual(len(summary["developer_test_sessions"]), 3)


class TheG4Record(unittest.TestCase):
    PROXY = {"sessions": [{"project": "mobile-emulated", "measurement_class": "emulated-mobile",
                           "frame_stats": {"median_fps": 60.0, "p95_frame_ms": 17.0}}]}

    def test_a_desktop_proxy_never_decides_the_mobile_criterion(self):
        record = g4.build(device.unverified("no device", []), self.PROXY, None, 10.5, 2.5)
        fourth = next(c for c in record["criteria"] if c["criterion"] == 4)
        self.assertEqual(fourth["status"], "UNVERIFIED")
        self.assertFalse(fourth["can_this_class_decide_it"])
        # The proxy is retained - it is a real measurement of something - but not as the answer.
        self.assertEqual(fourth["evidence"]["proxies_recorded_but_not_deciding"][0]
                         ["measurement_class"], "emulated-mobile")

    def test_a_device_measurement_decides_it(self):
        measurement = {"status": "PASS", "measurement_class": "real-device",
                       "frame_stats": {"median_fps": 58.0}, "device": {"model": "Pixel 6a"},
                       "failures": []}
        record = g4.build(measurement, self.PROXY, None, 10.5, 2.5)
        fourth = next(c for c in record["criteria"] if c["criterion"] == 4)
        self.assertEqual(fourth["status"], "NOT_MET")
        self.assertTrue(fourth["can_this_class_decide_it"])

    def test_the_timebox_criterion_reads_the_run_record(self):
        record = g4.build(None, None, None, 10.5, 20.0)
        third = next(c for c in record["criteria"] if c["criterion"] == 3)
        self.assertEqual(third["status"], "MET")
        self.assertEqual(third["measurement_class"], "run-record")

    def test_without_a_playtest_both_player_criteria_are_unverified(self):
        record = g4.build(None, None, None, 10.5, 2.5)
        for number in (1, 2):
            entry = next(c for c in record["criteria"] if c["criterion"] == number)
            self.assertEqual(entry["status"], "UNVERIFIED")
        self.assertEqual(sorted(record["summary"]["unverified"]),
                         ["control_not_understood", "mobile_fps_below_30", "no_retry_pull"])

    def test_every_criterion_is_present_even_with_no_evidence_at_all(self):
        record = g4.build(None, None, None, None, None)
        self.assertEqual([c["criterion"] for c in record["criteria"]], [1, 2, 3, 4])


class TheSessionHarness(unittest.TestCase):
    def test_the_build_target_is_the_contracts_own_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "game.config.yaml",
                  "platforms:\n"
                  "  - { id: crazygames, profile: 'crazygames@1.1.0', role: optional }\n"
                  "  - { id: poki, profile: 'poki@1.1.0', role: required }\n")
            self.assertEqual(session_module.target_platform(directory), "poki")

    def test_no_platforms_has_no_target(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "game.config.yaml", "game:\n  id: x\n")
            self.assertIsNone(session_module.target_platform(directory))

    def test_the_browser_side_derives_its_class_from_the_project_never_a_flag(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mv4",
                               "session.spec.ts"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('return project.startsWith("mobile") ? "emulated-mobile"', source)
        self.assertNotIn("MV4_CLASS", source)
        self.assertNotIn('"real-device"', source)


if __name__ == "__main__":
    unittest.main()
