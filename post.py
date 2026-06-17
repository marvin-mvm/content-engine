"""post.py — Acme brief-driven image runner (M5 -> M6 prep), 0 Higgsfield credits.

The image analogue of reel.py: turns a job folder (brief.json, type=image) into a
brand-rendered PNG — or a carousel slide set — via produce.py, with no hand-typed
--set flags. This is the A3 "wrap it" deliverable for the image pipeline.

bg_policy is **plain** or **reuse** ONLY. post.py NEVER generates a background:
"generate" is rejected, because that path spends Higgsfield credits. To deliberately
generate (the gated A5 spend), call produce.py --bg-prompt directly.

Usage:
    python3 post.py output/jobs/ACME-008              # render from the brief
    python3 post.py output/jobs/ACME-008 --log        # also log to the live Content Matrix

Job folder contract (brief.json, type=image):
    {
      "job_id": "ACME-008",
      "type": "image",
      "brand": "labs", "pillar": "stack", "persona": "P1",
      "topic": "Semaglutide — GLP-1 research feature",
      "image": {
        "template": "templates/src/static-compound-dark.html",
        "bg_policy": "plain" | "reuse",
        "source_asset": "asset_cache/url_309e....png",   # required iff bg_policy == reuse
        "carousel": "slides.json",                        # optional -> one PNG per slide (plain only)
        "set": { "COMPOUND": "Semaglutide", "CLASS_CHIP": "GLP-1 ANALOG", ... }
      }
    }

Writes (into the job folder):
    <job_id>.png                 # single image
    <job_id>-slide-01.png ...    # carousel mode

Mirrors reel.py: the engine/template is never hand-edited; the brief supplies all
per-job data, post.py drives produce.py (--no-log by default for the validation
pipeline; pass --log for a real post).
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).parent.resolve()
PRODUCE = str(WORKSPACE / "produce.py")


def fail(msg: str) -> "NoReturn":
    sys.exit(f"[post] ERROR: {msg}")


def run(cmd, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser(description="Acme brief-driven image runner (M5)")
    ap.add_argument("job_dir", help="Job folder containing brief.json (type=image)")
    ap.add_argument("--log", action="store_true",
                    help="Log to the live Content Matrix (default: --no-log, like the test pipeline)")
    args = ap.parse_args()

    job = Path(args.job_dir).resolve()
    brief_path = job / "brief.json"
    if not brief_path.exists():
        fail(f"no brief.json in {job}")
    brief = json.loads(brief_path.read_text())
    if brief.get("type") != "image":
        fail(f"brief type is {brief.get('type')!r}; post.py only handles type=image (use reel.py for reel)")

    img = brief.get("image")
    if not isinstance(img, dict) or "template" not in img:
        fail("brief.image is missing or has no 'template' — see post.py docstring for the contract")

    template = img["template"]
    if not (WORKSPACE / template).exists():
        fail(f"template not found: {template}")

    bg_policy = img.get("bg_policy", "plain")
    if bg_policy not in ("plain", "reuse"):
        fail(f"bg_policy {bg_policy!r} not allowed — post.py is 0-credit (plain|reuse only). "
             f"For a deliberate generation (A5), call produce.py --bg-prompt directly.")

    tokens = img.get("set", {})
    if not isinstance(tokens, dict):
        fail("brief.image.set must be an object of TOKEN: value pairs")

    # Resolve a reuse background (existing local asset only — never generated).
    bg_file = None
    if bg_policy == "reuse":
        src = img.get("source_asset")
        if not src:
            fail("bg_policy=reuse requires 'source_asset' (path to an EXISTING local image)")
        bg_path = (WORKSPACE / src).resolve()
        if not bg_path.exists():
            fail(f"source_asset not found: {bg_path} — reuse never generates; pick an existing asset")
        bg_file = str(bg_path)

    log_flags = [] if args.log else ["--no-log"]
    topic = brief.get("topic", "")
    common_set = [arg for k, v in tokens.items() for arg in ("--set", f"{k}={v}")]

    # ── Carousel mode ────────────────────────────────────────────────────────
    carousel = img.get("carousel")
    if carousel:
        if bg_policy == "reuse":
            fail("carousel + reuse is not supported (produce.py --carousel renders text cards "
                 "with no bg injection) — use bg_policy=plain for carousels")
        slides = (job / carousel)
        if not slides.exists():
            slides = (WORKSPACE / carousel)
        if not slides.exists():
            fail(f"carousel slides file not found: {carousel}")
        cmd = ["python3", PRODUCE, template, *log_flags, "--carousel", str(slides)]
        if topic:
            cmd += ["--topic", topic]
        cmd += common_set
        r = run(cmd, cwd=WORKSPACE)
        if r.returncode != 0:
            fail(f"produce.py (carousel) failed:\n{(r.stdout + r.stderr)[-1500:]}")
        # produce.py writes output/<stem>-<ts>-slide-NN.png — relocate into the job folder.
        stem = Path(template).stem
        produced = sorted((WORKSPACE / "output").glob(f"{stem}-*-slide-*.png"))
        # Keep only the most recent run (group by the shared timestamp in the name).
        if not produced:
            fail("carousel produced no slides")
        latest_ts = produced[-1].name.rsplit("-slide-", 1)[0]
        produced = [p for p in produced if p.name.startswith(latest_ts)]
        outs = []
        for p in produced:
            n = p.name.rsplit("-slide-", 1)[1]  # NN.png
            dst = job / f"{brief['job_id']}-slide-{n}"
            shutil.move(str(p), str(dst))
            outs.append(dst)
        for o in outs:
            print(f"slide={o}")
        print(f"[post] {len(outs)} slides -> {job}", file=sys.stderr)
        return

    # ── Single image mode ────────────────────────────────────────────────────
    out = job / f"{brief['job_id']}.png"
    cmd = ["python3", PRODUCE, template, str(out), *log_flags]
    if bg_file:
        cmd += ["--bg-file", bg_file]
    if topic:
        cmd += ["--topic", topic]
    cmd += common_set
    r = run(cmd, cwd=WORKSPACE)
    if r.returncode != 0 or not out.exists():
        fail(f"produce.py failed:\n{(r.stdout + r.stderr)[-1500:]}")
    print(f"image={out}")
    print(f"[post] rendered {bg_policy} -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
