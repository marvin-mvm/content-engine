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

SCOPE: carousels + static images ONLY. Video reels are EXCLUDED from the auto loop (they
cost Higgsfield credits + need hand-authored caption beats). research.py only ever emits
type=image briefs, but we defensively skip anything type=reel.

Each job ends pending review (status=produced); NO qc.json yet — that is written only on
Telegram APPROVE (approvals.py). Spend-capped + STOP-flag honored via engine.py.

Subcommands:
    run [--posts N] [--no-carousel] [--dry-run] [--force]   full morning produce
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

PY = sys.executable or "python3"
RESEARCH = str(e.WORKSPACE / "research.py")
POST = str(e.WORKSPACE / "post.py")
COPY = str(e.WORKSPACE / "copywriter.py")

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
    reserve = (len(e.RUO_SENTENCE) + 2 if e.is_labs(brief) else 0) + (len(link) + 6 if link else 0)
    last = fit_x(strip_hashtags(tweets[-1]), reserve=reserve)
    last = e.ensure_link(last, link)
    tweets[-1] = e.ensure_ruo(last, brief)
    return {"text": tweets[0], "thread": tweets[1:]}


def build_captions(job_dir: Path, force: bool = False) -> dict | None:
    """THE BRIDGE: write captions.json (per-platform, RUO-enforced, X-fitted) for a job.
    Returns the captions dict, or None if the brief is missing / nothing could be built."""
    brief = e.load_json(job_dir / "brief.json")
    if not isinstance(brief, dict):
        e.log(f"{job_dir.name}: no/invalid brief.json — cannot build captions")
        return None
    if brief.get("type") == "reel":
        e.log(f"{job_dir.name}: type=reel is excluded from the auto loop — skipping")
        return None

    out_path = job_dir / "captions.json"
    if out_path.exists() and not force:
        e.log(f"{job_dir.name}: captions.json exists (use --force to rebuild)")
        return e.load_json(out_path)

    brand = brief.get("brand", "labs")
    topic = brief.get("topic", "")
    # Live channels first, then any extra brief platform (threads/facebook).
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
            # X: 0 hashtags, <= 280 incl. the RUO line (Labs) AND the COA link. Reserve room
            # for both, trim the body, then append link then RUO (RUO stays the last line).
            reserve = (len(e.RUO_SENTENCE) + 2) if e.is_labs(brief) else 0
            if link:
                reserve += len(link) + 6  # "\nCOA: " + url
            text = fit_x(text, reserve=reserve)
            text = e.ensure_link(text, link)
            text = e.ensure_ruo(text, brief)
        else:
            text = append_hashtags(text, hashtags, HASHTAG_CAP.get(p, 0))
            text = e.ensure_link(text, link)
            text = e.ensure_ruo(text, brief)
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


def package_job(job_dir: Path, pillar: str, brand: str, slot: str | None,
                force: bool = False) -> bool:
    """Render + build captions + set status for one job. Returns True if review-ready."""
    job_id = job_dir.name
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


# ── subcommands ────────────────────────────────────────────────────────────────
def cmd_run(args):
    e.assert_running("produce")
    date = e.today_pt()

    # Budget-gate the research sweep (searchapi + the one apify outlier extract). The
    # per-call teeth are on copywriter.py below; research.py caches its API calls (24h/7d).
    if not args.skip_research:
        if not e.spend("searchapi", 1) or not e.spend("apify", 1):
            e.log("research sweep skipped — searchapi/apify daily cap reached.")
        else:
            before = {p.name for p in e.JOBS_DIR.glob("ACME-*")}
            rargs = [PY, RESEARCH, "run", "--select", str(args.posts)]
            if args.carousel:
                rargs.append("--carousel")
            if args.dry_run:
                rargs.append("--dry-run")
            if args.fresh:
                rargs.append("--fresh")
            e.log(f"research: {' '.join(rargs[1:])}")
            r = subprocess.run(rargs, capture_output=True, text=True)
            sys.stderr.write(r.stderr)
            if r.returncode != 0:
                e.log("research.py run failed — see stderr above. Continuing with any new briefs.")
            after = {p.name for p in e.JOBS_DIR.glob("ACME-*")}
            new_ids = sorted(after - before)
            e.log(f"research produced {len(new_ids)} new job(s): {new_ids}")
    else:
        new_ids = []

    if args.dry_run:
        e.log("DRY-RUN: research scored/printed; no render, no captions, no manifest.")
        return

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
    for j in slotted:
        st = e.read_status(j["job_id"]) or {}
        e.log(f"  {j['job_id']}  slot={j['slot']}  pillar={j['pillar']}  status={st.get('status')}")


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
    pr.add_argument("--no-carousel", dest="carousel", action="store_false",
                    help="Render single cards instead of full carousel decks")
    pr.add_argument("--skip-research", action="store_true",
                    help="Skip the research sweep (package only briefs already on disk)")
    pr.add_argument("--dry-run", action="store_true", help="Score/print only; no render/captions/manifest")
    pr.add_argument("--fresh", action="store_true", help="Bypass research's API cache")
    pr.add_argument("--force", action="store_true", help="Rebuild captions even if present")
    pr.set_defaults(carousel=True, func=cmd_run)

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
    main()
