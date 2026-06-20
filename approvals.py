#!/usr/bin/env python3
"""
approvals.py — STEP B (read side): turn Telegram replies into the publish gate's sign-off.

Polls the DEDICATED engine bot's getUpdates (ENGINE_TELEGRAM_BOT_TOKEN — NEVER OpenClaw's),
parses commands, and applies them to the job folder. The human's eyes in Telegram REPLACE
the M6 visual-QC step, so:

    APPROVE ACME-NNN          → writes qc.json {"passed": true} into the job  ← the M6 sign-off
                                publish.py REQUIRES; status=approved; SOUL §16 +8 (or +3 if it
                                was revised first; +15 streak bonus every 7th clean approval)
    REJECT  ACME-NNN [note]   → status=rejected + note; removes qc.json; §16 −10 (−20 if 2nd
                                rejection same day)
    REVISE  ACME-NNN [note]   → status=revise + note; removes qc.json; no score change
    HOLD    ACME-NNN          → status=held; no score change (SOUL §20)

Idempotent: getUpdates offset is persisted, so re-running never re-applies a command.
0 Higgsfield credits.

Usage:
    python3 approvals.py poll [--no-reply]              # drain pending replies once (launchd job)
    python3 approvals.py apply "APPROVE ACME-015 note"  # apply ONE command directly (manual / test)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import engine as e
import telegram as tg

API = "https://api.telegram.org/bot{token}/{method}"
OFFSET_FILE = e.ENGINE_DIR / "approvals_offset.json"

# Tolerate leading emoji/whitespace (✅ APPROVE …) then VERB ACME-NNN [note].
CMD_RE = re.compile(r"(APPROVE|REJECT|REVISE|HOLD)\s+(ACME-\d+)\s*([^\n]*)", re.IGNORECASE)


# ── trust helpers ────────────────────────────────────────────────────────────
def _was_revised(job_id: str) -> bool:
    st = e.read_status(job_id) or {}
    return any(h.get("event") == "revise" for h in st.get("history", []))


def _reject_is_second_today() -> bool:
    """SOUL §16: 'rejected twice same day' = −20. Track reject timestamps in
    engine_state.rejection_window_48h (pruned to 48h); ≥1 already today ⇒ second."""
    st = e.read_state()
    win = st.get("rejection_window_48h", []) or []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    kept = []
    for ts in win:
        try:
            if datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) >= cutoff:
                kept.append(ts)
        except (ValueError, TypeError):
            continue
    today = e.today_pt()
    second = any(
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        .astimezone(e.PT).strftime("%Y-%m-%d") == today
        for ts in kept
    )
    kept.append(e.now_iso())
    st["rejection_window_48h"] = kept
    e.write_state(st)
    return second


# ── F7 GATE 1 — concept gate (pre-credit) ────────────────────────────────────
def _apply_concept(verb: str, job_id: str, note: str, who: str, reply: bool, job_dir: Path) -> str:
    """A reel at the concept gate (status=awaiting_concept) is PRE-generation: no credit
    spent, no media yet. A/R/E here decides the CONCEPT only and is trust-NEUTRAL — trust
    moves solely at the final gate (SOUL §16), so concept iteration never skews the curve.
    APPROVE writes concept_qc.json, the marker RV3 requires before it may spend a credit."""
    cqc = job_dir / "concept_qc.json"
    if verb == "APPROVE":
        cqc.write_text(json.dumps({"passed": True, "by": who, "at": e.today_pt(),
                                   "via": "telegram-concept-approval", "note": note or None},
                                  ensure_ascii=False, indent=2))
        e.write_status(job_id, "concept_approved", reviewed_at=e.now_iso(),
                       reviewed_by=who, review_note=note or None)
        try:
            n_clips = int(e.load_env("ENGINE_REEL_CLIPS") or 3)
            per = int(e.load_env("ENGINE_REEL_CREDITS_PER_CLIP") or 45)
        except (ValueError, TypeError):
            n_clips, per = 3, 45
        msg = (f"🎬 {job_id} concept approved by {who} — cleared to generate the reel "
               f"(~{n_clips * per} Higgsfield credits, {n_clips} stitched b-roll clips × ~{per}). "
               "Final review still required before publish.")
    elif verb == "REJECT":
        cqc.unlink(missing_ok=True)
        e.write_status(job_id, "concept_rejected", reviewed_at=e.now_iso(),
                       reviewed_by=who, review_note=note or None)
        msg = (f"🛑 {job_id} concept rejected by {who}" + (f" — {note}" if note else "")
               + " — NO credit spent (trust unchanged; the spend never happened).")
    elif verb == "REVISE":
        cqc.unlink(missing_ok=True)
        e.write_status(job_id, "concept_revise", reviewed_at=e.now_iso(),
                       reviewed_by=who, review_note=note or None)
        msg = (f"✏️ {job_id} concept flagged for revision by {who}" + (f" — {note}" if note else "")
               + ". Rewrite the script (RV2), then it re-enters the concept gate. No credit spent.")
    else:  # HOLD
        e.write_status(job_id, "concept_held", reviewed_at=e.now_iso(), reviewed_by=who,
                       review_note=note or "concept held")
        msg = f"⏸ {job_id} concept held by {who} — no credit spent; defers."
    # Record the concept-gate decision (script + generation prompts) in the learning ledger.
    e.record_decision(job_id, verb, "concept", who, note)
    e.log(msg)
    if reply:
        tg.send_text(msg, dry_run=False)
    return msg


# ── apply one command ────────────────────────────────────────────────────────
def apply_command(verb: str, job_id: str, note: str, who: str = "telegram",
                  reply: bool = True) -> str:
    verb = verb.upper()
    note = (note or "").strip()
    job_dir = e.JOBS_DIR / job_id
    if not (job_dir / "brief.json").exists():
        msg = f"⚠️ {job_id}: unknown job (no brief.json) — ignored."
        e.log(msg)
        if reply:
            tg.send_text(msg, dry_run=False)
        return msg
    # F7: route a pre-generation reel's A/R/E to the concept gate (the SAME commands, gated
    # by status). The final-gate branches below are unchanged for every other job.
    if (e.read_status(job_id) or {}).get("status") == "awaiting_concept" \
            and verb in ("APPROVE", "REJECT", "REVISE", "HOLD"):
        return _apply_concept(verb, job_id, note, who, reply, job_dir)
    qc = job_dir / "qc.json"

    if verb == "APPROVE":
        qc.write_text(json.dumps({
            "passed": True, "by": who, "at": e.today_pt(),
            "via": "telegram-approval", "note": note or None,
        }, ensure_ascii=False, indent=2))
        revised = _was_revised(job_id)
        ev = e.apply_trust_event("approved_revised" if revised else "approved",
                                 clean=not revised)
        e.write_status(job_id, "approved", reviewed_at=e.now_iso(),
                       reviewed_by=who, review_note=note or None)
        # Backstop the publish invariant: a job approved out-of-band (e.g. a manual push)
        # can arrive with no slot / no manifest entry, and publish_slot.py selects by slot —
        # so an unslotted approval would silently never post. Heal it here so a sign-off can
        # never strand a post (no-op for the normal produce_daily path, which slots at produce).
        slot = e.ensure_slotted_in_manifest(job_id)
        st = e.read_status(job_id) or {}
        msg = (f"✅ {job_id} approved by {who} — queued for its {slot or st.get('slot') or '?'} PT slot"
               + (f" (trust → {ev['score']})." if ev else "."))
    elif verb == "REJECT":
        qc.unlink(missing_ok=True)
        ev = e.apply_trust_event("rejected_twice" if _reject_is_second_today() else "rejected")
        e.write_status(job_id, "rejected", reviewed_at=e.now_iso(),
                       reviewed_by=who, review_note=note or None)
        msg = (f"❌ {job_id} rejected by {who}"
               + (f" — {note}" if note else "")
               + (f" (trust → {ev['score']})." if ev else "."))
    elif verb == "REVISE":
        qc.unlink(missing_ok=True)
        e.write_status(job_id, "revise", reviewed_at=e.now_iso(),
                       reviewed_by=who, review_note=note or None)
        msg = (f"✏️ {job_id} flagged for revision by {who}"
               + (f" — {note}" if note else "") + ". Re-produce, then it re-enters review.")
    elif verb == "HOLD":
        e.write_status(job_id, "held", reviewed_at=e.now_iso(), reviewed_by=who,
                       review_note=note or "held to next slot")
        msg = f"⏸ {job_id} held by {who} — no score change; defers to its next slot."
    else:
        msg = f"⚠️ {job_id}: unrecognized command {verb!r}."

    # Record the final-gate decision (caption + slide copy + any prompts) in the learning ledger.
    if verb in ("APPROVE", "REJECT", "REVISE", "HOLD"):
        e.record_decision(job_id, verb, "final", who, note)
    e.log(msg)
    if reply:
        tg.send_text(msg, dry_run=False)
    return msg


# ── getUpdates polling ──────────────────────────────────────────────────────────
def _read_offset() -> int:
    o = e.load_json(OFFSET_FILE)
    return int(o.get("offset", 0)) if isinstance(o, dict) else 0


def _write_offset(offset: int) -> None:
    e.ENGINE_DIR.mkdir(parents=True, exist_ok=True)
    OFFSET_FILE.write_text(json.dumps({"offset": offset}))


def cmd_poll(args):
    e.assert_running("approvals-poll")
    token = e.load_env("ENGINE_TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("ERROR: ENGINE_TELEGRAM_BOT_TOKEN not set — create the dedicated bot first "
                 "(see telegram.py header). Use `approvals.py apply` to apply commands manually.")
    requests = tg._requests()
    offset = _read_offset()
    resp = requests.get(API.format(token=token, method="getUpdates"),
                        params={"offset": offset + 1, "timeout": 0, "allowed_updates": '["message"]'},
                        timeout=40, verify=e.tls_verify())
    if resp.status_code != 200:
        sys.exit(f"getUpdates failed {resp.status_code}: {resp.text[:200]}")
    updates = resp.json().get("result", [])
    applied = 0
    max_id = offset
    for u in updates:
        max_id = max(max_id, u.get("update_id", offset))
        msg = u.get("message") or u.get("channel_post") or {}
        text = msg.get("text", "") or msg.get("caption", "")
        frm = msg.get("from", {}) or {}
        who = frm.get("username") or frm.get("first_name") or "telegram"
        m = CMD_RE.search(text)
        if not m:
            continue
        apply_command(m.group(1), m.group(2).upper(), m.group(3), who=who,
                      reply=not args.no_reply)
        applied += 1
    if updates:
        _write_offset(max_id)
    e.log(f"poll: {len(updates)} update(s), {applied} command(s) applied. offset -> {max_id}")


def cmd_apply(args):
    e.assert_running("approvals-apply")
    m = CMD_RE.search(args.command)
    if not m:
        sys.exit("could not parse a command — expected e.g. 'APPROVE ACME-015 [note]'")
    apply_command(m.group(1), m.group(2).upper(), m.group(3), who=args.who,
                  reply=not args.no_reply)


def main():
    ap = argparse.ArgumentParser(prog="approvals",
                                 description="Acme loop STEP B — apply Telegram A/R/E replies (dedicated bot)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("poll", help="Drain pending getUpdates replies once and apply them")
    pp.add_argument("--no-reply", action="store_true", help="Don't post a confirmation back to the group")
    pp.set_defaults(func=cmd_poll)

    pa = sub.add_parser("apply", help="Apply ONE command string directly (manual override / test)")
    pa.add_argument("command", help="e.g. 'APPROVE ACME-015 looks good'")
    pa.add_argument("--who", default="manual", help="Attribution for the action")
    pa.add_argument("--no-reply", action="store_true", help="Don't post a confirmation to the group")
    pa.set_defaults(func=cmd_apply)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
