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
def _cap_text(captions: dict, *platforms: str) -> str:
    """First non-empty caption text across `platforms`, tolerating BOTH the plain-string and
    the {text, thread} dict shapes a captions.json entry can take (publish.py's caption_for
    normalizes the same way)."""
    for p in platforms:
        v = captions.get(p)
        if isinstance(v, dict):
            v = v.get("text", "")
        if v:
            return v
    return ""


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
    return _cap_text(captions, "x", "instagram").split("\n", 1)[0][:120]


def _reference(job_dir: Path, brief: dict) -> dict:
    """F3 provenance block. Canonical home is brief.reference (it travels IN the brief,
    schema'd); fall back to research.json for jobs produced before the reference block."""
    ref = brief.get("reference")
    if not isinstance(ref, dict) or not ref:
        r = e.load_json(job_dir / "research.json") or {}
        ref = r.get("reference") if isinstance(r.get("reference"), dict) else {}
    return ref or {}


def _source(job_dir: Path, brief: dict) -> str:
    """Short discovery-source label for the card."""
    ref = _reference(job_dir, brief)
    plat = ref.get("platform")
    n_src = len([s for s in (ref.get("sources") or []) if s.get("url")])
    if plat == "topic-discovery":
        return f"topic discovery · {n_src} source link{'s' if n_src != 1 else ''}" if n_src else "topic discovery"
    if plat:
        fmt = ref.get("cloned_format")
        return f"{plat}" + (f" · cloned {fmt}" if fmt else "")
    # Legacy research.json shapes (jobs produced before the reference block).
    r = e.load_json(job_dir / "research.json") or {}
    for k in ("source_url", "source", "url", "outlier_url"):
        if r.get(k):
            return str(r[k])
    return "topic discovery"


def build_card(job_dir: Path) -> str:
    job_id = job_dir.name
    brief = e.load_json(job_dir / "brief.json") or {}
    captions = e.load_json(job_dir / "captions.json") or {}
    st = e.read_status(job_id) or {}
    ref = _reference(job_dir, brief)
    preview = _cap_text(captions, "instagram", "x").strip()
    if len(preview) > 320:
        preview = preview[:317].rstrip() + "…"
    media_kind = ("reel" if brief.get("type") == "reel"
                  else "carousel" if brief.get("image", {}).get("carousel") else "static card")
    lines = [
        f"📋 *{job_id}* · {brief.get('pillar', '?').title()} · Acme {brief.get('brand', '?').title()}",
        f"🎯 Hook: {_hook(job_dir, captions)}",
        "",
        f"_{preview}_",
        "",
        f"• Pillar: {brief.get('pillar', '?')}   • Persona: {brief.get('persona', '?')}",
        f"• Brand: {brief.get('brand', '?')}   • Format: {media_kind}",
        f"• Slot (PT): {st.get('slot', '—')}   • Platforms: {', '.join(sorted(captions))}",
        f"• Source: {_source(job_dir, brief)}",
    ]
    # Reference provenance — EVERY brief carries source link(s) now (Task 3): Mode B = the cloned
    # post; Mode A = the news articles behind the topic. NOT part of the post — review only.
    src_links = []
    if ref.get("url"):
        src_links.append((ref.get("description") or ref.get("platform") or "source", ref["url"]))
    for s in (ref.get("sources") or []):
        u = s.get("url")
        if u and not any(u == existing for _, existing in src_links):
            src_links.append((s.get("title") or s.get("source") or s.get("platform") or "source", u))
    if src_links:
        lines.append(f"📎 Source{'s' if len(src_links) > 1 else ''} ({len(src_links)}):")
        for title, url in src_links[:5]:
            label = (title[:58] + "…") if len(title) > 58 else title
            lines.append(f"   • {label} — {url}" if label else f"   • {url}")
        if ref.get("selection_rationale"):
            lines.append(f"   ↳ {ref['selection_rationale']}")
    elif ref.get("selection_rationale"):
        lines.append(f"📎 Why: {ref['selection_rationale']}")
    lines += [
        "",
        f"Reply: `APPROVE {job_id}`  /  `REJECT {job_id} [note]`  /  `REVISE {job_id} [note]`",
    ]
    return "\n".join(lines)


