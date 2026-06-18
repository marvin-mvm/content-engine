#!/usr/bin/env python3
"""
publish.py — Acme one-command publisher (F1). 0 Higgsfield credits.

Turns a finished M6 job folder into live (or scheduled) social posts by driving
blotato.py — the proven publish flow (RUNBOOK §11), wrapped so it's one command
with a HARD compliance gate in front of it.

    publish.py output/jobs/ACME-NNN [--when ISO8601] [--platforms x,tiktok] [--go]

DEFAULT IS DRY RUN. It prints every blotato.py call it WOULD make and makes ZERO
network calls — nothing is uploaded, nothing is posted. Pass --go to actually
upload + publish. Publishing is irreversible and outward-facing (you cannot delete
a published post — RUNBOOK §11 P4), so --go is deliberately opt-in.

What it reads from the job folder
---------------------------------
  brief.json        the M1 contract (type, brand, product_feature, default platforms)
  qc.json           the M6 QC pass marker  {"passed": true, ...}  (REQUIRED to publish)
  captions.json     per-platform captions (the reviewed M2/M6 artifact copy.py feeds)
  <media>           reel  -> <job>-final.mp4
                    image -> <job_id>.png  (single)  or  <job_id>-slide-*.png (carousel)

captions.json contract (one UNIQUE caption per platform — SOUL §6, never verbatim-shared):
  {
    "x":        { "text": "<=280 opinion, 0 hashtags", "thread": ["follow-up <=280", ...] },
    "tiktok":   "caption + 3-5 hashtags",
    "instagram":"hook -> payoff -> Save this -> CTA",
    "youtube":  { "title": "Compound front-loaded", "text": "2-3 sentence description" }
  }
  A platform value is a string (single post) OR an object {text, thread[], title}.

The compliance gate (hard wall, fully offline — runs in BOTH dry-run and --go)
------------------------------------------------------------------------------
ANY failed check -> reasons to stderr, exit 1, publish NOTHING:
  - QC-pass flag      qc.json present with passed=true
  - RUO               every Labs-brand caption carries the research-use-only line
  - Labs = organic    Labs posts are never paid/boosted (no paid path exists here)
  - Banned claims     treats/cures/heals/fixes/prevents/diagnoses/proven-to/guaranteed/...
  - Media             each file exists + aspect matches (carousel 4:5 · callout 1:1 · reel 9:16)
  - X caption shape   each X post (main + thread) <=280 chars and 0 hashtags (§1A.4)
  - Caption present   every active target has a caption in captions.json

Connected Blotato accounts (RUNBOOK §11): X/twitter 18688 · tiktok 43061 · youtube 37252.
instagram/threads/facebook are NOT connected yet -> skipped with a warning (Operator's manual
Blotato step). YouTube takes video only (P2) -> skipped for image jobs.

Supabase published_posts is F-series; for now successes are recorded to
<job>/published_posts.json (accumulates across --go runs).
"""

import argparse
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).parent.resolve()
BLOTATO = str(WORKSPACE / "blotato.py")

# brief platform-name -> Blotato platform + connected account (RUNBOOK §11 / SOUL §6).
# account_id None = not connected yet (skipped with a warning, never a hard fail).
ACCOUNTS = {
    "x":         {"blotato": "twitter",   "account_id": "18688", "connected": True},
    "twitter":   {"blotato": "twitter",   "account_id": "18688", "connected": True},
    "tiktok":    {"blotato": "tiktok",    "account_id": "43061", "connected": True},
    "youtube":   {"blotato": "youtube",   "account_id": "37252", "connected": True, "video_only": True},
    "instagram": {"blotato": "instagram", "account_id": None,    "connected": False},
    "threads":   {"blotato": "threads",   "account_id": None,    "connected": False},
    "facebook":  {"blotato": "facebook",  "account_id": None,    "connected": False},
}

# Aspect ratios as width/height (gate: rendered media must match the template family).
ASPECT_RATIO = {"9:16": 9 / 16, "4:5": 4 / 5, "1:1": 1.0, "16:9": 16 / 9}
ASPECT_TOL = 0.02  # ~2% — covers rounding (1080x1350 = 0.8 exactly, but stay lenient)

