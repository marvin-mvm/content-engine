#!/usr/bin/env python3
"""
copywriter.py — Acme brand-voice copy generator (OpenRouter).

Generates brand-compliant copy for a post in one call:
  - Template overlay tokens (EYEBROW, HOOK_LINE_1/2/3, SUBTITLE_TEXT, CTA_LABEL, HANDLE)
  - Social caption (the Research Pharmacist voice, enforced)
  - Hashtags + alt text

Output is a single JSON object. The overlay tokens feed produce.py --json;
the caption/hashtags/alt_text feed the Blotato publish step (SYSTEM_CONTEXT §18).

Usage:
  copywriter.py "TOPIC" --brand labs|health [--kind full|overlay|caption]
                  [--product-feature] [--compound "BPC-157" --class "PENTADECAPEPTIDE"]
                  [--platform instagram|tiktok|twitter|x|youtube|threads|facebook|linkedin]
                  [--model MODEL] [--raw]

  # Auto-derive topic from a Higgsfield job (reads the generation prompt from metadata):
  copywriter.py --job-id JOB_ID --brand labs|health [--platform ...]

Examples:
  # Full copy for a Health metabolic post, save tokens for produce.py:
  python3 copywriter.py "semaglutide mechanism of action" --brand health > /tmp/copy.json
  python3 produce.py templates/src/story-reel-dark.html --json /tmp/copy.json \\
      --bg-prompt "..."

  # Product-feature post (auto-appends RUO + class/COA chips):
  python3 copywriter.py "BPC-157 tissue repair research" --brand labs \\
      --product-feature --compound "BPC-157" --class "PENTADECAPEPTIDE"

  # Caption for an existing Higgsfield video — topic derived from the job prompt:
  python3 copywriter.py --job-id 22a79dcc-1e1d-4876-9ee1-7f8016d11a61 --brand labs --platform tiktok

Reads OPENROUTER_API_KEY from .env (same folder) or environment.
"""

import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()

SCRIPT_DIR = Path(__file__).parent
API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"

RUO_LINE = "RUO · NOT FOR HUMAN CONSUMPTION"

BRANDS = {
    "labs": {
        "wordmark": "ACME LABS",
        "handle": "@acmelabs",
        "url": "acmelabs.co",
        "tagline": "PEPTIDES · PERFORMANCE · LONGEVITY",
        "scope": "research-grade peptides; in-vitro/pre-clinical research only",
    },
    "health": {
        "wordmark": "ACME HEALTH",
        "handle": "@acmehealth",
        "url": "acmehealth.co",
        "tagline": "METABOLIC · LONGEVITY · OPTIMIZATION",
        "scope": "clinician-supervised metabolic & longevity protocols",
    },
}

# Per-platform caption shape (SOUL §6 + MIGRATION §1A.4). Each platform gets a
# UNIQUE caption — never the same text verbatim — and a different shape. Injected
# into the user prompt so the model writes to the right length/format per channel.
# `x` is an alias of `twitter` (the brief/publish layer uses "x"; Blotato uses
# "twitter"). The legacy 4 platforms keep their prior behavior (backward-compatible).
PLATFORM_SHAPES = {
    "instagram": "Instagram: a hook line, then a 2–3 sentence payoff, then \"Save this.\", "
                 "then a rotating CTA. Scannable and conversational.",
    "tiktok": "TikTok: ONE punchy hook sentence and a punchy CTA — very short. "
              "Up to 5 hashtags in the body is fine.",
    "youtube": "YouTube Shorts: front-load the compound/topic name; a 2–3 sentence "
               "description; end on a subscribe CTA.",
    "twitter": "X (Twitter): ONE bold, specific claim or finding in 280 characters or fewer. "
               "ZERO hashtags. A single opinion, not a list. Sparing emoji.",
    "threads": "Threads: a casual, conversational, slightly more personal repurpose of the "
               "Instagram angle. Shorter and lighter. No hashtag wall.",
    "facebook": "Facebook: a clear, informative repurpose for broad reach — a little longer-form, "
                "plainspoken, minimal hashtags.",
    "linkedin": "LinkedIn: 3–5 short paragraphs. Open on a data point, close on a question. "
                "Professional and sourced; at most a few hashtags.",
}