def build_concept_card(job_dir: Path) -> str:
    """F7 GATE 1 — the CONCEPT review card sent BEFORE any Higgsfield credit. Shows the
    spoken script + the branded-cover hook + the F3 reference, and states plainly that
    APPROVE is the one action that spends a credit (Seedance b-roll). Same A/R/E reply
    contract as the final card, but approvals.py routes it to the concept gate by status."""
    job_id = job_dir.name
    brief = e.load_json(job_dir / "brief.json") or {}
    beats = e.load_json(job_dir / "script.json") or {}
    ref = _reference(job_dir, brief)
    cover = brief.get("cover", {}) or {}
    cover_hook = " ".join(filter(None, [cover.get("HOOK_LINE_1"), cover.get("HOOK_LINE_2_ITALIC"),
                                        cover.get("HOOK_LINE_3")])).strip()
    script_text = (beats.get("full_text") or brief.get("script") or "(no script yet — run script.py)").strip()
    if len(script_text) > 600:
        script_text = script_text[:597].rstrip() + "…"
    est = beats.get("est_seconds")
    lines = [
        f"🎬 *{job_id}* · CONCEPT REVIEW (reel) · {brief.get('pillar', '?').title()} · Acme {brief.get('brand', '?').title()}",
        f"🎯 Hook: {beats.get('hook') or cover_hook or '—'}",
        "",
        f"📝 Script{f' (~{est}s)' if est else ''}:",
        f"_{script_text}_",
        "",
        f"• Pillar: {brief.get('pillar', '?')}   • Persona: {brief.get('persona', '?')}",
        f"• Brand: {brief.get('brand', '?')}   • Cover: {Path(cover.get('template', '')).stem or '—'}",
        f"• Platforms: {', '.join(brief.get('platforms', [])) or '—'}",
        f"• Source: {_source(job_dir, brief)}",
    ]
    if ref.get("url"):
        lines.append(f"📎 Reference: {ref.get('description') or ref.get('platform') or 'source'}")
        lines.append(f"   {ref['url']}")
    elif ref.get("selection_rationale"):
        lines.append(f"📎 Why: {ref['selection_rationale']}")
    try:
        n_clips = int(e.load_env("ENGINE_REEL_CLIPS") or 3)
        per = int(e.load_env("ENGINE_REEL_CREDITS_PER_CLIP") or 45)
    except (ValueError, TypeError):
        n_clips, per = 3, 45
    lines += [
        "",
        f"⚠️ *APPROVE spends ~{n_clips * per} Higgsfield credits* ({n_clips} stitched b-roll clips "
        f"× ~{per} each). REJECT / REVISE cost nothing.",
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
                  data={"chat_id": chat, "text": text, "parse_mode": "Markdown"},
                  timeout=30, verify=e.tls_verify())
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
                      files=handles, timeout=60, verify=e.tls_verify())
    finally:
        for _, fh, _ in handles.values():
            fh.close()
    if resp.status_code != 200:
        e.log(f"sendMediaGroup failed {resp.status_code}: {resp.text[:200]}")
        return False
    return True


def send_video(path: Path, dry_run: bool) -> bool:
    token, chat = _creds()
    if dry_run or not token or not chat:
        print(f"[video] {path.name}")
        return True
    r = _requests()
    with path.open("rb") as fh:
        resp = r.post(API.format(token=token, method="sendVideo"),
                      data={"chat_id": chat}, files={"video": (path.name, fh, "video/mp4")},
                      timeout=180, verify=e.tls_verify())
    if resp.status_code != 200:
        e.log(f"sendVideo failed {resp.status_code}: {resp.text[:200]}")
        return False
    return True


