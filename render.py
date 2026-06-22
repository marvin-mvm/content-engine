"""
render.py — Acme HTML template renderer (Playwright/Chromium headless)

Substitutes {{TOKEN}} placeholders in an HTML template, renders to PNG at
the template's native resolution (auto-detected from root element style),
and saves to output/.

Usage:
    python3 render.py <template.html> [output.png] [--set KEY=VALUE ...] [--json data.json] [--bg image.jpg]

Examples:
    python3 render.py templates/src/story-reel-dark.html \\
        --set EYEBROW="PEPTIDE RESEARCH" \\
        --set HOOK_LINE_1="What if recovery" \\
        --set HOOK_LINE_2_ITALIC="actually worked" \\
        --set HOOK_LINE_3="for you?" \\
        --set SUBTITLE_TEXT="BPC-157 · 12-week study" \\
        --set CTA_LABEL="READ THE COA" \\
        --set HANDLE="@acmelabs"

    # With a Higgsfield background image:
    python3 render.py templates/src/story-reel-dark.html \\
        --bg asset_cache/hf_bg_20260531.jpg \\
        --set EYEBROW="PEPTIDE RESEARCH" ...

    python3 render.py templates/src/story-poll.html --json content/poll.json

Install deps (first run only):
    pip3 install playwright
    python3 -m playwright install chromium
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


OUTPUT_DIR = Path(__file__).parent / "output"
FONT_WAIT_MS = 1800  # wait for Google Fonts to load
SUPERSAMPLE = 2      # render at N× device pixels, then downscale (Lanczos) to native.
                     # Chromium's 1× screenshots alias thin strokes (1px chip borders) and
                     # small type into rough/"cracked" edges; 2× supersampling fixes that.

# Root-div background colors for the two Acme themes
_BG_COLORS = re.compile(r"background:\s*(#(?:1A2E1E|F2EDE4))", re.IGNORECASE)


def substitute(html: str, values: dict) -> str:
    """Replace {{KEY}} tokens with their values. Unreplaced tokens stay as-is."""
    def replacer(m):
        key = m.group(1).strip()
        return values.get(key, m.group(0))
    return re.sub(r"\{\{([^}]+)\}\}", replacer, html)


def inject_background(html: str, bg_path: str) -> str:
    """Replace the root div's solid background color with a cover image.

    Softens all overlays so the image shows through at the brand-spec 65–80%
    Deep Forest overlay (i.e. image visible at ~20–35%). The shipped templates
    use a near-opaque vignette designed for a text-only card; for photography we
    drop it well down so the image reads while text stays legible.
    - Dark (forest-green #1A2E1E): radial vignette → 0.38, rgba bars scaled.
    - Light (cream #F2EDE4): radial vignette → 0.22 (cream-on-anything is harsher).
    """
    bg_uri = Path(bg_path).resolve().as_uri()

    # Detect template theme by which root color is present
    is_light = bool(re.search(r"background:\s*#F2EDE4", html, re.IGNORECASE))
    vignette_opacity = 0.22 if is_light else 0.38

    # 1. Replace root div background color with the image.
    #    Use SINGLE quotes around the url: the template's style attributes are
    #    delimited by double quotes, so url("...") would terminate the attribute
    #    early and the image would silently fail to load (leaving overlay-on-white).
    replaced, n = _BG_COLORS.subn(
        f"background: url('{bg_uri}') center/cover no-repeat",
        html,
        count=1,
    )
    if n == 0:
        print("[render] Warning: could not find root background color to replace.", file=sys.stderr)

    # 2. Soften the radial vignette overlay (uses solid hex colors — opacity is
    #    the only lever). Light template needs a lower value since it's cream-on-anything.
    replaced = re.sub(
        r"(background:\s*radial-gradient\([^)]+\);)",
        f"\\1 opacity: {vignette_opacity};",
        replaced,
        count=1,
    )

    # 3. Scale all rgba gradient bars (top/bottom header+footer overlays) down by
    #    0.45 so the bg image bleeds through while still protecting text legibility.
    def _scale_alpha(m):
        r, g, b, a = m.group(1), m.group(2), m.group(3), float(m.group(4))
        return f"rgba({r}, {g}, {b}, {a * 0.45:.2f})"

    replaced = re.sub(
        r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)",
        _scale_alpha,
        replaced,
    )

    return replaced


def list_tokens(html: str) -> list[str]:
    """Return all unique {{TOKEN}} names found in the template."""
    return sorted(set(m.strip() for m in re.findall(r"\{\{([^}]+)\}\}", html)))


def detect_size(html: str) -> tuple[int, int]:
    """Detect width/height from the root element style attribute.

    Matches the first `width: Npx; height: Mpx` pair — every template declares
    its canonical size on the `body` rule (and the root div) with the two
    properties adjacent, separated by `; `. The earlier `[^;"]` separator class
    could NOT cross that semicolon, so any non-9:16 template silently fell back
    to the 1080×1920 default and rendered a banned white band below the card
    (carousel 1350, callout 1080, compound 1350). The `\\s*;?\\s*` separator
    fixes that while leaving the 9:16 story/poll templates at 1920 unchanged.
    """
    m = re.search(r"width:\s*(\d+)px\s*;?\s*height:\s*(\d+)px", html)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 1080, 1920


def render(template_path: str, output_path: str, values: dict, bg_path: str | None = None,
           transparent: bool = False) -> str:
    """Render an Acme template to PNG.

    transparent=True keeps the page's empty areas transparent (RGBA PNG with an
    alpha channel) — used for the video-underlay reel overlays, where the centre
    of the frame must show the video through and only the scrims/text/logo are
    painted. The overlay templates declare transparent backgrounds themselves;
    omit_background then captures that as real alpha instead of white.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[render] ERROR: playwright not installed.", file=sys.stderr)
        print("[render] Run: pip3 install playwright && python3 -m playwright install chromium", file=sys.stderr)
        sys.exit(1)

    template = Path(template_path).resolve()
    html = template.read_text()

    # Warn about any tokens that were not supplied
    missing = [t for t in list_tokens(html) if t not in values]
    if missing:
        print(f"[render] Warning: unfilled tokens: {missing}", file=sys.stderr)

    if bg_path:
        html = inject_background(html, bg_path)

    html = substitute(html, values)
    w, h = detect_size(html)

    # Write substituted HTML next to the template so relative asset paths
    # (../../assets/acme-logo-icon.svg) resolve from the same directory.
    tmp = template.parent / f"_render_tmp_{os.getpid()}.html"
    # Supersample: render at N× device pixels, then downscale to native with Lanczos for
    # crisp text/borders. Needs Pillow; without it we fall back to a native 1× screenshot.
    ss = SUPERSAMPLE
    if ss > 1:
        try:
            from PIL import Image
        except ImportError:
            print("[render] Pillow not installed — rendering at 1× (text will be softer). "
                  "pip3 install pillow to enable supersampling.", file=sys.stderr)
            ss = 1
    try:
        tmp.write_text(html, encoding="utf-8")

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=ss)
            page.goto(tmp.as_uri(), wait_until="networkidle")
            page.wait_for_timeout(FONT_WAIT_MS)
            shot = page.screenshot(
                path=None if ss > 1 else output_path,  # at N× grab bytes, downscale below
                clip={"x": 0, "y": 0, "width": w, "height": h},
                omit_background=transparent,
            )
            browser.close()
    finally:
        if tmp.exists():
            tmp.unlink()

    if ss > 1:
        import io
        # screenshot is w·ss × h·ss; Lanczos back to native preserves alpha for transparent overlays
        Image.open(io.BytesIO(shot)).resize((w, h), Image.LANCZOS).save(output_path)

    print(f"[render] {w}×{h}{f' ({ss}×SSAA)' if ss > 1 else ''}"
          f"{' (transparent)' if transparent else ''} → {output_path}", file=sys.stderr)
    return output_path