def shape_key(platform: str) -> str:
    """Normalize a platform name to its caption-shape key (`x` → `twitter`)."""
    return "twitter" if platform in ("twitter", "x") else platform

# ── Brand voice + compliance system prompt (from BRAND.md §4/§8 + CLAUDE.md) ──

BRAND_SYSTEM = """\
You are the copywriter for Acme, a dual-brand longevity company. You write in ONE \
persona: "The Research Pharmacist" — calm, rigorous, plainspoken, the most credible \
voice in the room and never the loudest. You connect through trust, not urgency.

NON-NEGOTIABLE VOICE RULES:
- Reading level: grade 8–9. Plain English. Define any acronym on first use, e.g. \
"BPC-157 (Body Protection Compound-157)".
- Be: sourced, plainspoken, curious, patient, specific, rigorous.
- Never: hand-waving, jargon-laden, hyped, pushy, vague, overconfident.
- Conversational (not formal), respectful (not irreverent), matter-of-fact (not enthusiastic). \
The BODY is rigorous and calm — but the HOOK is allowed to be witty and human (see HOOK DOCTRINE).
- Cite when you claim: every efficacy statement is tied to a mechanism or study. \
Comfortable saying "the evidence is mixed."

HOOK DOCTRINE (the single most important rule — this is what makes a post trend):
- The HOOK = the headline (HOOK_LINE_1/2/3) AND the first line of the caption. It must STOP THE \
SCROLL. Write it like a smart friend talking, NOT like a pharmacist reading a label.
- Reading level for the hook: grade 6-8. Plain, human, witty. A real person says it out loud.
- NEVER open with jargon, a mechanism, a Latin/chemical name, a receptor, a percentage, or a \
dry "X is a Y-peptide that does Z" definition. Those belong in the body, never the hook.
- Use ONE of these proven viral patterns, fit to the topic:
  • Myth-bust / contradiction: "Everyone's wrong about ___." / "Two things that aren't the same."
  • Curiosity gap (SPECIFIC, not vague): "The part nobody mentions about ___." / "What ___ actually does."
  • Question: "Why is nobody talking about ___?" / "___ or ___ — which one's the hype?"
  • Plain-truth contrast: "The hype says ___. The studies say ___."
- The wit comes from CURIOSITY and CONTRAST and plain language — NOT from exaggeration. Every \
compliance rule below still holds: no hype words, no miracle/cure/breakthrough, no promised outcomes.
- Acme's angle is always the same and it's both honest and viral: everyone is selling the hype; \
we show the actual research and the COA. Lead with that tension.

CAPTION RULES (enforce strictly):
- NEVER open the caption with the word "I", with the brand name, or with a generic \
statement ("In today's world…", "Are you tired of…").
- Open on a specific, concrete observation or finding.
- Max 3 emoji, and ONLY from this set: 🔬 🧬 📊 ⚡ ✓. Zero emoji is fine and often better.
- No exclamation-point hype. No "miracle", "breakthrough", "game-changer", "cure".

__COMPLIANCE_BLOCK__
- Acme Health content: clinician-supervised; therapeutic framing is allowed only \
when clinician-reviewed and source-cited.

OVERLAY COPY RULES (for the on-image template):
- EYEBROW: 2–4 words, ALL CAPS, a category label (e.g. "GLP-1 RESEARCH").
- Headline splits into 3 short lines. HOOK_LINE_2_ITALIC is the single emphasis \
phrase rendered in italic green — make it the most evocative 1–3 words. Lines 1 and \
3 are plain. Total headline ≤ 8 words. No period unless it's a question.
- SUBTITLE_TEXT: one line, ≤ 7 words, often "Term · Term · Term" format.
- CTA_LABEL: 2–3 words, imperative, ALL CAPS (e.g. "READ THE COA", "EXPLORE PROTOCOL").

You output ONLY a JSON object — no prose, no code fences — with exactly these keys:
{
  "EYEBROW": "...",
  "HOOK_LINE_1": "...",
  "HOOK_LINE_2_ITALIC": "...",
  "HOOK_LINE_3": "...",
  "SUBTITLE_TEXT": "...",
  "CTA_LABEL": "...",
  "caption": "the full social caption following all caption rules",
  "hashtags": ["#tag", "..."],
  "alt_text": "literal description of the image for accessibility"
}
"""


