#!/usr/bin/env python3
"""
test_cadence.py — content cadence policy (Marvin 2026-06-19):
  • VIDEO runs on ALTERNATING calendar days only (engine.is_video_day) — never two in a row,
    and the alternation must hold ACROSS week boundaries (the weekday-parity bug it replaces
    would double up Sun→Mon).
  • On a video day exactly ONE pillar carries the reel, alternating trending<->science
    (research.reel_pillar_today); non-video days yield no reel.
  • Image GENERATION source rotates ~4:1 Higgsfield:Blotato (engine.image_source) on a TRUE
    persisted rolling counter, not random.

Pure: no network, no credits. image_source is exercised against a temp engine_state.json so the
real one is untouched. Run:  python3 tests/test_cadence.py     # exits 0 = pass, 1 = fail
"""

import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine as e
import research as r

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
    anchor = e._video_anchor()

    # 1 — the anchor is a video day; the very next day is not (alternation).
    check("anchor date is a video day", e.is_video_day(anchor))
    check("day after the anchor is NOT a video day", not e.is_video_day(anchor + timedelta(days=1)))

    # 2 — over a 28-day span: exactly every other day, and NEVER two video days in a row
    #     (this is the across-week-boundary property weekday-parity lacks).
    span = [anchor + timedelta(days=i) for i in range(28)]
    flags = [e.is_video_day(d) for d in span]
    check("exactly half the days are video days", sum(flags) == 14)
    check("never two video days in a row (holds across weeks)",
          not any(flags[i] and flags[i + 1] for i in range(len(flags) - 1)))
    check("video days are strictly alternating", all(flags[i] != flags[i + 1] for i in range(len(flags) - 1)))

    # 3 — at most ONE reel pillar per day; None on non-video days; alternates trending<->science.
    pillars_on_video_days = [r.reel_pillar_today(d) for d in span if e.is_video_day(d)]
    check("non-video days have no reel pillar",
          all(r.reel_pillar_today(d) is None for d in span if not e.is_video_day(d)))
    check("every video day yields exactly one reel pillar",
          all(p in r.REEL_PILLARS for p in pillars_on_video_days))
    check("reel pillar alternates trending<->science across video days",
          all(pillars_on_video_days[i] != pillars_on_video_days[i + 1]
              for i in range(len(pillars_on_video_days) - 1)))

    # 4 — slot_wants_reel agrees with reel_pillar_today (the F7 trigger).
    vd = anchor                      # a video day
    nvd = anchor + timedelta(days=1)  # not a video day
    check("slot_wants_reel true for the day's reel pillar on a video day",
          r.slot_wants_reel(r.reel_pillar_today(vd), d=vd))
    check("slot_wants_reel false for the OTHER pillar on a video day",
          not r.slot_wants_reel(r.REEL_PILLARS[1] if r.reel_pillar_today(vd) == r.REEL_PILLARS[0]
                                else r.REEL_PILLARS[0], d=vd))
    check("slot_wants_reel false for every pillar on a non-video day",
          not any(r.slot_wants_reel(p, d=nvd) for p in ("science", "trending", "stack", "proof", "founder")))

    # 5 — env override of the anchor flips the calendar deterministically.
    import os
    os.environ["ENGINE_VIDEO_ANCHOR"] = (anchor + timedelta(days=1)).isoformat()
    check("ENGINE_VIDEO_ANCHOR shifts the video calendar by a day",
          e.is_video_day(anchor + timedelta(days=1)) and not e.is_video_day(anchor))
    del os.environ["ENGINE_VIDEO_ANCHOR"]

    # 6 — image_source: a TRUE rolling 4:1 (4 Higgsfield then 1 Blotato), persisted, not random.
    tmp = Path(tempfile.mkdtemp(prefix="cadence_"))
    e.ENGINE_STATE = tmp / "engine_state.json"
    e.ENGINE_STATE.write_text(json.dumps({"image_source_counter": 0}))
    seq = [e.image_source() for _ in range(10)]
    check("image_source rolls 4 Higgsfield then 1 Blotato",
          seq == (["higgsfield"] * 4 + ["blotato"]) * 2)
    check("image_source is ~20% Blotato over a cycle", seq.count("blotato") == 2)
    check("image_source persists the counter (10 advances recorded)",
          json.loads(e.ENGINE_STATE.read_text())["image_source_counter"] == 10)
    check("image_source advance=False does NOT consume a slot",
          e.image_source(advance=False) == e.image_source(advance=False))

    # ENGINE_IMAGE_BLOTATO_EVERY tunes the ratio.
    e.ENGINE_STATE.write_text(json.dumps({"image_source_counter": 0}))
    os.environ["ENGINE_IMAGE_BLOTATO_EVERY"] = "3"
    seq3 = [e.image_source() for _ in range(6)]
    check("ENGINE_IMAGE_BLOTATO_EVERY=3 → every 3rd is Blotato",
          seq3 == ["higgsfield", "higgsfield", "blotato"] * 2)
    del os.environ["ENGINE_IMAGE_BLOTATO_EVERY"]

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
