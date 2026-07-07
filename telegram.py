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

LINK-DROPS (v2 Stage 1, ANY group member — Marvin 2026-06-21): approvals.py's same getUpdates
poll also captures any content URL (IG/TikTok/YouTube/X/Reddit/FB/Threads) posted in the group
by ANYONE, queueing it (drops.py) for the Trending pillar — 0 cost at drop time; the morning run
consumes one. For the bot to SEE non-command messages from members, **group privacy must be OFF**:
in @BotFather → /setprivacy → select this bot → **Disable** (or make the bot a group admin).
Otherwise Telegram hides everything except commands/replies/@mentions and drops are never seen.
No new env var is needed — drops are read from the SAME ENGINE_TELEGRAM_CHAT_ID group as approvals.

Usage:
    python3 telegram.py push <job_dir> [--dry-run]
    python3 telegram.py push-day [--date YYYY-MM-DD] [--dry-run]   # all produced, un-pushed jobs
    python3 telegram.py send "message text" [--dry-run]            # plain status/alert message
"""
from __future__ import annotations

import argparse
import json
import sys
import time
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


def _md_esc(s: str) -> str:
    """Escape legacy-Markdown entity chars in free text so a stray '_'/'*'/'`'/'[' in a hook
    label can't open an entity that never closes (Telegram 400s the WHOLE card)."""
    for ch in ("\\", "_", "*", "`", "["):
        s = s.replace(ch, "\\" + ch)
    return s


def _md_url(url: str) -> str:
    """Render a URL as a Markdown-safe inline link. A bare URL with '_' (an Instagram
    /p/DXwuiB_AdKu/ slug or a '?img_index=' query) opens a legacy-Markdown italic that never
    closes and 400s the entire review card; inside the () href those chars are never parsed, so
    the link stays visible + tappable and the card always sends (Marvin 2026-06-22)."""
    return f"[{_md_esc(url)}]({url})"