# ── Carousel deck system prompt (--carousel N) — Devon's Stage 3 "slide copy" ──
# Reuses the same Research-Pharmacist voice + compliance as BRAND_SYSTEM, but emits
# an N-slide deck instead of one card. Built with .format(n=, ruo_rule=) at call time.
CAROUSEL_SYSTEM = """\
You are the copywriter for Acme, a dual-brand longevity company, writing in ONE \
persona: "The Research Pharmacist" — calm, rigorous, plainspoken, the most credible \
voice in the room and never the loudest. You connect through trust, not urgency.

You are writing an INSTAGRAM CAROUSEL: a deck of exactly {n} slides that teaches ONE \
idea, slide by slide, building from a hook to a close.

NON-NEGOTIABLE VOICE: reading level grade 8-9; plain English; define any acronym on \
first use; sourced, specific, patient; never hyped, never vague. Conversational, \
matter-of-fact. Comfortable saying "the evidence is mixed."

HOOK DOCTRINE (slide 1 + the caption's first line — this is what makes the deck trend):
- Slide 1's headline and the caption opener must STOP THE SCROLL. Write them like a smart friend \
talking (grade 6-8, plain, witty, human) — NEVER a dry "X is a Y-peptide" definition, a mechanism, \
a chemical/Latin name, a receptor, or a percentage. Save all of that for the middle slides.
- Use a proven viral pattern: myth-bust/contradiction ("Everyone's wrong about ___"), SPECIFIC \
curiosity gap ("What ___ actually does"), a question ("Why is nobody talking about ___?"), or \
plain-truth contrast ("The hype says ___. The studies say ___."). Acme's honest+viral angle: \
everyone sells the hype; we show the research and the COA. Wit from curiosity/contrast, NEVER hype.

__COMPLIANCE_BLOCK__

SLIDE-DECK STRUCTURE (exactly {n} slides, in order):
- Slide 1 = the HOOK / cover: a scroll-stopping human hook (see HOOK DOCTRINE), not a definition. \
EYEBROW = the topic label.
- Middle slides = ONE idea each (mechanism, evidence, comparison, caveat) — build the argument.
- Final slide = the closer. {ruo_rule}
- Each slide carries: EYEBROW (2-4 words, ALL CAPS, a category label); a 3-part headline \
HEAD_1 + HEAD_2_ITALIC + HEAD_3 that reads as ONE short phrase (<=6 words total; \
HEAD_2_ITALIC is the 1-3 word emphasis rendered green italic; HEAD_3 may be ""); and \
BODY (1-3 plain sentences, <=45 words, with a source where you make a research claim).

You output ONLY a JSON object — no prose, no code fences — with exactly these keys:
{{
  "slides": [
    {{"EYEBROW": "...", "HEAD_1": "...", "HEAD_2_ITALIC": "...", "HEAD_3": "...", "BODY": "..."}}
  ],
  "caption": "the Instagram caption: hook line, 2-3 short sentences, a CTA",
  "hashtags": ["#tag", "..."],
  "alt_text": "literal description of the carousel for accessibility"
}}
The "slides" array MUST have exactly {n} objects.
"""

_RUO_SLIDE_RULE_LABS = (
    "For Acme LABS: the final slide's EYEBROW = \"RESEARCH USE ONLY\" and its BODY MUST "
    "end with the exact sentence \"For research use only — not for human consumption.\""
)
_RUO_SLIDE_RULE_HEALTH = (
    "Close with a clear, compliant CTA (e.g. explore the protocol / read the research) — "
    "no promised outcomes, no specific human dosing."
)
RUO_SENTENCE = "For research use only — not for human consumption."


