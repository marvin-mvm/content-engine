#!/usr/bin/env python3
"""
sheetlog.py — log a Content Matrix row for a generated asset (newest on top).

Used by produce.py to auto-log every image/video on creation. Also runnable
standalone. Schema (12 cols, A–L):
  ID | Date Created | Stage | Topic/Link | Draft Copy | Prompt | Media Link | My Remarks | Pass | Status | 7-Day Views | 7-Day Comments

Next ID is derived from the current sheet tail (ACME-NNN, max + 1). Uses the
`acme-sheets` CLI so it shares the same credentials/spreadsheet wiring.

Usage (standalone):
  python3 sheetlog.py --media output/x.png --topic "Semaglutide mechanism" \
      [--prompt "brand prompt used"] [--stage Production] [--status Generated] [--remarks "..."]

Import:
  from sheetlog import log_asset
  log_asset(media="output/x.png", topic="...", prompt="...", stage="Production", status="Generated")
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date

SHEETS = "acme-sheets"
INSERT_RANGE = "Sheet1!A:L"
ID_RE = re.compile(r"ACME-(\d+)")


def _next_id() -> str:
    """Return the next ACME-NNN id = (max existing id) + 1.

    Logging is newest-on-top (rows inserted at row 2), so the highest id normally
    sits near the top — but we scan all of column A to stay correct regardless of
    ordering (e.g. legacy append-order rows still at the bottom). Column A only,
    bounded read, so it stays cheap.
    """
    try:
        out = subprocess.run([SHEETS, "read", "Sheet1!A1:A100"],
                             capture_output=True, text=True, timeout=30)
        rows = json.loads(out.stdout)
    except Exception as e:
        print(f"[sheetlog] WARNING: could not read column A for next id: {e}", file=sys.stderr)
        return "ACME-000"
    max_n = 0
    for row in rows if isinstance(rows, list) else []:
        if row and isinstance(row, list):
            m = ID_RE.match(str(row[0]))
            if m:
                max_n = max(max_n, int(m.group(1)))
    return f"ACME-{max_n + 1:03d}"


def log_asset(media: str, topic: str = "", prompt: str = "", stage: str = "Production",
              status: str = "Generated", remarks: str = "") -> str | None:
    """Insert one Content Matrix row at the top (row 2). Returns the new ID, or None on failure.

    Failure is non-fatal: logging must never break asset generation.
    """
    new_id = _next_id()
    row = [
        new_id,                  # A ID
        date.today().isoformat(),# B Date Created
        stage,                   # C Stage
        topic,                   # D Topic/Link
        "",                      # E Draft Copy
        prompt,                  # F Prompt
        media,                   # G Media Link
        remarks,                 # H My Remarks
        "",                      # I Pass
        status,                  # J Status
        "",                      # K 7-Day Views
        "",                      # L 7-Day Comments
    ]
    try:
        # Insert at row 2 (top, under the header) so newest is always on top.
        result = subprocess.run(
            [SHEETS, "insert", INSERT_RANGE, json.dumps([row]), "2"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print(f"[sheetlog] WARNING: insert failed: {result.stderr.strip() or result.stdout.strip()}",
                  file=sys.stderr)
            return None
    except Exception as e:
        print(f"[sheetlog] WARNING: insert error: {e}", file=sys.stderr)
        return None
    print(f"[sheetlog] logged {new_id} → {media}", file=sys.stderr)
    return new_id


def main():
    ap = argparse.ArgumentParser(description="Append a Content Matrix row for a generated asset")
    ap.add_argument("--media", required=True, help="Path or URL of the generated asset")
    ap.add_argument("--topic", default="", help="Topic / subject (col D)")
    ap.add_argument("--prompt", default="", help="Generation prompt used (col F)")
    ap.add_argument("--stage", default="Production")
    ap.add_argument("--status", default="Generated")
    ap.add_argument("--remarks", default="", help="My Remarks (col H)")
    args = ap.parse_args()
    new_id = log_asset(args.media, args.topic, args.prompt, args.stage, args.status, args.remarks)
    print(new_id or "")


if __name__ == "__main__":
    main()
