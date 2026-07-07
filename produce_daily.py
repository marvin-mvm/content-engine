#!/usr/bin/env python3
"""
produce_daily.py — STEP A of the autonomous loop: PRODUCE (morning run, 0 credits).

Orchestrates the proven 0-credit core into review-ready job folders:

    research.py run --carousel   →  brief.json (+ copy.json, slides.json)   [topic/outlier discovery]
    post.py <job>                →  slide/static PNGs                        [render]
    copywriter.py --platform x|tiktok|instagram  →  captions.json                  [THE BRIDGE]

THE BRIDGE (why this script exists): research.py writes copy.json (ONE caption), but
publish.py's gate needs captions.json (one UNIQUE caption per platform) AND the RUO line
on EVERY Labs caption. copywriter.py only auto-appends RUO for --product-feature posts, so
without this step every non-product Labs post would be blocked at publish. We generate a
shaped caption per platform, force RUO on all Labs captions, strip hashtags + fit X to
≤280 (the publish gate's hard X rule), and write captions.json the gate will accept.

SCOPE: images/carousels run end-to-end here (0 credits). REELS (F7) are also handled, but as
a STATUS-DRIVEN state machine that puts GATE 1 (concept approval) BEFORE the only credit
spend (RV3): PHASE A = script -> captions -> push concept; [human approves]; PHASE B = RV3
b-roll (dry-run unless REELS_LIVE + --generate-reels) -> RV4 captions -> push final (GATE 2).

Each job ends pending review (status=produced / awaiting_concept / pushed); NO qc.json yet —
that is written only on Telegram APPROVE (approvals.py). Spend-capped + STOP-flag honored.

Subcommands:
    run [--posts N] [--no-carousel] [--dry-run] [--force] [--generate-reels]   full morning produce
    reel <job_dir> [--generate] [--dry-run-push] [--force]  advance ONE reel through its phases
    captions <job_dir> [--force]                            (re)build captions.json only (the bridge)
    enqueue <job_id ...>                                    add existing jobs to today's manifest
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import engine as e
try:
    import dedup            # reel-script duplication gate (Marvin 2026-06-22) — fail-open
except Exception:
    dedup = None

PY = sys.executable or "python3"
RESEARCH = str(e.WORKSPACE / "research.py")
POST = str(e.WORKSPACE / "post.py")
COPY = str(e.WORKSPACE / "copywriter.py")
# F7 reel pipeline tools (script -> GATE 1 -> video -> captions -> GATE 2).
SCRIPT = str(e.WORKSPACE / "script.py")
REEL_VIDEO = str(e.WORKSPACE / "reel_video.py")
REEL_CAPTIONS = str(e.WORKSPACE / "reel_captions.py")
TELEGRAM = str(e.WORKSPACE / "telegram.py")

# captions.json always carries the live publish channels (x, tiktok) + instagram; any
# extra platform named in the brief (threads/facebook) is appended. Canonical order.
CAPTION_PLATFORMS = ["x", "tiktok", "instagram"]
HASHTAG_CAP = {"tiktok": 5, "instagram": 30, "threads": 0, "facebook": 3}


# ── helpers ──────────────────────────────────────────────────────────────────
def strip_hashtags(text: str) -> str:
    """Remove all #hashtag tokens (X must have 0; defensive everywhere)."""
    return re.sub(r"\s*#[A-Za-z0-9_]+", "", text or "").strip()


