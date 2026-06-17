---
name: acme-sheets
description: "Read/write the Acme Content Matrix sheet. Sheet ID and auth pre-wired — never ask for URL or credentials."
metadata:
  {
    "openclaw":
      {
        "emoji": "📊",
        "requires": { "bins": ["acme-sheets"] }
      }
  }
---

# acme-sheets

```bash
acme-sheets info                              # tab list, row count
acme-sheets tail N                            # last N rows (use N=5 for next ID)
acme-sheets read "Sheet1!A1:L50"              # bounded range only
acme-sheets write "Sheet1!J5" '[["Published"]]'  # 2D JSON array
acme-sheets append "Sheet1!A:L" '[[...12 cols...]]'   # adds to BOTTOM
acme-sheets insert "Sheet1!A:L" '[[...12 cols...]]'   # inserts at row 2 (TOP), pushes others down
acme-sheets clear "Sheet1!D2:D"
```

## Schema — 12 cols A–L

| Col | Header | Notes |
|-----|--------|-------|
| A | ID | `ACME-NNN` |
| B | Date Created | `YYYY-MM-DD` |
| C | Stage | `Ideation` \| `Draft` \| `Production` \| `Scheduled` \| `Published` \| `Review` |
| D | Topic/Link | Human-readable topic or URL |
| E | Draft Copy | Caption draft (usually blank on first log) |
| **F** | **Prompt** | **Generation prompt used (Higgsfield/DTC/copy.py)** |
| G | Media Link | Local path or CDN URL of the asset |
| H | My Remarks | Free-text notes |
| I | Pass | `""` \| `Approved` \| `Rejected` |
| J | Status | `Pending` \| `Generated` \| `Scheduled` \| `Published` |
| K | 7-Day Views | Analytics — blank on first log |
| L | 7-Day Comments | Analytics — blank on first log |

## Append — all 12 cols required, unknown = `""`

```bash
acme-sheets append "Sheet1!A:L" \
  '[["ACME-042","2026-06-01","Production","Semaglutide GLP-1","","the prompt used","output/x.png","Higgsfield bg","","Generated","",""]]'
```

⚠️ **Col F (6th value) = the generation Prompt — NEVER leave it `""` for a generated image/video.** This is a recurring failure. If you generated the asset, the prompt that made it goes in F. For a Higgsfield job, get it via `higgsfield generate get <job_id>` → `params.prompt`. Prefer `produce.py --prompt "..."` or `sheetlog.py --prompt "..."` which place it in F automatically.

⚠️ **Logging is NEWEST-ON-TOP.** New asset rows go at **row 2** (just under the header) via `insert`, not appended at the bottom. `sheetlog.py` / `produce.py` already do this. If logging a row by hand, use `insert "Sheet1!A:L"` (not `append`) so the latest is always the top data row and the oldest stays at the bottom.

## Write individual cells

```bash
acme-sheets write "Sheet1!I5" '[["Approved"]]'    # Pass (col I)
acme-sheets write "Sheet1!J5" '[["Published"]]'   # Status (col J)
acme-sheets write "Sheet1!H5" '[["Remarks text"]]' # My Remarks (col H)
acme-sheets write "Sheet1!G5" '[["https://..."]]'  # Media Link (col G)
acme-sheets write "Sheet1!F5" '[["prompt text"]]'  # Prompt (col F)
acme-sheets write "Sheet1!E5" '[["caption draft"]]' # Draft Copy (col E)
```

## Rules

- Get next ID: `tail 5`, never a full read.
- Appends require exactly **12 cols** in A–L order.
- Append range is `Sheet1!A:L` — using `A:K` will put data in the wrong columns.
- Prefer `tail` over `read`. Unbounded reads cap at 100 rows.
