"""
produce.py — Acme full production pipeline

Orchestrates: brand prompt injection → Higgsfield image → download → render.py HTML overlay → final PNG.
With --video: also renders the template as a thumbnail and embeds it into the mp4 as cover art.
With --video-underlay: renders the template as a TRANSPARENT overlay and composites it over a CLEAN
video (the reel video-underlay model — caption lives in the template, never burned into the video).

Usage:
    python3 produce.py <template> [--bg-prompt "..."] [--bg-file path.jpg] [--set KEY=VALUE ...] [--json data.json]
    python3 produce.py <template> --video reel.mp4 [--set KEY=VALUE ...]              # cover-art only
    python3 produce.py <template> --video-underlay clean.mp4 [--set KEY=VALUE ...]    # overlay over video

Examples:
    # Full pipeline: generate Higgsfield bg, composite HTML template on top
    python3 produce.py templates/src/story-reel-dark.html \\
        --bg-prompt "cold-chain vial on dark forest surface, dramatic side lighting" \\
        --set EYEBROW="PEPTIDE RESEARCH" \\
        --set HOOK_LINE_1="What if recovery" \\
        --set "HOOK_LINE_2_ITALIC=actually worked" \\
        --set "HOOK_LINE_3=for you?" \\
        --set "SUBTITLE_TEXT=BPC-157 · 12-week study" \\
        --set "CTA_LABEL=READ THE COA" \\
        --set "HANDLE=@acmelabs"

    # Video reel: render template as thumbnail, embed into mp4 cover art
    python3 produce.py templates/src/story-reel-dark.html \\
        --video output/acme_reel.mp4 \\
        --set EYEBROW="PEPTIDE RESEARCH" \\
        --set HOOK_LINE_1="What if recovery" \\
        --set "HOOK_LINE_2_ITALIC=actually worked" \\
        --set "HOOK_LINE_3=for you?" \\
        --set "SUBTITLE_TEXT=BPC-157 · 12-week study" \\
        --set "CTA_LABEL=READ THE COA" \\
        --set "HANDLE=@acmelabs"
    # → output/<stem>-<ts>.mp4 (with embedded thumbnail)
    # → output/<stem>-<ts>-thumb.png (standalone thumbnail for Blotato)

    # Skip Higgsfield — use an existing image as background
    python3 produce.py templates/src/story-reel-light.html \\
        --bg-file asset_cache/vial_shot_001.jpg \\
        --json content/glp1_story.json

    # No background — standalone branded template
    python3 produce.py templates/src/story-poll.html \\
        --set STORY_TAG="RESEARCH INSIGHT" \\
        --set STORY_HOOK_1="Have you used" \\
        --set "STORY_HOOK_2_ITALIC=tirzepatide?" \\
        --set STORY_HOOK_3="" \\
        --set POLL_OPTION_A="YES" \\
        --set POLL_OPTION_B="NO"
"""

import argparse
import hashlib
import json
import os
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()

from render import render, list_tokens
from sheetlog import log_asset
import engine as eng  # image-source rotation policy (Higgsfield/Blotato) lives in the core

WORKSPACE = Path(__file__).parent
OUTPUT_DIR = WORKSPACE / "output"
ASSET_CACHE = WORKSPACE / "asset_cache"
HIGGSFIELD = str(WORKSPACE / "higgsfield.py")
BLOTATO = str(WORKSPACE / "blotato.py")

# Prepended verbatim to every Higgsfield image prompt (CLAUDE.md §IMAGE Brand Prompt Block)
IMAGE_BRAND_PROMPT = (
    "Acme premium-biotech editorial visual system. "
    "Color palette STRICTLY: deep forest green #1A2E1E and #2D6A4A, warm cream #F2EDE4, "
    "sage mint #C8DDD0, with bright accent green #3D9E6E for a single point of emphasis. "
    "NEVER use gold, yellow, amber, purple, pink, red, or orange. "
    "NEVER a plain white background — minimum is warm cream #F2EDE4. "
    "Clean, lit-from-the-side product photography on cream or deep-forest surfaces, "
    "generous negative space, thin hairline rules, subtle elliptical leaf motif echoing the logomark. "
    "Mood: scientific precision meeting accessible education — calm, rigorous, premium. "
    "Not spa-wellness, not stock-photo smiles, not cluttered, not neon. "
    "Editorial, authoritative, minimal. ::"
)


