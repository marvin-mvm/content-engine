#!/usr/bin/env python3
"""
schedule.py — STEP C′: hand approved jobs to BLOTATO'S OWN scheduler (native scheduling).

Where publish_slot.py posts the current slot's jobs "now" at each launchd tick (the Mac must
be awake at the slot), this submits each job to Blotato with a FUTURE timestamp so Blotato
posts it itself, unattended. Use it to pre-fill a day's (or a run of days') 5 PT slots from a
start date, or to schedule one job at an explicit time. This is the path to prove the loop
runs unsupervised: queue tomorrow's slots today, then just watch them go out.

    schedule.py fill JOB [JOB ...] --start YYYY-MM-DD [--platforms x] [--go]
        Lay the jobs into consecutive PT slots (08:00/11:00/13:00/16:00/19:00) starting
        --start 08:00, rolling to the next day after 5/day. One Blotato scheduled post each.

    schedule.py at JOB "YYYY-MM-DDTHH:MM" [--platforms x] [--go]
        Schedule ONE job at an explicit PT wall-clock time (Devon picks the moment).

    schedule.py show [--date YYYY-MM-DD]
        Print the schedule manifest written for a date.

HARD TG GATE: a job may be scheduled ONLY if it is status=approved — i.e. a human signed off
via Telegram (approvals.py writes that status + qc.json). Everything goes through TG A/R/E
before Blotato; a not-approved job is REFUSED. --force is the explicit manual/test override
(and is logged). The decision itself is captured in engine's decision ledger.

DRY-RUN BY DEFAULT — prints the Blotato schedule it WOULD submit and runs publish.py's
compliance gate, but queues nothing. --go submits the REAL scheduled posts (IRREVERSIBLE: a
queued post counts and can't be deleted via Blotato). X-only by default (the scheduler test).

RECYCLE: each job is published from its existing media + captions (no regeneration). Note a
PUBLISHED job is status=published, not approved, so re-scheduling it needs --force.
A successfully-scheduled job is marked status=scheduled (with scheduled_for/slot), so the
publish_slot cron treats it as not-approved and never ALSO posts it (no double-post, SOUL §19).
0 Higgsfield credits.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import engine as e

PY = sys.executable or "python3"
PUBLISH = str(e.WORKSPACE / "publish.py")
DEFAULT_PLATFORMS = "x"                   # scheduler test posts to X only


def schedule_path(date: str) -> Path:
    return e.ENGINE_DIR / date / "schedule.json"


# ── slot/time math ────────────────────────────────────────────────────────────
def slot_plan(job_ids: list[str], start_date: str, per_day: int | None = None) -> list[dict]:
    """Lay jobs into consecutive PT slots from start_date 08:00, rolling to the next day
    after the day's slots are used. Returns [{job_id, date, slot, when_pt, when_utc}]."""
    per_day = per_day or len(e.SLOTS)
    base = datetime.strptime(start_date, "%Y-%m-%d").date()
    plan = []
    for i, jid in enumerate(job_ids):
        day = base + timedelta(days=i // per_day)
        slot = e.SLOTS[i % per_day]
        plan.append(_entry(jid, day.strftime("%Y-%m-%d"), slot))
    return plan


def _entry(job_id: str, date: str, slot: str) -> dict:
    hh, mm = (int(x) for x in slot.split(":"))
    pt = datetime.strptime(date, "%Y-%m-%d").replace(hour=hh, minute=mm, tzinfo=e.PT)
    return {
        "job_id": job_id,
        "date": date,
        "slot": slot,
        "when_pt": pt.strftime("%Y-%m-%d %H:%M %Z"),
        "when_utc": pt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ── one scheduled submit (via publish.py, which owns the gate + thread build + upload) ──
def submit(entry: dict, platforms: str, go: bool, force: bool = False) -> dict:
    job_dir = e.JOBS_DIR / entry["job_id"]
    if not (job_dir / "brief.json").exists():
        e.log(f"{entry['job_id']}: no brief.json — cannot schedule. Skipping.")
        return {**entry, "ok": False, "error": "no brief.json"}
    # HARD TG GATE: only a job APPROVED in Telegram (approvals.py sets status=approved + writes
    # qc.json) may be scheduled to Blotato. Everything goes through human A/R/E first. --force
    # is the explicit manual/test override (and is logged).
    status = (e.read_status(entry["job_id"]) or {}).get("status")
    if status != "approved" and not force:
        e.log(f"{entry['job_id']}: status={status or '—'} — NOT approved in Telegram; REFUSED. "
              f"It must be APPROVED via TG first (or pass --force for a manual/test override).")
        return {**entry, "ok": False, "error": f"not approved (status={status or 'none'})"}
    if status != "approved" and force:
        e.log(f"{entry['job_id']}: status={status or '—'} but --force given — scheduling anyway "
              f"(manual override, bypassing the TG gate).")
    cmd = [PY, PUBLISH, str(job_dir), "--platforms", platforms, "--when", entry["when_utc"]]
    if go:
        cmd.append("--go")
    tag = "--go SCHEDULE" if go else "DRY-RUN"
    e.log(f"{tag}: {entry['job_id']} -> {platforms} @ {entry['when_pt']}  ({entry['when_utc']})")
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stderr.write(r.stderr)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if not go:
        return {**entry, "ok": r.returncode == 0, "dry_run": True}
    # --go: read back publish.py's own record (the blotato result) for THIS run.
    res = _last_run_result(job_dir, entry["when_utc"], platforms)
    ok = bool(res and res.get("ok") and res.get("post_id"))
    if ok:
        e.write_status(entry["job_id"], "scheduled", scheduled_for=entry["when_utc"],
                       slot=entry["slot"], slot_date=entry["date"],
                       platforms=[p.strip() for p in platforms.split(",") if p.strip()])
        e.log(f"{entry['job_id']}: SCHEDULED in Blotato (post_id={res.get('post_id')}) "
              f"— status=scheduled; the slot cron will not also post it.")
    else:
        e.log(f"{entry['job_id']}: schedule FAILED (publish.py rc={r.returncode}; "
              f"see output above) — status left unchanged.")
    return {**entry, "ok": ok, "post_id": (res or {}).get("post_id"),
            "blotato_status": (res or {}).get("status")}


def _last_run_result(job_dir: Path, when_utc: str, platforms: str) -> dict | None:
    """Pull the matching platform's post record from publish.py's published_posts.json
    (its last run for this scheduled_for). post_url is None for a scheduled post — success
    is ok=True + a post_id (Blotato's submission id)."""
    doc = e.load_json(job_dir / "published_posts.json")
    if not isinstance(doc, dict):
        return None
    runs = [r for r in doc.get("runs", []) if r.get("scheduled_for") == when_utc]
    if not runs:
        return None
    want = {p.strip() for p in platforms.split(",") if p.strip()}
    for post in runs[-1].get("posts", []):
        if post.get("platform") in want:
            return post
    return None


def write_schedule_manifest(platforms: str, results: list[dict]) -> list[Path]:
    """One schedule.json per date touched (the authoritative record of the day's queue)."""
    plats = [p.strip() for p in platforms.split(",") if p.strip()]
    by_date: dict[str, list[dict]] = {}
    for r in results:
        by_date.setdefault(r["date"], []).append(r)
    paths = []
    for date, rows in by_date.items():
        p = schedule_path(date)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "date": date, "scheduled_at": e.now_iso(), "platforms": plats,
            "posts": sorted(rows, key=lambda r: r["slot"]),
        }, ensure_ascii=False, indent=2))
        paths.append(p)
    return paths


