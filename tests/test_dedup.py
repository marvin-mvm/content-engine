#!/usr/bin/env python3
"""
test_dedup.py — the content-duplication gate (dedup.py). Guards:
  - recent_corpus() gathers PRODUCED-in-window jobs + APPROVED decisions, excludes self.
  - check_draft() is fail-open (no key/corpus/judge error → pass) and honours the judge.
  - revise() swaps ONLY the flagged element; follow-ups pass untouched; RED rewrites are dropped.

Pure: a temp JOBS_DIR + a stubbed judge (no network, no Higgsfield). 0 credits.
Run:  python3 tests/test_dedup.py     # exits 0 = pass, 1 = fail
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine as eng
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


def _mkjob(jobs, jid, *, pillar, compound, hook, produced_at):
    d = jobs / jid
    d.mkdir(parents=True, exist_ok=True)
    (d / "brief.json").write_text(json.dumps({
        "job_id": jid, "type": "image", "pillar": pillar, "compound": compound,
        "topic": f"{compound} — research-backed stack protocol",
        "image": {"set": {"HOOK_LINE_1": hook, "BODY": "research body"}},
    }))
    (d / "status.json").write_text(json.dumps({"status": "produced", "produced_at": produced_at}))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        jobs = Path(tmp) / "jobs"
        jobs.mkdir()
        _mkjob(jobs, "ACME-040", pillar="founder", compound="CJC-1295",
               hook="Why most people get CJC-1295 wrong", produced_at=eng.now_iso())
        # An OLD job outside the 7-day window must NOT be in the corpus.
        _mkjob(jobs, "ACME-001", pillar="founder", compound="BPC-157",
               hook="old hook", produced_at="2026-01-01T00:00:00Z")
        orig = eng.JOBS_DIR
        eng.JOBS_DIR = jobs
        try:
            corpus = dedup.recent_corpus(days=7, exclude_job="ACME-045")
            ids = {c["job_id"] for c in corpus}
            check("recent job is in the corpus", "ACME-040" in ids)
            check("out-of-window job is excluded", "ACME-001" not in ids)

            # Fail-open: a draft + empty corpus → pass (never blocks produce).
            v_empty = dedup.check_draft({"job_id": "ACME-045", "hook": "x"}, corpus=[])
            check("empty corpus → pass (fail-open)", not dedup.is_blocking(v_empty))

            # Stubbed judge: flag the hook as a duplicate of ACME-040 with a clean rewrite.
            draft = {"job_id": "ACME-045", "pillar": "founder", "compound": "CJC-1295",
                     "hook": "Why most people get CJC-1295 wrong", "body": "research body"}
            orig_judge = dedup.call_openrouter
            dedup.call_openrouter = lambda messages, model, api_key: {"choices": [{"message": {"content": json.dumps({
                "duplicate": True, "follow_up": False, "reason": "same founder hook as ACME-040",
                "parts": [{"element": "hook", "verdict": "duplicate", "matched_job": "ACME-040",
                           "revised": "The CJC-1295 mistake hiding in plain sight"}]})}}]}
            dedup.load_api_key = lambda: "test-key"
            verdict = dedup.check_draft(draft, corpus=corpus)
            new_draft, changed = dedup.revise(draft, verdict)
            check("duplicate is blocking", dedup.is_blocking(verdict))
            check("only the hook element changed", changed == ["hook"])
            check("hook was rewritten", new_draft["hook"] == "The CJC-1295 mistake hiding in plain sight")
            check("body left untouched", new_draft["body"] == "research body")

            # Follow-up → pass untouched even though the judge returned parts.
            dedup.call_openrouter = lambda messages, model, api_key: {"choices": [{"message": {"content": json.dumps({
                "duplicate": False, "follow_up": True, "reason": "part 2 of the CJC-1295 series",
                "parts": [{"element": "hook", "verdict": "similar", "matched_job": "ACME-040",
                           "revised": "ignored because follow_up"}]})}}]}
            v_follow = dedup.check_draft(draft, corpus=corpus)
            nd, ch = dedup.revise(draft, v_follow)
            check("follow-up is not blocking", not dedup.is_blocking(v_follow))
            check("follow-up leaves the draft untouched", ch == [] and nd["hook"] == draft["hook"])

            # A RED rewrite is dropped (original kept), and is_blocking sees no usable revision.
            dedup.call_openrouter = lambda messages, model, api_key: {"choices": [{"message": {"content": json.dumps({
                "duplicate": True, "follow_up": False, "reason": "dup",
                "parts": [{"element": "hook", "verdict": "duplicate", "matched_job": "ACME-040",
                           "revised": "This peptide will cure your fatigue"}]})}}]}
            v_red = dedup.check_draft(draft, corpus=corpus)
            nd2, ch2 = dedup.revise(draft, v_red)
            check("RED rewrite dropped (revised emptied)", v_red["parts"][0]["revised"] == "")
            check("RED rewrite does not change the draft", ch2 == [] and nd2["hook"] == draft["hook"])

            dedup.call_openrouter = orig_judge
        finally:
            eng.JOBS_DIR = orig

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
