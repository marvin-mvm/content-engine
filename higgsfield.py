#!/usr/bin/env python3
"""
Higgsfield CLI wrapper for ACME agent.

PRIMARY content generation engine — images, videos, product shots, Marketing Studio DTC ads.

Usage:
  higgsfield.py auth-status
  higgsfield.py credits
  higgsfield.py models                    [--type image|video|text]
  higgsfield.py upload                    FILE
  higgsfield.py uploads                   [--type image|video|audio]
  higgsfield.py soul-create               NAME --image ID [--image ID ...] [--soul-2] [--no-wait]
  higgsfield.py soul-list
  higgsfield.py soul-get                  SOUL_ID
  higgsfield.py image                     PROMPT [--model M] [--ref ID ...] [--soul ID]
                                          [--aspect 16:9|9:16|1:1|4:5] [--no-cinematic] [--no-wait]
  higgsfield.py video                     PROMPT [--model M] [--image ID] [--soul ID]
                                          [--aspect 16:9|9:16] [--duration N] [--no-cinematic] [--no-wait]
  higgsfield.py product                   PROMPT --product-image ID [--mode lifestyle|studio|model]
                                          [--brand-context TEXT] [--product-context TEXT] [--count N]
  higgsfield.py marketplace-card          PROMPT --product-image ID [--no-wait]
  higgsfield.py job                       JOB_ID
  higgsfield.py wait                      JOB_ID [--timeout N]
  higgsfield.py jobs                      [--type image|video]

  -- Marketing Studio (DTC Ads Engine / Supercomputer) --
  higgsfield.py ms-brand-kit-list
  higgsfield.py ms-brand-kit-fetch        URL [--no-wait]
  higgsfield.py ms-brand-kit-get          BRAND_KIT_ID
  higgsfield.py ms-product-list
  higgsfield.py ms-product-create         TITLE --image ID [--image ID ...] [--description TEXT]
  higgsfield.py ms-product-fetch          URL [--no-wait]
  higgsfield.py ms-avatar-list
  higgsfield.py ms-avatar-create          NAME --image ID
  higgsfield.py ms-ad-format-list         [--type headline]
  higgsfield.py ms-ad-ref-list
  higgsfield.py ms-ad-ref-create          --video-input ID [--avatar ID] [--product ID]
  higgsfield.py ms-hook-list              [--search TERM]
  higgsfield.py ms-setting-list           [--search TERM]
  higgsfield.py ms-dtc                    PROMPT --format-id ID [--brand-kit-id ID] [--product ID]
                                          [--avatar ID] [--media ID ...] [--quality low|medium|high]
                                          [--resolution 1k|2k|4k] [--aspect 1:1|9:16|16:9]
                                          [--batch N] [--no-wait]

  -- Apps (web UI features, all via generate pipeline) --
  higgsfield.py influencer                PROMPT --avatar ID [--product ID] [--hook-id ID]
                                          [--setting-id ID] [--ad-ref-id ID] [--aspect 9:16|16:9|1:1]
                                          [--mode ugc|product_showcase|product_review|tv_spot|ugc_unboxing|wild_card|virtual_try_on]
                                          [--duration N] [--audio] [--no-wait]
  higgsfield.py virality                  --media ID [--media ID ...]
  higgsfield.py upscale                   --video ID [--resolution 1080p|2160p] [--fps 30|60]
  higgsfield.py reframe                   --media ID --aspect 9:16|16:9|1:1 [--resolution 720p|1080p]
  higgsfield.py draw-to-video             PROMPT --video ID [--sketch ID] [--audio] [--aspect 9:16|16:9]
  higgsfield.py soul-cinematic            PROMPT [--soul ID] [--aspect 1:1|16:9|9:16] [--quality 1.5k|2k]
  higgsfield.py soul-location             PROMPT [--aspect 1:1|16:9|9:16]
"""

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

CLI = "higgsfield"

