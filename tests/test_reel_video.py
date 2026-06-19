#!/usr/bin/env python3
"""
test_reel_video.py — F7 RV3 must refuse to spend unless every gate passes: a faceless/
text-free scene, a concept-approved job, headroom under the HARD 2-reels/day cap.

Pure: no network, no higgsfield, no ffmpeg. Exercises the scene guard, prompt construction
(VIDEO block prepend via preflight --print-block, which is a local constant), the gate
checks (monkeypatched engine), and the reel cap (temp budget file). 0 credits.

Run:  python3 tests/test_reel_video.py     # exits 0 = pass, 1 = fail
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine as e
import reel_video as rv

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
    # 1 — scene guard: humans + on-screen text are rejected; clean b-roll passes.
    check("guard rejects a person", bool(rv._BAD_SCENE.search("a man in a lab coat holding a vial")))
    check("guard rejects a face", bool(rv._BAD_SCENE.search("close-up of a researcher's face")))
    check("guard rejects on-screen text", bool(rv._BAD_SCENE.search("text overlay reading PEPTIDES")))
    check("guard passes faceless lab b-roll",
          not rv._BAD_SCENE.search("slow macro dolly across frosted glass vials, soft side light"))

    # 2 — prompt = VIDEO brand block (verbatim, by construction) + the scene.
    scene = "rotating 3D molecular peptide chain, shallow depth of field, clean clinical background"
    prompt = rv.build_prompt(scene)
    check("prompt begins with the verbatim VIDEO brand block",
          prompt.startswith("Acme premium-biotech cinematic system."))
    check("prompt ends with the scene", prompt.rstrip().endswith(scene))

    # build_prompt must REFUSE a scene that implies a human / text.
    raised = False
    try:
        rv.build_prompt("a spokesperson presenting the product")
    except SystemExit:
        raised = True
    check("build_prompt refuses a human/text scene", raised)

    # 3 — gate checks (monkeypatched engine). No concept_qc => G2 blocks.
    e.stop_engaged = lambda: False
    e.compliance_hold = lambda: False
    e.budget_remaining = lambda kind: 2
    e.load_json = lambda p: {}  # no concept_qc.json
    fails = rv.check_gates(Path("/tmp/ACME-X"), {"type": "reel"})
    check("G2 blocks when concept not approved", any("G2" in f for f in fails))

    e.load_json = lambda p: {"passed": True}  # concept approved
    check("all gates pass when concept approved + budget + running",
          rv.check_gates(Path("/tmp/ACME-X"), {"type": "reel"}) == [])

    e.budget_remaining = lambda kind: 0       # cap exhausted
    check("G4 blocks when reel cap exhausted",
          any("G4" in f for f in rv.check_gates(Path("/tmp/ACME-X"), {"type": "reel"})))

    # 4 — the HARD 2-reels/day cap actually enforces (temp budget file).
    import importlib
    importlib.reload(e)                        # restore real functions after monkeypatching
    tmp = Path(tempfile.mkdtemp(prefix="reelcap_"))
    e.ENGINE_DIR = tmp
    e._budget_path = lambda date=None: tmp / "budget.json"
    check("reel cap is 2/day", e._caps()["reel"] == 2)
    check("1st reel spend allowed", e.spend("reel") is True)
    check("2nd reel spend allowed", e.spend("reel") is True)
    check("3rd reel spend REFUSED (cap)", e.spend("reel") is False)

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
