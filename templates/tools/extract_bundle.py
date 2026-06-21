"""
extract_bundle.py — unpack an Acme "standalone" bundler export into a clean,
editable HTML template.

The standalone exports in `assets/Acme Labs Post Overlay Templates/` are NOT
plain HTML: the real markup is a JSON string inside
`<script type="__bundler/template">`, and every image/font is base64 (sometimes
gzip-compressed) inside `<script type="__bundler/manifest">`, referenced by UUID.
A runtime script unpacks them in the browser — useless for our Playwright
renderer, which needs static files.

This tool resolves the bundle offline:
  1. decode every manifest asset (gunzip if compressed) → write to an asset dir
  2. pull out the inner template HTML
  3. rewrite every UUID reference to a relative path to the written asset
  4. write a clean, self-contained <!DOCTYPE html> file we can then tokenize

Usage:
    python3 templates/tools/extract_bundle.py "<bundle.html>" <out.html> <asset_subdir>

    # asset_subdir is created under assets/templates/<asset_subdir>/ and the
    # rewritten refs point at ../../assets/templates/<asset_subdir>/<uuid>.<ext>
"""

import gzip
import base64
import json
import re
import sys
from pathlib import Path

WS = Path(__file__).resolve().parents[2]            # repo root
ASSETS = WS / "assets" / "templates"

EXT = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg",
    "image/webp": ".webp", "image/svg+xml": ".svg", "image/gif": ".gif",
    "font/woff2": ".woff2", "font/woff": ".woff", "font/ttf": ".ttf",
    "font/otf": ".otf", "application/font-woff2": ".woff2",
    "application/octet-stream": ".bin",
}


def script_body(raw: str, kind: str) -> str:
    m = re.search(rf'<script type="__bundler/{kind}">\s*(.*?)\s*</script>', raw, re.S)
    if not m:
        sys.exit(f"[extract] no __bundler/{kind} script found")
    return m.group(1)


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    src, out, subdir = sys.argv[1], sys.argv[2], sys.argv[3]
    raw = Path(src).read_text(encoding="utf-8")

    manifest = json.loads(script_body(raw, "manifest"))
    template = json.loads(script_body(raw, "template"))   # JSON string → real HTML

    asset_dir = ASSETS / subdir
    asset_dir.mkdir(parents=True, exist_ok=True)
    rel = f"../../assets/templates/{subdir}"

    written = 0
    for uuid, entry in manifest.items():
        data = base64.b64decode(entry["data"])
        if entry.get("compressed"):
            data = gzip.decompress(data)
        ext = EXT.get(entry.get("mime", ""), ".bin")
        fn = f"{uuid}{ext}"
        (asset_dir / fn).write_bytes(data)
        # rewrite every reference to this uuid (src="UUID", url(UUID), "UUID")
        template = template.replace(uuid, f"{rel}/{fn}")
        written += 1

    # ext_resources: id → uuid map for things referenced by id rather than uuid
    ext_res = script_body(raw, "ext_resources")
    try:
        for entry in json.loads(ext_res):
            if entry.get("id") and entry.get("uuid"):
                # the uuid was already rewritten to its path above
                pass
    except (json.JSONDecodeError, TypeError):
        pass

    Path(out).write_text(template, encoding="utf-8")
    print(f"[extract] {written} assets → {asset_dir}")
    print(f"[extract] template → {out}  ({len(template):,} bytes)")


if __name__ == "__main__":
    main()
