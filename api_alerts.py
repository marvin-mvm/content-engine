#!/usr/bin/env python3
"""
api_alerts.py — turn a tool's quota/credit exhaustion into ONE clear, actionable Telegram
heads-up, so a depleted external API never silently degrades the engine.

Background: on 2026-06-23 SearchAPI hit its monthly cap (HTTP 429). Every discovery call
returned nothing, the topic scorer went blind, and the daily run quietly fell back to
compound rotation — shipping four duplicate-compound posts (ACME-062..065) with no source
links. Nothing told us the API was down. This module fixes the "silent" part.

Each external tool (searchapi, apify, firecrawl, blotato, higgsfield) calls `note(...)`
from its error branch. note():
  • classifies whether the failure is a DEPLETION (quota / credits / payment) vs a
    transient/other error,
  • on depletion, sends ONE custom, per-tool Telegram message,
  • dedups once per UTC day per tool (a daily run that hammers a dead API won't spam the
    group; the next day it re-alerts so it stays on the radar until fixed),
  • returns True iff it was a depletion, so callers can branch (e.g. research stops
    generating blind-rotation duplicates).

Stdlib-only and strictly best-effort: alerting must NEVER raise into a tool's own error
path. Set APIALERTS_DRYRUN=1 to print instead of send (used by tests); ENGINE_ALERTS_OFF=1
to disable entirely.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).parent.resolve()
ENV_FILE = WORKSPACE / ".env"
STATE_FILE = WORKSPACE / "output" / "engine" / "api_alerts.json"

# Canonical tool keys (also accepted: the tool's script stem, e.g. "searchapi.py").
TOOLS = ("searchapi", "apify", "firecrawl", "blotato", "higgsfield")

# Per-tool message: WHAT is down + WHAT to do about it. Plain text (engine alerts send with
# no parse_mode), so no Markdown. Keep each one specific — the whole point is that you know
# exactly which capability died and how to keep moving.
DEPLETION_MESSAGES = {
    "searchapi": (
        "⚠️ SearchAPI is depleted (monthly search quota used up).\n"
        "I can't run trending / Google-Trends / news / YouTube discovery right now — so any "
        "auto-picked topics would just be blind repeats of past posts.\n"
        "👉 Drop any links you want me to build from (an article, or an IG / TikTok / X / "
        "YouTube post) and I'll use those instead, or top up SearchApi.io. "
        "I'm holding back auto-generated topic posts until it's back."
    ),
    "apify": (
        "⚠️ Apify is depleted / rate-limited.\n"
        "I can't scrape social posts (Instagram / TikTok / X / YouTube) — Mode-B clones, "
        "transcripts and outlier mining are down.\n"
        "👉 Paste the post text or links manually, or top up Apify."
    ),
    "firecrawl": (
        "⚠️ Firecrawl is depleted / out of credits.\n"
        "I can't read article or blog pages — pasted article links can't be extracted into a brief.\n"
        "👉 Paste the article text directly, or top up Firecrawl."
    ),
    "blotato": (
        "⚠️ Blotato is depleted / limited.\n"
        "I can't publish or schedule posts — approved content will queue but won't go live.\n"
        "👉 Top up Blotato, or publish manually for now."
    ),
    "higgsfield": (
        "⚠️ Higgsfield credits are depleted.\n"
        "I can't generate images / reels / video — reel and image generation are paused.\n"
        "👉 Top up Higgsfield, or I'll fall back to Blotato for images where possible."
    ),
}
_GENERIC = ("⚠️ {tool} is depleted / out of quota — that capability is down until it's "
            "topped up.")

# Depletion signatures in an error body (lowercased substring match). These are the things
# our APIs actually say when they're out of quota/credits — NOT transient network errors.
_DEPLETION_PHRASES = (
    "used all of", "out of credit", "insufficient credit", "insufficient balance",
    "insufficient funds", "not enough credit", "no credits", "credit limit",
    "credits remaining: 0", "out of quota", "quota exceeded", "quota has been",
    "exceeded your", "usage limit", "limit exceeded", "monthly usage", "monthly limit",
    "rate limit", "too many requests", "payment required", "upgrade your plan",
    "billing", "depleted", "subscription", "plan limit",
)
_DEPLETION_CODES = {402, 429}              # Payment Required / Too Many Requests (quota)
_CODE_IN_TEXT = re.compile(r"\b(402|429)\b")


def _norm(tool: str) -> str:
    """Map 'searchapi.py' / 'SearchAPI' -> canonical 'searchapi'."""
    t = (tool or "").strip().lower()
    if t.endswith(".py"):
        t = t[:-3]
    return t


def classify(code=None, body: str = "") -> bool:
    """True iff this failure looks like quota/credit/payment depletion (vs transient/other).
    Caller passes the HTTP status (best) and/or the raw error body text."""
    try:
        if code is not None and int(code) in _DEPLETION_CODES:
            return True
    except (TypeError, ValueError):
        pass
    blob = (body or "").lower()
    if any(p in blob for p in _DEPLETION_PHRASES):
        return True
    # The tools embed the HTTP code in their ERROR string ("ERROR: SearchAPI 429: ..."),
    # so callers that only have the text (e.g. research.run_tool) still detect it.
    return bool(_CODE_IN_TEXT.search(blob))


# ── env + Telegram send (mirrors engine.alert; kept standalone so the lightweight CLI
#    tools don't have to import the whole engine module) ───────────────────────────────
def _load_env(key: str, default: str = "") -> str:
    val = os.environ.get(key)
    if val:
        return val
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return default


def _tls_verify():
    if (_load_env("ENGINE_INSECURE_SSL") or "").strip() == "1":
        try:
            import urllib3
            urllib3.disable_warnings()
        except ImportError:
            pass
        return False
    try:
        import certifi
        return certifi.where()
    except ImportError:
        return True


def _send(text: str) -> None:
    """Best-effort Telegram send to the engine group. Never raises."""
    if (_load_env("ENGINE_ALERTS_OFF") or "").strip() == "1":
        return
    if (os.environ.get("APIALERTS_DRYRUN") or "").strip() == "1":
        print(f"[api_alerts DRYRUN] would send:\n{text}", file=sys.stderr)
        return
    try:
        token = _load_env("ENGINE_TELEGRAM_BOT_TOKEN")
        chat = _load_env("ENGINE_TELEGRAM_CHAT_ID")
        if not token or not chat:
            return
        import requests
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": text[:3500]},
                      timeout=15, verify=_tls_verify())
    except Exception:
        pass


# ── once-per-day-per-tool dedup ───────────────────────────────────────────────────────
def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    except Exception:
        pass


def already_alerted_today(tool: str) -> bool:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _load_state().get(_norm(tool)) == today


def _mark(tool: str) -> None:
    state = _load_state()
    state[_norm(tool)] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _save_state(state)


def note(tool: str, *, code=None, body: str = "", detail: str = "") -> bool:
    """Entry point for tools. If (code, body) is a depletion, send the tool's custom Telegram
    heads-up (once per UTC day) and return True; otherwise return False. Never raises."""
    try:
        if not classify(code=code, body=body):
            return False
        key = _norm(tool)
        if already_alerted_today(key):
            return True                       # depletion, but we've already pinged today
        msg = DEPLETION_MESSAGES.get(key, _GENERIC.format(tool=key or "An API"))
        if detail:
            msg += f"\n\n(detail: {detail[:200].strip()})"
        _send(msg)
        _mark(key)
        return True
    except Exception:
        return False


# CLI: manual test / one-off alert.  `python3 api_alerts.py test searchapi`
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="api_alerts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("test", help="classify + (dry-run) preview a tool's depletion message")
    t.add_argument("tool", choices=list(TOOLS))
    t.add_argument("--code", type=int, default=429)
    t.add_argument("--body", default="You have used all of the searches for the month.")
    a = ap.parse_args()
    if a.cmd == "test":
        os.environ.setdefault("APIALERTS_DRYRUN", "1")
        hit = note(a.tool, code=a.code, body=a.body)
        print(f"classified_as_depletion={hit}")