CINEMATIC_SUFFIX_VIDEO = (
    " — cinematic shot, anamorphic lens, shallow depth of field, soft side lighting, "
    "subtle film grain, 24fps motion, color graded toward deep forest green and warm cream, "
    "premium biotech editorial aesthetic"
)
CINEMATIC_SUFFIX_IMAGE = (
    " — high-end editorial photography, soft natural rim lighting, shallow depth of field, "
    "85mm lens look, refined color palette, premium biotech / longevity brand aesthetic"
)

# These models reject --aspect-ratio flag; bake aspect into the prompt instead.
MODELS_NO_ASPECT_FLAG = {"kling3_0", "seedance_2_0"}


def run(cmd, capture=True, check=True):
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    full = [CLI] + cmd
    result = subprocess.run(full, capture_output=capture, text=True)
    if check and result.returncode != 0:
        sys.exit(f"ERROR: `{' '.join(full)}` failed:\n{result.stderr.strip() or result.stdout.strip()}")
    return result


def run_json(args):
    result = run(args + ["--json"])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"raw": result.stdout.strip()}


# ── Auth / account ────────────────────────────────────────────────────────────

def cmd_auth_status():
    r = run(["auth", "token"], check=False)
    if r.returncode != 0:
        print(json.dumps({"authenticated": False, "hint": "Run: higgsfield auth login"}))
        sys.exit(1)
    print(json.dumps({"authenticated": True, "token_present": bool(r.stdout.strip())}))


def cmd_credits():
    print(json.dumps(run_json(["account", "status"]), indent=2))


def cmd_models(type_filter):
    args = ["model", "list"]
    if type_filter:
        args.append(f"--{type_filter}")
    print(json.dumps(run_json(args), indent=2))


# ── Uploads ───────────────────────────────────────────────────────────────────

def cmd_upload(file_path):
    if not Path(file_path).exists():
        sys.exit(f"ERROR: file not found: {file_path}")
    print(json.dumps(run_json(["upload", "create", file_path]), indent=2))


def cmd_uploads_list(type_filter):
    args = ["upload", "list"]
    if type_filter:
        args.append(f"--{type_filter}")
    print(json.dumps(run_json(args), indent=2))


# ── Soul-ID ───────────────────────────────────────────────────────────────────

def cmd_soul_create(name, image_ids, soul_2, wait):
    args = ["soul-id", "create", "--name", name]
    if soul_2:
        args.append("--soul-2")
    for img in image_ids:
        args += ["--image", img]
    result = run_json(args)
    soul_id = result.get("id") or result.get("soul_id")
    print(json.dumps(result, indent=2))
    if wait and soul_id:
        print(f"[acme-higgsfield] training soul-id {soul_id}...", file=sys.stderr)
        run(["soul-id", "wait", soul_id])
        print(json.dumps(run_json(["soul-id", "get", soul_id]), indent=2))


def cmd_soul_list():
    print(json.dumps(run_json(["soul-id", "list"]), indent=2))


def cmd_soul_get(soul_id):
    print(json.dumps(run_json(["soul-id", "get", soul_id]), indent=2))


# ── Image generation ──────────────────────────────────────────────────────────

def cmd_image(prompt, model, refs, soul, no_cinematic, aspect, no_wait):
    if not no_cinematic:
        prompt = prompt.rstrip() + CINEMATIC_SUFFIX_IMAGE
    if aspect and model in MODELS_NO_ASPECT_FLAG:
        prompt = f"{prompt.rstrip()} — {aspect} aspect ratio"
        print(f"[acme-higgsfield] note: {model} ignores --aspect-ratio; baked '{aspect}' into prompt.", file=sys.stderr)
        aspect = None
    args = ["generate", "create", model, "--prompt", prompt]
    for ref in refs or []:
        args += ["--image", ref]
    if soul:
        args += ["--soul-id", soul]
    if aspect:
        args += ["--aspect-ratio", aspect]
    _handle_job_result(run_json(args), no_wait, "image")


# ── Video generation ──────────────────────────────────────────────────────────

