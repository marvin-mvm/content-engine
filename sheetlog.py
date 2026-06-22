#!/usr/bin/env python3
"""
sheetlog.py — RETIRED at migration cutover (Marvin 2026-06-21).

The Google-Sheets "Content Matrix" was the OpenClaw-era log. The migrated engine's
system-of-record is the JOB FOLDER (brief.json / status.json / captions.json), the daily
MANIFEST, and the append-only decision ledger (output/engine/decisions.jsonl) — with Supabase
as the relational store once provisioned. NOTHING writes to Google Sheets anymore.

`log_asset` is kept as a NO-OP so existing callers (produce.py) keep importing it without change;
it simply does nothing and returns None. The old gspread/`acme-sheets` write path is gone.
See acme-token-cost-fix: Sheets-as-DB also caused a real cost problem (unbounded reads).
"""

import argparse


def log_asset(media: str = "", topic: str = "", prompt: str = "", stage: str = "Production",
              status: str = "Generated", remarks: str = "") -> None:
    """No-op (Sheets retired). Kept for import compatibility; writes nothing, returns None."""
    return None


def main():
    # Standalone invocation is also a no-op now — accept the old flags, do nothing.
    ap = argparse.ArgumentParser(description="RETIRED — Sheets logging removed at cutover (no-op)")
    ap.add_argument("--media", default="")
    ap.add_argument("--topic", default="")
    ap.add_argument("--prompt", default="")
    ap.add_argument("--stage", default="Production")
    ap.add_argument("--status", default="Generated")
    ap.add_argument("--remarks", default="")
    ap.parse_args()
    print("sheetlog.py is retired (cutover 2026-06-21) — no Sheets write performed.")


if __name__ == "__main__":
    main()
