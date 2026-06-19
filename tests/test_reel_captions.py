#!/usr/bin/env python3
"""
test_reel_captions.py — F7 RV4 caption core: reconcile Whisper timings to the AUTHORED
script (exact text, no mis-hear) and auto beat-group into a valid caption_data structure
(3-5 words/beat, <=2 lines, UNIFORM_CREAM, every word indexed exactly once in order).

Pure: no TTS, no Whisper, no render — feeds a synthetic transcript. 0 credits.
Run:  python3 tests/test_reel_captions.py     # exits 0 = pass, 1 = fail
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import reel_captions as rc

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
    script = "Most peptide advice is wrong. Research suggests otherwise. For research use only."
    toks = script.split()  # 12 tokens

    # Whisper with a couple of mis-hears + a split; same-ish timings.
    whisper = [{"id": f"w{i}", "text": t, "start": round(i * 0.4, 2), "end": round(i * 0.4 + 0.35, 2)}
               for i, t in enumerate(["Most", "peptide", "advise", "is", "wrong.", "Research",
                                      "suggest", "otherwise.", "For", "research", "use", "only."])]

    words = rc.reconcile(whisper, script)
    check("one reconciled word per script token", len(words) == len(toks))
    check("reconciled TEXT is the exact script (mis-hears fixed)", [w["text"] for w in words] == toks)
    check("borrowed Whisper timings", words[0]["start"] == 0.0 and words[1]["end"] == 0.75)
    check("timings monotonic non-decreasing",
          all(words[i]["start"] <= words[i + 1]["start"] for i in range(len(words) - 1)))

    # Unequal counts (a dropped word) still yields one entry per script token, monotonic.
    words2 = rc.reconcile(whisper[:-1], script)
    check("unequal counts: still one word per script token", len(words2) == len(toks))
    check("unequal counts: timings stay monotonic",
          all(words2[i]["start"] <= words2[i + 1]["start"] for i in range(len(words2) - 1)))

    # Beat-grouping.
    blocks = rc.beat_group(words)
    flat = [idx for b in blocks for line in (b["line1"], b["line2"]) if line for idx, _ in line]
    check("every word indexed exactly once, in order", flat == list(range(len(words))))
    check("each beat <= 5 words", all(
        len(b["line1"]) + (len(b["line2"]) if b["line2"] else 0) <= rc.BEAT_MAX for b in blocks))
    check("each beat <= 2 lines (line1 + optional line2)", all(set(b) == {"line1", "line2"} for b in blocks))
    check("all tiers are 'n' (uniform cream)", all(
        tier == "n" for b in blocks for line in (b["line1"], b["line2"]) if line for _, tier in line))
    check("beats break on sentence ends (first beat ends at 'wrong.')",
          blocks[0]["line1"][-1][0] == 4 or (blocks[0]["line2"] and blocks[0]["line2"][-1][0] == 4))

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
