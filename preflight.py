#!/usr/bin/env python3
"""
preflight.py — Acme Higgsfield pre-submit GATE (M3). 0 credits.

The hard wall that MUST pass before ANY Higgsfield generation is submitted. It is
the safety mechanism that protects the single credit spend (A5): ANY failed check
→ exit non-zero, print the blocking reasons, emit NO go-token, NO submit, NO spend.

This is a STANDALONE check (decided with Operator, A4): it validates the *generation
plan* — not one code path — so it covers every route (raw `higgsfield image/video`,
`ms-dtc`, `product-photoshoot`, and `produce.py --bg-prompt`). It deliberately does
NOT modify the shared OpenClaw scripts, so the live system is untouched. It never
calls a generator; the only network it does is a best-effort READ (`generate list`)
for the reuse check, which is non-fatal and works offline.

Usage (the gate):
  preflight.py --route image|video|dtc|product \\
      --prompt "<the FULL prompt that will be submitted, brand block included>" \\
      [--model M] [--aspect 9:16|4:5|1:1|16:9] [--template templates/src/....html] \\
      [--bg-policy plain|reuse|generate] [--no-wait] --reuse-checked

Helper (so the brand block stays verbatim by construction):
  preflight.py --print-block image      # prints the IMAGE Brand Prompt Block, exit 0
  preflight.py --print-block video      # prints the VIDEO Brand Prompt Block, exit 0
  # e.g.  P="$(python3 preflight.py --print-block video) cold-chain vial b-roll, slow dolly"

Exit code: 0 = PASS (prints `PREFLIGHT-OK` go-token on stdout); 1 = BLOCK; 2 = bad args.

Sources of truth (verbatim): SOUL.md §"IMAGE/VIDEO Brand Prompt Block" + §17 Production
router + M3 checklist (MIGRATION.md 1.2). Brand rules are NOT duplicated here — only
machine-checked.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).parent.resolve()
ASSET_CACHE = WORKSPACE / "asset_cache"

# ── Brand Prompt Blocks (verbatim, SOUL.md §132 / §138) ───────────────────────
# IMAGE block is the exact string produce.py injects — import it so the two can
# never drift; fall back to the verbatim literal if produce's import chain is
# unavailable (keeps preflight standalone).
_IMAGE_BLOCK_LITERAL = (
    "Acme premium-biotech editorial visual system. Color palette STRICTLY: deep forest "
    "green #1A2E1E and #2D6A4A, warm cream #F2EDE4, sage mint #C8DDD0, with bright accent "
    "green #3D9E6E for a single point of emphasis. NEVER use gold, yellow, amber, purple, "
    "pink, red, or orange. NEVER a plain white background — minimum is warm cream #F2EDE4. "
    "Clean, lit-from-the-side product photography on cream or deep-forest surfaces, generous "
    "negative space, thin hairline rules, subtle elliptical leaf motif echoing the logomark. "
    "Mood: scientific precision meeting accessible education — calm, rigorous, premium. Not "
    "spa-wellness, not stock-photo smiles, not cluttered, not neon. Editorial, authoritative, "
    "minimal. ::"
)
try:
    from produce import IMAGE_BRAND_PROMPT as IMAGE_BLOCK
except Exception:
    IMAGE_BLOCK = _IMAGE_BLOCK_LITERAL

VIDEO_BLOCK = (
    "Acme premium-biotech cinematic system. Deep forest green and warm cream palette only, "
    "single bright-green #3D9E6E accent. Anamorphic lens, shallow depth of field, soft side "
    "lighting, subtle film grain, 24fps motion, color graded toward forest-green and cream — "
    "never teal/orange, never gold, never neon. Lab, molecular, clinical, or clean product "
    "b-roll. Calm authoritative pacing, generous negative space, editorial biotech mood. No "
    "on-screen text in the generated footage. ::"
)

# Route → medium (which Brand Prompt Block must lead the prompt).
VIDEO_ROUTES = {"video"}
IMAGE_ROUTES = {"image", "dtc", "product"}

# Known model families, used only to catch a medium↔model mismatch (not a full catalog).
KNOWN_IMAGE_MODELS = {"gpt_image_2", "flux_1_1_pro", "cinematic_studio_2_5", "nano_banana"}
KNOWN_VIDEO_MODELS = {"seedance_2_0", "kling3_0", "cinematic_studio_3_0", "marketing_studio_video"}

# Template family → required aspect ratio (SOUL Formats / RUNBOOK §9.2).
TEMPLATE_ASPECT = [
    (re.compile(r"story-(reel|poll)"), "9:16"),
    (re.compile(r"carousel"), "4:5"),
    (re.compile(r"static-compound"), "4:5"),
    (re.compile(r"static-callout"), "1:1"),
]
VALID_ASPECTS = {"9:16", "4:5", "1:1", "16:9"}

# Positive "render this text" requests — models hallucinate text; it is burned in
# later (M4/M5), never asked of the generator (SOUL §144). Negations ("no text")
# are allowed and ignored.
TEXT_REQUEST = re.compile(
    r"\b(text|caption|subtitle|title|headline|lettering|typograph\w*|"
    r"words?\s+that\s+say|says|reads|written|writing|label|wordmark)\b",
    re.IGNORECASE,
)
NEGATION_BEFORE = re.compile(r"(no|without|free of|zero|devoid of|avoid|sans)\s+$", re.IGNORECASE)
QUOTED_LITERAL = re.compile(r"""["'“”‘’]([^"'“”‘’]*[A-Za-z]{2,}[^"'“”‘’]*)["'“”‘’]""")

