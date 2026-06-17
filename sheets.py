#!/usr/bin/env python3
"""
Google Sheets CLI for ACME agent.
Authenticates via service account in acme-google-credentials.json.

Usage:
  python3 sheets.py tail [N]              — last N rows (default 30) — USE THIS FIRST
  python3 sheets.py read RANGE            — read a BOUNDED range (start+end row required)
  python3 sheets.py write RANGE JSON      — write values (JSON 2D array)
  python3 sheets.py append RANGE JSON     — append rows (bottom)
  python3 sheets.py insert RANGE JSON [ROW] — insert rows at ROW (default 2, top), push others down
  python3 sheets.py clear RANGE           — clear a range
  python3 sheets.py info                  — spreadsheet metadata

Examples:
  python3 sheets.py tail 30              # last 30 rows — default for session startup
  python3 sheets.py tail 5               # last 5 rows — get next ID before append
  python3 sheets.py read "Sheet1!A1:K50"  # bounded range — both row numbers required
  python3 sheets.py write "Sheet1!A2" '[["value1","value2"]]'
  python3 sheets.py append "Sheet1!A:K" '[["new","row","data"]]'
  python3 sheets.py clear "Sheet1!A2:Z"

IMPORTANT: read with no range or unbounded range (e.g. "Sheet1!A2:K") is BLOCKED.
Use tail or specify explicit row numbers on both ends.
"""

import sys
import os
import re
import json
from pathlib import Path

MAX_ROWS_OUTPUT = 100  # hard cap — never return more than this many rows in one read

SCRIPT_DIR = Path(__file__).parent
CREDS_FILE = SCRIPT_DIR / "acme-google-credentials.json"