def cache_path_for(prompt: str, model: str) -> Path:
    key = hashlib.sha256(f"{model}:{prompt}".encode()).hexdigest()[:16]
    return ASSET_CACHE / f"hf_{key}.jpg"


def download_image(url: str) -> str:
    """Download a remote image (e.g. a Higgsfield result_url) into asset_cache and
    return the local path. Cached by URL hash so the same image is fetched once.

    This is the bridge for the automation pipeline: Higgsfield hands back a URL,
    produce.py needs a local file for the template background.
    """
    ext = ".webp" if ".webp" in url.lower() else ".png" if ".png" in url.lower() else ".jpg"
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    cached = ASSET_CACHE / f"url_{key}{ext}"
    if cached.exists():
        print(f"[produce] bg-url cache hit → {cached}", file=sys.stderr)
        return str(cached)
    ASSET_CACHE.mkdir(exist_ok=True)
    print(f"[produce] downloading bg-url {url[:80]}... ", file=sys.stderr)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ssl_context()))
    # Some image CDNs/proxies (e.g. images.higgs.ai) 403 the default Python UA.
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (acme-produce)"})
    with opener.open(req) as r, open(cached, "wb") as f:
        f.write(r.read())
    print(f"[produce] cached → {cached}", file=sys.stderr)
    return str(cached)


