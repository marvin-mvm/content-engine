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

    # 3 — gate checks (monkeypatched engine). Budget + wallet are in REAL Higgsfield credits.
    e.stop_engaged = lambda: False
    e.compliance_hold = lambda: False
    e.budget_remaining = lambda kind: 1000
    rv.wallet_balance = lambda: 10 ** 9        # never hit the live API in tests
    e.load_json = lambda p: {}  # no concept_qc.json
    fails = rv.check_gates(Path("/tmp/ACME-X"), {"type": "reel"})
    check("G2 blocks when concept not approved", any("G2" in f for f in fails))

    e.load_json = lambda p: {"passed": True}  # concept approved
    e._caps = lambda: {"reel": 135}           # real-credit cap (for the G4 message)
    check("all gates pass when concept approved + budget + wallet + running",
          rv.check_gates(Path("/tmp/ACME-X"), {"type": "reel"}, need_credits=135) == [])

    # G4 = the engine's daily REAL-credit ceiling.
    e.budget_remaining = lambda kind: 90       # only 90 real credits left today
    check("G4 blocks when daily budget < this reel's real cost",
          any("G4" in f for f in rv.check_gates(Path("/tmp/ACME-X"), {"type": "reel"}, need_credits=135)))
    check("G4 passes when daily budget covers the real cost",
          not any("G4" in f for f in rv.check_gates(Path("/tmp/ACME-X"), {"type": "reel"}, need_credits=90)))

    # G6 = the LIVE Higgsfield wallet (the actual money), independent of the engine counter.
    e.budget_remaining = lambda kind: 1000
    rv.wallet_balance = lambda: 50             # wallet nearly empty
    check("G6 blocks when the live wallet < this reel's cost",
          any("G6" in f for f in rv.check_gates(Path("/tmp/ACME-X"), {"type": "reel"}, need_credits=135)))
    rv.wallet_balance = lambda: None           # unreadable wallet must NOT block (cap still guards)
    check("G6 does not block when the wallet is unreadable",
          not any("G6" in f for f in rv.check_gates(Path("/tmp/ACME-X"), {"type": "reel"}, need_credits=135)))
    rv.wallet_balance = lambda: 10 ** 9

    # 4 — the HARD 135-real-credits/day reel cap actually enforces (temp budget file).
    import importlib
    importlib.reload(e)                        # restore real functions after monkeypatching
    tmp = Path(tempfile.mkdtemp(prefix="reelcap_"))
    e.ENGINE_DIR = tmp
    e._budget_path = lambda date=None: tmp / "budget.json"
    check("reel cap is 135 real credits/day", e._caps()["reel"] == 135)
    check("a 3-clip reel (3×45=135) spend allowed", e.spend("reel", 3 * rv.CREDITS_PER_CLIP) is True)
    check("a 4th clip (+45 over the cap) REFUSED", e.spend("reel", rv.CREDITS_PER_CLIP) is False)

    # 5 — the curated deck always yields N DISTINCT premium scenes (the no-LLM variety net).
    deck = rv.pick_deck("science", 3)
    check("pick_deck returns N scenes", len(deck) == 3)
    check("pick_deck scenes are distinct", len(set(deck)) == 3)
    check("every curated deck scene clears the FULL preflight mirror (no face/text/ad)",
          all(rv._scene_rejected(s) is None
              for scenes in rv._SCENE_DECK.values() for s in scenes))
    check("pick_deck respects exclude", rv.pick_deck("science", 2, exclude=deck)[0] not in deck)

    # the scene filter mirrors preflight: a stray 'model' / on-screen 'text' is rejected so it
    # can never block the multi-clip batch at generation time.
    check("scene filter rejects a 'model' (preflight AD_PERSON)",
          rv._scene_rejected("macro orbit around a molecular model on a stand") is not None)
    check("scene filter rejects requested on-screen text (preflight TEXT_REQUEST)",
          rv._scene_rejected("a vial with a label that reads PEPTIDE") is not None)
    check("scene filter passes a clean premium b-roll scene",
          rv._scene_rejected("slow macro dolly across frosted vials, soft cream side light") is None)

    # tolerant scene-array parse (LLM may fence or wrap the JSON array).
    check("parse a bare JSON array", rv._parse_scene_array('["a","b"]') == ["a", "b"])
    check("parse a fenced JSON array", rv._parse_scene_array('```json\n["a","b"]\n```') == ["a", "b"])
    check("parse an array embedded in prose", rv._parse_scene_array('Here: ["a","b"] done') == ["a", "b"])
    check("non-array parses to empty", rv._parse_scene_array('not json') == [])

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
