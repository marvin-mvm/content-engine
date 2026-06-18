#!/usr/bin/env python3
"""
publish_slot.py — STEP C: at a posting slot, publish the APPROVED + due jobs.

Driven by launchd at each of the 5 PT slots (08:00/11:00/13:00/16:00/19:00). For the
firing slot it:
  1. drains pending Telegram approvals (approvals.py poll) so late replies land,
  2. finds the manifest jobs assigned to THIS slot with status=approved (qc.json passed),
  3. runs publish.py for each → X + TikTok (IG/Threads/FB auto-skipped; YouTube image-skipped).

SAFETY (all enforced here):
  • STOP flag      → halt, publish nothing.
  • compliance hold (SOUL §16) → halt, publish nothing (owner releases via RESUME PUBLISHING).
  • SUPERVISED BY DEFAULT → publish.py runs in DRY-RUN unless the GO_LIVE flag file exists
    (or --go is passed). Marvin flips one file (output/GO_LIVE) to go from supervised to auto.
  • Never double-post (SOUL §19): a job already `published` is skipped; no approval at this
    slot → held to its next opportunity, nothing posted.

publish.py owns the hard compliance gate + the irreversible Blotato calls; this script only
selects WHICH jobs are due and whether the run is live. 0 Higgsfield credits.

Usage:
    python3 publish_slot.py                 # infer the current slot; supervised (dry-run)
    python3 publish_slot.py --slot 11:00    # force a slot
    python3 publish_slot.py --go            # publish live this run (overrides the flag)
    python3 publish_slot.py --no-poll       # skip the approvals drain
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import engine as e

PY = sys.executable or "python3"
PUBLISH = str(e.WORKSPACE / "publish.py")
APPROVALS = str(e.WORKSPACE / "approvals.py")

PUBLISH_PLATFORMS = "x,tiktok"           # the connected live channels (RUNBOOK §11.5)


def infer_slot(now: datetime | None = None) -> str | None:
    """The latest slot whose time is <= now (PT). None before the first slot."""
    now = now or datetime.now(e.PT)
    hhmm = now.strftime("%H:%M")
    due = [s for s in e.SLOTS if s <= hhmm]
    return due[-1] if due else None


def drain_approvals():
    """Best-effort: apply any pending Telegram replies before publishing."""
    if not e.load_env("ENGINE_TELEGRAM_BOT_TOKEN"):
        e.log("approvals drain skipped — ENGINE_TELEGRAM_BOT_TOKEN not set yet.")
        return
    r = subprocess.run([PY, APPROVALS, "poll"], capture_output=True, text=True)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        e.log("approvals poll failed (non-fatal) — continuing with current statuses.")


def publish_job(job_dir: Path, live: bool, when: str | None) -> bool:
    cmd = [PY, PUBLISH, str(job_dir), "--platforms", PUBLISH_PLATFORMS]
    if when:
        cmd += ["--when", when]
    if live:
        cmd.append("--go")
    e.log(f"publish.py {'--go LIVE' if live else 'DRY-RUN'}: {job_dir.name}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stderr.write(r.stderr)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.returncode != 0:
        e.log(f"{job_dir.name}: publish.py exited {r.returncode} "
              f"({'gate blocked / error' if not live else 'PUBLISH FAILED'}).")
        return False
    return True


def main():
    ap = argparse.ArgumentParser(prog="publish_slot",
                                 description="Acme loop STEP C — publish approved+due jobs at a slot")
    ap.add_argument("--slot", help="Force a slot HH:MM (default: infer from current PT time)")
    ap.add_argument("--date", help="Manifest date YYYY-MM-DD (default today PT)")
    ap.add_argument("--go", action="store_true", help="Publish LIVE this run (overrides the GO_LIVE flag)")
    ap.add_argument("--no-poll", action="store_true", help="Skip draining Telegram approvals first")
    ap.add_argument("--when", help="Schedule time ISO 8601 (default: post now)")
    args = ap.parse_args()

    e.assert_running("publish-slot")
    if e.compliance_hold():
        e.log("COMPLIANCE HOLD active (engine_state) — publishing halted. Owner: RESUME PUBLISHING.")
        sys.exit(0)

    slot = args.slot or infer_slot()
    if not slot:
        e.log("no slot is due yet (before the first 08:00 PT slot) — nothing to do.")
        return
    date = args.date or e.today_pt()
    live = args.go or e.go_live()
    mode = "LIVE (--go)" if live else "SUPERVISED dry-run"
    e.log(f"slot {slot} PT · {date} · mode={mode}")

    if not args.no_poll:
        drain_approvals()

    man = e.read_manifest(date)
    due = [j for j in man["jobs"] if j.get("slot") == slot]
    if not due:
        e.log(f"no jobs assigned to slot {slot} on {date}.")
        return

    published = held = failed = 0
    for j in due:
        jid = j["job_id"]
        st = e.read_status(jid) or {}
        status = st.get("status")
        if status == "published":
            e.log(f"{jid}: already published — skipping (no double-post, SOUL §19).")
            continue
        if status != "approved":
            e.log(f"{jid}: status={status or '—'} (not approved) — HELD, nothing posted.")
            held += 1
            continue
        ok = publish_job(e.JOBS_DIR / jid, live, args.when)
        if ok and live:
            e.write_status(jid, "published", published_at=e.now_iso(), slot=slot)
            published += 1
        elif ok:
            e.log(f"{jid}: dry-run OK — gate passed, WOULD publish (supervised; not posted).")
        else:
            failed += 1

    e.log(f"slot {slot} done: {published} published, {held} held, {failed} failed "
          f"({'LIVE' if live else 'dry-run — set output/GO_LIVE to go live'}).")


if __name__ == "__main__":
    main()