# Template family -> required aspect (mirrors preflight.TEMPLATE_ASPECT / RUNBOOK §9.2).
TEMPLATE_ASPECT = [
    (re.compile(r"story-(reel|poll)"), "9:16"),
    (re.compile(r"carousel"), "4:5"),
    (re.compile(r"static-compound"), "4:5"),
    (re.compile(r"static-callout"), "1:1"),
]

# Banned medical-claim language (SOUL §12 + MIGRATION §1A.5). Union of the brand
# hard-stops; any hit blocks publishing.
BANNED = re.compile(
    r"\b(cure|cures|cured|curing|treat|treats|treated|treating|"
    r"heal|heals|healed|healing|fix|fixes|fixed|fixing|"
    r"prevent|prevents|prevented|preventing|diagnos\w+|"
    r"proven\s+to|guarantee|guarantees|guaranteed|"
    r"miracle|breakthrough|game[-\s]?changer)\b",
    re.IGNORECASE,
)

# RUO footer evidence (any one phrase satisfies the Labs RUO requirement).
RUO_RE = re.compile(r"research use only|not for human consumption|\bRUO\b", re.IGNORECASE)

X_LIMIT = 280


def fail(msg: str) -> "NoReturn":
    sys.exit(f"[publish] ERROR: {msg}")


def template_aspect(template: str):
    name = Path(template).name
    for rx, asp in TEMPLATE_ASPECT:
        if rx.search(name):
            return asp
    return None


# ── job-folder readers ─────────────────────────────────────────────────────────

def load_captions(job: Path) -> dict:
    p = job / "captions.json"
    if not p.exists():
        fail(f"no captions.json in {job} — author per-platform captions first "
             f"(copy.py --platform ...; see publish.py docstring for the contract)")
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as e:
        fail(f"captions.json is not valid JSON: {e}")


def caption_for(captions: dict, platform: str):
    """Normalize a captions.json entry to {text, thread[], title}. None if absent."""
    v = captions.get(platform)
    if v is None and platform in ("x", "twitter"):
        v = captions.get("twitter") if platform == "x" else captions.get("x")
    if v is None:
        return None
    if isinstance(v, str):
        return {"text": v, "thread": [], "title": None}
    if isinstance(v, dict):
        return {
            "text": v.get("text", ""),
            "thread": list(v.get("thread") or v.get("also") or []),
            "title": v.get("title"),
        }
    return None


def resolve_media(job: Path, brief: dict):
    """Return {'kind': 'video'|'images', 'files': [Path, ...]} from the M6 output."""
    job_id = brief["job_id"]
    if brief["type"] == "reel":
        final = job / f"{job_id}-final.mp4"
        return {"kind": "video", "files": [final]}  # existence checked in the gate
    img = brief.get("image", {})
    if img.get("carousel"):
        slides = sorted(job.glob(f"{job_id}-slide-*.png"))
        return {"kind": "images", "files": slides or [job / f"{job_id}-slide-01.png"]}
    return {"kind": "images", "files": [job / f"{job_id}.png"]}


def media_dims(path: Path, kind: str):
    """(w, h) for an image (PIL) or video (ffprobe). None if unreadable."""
    try:
        if kind == "video":
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
                capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                return None
            w, h = r.stdout.strip().split(",")[:2]
            return int(w), int(h)
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None


# ── target resolution (which platforms can actually receive this post) ──────────

def resolve_targets(requested, media_kind):
    """Split requested brief-platforms into (active, skips). Each active is a dict
    carrying the Blotato platform + account id; skips carry a human reason."""
    active, skips = [], []
    for name in requested:
        acct = ACCOUNTS.get(name)
        if acct is None:
            skips.append((name, "unknown platform"))
            continue
        if not acct["connected"]:
            skips.append((name, "not connected in Blotato yet (Operator's manual step)"))
            continue
        if acct.get("video_only") and media_kind != "video":
            skips.append((name, "YouTube takes video only — image post can't go here (RUNBOOK §11 P2)"))
            continue
        active.append({"name": name, **acct})
    return active, skips


def media_urls_for(target, all_urls, kind):
    """Per-platform media selection. X = single opinion tweet w/ cover image (proven
    ACME-011 treatment); YouTube = the one video; tiktok/instagram = full set."""
    plat = target["blotato"]
    if plat in ("twitter", "youtube"):
        return all_urls[:1]
    return all_urls


