"""MV-4's playtest arithmetic: the two kill criteria that are statements about people.

    python scripts/mv4/playtest.py --sessions docs/evidence/mv-4/playtests [--out FILE]

Reads the observation sheets written under `--sessions` (the format is in
docs/mv-4-playtest-protocol.md) and computes:

  criterion 1  control_not_understood  — met when fewer than 60% understood the control
  criterion 2  no_retry_pull           — met when fewer than 50% retried unprompted

Three refusals are the point of this script, and none of them can be turned off:

* A session whose `measurement_class` is `developer-test`, or whose `prior_knowledge` is yes,
  never enters either share. It is counted and reported separately.
* A share computed from fewer than MINIMUM first-time participants is not reported at all. The
  criterion is UNVERIFIED and the reason says how many were seen.
* A participant who never reached game-over is excluded from the retry share, and the
  exclusion is reported rather than folded into the denominator.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from wgflib import yamllite  # noqa: E402

# Below this many first-time participants, a percentage is noise presented as a measurement.
MINIMUM = 5
UNDERSTOOD_THRESHOLD = 0.60
RETRY_THRESHOLD = 0.50


def _yes(value):
    return str(value).strip().lower() in ("yes", "true")


def load(directory):
    sessions = []
    for name in sorted(os.listdir(directory)) if os.path.isdir(directory) else []:
        if not name.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(directory, name)
        sheet = yamllite.load_file(path)
        sheet["_file"] = os.path.relpath(path)
        sessions.append(sheet)
    return sessions


def classify(sheet):
    """first-time or developer-test. A `yes` to prior knowledge decides it, whatever the
    sheet's own measurement_class says: the answer about the person wins."""
    if _yes(sheet.get("prior_knowledge")):
        return "developer-test"
    if str(sheet.get("measurement_class") or "").strip() == "developer-test":
        return "developer-test"
    return "first-time-player"


def summarize(sessions):
    first_time = [s for s in sessions if classify(s) == "first-time-player"]
    developer = [s for s in sessions if classify(s) == "developer-test"]

    understood = [s for s in first_time
                  if _yes((s.get("first_60_seconds") or {}).get("understood_control"))]
    reached_over = [s for s in first_time
                    if str((s.get("session") or {}).get("retried_unprompted") or "").strip()
                    .lower() in ("yes", "no")]
    retried = [s for s in reached_over
               if _yes((s.get("session") or {}).get("retried_unprompted"))]

    result = {
        "participants": {
            "total_sessions": len(sessions),
            "first_time_players": len(first_time),
            "developer_tests": len(developer),
            "minimum_for_a_share": MINIMUM,
        },
        "developer_test_sessions": [
            {"session_id": s.get("session_id"), "file": s.get("_file"),
             "counted_towards_criteria": False} for s in developer],
        "criteria": {},
    }

    if len(first_time) < MINIMUM:
        reason = (f"{len(first_time)} first-time participant(s); {MINIMUM} are the minimum for "
                  f"a share. Developer tests ({len(developer)}) are excluded by construction.")
        for cid, name in (("1", "control_not_understood"), ("2", "no_retry_pull")):
            result["criteria"][name] = {
                "criterion": cid, "status": "UNVERIFIED", "measurement_class": None,
                "share": None, "reason": reason,
            }
        return result

    understood_share = len(understood) / len(first_time)
    result["criteria"]["control_not_understood"] = {
        "criterion": "1",
        "status": "MET" if understood_share < UNDERSTOOD_THRESHOLD else "NOT_MET",
        "measurement_class": "first-time-player",
        "share": round(understood_share, 4),
        "threshold": UNDERSTOOD_THRESHOLD,
        "numerator": len(understood), "denominator": len(first_time),
        "calculation": "participants who performed and repeated the primary action within 60 s "
                       "without being told, over all first-time participants",
    }
    if not reached_over:
        result["criteria"]["no_retry_pull"] = {
            "criterion": "2", "status": "UNVERIFIED", "measurement_class": "first-time-player",
            "share": None,
            "reason": "no first-time participant reached game-over, so no retry was possible",
        }
        return result
    retry_share = len(retried) / len(reached_over)
    result["criteria"]["no_retry_pull"] = {
        "criterion": "2",
        "status": "MET" if retry_share < RETRY_THRESHOLD else "NOT_MET",
        "measurement_class": "first-time-player",
        "share": round(retry_share, 4),
        "threshold": RETRY_THRESHOLD,
        "numerator": len(retried), "denominator": len(reached_over),
        "excluded_never_reached_game_over": len(first_time) - len(reached_over),
        "calculation": "participants who started another run unprompted within 30 s of the "
                       "first game-over, over the first-time participants who reached it",
    }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sessions", required=True, help="directory of observation sheets")
    parser.add_argument("--out", help="write the summary here as JSON")
    parser.add_argument("--summarize", action="store_true", help="accepted for readability")
    args = parser.parse_args(argv)

    summary = summarize(load(args.sessions))
    text = json.dumps(summary, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
