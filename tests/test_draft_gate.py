#!/usr/bin/env python3
"""
test_draft_gate.py — research.py's draft+dedup glue (the image-card side of the gate). Guards:
  - dedup_gate ALWAYS writes draft.md (the "text drafts" stage), gate on or off.
  - a flagged hook is mapped back into HOOK_LINE_1/2_ITALIC/3; a flagged body → caption;
    nothing else in the copy is touched (surgical — "revise the part, not the whole draft").
  - a follow-up verdict leaves the copy untouched.

Pure: stubs dedup.check_draft (no network, no Higgsfield). 0 credits.
Run:  python3 tests/test_draft_gate.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import research as r
import dedup

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if cond:
        PASS += 1
    else:
        FAIL += 1


def main():
    base_cp = lambda: {"EYEBROW": "TIRZEPATIDE", "HOOK_LINE_1": "Why most people",
                       "HOOK_LINE_2_ITALIC": "get this", "HOOK_LINE_3": "wrong",
                       "SUBTITLE_TEXT": "keep me", "CTA_LABEL": "VIEW COA",
                       "caption": "Original caption body.", "hashtags": ["#x"]}

    with tempfile.TemporaryDirectory() as tmp:
        job = Path(tmp)
        orig_check = dedup.check_draft

        # 1. Duplicate hook + body → surgical swap; untouched fields preserved; draft.md written.
        dedup.check_draft = lambda draft, corpus=None, **kw: {
            "duplicate": True, "follow_up": False, "reason": "dup of ACME-040",
            "parts": [
                {"element": "hook", "verdict": "duplicate", "matched_job": "ACME-040",
                 "revised": "The half life difference nobody checks first"},
                {"element": "body", "verdict": "duplicate", "matched_job": "ACME-040",
                 "revised": "A fresh, distinct caption."}]}
        cp = base_cp()
        brief = {}
        cp = r.dedup_gate(job, "ACME-099", cp, brief, topic="Tirzepatide", pillar="founder",
                          persona="P1", compound="Tirzepatide", brand="labs", want_carousel=False)
        check("caption replaced surgically", cp["caption"] == "A fresh, distinct caption.")
        check("hook mapped into the 3 headline lines",
              cp["HOOK_LINE_1"] and cp["HOOK_LINE_2_ITALIC"] and cp["HOOK_LINE_3"])
        check("hook actually changed", cp["HOOK_LINE_1"] != "Why most people")
        check("unrelated tokens untouched (SUBTITLE_TEXT, CTA_LABEL)",
              cp["SUBTITLE_TEXT"] == "keep me" and cp["CTA_LABEL"] == "VIEW COA")
        check("dedup_note recorded on the brief", "dedup_note" in brief)
        check("draft.md written", (job / "draft.md").exists())
        check("draft.md shows the duplication gate section",
              "Duplication gate" in (job / "draft.md").read_text())

        # 2. Follow-up → copy untouched even though parts are returned.
        dedup.check_draft = lambda draft, corpus=None, **kw: {
            "duplicate": False, "follow_up": True, "reason": "part 2",
            "parts": [{"element": "hook", "verdict": "similar", "matched_job": "ACME-040",
                       "revised": "should be ignored"}]}
        cp2 = base_cp()
        brief2 = {}
        cp2 = r.dedup_gate(job, "ACME-100", cp2, brief2, topic="Tirzepatide", pillar="science",
                           persona="P1", compound="Tirzepatide", brand="labs", want_carousel=False)
        check("follow-up leaves the hook untouched", cp2["HOOK_LINE_1"] == "Why most people")
        check("follow-up records no dedup_note", "dedup_note" not in brief2)

        # 3. Gate disabled (ENGINE_DEDUP=0) still writes draft.md, never calls the judge.
        import os
        os.environ["ENGINE_DEDUP"] = "0"
        called = {"n": 0}
        dedup.check_draft = lambda *a, **k: called.__setitem__("n", called["n"] + 1) or {}
        cp3 = base_cp()
        r.dedup_gate(job, "ACME-101", cp3, {}, topic="T", pillar="proof", persona="P3",
                     compound="Tirzepatide", brand="labs", want_carousel=False)
        check("gate off → judge not called", called["n"] == 0)
        check("gate off → draft.md still written", (job / "draft.md").exists())
        os.environ.pop("ENGINE_DEDUP", None)

        dedup.check_draft = orig_check

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