def cmd_video(prompt, model, image, soul, no_cinematic, aspect, duration, no_wait):
    if not no_cinematic:
        prompt = prompt.rstrip() + CINEMATIC_SUFFIX_VIDEO
    if aspect and model in MODELS_NO_ASPECT_FLAG:
        prompt = f"{prompt.rstrip()} — {aspect} aspect ratio"
        print(f"[acme-higgsfield] note: {model} ignores --aspect-ratio; baked '{aspect}' into prompt.", file=sys.stderr)
        aspect = None
    args = ["generate", "create", model, "--prompt", prompt]
    if image:
        args += ["--image", image]
    if soul:
        args += ["--soul-id", soul]
    if aspect:
        args += ["--aspect-ratio", aspect]
    if duration:
        args += ["--duration", str(duration)]
    _handle_job_result(run_json(args), no_wait, "video")


# ── Product photoshoot ────────────────────────────────────────────────────────

def cmd_product(prompt, product_image, mode, brand_context, product_context, count):
    args = ["product-photoshoot", "create", "--prompt", prompt, "--image", product_image]
    if mode:
        args += ["--mode", mode]
    if brand_context:
        args += ["--brand_context", brand_context]
    if product_context:
        args += ["--product_context", product_context]
    if count and count > 1:
        args += ["--count", str(count)]
    print(json.dumps(run_json(args), indent=2))


# ── Marketplace card ──────────────────────────────────────────────────────────

def cmd_marketplace_card(prompt, product_image, no_wait):
    args = ["marketplace-cards", "create", "--prompt", prompt, "--image", product_image]
    _handle_job_result(run_json(args), no_wait, "marketplace-card")


# ── Job helpers ───────────────────────────────────────────────────────────────

def _handle_job_result(result, no_wait, kind):
    if isinstance(result, list) and result:
        result = result[0]
    # `generate create … --json` returns the new job id as a BARE string, not an
    # object — normalize it so a successful submit isn't mistaken for an error
    # (this mis-handling caused a double-submit once: the crash hid a real job id).
    if isinstance(result, str):
        result = {"id": result}
    if not isinstance(result, dict):
        print(json.dumps({"kind": kind, "error": "unexpected (non-object) response from higgsfield",
                          "raw": result}, ensure_ascii=False, indent=2))
        return
    job_id = result.get("id") or result.get("job_id")
    if not job_id:
        print(json.dumps(result, indent=2))
        return
    if no_wait:
        print(json.dumps({"job_id": job_id, "kind": kind, "status": "pending"}, indent=2))
        return
    print(f"[acme-higgsfield] {kind} job_id={job_id} — polling until complete...", file=sys.stderr)
    run(["generate", "wait", job_id])
    print(json.dumps(_clean_job_output(run_json(["generate", "get", job_id]), kind), ensure_ascii=False, indent=2))


def _clean_job_output(job, kind):
    if not isinstance(job, dict):
        return {"kind": kind, "raw": job}
    return {k: v for k, v in {
        "kind": kind,
        "job_id": job.get("id") or job.get("job_id"),
        "status": job.get("status"),
        "url": job.get("url") or job.get("output_url") or job.get("result_url"),
        "thumbnail": job.get("thumbnail") or job.get("preview_url"),
        "duration": job.get("duration"),
        "aspect_ratio": job.get("aspect_ratio"),
        "model": job.get("model"),
    }.items() if v is not None}


def cmd_job(job_id):
    print(json.dumps(_clean_job_output(run_json(["generate", "get", job_id]), "job"), indent=2))


def cmd_wait(job_id, timeout):
    args = ["generate", "wait", job_id]
    if timeout:
        args += ["--timeout", str(timeout)]
    run(args)
    print(json.dumps(_clean_job_output(run_json(["generate", "get", job_id]), "job"), indent=2))


def cmd_jobs(type_filter):
    args = ["generate", "list"]
    if type_filter:
        args.append(f"--{type_filter}")
    print(json.dumps(run_json(args), indent=2))


# ── Marketing Studio — Brand Kits ─────────────────────────────────────────────

def cmd_ms_brand_kit_list():
    print(json.dumps(run_json(["marketing-studio", "brand-kits", "list"]), indent=2))


