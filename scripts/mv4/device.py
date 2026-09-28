"""MV-4 criterion A: performance on a real device, or an honest record that there was none.

    python scripts/mv4/device.py --detect --out docs/evidence/mv-4/device
    python scripts/mv4/device.py --instructions --url http://192.168.1.20:4173
    python scripts/mv4/device.py --record capture.json --out docs/evidence/mv-4/device

`--detect` looks for an attached Android device through adb and writes `device-session.json`.
No adb, or no device, is not an error and not a gap to be filled by something else: it is
recorded as UNVERIFIED with the reason, and criterion A stays UNVERIFIED.

`--record` ingests a capture taken on the handset (`--instructions` prints how) and derives the
frame statistics. It refuses a capture that does not carry the device's own identity — model,
Android version, browser version — because `measurement_class: real-device` is a claim about
where the numbers came from, and a claim nothing can check is not evidence. Nothing in this
module can produce a real-device measurement from a desktop browser, by any flag.
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from wgflib import procs  # noqa: E402

# The identity a capture must carry before it may be called a device measurement.
REQUIRED_IDENTITY = ("model", "android", "browser", "screen")
# The thresholds criterion A is decided on (docs/mv-4-plan.md).
MEDIAN_FPS_FLOOR = 30
P95_FRAME_MS_CEILING = 50
WINDOW_FPS_FLOOR = 25

CAPTURE_SNIPPET = """\
// MV-4 on-device capture. Paste into the handset browser's console with the game open and
// PLAYING, let it run for the full 60 s while you keep playing, then copy the JSON it prints.
(() => {
  const deltas = []; let last = 0; const startedAt = performance.now();
  const probe = window.__wgf__ ?? null;
  const frame = (now) => {
    if (last > 0) deltas.push(now - last);
    last = now;
    if (now - startedAt < 60000) requestAnimationFrame(frame);
    else {
      const out = {
        device: { model: "FILL IN: make and model", android: "FILL IN: Android version",
                  browser: navigator.userAgent,
                  screen: innerWidth + "x" + innerHeight + "@" + devicePixelRatio },
        artifact_sha256: "FILL IN: the sha256 the harness printed",
        url: location.href,
        sampled_seconds: 60,
        probe: probe ? { gameId: probe.gameId, platformId: probe.platformId,
                         engine: probe.engine, timeToInteractiveMs: probe.timeToInteractiveMs,
                         framesRendered: probe.framesRendered(), usage: probe.usage() } : null,
        memory: performance.memory ? performance.memory.usedJSHeapSize : null,
        samples_ms: deltas.map((d) => Math.round(d * 100) / 100),
      };
      console.log(JSON.stringify(out));
    }
  };
  requestAnimationFrame(frame);
})();
"""


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def detect():
    """(devices, reason). An empty list with a reason is a result, not a failure."""
    if shutil.which("adb") is None:
        return [], "adb is not installed on this machine, so no handset can be reached from it"
    result = procs.run(["adb", "devices", "-l"], timeout=60)
    if not result.ok:
        return [], f"adb could not be run: {result.tail(5)}"
    devices = []
    for line in (result.stdout or "").splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append({"serial": parts[0], "descriptor": " ".join(parts[2:])})
    if not devices:
        return [], "adb is installed but no device is attached and authorized"
    return devices, None


def percentile(sorted_values, p):
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int((p / 100) * len(sorted_values)))
    return sorted_values[index]


def frame_stats(deltas):
    """Frame statistics from raw frame-to-frame deltas in milliseconds. The same shape the
    browser-side harness derives, so the two are comparable line for line."""
    if not deltas:
        return {"frames": 0}
    ordered = sorted(deltas)
    median = percentile(ordered, 50)
    worst, start, total = None, 0, 0.0
    for end, delta in enumerate(deltas):
        total += delta
        while total > 1000 and start < end:
            worst = (end - start) if worst is None else min(worst, end - start)
            total -= deltas[start]
            start += 1
    return {
        "frames": len(deltas),
        "median_fps": round(1000 / median, 2) if median else 0,
        "mean_fps": round(1000 / (sum(deltas) / len(deltas)), 2),
        "p50_frame_ms": round(median, 2),
        "p95_frame_ms": round(percentile(ordered, 95), 2),
        "p99_frame_ms": round(percentile(ordered, 99), 2),
        "worst_frame_ms": round(ordered[-1], 2),
        "worst_1s_fps": worst if worst is not None else len(deltas),
    }


def verdict(stats):
    """Criterion A, decided on the thresholds fixed in docs/mv-4-plan.md."""
    failures = []
    if stats.get("median_fps", 0) < MEDIAN_FPS_FLOOR:
        failures.append(f"median {stats.get('median_fps')} fps < {MEDIAN_FPS_FLOOR}")
    if stats.get("p95_frame_ms", 0) > P95_FRAME_MS_CEILING:
        failures.append(f"p95 frame time {stats.get('p95_frame_ms')} ms > {P95_FRAME_MS_CEILING}")
    if stats.get("worst_1s_fps", 0) < WINDOW_FPS_FLOOR:
        failures.append(f"worst 1 s window {stats.get('worst_1s_fps')} fps < {WINDOW_FPS_FLOOR}")
    return ("FAIL" if failures else "PASS"), failures


def record(capture_path):
    with open(capture_path, encoding="utf-8") as handle:
        capture = json.load(handle)
    identity = capture.get("device") or {}
    missing = [key for key in REQUIRED_IDENTITY
               if not str(identity.get(key) or "").strip()
               or str(identity.get(key)).startswith("FILL IN")]
    if missing:
        raise SystemExit("refusing to record a device measurement without the device's own "
                         f"identity: {', '.join(missing)} is missing or unfilled")
    samples = [float(value) for value in capture.get("samples_ms") or []]
    if len(samples) < 60:
        raise SystemExit(f"refusing to record {len(samples)} frame samples: a device "
                         "measurement is at least 60 s of continuous play")
    stats = frame_stats(samples)
    status, failures = verdict(stats)
    return {
        "criterion": "A", "title": "Real mobile performance",
        "measurement_class": "real-device", "status": status, "failures": failures,
        "recorded_at": now(), "device": identity,
        "artifact_sha256": capture.get("artifact_sha256"), "url": capture.get("url"),
        "sampled_seconds": capture.get("sampled_seconds"), "probe": capture.get("probe"),
        "memory_bytes": capture.get("memory"), "frame_stats": stats,
        "raw_frame_deltas_ms": samples,
        "thresholds": {"median_fps_floor": MEDIAN_FPS_FLOOR,
                       "p95_frame_ms_ceiling": P95_FRAME_MS_CEILING,
                       "worst_1s_fps_floor": WINDOW_FPS_FLOOR},
    }


def unverified(reason, devices):
    return {
        "criterion": "A", "title": "Real mobile performance",
        "measurement_class": None, "status": "UNVERIFIED", "recorded_at": now(),
        "reason": reason, "devices_detected": devices,
        "note": "No device measurement exists for this run. The desktop proxy recorded by "
                "scripts/mv4/session.py is `emulated-mobile` and does not decide this "
                "criterion; neither does the verify step's policy.device-performance, which "
                "is PASS_MOCK by construction.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--detect", action="store_true")
    parser.add_argument("--record", help="a capture taken on the handset")
    parser.add_argument("--instructions", action="store_true")
    parser.add_argument("--url", help="the URL the handset should open, for --instructions")
    parser.add_argument("--out", help="directory for device-session.json")
    args = parser.parse_args(argv)

    if args.instructions:
        print("1. Serve the measured bundle on a port the handset can reach, from the scratch")
        print("   checkout the session harness made:  pnpm preview --host --port 4173")
        print(f"2. On the handset, open {args.url or 'http://<this machine>:4173'} and play until")
        print("   the game is running normally.")
        print("3. Open the handset's remote console and paste:\n")
        print(CAPTURE_SNIPPET)
        print("4. Fill in the three FILL IN fields, save the printed JSON, and record it with")
        print("   python scripts/mv4/device.py --record capture.json --out <dir>")
        return 0

    if args.record:
        session = record(args.record)
    else:
        devices, reason = detect()
        if devices:
            session = unverified(
                f"{len(devices)} device(s) attached but no capture was recorded; run "
                "--instructions, take one, and pass it to --record", devices)
        else:
            session = unverified(reason, [])

    text = json.dumps(session, indent=2)
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "device-session.json"), "w", encoding="utf-8") as h:
            h.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
