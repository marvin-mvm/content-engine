"""compliance.py — Acme's single source of truth for the Marketing Compliance Claims
Framework (Red / Yellow / Green). Every layer imports from HERE so the rules can never drift:

  • engine.py     — produce-step gate + the mirror the publish gate reads
  • publish.py    — the hard pre-publish compliance gate (RED = exit 1, publish nothing)
  • copywriter.py — generation-time safety net + the prompt's hard-stop list

  🔴 RED    — never publish. FDA/Meta violation. HARD BLOCK.
  🟡 YELLOW — factually grounded but needs research-subject attribution + hedging + a citable
              source. We don't block these; we WARN so a human adds the framing.
  🟢 GREEN  — mechanism / COA / education / specs / RUO. No medical claim → free.

RUO ("For research use only. Not for human consumption.") must ride every Labs compound post.
"""
from __future__ import annotations

import re

RUO_SENTENCE = "For research use only — not for human consumption."
RUO_RE = re.compile(r"research use only|not for human consumption|\bRUO\b", re.IGNORECASE)

# ── 🔴 RED — never use (hard block) ──────────────────────────────────────────────
# Disease/condition action verbs (every tense) + the framework's named banned outcome
# claims + customer-directed outcomes ("…your skin") + testimonials + hype words.
# Tuned to MISS compliant copy: "Acme Health" (heal≠health), "tissue repair", "may
# support", "reverse transcriptase", "anti-aging", the RUO "not for human consumption".
RED_RE = re.compile(
    r"""
      \b(?:cure[sd]?|curing)\b
    | \b(?:treats?|treated|treating|treatments?)\b
    | \b(?:heal[sd]?|healing)\b
    | \b(?:prevent[sd]?|preventing|prevention)\b
    | \b(?:diagnos(?:e[sd]?|ing|is|tic))\b
    | \b(?:remed(?:y|ies))\b
    | \b(?:fixes|fixing)\b
    | \brevers\w*\s+(?:the\s+)?(?:age?ing|age)\b              # reverses ageing
    | \b(?:burns?|burning)\s+fat\b | \bfat[-\s]?burning\b
    | \bbuilds?\s+(?:lean\s+)?muscle\b | \bmuscle[-\s]?building\b
    | \bregrow(?:s|n|ing)?\s+(?:your\s+)?hair\b | \bhair\s+regrowth\b
    | \b(?:boosts?|increases?|raises?|elevates?)\s+(?:your\s+)?testosterone\b
    | (?<!not\s)(?<!never\s)(?<!intended\s)\bfor\s+(?:human|personal)\s+use\b   # asserting it; "not/never/not intended for human use" is COMPLIANT
    | \bsafe\s+for\s+(?:humans?|people|you)\b
    | \b(?:heals?|cures?|fixes?|repairs?|improves?|boosts?|burns?|builds?|regrows?|reverses?|restores?|treats?)\s+your\b
    | \b(?:repairs?|regenerates?|rebuilds?|restores?)\s+(?:your\s+)?(?:tendons?|ligaments?|joints?|cartilage|muscles?|bones?)\b   # "repairs tendons" — certainty claim (noun "tissue repair" is fine)
    | \bI\s+(?:healed|cured|fixed|repaired|treated)\b         # health testimonial
    | \byou(?:'ll|\s+will)\s+(?:feel|see|notice|experience|get|lose|gain|grow)\b
    | \bproven\s+to\b
    | \bguarantee[sd]?\b
    | \b(?:miracle|breakthrough|game[-\s]?changer|anti[-\s]?cancer)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Back-compat: the gate has always called this `BANNED`. Same object, comprehensive rules.
BANNED = RED_RE

# ── 🟡 YELLOW — efficacy verbs OK only with framing (advisory warning, never a block) ──
# A research-subject attribution OR a hedge anywhere in the post makes a yellow claim
# compliant; without one we surface the verbs so a human adds "research subjects … may …".
_FRAME_RE = re.compile(
    r"research\s+(?:suggest\w*|indicat\w*|found|report\w*|subjects?)"
    r"|stud(?:y|ies)\s+(?:suggest\w*|indicat\w*|found|report\w*|show\w*)"
    r"|study\s+participants?|participants?\s+reported"
    r"|may\s+(?:support|help|aid|assist)|suggests?\b|indicat\w+"
    r"|in\s+(?:preclinical|animal|rodent|in[-\s]?vitro)\b|published\s+(?:research|stud)",
    re.IGNORECASE,
)
_YELLOW_VERB_RE = re.compile(
    r"\b(supports?|improves?|increases?|enhances?|repairs?|stimulat\w+|accelerat\w+"
    r"|reduces?|restores?|promotes?|elevates?|upregulat\w+)\b",
    re.IGNORECASE,
)


def red_hits(text: str) -> list[str]:
    """Every RED claim phrase in the text (empty = clean). The hard-block signal."""
    return [m.group(0) for m in RED_RE.finditer(text or "")]


def yellow_hits(text: str) -> list[str]:
    """Efficacy verbs present WITHOUT any research-subject framing/hedge nearby → the post
    needs YELLOW framing before it's compliant. Advisory only (deduped, lowercased)."""
    t = text or ""
    if _FRAME_RE.search(t):
        return []
    return sorted({m.group(0).lower() for m in _YELLOW_VERB_RE.finditer(t)})


# "✅ Say this instead" — compliant rewrites surfaced in warnings to speed the human REVISE.
SAY_INSTEAD = {
    "heal": "research subjects showed accelerated tissue-repair markers (cite the study)",
    "cure": "[compound] has been studied for its effects on … in research subjects",
    "treat": "researched for its effects on … markers in animal/clinical studies",
    "prevent": "studied for its effects on … in study subjects",
    "revers": "research suggests … improvements in study subjects (no 'reverse ageing')",
    "burns fat": "research subjects showed changes in body composition in controlled studies",
    "builds muscle": "research subjects showed changes in lean body mass in controlled studies",
    "regrow": "studied for its effects on hair-follicle activity in research subjects",
    "your": "attribute to 'research subjects' / 'study participants' — never the customer ('your')",
    "testosterone": "studied for effects on endogenous hormone levels in research subjects",
    "human use": "For research use only. Not for human consumption.",
    "personal use": "For research use only. Not for human consumption.",
}


def say_instead(hit: str) -> str | None:
    """Best-effort compliant-rewrite hint for a RED hit (matches on a keyword)."""
    h = hit.lower()
    for key, fix in SAY_INSTEAD.items():
        if key in h:
            return fix
    return None


# ── Prompt block — the same framework, written for the LLM (prevention layer) ────
# Injected verbatim into copywriter.py's system prompts so it GENERATES compliant copy
# (the regex above is the detection safety-net behind it).
PROMPT_RULES = """\
COMPLIANCE — Marketing Claims Framework (Red/Yellow/Green). HARD STOPS, no exceptions:
🔴 NEVER write: that a compound heals / cures / treats / prevents / diagnoses / reverses /
   fixes / repairs anything; "burns fat", "builds muscle", "regrows hair", "boosts testosterone",
   "improves your skin", "repairs tendons/joints"; "for human use" or "for personal use"; the words
   miracle / breakthrough / game-changer / "proven to" / guaranteed; ANY customer-directed outcome
   ("you'll feel…", "your knee/skin/hair") or first-person testimonial ("I healed…").
🟡 EFFICACY CLAIMS ONLY WITH FRAMING — every outcome/benefit statement MUST: (a) attribute to
   "research subjects" / "study participants" (never "you"/"users"/"customers"), (b) hedge with
   "research suggests" / "may support" / "studies indicate" / "in preclinical (animal/in-vitro)
   models", and (c) be tied to a real study. Examples:
     ✗ "BPC-157 repairs tendons"   → ✓ "Research suggests BPC-157 may support tissue-repair markers in study subjects."
     ✗ "Reverses ageing"           → ✓ "Studied for its effects on telomere length in research subjects."
     ✗ "Boosts testosterone"       → ✓ "Studied for effects on endogenous hormone levels in research subjects."
🟢 WRITE FREELY (no claim, no risk): mechanism of action, COA / purity / third-party testing / specs,
   plain-language research education (summarise studies without promising a customer outcome), longevity
   science, founder/brand story. Make this the bulk of the copy.
Labs = research-use-only framing throughout; never personal dosing or medical advice; never name a competitor."""
