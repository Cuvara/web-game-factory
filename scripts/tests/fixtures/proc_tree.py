"""A process tree for test_core_process.py: a child that starts a grandchild, then misbehaves.

    proc_tree.py child <pidfile> <flags> <action>
    proc_tree.py grand <pidfile> <flags>

`flags` is a comma list for the grandchild: `setsid` (detach into its own session, as
Playwright's webServer does), `ignore-term` (ignore SIGTERM, so only SIGKILL ends it).
`action` is what the child does once the grandchild has reported: `exit0`, `exit3`, `sleep`,
`quiet` (print once, then sleep silently), `ignore-term` (ignore SIGTERM itself, then sleep).

Each process appends "<role> <pid>" to <pidfile> once it is set up, so a test knows exactly
which pids to check and that signal dispositions are already in place.
"""

import os
import signal
import subprocess
import sys
import time


def note(pidfile, role):
    with open(pidfile, "a", encoding="utf-8") as handle:
        handle.write(f"{role} {os.getpid()}\n")


def grand(pidfile, flags):
    if "setsid" in flags:
        os.setsid()
    if "ignore-term" in flags:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    note(pidfile, "g")
    time.sleep(120)


def child(pidfile, flags, action):
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "grand", pidfile,
                      ",".join(flags)])
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if os.path.exists(pidfile):
            with open(pidfile, encoding="utf-8") as handle:
                if any(line.startswith("g ") for line in handle):
                    break
        time.sleep(0.01)
    if action == "ignore-term":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    note(pidfile, "c")
    if action == "exit0":
        sys.exit(0)
    if action == "exit3":
        sys.exit(3)
    if action == "quiet":
        print("started", flush=True)
    time.sleep(120)


if __name__ == "__main__":
    role, pidfile = sys.argv[1], sys.argv[2]
    flags = [f for f in (sys.argv[3] if len(sys.argv) > 3 else "").split(",") if f]
    if role == "grand":
        grand(pidfile, flags)
    else:
        child(pidfile, flags, sys.argv[4])