# ── the compliance gate ─────────────────────────────────────────────────────────

def compliance_gate(job, brief, captions, media, active_targets):
    """Return a list of blocking-reason strings (empty list = PASS)."""
    reasons = []
    brand = brief.get("brand")
    is_labs = brand == "labs"

    # 1 — QC pass marker (the M6 visual-QC sign-off must exist).
    qc = job / "qc.json"
    if not qc.exists():
        reasons.append("no qc.json — run the M6 visual QC and write {\"passed\": true} "
                       "to the job folder before publishing.")
    else:
        try:
            if json.loads(qc.read_text()).get("passed") is not True:
                reasons.append("qc.json present but passed != true — QC has not signed off.")
        except json.JSONDecodeError:
            reasons.append("qc.json is not valid JSON.")

    # 2 — Labs = organic only, never paid (no paid path exists here; guard a future flag).
    if is_labs and (brief.get("paid") or brief.get("boost")):
        reasons.append("brand=labs but brief requests paid/boosted distribution — "
                       "Labs is organic-only, NEVER paid (MIGRATION §1A.5).")

    # Per-active-target caption checks.
    for t in active_targets:
        name = t["name"]
        cap = caption_for(captions, name)
        if cap is None or not cap["text"].strip():
            reasons.append(f"no caption for active target '{name}' in captions.json.")
            continue
        posts = [cap["text"]] + list(cap["thread"])   # each X post is its own tweet
        full = " \n".join(posts)

        # 3 — banned medical-claim language (whole post, incl. thread).
        m = BANNED.search(full)
        if m:
            reasons.append(f"[{name}] banned claim language: {m.group(0)!r} "
                           "(use research framing: 'research suggests' / 'participants reported').")

        # 4 — RUO on every Labs caption (line may appear anywhere in the post/thread).
        if is_labs and not RUO_RE.search(full):
            reasons.append(f"[{name}] Labs post is missing the RUO line "
                           "('research use only' / 'not for human consumption').")

        # 5 — X caption shape: each tweet <=280 chars and 0 hashtags (§1A.4).
        if t["blotato"] == "twitter":
            for i, post in enumerate(posts):
                tag = "main tweet" if i == 0 else f"thread post {i}"
                if len(post) > X_LIMIT:
                    reasons.append(f"[{name}] {tag} is {len(post)} chars (>{X_LIMIT}).")
                if "#" in post:
                    reasons.append(f"[{name}] {tag} contains a hashtag — X must have 0 hashtags (§1A.4).")

    # 6 — media exists + correct aspect.
    if brief["type"] == "reel":
        want = "9:16"
    else:
        want = template_aspect(brief.get("image", {}).get("template", "")) or "4:5"
    want_ratio = ASPECT_RATIO.get(want)
    files = media["files"]
    if not files:
        reasons.append("no media files resolved for this job (nothing to publish).")
    for f in files:
        if not f.exists():
            reasons.append(f"media file missing: {f.name} (run the M5/M6 step first).")
            continue
        dims = media_dims(f, media["kind"])
        if dims is None:
            reasons.append(f"could not read media dimensions: {f.name}.")
            continue
        w, h = dims
        ratio = w / h if h else 0
        if want_ratio and abs(ratio - want_ratio) > ASPECT_TOL:
            reasons.append(f"{f.name} is {w}x{h} (ratio {ratio:.3f}); "
                           f"expected {want} ({want_ratio:.3f}) for this post.")

    return reasons


# ── upload + publish ────────────────────────────────────────────────────────────

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def upload_all(files, job, go, reupload):
    """Upload each unique media file once -> {filename: publicUrl}.

    Dry-run: NO network — returns a clear placeholder per file and prints the
    upload command. --go: runs `blotato.py upload`, caches URLs to uploaded_urls.json
    so re-runs don't re-upload (override with --reupload)."""
    cache_path = job / "uploaded_urls.json"
    cache = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except json.JSONDecodeError:
            cache = {}
    urls = {}
    for f in files:
        name = f.name
        if not go:
            print(f"  [dry-run] upload: {shlex.join(['python3', 'blotato.py', 'upload', str(f)])}", flush=True)
            urls[name] = f"<<UPLOADED_URL:{name}>>"
            continue
        if name in cache and not reupload:
            print(f"  [cached] {name} -> {cache[name]}", file=sys.stderr)
            urls[name] = cache[name]
            continue
        print(f"  uploading {name} ...", file=sys.stderr)
        r = run(["python3", BLOTATO, "upload", str(f)])
        if r.returncode != 0:
            fail(f"upload failed for {name}:\n{(r.stdout + r.stderr)[-800:]}")
        url = (r.stdout.strip().splitlines() or [""])[-1].strip()
        if not url.startswith("http"):
            fail(f"upload for {name} did not return a URL:\n{r.stdout[-400:]}")
        urls[name] = url
        cache[name] = url
    if go:
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    return urls