def fit_x(text: str, reserve: int = 0) -> str:
    """Trim an X caption to <= X_LIMIT-reserve chars on a clean boundary (keeps RUO room)."""
    limit = e.X_LIMIT - reserve
    text = strip_hashtags(text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in (". ", "! ", "? ", "; ", ", ", " "):
        idx = cut.rfind(sep)
        if idx > limit * 0.55:
            return cut[: idx + 1].rstrip()
    return cut.rstrip()[: limit - 1] + "…"


def append_hashtags(text: str, hashtags: list[str], cap: int) -> str:
    """Append up to `cap` clean hashtags not already present in the caption body."""
    if cap <= 0 or not hashtags:
        return text
    seen = {h.lower() for h in re.findall(r"#[A-Za-z0-9_]+", text or "")}
    add = []
    for h in hashtags:
        h = h.strip()
        if not h:
            continue
        if not h.startswith("#"):
            h = "#" + re.sub(r"\s+", "", h)
        if h.lower() in seen:
            continue
        add.append(h)
        seen.add(h.lower())
        if len(add) >= cap:
            break
    return (text.rstrip() + "\n\n" + " ".join(add)) if add else text


def call_copy(topic: str, brand: str, platform: str, brief: dict) -> dict | None:
    """One copywriter.py call (M2) → its JSON. Spend-capped. None on failure/cap."""
    if not e.spend("copy", 1):
        return None
    args = [PY, COPY, topic, "--brand", brand, "--platform", platform]
    if brief.get("product_feature"):
        args += ["--product-feature"]
        if brief.get("compound"):
            args += ["--compound", brief["compound"]]
        if brief.get("class"):
            args += ["--class", brief["class"]]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        e.log(f"copywriter.py failed ({platform}): {(r.stderr or r.stdout)[-200:]}")
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", r.stdout, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        e.log(f"copywriter.py returned non-JSON for {platform}")
        return None


def build_x_thread(slides: list, brief: dict, link: str | None) -> dict | None:
    """Turn a carousel's slides.json into an X THREAD — one tweet per slide (headline + body,
    hashtags stripped, fitted to <=280). The lead tweet is the hook (slide 1); RUO + the COA
    link fold into the LAST tweet (the CTA slide), room reserved. Mirrors the guide's
    "each carousel slide → a tweet" (CONTENT_ENGINE_GUIDE §3.4 / SOUL §6). The publish gate
    re-checks every tweet (<=280, 0 hashtags, RUO somewhere in the thread)."""
    tweets = []
    for s in slides:
        if not isinstance(s, dict):
            continue
        head = " ".join(x for x in (s.get("HEAD_1"), s.get("HEAD_2_ITALIC"), s.get("HEAD_3")) if x).strip()
        body = (s.get("BODY") or "").strip()
        raw = (f"{head} — {body}" if (head and body) else (head or body)).strip(" —")
        t = fit_x(strip_hashtags(raw))
        if t:
            tweets.append(t)
    if not tweets:
        return None
    # X = no COA link, no hashtags; last tweet ends body → WAITLIST CTA → RUO (disclaimer last; Marvin 2026-06-29).
    reserve = (len(e.RUO_SENTENCE) + 2 if e.is_labs(brief) else 0) + (len(e.WAITLIST_CTA) + 2)
    last = fit_x(strip_hashtags(tweets[-1]), reserve=reserve)
    last = e.ensure_ruo(last, brief)
    tweets[-1] = e.ensure_waitlist(last)
    return {"text": tweets[0], "thread": tweets[1:]}


def _reel_dedup(job_dir: Path, job_id: str) -> None:
    """Duplication gate on the reel SCRIPT (and overlay hook), run after RV2 writes brief.script
    and BEFORE the concept is pushed to GATE 1 — so we never spend a review slot (or, later, a
    Higgsfield credit) on a reel that just repeats a recent post. Surgically swaps only the
    near-duplicate part; follow-ups pass. Writes draft.md. Fail-open (Marvin 2026-06-22)."""
    if dedup is None or (e.load_env("ENGINE_DEDUP", "1") or "1") == "0":
        return
    brief = e.load_json(job_dir / "brief.json") or {}
    if not brief.get("script"):
        return
    ov = brief.get("overlay") or {}
    hook = " ".join(str(ov.get(k, "")).strip() for k in
                    ("EYEBROW", "HOOK_LINE_1", "HOOK_LINE_2_ITALIC", "HOOK_LINE_3") if ov.get(k)).strip()
    draft = {"job_id": job_id, "pillar": brief.get("pillar"), "compound": brief.get("compound"),
             "topic": brief.get("topic"), "script": brief.get("script"), "hook": hook}
    try:
        verdict = dedup.check_draft(draft, dedup.recent_corpus(exclude_job=job_id))
    except Exception as ex:                              # a gate hiccup must never break produce
        e.log(f"{job_id}: reel dedup skipped (non-fatal): {ex}")
        return
    _, changed = dedup.revise(draft, verdict)
    by_el = {p["element"]: (p.get("revised") or "").strip() for p in verdict.get("parts", [])}
    if "script" in changed and by_el.get("script"):
        brief["script"] = by_el["script"]
    if "hook" in changed and by_el.get("hook") and ov:
        l1, it, l3 = dedup.split_headline(by_el["hook"])
        ov.update(HOOK_LINE_1=l1, HOOK_LINE_2_ITALIC=it, HOOK_LINE_3=l3)
        brief["overlay"] = ov
    summary = dedup.summarize(verdict, changed)
    if changed:
        brief["dedup_note"] = summary
        (job_dir / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2))
    e.log(f"{job_id}: reel dedup — {summary}")
    (job_dir / "draft.md").write_text(
        f"# {job_id} — reel draft\n\n- pillar: {brief.get('pillar')} · compound: {brief.get('compound') or '—'}\n"
        f"- topic: {brief.get('topic', '')}\n\n## Hook\n{hook or '—'}\n\n## Script\n{brief.get('script', '')}\n"
        + (f"\n## Duplication gate\n{summary}\n" if summary else ""))


