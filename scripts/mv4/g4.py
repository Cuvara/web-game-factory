"""MV-4 criterion G: the G4 record, with the class of every measurement behind it.

    python scripts/mv4/g4.py --device DIR/device-session.json \\
        --browser DIR/browser-session.json --playtest DIR/playtest-summary.json \\
        --timebox-days 10.5 --planned-days 2.5 --out DIR/g4-evidence.json

Assembles one file per the four kill criteria set at strategy, each carrying its measurement,
the `measurement_class` it was taken at, and its evidence status. It decides nothing: G4 is a
person's decision (`core/lifecycle/stages/prototype-review.md`), and this exists so that the
person deciding it can see which of the four were measured and which were not.

The one rule it enforces is the one MV-4 exists for: a criterion whose only measurement is of a
class that cannot decide it is UNVERIFIED, never PASS. In particular criterion 4 — mobile
performance — is not decided by a desktop proxy, whatever the proxy says.
"""

import argparse
import json
import os
from datetime import datetime, timezone

# Which measurement classes may decide which criterion. Anything else is UNVERIFIED.
DECIDES = {
    "control_not_understood": ("first-time-player",),
    "no_retry_pull": ("first-time-player",),
    "timebox_exceeded": ("run-record",),
    "mobile_fps_below_30": ("real-device",),
}


def read(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def criterion(name, number, statement, measurement, klass, status, detail, evidence):
    return {
        "criterion": number, "id": name, "statement": statement,
        "measurement": measurement, "measurement_class": klass,
        "status": status, "detail": detail, "evidence": evidence,
        "can_this_class_decide_it": klass in DECIDES[name] if klass else False,
    }


def build(device, browser, playtest, timebox_days, planned_days, proxy_note=True):
    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "decided_by": "a person; this file is the record they read, not a decision",
        "criteria": [],
    }

    play = ((playtest or {}).get("criteria") or {})
    for name, number, statement in (
        ("control_not_understood", 1,
         "Fewer than 60% of first-time players understand the control"),
        ("no_retry_pull", 2, "Fewer than 50% retry without being prompted"),
    ):
        entry = play.get(name)
        if not entry or entry.get("status") == "UNVERIFIED":
            out["criteria"].append(criterion(
                name, number, statement, None, entry.get("measurement_class") if entry else None,
                "UNVERIFIED", (entry or {}).get("reason", "no playtest evidence"),
                {"playtest": (playtest or {}).get("participants")}))
        else:
            out["criteria"].append(criterion(
                name, number, statement, entry.get("share"), entry.get("measurement_class"),
                "MET" if entry["status"] == "MET" else "NOT_MET",
                entry.get("calculation"),
                {"numerator": entry.get("numerator"), "denominator": entry.get("denominator")}))

    if timebox_days is None or planned_days is None:
        out["criteria"].append(criterion(
            "timebox_exceeded", 3, "The prototype exceeds the allowed timebox",
            None, None, "UNVERIFIED", "no run record was given", {}))
    else:
        exceeded = planned_days > timebox_days
        out["criteria"].append(criterion(
            "timebox_exceeded", 3, "The prototype exceeds the allowed timebox",
            planned_days, "run-record", "MET" if exceeded else "NOT_MET",
            f"{planned_days} days planned against {timebox_days} allowed",
            {"timebox_days": timebox_days, "planned_days": planned_days}))

    if device and device.get("status") != "UNVERIFIED":
        stats = device.get("frame_stats") or {}
        out["criteria"].append(criterion(
            "mobile_fps_below_30", 4,
            "Mobile performance below 30 FPS on a mid-range mobile browser",
            stats.get("median_fps"), device.get("measurement_class"),
            "MET" if device.get("status") == "FAIL" else "NOT_MET",
            "; ".join(device.get("failures") or []) or "within every threshold",
            {"device": device.get("device"), "frame_stats": stats}))
    else:
        proxies = []
        for session in (browser or {}).get("sessions") or []:
            proxies.append({"project": session.get("project"),
                            "measurement_class": session.get("measurement_class"),
                            "frame_stats": session.get("frame_stats")})
        out["criteria"].append(criterion(
            "mobile_fps_below_30", 4,
            "Mobile performance below 30 FPS on a mid-range mobile browser",
            None, None, "UNVERIFIED",
            (device or {}).get("reason", "no device measurement"),
            {"proxies_recorded_but_not_deciding": proxies} if proxy_note else {}))

    out["summary"] = {
        "measured": [c["id"] for c in out["criteria"] if c["status"] != "UNVERIFIED"],
        "unverified": [c["id"] for c in out["criteria"] if c["status"] == "UNVERIFIED"],
        "met": [c["id"] for c in out["criteria"] if c["status"] == "MET"],
    }
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device")
    parser.add_argument("--browser")
    parser.add_argument("--playtest")
    parser.add_argument("--timebox-days", type=float)
    parser.add_argument("--planned-days", type=float)
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    evidence = build(read(args.device), read(args.browser), read(args.playtest),
                     args.timebox_days, args.planned_days)
    text = json.dumps(evidence, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
