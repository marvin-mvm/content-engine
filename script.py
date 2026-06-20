#!/usr/bin/env python3
"""script.py — F7 RV2: write the spoken voiceover SCRIPT for a reel (NET-NEW).

A 15-45s Research-Pharmacist script: a hook in the first ~2 seconds, then
hook -> build -> payoff -> CTA (the VIRAL_FRAMEWORK retention structure
0-2 HOOK / 2-5 PROOF / 5-8 VALUE / 8-10 CTA, scaled to length). Reuses
copywriter.py's brand-voice engine and compliance.py's Red/Yellow/Green
framework by IMPORT — no edits to those shared tools. 0 Higgsfield credits.

The script is the thing Kokoro TTS narrates in RV4 AND the ground truth that
reconciles Whisper's word-timings — so the burned captions are exact (we wrote
the words, so there is no mis-hear fight).

It writes brief.script (the exact spoken words) + a script.json sidecar with the
structured beats so GATE 1 (concept approval) can review the concept BEFORE any
Higgsfield credit is spent. A RED compliance claim FAILS the run (exit 2) so a
non-compliant concept can never reach a credit spend.

Usage:
  script.py output/jobs/ACME-021                 # read brief.json -> brief.script + script.json
  script.py output/jobs/ACME-021 --seconds 30    # target ~30s of narration
  script.py --topic "How BPC-157 actually works" --brand labs --pillar science  # ad-hoc, prints
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Reuse the shared engines (voice + OpenRouter + compliance) — never duplicate or edit them.
from copywriter import call_openrouter, extract_json, load_api_key, DEFAULT_MODEL, BRAND_SYSTEM
from compliance import red_hits, yellow_hits, say_instead, PROMPT_RULES

WS = Path(__file__).parent.resolve()

# Calm, authoritative narration ~145 wpm -> ~2.4 words/sec. 15-45s => ~36-108 spoken words.
WORDS_PER_SEC = 2.4
MIN_SECONDS, MAX_SECONDS = 15, 45
DEFAULT_SECONDS = 28

SCRIPT_SYSTEM = (
    BRAND_SYSTEM
    + "\n\n" + PROMPT_RULES
    + "\n\nYou are writing the SPOKEN VOICEOVER for a 15-45 second vertical video reel — words a "
      "narrator says aloud, nothing else. Obey the Research-Pharmacist voice and the compliance "
      "framework above (NEVER a RED claim).\n"
      "STRUCTURE (VIRAL_FRAMEWORK retention curve, scaled to length):\n"
      "  HOOK   (first ~2s) — one scroll-stopping line; contrarian, a curiosity gap, or an identity "
      "claim. It must land in the first sentence.\n"
      "  BUILD  — the proof: a stat, a study reference, or a credibility signal (research-subject "
      "framed, hedged).\n"
      "  PAYOFF — the actual value: the mechanism / science / specific takeaway.\n"
      "  CTA    — a soft close. For Labs, the close MUST carry research-use framing (e.g. 'For "
      "research use only.') and point to the brand; for Health, a clean follow/learn-more CTA.\n"
      "HARD RULES: output ONLY spoken words — no scene directions, no '[pause]', no stage notes, no "
      "emojis, no hashtags, no on-screen-text callouts, no speaker labels. Short, punchy sentences "
      "a TTS voice reads naturally. Do not invent claims; keep every efficacy statement compliant."
)


def _target_words(seconds: int) -> int:
    return max(12, round(seconds * WORDS_PER_SEC))


def build_user_prompt(*, topic, pillar, persona, brand, reference, seconds, avoid=None) -> str:
    cloned = (reference or {}).get("cloned_format")
    parts = [
        f"Brand: Acme {brand.title()}.",
        f"Content pillar: {pillar}. Target persona: {persona}.",
        f"Reel topic / angle: {topic}.",
        f"Target length: ~{seconds} seconds (~{_target_words(seconds)} spoken words — stay close).",
    ]
    if cloned:
        parts.append(f"Clone this viral STRUCTURE only (not its words/claims): {cloned}.")
    if avoid:
        parts.append(
            "AVOID repeating these — reel concepts a human PREVIOUSLY REJECTED/REVISED. Do not "
            "reuse their angle or repeat the flagged mistake (the REASON says why):\n" + avoid)
    parts.append(
        "Return ONLY a JSON object with the spoken text per beat plus the joined script:\n"
        '{ "hook": "<~1 sentence, lands in the first 2s>", '
        '"build": "<proof/credibility, research-subject framed>", '
        '"payoff": "<the mechanism/value>", '
        '"cta": "<soft close; Labs carries research-use framing>", '
        '"full_text": "<hook + build + payoff + cta as ONE clean spoken paragraph, the exact words '
        'to narrate>" }'
    )
    return "\n".join(parts)


def generate(*, topic, pillar, persona, brand, reference=None, seconds=DEFAULT_SECONDS,
             model=DEFAULT_MODEL, api_key=None, retry_on_red=True, avoid=None):
    """Generate the spoken script. Returns (beats_dict, warnings). Raises ScriptComplianceError
    if a RED claim survives a compliant-rewrite retry (so it can never reach a credit spend).
    `avoid` is an optional compact block of previously-rejected reel lessons to steer away from."""
    api_key = api_key or load_api_key()
    user = build_user_prompt(topic=topic, pillar=pillar, persona=persona, brand=brand,
                             reference=reference, seconds=seconds, avoid=avoid)
    messages = [{"role": "system", "content": SCRIPT_SYSTEM}, {"role": "user", "content": user}]

    for attempt in (1, 2):
        resp = call_openrouter(messages, model, api_key)
        beats = extract_json(resp["choices"][0]["message"]["content"])
        full = (beats.get("full_text") or " ".join(
            beats.get(k, "") for k in ("hook", "build", "payoff", "cta"))).strip()
        beats["full_text"] = full
        red = red_hits(full)
        if not red:
            break
        if attempt == 1 and retry_on_red:
            fixes = "; ".join(f"{h!r} -> {say_instead(h) or 'remove it'}" for h in red[:6])
            messages.append({"role": "assistant", "content": json.dumps(beats, ensure_ascii=False)})
            messages.append({"role": "user", "content":
                f"That script contains BANNED (RED) claims: {red}. Rewrite it fully compliant. "
                f"Apply: {fixes}. Return the same JSON shape."})
            continue
        raise ScriptComplianceError(red, full)

    words = len(full.split())
    est = round(words / WORDS_PER_SEC, 1)
    warnings = []
    yh = yellow_hits(full)
    if yh:
        warnings.append(f"YELLOW efficacy verbs without framing: {yh} — verify research-subject attribution")
    if not (MIN_SECONDS <= est <= MAX_SECONDS):
        warnings.append(f"est {est}s outside {MIN_SECONDS}-{MAX_SECONDS}s ({words} words) — adjust --seconds")
    if brand == "labs" and "research use only" not in full.lower():
        warnings.append("Labs script: no 'research use only' framing in the CTA — confirm RUO before generation")
    beats.update(words=words, est_seconds=est, warnings=warnings)
    return beats, warnings


class ScriptComplianceError(Exception):
    def __init__(self, red, text):
        self.red = red
        self.text = text
        super().__init__(f"RED compliance claims survived rewrite: {red}")


def write_to_job(job_dir: Path, beats: dict) -> None:
    """Persist brief.script + the script.json sidecar (reviewed at GATE 1)."""
    brief_path = job_dir / "brief.json"
    brief = json.loads(brief_path.read_text())
    brief["script"] = beats["full_text"]
    brief_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2))
    (job_dir / "script.json").write_text(json.dumps(beats, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="F7 RV2 — spoken reel script generator (0 credits)")
    ap.add_argument("job_dir", nargs="?", help="Job folder with a type=reel brief.json")
    ap.add_argument("--topic", help="Ad-hoc topic (instead of a job brief)")
    ap.add_argument("--pillar", default="science", help="Pillar (ad-hoc mode; default science)")
    ap.add_argument("--persona", default="P1", choices=["P1", "P2", "P3"])
    ap.add_argument("--brand", default="labs", choices=["labs", "health"])
    ap.add_argument("--seconds", type=int, default=DEFAULT_SECONDS, help=f"Target length (default {DEFAULT_SECONDS})")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    reference = None
    if args.job_dir:
        job = Path(args.job_dir).resolve()
        brief_path = job / "brief.json"
        if not brief_path.exists():
            sys.exit(f"[script] no brief.json in {job}")
        brief = json.loads(brief_path.read_text())
        if brief.get("type") != "reel":
            sys.exit(f"[script] brief type is {brief.get('type')!r}; script.py only writes reel scripts")
        topic, pillar = brief["topic"], brief["pillar"]
        persona, brand = brief.get("persona", "P1"), brief.get("brand", "labs")
        reference = brief.get("reference")
    elif args.topic:
        job = None
        topic, pillar, persona, brand = args.topic, args.pillar, args.persona, args.brand
    else:
        ap.error("provide a job_dir or --topic")

    # Steer away from past mistakes: inject the (few) previously-rejected reel lessons.
    try:
        import engine as eng
        avoid = eng.rejected_lessons_text(kind="reel")
        if avoid:
            print(f"[script] steering away from {len(avoid.splitlines())} prior rejected reel(s)", file=sys.stderr)
    except Exception:
        avoid = None

    try:
        beats, warnings = generate(topic=topic, pillar=pillar, persona=persona, brand=brand,
                                   reference=reference, seconds=args.seconds, model=args.model,
                                   avoid=avoid)
    except ScriptComplianceError as e:
        print(f"[script] BLOCKED — RED compliance claims survived rewrite: {e.red}", file=sys.stderr)
        print(f"[script] offending text: {e.text}", file=sys.stderr)
        sys.exit(2)

    print(f"\nHOOK   {beats.get('hook','')}")
    print(f"BUILD  {beats.get('build','')}")
    print(f"PAYOFF {beats.get('payoff','')}")
    print(f"CTA    {beats.get('cta','')}")
    print(f"\nSCRIPT ({beats['words']} words ≈ {beats['est_seconds']}s):\n{beats['full_text']}")
    for w in warnings:
        print(f"[script] WARN {w}", file=sys.stderr)

    if job:
        write_to_job(job, beats)
        print(f"\n[script] wrote brief.script + script.json -> {job}", file=sys.stderr)


if __name__ == "__main__":
    main()
