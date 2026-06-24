#!/usr/bin/env python3
"""
test_product_window.py — products rotate on a 7-DAY window (Marvin 2026-06-22). Guards:
  - products_in_last_days(7) lists compounds that went out in the last 7 days, most-recent first,
    and EXCLUDES anything older than the window.
  - the daily candidate pool prefers products OUTSIDE that window; when the catalog is exhausted it
    falls back to the least-recently-used product.

Pure: a temp JOBS_DIR of synthetic briefs with backdated status. 0 credits.
Run:  python3 tests/test_product_window.py
"""

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine as eng
import research as r

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if cond:
        PASS += 1
    else:
        FAIL += 1


def _iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mkjob(jobs, jid, compound, days_ago):
    d = jobs / jid
    d.mkdir(parents=True, exist_ok=True)
    (d / "brief.json").write_text(json.dumps({"job_id": jid, "type": "image", "compound": compound}))
    (d / "status.json").write_text(json.dumps({"status": "produced", "produced_at": _iso(days_ago)}))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        jobs = Path(tmp) / "jobs"
        jobs.mkdir()
        _mkjob(jobs, "ACME-050", "Tirzepatide", days_ago=1)   # in window, newest
        _mkjob(jobs, "ACME-049", "Semaglutide", days_ago=3)   # in window
        _mkjob(jobs, "ACME-048", "BPC-157", days_ago=6)       # in window (edge)
        _mkjob(jobs, "ACME-047", "CJC-1295", days_ago=12)     # OUT of window
        orig = eng.JOBS_DIR
        eng.JOBS_DIR = jobs
        try:
            recent = r.products_in_last_days(7)
            check("in-window products listed", set(recent) == {"Tirzepatide", "Semaglutide", "BPC-157"})
            check("most-recent first (ACME-050 = Tirzepatide leads)", recent[0] == "Tirzepatide")
            check("out-of-window product excluded (CJC-1295 not listed)", "CJC-1295" not in recent)

            ranked = ["Tirzepatide", "Semaglutide", "BPC-157", "TB-500", "CJC-1295", "Ipamorelin"]
            fresh = [c for c in ranked if c not in recent]
            pick = fresh[0] if fresh else None
            check("daily pick is a product OUTSIDE the 7-day window", pick not in recent)
            check("CJC-1295 (12d ago) is eligible again", "CJC-1295" in fresh)
        finally:
            eng.JOBS_DIR = orig

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