def higgsfield_generate(prompt: str, model: str = "flux_1_1_pro", aspect: str = "9:16") -> str:
    """Generate an image via Higgsfield, return local cached path."""
    cached = cache_path_for(prompt, model)
    if cached.exists():
        print(f"[produce] cache hit → {cached}", file=sys.stderr)
        return str(cached)

    branded = f"{IMAGE_BRAND_PROMPT} {prompt}"
    print(f"[produce] Higgsfield image ({model}) ...", file=sys.stderr)

    result = subprocess.run(
        ["higgsfield", "generate", "create", model,
         "--prompt", branded,
         "--aspect_ratio", aspect,
         "--json", # Request JSON output
         "--wait" # Ensure it waits for completion
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        sys.exit(f"[produce] Higgsfield failed:\n{result.stderr.strip() or result.stdout.strip()}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        sys.exit(f"[produce] Could not parse Higgsfield output:\n{result.stdout[:400]}")

    # Check if 'data' is a list and take the first element, otherwise assume it's a dict
    if isinstance(data, list) and data:
        job_data = data[0]
    else:
        job_data = data

    url = job_data.get("url") or job_data.get("media_url") or job_data.get("output_url") or job_data.get("result_url")
    if not url:
        sys.exit(f"[produce] No url in Higgsfield output:\n{json.dumps(data, indent=2)}")

    print(f"[produce] downloading {url} ...", file=sys.stderr)
    ASSET_CACHE.mkdir(exist_ok=True)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ssl_context()))
    with opener.open(url) as r, open(cached, "wb") as f:
        f.write(r.read())
    print(f"[produce] cached → {cached}", file=sys.stderr)
    return str(cached)


def blotato_generate(prompt: str) -> "str | None":
    """Generate the background image via Blotato instead of Higgsfield (conserves Higgsfield
    credits — Marvin 2026-06-19). Needs a Blotato image template id in .env BLOTATO_IMAGE_TEMPLATE_ID;
    returns the local cached path, or None if it isn't configured / fails (caller falls back)."""
    tid = (eng.load_env("BLOTATO_IMAGE_TEMPLATE_ID") or "").strip()
    if not tid:
        print("[produce] Blotato image template not set (BLOTATO_IMAGE_TEMPLATE_ID) — "
              "falling back to Higgsfield this time.", file=sys.stderr)
        return None
    branded = f"{IMAGE_BRAND_PROMPT} {prompt}"
    print(f"[produce] Blotato image (template={tid}) ...", file=sys.stderr)
    r = subprocess.run(["python3", BLOTATO, "generate", tid, branded],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[produce] Blotato generate failed — falling back to Higgsfield:\n{r.stderr[-300:]}",
              file=sys.stderr)
        return None
    try:
        data = json.loads(r.stdout)
        if isinstance(data, list) and data:
            data = data[0]
        url = data.get("url") or data.get("exportUrl") or data.get("mediaUrl") or data.get("outputUrl")
    except (json.JSONDecodeError, AttributeError):
        url = None
    if not url:
        print("[produce] Blotato returned no image url — falling back to Higgsfield.", file=sys.stderr)
        return None
    return download_image(url)


def bg_generate(prompt: str, model: str, aspect: str, source: str = "auto") -> str:
    """Resolve the background-image generator per the rolling 4:1 policy (engine.image_source):
    ~4 of 5 generated images → Higgsfield, ~1 of 5 → Blotato. `source` of 'higgsfield'/'blotato'
    forces it (no rotation advance); 'auto' consults + advances the rolling counter."""
    if source == "auto":
        chosen = eng.image_source(advance=True)
        print(f"[produce] image-source rotation → {chosen}", file=sys.stderr)
    else:
        chosen = source
    if chosen == "blotato":
        path = blotato_generate(prompt)
        if path:
            return path
        # blotato unconfigured/failed → conserve the run, fall back to Higgsfield
    return higgsfield_generate(prompt, model=model, aspect=aspect)


def composite_overlay(video_path: str, overlay_png: str, output_path: str,
                      w: int = 1080, h: int = 1920, window=None, band: str = "#1A2E1E") -> str:
    """Composite a transparent brand overlay PNG over a CLEAN video underlay.

    This is the video-underlay reel model (Marvin 2026-06-20): the caption/brand
    chrome lives in the template overlay and the video stays clean, never burned.

    Two layouts:
      • window=(x,y,wd,ht): the video is CONTAINED in that box (the template's design
        window), scaled to COVER the box; the opaque template band (drawn by the
        overlay PNG) frames it and the caption sits OUTSIDE the box. The brand-colour
        `band` fills the base behind the bands.
      • window=None: full-frame — video covers the whole WxH frame, overlay on top.
    Audio is copied through when present.
    """
    if window:
        wx, wy, ww, wh = window
        bandhex = "0x" + band.lstrip("#")
        vf = (f"[0:v]scale={ww}:{wh}:force_original_aspect_ratio=increase,crop={ww}:{wh},setsar=1[v];"
              f"[2:v][v]overlay={wx}:{wy}:shortest=1[base];"
              f"[base][1:v]overlay=0:0:format=auto[o]")
        cmd = [
            "ffmpeg", "-y", "-i", video_path, "-i", overlay_png,
            "-f", "lavfi", "-i", f"color=c={bandhex}:s={w}x{h}",
            "-filter_complex", vf, "-map", "[o]", "-map", "0:a?",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium",
            "-c:a", "copy", "-movflags", "+faststart", output_path,
        ]
    else:
        vf = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
              f"crop={w}:{h},setsar=1[bg];[bg][1:v]overlay=0:0:format=auto[v]")
        cmd = [
            "ffmpeg", "-y", "-i", video_path, "-i", overlay_png,
            "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium",
            "-c:a", "copy", "-movflags", "+faststart", output_path,
        ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"[produce] ffmpeg overlay composite failed:\n{result.stderr[-800:]}")
    where = f"into window {window}" if window else "over full frame"
    print(f"[produce] overlay composited {where} → {output_path}", file=sys.stderr)
    return output_path


CAPTION_TEMPLATE = str(WORKSPACE / "templates" / "src" / "reel-caption-overlay.html")


