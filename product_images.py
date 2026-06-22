#!/usr/bin/env python3
"""product_images.py — resolve an Acme compound/stack name → its product photo.

Marvin dropped the real product photos in "Acme Labs Product Images" (one folder
per SKU, the mg in the filename). This module is the single resolver the engine uses
to wire those photos into:
  • story-product / static-compound cards  → PRODUCT_IMAGE token (a file:// URI the
    Chromium renderer loads, see render.py),
  • Higgsfield video/image generation       → a reference media id (upload + cache),
    so a tirzepatide reel is anchored on the real tirzepatide vial.

It AUTO-SCANS the asset tree (no hard-coded file list — robust to re-drops/renames):
prefers a transparent "No_BG" cutout for overlays, and can match a specific mg.

Usage:
  python3 product_images.py list                      # every resolvable name → path
  python3 product_images.py resolve "Tirzepatide"     # best photo path
  python3 product_images.py resolve "BPC-157" --bg     # prefer the WITH-background photo
  python3 product_images.py uri "Semaglutide"         # file:// URI (renderer-ready)
  python3 product_images.py ref "Tirzepatide"         # upload to Higgsfield → media id (cached)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

WS = Path(__file__).parent.resolve()
# Stable location (copied out of the fragile __pycache__ drop). Fall back to the
# original drop and any future re-drop so a missing copy never silently breaks.
ROOTS = [
    WS / "assets" / "product_images",
    WS / "__pycache__" / "Acme Labs Product Images",
]
REF_CACHE = WS / "asset_cache" / "product_higgsfield_refs.json"
IMG_EXT = (".webp", ".png", ".jpg", ".jpeg")


def _norm(s: str) -> str:
    """Lowercase, collapse separators — so 'CJC-1295', 'CJC 1295', 'cjc1295' all match."""
    return re.sub(r"[^a-z0-9]+", "", s.lower())


# Compound/stack name (and common variants) → the folder name in the asset tree.
# Keys are matched after _norm(), so case/space/dash differences don't matter; this map
# only handles the genuinely AMBIGUOUS ones (blends, typo'd folders, the GHRP→blend tie).
ALIASES = {
    "cjc1295": "CJC 1295",
    "ipamorelin": "CJC 1295 : Ipamorelin",
    "cjc1295ipamorelin": "CJC 1295 : Ipamorelin",
    "cjc1295dac": "CJC 1295 : DAC",
    "bpc157tb500": "BPC-157:TB-500",
    "tb500": "TB-500",
    "pt141": "PT 141",
    "melanotan2": "Melanotan 2",
    "igf1lr3": "IGF-1 LR3",
    "tesamorelin": "Tesamorelin 10mg",
    "thymosinalpha": "Thymosin Alpha",
    "thymosinalpha1": "Thymosin Alpha",
    "cagrisema": "Cargi : Sema",
    # stacks
    "longevitystack": "Stacks/Longevity Stack",
    "recoverypro": "Stacks/Recovery Pro",
    "glpbundle": "Stacks/GLP Bundle",
    "gainbundle": "Stacks/Gain Bundle",
    "cognitivebundle": "Stacks/Cognitive Bundle",
    "collagenresearchbundle": "Stacks/Collagen Research Bundle",
    "repairstarter": "Stacks/Repair Starter",
    "glow": "Stacks/Glow",
    "klow": "Stacks/Klow",
    "bacteriostaticwater": "Stacks/Bacteriostatic Water 3 ML",
}


def _active_root() -> Path | None:
    for r in ROOTS:
        if r.exists():
            return r
    return None


def _folder_for(name: str, root: Path) -> Path | None:
    """Find the SKU folder for `name`: alias first, else a fuzzy normalized match on
    every directory (top-level and one level into Stacks/)."""
    key = _norm(name)
    if key in ALIASES:
        cand = root / ALIASES[key]
        if cand.exists():
            return cand
    dirs = [p for p in root.iterdir() if p.is_dir()]
    dirs += [p for p in (root / "Stacks").iterdir() if p.is_dir()] if (root / "Stacks").exists() else []
    # exact normalized folder-name match, then "starts-with" / "contains"
    for matcher in (lambda d: _norm(d.name) == key,
                    lambda d: _norm(d.name).startswith(key) or key.startswith(_norm(d.name)),
                    lambda d: key in _norm(d.name) or _norm(d.name) in key):
        for d in dirs:
            if matcher(d):
                return d
    return None


def resolve(name: str, *, mg: str | None = None, prefer_no_bg: bool = True) -> Path | None:
    """Best product photo for a compound/stack name, or None.

    prefer_no_bg=True  → a transparent cutout (filename contains 'No_BG'/'NoBG'), ideal
                         for the story-product overlay card. False → a with-background hero.
    mg="10mg"          → prefer the file whose name carries that strength.
    """
    root = _active_root()
    if not root or not name:
        return None
    folder = _folder_for(name, root)
    if not folder:
        return None
    imgs = sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in IMG_EXT)
    if not imgs:
        return None

    def score(p: Path) -> tuple:
        n = _norm(p.name)
        no_bg = "nobg" in n
        mg_hit = bool(mg) and _norm(mg) in n
        # higher tuple sorts first (we reverse): mg match, then no_bg pref aligned to flag
        return (mg_hit, (no_bg == prefer_no_bg), no_bg if prefer_no_bg else (not no_bg))

    return sorted(imgs, key=score, reverse=True)[0]


def file_uri(name: str, **kw) -> str | None:
    """Renderer-ready file:// URI for PRODUCT_IMAGE (Chromium loads local files from a
    file:// page — see render.py). Short value → no ARG_MAX risk via post.py --set."""
    p = resolve(name, **kw)
    return p.resolve().as_uri() if p else None