# Content that means "this is a product/spokesperson AD" → must route to DTC Ads
# Engine, never raw image/video (SOUL §86, M3 routing).
AD_PERSON = re.compile(
    r"\b(ava|spokesperson|talking[- ]head|presenter|influencer|ugc|testimonial|"
    r"person|model|woman|man|she|he|holding the product|wearing|hands holding|"
    r"unboxing|to camera|on camera)\b",
    re.IGNORECASE,
)


def creative_part(prompt: str) -> str:
    """The creative tail after the brand block's terminating `::` (the block itself
    contains phrases like 'No on-screen text' that must not trip the text check)."""
    return prompt.rsplit("::", 1)[-1].strip() if "::" in prompt else prompt.strip()


def template_aspect(template: str):
    name = Path(template).name
    for rx, asp in TEMPLATE_ASPECT:
        if rx.search(name):
            return asp
    return None


def find_text_requests(creative: str):
    """Return offending text-render requests in the creative prompt (empty = clean)."""
    hits = []
    for m in TEXT_REQUEST.finditer(creative):
        pre = creative[max(0, m.start() - 14):m.start()]
        if NEGATION_BEFORE.search(pre):
            continue  # "no text", "without lettering" → fine
        hits.append(m.group(0))
    for m in QUOTED_LITERAL.finditer(creative):
        hits.append(f'quoted literal {m.group(0)}')
    return hits


def reuse_inventory():
    """Best-effort, non-fatal: surface what already exists so a --reuse-checked ack
    is informed. Never blocks on its own; never spends (read-only `generate list`)."""
    lines = []
    try:
        cached = sorted(p.name for p in ASSET_CACHE.glob("*") if p.is_file())
        lines.append(f"asset_cache/ ({len(cached)} files): " + (", ".join(cached) or "—"))
    except Exception as e:
        lines.append(f"asset_cache/ unreadable: {e}")
    lines.append("Known reusable Higgsfield job: Metabolic Support Stack 7d01b600-… (verify nothing fits)")
    try:
        r = subprocess.run(["higgsfield", "generate", "list", "--json"],
                           capture_output=True, text=True, timeout=25)
        if r.returncode == 0:
            import json as _json
            data = _json.loads(r.stdout)
            jobs = data if isinstance(data, list) else data.get("jobs", [])
            done = [j for j in jobs if str(j.get("status", "")).lower()
                    in {"completed", "done", "ready", "succeeded", "success"}]
            lines.append(f"higgsfield generate list: {len(done)} completed job(s) available to reuse")
            for j in done[:5]:
                pid = (j.get("params") or {}).get("prompt", "")
                lines.append(f"  · {j.get('id', '?')[:8]} [{j.get('job_set_type', '?')}] {pid[:70]}")
        else:
            lines.append("higgsfield generate list: unavailable (offline/auth) — verify reuse manually")
    except Exception as e:
        lines.append(f"higgsfield generate list: skipped ({e}) — verify reuse manually")
    return lines