def burn_synced_captions(video_path: str, script: str, duration: float, output_path: str,
                         cap_dir: str, template: str = CAPTION_TEMPLATE) -> str:
    """Overlay the spoken script as SYNCED captions on the reel (this ffmpeg has no libass, so
    captions are timed transparent PNG overlays, not SRT/ASS). The script is split into short
    sentence-aware phrases, each timed proportionally across the narration `duration`, rendered
    as a brand caption pill, and overlaid only during its time window. The video/audio underneath
    is untouched — the caption rides the brand overlay, never burned into the source b-roll."""
    words = script.split()
    if not words:
        return video_path
    segs, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= 6 or w.endswith((".", "!", "?")):
            segs.append(" ".join(cur)); cur = []
    if cur:
        segs.append(" ".join(cur))
    tot = len(words)
    capd = Path(cap_dir); capd.mkdir(parents=True, exist_ok=True)
    items, t = [], 0.0
    for i, s in enumerate(segs):
        d = duration * len(s.split()) / tot
        a, b = t, t + d; t = b
        png = str(capd / f"cap_{i:02d}.png")
        render(template, png, {"CAP_TEXT": s}, transparent=True)
        items.append((png, a, b))

    inputs, fc, prev = ["-i", video_path], [], "0:v"
    for idx, (png, a, b) in enumerate(items):
        inputs += ["-i", png]
        lbl = f"v{idx}"
        fc.append(f"[{prev}][{idx + 1}:v]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[{lbl}]")
        prev = lbl
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", f"[{prev}]",
           "-map", "0:a?", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium",
           "-c:a", "copy", "-movflags", "+faststart", output_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"[produce] caption burn failed:\n{r.stderr[-600:]}")
    print(f"[produce] burned {len(items)} synced captions → {output_path}", file=sys.stderr)
    return output_path