def build_publish_cmd(target, cap, media_urls, when):
    """The exact blotato.py publish argv for one platform. --raw so we capture the
    postSubmissionId + publicUrl (the formatted output drops the live post URL)."""
    cmd = ["python3", BLOTATO, "publish", cap["text"],
           "--account-id", target["account_id"], "--platform", target["blotato"], "--raw"]
    for u in media_urls:
        cmd += ["--media-url", u]
    for follow in cap["thread"]:
        cmd += ["--also", follow]
    if when:
        cmd += ["--schedule", when]
    if target["blotato"] == "youtube" and cap.get("title"):
        cmd += ["--title", cap["title"]]
    return cmd


def parse_publish_result(stdout: str) -> dict:
    """Parse `blotato.py publish --raw` stdout -> {post_id, post_url, status, raw}.

    The raw Blotato response is multi-line JSON; for an immediate post it carries
    {postSubmissionId, status, publicUrl, statusCode}, for a scheduled post
    {postSubmissionId, message}. Robust to a stray leading non-JSON line (extracts
    the {...} block) so subprocess stdout/stderr bleed can't break recording."""
    out = (stdout or "").strip()
    data = {}
    if out:
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", out, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(0))
                except json.JSONDecodeError:
                    data = {}
    if not isinstance(data, dict):
        data = {"raw": data}
    return {
        "post_id": data.get("postSubmissionId") or data.get("id") or data.get("postId"),
        "post_url": data.get("publicUrl") or data.get("postUrl"),
        "status": data.get("status") or data.get("message"),
        "raw": data,
    }


def record_run(job, mode, when, posts):
    """Append a run record to published_posts.json (accumulates across --go runs)."""
    path = job / "published_posts.json"
    doc = {"job_id": job.name, "runs": []}
    if path.exists():
        try:
            doc = json.loads(path.read_text())
            doc.setdefault("runs", [])
        except json.JSONDecodeError:
            pass
    doc["runs"].append({
        "run_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "scheduled_for": when,
        "posts": posts,
    })
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    return path