def build_captions(job_dir: Path, force: bool = False) -> dict | None:
    """THE BRIDGE: write captions.json (per-platform, RUO-enforced, X-fitted) for a job.
    Returns the captions dict, or None if the brief is missing / nothing could be built."""
    brief = e.load_json(job_dir / "brief.json")
    if not isinstance(brief, dict):
        e.log(f"{job_dir.name}: no/invalid brief.json — cannot build captions")
        return None
    is_reel = brief.get("type") == "reel"

    out_path = job_dir / "captions.json"
    if out_path.exists() and not force:
        e.log(f"{job_dir.name}: captions.json exists (use --force to rebuild)")
        return e.load_json(out_path)

    brand = brief.get("brand", "labs")
    topic = brief.get("topic", "")
    # Reels carry their fixed video distribution (tiktok/x/youtube) — no instagram default,
    # no carousel/X-thread. Images use the live-channel default set + any extra brief platform.
    if is_reel:
        platforms = list(brief.get("platforms", ["tiktok", "x", "youtube"]))
    else:
        platforms = list(CAPTION_PLATFORMS)
        for p in brief.get("platforms", []):
            if p not in platforms:
                platforms.append(p)

    # Product/COA link (live SKU only) → folded into every caption so the card's "VIEW COA"
    # CTA resolves to a real page on every platform. None for non-live compounds.
    link = brief.get("link")

    # A carousel becomes a slide-per-tweet THREAD on X (the guide's preferred treatment).
    slides = e.load_json(job_dir / "slides.json")
    is_carousel = bool(brief.get("image", {}).get("carousel")) and isinstance(slides, list) and len(slides) > 1

    captions: dict = {}
    warnings: list[str] = []
    for p in platforms:
        if p == "x" and is_carousel:
            xt = build_x_thread(slides, brief, link)
            if xt:
                captions["x"] = xt
                for i, post in enumerate([xt["text"], *xt["thread"]]):
                    for hit in e.red_hits(post):
                        fix = e.say_instead(hit)
                        warnings.append(f"[x] tweet {i+1} RED claim {hit!r} — REVISE" + (f" → {fix}" if fix else ""))
                    if len(post) > e.X_LIMIT or "#" in post:
                        warnings.append(f"[x] tweet {i+1} shape off ({len(post)} chars / hashtags)")
                continue
            # thread build failed → fall through to a single X caption
        cp = call_copy(topic, brand, p, brief)
        if not cp:
            warnings.append(f"no caption generated for {p}")
            continue
        text = (cp.get("caption") or "").strip()
        hashtags = cp.get("hashtags") or []
        if p == "x":
            # X: 0 hashtags, <= 280 incl. RUO (Labs) + the WAITLIST CTA. No COA link (Marvin
            # 2026-06-28: dropped the "COA: <url>" line). Order: body → waitlist CTA → RUO (last).
            reserve = (len(e.RUO_SENTENCE) + 2) if e.is_labs(brief) else 0
            reserve += len(e.WAITLIST_CTA) + 2
            text = fit_x(text, reserve=reserve)
            text = e.ensure_ruo(text, brief)
            text = e.ensure_waitlist(text)
        else:
            # Footer order (Marvin 2026-06-29): body → HASHTAGS → waitlist CTA → RUO (disclaimer
            # ALWAYS last). No COA link line. Append hashtags FIRST, then ensure_waitlist re-pins
            # the CTA + RUO at the very end so the disclaimer stays the final line.
            text = e.ensure_ruo(text, brief)
            text = append_hashtags(text, hashtags, HASHTAG_CAP.get(p, 0))
            text = e.ensure_waitlist(text)
        # Pre-flight the publish gate's own checks so we surface problems at produce time.
        for hit in e.red_hits(text):
            fix = e.say_instead(hit)
            warnings.append(f"[{p}] RED claim {hit!r} — human must REVISE" + (f" → {fix}" if fix else ""))
        yl = e.yellow_hits(text)
        if yl:
            warnings.append(f"[{p}] efficacy verb(s) {yl} need research-subject framing ('may'/'research suggests')")
        if p == "x" and (len(text) > e.X_LIMIT or "#" in text):
            warnings.append(f"[{p}] X shape off ({len(text)} chars / hashtags) — check")
        captions[p] = text

    if not captions:
        e.log(f"{job_dir.name}: produced ZERO captions (copywriter.py failures / cap) — not writing")
        return None
    out_path.write_text(json.dumps(captions, ensure_ascii=False, indent=2))
    e.log(f"{job_dir.name}: captions.json -> {sorted(captions)}"
          + (f"  ⚠ {len(warnings)} warning(s)" if warnings else ""))
    for w in warnings:
        e.log(f"  ⚠ {job_dir.name} {w}")
    return captions


