#!/usr/bin/env python3
"""
test_bank_cleanup.py — the Source Bank archives used angles + Sunday is bank-first. Guards:
  - mark_used() REMOVES the angle from the servable pool and appends it to _used.jsonl (Marvin
    2026-06-22: 'used items must be removed from the bank'); a fully-spent source file is pruned.
  - unused_angles() no longer returns an archived angle.
  - serve_bank_day() mints from the bank (dry-run), spreads pillars, and returns a count; an empty
    bank returns 0 (so the caller falls back to external).

Pure: a temp SOURCES_DIR. 0 credits, no network.
Run:  python3 tests/test_bank_cleanup.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import source_bank as sb

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if cond:
        PASS += 1
    else:
        FAIL += 1


def _rec(url, angles):
    return {"url": url, "source_id": sb.source_id(url), "platform": "youtube",
            "scraped_at": sb.now_iso(), "full_transcript": "t", "transcript_chars": 1,
            "caption": "", "engagement": {}, "reference": None,
            "angles": [{"id": f"ang-{i+1:03d}", "angle": a, "pillar": "science",
                        "format": "carousel", "used": False, "job_id": None}
                       for i, a in enumerate(angles)]}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        sb.SOURCES_DIR = Path(tmp)
        sb.USED_LOG = sb.SOURCES_DIR / "_used.jsonl"

        rec = sb.save(_rec("https://x.test/a", ["angle one", "angle two"]))
        rec = sb.load("https://x.test/a")
        check("two angles banked", len(sb.unused_angles(rec)) == 2)

        rec = sb.mark_used(rec, "ang-001", "ACME-200")
        check("used angle removed from the pool", [a["id"] for a in rec["angles"]] == ["ang-002"])
        check("unused_angles drops the used one", [a["id"] for a in sb.unused_angles(rec)] == ["ang-002"])
        check("source file still exists (1 angle left)", sb.bank_path(rec["source_id"]).exists())
        log = sb.USED_LOG.read_text().strip().splitlines()
        check("used angle logged to _used.jsonl", len(log) == 1 and json.loads(log[0])["job_id"] == "ACME-200")

        rec = sb.mark_used(rec, "ang-002", "ACME-201")
        check("source file PRUNED once every angle is spent", not sb.bank_path(rec["source_id"]).exists())
        check("both uses logged", len(sb.USED_LOG.read_text().strip().splitlines()) == 2)

        # serve_bank_day: empty bank → 0 (caller falls back to external).
        import research as r
        r.source_bank = sb     # point research at the temp bank
        check("empty bank → serve_bank_day returns 0", r.serve_bank_day(n=4, dry_run=True) == 0)

        # Refill the bank across 2 sources / 2 pillars → dry-run mints up to n, spread.
        rec2 = _rec("https://x.test/b", ["b angle 1"])
        rec2["angles"][0]["pillar"] = "founder"
        sb.save(rec2)
        sb.save(_rec("https://x.test/c", ["c angle 1"]))     # science
        minted = r.serve_bank_day(n=4, dry_run=True)
        check("serve_bank_day mints from a non-empty bank", minted == 2)

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
