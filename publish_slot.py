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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import engine as e

PY = sys.executable or "python3"
PUBLISH = str(e.WORKSPACE / "publish.py")
APPROVALS = str(e.WORKSPACE / "approvals.py")

PUBLISH_PLATFORMS = "x,tiktok"           # the connected live channels (RUNBOOK §11.5)
CARRYOVER_HOURS = 48                     # safety-sweep horizon for stranded approvals


def infer_slot(now: datetime | None = None) -> str | None:
    """The latest slot whose time is <= now (PT). None before the first slot."""
    now = now or datetime.now(e.PT)
    hhmm = now.strftime("%H:%M")
    due = [s for s in e.SLOTS if s <= hhmm]
    return due[-1] if due else None


def _reviewed_within(st: dict, cutoff: datetime) -> bool:
    """True if the job's approval timestamp is at/after cutoff (recency bound on the sweep)."""
    rv = st.get("reviewed_at")
    if not rv:
        return False
    try:
        t = datetime.strptime(rv, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        try:
            t = datetime.fromisoformat(rv.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return False
    return t >= cutoff


def _is_due(jslot: str | None, jdate: str | None, firing_slot: str, today: str) -> bool:
    """Is an approved job due to post at `firing_slot` on `today`?
      • carried over from a prior day (slot_date < today) → overdue, post now
      • no slot at all (orphan)                           → post now
      • scheduled for a future day (slot_date > today)    → not yet
      • today: due once its own slot time has arrived (slot <= firing_slot)"""
    if jdate and jdate < today:
        return True
    if not jslot:
        return True
    if jdate and jdate > today:
        return False
    return jslot <= firing_slot


def collect_due(date: str, slot: str) -> list[dict]:
    """Jobs to publish at this slot: the manifest's entries for the slot, PLUS a safety
    sweep of any APPROVED + un-published image job the manifest missed (manual push,
    produced-but-un-manifested, or approved after its own slot/day). Recency-bounded to
    CARRYOVER_HOURS so stale approvals aren't resurrected; reels are excluded (out of the
    auto-publish loop). Dedup by job_id; already-published jobs are skipped in main()."""
    man = e.read_manifest(date)
    due: dict[str, dict] = {j["job_id"]: j for j in man["jobs"] if j.get("slot") == slot}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=CARRYOVER_HOURS)
    for jd in sorted(e.JOBS_DIR.glob("ACME-*")):
        jid = jd.name
        if jid in due:
            continue
        st = e.read_status(jid) or {}
        if st.get("status") != "approved" or not _reviewed_within(st, cutoff):
            continue
        brief = e.load_json(jd / "brief.json") or {}
        if brief.get("type") == "reel":
            continue
        if _is_due(st.get("slot"), st.get("slot_date"), slot, date):
            due[jid] = {"job_id": jid, "slot": st.get("slot") or slot}
            e.log(f"safety-sweep: {jid} is approved + due but absent from the {slot} manifest "
                  f"list — including it so it isn't stranded (no silent drop).")
    return list(due.values())


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

    due = collect_due(date, slot)
    if not due:
        e.log(f"no jobs due at slot {slot} on {date}.")
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
            # publish.py already advances status->published + notifies Telegram. Only stamp
            # the slot here if it somehow didn't, so history isn't double-appended.
            if (e.read_status(jid) or {}).get("status") != "published":
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