def run_checks(args):
    """Return a list of blocking-reason strings (empty list = PASS)."""
    reasons = []
    route = args.route
    prompt = args.prompt or ""
    creative = creative_part(prompt)

    # 1 — bg_policy honored: plain/reuse never generate (0 credits). Only 'generate' proceeds.
    if args.bg_policy and args.bg_policy != "generate":
        reasons.append(
            f"bg_policy={args.bg_policy}: no generation needed — render locally (plain) or "
            f"--bg-file an existing asset (reuse). 0 credits. Do NOT submit to Higgsfield.")

    # 2 — Brand Prompt Block prepended verbatim (IMAGE for image/dtc/product, VIDEO for video).
    want_block, label = (VIDEO_BLOCK, "VIDEO") if route in VIDEO_ROUTES else (IMAGE_BLOCK, "IMAGE")
    if not prompt.startswith(want_block):
        reasons.append(
            f"{label} Brand Prompt Block is not prepended verbatim. The submitted prompt MUST "
            f"begin with it. Build it with: preflight.py --print-block {'video' if route in VIDEO_ROUTES else 'image'}")

    # 3 — No rendered text requested in the creative prompt.
    text_hits = find_text_requests(creative)
    if text_hits:
        reasons.append(
            "prompt requests rendered text (models hallucinate it; burn text in M4/M5 instead): "
            + ", ".join(sorted(set(text_hits))))

    # 4 — Correct route.
    if route in {"image", "video"} and AD_PERSON.search(creative):
        reasons.append(
            "prompt reads like a product/spokesperson AD (person/Nova/UGC) but route is raw "
            f"'{route}'. Product & spokesperson ads → DTC Ads Engine (--route dtc); "
            "product photography → --route product (product-photoshoot).")
    if args.model:
        if route == "image" and args.model in KNOWN_VIDEO_MODELS:
            reasons.append(f"route=image but model '{args.model}' is a VIDEO model. "
                           "B-roll/background images → gpt_image_2.")
        if route == "video" and args.model in KNOWN_IMAGE_MODELS:
            reasons.append(f"route=video but model '{args.model}' is an IMAGE model. "
                           "B-roll/background video → seedance_2_0.")

    # 5 — Aspect matches template (or is a valid ratio when no template is given).
    if args.template:
        if not (WORKSPACE / args.template).exists():
            reasons.append(f"template not found: {args.template}")
        want = template_aspect(args.template)
        if want and args.aspect != want:
            reasons.append(f"aspect {args.aspect or '(none)'} != template requires {want} "
                           f"({Path(args.template).name}: 9:16 story · 4:5 carousel/compound · 1:1 callout).")
        elif want is None:
            reasons.append(f"could not infer required aspect from template {Path(args.template).name}; "
                           "add it to TEMPLATE_ASPECT or pass a known template.")
    else:
        if not args.aspect:
            reasons.append("no --aspect and no --template — specify the aspect ratio (reels are 9:16).")
        elif args.aspect not in VALID_ASPECTS:
            reasons.append(f"aspect {args.aspect!r} is not a valid brand ratio {sorted(VALID_ASPECTS)}.")

    # 6 — Video must not block on --wait (SOUL §17: video jobs never block).
    if route == "video" and not args.no_wait:
        reasons.append("video route must submit with --no-wait (video jobs never block on --wait). "
                       "Pass --no-wait once you've confirmed the submit command uses it.")

    # 7 — Reuse check acknowledged (informed by the inventory printed above).
    if not args.reuse_checked:
        reasons.append("reuse check not acknowledged. Review the inventory above; if nothing "
                       "existing fits, re-run with --reuse-checked.")

    return reasons


def main():
    ap = argparse.ArgumentParser(
        description="Acme Higgsfield pre-submit gate (M3) — hard wall before any credit spend.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--print-block", choices=["image", "video"],
                    help="Print the verbatim Brand Prompt Block and exit (use to build a prompt).")
    ap.add_argument("--route", choices=["image", "video", "dtc", "product"],
                    help="The generation route/tool being used.")
    ap.add_argument("--prompt", help="The FULL prompt that will be submitted (brand block included).")
    ap.add_argument("--model", help="Higgsfield model (e.g. gpt_image_2, seedance_2_0).")
    ap.add_argument("--aspect", help="Aspect ratio (9:16 | 4:5 | 1:1 | 16:9).")
    ap.add_argument("--template", help="Template the asset feeds (used to check aspect).")
    ap.add_argument("--bg-policy", choices=["plain", "reuse", "generate"], dest="bg_policy",
                    help="If set, plain/reuse → blocked (0-credit paths don't submit).")
    ap.add_argument("--no-wait", action="store_true", help="Video submit is non-blocking (required for video).")
    ap.add_argument("--reuse-checked", action="store_true",
                    help="Acknowledge you reviewed existing assets and nothing fits.")
    args = ap.parse_args()

    if args.print_block:
        print(IMAGE_BLOCK if args.print_block == "image" else VIDEO_BLOCK)
        return

    if not args.route or args.prompt is None:
        ap.error("--route and --prompt are required (unless using --print-block)")

    print("── PREFLIGHT (M3) ──────────────────────────────────────────", file=sys.stderr)
    print(f"route={args.route} model={args.model or '—'} aspect={args.aspect or '—'} "
          f"template={Path(args.template).name if args.template else '—'} "
          f"bg_policy={args.bg_policy or '—'}", file=sys.stderr)
    print("Reuse inventory (check nothing existing fits before spending):", file=sys.stderr)
    for line in reuse_inventory():
        print(f"  {line}", file=sys.stderr)

    reasons = run_checks(args)
    if reasons:
        print("\nPREFLIGHT: BLOCK — do NOT submit, do NOT spend. Failed checks:", file=sys.stderr)
        for i, r in enumerate(reasons, 1):
            print(f"  {i}. {r}", file=sys.stderr)
        sys.exit(1)

    print("\nPREFLIGHT: PASS — all M3 checks cleared. Clear to submit.", file=sys.stderr)
    print("PREFLIGHT-OK")  # go-token on stdout, only emitted on a clean pass
    sys.exit(0)


if __name__ == "__main__":
    main()