def cmd_ms_brand_kit_fetch(url, no_wait):
    args = ["marketing-studio", "brand-kits", "fetch", "--url", url]
    if not no_wait:
        args.append("--wait")
    print(json.dumps(run_json(args), indent=2))


def cmd_ms_brand_kit_get(brand_kit_id):
    print(json.dumps(run_json(["marketing-studio", "brand-kits", "get", brand_kit_id]), indent=2))


# ── Marketing Studio — Products ───────────────────────────────────────────────

def cmd_ms_product_list():
    print(json.dumps(run_json(["marketing-studio", "products", "list"]), indent=2))


def cmd_ms_product_create(title, image_ids, description):
    args = ["marketing-studio", "products", "create", "--title", title]
    for img in image_ids:
        args += ["--image", img]
    if description:
        args += ["--description", description]
    print(json.dumps(run_json(args), indent=2))


def cmd_ms_product_fetch(url, no_wait):
    args = ["marketing-studio", "products", "fetch", "--url", url]
    if not no_wait:
        args.append("--wait")
    print(json.dumps(run_json(args), indent=2))


# ── Marketing Studio — Web Products ──────────────────────────────────────────

def cmd_ms_webproduct_list():
    print(json.dumps(run_json(["marketing-studio", "webproducts", "list"]), indent=2))


def cmd_ms_webproduct_fetch(url, no_wait):
    args = ["marketing-studio", "webproducts", "fetch", "--url", url]
    if not no_wait:
        args.append("--wait")
    print(json.dumps(run_json(args), indent=2))


# ── Marketing Studio — Avatars ────────────────────────────────────────────────

def cmd_ms_avatar_list():
    print(json.dumps(run_json(["marketing-studio", "avatars", "list"]), indent=2))


def cmd_ms_avatar_create(name, image_id):
    print(json.dumps(run_json(["marketing-studio", "avatars", "create", "--name", name, "--image", image_id]), indent=2))


# ── Marketing Studio — Ad Formats ─────────────────────────────────────────────

def cmd_ms_ad_format_list(type_filter):
    args = ["marketing-studio", "ad-formats", "list"]
    if type_filter:
        args += ["--type", type_filter]
    print(json.dumps(run_json(args), indent=2))


# ── Marketing Studio — Ad References ─────────────────────────────────────────

def cmd_ms_ad_ref_list():
    print(json.dumps(run_json(["marketing-studio", "ad-references", "list"]), indent=2))


def cmd_ms_ad_ref_create(video_input, avatar, product):
    args = ["marketing-studio", "ad-references", "create", "--video-input", video_input]
    if avatar:
        args += ["--avatar", avatar]
    if product:
        args += ["--product", product]
    print(json.dumps(run_json(args), indent=2))


# ── Marketing Studio — Hooks & Settings (video scenarios) ────────────────────

def cmd_ms_hook_list(search):
    args = ["marketing-studio", "hooks", "list"]
    if search:
        args += ["--search", search]
    print(json.dumps(run_json(args), indent=2))


def cmd_ms_setting_list(search):
    args = ["marketing-studio", "settings", "list"]
    if search:
        args += ["--search", search]
    print(json.dumps(run_json(args), indent=2))


# ── Marketing Studio — DTC Ads Engine (the AI agent) ─────────────────────────

def cmd_ms_dtc(prompt, format_id, brand_kit_id, product_id, avatar_id, media_ids, quality, resolution, aspect, batch, no_wait):
    args = ["marketing-studio", "dtc-ads", "generate", "--prompt", prompt, "--format-id", format_id]
    if brand_kit_id:
        args += ["--brand-kit-id", brand_kit_id]
    if product_id:
        args += ["--product", product_id]
    if avatar_id:
        args += ["--avatar", avatar_id]
    for m in media_ids or []:
        args += ["--media", m]
    if quality:
        args += ["--quality", quality]
    if resolution:
        args += ["--resolution", resolution]
    if aspect:
        args += ["--aspect-ratio", aspect]
    if batch and batch > 1:
        args += ["--batch-size", str(batch)]
    if not no_wait:
        args.append("--wait")
    print(json.dumps(run_json(args), indent=2))