def render_job(job_dir: Path) -> bool:
    """Render the job's PNG(s) via post.py (0 credits). Skips if media already present."""
    job_id = job_dir.name
    brief = e.load_json(job_dir / "brief.json") or {}
    carousel = brief.get("image", {}).get("carousel")
    existing = list(job_dir.glob(f"{job_id}-slide-*.png")) if carousel \
        else [job_dir / f"{job_id}.png"]
    if all(p.exists() for p in existing) and existing:
        e.log(f"{job_id}: media already rendered — skipping post.py")
        return True
    r = subprocess.run([PY, POST, str(job_dir)], capture_output=True, text=True)
    if r.returncode != 0:
        e.log(f"{job_id}: post.py FAILED: {(r.stderr or r.stdout)[-300:]}")
        return False
    return True


def retheme_to_slot(job_dir: Path, slot: str | None, brand: str) -> None:
    """Force this image job's template to the dark/light mode its ASSIGNED slot needs (content.md:
    morning 08:00/11:00 → light, else dark) BEFORE it renders. Fixes the same-pillar-day case where
    the assembly-time pillar theme is wrong — e.g. a trending post slotted into 08:00 must be light,
    not dark. Swaps only the -dark/-light suffix; the two templates share one token set, so the render
    is otherwise identical. No-op for reels / unthemed templates / missing briefs."""
    brief = e.load_json(job_dir / "brief.json")
    if not isinstance(brief, dict) or brief.get("type") == "reel":
        return
    img = brief.get("image")
    if not isinstance(img, dict):
        return
    tpl = img.get("template") or ""
    want = e.theme_for_slot(slot, brand)
    other = "dark" if want == "light" else "light"
    needle = f"-{other}.html"
    if not tpl.endswith(needle):                  # already correct mode (or not a -dark/-light template)
        return
    img["template"] = tpl[: -len(needle)] + f"-{want}.html"
    (job_dir / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2))
    e.log(f"{job_dir.name}: re-themed → {want} for slot {slot} ({Path(img['template']).name})")


def package_job(job_dir: Path, pillar: str, brand: str, slot: str | None,
                force: bool = False) -> bool:
    """Render + build captions + set status for one job. Returns True if review-ready."""
    job_id = job_dir.name
    retheme_to_slot(job_dir, slot, brand)         # theme follows the ASSIGNED slot, not the pillar
    ok_render = render_job(job_dir)
    caps = build_captions(job_dir, force=force) if ok_render else None
    if ok_render and caps:
        e.write_status(job_id, "produced", pillar=pillar, brand=brand,
                       slot=slot, slot_date=e.today_pt(),
                       produced_at=e.now_iso(),
                       caption_platforms=sorted(caps))
        return True
    e.write_status(job_id, "failed", pillar=pillar, brand=brand, slot=slot,
                   slot_date=e.today_pt(),
                   note="render failed" if not ok_render else "no captions built")
    return False