def load_api_key():
    env_file = SCRIPT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    sys.exit("ERROR: OPENROUTER_API_KEY not found in .env or environment")


def build_user_prompt(args, brand):
    pkey = shape_key(args.platform)
    parts = [
        f"Brand: Acme {args.brand.title()} ({brand['scope']}).",
        f"Tagline: {brand['tagline']}. Handle: {brand['handle']}. URL: {brand['url']}.",
        f"Topic: {args.topic}.",
        f"Target platform for the caption: {args.platform}.",
        f"Platform caption shape — follow it exactly: {PLATFORM_SHAPES[pkey]}",
    ]
    if pkey == "twitter":
        parts.append(
            "HARD RULE for X: the caption MUST be ≤280 characters and contain NO '#' hashtags; "
            "return an EMPTY \"hashtags\" array."
        )
    if args.product_feature:
        chips = []
        if args.compound:
            chips.append(f"compound name: {args.compound}")
        if args.cls:
            chips.append(f"class chip: {args.cls}")
        chips.append("COA AVAILABLE chip applies")
        parts.append(
            "This is a PRODUCT-FEATURE post. Reference these in the caption where natural: "
            + "; ".join(chips)
            + f". The compliance line \"{RUO_LINE}\" will be appended automatically — "
            "do not omit product-research framing."
        )
    parts.append(
        "Write the headline so HOOK_LINE_2_ITALIC carries the emotional weight. "
        "Return the JSON object only."
    )
    return "\n".join(parts)


def call_openrouter(messages, model, api_key):
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://acmelabs.co",
            "X-Title": "Acme Copy Engine",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.exit(f"ERROR: OpenRouter {e.code}: {body}")
    except urllib.error.URLError as e:
        sys.exit(f"ERROR: network failure: {e}")