# ── main ─────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Acme one-command publisher (F1) — dry-run by default; --go to post.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("job_dir", help="Job folder containing brief.json + captions.json + qc.json + media")
    ap.add_argument("--when", help="Schedule time, ISO 8601 (e.g. 2026-06-18T16:00:00Z). Omit = post now.")
    ap.add_argument("--platforms", help="Comma list overriding brief.platforms (e.g. x,tiktok)")
    ap.add_argument("--go", action="store_true",
                    help="ACTUALLY upload + publish. Without it, everything is a dry run (no network).")
    ap.add_argument("--reupload", action="store_true", help="Force re-upload even if URLs are cached")
    ap.add_argument("--upload-only", action="store_true", dest="upload_only",
                    help="Stage the job's media to Blotato (REAL upload) and print the public URLs "
                         "— posts NOTHING. Pre-stage media, or validate the upload path safely.")
    args = ap.parse_args()

    job = Path(args.job_dir).resolve()
    brief_path = job / "brief.json"
    if not brief_path.exists():
        fail(f"no brief.json in {job}")
    brief = json.loads(brief_path.read_text())
    if brief.get("type") not in ("reel", "image"):
        fail(f"brief.type must be reel|image, got {brief.get('type')!r}")
    brief.setdefault("job_id", job.name)

    media = resolve_media(job, brief)

    # Upload-only: stage media to Blotato and stop. Real upload, but posts NOTHING,
    # so it needs neither captions nor the publish gate — it's the safe way to prove
    # the upload subprocess path (or to pre-stage media before a publish).
    if args.upload_only:
        print(f"── UPLOAD-ONLY {brief['job_id']} — staging media, posting NOTHING ──", file=sys.stderr)
        missing = [f for f in media["files"] if not f.exists()]
        if missing:
            fail("missing media: " + ", ".join(m.name for m in missing))
        url_map = upload_all(media["files"], job, go=True, reupload=args.reupload)
        for f in media["files"]:
            print(f"{f.name}\t{url_map[f.name]}")
        print(f"\n[publish] staged {len(media['files'])} file(s) -> {job/'uploaded_urls.json'}. "
              "Nothing was posted.", file=sys.stderr)
        return

    captions = load_captions(job)

    requested = ([p.strip() for p in args.platforms.split(",") if p.strip()]
                 if args.platforms else brief.get("platforms", ["instagram", "tiktok"]))
    requested = ["x" if p == "twitter" else p for p in requested]
    active, skips = resolve_targets(requested, media["kind"])

    mode = "go" if args.go else "dry-run"
    print(f"── PUBLISH {brief['job_id']} ({brief['type']}, brand={brief.get('brand')}) · mode={mode.upper()} ──", file=sys.stderr)
    print(f"requested platforms: {', '.join(requested)}", file=sys.stderr)
    for name, why in skips:
        print(f"  SKIP {name}: {why}", file=sys.stderr)
    if not active:
        fail("no active publishable targets after skips — nothing to do.")
    print(f"active targets: {', '.join(t['name'] for t in active)}"
          f"{'  scheduled ' + args.when if args.when else '  (immediate)'}", file=sys.stderr)

    # ── compliance gate (runs in BOTH modes; --go cannot bypass it) ──
    reasons = compliance_gate(job, brief, captions, media, active)
    if reasons:
        print("\nCOMPLIANCE GATE: BLOCK — publishing nothing. Failed checks:", file=sys.stderr)
        for i, r in enumerate(reasons, 1):
            print(f"  {i}. {r}", file=sys.stderr)
        sys.exit(1)
    print("COMPLIANCE GATE: PASS — all checks cleared.\n", file=sys.stderr)

    # ── upload media ──
    print("Upload step:", file=sys.stderr)
    url_map = upload_all(media["files"], job, args.go, args.reupload)
    ordered_urls = [url_map[f.name] for f in media["files"]]

    # ── per-platform publish ──
    posts = []
    for t in active:
        cap = caption_for(captions, t["name"])
        urls = media_urls_for(t, ordered_urls, media["kind"])
        cmd = build_publish_cmd(t, cap, urls, args.when)
        sys.stderr.flush()
        print(f"\n# {t['name']} -> Blotato {t['blotato']} (account {t['account_id']})", file=sys.stderr, flush=True)
        if not args.go:
            print(shlex.join(cmd), flush=True)
            posts.append({"platform": t["name"], "blotato": t["blotato"],
                          "account_id": t["account_id"], "media_urls": urls,
                          "dry_run": True})
            continue
        r = run(cmd)
        out = (r.stdout or "").strip()
        print(out, file=sys.stderr)
        if r.returncode != 0:
            print(f"  publish FAILED for {t['name']}:\n{(r.stdout + r.stderr)[-600:]}", file=sys.stderr)
            posts.append({"platform": t["name"], "blotato": t["blotato"],
                          "account_id": t["account_id"], "media_urls": urls,
                          "ok": False, "error": (r.stdout + r.stderr)[-600:]})
            continue
        info = parse_publish_result(out)
        if info["post_url"]:
            print(f"  live: {info['post_url']}", file=sys.stderr)
        posts.append({"platform": t["name"], "blotato": t["blotato"],
                      "account_id": t["account_id"], "media_urls": urls,
                      "ok": True, **info})

    if args.go:
        rec = record_run(job, mode, args.when, posts)
        print(f"\n[publish] recorded -> {rec}", file=sys.stderr)
        print("\n⚠️  VERIFY EACH POST VISUALLY on the platform — a 200/published from the API "
              "confirms only the MAIN post, and a published post cannot be deleted via Blotato "
              "(RUNBOOK §11 P4/P6).", file=sys.stderr)
    else:
        print("\n[publish] DRY RUN — nothing uploaded, nothing posted. Re-run with --go to publish.", file=sys.stderr)


if __name__ == "__main__":
    main()