# ── F7 reel pipeline (status-driven; GATE 1 always precedes the RV3 credit spend) ──
def _sub(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stderr.write(r.stderr)
    return r


def handle_reel(job_dir: Path, *, generate: bool = False, dry_run_push: bool = False,
                force: bool = False) -> str | None:
    """Advance ONE type=reel job through its phases, driven by status:

      PHASE A (pre-credit): RV2 script.py -> captions.json -> push CONCEPT (GATE 1) -> awaiting_concept
      [human concept-approves in Telegram -> concept_qc.json, status concept_approved]
      PHASE B (post-approval): RV3 reel_video.py (the credit spend, dry-run unless REELS_LIVE
        + generate) -> RV4 reel_captions.py -> captions.json -> push FINAL (GATE 2) -> pushed

    The RV3 spend is ALWAYS behind GATE 1 (concept_qc) AND the engine 6 credits/day cap, and only
    actually fires when both `generate` and engine.reels_live() are set — otherwise RV3 runs
    DRY-RUN (0 credits) and the reel parks at concept_approved until generation is enabled."""
    job_id = job_dir.name
    brief = e.load_json(job_dir / "brief.json") or {}
    if brief.get("type") != "reel":
        return None
    pillar, brand = brief.get("pillar", ""), brief.get("brand", "labs")
    st = (e.read_status(job_id) or {}).get("status")
    concept_ok = (e.load_json(job_dir / "concept_qc.json") or {}).get("passed") is True

    # Waiting / terminal states the loop must not disturb.
    if st in ("awaiting_concept", "pushed", "approved", "published",
              "concept_rejected", "concept_held", "rejected", "held", "failed"):
        e.log(f"{job_id}: reel waiting at status={st} — no action")
        return st

    # ── PHASE B — concept approved → generate → caption → final review ──
    if concept_ok or st in ("concept_approved", "revise"):
        # A FINAL-gate REVISE must RE-RENDER, not silently re-push the stale artifact — the reel
        # REVISE no-op bug (Marvin 2026-06-21, ACME-021): without this, handle_reel finds the
        # leftover <job>-final.mp4, skips RV4, and pushes the SAME video back. Drop the stale
        # render (and any captioned.mp4) so RV4 below regenerates the reel from the current brief.
        if st == "revise":
            (job_dir / f"{job_id}-final.mp4").unlink(missing_ok=True)
            (job_dir / "captioned.mp4").unlink(missing_ok=True)
            e.log(f"{job_id}: REVISE → cleared stale render; re-rendering from current brief")
        side = e.load_json(job_dir / "reel_video.json") or {}
        if not brief.get("video"):
            if side.get("status") == "pending":            # async Seedance job in flight → poll
                e.log(f"{job_id}: polling the pending Seedance job…")
                _sub([PY, REEL_VIDEO, str(job_dir), "--poll"])
            else:
                cmd = [PY, REEL_VIDEO, str(job_dir)]
                if generate and e.reels_live():
                    cmd.append("--go")
                    e.log(f"{job_id}: RV3 — REELS_LIVE on → may spend up to {e._caps()['reel']} REAL Higgsfield "
                          f"credits/day (~45 per stitched clip; gated by cap + live wallet + concept)")
                else:
                    e.log(f"{job_id}: concept approved → RV3 DRY-RUN (REELS_LIVE off / no --generate); 0 credits")
                _sub(cmd)
            brief = e.load_json(job_dir / "brief.json") or {}
            if not brief.get("video"):                     # dry-run / still rendering → resume next run
                e.log(f"{job_id}: no b-roll yet (dry-run or pending) — will resume next run")
                return st
        final = job_dir / f"{job_id}-final.mp4"
        if not final.exists() and not (job_dir / "captioned.mp4").exists():
            e.log(f"{job_id}: RV4 — TTS voiceover + synced captions + render")
            if _sub([PY, REEL_CAPTIONS, str(job_dir)]).returncode != 0:
                e.log(f"{job_id}: RV4 failed (TTS/render run on the real machine) — stopping")
                return st
        build_captions(job_dir, force=force)
        _sub([PY, TELEGRAM, "push", str(job_dir)] + (["--dry-run"] if dry_run_push else []))
        if not dry_run_push:
            e.write_status(job_id, "pushed", pillar=pillar, brand=brand,
                           slot=e.PILLAR_SLOT.get(pillar), slot_date=e.today_pt(),
                           pushed_at=e.now_iso())
        e.log(f"{job_id}: reel rendered → GATE 2 (final review)")
        return "pushed"

    # ── PHASE A — pre-concept: script + captions + concept review (GATE 1) ──
    if not brief.get("script"):
        e.log(f"{job_id}: RV2 — writing the spoken script")
        if _sub([PY, SCRIPT, str(job_dir)]).returncode != 0:
            e.log(f"{job_id}: RV2 blocked (likely a RED concept) — marking failed, no credit at risk")
            e.write_status(job_id, "failed", pillar=pillar, brand=brand, note="script compliance-blocked")
            return "failed"
    _reel_dedup(job_dir, job_id)   # duplication gate on the script BEFORE the concept burns a GATE-1 slot
    build_captions(job_dir, force=force)
    if _sub([PY, TELEGRAM, "push-concept", str(job_dir)] + (["--dry-run"] if dry_run_push else [])).returncode != 0:
        e.log(f"{job_id}: concept push failed")
        return st
    if not dry_run_push:
        e.write_status(job_id, "awaiting_concept", pillar=pillar, brand=brand,
                       slot=e.PILLAR_SLOT.get(pillar), slot_date=e.today_pt(),
                       concept_pushed_at=e.now_iso())
    e.log(f"{job_id}: concept → GATE 1 (awaiting approval; NO credit spent)")
    return "awaiting_concept"


def reproduce_revised_images() -> list[str]:
    """Re-produce every status=revise IMAGE job — the image REVISE re-render path (Marvin
    2026-06-21; mirrors the reel revise fix). For each: regenerate the copy from the reviewer's
    note (research.py recopy), drop the stale PNGs so it actually re-renders, then re-render +
    re-caption + re-push for review. Without this a revised image was orphaned (could never publish
    — publish needs status=approved — and nothing regenerated it). 0 Higgsfield credits."""
    done = []
    for jd in sorted(e.JOBS_DIR.glob("ACME-*")):
        brief = e.load_json(jd / "brief.json")
        if not isinstance(brief, dict) or brief.get("type") != "image":
            continue
        st = e.read_status(jd.name) or {}
        if st.get("status") != "revise":
            continue
        job_id = jd.name
        note = st.get("review_note") or ""
        pillar, brand = brief.get("pillar", ""), brief.get("brand", "labs")
        slot = st.get("slot") or e.PILLAR_SLOT.get(pillar)
        e.log(f"{job_id}: REVISE → re-producing image (note: {note[:80]!r})")
        if _sub([PY, RESEARCH, "recopy", str(jd)] + (["--note", note] if note else [])).returncode != 0:
            e.log(f"{job_id}: recopy failed — leaving at revise for next run")
            continue
        for png in list(jd.glob(f"{job_id}-slide-*.png")) + [jd / f"{job_id}.png"]:
            png.unlink(missing_ok=True)                 # stale render would otherwise be reused
        if not package_job(jd, pillar, brand, slot):
            e.log(f"{job_id}: re-render failed — leaving for next run")
            continue
        _sub([PY, TELEGRAM, "push", str(jd)])
        e.write_status(job_id, "pushed", pillar=pillar, brand=brand, slot=slot,
                       slot_date=e.today_pt(), pushed_at=e.now_iso())
        done.append(job_id)
    return done


def sweep_reels(*, generate: bool = False, dry_run_push: bool = False, force: bool = False) -> list[str]:
    """Advance every reel job that isn't in a waiting/terminal state (the loop's reel pass)."""
    advanced = []
    for jd in sorted(e.JOBS_DIR.glob("ACME-*")):
        brief = e.load_json(jd / "brief.json")
        if not isinstance(brief, dict) or brief.get("type") != "reel":
            continue
        st = (e.read_status(jd.name) or {}).get("status")
        concept_ok = (e.load_json(jd / "concept_qc.json") or {}).get("passed") is True
        if st in ("awaiting_concept", "pushed", "approved", "published",
                  "concept_rejected", "concept_held", "rejected", "held", "failed") and not (
                concept_ok and st == "awaiting_concept"):
            continue
        if handle_reel(jd, generate=generate, dry_run_push=dry_run_push, force=force):
            advanced.append(jd.name)
    return advanced


# ── subcommands ────────────────────────────────────────────────────────────────
def cmd_reel(args):
    e.assert_running("produce-reel")
    job_dir = Path(args.job_dir).resolve()
    if not (job_dir / "brief.json").exists():
        sys.exit(f"no brief.json in {job_dir}")
    status = handle_reel(job_dir, generate=args.generate, dry_run_push=args.dry_run_push,
                         force=args.force)
    e.log(f"{job_dir.name}: reel advanced -> status={status}")


def cmd_run(args):
    e.assert_running("produce")
    date = e.today_pt()

    # Budget-gate the research sweep (searchapi + the one apify outlier extract). The
    # per-call teeth are on copywriter.py below; research.py caches its API calls (24h/7d).
    if not args.skip_research:
        before = {p.name for p in e.JOBS_DIR.glob("ACME-*")}
        # Manual Telegram link-drops first (v2 Stage 1 "manual_save", ANY user): drain ONE into the
        # Trending pillar. research.py drops has its own apify-budget gate + does nothing if none are
        # pending; when it lands a Trending brief we pass --no-outliers so the drop REPLACES the
        # YouTube outlier for today's 13:00 slot (no collision, no wasted extraction).
        drop_used = False
        try:
            import drops as _drops
            if _drops.pending(limit=1):
                dargs = ([PY, RESEARCH, "drops", "--max", "1"]
                         + (["--dry-run"] if args.dry_run else [])
                         + (["--fresh"] if args.fresh else []))
                e.log("manual link-drop(s) pending → draining one into Trending")
                dr = subprocess.run(dargs, capture_output=True, text=True)
                sys.stderr.write(dr.stderr)
                drop_used = bool({p.name for p in e.JOBS_DIR.glob("ACME-*")} - before)
        except Exception as ex:                       # a drop hiccup must never break the morning produce
            e.log(f"drop drain skipped (non-fatal): {ex}")

        if not e.spend("searchapi", 1) or not e.spend("apify", 1):
            e.log("research sweep skipped — searchapi/apify daily cap reached.")
        else:
            rargs = [PY, RESEARCH, "run", "--select", str(args.posts)]
            # Carousel mode (Devon §3.2): default 'rotate' = format-of-the-day per pillar/day;
            # 'carousel' forces decks; 'single' forces single cards.
            if args.carousel_mode == "carousel":
                rargs.append("--carousel")
            elif args.carousel_mode == "single":
                rargs.append("--no-carousel")
            if drop_used:
                rargs.append("--no-outliers")          # a manual drop already filled Trending today
            if args.dry_run:
                rargs.append("--dry-run")
            if args.fresh:
                rargs.append("--fresh")
            e.log(f"research: {' '.join(rargs[1:])}")
            r = subprocess.run(rargs, capture_output=True, text=True)
            sys.stderr.write(r.stderr)
            if r.returncode != 0:
                e.log("research.py run failed — see stderr above. Continuing with any new briefs.")
                e.alert(f"⚠️ Acme produce: research.py run failed (rc={r.returncode}). {(r.stderr or '')[-400:].strip()}")
        after = {p.name for p in e.JOBS_DIR.glob("ACME-*")}
        new_ids = sorted(after - before)
        e.log(f"research produced {len(new_ids)} new job(s): {new_ids}")
    else:
        new_ids = []

    # F7 autonomous reel (alternating-day cadence, Marvin 2026-06-19): on a VIDEO day, mint the
    # day's reel brief so sweep_reels below carries it through GATE 1. No-op on non-video days.
    # 0 credits here — generation still needs GATE 1 + REELS_LIVE + the 135-credit/day cap.
    if not args.skip_research:
        if e.is_video_day():
            e.log("video day → research reel-today (minting the day's reel brief)")
            rt = subprocess.run([PY, RESEARCH, "reel-today"] + (["--dry-run"] if args.dry_run else []),
                                capture_output=True, text=True)
            sys.stderr.write(rt.stderr)
            if rt.returncode != 0:
                e.log("reel-today failed — see stderr above. Continuing.")
        else:
            e.log("not a video day (alternating cadence) — no reel created today")

    if args.dry_run:
        e.log("DRY-RUN: research scored/printed; no render, no captions, no manifest.")
        return

    # F7 reels: advance every non-terminal reel through its phases (GATE 1 before any RV3
    # credit spend). New reels (research --reel / bank --format reel) enter at PHASE A;
    # concept-approved reels move to PHASE B. RV3 only SPENDS with --generate-reels + REELS_LIVE.
    advanced = sweep_reels(generate=args.generate_reels)
    if advanced:
        e.log(f"reels advanced: {advanced}")

    # Image REVISE re-production: regenerate + re-push any status=revise image (mirrors reels).
    reproduced = reproduce_revised_images()
    if reproduced:
        e.log(f"revised images re-produced: {reproduced}")

    # Collect the new image briefs.
    jobs = []
    for jid in new_ids:
        brief = e.load_json(e.JOBS_DIR / jid / "brief.json")
        if not isinstance(brief, dict) or brief.get("type") == "reel":
            continue
        jobs.append({"job_id": jid, "pillar": brief.get("pillar", ""),
                     "brand": brief.get("brand", "labs")})

    if not jobs:
        e.log("no new image briefs to package today.")
        return

    # Assign the 5 PT slots; cap packaging at the slots available (extras -> held).
    jobs = e.assign_slots(jobs)
    slotted = [j for j in jobs if j["slot"]]
    held = [j for j in jobs if not j["slot"]]

    ready = []
    for j in slotted:
        ok = package_job(e.JOBS_DIR / j["job_id"], j["pillar"], j["brand"], j["slot"],
                         force=args.force)
        if ok:
            ready.append(j)
    for j in held:
        e.write_status(j["job_id"], "held", pillar=j["pillar"], brand=j["brand"],
                       slot=None, slot_date=date, note="over the 5-slot/day cap")

    e.write_manifest(slotted, date)
    e.log(f"PRODUCE done: {len(ready)}/{len(slotted)} review-ready, {len(held)} held. "
          f"Manifest -> {e.manifest_path(date)}")
    failed = []
    for j in slotted:
        st = e.read_status(j["job_id"]) or {}
        e.log(f"  {j['job_id']}  slot={j['slot']}  pillar={j['pillar']}  status={st.get('status')}")
        if st.get("status") == "failed":
            failed.append(j["job_id"])
    # v2 error-handling: a stage failure pings Marvin (don't let a bad render pass silently).
    if failed:
        e.alert(f"⚠️ Acme produce: {len(failed)} job(s) FAILED to render/caption today: {', '.join(failed)}")


def cmd_captions(args):
    e.assert_running("produce-captions")
    job_dir = Path(args.job_dir).resolve()
    if not (job_dir / "brief.json").exists():
        sys.exit(f"no brief.json in {job_dir}")
    caps = build_captions(job_dir, force=args.force)
    if caps is None:
        sys.exit(1)
    print(json.dumps(caps, ensure_ascii=False, indent=2))


def cmd_enqueue(args):
    """Add already-produced jobs to today's manifest + status (prove-loop / manual)."""
    e.assert_running("produce-enqueue")
    date = e.today_pt()
    man = e.read_manifest(date)
    existing = {j["job_id"] for j in man["jobs"]}
    new = []
    for jid in args.job_ids:
        brief = e.load_json(e.JOBS_DIR / jid / "brief.json")
        if not isinstance(brief, dict):
            e.log(f"{jid}: no brief.json — skipping")
            continue
        new.append({"job_id": jid, "pillar": brief.get("pillar", ""),
                    "brand": brief.get("brand", "labs")})
    merged = man["jobs"] + [j for j in new if j["job_id"] not in existing]
    merged = e.assign_slots([{k: v for k, v in j.items() if k != "slot"} for j in merged])
    for j in merged:
        if j["job_id"] in existing:
            continue
        jd = e.JOBS_DIR / j["job_id"]
        caps = build_captions(jd, force=args.force)
        status = "produced" if caps else "failed"
        e.write_status(j["job_id"], status, pillar=j["pillar"], brand=j["brand"],
                       slot=j["slot"], slot_date=date, produced_at=e.now_iso())
    e.write_manifest(merged, date)
    e.log(f"enqueued {len(new)} job(s); manifest now {len(merged)} job(s) -> {e.manifest_path(date)}")


def main():
    ap = argparse.ArgumentParser(prog="produce_daily",
                                 description="Acme loop STEP A — PRODUCE (0 Higgsfield credits)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="Full morning produce: research -> render -> captions -> manifest")
    pr.add_argument("--posts", type=int, default=4,
                    help="Mode-A topics to select (default 4; research adds +1 trending -> ~5/day)")
    pr.add_argument("--carousel", dest="carousel_mode", action="store_const", const="carousel",
                    help="FORCE every daily image to a carousel deck (overrides Devon's §3.2 rotation)")
    pr.add_argument("--no-carousel", dest="carousel_mode", action="store_const", const="single",
                    help="FORCE single cards instead of the rotation / carousels")
    pr.add_argument("--skip-research", action="store_true",
                    help="Skip the research sweep (package only briefs already on disk)")
    pr.add_argument("--dry-run", action="store_true", help="Score/print only; no render/captions/manifest")
    pr.add_argument("--fresh", action="store_true", help="Bypass research's API cache")
    pr.add_argument("--force", action="store_true", help="Rebuild captions even if present")
    pr.add_argument("--generate-reels", action="store_true",
                    help="Let concept-approved reels SPEND on RV3 generation (still needs REELS_LIVE "
                         "+ a per-reel concept approval + the 6 credits/day cap). Default: RV3 dry-run, 0 credits.")
    pr.set_defaults(carousel_mode="rotate", func=cmd_run)

    prl = sub.add_parser("reel", help="F7: advance ONE reel through its phases (RV2 -> GATE 1 -> RV3 -> RV4 -> GATE 2)")
    prl.add_argument("job_dir")
    prl.add_argument("--generate", action="store_true",
                     help="Allow the RV3 credit spend (also needs REELS_LIVE + concept approval + cap)")
    prl.add_argument("--dry-run-push", action="store_true", help="Print the Telegram card; don't send / don't change status")
    prl.add_argument("--force", action="store_true", help="Rebuild captions even if present")
    prl.set_defaults(func=cmd_reel)

    pc = sub.add_parser("captions", help="(Re)build captions.json for ONE existing job (the bridge alone)")
    pc.add_argument("job_dir")
    pc.add_argument("--force", action="store_true")
    pc.set_defaults(func=cmd_captions)

    pe = sub.add_parser("enqueue", help="Add already-produced job(s) to today's manifest")
    pe.add_argument("job_ids", nargs="+")
    pe.add_argument("--force", action="store_true")
    pe.set_defaults(func=cmd_enqueue)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    e.guard_main("produce", main)
