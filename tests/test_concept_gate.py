#!/usr/bin/env python3
"""
test_concept_gate.py — F7 GATE 1 (concept gate) must route A/R/E to the PRE-CREDIT concept
decision when a reel is awaiting_concept, write the concept_qc marker on APPROVE, spend NO
credit and move NO trust, and leave the final gate (qc.json + trust) untouched for everyone else.

Pure: monkeypatches engine status I/O + telegram.send_text (no network, no trust mutation,
0 credits). Run:  python3 tests/test_concept_gate.py     # exits 0 = pass, 1 = fail
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine as e
import telegram as tg
import approvals as ap

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
    tmp = Path(tempfile.mkdtemp(prefix="gate1_"))
    job_id = "ACME-TST"
    job = tmp / job_id
    job.mkdir(parents=True)
    (job / "brief.json").write_text(json.dumps({"job_id": job_id, "type": "reel", "brand": "labs",
                                                "pillar": "science", "persona": "P1", "topic": "x",
                                                "script": "A clean spoken script. For research use only."}))

    # In-memory status store; stub trust + telegram so nothing real is touched.
    status = {}
    trust_calls = []
    e.JOBS_DIR = tmp
    e.read_status = lambda jid: status.get(jid)
    e.write_status = lambda jid, s, **kw: status.__setitem__(jid, {"status": s, **kw})
    e.apply_trust_event = lambda *a, **k: trust_calls.append(a) or {"score": 999}
    e.record_decision = lambda *a, **k: None      # don't touch the real decision ledger in tests
    # Reels now auto-slot on GATE-2 approval (2026-06-23); stub it so the test never writes the
    # real manifest and stays focused on the gate's qc.json/status/trust behavior.
    e.ensure_slotted_in_manifest = lambda *a, **k: "08:00"
    tg.send_text = lambda text, dry_run: True

    # 1 — concept APPROVE: concept_qc written, NO final qc, NO trust.
    e.write_status(job_id, "awaiting_concept")
    ap.apply_command("APPROVE", job_id, "go", who="test", reply=False)
    check("concept APPROVE -> status concept_approved", status[job_id]["status"] == "concept_approved")
    check("concept_qc.json written (passed)", json.loads((job / "concept_qc.json").read_text())["passed"])
    check("final qc.json NOT written at concept gate", not (job / "qc.json").exists())
    check("concept APPROVE is trust-neutral", trust_calls == [])

    # 2 — concept REJECT: blocked, marker removed, still no trust.
    e.write_status(job_id, "awaiting_concept")
    ap.apply_command("REJECT", job_id, "wrong angle", who="test", reply=False)
    check("concept REJECT -> status concept_rejected", status[job_id]["status"] == "concept_rejected")
    check("concept_qc.json removed on reject", not (job / "concept_qc.json").exists())
    check("concept REJECT is trust-neutral (no credit was spent)", trust_calls == [])

    # 3 — GATE-2 guard (the double-APPROVE hole, Marvin 2026-06-23): a reel APPROVE is REFUSED
    # unless the reel is generated (a render exists) AND at status=pushed. A 2nd APPROVE while
    # concept_approved must NOT write the publish sign-off on an un-generated reel.
    (job / "qc.json").unlink(missing_ok=True)
    e.write_status(job_id, "concept_approved")
    ap.apply_command("APPROVE", job_id, "", who="test", reply=False)
    check("reel APPROVE w/o render is REFUSED (no qc.json)", not (job / "qc.json").exists())
    check("refused APPROVE leaves status unchanged", status[job_id]["status"] == "concept_approved")
    check("refused APPROVE is trust-neutral", trust_calls == [])

    # 4 — final gate proper: a GENERATED reel (render present) at status=pushed APPROVES normally.
    (job / f"{job_id}-final.mp4").write_text("render")
    e.write_status(job_id, "pushed")
    ap.apply_command("APPROVE", job_id, "", who="test", reply=False)
    check("final APPROVE -> status approved", status[job_id]["status"] == "approved")
    check("final APPROVE writes qc.json", json.loads((job / "qc.json").read_text())["passed"])
    check("final APPROVE DOES move trust", len(trust_calls) == 1)

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