def data_uri(name: str, **kw) -> str | None:
    """Base64 data: URI fallback (path-independent). Heavier; use file_uri by default."""
    import base64
    import mimetypes
    p = resolve(name, **kw)
    if not p:
        return None
    mime = mimetypes.guess_type(p.name)[0] or "image/webp"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


# ── Higgsfield reference (for video/image generation anchored on the real product) ──

def _load_ref_cache() -> dict:
    if REF_CACHE.exists():
        try:
            return json.loads(REF_CACHE.read_text())
        except Exception:
            return {}
    return {}


def higgsfield_ref(name: str, **kw) -> str | None:
    """Upload the product photo to Higgsfield once and return its media id (cached), so a
    reel/image for that compound can pass it as a reference. None if no photo or upload fails."""
    p = resolve(name, **kw)
    if not p:
        return None
    cache = _load_ref_cache()
    ckey = str(p.relative_to(WS)) if p.is_relative_to(WS) else str(p)
    if ckey in cache:
        return cache[ckey]
    try:
        out = subprocess.run([sys.executable, str(WS / "higgsfield.py"), "upload", str(p)],
                             capture_output=True, text=True, timeout=180)
        if out.returncode != 0:
            print(f"[product_images] higgsfield upload failed for {name}: {out.stderr[-300:]}", file=sys.stderr)
            return None
        # higgsfield.py upload prints one pretty-printed JSON object with the media id.
        mid = None
        try:
            j = json.loads(out.stdout)
            mid = j.get("id") or j.get("media_id") or j.get("image_id")
        except Exception:
            mid = None
        if mid:
            cache[ckey] = mid
            REF_CACHE.parent.mkdir(parents=True, exist_ok=True)
            REF_CACHE.write_text(json.dumps(cache, indent=2))
        return mid
    except Exception as e:
        print(f"[product_images] higgsfield upload error for {name}: {e}", file=sys.stderr)
        return None


def all_resolvable() -> dict:
    """name → path for every SKU folder found (for `list` and sanity checks)."""
    root = _active_root()
    out = {}
    if not root:
        return out
    dirs = [p for p in root.iterdir() if p.is_dir() and p.name != "Stacks"]
    dirs += [p for p in (root / "Stacks").iterdir() if p.is_dir()] if (root / "Stacks").exists() else []
    for d in dirs:
        best = resolve(d.name)
        if best:
            out[d.name] = str(best.relative_to(WS))
    return out


def main():
    ap = argparse.ArgumentParser(prog="product_images")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    pr = sub.add_parser("resolve"); pr.add_argument("name"); pr.add_argument("--mg"); pr.add_argument("--bg", action="store_true")
    pu = sub.add_parser("uri"); pu.add_argument("name"); pu.add_argument("--mg"); pu.add_argument("--bg", action="store_true")
    pd = sub.add_parser("datauri"); pd.add_argument("name"); pd.add_argument("--mg"); pd.add_argument("--bg", action="store_true")
    prf = sub.add_parser("ref"); prf.add_argument("name"); prf.add_argument("--mg"); prf.add_argument("--bg", action="store_true")
    a = ap.parse_args()

    if a.cmd == "list":
        for k, v in all_resolvable().items():
            print(f"{k:32s} -> {v}")
        return
    kw = {"mg": getattr(a, "mg", None), "prefer_no_bg": not getattr(a, "bg", False)}
    if a.cmd == "resolve":
        p = resolve(a.name, **kw); print(p if p else "(no match)")
    elif a.cmd == "uri":
        u = file_uri(a.name, **kw); print(u if u else "(no match)")
    elif a.cmd == "datauri":
        u = data_uri(a.name, **kw); print((u[:80] + "…") if u else "(no match)")
    elif a.cmd == "ref":
        print(higgsfield_ref(a.name, **kw) or "(no ref)")


if __name__ == "__main__":
    main()