# ── subcommands ────────────────────────────────────────────────────────────────
def cmd_fill(args):
    e.assert_running("schedule-fill")
    plan = slot_plan(args.jobs, args.start)
    e.log(f"schedule fill: {len(plan)} job(s) from {args.start} · {args.platforms} · "
          f"{'LIVE --go' if args.go else 'DRY-RUN'}{' · --force' if args.force else ''}")
    results = [submit(en, args.platforms, args.go, args.force) for en in plan]
    _finish(results, args.platforms, args.go)


def cmd_at(args):
    e.assert_running("schedule-at")
    try:
        pt = datetime.strptime(args.when, "%Y-%m-%dT%H:%M")
    except ValueError:
        sys.exit("could not parse --when; expected PT wall-clock 'YYYY-MM-DDTHH:MM'")
    en = _entry(args.job, pt.strftime("%Y-%m-%d"), pt.strftime("%H:%M"))
    results = [submit(en, args.platforms, args.go, args.force)]
    _finish(results, args.platforms, args.go)


def _finish(results: list[dict], platforms: str, go: bool):
    ok = sum(1 for r in results if r.get("ok"))
    if go:
        paths = write_schedule_manifest(platforms, results)
        for p in paths:
            e.log(f"schedule manifest -> {p}")
        e.log(f"SCHEDULED {ok}/{len(results)} post(s) into Blotato. Verify with "
              f"`blotato.py schedules` and watch them post at their slot.")
    else:
        e.log(f"DRY-RUN: {ok}/{len(results)} would pass the gate. Re-run with --go to queue "
              f"the real scheduled posts.")


def cmd_show(args):
    date = args.date or e.today_pt()
    p = schedule_path(date)
    doc = e.load_json(p)
    if not isinstance(doc, dict):
        print(f"no schedule manifest for {date} ({p})")
        return
    print(json.dumps(doc, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(prog="schedule",
                                 description="Acme STEP C′ — schedule jobs into Blotato (native)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("fill", help="Lay jobs into consecutive PT slots from a start date")
    pf.add_argument("jobs", nargs="+", help="Job ids in slot order, e.g. ACME-015 ACME-016 ...")
    pf.add_argument("--start", required=True, help="First day YYYY-MM-DD (slot 1 = 08:00 PT)")
    pf.add_argument("--platforms", default=DEFAULT_PLATFORMS, help="Comma list (default: x)")
    pf.add_argument("--go", action="store_true", help="Submit the REAL scheduled posts (irreversible)")
    pf.add_argument("--force", action="store_true",
                    help="Override the TG gate — schedule even if not approved in Telegram (manual/test)")
    pf.set_defaults(func=cmd_fill)

    pa = sub.add_parser("at", help="Schedule ONE job at an explicit PT time")
    pa.add_argument("job", help="Job id, e.g. ACME-019")
    pa.add_argument("when", help="PT wall-clock 'YYYY-MM-DDTHH:MM'")
    pa.add_argument("--platforms", default=DEFAULT_PLATFORMS)
    pa.add_argument("--go", action="store_true")
    pa.add_argument("--force", action="store_true",
                    help="Override the TG gate — schedule even if not approved in Telegram (manual/test)")
    pa.set_defaults(func=cmd_at)

    ps = sub.add_parser("show", help="Print the schedule manifest for a date")
    ps.add_argument("--date", help="YYYY-MM-DD (default today PT)")
    ps.set_defaults(func=cmd_show)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
