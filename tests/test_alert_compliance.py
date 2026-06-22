#!/usr/bin/env python3
"""
test_alert_compliance.py — guards two engine-hardening fixes (Marvin 2026-06-21):
  • engine.guard_main: an uncaught stage failure fires a Telegram alert + re-raises
    (v2 error-handling: every stage failure pings Marvin). SystemExit passes through.
  • compliance: weight-loss PROMISES ("lose 20 pounds", "melts fat") are RED, while
    research framing ("subjects lost 15 pounds", "weight-loss study") stays compliant.

Pure: no network (alert is monkeypatched). Run:  python3 tests/test_alert_compliance.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine as e          # noqa: E402
import compliance as c      # noqa: E402


def main():
    fails = []

    def check(name, cond):
        print(("ok  " if cond else "FAIL"), name)
        if not cond:
            fails.append(name)

    # ── guard_main: alert + re-raise on failure; SystemExit passes through ──
    captured = {}
    e.alert = lambda m: captured.setdefault("msg", m)   # mock — never hits Telegram
    raised = False
    try:
        e.guard_main("unit", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    except RuntimeError:
        raised = True
    check("guard_main re-raises the original error", raised)
    check("guard_main fired a Telegram alert", "msg" in captured and "FAILED" in captured["msg"])
    se = False
    try:
        e.guard_main("unit", lambda: (_ for _ in ()).throw(SystemExit(0)))
    except SystemExit:
        se = True
    check("guard_main lets SystemExit pass through", se)

    # ── compliance: weight-loss promises are RED ──
    for bad in ["lose 20 pounds in 30 days", "drop 15 lbs", "melts fat fast",
                "torches fat", "blast away fat"]:
        check(f"RED: {bad!r}", bool(c.red_hits(bad)))

    # ── compliance: research framing is NOT over-blocked ──
    for good in ["Research subjects lost an average of 15 pounds",
                 "studied for fat metabolism in preclinical models",
                 "a 2024 GLP-1 weight-loss study", "research on body weight regulation"]:
        check(f"compliant: {good!r}", not c.red_hits(good))

    print("PASS" if not fails else f"FAIL: {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
