#!/usr/bin/env python3
"""
copy.py — Acme brand-voice copy generator (OpenRouter).

Generates brand-compliant copy for a post in one call:
  - Template overlay tokens (EYEBROW, HOOK_LINE_1/2/3, SUBTITLE_TEXT, CTA_LABEL, HANDLE)
  - Social caption (the Research Pharmacist voice, enforced)
  - Hashtags + alt text

Output is a single JSON object. The overlay tokens feed produce.py --json;
the caption/hashtags/alt_text feed the Blotato publish step (SYSTEM_CONTEXT §18).

Usage:
  copy.py "TOPIC" --brand labs|health [--kind full|overlay|caption]
                  [--product-feature] [--compound "BPC-157" --class "PENTADECAPEPTIDE"]
                  [--platform instagram|tiktok|twitter|youtube]
                  [--model MODEL] [--raw]

  # Auto-derive topic from a Higgsfield job (reads the generation prompt from metadata):
  copy.py --job-id JOB_ID --brand labs|health [--platform ...]

Examples:
  # Full copy for a Health metabolic post, save tokens for produce.py:
  python3 copy.py "semaglutide mechanism of action" --brand health > /tmp/copy.json
  python3 produce.py templates/src/story-reel-dark.html --json /tmp/copy.json \\
      --bg-prompt "..."

  # Product-feature post (auto-appends RUO + class/COA chips):
  python3 copy.py "BPC-157 tissue repair research" --brand labs \\
      --product-feature --compound "BPC-157" --class "PENTADECAPEPTIDE"

  # Caption for an existing Higgsfield video — topic derived from the job prompt:
  python3 copy.py --job-id 22a79dcc-1e1d-4876-9ee1-7f8016d11a61 --brand labs --platform tiktok

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
- Serious (not funny), conversational (not formal), respectful (not irreverent), \
matter-of-fact (not enthusiastic).
- Cite when you claim: every efficacy statement is tied to a mechanism or study. \
Comfortable saying "the evidence is mixed."

CAPTION RULES (enforce strictly):
- NEVER open the caption with the word "I", with the brand name, or with a generic \
statement ("In today's world…", "Are you tired of…").
- Open on a specific, concrete observation or finding.
- Max 3 emoji, and ONLY from this set: 🔬 🧬 📊 ⚡ ✓. Zero emoji is fine and often better.
- No exclamation-point hype. No "miracle", "breakthrough", "game-changer", "cure".

COMPLIANCE (hard stops):
- NEVER say a compound "treats", "cures", "prevents", or "diagnoses" anything. \
Frame as "research suggests", "studies report", or "participants reported".
- Dosage is research context only — never personal medical advice.
- Never name or disparage a competitor brand.
- Acme Labs content: refer to mechanism, structure, and pre-clinical evidence only \
— it is research-use-only material, never for human use.
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
    parts = [
        f"Brand: Acme {args.brand.title()} ({brand['scope']}).",
        f"Tagline: {brand['tagline']}. Handle: {brand['handle']}. URL: {brand['url']}.",
        f"Topic: {args.topic}.",
        f"Target platform for the caption: {args.platform}.",
    ]
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
            return json.loads(m.group(0))
        sys.exit(f"ERROR: could not parse model JSON:\n{text[:500]}")


# ── Compliance enforcement (safety net beyond the prompt) ────────────────────

BANNED = re.compile(r"\b(cure|cures|cured|treat|treats|treating|prevent|prevents|"
                    r"diagnos\w*|miracle|breakthrough|game[- ]?changer)\b", re.IGNORECASE)
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

    # Banned medical-claim verbs
    if BANNED.search(caption):
        warnings.append(f"caption contains a banned claim word: {BANNED.search(caption).group(0)!r}")

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
                    choices=["instagram", "tiktok", "twitter", "youtube"])
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

    messages = [
        {"role": "system", "content": BRAND_SYSTEM},
        {"role": "user", "content": build_user_prompt(args, brand)},
    ]
    resp = call_openrouter(messages, args.model, api_key)

    if args.raw:
        print(json.dumps(resp, indent=2, ensure_ascii=False))
        return

    content = resp["choices"][0]["message"]["content"]
    result = extract_json(content)
    result, warnings = enforce(result, args, brand)

    for w in warnings:
        print(f"[copy] WARNING: {w}", file=sys.stderr)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
