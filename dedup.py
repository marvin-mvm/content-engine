#!/usr/bin/env python3
"""dedup.py — the content-duplication gate (Marvin 2026-06-22). 0 Higgsfield credits.

The engine was shipping near-identical posts day after day (ACME-042..045 == 037..040) because
nothing compared the TEXT of a new post against what it recently made. This module is that gate —
the single authority for "have we basically said this already?", mirroring how compliance.py is the
single claims authority.

Flow (called from research.assemble_brief / the reel script path, BEFORE any render):
  1. recent_corpus()  — gather the comparison set: everything PRODUCED in the last 7 days PLUS
     anything APPROVED/published in that window (Marvin: catch dupes at production time, not only
     after approvals accumulate).
  2. check_draft()    — ONE OpenRouter call (reusing copywriter's helpers) judges the new draft
     against the corpus. A follow-up / continuation / complement to a past post is NOT a duplicate
     and PASSES; only a genuine repeat of the hook / body / script / thumbnail-concept is flagged,
     and the judge returns a rewrite of ONLY that element.
  3. revise()         — swap in the rewritten element(s); the rest of the draft is untouched
     (Marvin: "revise that PART, not the whole draft").

Fail-OPEN by design: no API key, no corpus, or any judge error → PASS (a hiccup must never block the
morning produce). Compliance-safe: a proposed rewrite that trips a RED claim is dropped (original kept).

CLI (proving / ops):
  python3 dedup.py corpus [--days 7]            # dump the comparison corpus
  python3 dedup.py check <job_dir> [--days 7]   # judge a job's draft vs the corpus (excludes itself)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import engine as eng
from compliance import red_hits, PROMPT_RULES
from copywriter import call_openrouter, extract_json, load_api_key, DEFAULT_MODEL

WS = Path(__file__).parent.resolve()
WINDOW_DAYS = 7
CORPUS_LIMIT = 40          # cap the corpus we feed the judge (token-cost discipline)
ELEMENTS = ("hook", "body", "script", "thumbnail")   # the parts we dedup + can revise


# ── time helpers ──────────────────────────────────────────────────────────────
def _parse_iso(s: str | None) -> "datetime | None":
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _within(ts: str | None, days: int, fallback_path: Path | None = None) -> bool:
    """True if `ts` (or, missing, the fallback file's mtime) is within the last `days`."""
    dt = _parse_iso(ts)
    if dt is None and fallback_path is not None and fallback_path.exists():
        dt = datetime.fromtimestamp(fallback_path.stat().st_mtime, tz=timezone.utc)
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= datetime.now(timezone.utc) - timedelta(days=days)


# ── snapshots ───────────────────────────────────────────────────────────────--
def _hook_from_tokens(tokens: dict) -> str:
    """The on-card hook, however the template named it (story / poll / callout / carousel)."""
    keys = ("EYEBROW", "HOOK_LINE_1", "HOOK_LINE_2_ITALIC", "HOOK_LINE_3",
            "STORY_HOOK_1", "STORY_HOOK_2_ITALIC", "STORY_HOOK_3",
            "HEAD_1", "HEAD_2_ITALIC", "HEAD_3", "HEADLINE")
    return " ".join(str(tokens.get(k, "")).strip() for k in keys if tokens.get(k)).strip()


def job_snapshot(job_id: str) -> dict:
    """A compact content snapshot of a job folder for dedup comparison: hook, body, topic,
    script, caption, slide gist. Reads the brief/captions/slides directly so it works for ANY
    produced job (not just ones that reached a decision)."""
    jd = eng.JOBS_DIR / job_id
    brief = eng.load_json(jd / "brief.json") or {}
    tokens = (brief.get("image") or {}).get("set") or {}
    snap = {
        "job_id": job_id, "type": brief.get("type"), "pillar": brief.get("pillar"),
        "compound": brief.get("compound"), "topic": brief.get("topic"),
        "hook": _hook_from_tokens(tokens),
        "body": str(tokens.get("BODY") or tokens.get("SUBHEAD") or tokens.get("BODY_TEXT") or ""),
        "script": brief.get("script"),
    }
    caps = eng.load_json(jd / "captions.json")
    if isinstance(caps, dict):
        x = caps.get("x")
        snap["caption"] = (x.get("text") if isinstance(x, dict) else x) or caps.get("instagram") or ""
    slides = eng.load_json(jd / "slides.json")
    if isinstance(slides, list):
        snap["slides"] = [" / ".join(str(s.get(k, "")) for k in ("HEAD_1", "HEAD_2_ITALIC", "HEAD_3", "BODY")
                                     if s.get(k)) for s in slides if isinstance(s, dict)]
    return {k: v for k, v in snap.items() if v not in (None, "", [])}


def recent_corpus(days: int = WINDOW_DAYS, exclude_job: str | None = None) -> list[dict]:
    """The comparison set: every job PRODUCED in the last `days`, plus anything APPROVED/published
    in that window (deduped by job_id, most-recent first)."""
    seen: dict[str, dict] = {}
    jobs = sorted(eng.JOBS_DIR.glob("ACME-*"), key=lambda p: p.name, reverse=True) if eng.JOBS_DIR.exists() else []
    for jd in jobs:
        jid = jd.name
        if jid == exclude_job:
            continue
        st = eng.load_json(jd / "status.json") or {}
        if not _within(st.get("produced_at") or st.get("pushed_at"), days, fallback_path=jd / "brief.json"):
            continue
        snap = job_snapshot(jid)
        if snap.get("hook") or snap.get("topic") or snap.get("script"):
            seen[jid] = snap
    for d in eng.read_decisions():                      # approved/published may matter even if older-produced
        if not str(d.get("verb", "")).startswith("approv"):
            continue
        if not _within(d.get("at"), days):
            continue
        jid = d.get("job_id")
        if jid and jid != exclude_job and jid not in seen:
            seen[jid] = job_snapshot(jid) or {"job_id": jid, **(d.get("content") or {})}
    return list(seen.values())


# ── the judge (one OpenRouter call; reuses copywriter's client) ─────────────────
_SYSTEM = (
    "You are the duplication checker for a content engine. You compare a NEW post draft against a "
    "list of RECENT posts and decide whether the new draft repeats one of them.\n"
    "RULES:\n"
    "- A follow-up, continuation, part-2, or complement to a past post is NOT a duplicate. If the "
    "new draft deliberately builds on a recent one (same topic, new angle/depth), set follow_up=true "
    "and DO NOT flag it.\n"
    "- Only flag an element as duplicate/similar when it genuinely repeats a recent post's hook, "
    "body, script, or thumbnail concept (same idea AND near-same wording/structure). Different "
    "compound or a different angle on the same compound is NOT a duplicate.\n"
    "- When you flag an element, return `revised`: a fresh rewrite of ONLY that element — same factual "
    "meaning, different wording/angle so it no longer reads as a repeat. Keep the brand's calm, "
    "research-grade voice. Every rewrite MUST obey the compliance rules below.\n\n"
    + PROMPT_RULES +
    "\n\nReturn ONLY JSON: {\"duplicate\": bool, \"follow_up\": bool, \"reason\": \"<short>\", "
    "\"parts\": [ {\"element\": \"hook|body|script|thumbnail\", \"verdict\": \"unique|similar|duplicate\", "
    "\"matched_job\": \"ACME-NNN\", \"revised\": \"<rewrite of just this element, only if similar/duplicate>\"} ] }"
)


def _fmt_corpus(corpus: list[dict], limit: int = CORPUS_LIMIT) -> str:
    lines = []
    for c in corpus[:limit]:
        parts = [f"{c.get('job_id', '?')} [{c.get('pillar', '?')}/{c.get('compound', '-')}]"]
        if c.get("topic"):
            parts.append(f"topic: {str(c['topic'])[:120]}")
        if c.get("hook"):
            parts.append(f"hook: {str(c['hook'])[:140]}")
        if c.get("script"):
            parts.append(f"script: {str(c['script'])[:200]}")
        elif c.get("caption"):
            parts.append(f"caption: {str(c['caption'])[:200]}")
        if c.get("slides"):
            parts.append("slides: " + (" | ".join(c["slides"][:4]))[:240])
        lines.append(" — ".join(parts))
    return "\n".join(lines)


def _fmt_draft(draft: dict) -> str:
    parts = [f"pillar: {draft.get('pillar', '?')}  compound: {draft.get('compound', '-')}"]
    for k in ("topic", "hook", "body", "script", "thumbnail"):
        if draft.get(k):
            parts.append(f"{k}: {str(draft[k])[:300]}")
    if draft.get("slides"):
        parts.append("slides: " + (" | ".join(str(s) for s in draft["slides"][:6]))[:400])
    return "\n".join(parts)


def _passed(reason: str) -> dict:
    return {"duplicate": False, "follow_up": False, "parts": [], "reason": reason}


def _normalize(data) -> dict:
    if not isinstance(data, dict):
        return _passed("judge returned no object")
    parts = []
    for p in (data.get("parts") or []):
        if not isinstance(p, dict):
            continue
        el = p.get("element")
        if el not in ELEMENTS:
            continue
        rev = (p.get("revised") or "").strip()
        if rev and red_hits(rev):                       # never apply a non-compliant rewrite
            rev = ""
        parts.append({"element": el, "verdict": p.get("verdict", "similar"),
                      "matched_job": p.get("matched_job"), "revised": rev})
    return {"duplicate": bool(data.get("duplicate")), "follow_up": bool(data.get("follow_up")),
            "reason": str(data.get("reason", ""))[:300], "parts": parts}


def check_draft(draft: dict, corpus: list[dict] | None = None, *,
                api_key: str | None = None, model: str = DEFAULT_MODEL) -> dict:
    """Judge `draft` against recent posts. Returns a verdict dict (see _SYSTEM). Fail-open."""
    corpus = recent_corpus(exclude_job=draft.get("job_id")) if corpus is None else corpus
    if not corpus:
        return _passed("no recent posts to compare against")
    try:
        api_key = api_key or load_api_key()
    except Exception as ex:
        return _passed(f"dedup disabled (no api key: {ex})")
    user = (f"NEW DRAFT:\n{_fmt_draft(draft)}\n\nRECENT POSTS (last {WINDOW_DAYS} days):\n"
            f"{_fmt_corpus(corpus)}\n\nJudge the new draft.")
    try:
        resp = call_openrouter([{"role": "system", "content": _SYSTEM},
                                {"role": "user", "content": user}], model, api_key)
        data = extract_json(resp["choices"][0]["message"]["content"])
    except Exception as ex:
        eng.log(f"dedup judge failed ({ex}) — passing (fail-open)")
        return _passed(f"judge error: {ex}")
    return _normalize(data)


def revise(draft: dict, verdict: dict) -> tuple[dict, list[str]]:
    """Apply the judge's per-element rewrites to a COPY of the draft. Follow-ups pass untouched.
    Returns (new_draft, changed_elements)."""
    out = dict(draft)
    changed: list[str] = []
    if verdict.get("follow_up"):
        return out, changed
    for p in verdict.get("parts", []):
        el, rev = p.get("element"), (p.get("revised") or "").strip()
        if p.get("verdict") in ("similar", "duplicate") and el in ELEMENTS and rev and out.get(el) != rev:
            out[el] = rev
            changed.append(el)
    return out, changed


def split_headline(text: str) -> tuple[str, str, str]:
    """Map a rewritten hook back into the template's 3 headline lines (line2 = the green-italic
    emphasis). Best-effort, used only on the rare dedup-revise path; templates tolerate an empty
    3rd line. Shared by research.py (image cards) and produce_daily.py (reel overlay)."""
    t = " ".join(str(text).replace("\n", " ").split()).rstrip(".")
    words = t.split()
    n = len(words)
    if n == 0:
        return "", "", ""
    if n <= 2:
        return t, "", ""
    if n <= 4:
        return " ".join(words[:-1]), words[-1], ""
    a, b = n // 3, 2 * n // 3
    return " ".join(words[:a]), " ".join(words[a:b]), " ".join(words[b:])


def is_blocking(verdict: dict) -> bool:
    """True if the draft repeats a recent post and it is NOT a deliberate follow-up."""
    return bool(verdict.get("duplicate")) and not verdict.get("follow_up") and bool(verdict.get("parts"))


def summarize(verdict: dict, changed: list[str]) -> str:
    if verdict.get("follow_up"):
        return f"follow-up to a recent post — passed ({verdict.get('reason', '')})"
    if changed:
        # Normalize (strip/upper) before de-duping so whitespace/case variants from the judge
        # (e.g. "ACME-046" vs "ACME-046 ") can't render as visual duplicates in the card note.
        ids = sorted({(p.get("matched_job") or "").strip().upper()
                      for p in verdict.get("parts", [])} - {""})
        return f"auto-revised {', '.join(changed)} (too close to {', '.join(ids) or 'a recent post'})"
    return f"unique — passed ({verdict.get('reason', '')})" if verdict.get("reason") else "unique — passed"


# ── CLI ─────────────────────────────────────────────────────────────────────--
def _draft_from_job(job_id: str) -> dict:
    s = job_snapshot(job_id)
    return {"job_id": job_id, "pillar": s.get("pillar"), "compound": s.get("compound"),
            "topic": s.get("topic"), "hook": s.get("hook"), "body": s.get("body"),
            "script": s.get("script"), "slides": s.get("slides")}


def main():
    ap = argparse.ArgumentParser(description="Acme content-duplication gate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("corpus", help="Dump the comparison corpus")
    pc.add_argument("--days", type=int, default=WINDOW_DAYS)
    pk = sub.add_parser("check", help="Judge a job's draft vs the corpus (excludes itself)")
    pk.add_argument("job_dir")
    pk.add_argument("--days", type=int, default=WINDOW_DAYS)
    args = ap.parse_args()

    if args.cmd == "corpus":
        for c in recent_corpus(days=args.days):
            print(json.dumps(c, ensure_ascii=False))
        return
    if args.cmd == "check":
        jid = Path(args.job_dir).resolve().name
        draft = _draft_from_job(jid)
        corpus = recent_corpus(days=args.days, exclude_job=jid)
        verdict = check_draft(draft, corpus)
        new_draft, changed = revise(draft, verdict)
        print(json.dumps({"job": jid, "verdict": verdict, "changed": changed,
                          "summary": summarize(verdict, changed)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
