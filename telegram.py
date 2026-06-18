#!/usr/bin/env python3
"""
telegram.py — STEP B (push side): send a packaged job to the DEDICATED engine review group.

⚠️ DEDICATED BOT ONLY. This uses ENGINE_TELEGRAM_BOT_TOKEN / ENGINE_TELEGRAM_CHAT_ID —
a bot + private group Marvin creates via @BotFather, SEPARATE from OpenClaw's Telegram
bot (which is FROZEN — MIGRATION Part 4). This script NEVER reads TELEGRAM_BOT_TOKEN.

Per job it sends (Devon's Stage 4 / SOUL §20):
  • sendMediaGroup — the carousel/static PNGs (the human sees the actual creative)
  • a review CARD — hook, caption preview, pillar/persona/brand, slot, source
  • the reply contract: "APPROVE / REJECT / REVISE ACME-NNN [note]"

approvals.py reads the replies. 0 Higgsfield credits. No keys / --dry-run → prints the
package instead of sending (so the card is testable without a live bot).

Usage:
    python3 telegram.py push <job_dir> [--dry-run]
    python3 telegram.py push-day [--date YYYY-MM-DD] [--dry-run]   # all produced, un-pushed jobs
    python3 telegram.py send "message text" [--dry-run]            # plain status/alert message
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import engine as e

API = "https://api.telegram.org/bot{token}/{method}"


def _creds():
    token = e.load_env("ENGINE_TELEGRAM_BOT_TOKEN")
    chat = e.load_env("ENGINE_TELEGRAM_CHAT_ID")
    return token, chat


def _requests():
    try:
        import requests  # noqa
        return requests
    except ImportError:
        sys.exit("ERROR: the `requests` package is required for live Telegram calls "
                 "(pip install requests). Use --dry-run to preview without it.")


# ── card composition ─────────────────────────────────────────────────────────
def _hook(job_dir: Path, captions: dict) -> str:
    """Best available one-line hook: carousel slide 1, overlay HOOK_*, or X caption head."""
    cp = e.load_json(job_dir / "copy.json") or {}
    slides = e.load_json(job_dir / "slides.json")
    if isinstance(slides, list) and slides:
        s = slides[0]
        line = " ".join(filter(None, [s.get("HEAD_1"), s.get("HEAD_2_ITALIC"), s.get("HEAD_3")]))
        if line.strip():
            return line.strip()
    line = " ".join(filter(None, [cp.get("HOOK_LINE_1"), cp.get("HOOK_LINE_2_ITALIC"),
                                   cp.get("HOOK_LINE_3")]))
    if line.strip():
        return line.strip()
    x = captions.get("x") or captions.get("instagram") or ""
    return x.split("\n", 1)[0][:120]


def _source(job_dir: Path) -> str:
    r = e.load_json(job_dir / "research.json") or {}
    bits = []
    for k in ("source_url", "source", "url", "outlier_url"):
        if r.get(k):
            bits.append(str(r[k]))
            break
    prov = r.get("provenance") or r
    if isinstance(prov, dict) and prov.get("mode"):
        bits.append(f"mode={prov['mode']}")
    return " · ".join(bits) if bits else "topic discovery"


def build_card(job_dir: Path) -> str:
    job_id = job_dir.name
    brief = e.load_json(job_dir / "brief.json") or {}
    captions = e.load_json(job_dir / "captions.json") or {}
    st = e.read_status(job_id) or {}
    preview = (captions.get("instagram") or captions.get("x") or "").strip()
    if len(preview) > 320:
        preview = preview[:317].rstrip() + "…"
    media_kind = "carousel" if brief.get("image", {}).get("carousel") else "static card"
    lines = [
        f"📋 *{job_id}* · {brief.get('pillar', '?').title()} · Acme {brief.get('brand', '?').title()}",
        f"🎯 Hook: {_hook(job_dir, captions)}",
        "",
        f"_{preview}_",
        "",
        f"• Pillar: {brief.get('pillar', '?')}   • Persona: {brief.get('persona', '?')}",
        f"• Brand: {brief.get('brand', '?')}   • Format: {media_kind}",
        f"• Slot (PT): {st.get('slot', '—')}   • Platforms: {', '.join(sorted(captions))}",
        f"• Source: {_source(job_dir)}",
        "",
        f"Reply: `APPROVE {job_id}`  /  `REJECT {job_id} [note]`  /  `REVISE {job_id} [note]`",
    ]
    return "\n".join(lines)


def media_files(job_dir: Path) -> list[Path]:
    job_id = job_dir.name
    slides = sorted(job_dir.glob(f"{job_id}-slide-*.png"))
    if slides:
        return slides[:10]                       # Telegram media group cap = 10
    single = job_dir / f"{job_id}.png"
    return [single] if single.exists() else []


# ── send ─────────────────────────────────────────────────────────────────────
def send_text(text: str, dry_run: bool) -> bool:
    token, chat = _creds()
    if dry_run or not token or not chat:
        if not dry_run:
            e.log("ENGINE_TELEGRAM_* not set — printing instead of sending.")
        print(text)
        return True
    r = _requests()
    resp = r.post(API.format(token=token, method="sendMessage"),
                  data={"chat_id": chat, "text": text, "parse_mode": "Markdown"}, timeout=30)
    if resp.status_code != 200:
        e.log(f"sendMessage failed {resp.status_code}: {resp.text[:200]}")
        return False
    return True


def send_media_group(files: list[Path], dry_run: bool) -> bool:
    token, chat = _creds()
    if dry_run or not token or not chat:
        print(f"[media group] {len(files)} image(s): {[f.name for f in files]}")
        return True
    if not files:
        return True
    r = _requests()
    media = [{"type": "photo", "media": f"attach://photo{i}"} for i in range(len(files))]
    handles = {f"photo{i}": (f.name, f.open("rb"), "image/png") for i, f in enumerate(files)}
    try:
        resp = r.post(API.format(token=token, method="sendMediaGroup"),
                      data={"chat_id": chat, "media": json.dumps(media)},
                      files=handles, timeout=60)
    finally:
        for _, fh, _ in handles.values():
            fh.close()
    if resp.status_code != 200:
        e.log(f"sendMediaGroup failed {resp.status_code}: {resp.text[:200]}")
        return False
    return True


def push_job(job_dir: Path, dry_run: bool) -> bool:
    job_id = job_dir.name
    if not (job_dir / "captions.json").exists():
        e.log(f"{job_id}: no captions.json — run produce_daily first. Skipping.")
        return False
    files = media_files(job_dir)
    if not files:
        e.log(f"{job_id}: no media PNGs found — skipping.")
        return False
    ok = send_media_group(files, dry_run) and send_text(build_card(job_dir), dry_run)
    if ok and not dry_run:
        st = e.read_status(job_id) or {}
        # only advance produced -> pushed; never clobber an approval already given
        if st.get("status") in (None, "produced", "revise"):
            e.write_status(job_id, "pushed", pushed_at=e.now_iso())
    e.log(f"{job_id}: {'pushed to review group' if ok and not dry_run else 'previewed (dry-run)' if ok else 'push FAILED'}")
    return ok


# ── subcommands ────────────────────────────────────────────────────────────────
def cmd_push(args):
    e.assert_running("telegram-push")
    job_dir = Path(args.job_dir).resolve()
    sys.exit(0 if push_job(job_dir, args.dry_run) else 1)


def cmd_push_day(args):
    e.assert_running("telegram-push-day")
    date = args.date or e.today_pt()
    man = e.read_manifest(date)
    if not man["jobs"]:
        e.log(f"no manifest jobs for {date} — nothing to push.")
        return
    pushed = 0
    for j in man["jobs"]:
        st = e.read_status(j["job_id"]) or {}
        if st.get("status") in ("pushed", "approved", "published"):
            continue                               # already in front of a human / done
        if st.get("status") != "produced":
            continue                               # held/failed -> don't push
        if push_job(e.JOBS_DIR / j["job_id"], args.dry_run):
            pushed += 1
    e.log(f"push-day {date}: pushed {pushed} job(s).")


def cmd_send(args):
    e.assert_running("telegram-send")
    send_text(args.text, args.dry_run)


def main():
    ap = argparse.ArgumentParser(prog="telegram",
                                 description="Acme loop STEP B — push review packages to the DEDICATED engine group")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("push", help="Push ONE job package (media group + review card)")
    pp.add_argument("job_dir")
    pp.add_argument("--dry-run", action="store_true", help="Print the package; send nothing")
    pp.set_defaults(func=cmd_push)

    pd = sub.add_parser("push-day", help="Push all produced, un-pushed jobs in today's manifest")
    pd.add_argument("--date")
    pd.add_argument("--dry-run", action="store_true")
    pd.set_defaults(func=cmd_push_day)

    ps = sub.add_parser("send", help="Send a plain status/alert message")
    ps.add_argument("text")
    ps.add_argument("--dry-run", action="store_true")
    ps.set_defaults(func=cmd_send)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