def build_card(job_dir: Path) -> str:
    job_id = job_dir.name
    brief = e.load_json(job_dir / "brief.json") or {}
    captions = e.load_json(job_dir / "captions.json") or {}
    st = e.read_status(job_id) or {}
    ref = _reference(job_dir, brief)
    # Collapse the caption to ONE physical line — a multi-line string wrapped in _italic_ makes the
    # entity span line breaks, which _fit_caption's whole-line trim could split (Marvin 2026-06-23).
    preview = " ".join(_cap_text(captions, "instagram", "x").split())
    if len(preview) > 320:
        preview = preview[:317].rstrip() + "…"
    media_kind = ("reel" if brief.get("type") == "reel"
                  else "carousel" if brief.get("image", {}).get("carousel") else "static card")
    # Every card must show a post time. Prefer the slot stamped on the job's status, but fall back
    # to the pillar's canonical PT slot (e.PILLAR_SLOT) — reels are pushed outside the image
    # packaging path and never get a slot stamped, which left "Slot (PT):" blank (Marvin 2026-06-21).
    slot = st.get("slot") or e.PILLAR_SLOT.get(brief.get("pillar", ""), "—")
    # Show the FULL post time — weekday + date + PT slot — so a reviewer seeing several days'
    # posts at once knows exactly when each one goes out (Marvin 2026-06-21: "right date and time").
    when = slot
    sd = st.get("slot_date")
    if sd:
        try:
            from datetime import datetime as _dt
            when = f"{_dt.strptime(sd, '%Y-%m-%d'):%a %b %d} · {slot}"
        except (ValueError, TypeError):
            when = f"{sd} · {slot}"
    persona = brief.get("persona", "?")
    target = {"P1": "P1 · The Optimizer", "P3": "P3 · The Curious Newcomer",
              "P2": "P2 · Health (future)"}.get(persona, persona)
    lines = [
        f"📋 *{job_id}* · {brief.get('pillar', '?').title()} · Acme {brief.get('brand', '?').title()}",
        f"🎯 Hook: {_hook(job_dir, captions)}",
        "",
        f"_{_md_esc(preview)}_",
        "",
        f"• Pillar: {brief.get('pillar', '?')}   • Target: {target}",
        f"• Brand: {brief.get('brand', '?')}   • Format: {media_kind}",
        f"• When (PT): {when}   • Platforms: {', '.join(sorted(captions))}",
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
            lines.append(f"   • {_md_esc(label)} — {_md_url(url)}" if label else f"   • {_md_url(url)}")
        if ref.get("selection_rationale"):
            lines.append(f"   ↳ {ref['selection_rationale']}")
    elif ref.get("selection_rationale"):
        lines.append(f"📎 Why: {ref['selection_rationale']}")
    if brief.get("dedup_note"):                         # surface a duplication auto-revise
        lines.append(f"♻️ Dedup: {brief['dedup_note']}")
    lines += [
        "",
        "Reply — tap a command to copy:",
        f"`APPROVE {job_id}`",
        f"`REJECT {job_id} [note]`",
        f"`REVISE {job_id} [note]`",
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
    script_text = " ".join((beats.get("full_text") or brief.get("script")
                             or "(no script yet — run script.py)").split())
    if len(script_text) > 600:
        script_text = script_text[:597].rstrip() + "…"
    est = beats.get("est_seconds")
    lines = [
        "⚠️ *Video not generated yet* (for approval — script & concept only)",
        "",
        f"🎬 *{job_id}* · CONCEPT REVIEW (reel) · {brief.get('pillar', '?').title()} · Acme {brief.get('brand', '?').title()}",
        f"🎯 Hook: {beats.get('hook') or cover_hook or '—'}",
        "",
        f"📝 Script{f' (~{est}s)' if est else ''}:",
        f"_{_md_esc(script_text)}_",
        "",
        f"• Pillar: {brief.get('pillar', '?')}   • Persona: {brief.get('persona', '?')}",
        f"• Brand: {brief.get('brand', '?')}   • Cover: {Path(cover.get('template', '')).stem or '—'}",
        f"• Platforms: {', '.join(brief.get('platforms', [])) or '—'}",
        f"• Source: {_source(job_dir, brief)}",
    ]
    # List EVERY source link (mirrors build_card): a topic-discovery reel carries N study URLs in
    # ref.sources but no single ref.url, so the old single-line "Reference" left the "5 source links"
    # count with nothing behind it (Marvin 2026-06-22: "all source links must be included").
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
            lines.append(f"   • {_md_esc(label)} — {_md_url(url)}" if label else f"   • {_md_url(url)}")
        if ref.get("selection_rationale"):
            lines.append(f"   ↳ {ref['selection_rationale']}")
    elif ref.get("selection_rationale"):
        lines.append(f"📎 Why: {ref['selection_rationale']}")
    if brief.get("dedup_note"):                         # surface a duplication auto-revise
        lines.append(f"♻️ Dedup: {brief['dedup_note']}")
    try:
        n_clips = int(e.load_env("ENGINE_REEL_CLIPS") or 3)
        per = int(e.load_env("ENGINE_REEL_CREDITS_PER_CLIP") or 45)
    except (ValueError, TypeError):
        n_clips, per = 3, 45
    lines += [
        "",
        f"⚠️ *APPROVE spends ~{n_clips * per} Higgsfield credits* ({n_clips} stitched b-roll clips "
        f"× ~{per} each). REJECT / REVISE cost nothing.",
        "Reply — tap a command to copy:",
        f"`APPROVE {job_id}`",
        f"`REJECT {job_id} [note]`",
        f"`REVISE {job_id} [note]`",
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
    # Never let a URL in the body expand into a web-page preview card — the preview image/blurb
    # bloats the review message and buries the card (Marvin 2026-06-23). Links stay clickable.
    resp = r.post(API.format(token=token, method="sendMessage"),
                  data={"chat_id": chat, "text": text, "parse_mode": "Markdown",
                        "link_preview_options": json.dumps({"is_disabled": True}),
                        "disable_web_page_preview": "true"},
                  timeout=30, verify=e.tls_verify())
    if resp.status_code != 200:
        e.log(f"sendMessage failed {resp.status_code}: {resp.text[:200]}")
        return False
    return True


TG_CAPTION_LIMIT = 1024  # Telegram photo/video/album caption hard cap


def _fit_caption(text: str):
    """Return (caption, parse_mode) for the review card riding ON the media. Telegram caps captions
    at 1024 chars. Under the cap we keep the card whole. When a long card overflows (e.g. a reel
    caption with several source links — Marvin 2026-06-23), we must NOT (a) drop the APPROVE/REJECT
    commands or (b) show literal Markdown. So: keep the full reply contract (the "Reply — tap…" line
    + the three A/R/E command lines) intact, and trim only the BODY — dropping WHOLE lines from its
    end until it fits. Whole-line trims keep every line's Markdown entities (_italic_, *bold*,
    [label](url)) balanced, so Markdown stays valid and parse_mode is preserved."""
    if len(text) <= TG_CAPTION_LIMIT:
        return text, "Markdown"
    lines = text.splitlines()
    cut = next((i for i, ln in enumerate(lines) if ln.startswith("Reply — tap")), None)
    if cut is None:                                  # no contract marker → keep the last 4 lines
        cut = max(0, len(lines) - 4)
    body, footer = lines[:cut], lines[cut:]
    foot = "\n".join(footer)
    budget = TG_CAPTION_LIMIT - len(foot) - 2        # leave room for the "\n…" elision marker
    while body and len("\n".join(body)) > budget:    # drop whole body lines until it fits
        body.pop()
    head = "\n".join(body).rstrip()
    return (f"{head}\n…\n{foot}" if head else foot), "Markdown"


def send_photo(path: Path, caption: str, dry_run: bool) -> bool:
    """One image + the review card as its caption — a SINGLE message so text and image stay together."""
    token, chat = _creds()
    cap, mode = _fit_caption(caption)
    if dry_run or not token or not chat:
        print(f"[photo] {path.name}\n{cap}\n")
        return True
    r = _requests()
    data = {"chat_id": chat, "caption": cap}
    if mode:
        data["parse_mode"] = mode
    with path.open("rb") as fh:
        resp = r.post(API.format(token=token, method="sendPhoto"),
                      data=data, files={"photo": (path.name, fh, "image/png")},
                      timeout=60, verify=e.tls_verify())
    if resp.status_code != 200:
        e.log(f"sendPhoto failed {resp.status_code}: {resp.text[:200]}")
        return False
    return True


def send_media_group(files: list[Path], caption: str, dry_run: bool) -> bool:
    """Carousel/album with the review card as the caption on the FIRST slide, so the card rides WITH
    the images as ONE message (no detached text card drifting away from its creative). A single image
    goes via sendPhoto — Telegram rejects 1-item albums."""
    if not files:
        return True
    if len(files) == 1:
        return send_photo(files[0], caption, dry_run)
    token, chat = _creds()
    cap, mode = _fit_caption(caption)
    if dry_run or not token or not chat:
        print(f"[media group] {len(files)} image(s): {[f.name for f in files]}\n{cap}\n")
        return True
    r = _requests()
    media = []
    for i in range(len(files)):
        item = {"type": "photo", "media": f"attach://photo{i}"}
        if i == 0:                                   # caption attaches to the album via its first item
            item["caption"] = cap
            if mode:
                item["parse_mode"] = mode
        media.append(item)
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


def send_video(path: Path, caption: str, dry_run: bool) -> bool:
    """The reel video + the review card as its caption — a SINGLE message."""
    token, chat = _creds()
    cap, mode = _fit_caption(caption)
    if dry_run or not token or not chat:
        print(f"[video] {path.name}\n{cap}\n")
        return True
    r = _requests()
    data = {"chat_id": chat, "caption": cap}
    if mode:
        data["parse_mode"] = mode
    with path.open("rb") as fh:
        resp = r.post(API.format(token=token, method="sendVideo"),
                      data=data, files={"video": (path.name, fh, "video/mp4")},
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
    card = build_card(job_dir)
    # The review card rides ON the media as a caption — ONE message, so the text never drifts away
    # from its image/carousel/reel (Marvin 2026-06-23: "messages and images not on each other").
    if brief.get("type") == "reel":
        vid = reel_final(job_dir)
        if not vid:
            e.log(f"{job_id}: no rendered reel (captioned.mp4 / {job_id}-final.mp4) — run RV4 first. Skipping.")
            return False
        ok = send_video(vid, card, dry_run)
    else:
        files = media_files(job_dir)
        if not files:
            e.log(f"{job_id}: no media PNGs found — skipping.")
            return False
        ok = send_media_group(files, card, dry_run)
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
    gap = max(0, getattr(args, "gap", 0) or 0)
    resend = getattr(args, "resend", False)
    # Normally only freshly 'produced' jobs push. --resend ALSO re-sends cards already in front of a
    # human ('pushed'/'revise') so a formatting fix can replace the jumbled originals; approved/
    # published jobs are never re-pushed.
    sendable = {"produced"} | ({"pushed", "revise"} if resend else set())
    pushed = 0
    for j in man["jobs"]:
        st = e.read_status(j["job_id"]) or {}
        if st.get("status") not in sendable:
            continue                               # held/failed/approved/published -> don't push
        if pushed and gap:                         # space sends so Telegram can't re-order the batch
            time.sleep(gap)
        if push_job(e.JOBS_DIR / j["job_id"], args.dry_run):
            pushed += 1
    e.log(f"push-day {date}: pushed {pushed} job(s)"
          + (f" [resend, {gap}s gap]" if resend else f" [{gap}s gap]" if gap else "") + ".")


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
    pd.add_argument("--gap", type=int, default=0,
                    help="Seconds to wait between sends so Telegram can't jumble the batch order (e.g. 15)")
    pd.add_argument("--resend", action="store_true",
                    help="Also re-send jobs already 'pushed'/'revise' (replace jumbled/mis-themed originals)")
    pd.set_defaults(func=cmd_push_day)

    ps = sub.add_parser("send", help="Send a plain status/alert message")
    ps.add_argument("text")
    ps.add_argument("--dry-run", action="store_true")
    ps.set_defaults(func=cmd_send)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    e.guard_main("review-push", main)