def get_sheet_id():
    env_file = SCRIPT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("GOOGLE_SHEET_ID="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if sheet_id:
        return sheet_id
    sys.exit("ERROR: GOOGLE_SHEET_ID not found in .env or environment")


def get_client():
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(str(CREDS_FILE), scopes=scopes)
    return gspread.authorize(creds)


def _is_unbounded_range(cell_range):
    """Return True if the range has no end row number (e.g. A2:K or A:K)."""
    # Extract the end part after the colon
    if ":" not in cell_range:
        return False  # single cell — fine
    end_part = cell_range.split(":")[-1]
    # Unbounded if end part is only letters (no digits)
    return bool(re.match(r'^[A-Za-z]+$', end_part))


def cmd_read(sheet_id, range_name=None):
    gc = get_client()
    sh = gc.open_by_key(sheet_id)
    if range_name is None:
        # No range given — auto-fallback to last MAX_ROWS_OUTPUT rows instead of hard error
        sys.stderr.write(f"HINT: 'read' called with no range — returning last {MAX_ROWS_OUTPUT} rows. Use 'tail N' next time.\n")
        cmd_tail(sheet_id, MAX_ROWS_OUTPUT)
        return
    if "!" in range_name:
        ws_name, cell_range = range_name.split("!", 1)
        ws = sh.worksheet(ws_name)
    else:
        ws = sh.sheet1
        cell_range = range_name
    if _is_unbounded_range(cell_range):
        # Unbounded range — cap to MAX_ROWS_OUTPUT instead of hard error
        sys.stderr.write(f"HINT: Range '{range_name}' is unbounded — capping output to {MAX_ROWS_OUTPUT} rows. Add an end row number next time.\n")
        all_vals = ws.get_all_values()
        values = all_vals[:MAX_ROWS_OUTPUT]
    else:
        values = ws.get(cell_range)
        if len(values) > MAX_ROWS_OUTPUT:
            sys.stderr.write(f"HINT: Truncating output to {MAX_ROWS_OUTPUT} rows (got {len(values)}). Use a tighter range.\n")
            values = values[:MAX_ROWS_OUTPUT]
    print(json.dumps(values, ensure_ascii=False, indent=2))


def cmd_tail(sheet_id, n=30):
    """Return the last N rows of Sheet1 (header + last N-1 data rows)."""
    gc = get_client()
    sh = gc.open_by_key(sheet_id)
    ws = sh.sheet1
    total_rows = ws.row_count
    # Find actual last row with data
    all_vals = ws.get_all_values()
    actual_rows = len(all_vals)
    if actual_rows == 0:
        print(json.dumps([]))
        return
    start = max(1, actual_rows - n + 1)
    # Always include row 1 (header) if we're not starting from row 1
    result = []
    if start > 1:
        result = [all_vals[0]]  # header
        result += all_vals[start - 1:]
    else:
        result = all_vals[start - 1:]
    result = result[:MAX_ROWS_OUTPUT]
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_write(sheet_id, range_name, values_json):
    gc = get_client()
    sh = gc.open_by_key(sheet_id)
    values = json.loads(values_json)
    if "!" in range_name:
        ws_name, cell_range = range_name.split("!", 1)
        ws = sh.worksheet(ws_name)
    else:
        ws = sh.sheet1
        cell_range = range_name
    ws.update(cell_range, values)
    print(json.dumps({"status": "ok", "updated": range_name}))


def cmd_append(sheet_id, range_name, values_json):
    gc = get_client()
    sh = gc.open_by_key(sheet_id)
    values = json.loads(values_json)
    if "!" in range_name:
        ws_name, cell_range = range_name.split("!", 1)
        ws = sh.worksheet(ws_name)
    else:
        ws = sh.sheet1
        cell_range = range_name
    ws.append_rows(values)
    print(json.dumps({"status": "ok", "appended_rows": len(values)}))


def cmd_insert(sheet_id, range_name, values_json, row=2):
    """Insert rows at a given position (default row 2 — just under the header),
    pushing all existing rows down. Used for newest-on-top logging."""
    gc = get_client()
    sh = gc.open_by_key(sheet_id)
    values = json.loads(values_json)
    if "!" in range_name:
        ws_name, _ = range_name.split("!", 1)
        ws = sh.worksheet(ws_name)
    else:
        ws = sh.sheet1
    ws.insert_rows(values, row=row)
    print(json.dumps({"status": "ok", "inserted_rows": len(values), "at_row": row}))


def cmd_clear(sheet_id, range_name):
    gc = get_client()
    sh = gc.open_by_key(sheet_id)
    if "!" in range_name:
        ws_name, cell_range = range_name.split("!", 1)
        ws = sh.worksheet(ws_name)
    else:
        ws = sh.sheet1
        cell_range = range_name
    ws.batch_clear([cell_range])
    print(json.dumps({"status": "ok", "cleared": range_name}))


def cmd_info(sheet_id):
    gc = get_client()
    sh = gc.open_by_key(sheet_id)
    info = {
        "title": sh.title,
        "id": sh.id,
        "url": sh.url,
        "sheets": [{"title": ws.title, "rows": ws.row_count, "cols": ws.col_count} for ws in sh.worksheets()],
    }
    print(json.dumps(info, ensure_ascii=False, indent=2))


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    sheet_id = get_sheet_id()
    cmd = args[0].lower()

    if cmd == "tail":
        n = int(args[1]) if len(args) > 1 else 30
        if n > MAX_ROWS_OUTPUT:
            sys.exit(f"ERROR: tail N cannot exceed {MAX_ROWS_OUTPUT} rows.")
        cmd_tail(sheet_id, n)
    elif cmd == "read":
        cmd_read(sheet_id, args[1] if len(args) > 1 else None)
    elif cmd == "write":
        if len(args) < 3:
            sys.exit("Usage: sheets.py write RANGE JSON_ARRAY")
        cmd_write(sheet_id, args[1], args[2])
    elif cmd == "append":
        if len(args) < 3:
            sys.exit("Usage: sheets.py append RANGE JSON_ARRAY")
        cmd_append(sheet_id, args[1], args[2])
    elif cmd == "insert":
        if len(args) < 3:
            sys.exit("Usage: sheets.py insert RANGE JSON_ARRAY [ROW]")
        row = int(args[3]) if len(args) > 3 else 2
        cmd_insert(sheet_id, args[1], args[2], row)
    elif cmd == "clear":
        if len(args) < 2:
            sys.exit("Usage: sheets.py clear RANGE")
        cmd_clear(sheet_id, args[1])
    elif cmd == "info":
        cmd_info(sheet_id)
    else:
        sys.exit(f"Unknown command: {cmd}. Use: read, write, append, insert, clear, info")


if __name__ == "__main__":
    main()
