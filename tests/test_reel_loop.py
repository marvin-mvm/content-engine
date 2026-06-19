#!/usr/bin/env python3
"""
test_reel_loop.py — F7 LOOP: produce_daily.handle_reel must put GATE 1 (concept) BEFORE the
RV3 credit spend, and must only let RV3 actually spend (--go) when BOTH --generate AND
engine.reels_live() are set. Concept-approved-but-supervised reels dry-run RV3 (0 credits).

Pure: stubs the subprocess wrapper + engine status I/O + reels_live (no tools run, no
network, no credits). Run:  python3 tests/test_reel_loop.py     # exits 0 = pass, 1 = fail
"""

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine as e
import produce_daily as pd

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if cond:
        PASS += 1
    else:
        FAIL += 1


def tool(cmd):
    """The script basename a recorded _sub call invoked (cmd = [py, '/path/foo.py', ...])."""
    return Path(cmd[1]).name if len(cmd) > 1 else cmd[0]


def setup(tmpname, brief, *, concept=False, status=None):
    job = Path(tempfile.mkdtemp(prefix=tmpname)) / "ACME-LTST"
    job.mkdir(parents=True)
    (job / "brief.json").write_text(json.dumps(brief))
    if concept:
        (job / "concept_qc.json").write_text(json.dumps({"passed": True}))
    state = {"ACME-LTST": {"status": status}} if status else {}
    e.read_status = lambda jid: state.get(jid)
    e.write_status = lambda jid, s, **kw: state.__setitem__(jid, {"status": s, **kw})
    pd.build_captions = lambda jd, force=False: {}
    return job


def record():
    calls = []
    pd._sub = lambda cmd: (calls.append(cmd), SimpleNamespace(returncode=0))[1]
    return calls


REEL = {"job_id": "ACME-LTST", "type": "reel", "brand": "labs", "pillar": "science",
        "persona": "P1", "topic": "x"}


def main():
    # 1 — PHASE A (no script): RV2 then push-concept; RV3 (reel_video) NEVER touched.
    job = setup("loopA_", REEL)
    calls = record()
    pd.handle_reel(job, generate=True, dry_run_push=True)  # generate=True must NOT matter pre-concept
    tools = [tool(c) for c in calls]
    check("Phase A runs script.py (RV2)", "script.py" in tools)
    check("Phase A pushes the CONCEPT card", any("push-concept" in c for c in calls))
    check("Phase A NEVER calls reel_video (no spend before GATE 1)", "reel_video.py" not in tools)

    # 2 — PHASE B, supervised (reels_live OFF) + generate=True: RV3 DRY-RUN (no --go), parks.
    job = setup("loopB1_", {**REEL, "script": "s"}, concept=True, status="concept_approved")
    calls = record()
    e.reels_live = lambda: False
    pd.handle_reel(job, generate=True, dry_run_push=True)
    rv3 = [c for c in calls if tool(c) == "reel_video.py"]
    check("Phase B calls reel_video (RV3)", len(rv3) == 1)
    check("RV3 does NOT spend when REELS_LIVE is off (no --go)", "--go" not in rv3[0])
    check("RV4 (reel_captions) not reached without a b-roll", "reel_captions.py" not in [tool(c) for c in calls])

    # 3 — PHASE B, REELS_LIVE on + generate=True: RV3 may spend (--go present).
    job = setup("loopB2_", {**REEL, "script": "s"}, concept=True, status="concept_approved")
    calls = record()
    e.reels_live = lambda: True
    pd.handle_reel(job, generate=True, dry_run_push=True)
    rv3 = [c for c in calls if tool(c) == "reel_video.py"][0]
    check("RV3 spends (--go) only with REELS_LIVE on + --generate", "--go" in rv3)

    # 4 — PHASE B, REELS_LIVE on but generate=False: still NO spend (both required).
    job = setup("loopB3_", {**REEL, "script": "s"}, concept=True, status="concept_approved")
    calls = record()
    e.reels_live = lambda: True
    pd.handle_reel(job, generate=False, dry_run_push=True)
    rv3 = [c for c in calls if tool(c) == "reel_video.py"][0]
    check("--generate is also required to spend (no --go without it)", "--go" not in rv3)

    # 5 — a reel awaiting concept approval is left untouched (no re-push, no spend).
    job = setup("loopW_", {**REEL, "script": "s"}, status="awaiting_concept")
    calls = record()
    out = pd.handle_reel(job, generate=True, dry_run_push=True)
    check("awaiting_concept reel is not disturbed", out == "awaiting_concept" and calls == [])

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