def extract_json(text):
    """Parse the model's content as JSON, tolerating code fences."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))      # may raise JSONDecodeError → caller can retry
        raise ValueError(f"no JSON object in model output:\n{text[:300]}")


# ── Compliance enforcement (safety net beyond the prompt) ────────────────────

# Compliance (RED/YELLOW) — single source of truth is compliance.py (Red/Yellow/Green framework).
from compliance import red_hits, yellow_hits, say_instead, PROMPT_RULES
# Auto-retry budget when the model emits a RED claim or non-JSON (the publish gate is the hard
# backstop; this just closes the gap so produced copy is usually clean on the first pass).
MAX_COMPLIANCE_RETRIES = 2
ALLOWED_EMOJI = set("🔬🧬📊⚡✓")
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF←-⇿⬀-⯿]"
)


def enforce(result, args, brand):
    warnings = []

    # Handle and brand name are always derived from brand config, never model-chosen
    result["HANDLE"] = brand["handle"]
    result["BRAND_NAME"] = brand["wordmark"]

    caption = result.get("caption", "")

    # RED claims (FDA/Meta hard-stops) — scan the caption AND every slide body/headline,
    # not just the caption (the old check missed slide copy → "healing" slipped through).
    texts = [("caption", caption)]
    for i, s in enumerate(result.get("slides") or []):
        for k in ("HEAD_1", "HEAD_2_ITALIC", "HEAD_3", "BODY"):
            if isinstance(s, dict) and s.get(k):
                texts.append((f"slide{i+1}.{k}", s[k]))
    for where, t in texts:
        for hit in red_hits(t):
            fix = say_instead(hit)
            warnings.append(f"RED claim in {where}: {hit!r}" + (f" — say instead: {fix}" if fix else ""))
    # YELLOW: efficacy verbs without research-subject framing/hedge (advisory).
    yl = yellow_hits(caption)
    if yl:
        warnings.append(f"caption efficacy verb(s) {yl} need YELLOW framing "
                        "('research subjects' + 'may'/'research suggests')")

    # Caption must not open with "I", brand name, or a generic lead-in
    first = caption.lstrip().split(maxsplit=1)
    if first:
        lead = first[0].strip(".,!:").lower()
        if lead in {"i", "acme"}:
            warnings.append(f"caption opens with disallowed word: {first[0]!r}")

    # Emoji policy: max 3, only the allowed set
    emojis = EMOJI_RE.findall(caption)
    bad = [e for e in emojis if e not in ALLOWED_EMOJI]
    if bad:
        warnings.append(f"caption uses non-approved emoji: {bad}")
    if len(emojis) > 3:
        warnings.append(f"caption uses {len(emojis)} emoji (max 3)")

    # Product-feature: RUO line is mandatory — auto-append if missing
    if args.product_feature and RUO_LINE not in caption:
        caption = caption.rstrip() + f"\n\n{RUO_LINE}"
        result["caption"] = caption
        warnings.append("RUO line auto-appended to caption")

    # Alt text: flag plain-white-background descriptions (brand forbids it)
    alt = result.get("alt_text", "")
    if re.search(r"\bwhite\s+background\b", alt, re.IGNORECASE):
        corrected = re.sub(
            r"\bwhite\s+background\b",
            "warm cream background",
            alt,
            flags=re.IGNORECASE,
        )
        result["alt_text"] = corrected
        warnings.append("alt_text: 'white background' replaced with 'warm cream background'")

    return result, warnings


def build_carousel_user_prompt(args, brand):
    parts = [
        f"Brand: Acme {args.brand.title()} ({brand['scope']}).",
        f"Tagline: {brand['tagline']}. Handle: {brand['handle']}. URL: {brand['url']}.",
        f"Topic: {args.topic}.",
        f"Build a {args.carousel}-slide carousel that teaches this topic clearly.",
        f"Target platform for the caption: {args.platform}.",
    ]
    if args.product_feature:
        chips = []
        if args.compound:
            chips.append(f"compound: {args.compound}")
        if args.cls:
            chips.append(f"class: {args.cls}")
        parts.append(
            "This deck features an Acme product — reference where natural ("
            + "; ".join(chips) + "). Keep strict research framing."
        )
    parts.append("Return the JSON object only, with exactly "
                 f"{args.carousel} slides in the \"slides\" array.")
    return "\n".join(parts)


def enforce_carousel(result, args, brand):
    """Compliance net for --carousel decks: banned-claim scan over every slide + the
    caption, RUO on the final Labs slide, and the shared caption/emoji checks."""
    warnings = []
    result["HANDLE"] = brand["handle"]
    result["BRAND_NAME"] = brand["wordmark"]

    slides = result.get("slides")
    if not isinstance(slides, list) or not slides:
        warnings.append("model returned no 'slides' array")
        return result, warnings
    if len(slides) != args.carousel:
        warnings.append(f"model returned {len(slides)} slides (asked for {args.carousel})")

    # RED-claim scan across every slide's text (Red/Yellow/Green framework).
    for i, s in enumerate(slides, 1):
        blob = " ".join(str(s.get(k, "")) for k in ("HEAD_1", "HEAD_2_ITALIC", "HEAD_3", "BODY"))
        for hit in red_hits(blob):
            fix = say_instead(hit)
            warnings.append(f"RED claim in slide {i}: {hit!r}" + (f" — say instead: {fix}" if fix else ""))

    # RUO on the final slide for Labs / product-feature decks (auto-append if missing).
    if (args.brand == "labs" or args.product_feature):
        last = slides[-1]
        body = last.get("BODY", "")
        if not re.search(r"research use only|not for human consumption", body, re.IGNORECASE):
            last["BODY"] = (body.rstrip() + " " + RUO_SENTENCE).strip()
            warnings.append("RUO sentence auto-appended to the final slide")

    # Shared caption checks (RED/YELLOW, lead-word, emoji policy).
    caption = result.get("caption", "")
    for hit in red_hits(caption):
        fix = say_instead(hit)
        warnings.append(f"RED claim in caption: {hit!r}" + (f" — say instead: {fix}" if fix else ""))
    yl = yellow_hits(caption)
    if yl:
        warnings.append(f"caption efficacy verb(s) {yl} need YELLOW framing ('research subjects' + hedge)")
    first = caption.lstrip().split(maxsplit=1)
    if first and first[0].strip(".,!:").lower() in {"i", "acme"}:
        warnings.append(f"caption opens with disallowed word: {first[0]!r}")
    emojis = EMOJI_RE.findall(caption)
    bad = [e for e in emojis if e not in ALLOWED_EMOJI]
    if bad:
        warnings.append(f"caption uses non-approved emoji: {bad}")
    if len(emojis) > 3:
        warnings.append(f"caption uses {len(emojis)} emoji (max 3)")

    return result, warnings


def strip_brand_block(prompt: str) -> str:
    """Drop the leading brand visual-style block from a generation prompt.

    produce.py / the brand-injection path prepends a fixed IMAGE/VIDEO Brand
    Prompt Block (palette, lens, lighting, mood) terminated by `::`. That styling
    is irrelevant to caption copy and can distract the model, so we keep only the
    creative content after the final `::`. Prompts without `::` are returned as-is.
    """
    if "::" in prompt:
        content = prompt.rsplit("::", 1)[-1].strip()
        if content:
            return content
    return prompt.strip()


def fetch_job_prompt(job_id: str) -> str:
    """Fetch a Higgsfield job and return its generation prompt, or exit on failure."""
    import subprocess
    result = subprocess.run(
        ["higgsfield", "generate", "get", job_id, "--json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        sys.exit(f"ERROR: could not fetch Higgsfield job {job_id}:\n{result.stderr.strip() or result.stdout.strip()}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        sys.exit(f"ERROR: could not parse Higgsfield job response:\n{result.stdout[:400]}")
    job = data[0] if isinstance(data, list) and data else data
    # Prompt location varies by job shape. Higgsfield video jobs nest it under
    # "params"; some shapes use a top-level "prompt" or an "input" object.
    prompt = job.get("prompt")
    for container in ("params", "input"):
        if not prompt and isinstance(job.get(container), dict):
            prompt = job[container].get("prompt")
    if not prompt:
        # Surface what we got so the caller can decide
        status = job.get("status", "unknown")
        sys.exit(
            f"ERROR: no prompt found in job {job_id} (status={status}). "
            f"Available keys: {list(job.keys())}. Pass a topic manually with positional arg."
        )
    topic = strip_brand_block(prompt)
    print(f"[copy] derived topic from job {job_id}: {topic[:120]!r}", file=sys.stderr)
    return topic


def main():
    ap = argparse.ArgumentParser(
        description="Generate Acme brand-voice copy via OpenRouter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("topic", nargs="?", help="What the post is about (omit when using --job-id)")
    ap.add_argument("--job-id", dest="job_id",
                    help="Higgsfield job ID — auto-derives topic from the job's generation prompt")
    ap.add_argument("--brand", choices=["labs", "health"], required=True,
                    help="labs = peptides/product/COA; health = protocols/metabolic")
    ap.add_argument("--kind", choices=["full", "overlay", "caption"], default="full",
                    help="(reserved) which copy to emphasize; full returns everything")
    ap.add_argument("--platform", default="instagram",
                    choices=["instagram", "tiktok", "twitter", "x", "youtube",
                             "threads", "facebook", "linkedin"],
                    help="Caption shape per SOUL §6 / §1A.4. `x` aliases `twitter`.")
    ap.add_argument("--carousel", type=int, metavar="N",
                    help="Generate an N-slide carousel deck (output: slides[] + caption + "
                         "hashtags + alt_text) instead of a single card. 5 is a good default.")
    ap.add_argument("--product-feature", action="store_true", dest="product_feature",
                    help="Triggers RUO auto-append + class/COA chip framing")
    ap.add_argument("--compound", help="Compound name for the class/COA chips")
    ap.add_argument("--class", dest="cls", help="Compound class chip, e.g. PENTADECAPEPTIDE")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"OpenRouter model (default {DEFAULT_MODEL})")
    ap.add_argument("--raw", action="store_true", help="Print the full OpenRouter response")
    args = ap.parse_args()

    if args.job_id:
        args.topic = fetch_job_prompt(args.job_id)
    elif not args.topic:
        ap.error("topic is required when --job-id is not provided")

    api_key = load_api_key()
    brand = BRANDS[args.brand]

    if args.carousel:
        if args.carousel < 2 or args.carousel > 10:
            ap.error("--carousel N must be between 2 and 10 (Instagram allows 2-10 slides)")
        ruo_rule = _RUO_SLIDE_RULE_LABS if args.brand == "labs" else _RUO_SLIDE_RULE_HEALTH
        system = CAROUSEL_SYSTEM.format(n=args.carousel, ruo_rule=ruo_rule)
        user = build_carousel_user_prompt(args, brand)
    else:
        system = BRAND_SYSTEM
        user = build_user_prompt(args, brand)
    system = system.replace("__COMPLIANCE_BLOCK__", PROMPT_RULES)   # inject the full framework

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    enforce_fn = enforce_carousel if args.carousel else enforce

    # Auto-retry loop: regenerate if the model returns non-JSON OR emits a RED claim, feeding
    # back the exact violations so the rewrite is compliant. Bounded (the gate is the backstop).
    result, warnings = None, []
    for attempt in range(MAX_COMPLIANCE_RETRIES + 1):
        resp = call_openrouter(messages, args.model, api_key)
        if args.raw:
            print(json.dumps(resp, indent=2, ensure_ascii=False))
            return
        content = resp["choices"][0]["message"]["content"]
        try:
            result = extract_json(content)
        except (json.JSONDecodeError, ValueError):
            if attempt >= MAX_COMPLIANCE_RETRIES:
                sys.exit(f"ERROR: model did not return valid JSON after {attempt+1} tries:\n{content[:400]}")
            print(f"[copy] non-JSON output (attempt {attempt+1}/{MAX_COMPLIANCE_RETRIES+1}) — retrying", file=sys.stderr)
            messages += [
                {"role": "assistant", "content": content},
                {"role": "user", "content": "Your previous reply was not valid JSON. Reply with ONLY "
                 "the JSON object specified — no prose, no markdown code fences."},
            ]
            continue

        result, warnings = enforce_fn(result, args, brand)
        reds = [w for w in warnings if w.startswith("RED claim")]
        if not reds or attempt >= MAX_COMPLIANCE_RETRIES:
            break

        # RED claim slipped through → regenerate with the exact violations + compliant framing.
        print(f"[copy] RED claim(s) on attempt {attempt+1}/{MAX_COMPLIANCE_RETRIES+1} — "
              f"regenerating compliant copy ({len(reds)} hit(s))", file=sys.stderr)
        messages += [
            {"role": "assistant", "content": content},
            {"role": "user", "content":
                "Your output contained FORBIDDEN red-claim language that violates FDA/Meta policy:\n"
                + "\n".join(f"- {r}" for r in reds)
                + "\n\nRewrite the COMPLETE JSON object. Replace EVERY forbidden claim with compliant "
                  "research-subject framing: attribute any outcome to 'research subjects' / 'study "
                  "participants' (never the reader/'you'/'your'), hedge with 'research suggests' / "
                  "'may support' / 'studies indicate', keep it research-use-only, and cite a study where "
                  "you make a claim. Do NOT use heal/cure/treat/prevent/reverse/'repairs tendons'/boosts/"
                  "burns/builds or any customer-directed outcome. Output ONLY the corrected JSON."},
        ]

    if reds := [w for w in warnings if w.startswith("RED claim")]:
        print(f"[copy] ⚠ {len(reds)} RED claim(s) REMAIN after {MAX_COMPLIANCE_RETRIES} retries — "
              "human must REVISE (the publish gate will block this).", file=sys.stderr)
    for w in warnings:
        print(f"[copy] WARNING: {w}", file=sys.stderr)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