# ── Apps — AI Influencer / Marketing Studio Video ────────────────────────────

def cmd_influencer(prompt, avatar_id, product_ids, hook_id, setting_id, ad_ref_id, aspect, mode, duration, audio, no_wait):
    """marketing_studio_video — AI Influencer, Shots, UGC, TV Spot, virtual try-on."""
    args = ["generate", "create", "marketing_studio_video", "--prompt", prompt]
    if avatar_id:
        args += ["--avatar", avatar_id]
    for pid in product_ids or []:
        args += ["--product_ids", pid]
    if hook_id:
        args += ["--hook_id", hook_id]
    if setting_id:
        args += ["--setting_id", setting_id]
    if ad_ref_id:
        args += ["--ad_reference_id", ad_ref_id]
    if aspect:
        args += ["--aspect_ratio", aspect]
    if mode:
        args += ["--mode", mode]
    if duration:
        args += ["--duration", str(duration)]
    if audio:
        args += ["--generate_audio", "true"]
    _handle_job_result(run_json(args), no_wait, "influencer-video")


# ── Apps — Virality Predictor ─────────────────────────────────────────────────

def cmd_virality(media_ids):
    """brain_activity — analyze media and predict virality. Returns text analysis."""
    args = ["generate", "create", "brain_activity"]
    for mid in media_ids:
        args += ["--medias", mid]
    print(json.dumps(run_json(args), indent=2))


# ── Apps — Video Tools ────────────────────────────────────────────────────────

def cmd_upscale(video_id, resolution, fps, no_wait):
    """topaz_video — upscale/enhance video up to 4K with frame interpolation."""
    args = ["generate", "create", "topaz_video", "--input_video", video_id,
            "--resolution", resolution or "1080p"]
    if fps:
        args += ["--frame_rate", str(fps)]
    _handle_job_result(run_json(args), no_wait, "upscale")


def cmd_reframe(media_ids, aspect, resolution, no_wait):
    """reframe — recut video to a different aspect ratio."""
    args = ["generate", "create", "reframe", "--aspect_ratio", aspect,
            "--resolution", resolution or "720p"]
    for mid in media_ids:
        args += ["--medias", mid]
    _handle_job_result(run_json(args), no_wait, "reframe")


def cmd_draw_to_video(prompt, video_id, sketch_id, audio, aspect, no_wait):
    """draw_to_video — animate a sketch/drawing into video, optionally with audio."""
    args = ["generate", "create", "draw_to_video", "--prompt", prompt, "--video", video_id]
    if sketch_id:
        args += ["--sketch", sketch_id]
    if audio:
        args += ["--generate_audio", "true"]
    if aspect:
        args += ["--aspect_ratio", aspect]
    _handle_job_result(run_json(args), no_wait, "draw-to-video")


# ── Apps — Soul Features ──────────────────────────────────────────────────────

def cmd_soul_cinematic(prompt, soul_id, aspect, quality, no_wait):
    """soul_cinematic — high-res image with Soul-ID character, 1.5k or 2k quality."""
    args = ["generate", "create", "soul_cinematic", "--prompt", prompt]
    if soul_id:
        args += ["--custom_reference_id", soul_id]
    if aspect:
        args += ["--aspect_ratio", aspect]
    if quality:
        args += ["--quality", quality]
    _handle_job_result(run_json(args), no_wait, "soul-cinematic")