def main():
    ap = argparse.ArgumentParser(
        description="Render an Acme HTML template to PNG via headless Chromium",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Install deps")[0].strip(),
    )
    ap.add_argument("template", help="Path to .html template")
    ap.add_argument("output", nargs="?",
                    help="Output PNG path (default: output/<stem>-<timestamp>.png)")
    ap.add_argument("--set", metavar="KEY=VALUE", action="append", default=[],
                    dest="pairs", help="Set a placeholder value")
    ap.add_argument("--json", metavar="FILE", dest="json_file",
                    help="JSON file with placeholder key/value pairs")
    ap.add_argument("--bg", metavar="FILE", dest="bg_path",
                    help="Background image (local path) to composite behind the template")
    ap.add_argument("--transparent", action="store_true",
                    help="Render with a transparent background (RGBA PNG) — for video-underlay "
                         "reel overlays where the video must show through the centre of the frame")
    ap.add_argument("--tokens", action="store_true",
                    help="Print the list of {{TOKEN}} placeholders in the template and exit")
    args = ap.parse_args()

    if args.tokens:
        html = Path(args.template).read_text()
        for t in list_tokens(html):
            print(f"  {{{{ {t} }}}}")
        return

    values = {}
    if args.json_file:
        with open(args.json_file) as f:
            values.update(json.load(f))
    for pair in args.pairs:
        if "=" not in pair:
            print(f"[render] Skipping malformed --set value: {pair!r}", file=sys.stderr)
            continue
        k, v = pair.split("=", 1)
        values[k.strip()] = v.strip()

    if not args.output:
        OUTPUT_DIR.mkdir(exist_ok=True)
        stem = Path(args.template).stem
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        output = str(OUTPUT_DIR / f"{stem}-{ts}.png")
    else:
        output = args.output

    render(args.template, output, values, bg_path=args.bg_path, transparent=args.transparent)
    print(output)


if __name__ == "__main__":
    main()
