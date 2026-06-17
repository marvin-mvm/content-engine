"""
overlay.py — Acme Labs canonical text overlay engine.
Version 2.0 — 2026-05-26

Three-tier system (locked brand spec):
  Heading  — large bold, upper-left, 7% safe-zone margin, 2–5 words
  Kicker   — small ALL CAPS label above heading, 40% of heading size, Forest Green
  Caption  — bottom-center, 2 lines max, medium weight, dark scrim behind

One font family. Fixed type scale: Heading 1.0 / Kicker 0.4 / Caption 0.55
Universal entrance: fade-up 0.3s ease-out, 18px travel, applied to every tier.

Usage:
    from overlay import burn_overlays
    burn_overlays("input.mp4", "output.mp4", SEGMENTS)

SEGMENTS format:
    [
        {
            "start": 0.0,          # seconds
            "end":   2.5,          # seconds
            "kicker":  "RESEARCH PEPTIDES · 2026",   # optional
            "heading": "The Industry\nIs Changing",   # optional, \n for forced break
            "caption": "Line one text\nLine two text" # optional, \n for line break
        },
        ...
    ]
"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import subprocess
import os
import sys

# ── Brand constants (Acme canonical — from BRAND.md) ───────────────────────

WARM_CREAM    = (230, 225, 216)   # Foreground: HSL 40 15% 90% = #e6e1d8
SAGE_GREEN    = (63,  130, 95)    # Primary: HSL 152 35% 38% = #3f825f
SAGE_LIGHT    = (107, 163, 131)   # Sage Light: HSL 152 30% 55% = #6ba383
MUTED_FG      = (122, 127, 138)   # Muted foreground: HSL 220 10% 55% = #7a7f8a
DARK_BG       = (16,  19,  26)    # Background: HSL 220 20% 8% = #10131a

# Legacy aliases kept for any external callers
FOREST_GREEN  = SAGE_GREEN
MINT          = SAGE_LIGHT
COOL_GREY     = MUTED_FG
ALMOST_BLACK  = DARK_BG

# Type scale — base 72px at 1080×1920
HEADING_SIZE  = 110  # Bebas Neue is condensed — can go big
KICKER_SIZE   = int(HEADING_SIZE * 0.38)   # ~42px
CAPTION_SIZE  = 58   # Bold impact captions — slightly smaller than heading

# Safe zone: 7% of 1080px width = 76px
SAFE_X = 76
SAFE_Y_TOP    = 135   # Top safe zone
SAFE_Y_BOTTOM = 135   # Bottom safe zone
CANVAS_W      = 1080
CANVAS_H      = 1920

# Position anchors
KICKER_Y   = SAFE_Y_TOP + 13          # 148px from top
HEADING_Y  = KICKER_Y + KICKER_SIZE + 12  # ~190px — just below kicker
CAPTION_Y  = CANVAS_H - SAFE_Y_BOTTOM - CAPTION_SIZE * 2 - 40  # bottom region

# Stroke weights per tier
STROKE         = 4   # px outline stroke for heading (Bebas Neue)
CAPTION_STROKE = 0   # Cormorant Garamond has natural contrast — no outline needed

# Entrance animation
FADE_UP_FRAMES   = 7    # 0.3s at 24fps ≈ 7 frames
FADE_UP_DISTANCE = 18   # px of upward travel

# Caption scrim
SCRIM_OPACITY   = 0.55
SCRIM_PAD_X     = 0     # full width
SCRIM_PAD_Y     = 16    # vertical padding above/below text

# ── Font loading ───────────────────────────────────────────────────────────────

FONT_PATHS = {
    # Bebas Neue — condensed display for kicker/heading (all-caps)
    "display": [
        "/Users/operator/Library/Fonts/BebasNeue-Regular.ttf",
        "/Library/Fonts/BebasNeue-Regular.ttf",
        "/tmp/BebasNeue-Regular.ttf",
    ],
    # Cormorant Garamond Italic — flowing serif italic for captions
    # Use the variable font (valid TTF) — SemiBold Italic weight via index
    "caption": [
        "/Users/operator/Library/Fonts/CormorantGaramond-Italic[wght].ttf",
        "/Users/operator/Library/Fonts/CormorantGaramond-SemiBoldItalic.ttf",
        "/Users/operator/Library/Fonts/CormorantGaramond-BoldItalic.ttf",
        "/Users/operator/Library/Fonts/CormorantGaramond-Italic.ttf",
    ],
    # Bold sans fallback
    "bold": [
        "/tmp/schibsted/SchibstedGrotesk-Bold.ttf",
        "/tmp/SchibstedGrotesk-Bold.ttf",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
    ],
    "regular": [
        "/tmp/schibsted/SchibstedGrotesk-Regular.ttf",
        "/tmp/SchibstedGrotesk-Regular.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial.ttf",
    ],
    "medium": [
        "/tmp/schibsted/SchibstedGrotesk-Medium.ttf",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
    ],
}

_font_cache = {}

def get_font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    key = (weight, size)
    if key in _font_cache:
        return _font_cache[key]
    for path in FONT_PATHS.get(weight, FONT_PATHS["bold"]):
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                _font_cache[key] = font
                return font
            except Exception:
                continue
    font = ImageFont.load_default()
    _font_cache[key] = font
    return font


# ── Fade-up interpolation ──────────────────────────────────────────────────────

def fade_up_alpha_y(frame_in_segment: int, base_y: int) -> tuple[float, int]:
    """
    Returns (alpha 0.0–1.0, y_offset) for a given frame index within a segment.
    Applies fade-up entrance over FADE_UP_FRAMES frames.
    """
    if frame_in_segment >= FADE_UP_FRAMES:
        return 1.0, 0
    t = frame_in_segment / FADE_UP_FRAMES           # 0→1
    alpha = t                                        # linear alpha
    y_offset = int(FADE_UP_DISTANCE * (1.0 - t))    # starts offset down, travels up
    return alpha, y_offset


# ── Text rendering helpers ─────────────────────────────────────────────────────

def draw_text_with_shadow(
    draw: ImageDraw.Draw,
    text: str,
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont,
    color: tuple,
    alpha: float = 1.0,
    shadow_offset: int = 2,
    shadow_alpha: float = 0.7,
):
    """Draw text with drop shadow. Alpha is blended at composite stage."""
    shadow_color = tuple(int(c * (1 - alpha) + 0 * alpha * shadow_alpha) for c in (0, 0, 0))
    # Shadow
    draw.text(
        (x + shadow_offset, y + shadow_offset),
        text,
        font=font,
        fill=(*shadow_color, int(255 * alpha * shadow_alpha)),
    )
    # Main text
    draw.text(
        (x, y),
        text,
        font=font,
        fill=(*color, int(255 * alpha)),
    )


def measure_text(draw: ImageDraw.Draw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def draw_caption_scrim(
    img: Image.Image,
    caption_lines: list[str],
    font: ImageFont.FreeTypeFont,
    y_start: int,
    alpha: float,
):
    """Draw a full-width semi-transparent scrim bar behind caption text."""
    draw = ImageDraw.Draw(img)
    line_h = CAPTION_SIZE + 8
    total_h = len(caption_lines) * line_h + SCRIM_PAD_Y * 2
    scrim = Image.new("RGBA", (CANVAS_W, total_h), (0, 0, 0, 0))
    scrim_draw = ImageDraw.Draw(scrim)
    scrim_draw.rectangle(
        [0, 0, CANVAS_W, total_h],
        fill=(0, 0, 0, int(255 * SCRIM_OPACITY * alpha)),
    )
    img.paste(scrim, (0, y_start - SCRIM_PAD_Y), scrim)


# ── Main render function ───────────────────────────────────────────────────────

def render_overlays_on_frame(
    frame_bgr: np.ndarray,
    t: float,
    segment: dict,
    seg_start: float,
    fps: float,
) -> np.ndarray:
    """
    Apply brand-standard overlays to a single BGR frame.
    t           — current timestamp in seconds
    segment     — dict with keys: start, end, kicker?, heading?, caption?
    seg_start   — segment start time (for fade-up calculation)
    fps         — video fps
    """
    frame_in_seg = int((t - seg_start) * fps)

    # Convert to RGBA PIL for compositing
    pil = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)).convert("RGBA")
    overlay = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    kicker_text  = segment.get("kicker", "")
    heading_text = segment.get("heading", "")
    caption_text = segment.get("caption", "")

    # ── Kicker ─────────────────────────────────────────────────────────────────
    if kicker_text:
        font_k = get_font("regular", KICKER_SIZE)
        alpha_k, dy_k = fade_up_alpha_y(frame_in_seg, KICKER_Y)
        # Kicker: centered
        kicker_upper = kicker_text.upper()
        kw, _ = measure_text(draw, kicker_upper, font_k)
        kx = (CANVAS_W - kw) // 2
        draw.text(
            (kx, KICKER_Y + dy_k),
            kicker_upper,
            font=font_k,
            fill=(*FOREST_GREEN, int(255 * alpha_k)),
        )

    # ── Heading ────────────────────────────────────────────────────────────────
    # Heading — Bebas Neue, ALL CAPS, centered. Line 1 = Warm Cream, Line 2 = Sage Light (brand).
    if heading_text:
        font_h = get_font("display", HEADING_SIZE)
        alpha_h, dy_h = fade_up_alpha_y(frame_in_seg, HEADING_Y)
        lines = [l.upper() for l in heading_text.split("\n")]
        y_cursor = HEADING_Y + dy_h
        for i, line in enumerate(lines):
            lw, lh = measure_text(draw, line, font_h)
            cx = (CANVAS_W - lw) // 2
            # Line 1: Warm Cream | Line 2: Sage Light green (brand accent)
            line_color = WARM_CREAM if i == 0 else SAGE_LIGHT
            # Dark stroke for legibility over footage
            for ox in range(-STROKE, STROKE + 1):
                for oy in range(-STROKE, STROKE + 1):
                    if ox == 0 and oy == 0:
                        continue
                    draw.text(
                        (cx + ox, y_cursor + oy),
                        line,
                        font=font_h,
                        fill=(*DARK_BG, int(255 * alpha_h)),
                    )
            draw.text(
                (cx, y_cursor),
                line,
                font=font_h,
                fill=(*line_color, int(255 * alpha_h)),
            )
            y_cursor += lh + 8

    # ── Caption ────────────────────────────────────────────────────────────────
    # Captions are INDEPENDENT of heading — own fade-up, never tied to heading.
    if caption_text:
        font_c = get_font("caption", CAPTION_SIZE)   # Cormorant Garamond Italic
        alpha_c, dy_c = fade_up_alpha_y(frame_in_seg, CAPTION_Y)
        lines = caption_text.split("\n")[:2]

        # Draw scrim on base image first
        scrim_y = CAPTION_Y + dy_c - SCRIM_PAD_Y
        line_spacing = CAPTION_SIZE + 12
        scrim_h = len(lines) * line_spacing + SCRIM_PAD_Y * 2
        scrim_layer = Image.new("RGBA", (CANVAS_W, scrim_h), (0, 0, 0, 0))
        ImageDraw.Draw(scrim_layer).rectangle(
            [0, 0, CANVAS_W, scrim_h],
            fill=(0, 0, 0, int(255 * SCRIM_OPACITY * alpha_c)),
        )
        overlay.paste(scrim_layer, (0, max(0, scrim_y)), scrim_layer)

        # Draw caption lines centered with stroke outline for extra thickness
        draw2 = ImageDraw.Draw(overlay)
        y_cursor = CAPTION_Y + dy_c
        for line in lines:
            tw, _ = measure_text(draw2, line, font_c)
            cx = (CANVAS_W - tw) // 2
            # Drop-shadow for Cormorant italic legibility
            draw2.text(
                (cx + 3, y_cursor + 3),
                line,
                font=font_c,
                fill=(*DARK_BG, int(255 * alpha_c * 0.85)),
            )
            # Captions: Warm Cream (brand foreground)
            draw2.text(
                (cx, y_cursor),
                line,
                font=font_c,
                fill=(*WARM_CREAM, int(255 * alpha_c)),
            )
            y_cursor += line_spacing

    # Composite overlay onto frame
    composited = Image.alpha_composite(pil, overlay)
    return cv2.cvtColor(np.array(composited.convert("RGB")), cv2.COLOR_RGB2BGR)


# ── Main burn function ─────────────────────────────────────────────────────────

def burn_overlays(
    input_path: str,
    output_path: str,
    segments: list[dict],
    audio_source: str | None = None,
) -> str:
    """
    Burn brand-standard overlays into a video.

    input_path   — source video (no text)
    output_path  — output path for final video
    segments     — list of segment dicts (start/end/kicker/heading/caption)
    audio_source — if None, copies audio from input_path

    Returns output_path on success.
    """
    cap = cv2.VideoCapture(input_path)
    fps    = cap.get(cv2.CAP_PROP_FPS) or 24.0
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    tmp_video = output_path.replace(".mp4", "_noaudio.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(tmp_video, fourcc, fps, (width, height))

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        t = frame_idx / fps

        # Find active segment
        active_seg = None
        for seg in segments:
            if seg["start"] <= t < seg["end"]:
                active_seg = seg
                break

        if active_seg:
            frame = render_overlays_on_frame(frame, t, active_seg, active_seg["start"], fps)

        writer.write(frame)
        frame_idx += 1

    cap.release()
    writer.release()
    print(f"[overlay] Processed {frame_idx} frames @ {fps:.1f}fps → {tmp_video}", file=sys.stderr)

    # Mux audio
    audio_src = audio_source or input_path
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", tmp_video,
            "-i", audio_src,
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-c:a", "aac", "-shortest",
            output_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Fallback: video only
        subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_video,
             "-c:v", "libx264", "-crf", "18", "-preset", "fast", output_path],
            check=True, capture_output=True,
        )
        print("[overlay] Warning: audio mux failed, output is video-only", file=sys.stderr)

    os.remove(tmp_video)
    print(f"[overlay] Final → {output_path}", file=sys.stderr)
    return output_path


# ── CLI convenience ────────────────────────────────────────────────────────────
# python3 overlay.py input.mp4 output.mp4  (uses built-in test segments)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 overlay.py <input.mp4> <output.mp4>")
        sys.exit(1)

    TEST_SEGMENTS = [
        {
            "start": 0.0, "end": 2.5,
            "kicker":  "PHYSICIAN-LED · PHARMACEUTICAL-GRADE",
            "heading": "The Industry\nIs Changing",
        },
        {
            "start": 2.5, "end": 5.0,
            "kicker":  "RESEARCH PEPTIDES · 2026",
            "heading": "Peptides",
            "caption": "$52.6B global market\n+652% search growth",
        },
        {
            "start": 5.0, "end": 7.5,
            "kicker":  "ACCELERATED RECOVERY",
            "heading": "BPC-157\nTB-500 · GLP-1",
        },
        {
            "start": 7.5, "end": 10.1,
            "heading": "Acme Labs",
            "caption": "For research use only\nNot FDA approved",
        },
    ]

    burn_overlays(sys.argv[1], sys.argv[2], TEST_SEGMENTS)
    print(f"Done → {sys.argv[2]}")