def cmd_soul_location(prompt, aspect, no_wait):
    """soul_location — place a Soul-ID character in a specific location/setting."""
    args = ["generate", "create", "soul_location", "--prompt", prompt]
    if aspect:
        args += ["--aspect_ratio", aspect]
    _handle_job_result(run_json(args), no_wait, "soul-location")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(prog="acme-higgsfield", description="Higgsfield content engine for Acme")
    sub = p.add_subparsers(dest="cmd", required=True)

    # ── Account
    sub.add_parser("auth-status")
    sub.add_parser("credits")
    m = sub.add_parser("models")
    m.add_argument("--type", choices=["image", "video", "text"])

    # ── Uploads
    u = sub.add_parser("upload")
    u.add_argument("file")
    ul = sub.add_parser("uploads")
    ul.add_argument("--type", choices=["image", "video", "audio"])

    # ── Soul-ID
    sc = sub.add_parser("soul-create")
    sc.add_argument("name")
    sc.add_argument("--image", action="append", required=True)
    sc.add_argument("--soul-2", action="store_true")
    sc.add_argument("--no-wait", action="store_true")
    sub.add_parser("soul-list")
    sg = sub.add_parser("soul-get")
    sg.add_argument("soul_id")

    # ── Image
    img = sub.add_parser("image")
    img.add_argument("prompt")
    img.add_argument("--model", default="cinematic_studio_2_5")
    img.add_argument("--ref", action="append", dest="refs")
    img.add_argument("--soul")
    img.add_argument("--no-cinematic", action="store_true")
    img.add_argument("--aspect")
    img.add_argument("--no-wait", action="store_true")

    # ── Video
    vid = sub.add_parser("video")
    vid.add_argument("prompt")
    vid.add_argument("--model", default="cinematic_studio_3_0")
    vid.add_argument("--image")
    vid.add_argument("--soul")
    vid.add_argument("--no-cinematic", action="store_true")
    vid.add_argument("--aspect")
    vid.add_argument("--duration", type=int)
    vid.add_argument("--no-wait", action="store_true")

    # ── Product photoshoot
    prod = sub.add_parser("product")
    prod.add_argument("prompt")
    prod.add_argument("--product-image", required=True)
    prod.add_argument("--mode", choices=["lifestyle", "studio", "model"])
    prod.add_argument("--brand-context")
    prod.add_argument("--product-context")
    prod.add_argument("--count", type=int, default=1)

    # ── Marketplace card
    mp = sub.add_parser("marketplace-card")
    mp.add_argument("prompt")
    mp.add_argument("--product-image", required=True)
    mp.add_argument("--no-wait", action="store_true")

    # ── Job helpers
    j = sub.add_parser("job")
    j.add_argument("job_id")
    w = sub.add_parser("wait")
    w.add_argument("job_id")
    w.add_argument("--timeout", type=int)
    jl = sub.add_parser("jobs")
    jl.add_argument("--type", choices=["image", "video"])

    # ── Marketing Studio — Brand Kits
    sub.add_parser("ms-brand-kit-list")
    bkf = sub.add_parser("ms-brand-kit-fetch")
    bkf.add_argument("url")
    bkf.add_argument("--no-wait", action="store_true")
    bkg = sub.add_parser("ms-brand-kit-get")
    bkg.add_argument("brand_kit_id")

    # ── Marketing Studio — Products
    sub.add_parser("ms-product-list")
    mpc = sub.add_parser("ms-product-create")
    mpc.add_argument("title")
    mpc.add_argument("--image", action="append", required=True)
    mpc.add_argument("--description")
    mpf = sub.add_parser("ms-product-fetch")
    mpf.add_argument("url")
    mpf.add_argument("--no-wait", action="store_true")

    # ── Marketing Studio — Web Products
    sub.add_parser("ms-webproduct-list")
    wpf = sub.add_parser("ms-webproduct-fetch")
    wpf.add_argument("url")
    wpf.add_argument("--no-wait", action="store_true")

    # ── Marketing Studio — Avatars
    sub.add_parser("ms-avatar-list")
    mac = sub.add_parser("ms-avatar-create")
    mac.add_argument("name")
    mac.add_argument("--image", required=True)

    # ── Marketing Studio — Ad Formats
    adf = sub.add_parser("ms-ad-format-list")
    adf.add_argument("--type")

    # ── Marketing Studio — Ad References
    sub.add_parser("ms-ad-ref-list")
    arc = sub.add_parser("ms-ad-ref-create")
    arc.add_argument("--video-input", required=True)
    arc.add_argument("--avatar")
    arc.add_argument("--product")

    # ── Marketing Studio — Hooks & Settings
    hl = sub.add_parser("ms-hook-list")
    hl.add_argument("--search")
    sl = sub.add_parser("ms-setting-list")
    sl.add_argument("--search")

    # ── Marketing Studio — DTC Ads Engine
    dtc = sub.add_parser("ms-dtc")
    dtc.add_argument("prompt")
    dtc.add_argument("--format-id", required=True)
    dtc.add_argument("--brand-kit-id")
    dtc.add_argument("--product")
    dtc.add_argument("--avatar")
    dtc.add_argument("--media", action="append", dest="media_ids", default=[])
    dtc.add_argument("--quality", choices=["low", "medium", "high"], default="medium")
    dtc.add_argument("--resolution", choices=["1k", "2k", "4k"], default="1k")
    dtc.add_argument("--aspect", default="1:1")
    dtc.add_argument("--batch", type=int, default=1)
    dtc.add_argument("--no-wait", action="store_true")

    # ── Apps — AI Influencer
    inf = sub.add_parser("influencer", help="AI Influencer/Shots/UGC video via marketing_studio_video")
    inf.add_argument("prompt")
    inf.add_argument("--avatar")
    inf.add_argument("--product", action="append", dest="product_ids", default=[])
    inf.add_argument("--hook-id")
    inf.add_argument("--setting-id")
    inf.add_argument("--ad-ref-id")
    inf.add_argument("--aspect", default="9:16")
    inf.add_argument("--mode", default="ugc",
                     choices=["ugc","product_showcase","product_review","tv_spot",
                              "ugc_unboxing","ugc_how_to","wild_card",
                              "ugc_virtual_try_on","virtual_try_on"])
    inf.add_argument("--duration", type=int, default=15)
    inf.add_argument("--audio", action="store_true", help="Generate audio track")
    inf.add_argument("--no-wait", action="store_true")

    # ── Apps — Virality Predictor
    vp = sub.add_parser("virality", help="Predict virality of a video/image (brain_activity)")
    vp.add_argument("--media", action="append", dest="media_ids", required=True)

    # ── Apps — Video Tools
    ups = sub.add_parser("upscale", help="Upscale/enhance video to 1080p or 4K (Topaz)")
    ups.add_argument("--video", required=True)
    ups.add_argument("--resolution", choices=["1080p", "2160p"], default="1080p")
    ups.add_argument("--fps", type=int, choices=[24, 30, 60])
    ups.add_argument("--no-wait", action="store_true")

    rf = sub.add_parser("reframe", help="Recut video to a different aspect ratio")
    rf.add_argument("--media", action="append", dest="media_ids", required=True)
    rf.add_argument("--aspect", required=True, help="e.g. 9:16, 16:9, 1:1")
    rf.add_argument("--resolution", choices=["480p", "720p", "1080p"], default="720p")
    rf.add_argument("--no-wait", action="store_true")

    dtv = sub.add_parser("draw-to-video", help="Animate a sketch or drawing into video")
    dtv.add_argument("prompt")
    dtv.add_argument("--video", required=True, help="Source video or drawing upload ID")
    dtv.add_argument("--sketch", help="Sketch overlay upload ID")
    dtv.add_argument("--audio", action="store_true")
    dtv.add_argument("--aspect", default="9:16")
    dtv.add_argument("--no-wait", action="store_true")

    # ── Apps — Soul Features
    sc2 = sub.add_parser("soul-cinematic", help="High-res Soul-ID image (Cinema Studio)")
    sc2.add_argument("prompt")
    sc2.add_argument("--soul", help="Soul-ID / custom reference ID")
    sc2.add_argument("--aspect", default="1:1")
    sc2.add_argument("--quality", choices=["1.5k", "2k"], default="2k")
    sc2.add_argument("--no-wait", action="store_true")

    sloc = sub.add_parser("soul-location", help="Place a Soul character in a specific setting")
    sloc.add_argument("prompt")
    sloc.add_argument("--aspect", default="9:16")
    sloc.add_argument("--no-wait", action="store_true")

    args = p.parse_args()

    dispatch = {
        "auth-status":        lambda: cmd_auth_status(),
        "credits":            lambda: cmd_credits(),
        "models":             lambda: cmd_models(args.type),
        "upload":             lambda: cmd_upload(args.file),
        "uploads":            lambda: cmd_uploads_list(args.type),
        "soul-create":        lambda: cmd_soul_create(args.name, args.image, args.soul_2, not args.no_wait),
        "soul-list":          lambda: cmd_soul_list(),
        "soul-get":           lambda: cmd_soul_get(args.soul_id),
        "image":              lambda: cmd_image(args.prompt, args.model, args.refs, args.soul, args.no_cinematic, args.aspect, args.no_wait),
        "video":              lambda: cmd_video(args.prompt, args.model, args.image, args.soul, args.no_cinematic, args.aspect, args.duration, args.no_wait),
        "product":            lambda: cmd_product(args.prompt, args.product_image, args.mode, args.brand_context, args.product_context, args.count),
        "marketplace-card":   lambda: cmd_marketplace_card(args.prompt, args.product_image, args.no_wait),
        "job":                lambda: cmd_job(args.job_id),
        "wait":               lambda: cmd_wait(args.job_id, args.timeout),
        "jobs":               lambda: cmd_jobs(args.type),
        "ms-brand-kit-list":  lambda: cmd_ms_brand_kit_list(),
        "ms-brand-kit-fetch": lambda: cmd_ms_brand_kit_fetch(args.url, args.no_wait),
        "ms-brand-kit-get":   lambda: cmd_ms_brand_kit_get(args.brand_kit_id),
        "ms-product-list":    lambda: cmd_ms_product_list(),
        "ms-product-create":  lambda: cmd_ms_product_create(args.title, args.image, args.description),
        "ms-product-fetch":   lambda: cmd_ms_product_fetch(args.url, args.no_wait),
        "ms-webproduct-list": lambda: cmd_ms_webproduct_list(),
        "ms-webproduct-fetch":lambda: cmd_ms_webproduct_fetch(args.url, args.no_wait),
        "ms-avatar-list":     lambda: cmd_ms_avatar_list(),
        "ms-avatar-create":   lambda: cmd_ms_avatar_create(args.name, args.image),
        "ms-ad-format-list":  lambda: cmd_ms_ad_format_list(args.type),
        "ms-ad-ref-list":     lambda: cmd_ms_ad_ref_list(),
        "ms-ad-ref-create":   lambda: cmd_ms_ad_ref_create(args.video_input, args.avatar, args.product),
        "ms-hook-list":       lambda: cmd_ms_hook_list(args.search),
        "ms-setting-list":    lambda: cmd_ms_setting_list(args.search),
        "ms-dtc":             lambda: cmd_ms_dtc(args.prompt, args.format_id, args.brand_kit_id, args.product, args.avatar, args.media_ids, args.quality, args.resolution, args.aspect, args.batch, args.no_wait),
        "influencer":         lambda: cmd_influencer(args.prompt, args.avatar, args.product_ids, args.hook_id, args.setting_id, args.ad_ref_id, args.aspect, args.mode, args.duration, args.audio, args.no_wait),
        "virality":           lambda: cmd_virality(args.media_ids),
        "upscale":            lambda: cmd_upscale(args.video, args.resolution, args.fps, args.no_wait),
        "reframe":            lambda: cmd_reframe(args.media_ids, args.aspect, args.resolution, args.no_wait),
        "draw-to-video":      lambda: cmd_draw_to_video(args.prompt, args.video, args.sketch, args.audio, args.aspect, args.no_wait),
        "soul-cinematic":     lambda: cmd_soul_cinematic(args.prompt, args.soul, args.aspect, args.quality, args.no_wait),
        "soul-location":      lambda: cmd_soul_location(args.prompt, args.aspect, args.no_wait),
    }

    fn = dispatch.get(args.cmd)
    if fn:
        fn()
    else:
        p.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
