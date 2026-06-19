#!/usr/bin/env python3
"""
test_reel_push.py — F7 GATE 2: the final review card must render for a REEL (video, not
PNGs), label it 'reel', and tolerate BOTH caption shapes (plain string AND {text, thread}),
which the original build_card crashed on.

Pure: builds the card off a temp job; no network, no Telegram send. 0 credits.
Run:  python3 tests/test_reel_push.py     # exits 0 = pass, 1 = fail
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import telegram as tg

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
    # _cap_text tolerates both shapes.
    check("_cap_text reads a plain-string caption", tg._cap_text({"x": "hello"}, "x") == "hello")
    check("_cap_text reads a {text} dict caption", tg._cap_text({"x": {"text": "hi", "thread": []}}, "x") == "hi")
    check("_cap_text falls through platforms in order",
          tg._cap_text({"x": {"text": "z"}}, "instagram", "x") == "z")

    tmp = Path(tempfile.mkdtemp(prefix="gate2_"))
    job = tmp / "ACME-RTST"
    job.mkdir()
    (job / "brief.json").write_text(json.dumps({
        "job_id": "ACME-RTST", "type": "reel", "brand": "labs", "pillar": "science",
        "persona": "P1", "topic": "MC1R pathway", "platforms": ["tiktok", "x", "youtube"],
        "reference": {"url": "https://youtu.be/X", "platform": "youtube",
                      "description": "Source Bank angle ang-002", "cloned_format": "reel"},
    }))
    # The {text, thread} dict shape that used to crash build_card.
    (job / "captions.json").write_text(json.dumps({
        "x": {"text": "MC1R receptor mechanism in research subjects. For research use only.", "thread": []},
        "tiktok": {"text": "How it signals. Research use only.", "thread": []},
    }))

    card = tg.build_card(job)
    check("build_card does not crash on dict captions", isinstance(card, str) and len(card) > 0)
    check("card labels the format 'reel'", "Format: reel" in card)
    check("card shows the X caption text", "MC1R receptor mechanism" in card)
    check("card surfaces the reference URL", "https://youtu.be/X" in card)
    check("card lists the reel platforms", "youtube" in card)

    # reel_final prefers the embedded final over the bare captioned clip.
    (job / "captioned.mp4").write_text("x")
    check("reel_final falls back to captioned.mp4", tg.reel_final(job).name == "captioned.mp4")
    (job / "ACME-RTST-final.mp4").write_text("x")
    check("reel_final prefers <job>-final.mp4", tg.reel_final(job).name == "ACME-RTST-final.mp4")

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