def first_frame(video_path: str, png_out: str) -> str:
    """Grab the first frame of a video as a PNG (poster/thumbnail for Blotato)."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-frames:v", "1", "-update", "1", png_out],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"[produce] WARN: poster extract failed:\n{result.stderr[-400:]}", file=sys.stderr)
    return png_out


def attach_thumbnail(video_path: str, thumb_path: str, output_path: str) -> str:
    """Embed a PNG as cover-art (attached_pic) in an mp4 and save to output_path."""
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", thumb_path,
            "-map", "0",
            "-map", "1",
            "-c", "copy",
            "-c:v:1", "png",
            "-disposition:v:1", "attached_pic",
            output_path,
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        sys.exit(f"[produce] ffmpeg thumbnail embed failed:\n{result.stderr[-600:]}")
    print(f"[produce] thumbnail embedded → {output_path}", file=sys.stderr)
    return output_path


def derive_topic(values: dict) -> str:
    """Build a Content Matrix topic string from the template tokens."""
    eyebrow = values.get("EYEBROW", "").strip()
    headline = " ".join(
        values.get(k, "").strip()
        for k in ("HOOK_LINE_1", "HOOK_LINE_2_ITALIC", "HOOK_LINE_3")
    ).strip()
    if not headline:  # poll template
        headline = " ".join(
            values.get(k, "").strip()
            for k in ("STORY_HOOK_1", "STORY_HOOK_2_ITALIC", "STORY_HOOK_3")
        ).strip()
    parts = [p for p in (eyebrow, headline) if p]
    return " — ".join(parts) or "Untitled asset"


def main():
    ap = argparse.ArgumentParser(
        description="Acme full production pipeline: Higgsfield bg → HTML template → PNG / mp4+thumb",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("template", help="Path to .html template")
    ap.add_argument("output", nargs="?",
                    help="Output path (default: output/<stem>-<timestamp>.png or .mp4)")

    bg = ap.add_mutually_exclusive_group()
    bg.add_argument("--bg-prompt", metavar="PROMPT",
                    help="Creative prompt for Higgsfield background (brand block auto-prepended)")
    bg.add_argument("--bg-file", metavar="FILE",
                    help="Use an existing local image as background (skips Higgsfield)")
    bg.add_argument("--bg-url", metavar="URL",
                    help="Download a remote image (e.g. a Higgsfield result_url) and use it as "
                         "the background. The automation bridge — no manual download step.")

    ap.add_argument("--video", metavar="FILE",
                    help="Source .mp4 reel — renders template as thumbnail and embeds it as cover art")
    ap.add_argument("--video-underlay", metavar="FILE", dest="video_underlay",
                    help="Source CLEAN .mp4 — renders the template as a TRANSPARENT overlay and "
                         "composites it over every frame (caption in the template, video stays clean). "
                         "The video-underlay reel model; distinct from --video (cover art only).")
    ap.add_argument("--window", metavar="X,Y,W,H",
                    help="With --video-underlay: place the video INSIDE this box (the template's "
                         "design window) instead of full-frame, so the caption sits OUTSIDE the video.")
    ap.add_argument("--band", default="#1A2E1E", metavar="#HEX",
                    help="Brand band colour behind a windowed composite (default deep forest; use cream for light).")
    ap.add_argument("--captions-script", metavar="TEXT",
                    help="With --video-underlay: overlay this spoken script as SYNCED captions on the reel.")
    ap.add_argument("--captions-dur", type=float, metavar="SECONDS",
                    help="Narration duration the captions sync across (default: the video duration).")
    ap.add_argument("--carousel", metavar="FILE", dest="carousel_file",
                    help="JSON array of per-slide token dicts — renders one PNG per slide "
                         "(slide-01.png …). --set / --json values are merged into every slide; "
                         "SLIDE_NUM/SLIDE_TOTAL auto-filled.")
    ap.add_argument("--model", default="gpt_image_2",
                    help="Higgsfield model (default: flux_1_1_pro)")
    ap.add_argument("--bg-source", choices=["auto", "higgsfield", "blotato"], default="auto",
                    help="Which engine generates the --bg-prompt image. 'auto' (default) follows "
                         "the rolling 4:1 Higgsfield:Blotato policy to conserve Higgsfield credits.")
    ap.add_argument("--set", metavar="KEY=VALUE", action="append", default=[],
                    dest="pairs", help="Set a template placeholder value")
    ap.add_argument("--json", metavar="FILE", dest="json_file",
                    help="JSON file with placeholder key/value pairs")
    ap.add_argument("--topic", help="Topic for the Content Matrix log (else derived from tokens)")
    ap.add_argument("--prompt", default="", help="Higgsfield/generation prompt to log in col F of the Content Matrix")
    ap.add_argument("--no-log", action="store_true",
                    help="Skip auto-logging to the Content Matrix sheet (use for test renders)")
    ap.add_argument("--tokens", action="store_true",
                    help="Print template tokens and exit")
    args = ap.parse_args()

    if args.tokens:
        html = Path(args.template).read_text()
        for t in list_tokens(html):
            print(f"  {{{{ {t} }}}}")
        return

    # Collect placeholder values
    values = {}
    if args.json_file:
        with open(args.json_file) as f:
            values.update(json.load(f))
    for pair in args.pairs:
        if "=" not in pair:
            print(f"[produce] Skipping malformed --set value: {pair!r}", file=sys.stderr)
            continue
        k, v = pair.split("=", 1)
        values[k.strip()] = v.strip()

    OUTPUT_DIR.mkdir(exist_ok=True)
    stem = Path(args.template).stem
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")

    # ── Carousel mode: render one PNG per slide ───────────────────────────────
    if args.carousel_file:
        with open(args.carousel_file) as f:
            slides = json.load(f)
        if not isinstance(slides, list) or not slides:
            sys.exit("[produce] --carousel JSON must be a non-empty array of slide objects")
        total = len(slides)
        outputs = []
        for i, slide in enumerate(slides, start=1):
            if not isinstance(slide, dict):
                sys.exit(f"[produce] slide {i} is not an object")
            # Merge: shared --set/--json values, then slide-specific, then auto counters
            slide_values = {**values, **slide}
            slide_values.setdefault("SLIDE_NUM", f"{i:02d}")
            slide_values.setdefault("SLIDE_TOTAL", f"{total:02d}")
            slide_values.setdefault("SWIPE_LABEL", "SWIPE TO READ →" if i < total else "")
            out = str(OUTPUT_DIR / f"{stem}-{ts}-slide-{i:02d}.png")
            render(args.template, out, slide_values)
            outputs.append(out)
            print(f"[produce] slide {i}/{total} → {out}", file=sys.stderr)
        if not args.no_log:
            log_asset(media="; ".join(outputs),
                      topic=args.topic or derive_topic(values) or "Carousel",
                      prompt=args.prompt, stage="Production", status="Generated",
                      remarks=f"Carousel ({total} slides)")
        for out in outputs:
            print(out)
        return

    # ── Video-underlay mode: render TRANSPARENT overlay → composite over clean video ──
    if args.video_underlay:
        overlay_png = str(OUTPUT_DIR / f"{stem}-{ts}-overlay.png")
        thumb_path = str(OUTPUT_DIR / f"{stem}-{ts}-thumb.png")
        mp4_out = args.output or str(OUTPUT_DIR / f"{stem}-{ts}.mp4")

        # 1. Render the brand template as a transparent RGBA overlay (no bg injection).
        render(args.template, overlay_png, values, transparent=True)
        # 2. Composite it: into the template window if given, else full-frame.
        window = None
        if args.window:
            try:
                window = tuple(int(n) for n in args.window.split(","))
                assert len(window) == 4
            except (ValueError, AssertionError):
                sys.exit(f"[produce] --window must be 'X,Y,W,H' integers, got {args.window!r}")
        composite_overlay(args.video_underlay, overlay_png, mp4_out, window=window, band=args.band)
        # 2b. Synced spoken captions (timed PNG overlays) on top of the composite.
        if args.captions_script:
            import shutil as _sh
            dur = args.captions_dur
            if not dur:
                pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                     "-of", "default=nw=1:nk=1", mp4_out], capture_output=True, text=True)
                try:
                    dur = float(pr.stdout.strip())
                except ValueError:
                    dur = 30.0
            capped = str(OUTPUT_DIR / f"{stem}-{ts}-capped.mp4")
            burn_synced_captions(mp4_out, args.captions_script, dur, capped,
                                 cap_dir=str(OUTPUT_DIR / f"{stem}-{ts}-caps"))
            _sh.move(capped, mp4_out)
        # 3. Poster = the composited first frame; embed it as cover art for Blotato.
        first_frame(mp4_out, thumb_path)

        if not args.no_log:
            log_asset(media=mp4_out, topic=args.topic or derive_topic(values),
                      prompt=args.prompt or args.video_underlay or "", stage="Production",
                      status="Generated", remarks="Reel (clean video underlay + template overlay caption)")

        print(f"video={mp4_out}")
        print(f"overlay={overlay_png}")
        print(f"thumb={thumb_path}")
        return

    # ── Video mode: render thumbnail → embed in mp4 ───────────────────────────
    if args.video:
        thumb_path = str(OUTPUT_DIR / f"{stem}-{ts}-thumb.png")
        mp4_out = args.output or str(OUTPUT_DIR / f"{stem}-{ts}.mp4")

        # Render template as thumbnail (no bg injection — thumbnail is standalone branded card)
        render(args.template, thumb_path, values)
        print(f"[produce] thumbnail → {thumb_path}", file=sys.stderr)

        attach_thumbnail(args.video, thumb_path, mp4_out)

        if not args.no_log:
            log_asset(media=mp4_out, topic=args.topic or derive_topic(values),
                      prompt=args.prompt or args.video or "", stage="Production",
                      status="Generated", remarks="Video reel (mp4 + branded thumbnail)")

        # Print both outputs so callers can pick them up
        print(f"video={mp4_out}")
        print(f"thumb={thumb_path}")
        return

    # ── Image mode: resolve bg → render PNG ───────────────────────────────────
    bg_path = None
    if args.bg_prompt:
        bg_path = bg_generate(args.bg_prompt, model=args.model, aspect="9:16", source=args.bg_source)
    elif args.bg_url:
        bg_path = download_image(args.bg_url)
    elif args.bg_file:
        bg_path = args.bg_file

    output = args.output or str(OUTPUT_DIR / f"{stem}-{ts}.png")
    render(args.template, output, values, bg_path=bg_path)

    if not args.no_log:
        remarks = "Image (Higgsfield bg)" if bg_path else "Image (template only)"
        # Col F provenance: explicit --prompt wins; else the generation prompt
        # (--bg-prompt); else the source the bg came from (url/file). Never blank
        # when a background was used.
        prompt_log = args.prompt or args.bg_prompt or args.bg_url or args.bg_file or ""
        log_asset(media=output, topic=args.topic or derive_topic(values),
                  prompt=prompt_log,
                  stage="Production", status="Generated", remarks=remarks)

    print(output)


if __name__ == "__main__":
    main()