def reel_final(job_dir: Path) -> Path | None:
    """The rendered reel to review at GATE 2: the embedded final, else the captioned clip."""
    for name in (f"{job_dir.name}-final.mp4", "captioned.mp4"):
        p = job_dir / name
        if p.exists():
            return p
    return None


def push_job(job_dir: Path, dry_run: bool) -> bool:
    """F4 final review (GATE 2). Reels send the captioned VIDEO; images send the PNG group."""
    job_id = job_dir.name
    if not (job_dir / "captions.json").exists():
        e.log(f"{job_id}: no captions.json — run produce_daily first. Skipping.")
        return False
    brief = e.load_json(job_dir / "brief.json") or {}
    if brief.get("type") == "reel":
        vid = reel_final(job_dir)
        if not vid:
            e.log(f"{job_id}: no rendered reel (captioned.mp4 / {job_id}-final.mp4) — run RV4 first. Skipping.")
            return False
        ok = send_video(vid, dry_run) and send_text(build_card(job_dir), dry_run)
    else:
        files = media_files(job_dir)
        if not files:
            e.log(f"{job_id}: no media PNGs found — skipping.")
            return False
        ok = send_media_group(files, dry_run) and send_text(build_card(job_dir), dry_run)
    if ok and not dry_run:
        st = e.read_status(job_id) or {}
        # advance to pushed from a pre-review state (incl. a concept-approved reel); never
        # clobber an approval already given.
        if st.get("status") in (None, "produced", "revise", "concept_approved"):
            e.write_status(job_id, "pushed", pushed_at=e.now_iso())
    e.log(f"{job_id}: {'pushed to review group' if ok and not dry_run else 'previewed (dry-run)' if ok else 'push FAILED'}")
    return ok


def push_concept(job_dir: Path, dry_run: bool) -> bool:
    """F7 GATE 1 — push a reel's CONCEPT (script + reference) for approval BEFORE generation.
    Text-only (no media yet — the visual is reviewed at GATE 2). Advances the job to
    'awaiting_concept' so approvals.py treats the next A/R/E as a concept decision."""
    job_id = job_dir.name
    brief = e.load_json(job_dir / "brief.json") or {}
    if brief.get("type") != "reel":
        e.log(f"{job_id}: concept gate is reels-only (type={brief.get('type')!r}) — skipping.")
        return False
    if not brief.get("script"):
        e.log(f"{job_id}: no brief.script yet — run script.py (RV2) before GATE 1. Skipping.")
        return False
    ok = send_text(build_concept_card(job_dir), dry_run)
    if ok and not dry_run:
        st = e.read_status(job_id) or {}
        if st.get("status") in (None, "produced", "concept_revise", "revise"):
            e.write_status(job_id, "awaiting_concept", concept_pushed_at=e.now_iso())
    e.log(f"{job_id}: {'concept pushed to review group' if ok and not dry_run else 'concept previewed (dry-run)' if ok else 'concept push FAILED'}")
    return ok


# ── subcommands ────────────────────────────────────────────────────────────────
def cmd_push(args):
    e.assert_running("telegram-push")
    job_dir = Path(args.job_dir).resolve()
    sys.exit(0 if push_job(job_dir, args.dry_run) else 1)


def cmd_push_concept(args):
    e.assert_running("telegram-push-concept")
    job_dir = Path(args.job_dir).resolve()
    sys.exit(0 if push_concept(job_dir, args.dry_run) else 1)


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

    pcn = sub.add_parser("push-concept", help="F7 GATE 1: push a reel CONCEPT (script + reference) for approval BEFORE any credit")
    pcn.add_argument("job_dir")
    pcn.add_argument("--dry-run", action="store_true", help="Print the concept card; send nothing")
    pcn.set_defaults(func=cmd_push_concept)

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
