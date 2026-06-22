"""
render_carousel.py — render the PREMIUM (React) carousel deck to per-slide PNGs.

The premium carousel (templates/premium-carousel/carousel-premium-{dark,light}.html)
is NOT a {{TOKEN}} template — it's a self-contained React/Babel app that mounts a
multi-slide deck into <div id="stack"> (one .slide-wrap per slide, 1080×1350 native).
render.py / post.py can't drive it (no token substitution), so it has its own renderer:
it loads the deck headless, neutralises the fit-to-viewport preview scaling so each
slide is at native resolution, waits for React+Babel, then screenshots every .slide-wrap.

Content note: slide copy currently comes from the SLIDES data baked into the app JS
(assets/templates/carousel-premium/<app>.bin). To change copy for a specific post, edit
that SLIDES array. Wiring per-post data injection into the engine is a documented
follow-up (see TEMPLATES.md) — the LEGACY carousel-dark/light templates remain the
engine's token-driven carousel until then.

Usage:
    python3 render_carousel.py templates/premium-carousel/carousel-premium-dark.html \
        output/jobs/ACME-010            # writes <outdir>/slide-01.png … slide-NN.png
"""

import argparse
import sys
from pathlib import Path

NATIVE_W, NATIVE_H = 1080, 1350
REACT_WAIT_MS = 7000  # Babel transpile + React mount
SUPERSAMPLE = 2       # render at N× device pixels then downscale (Lanczos) → crisp text/borders
                      # (1× aliases thin strokes + small type into rough/"cracked" edges)


def render_deck(template: str, out_dir: str) -> list[str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("[carousel] playwright not installed: pip3 install playwright && python3 -m playwright install chromium")

    tpl = Path(template).resolve()
    if not tpl.exists():
        sys.exit(f"[carousel] template not found: {tpl}")
    outd = Path(out_dir)
    outd.mkdir(parents=True, exist_ok=True)

    ss = SUPERSAMPLE
    if ss > 1:
        try:
            from PIL import Image
        except ImportError:
            print("[carousel] Pillow not installed — rendering at 1× (text softer). "
                  "pip3 install pillow to enable supersampling.", file=sys.stderr)
            ss = 1

    outputs = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # Viewport LARGER than the native slide so the deck's fit-to-viewport scaler leaves
        # each .slide-wrap at native 1080×1350 (a viewport ≤ native makes it shrink to fit).
        page = browser.new_page(viewport={"width": NATIVE_W + 200, "height": NATIVE_H + 200},
                                device_scale_factor=ss)
        page.goto(tpl.as_uri(), wait_until="networkidle")
        page.wait_for_timeout(REACT_WAIT_MS)
        # Belt-and-suspenders: pin the scaler to identity in case a resize handler scaled it.
        page.add_style_tag(content=".fit .scaler{transform:none!important;}")
        page.wait_for_timeout(300)

        slides = page.query_selector_all("#stack .slide-wrap")
        if not slides:
            browser.close()
            sys.exit("[carousel] no .slide-wrap slides found — did React mount? (check the deck renders)")

        for i, el in enumerate(slides, start=1):
            out = str(outd / f"slide-{i:02d}.png")
            el.scroll_into_view_if_needed()
            if ss > 1:
                import io
                # element shot is NATIVE·ss; Lanczos back to native 1080×1350
                Image.open(io.BytesIO(el.screenshot())).resize(
                    (NATIVE_W, NATIVE_H), Image.LANCZOS).save(out)
            else:
                el.screenshot(path=out)
            outputs.append(out)
            print(f"[carousel] slide {i}/{len(slides)}{f' ({ss}×SSAA)' if ss > 1 else ''} → {out}",
                  file=sys.stderr)
        browser.close()
    return outputs


def main():
    ap = argparse.ArgumentParser(description="Render the premium React carousel deck to per-slide PNGs")
    ap.add_argument("template", help="templates/premium-carousel/carousel-premium-{dark,light}.html")
    ap.add_argument("out_dir", help="Directory to write slide-NN.png into")
    args = ap.parse_args()
    outs = render_deck(args.template, args.out_dir)
    for o in outs:
        print(o)


if __name__ == "__main__":
    main()
