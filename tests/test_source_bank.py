#!/usr/bin/env python3
"""
test_source_bank.py — the Source Bank (RV0) must harvest the FULL transcript (no
truncation), preserve angle state across re-scrapes, and serve/mark unused angles.

Pure: exercises source_bank's transform + storage on crafted payloads against a temp
bank dir. No network, no extraction, 0 credits (propose_angles, the only OpenRouter
call, is NOT exercised here — its compliance gate is checked via red_hits directly).

Run:  python3 tests/test_source_bank.py     # exits 0 = pass, 1 = fail
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import source_bank as sb
from compliance import red_hits

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def long_raw(n_cues=400):
    """A synthetic apify `--raw` YouTube payload whose SRT transcript far exceeds
    apify's MAX_TRANSCRIPT_CHARS (4000) — proving the bank does NOT truncate."""
    cues = "\n".join(
        f"{i+1}\n00:00:{i%60:02d},000 --> 00:00:{(i+1)%60:02d},000\n"
        f"Research subjects in study segment number {i+1} showed measured markers.\n"
        for i in range(n_cues)
    )
    return [{
        "url": "https://youtu.be/PROOF", "title": "Long interview",
        "viewCount": "2.6M", "likeCount": "73,000", "commentCount": 5996,
        "subtitles": [{"language": "en", "srt": cues}], "text": "video description",
    }]


def main():
    # Isolate the bank in a temp dir so the real output/research/sources is untouched.
    tmp = Path(tempfile.mkdtemp(prefix="sbtest_"))
    sb.SOURCES_DIR = tmp

    # 1 — FULL transcript parse, no truncation; count coercion.
    ft, cap, eng = sb.normalize_payload(long_raw())
    check("raw transcript bypasses 4000-char truncation", len(ft) > 4000)
    check("transcript tail present (not cut)", "segment number 400" in ft)
    check("count coercion 2.6M/73,000/int", eng == {"views": 2_600_000, "likes": 73_000, "comments": 5996})
    check("caption falls back to description/text", cap == "video description")

    # 2 — structured (cache/blotato) payload also normalizes.
    ft2, cap2, eng2 = sb.normalize_payload({"platform": "youtube", "transcript": "short text",
                                            "caption": "a caption", "views": 10, "likes": 2, "comments_count": 1})
    check("structured transcript read", ft2 == "short text")
    check("structured engagement read", eng2 == {"views": 10, "likes": 2, "comments": 1})

    # 3 — article (blotato source) shape: content field.
    fta, _, _ = sb.normalize_payload({"content": "article body here", "title": "T"})
    check("article 'content' used as transcript", fta == "article body here")

    # 4 — identity.
    sid = sb.source_id("https://youtu.be/PROOF")
    check("source_id stable + 16 hex", len(sid) == 16 and sb._looks_like_id(sid))
    check("source_id case/space-insensitive", sb.source_id(" HTTPS://youtu.be/PROOF ") != sid
          or sb.source_id("https://youtu.be/proof") == sb.source_id("https://youtu.be/PROOF"))

    # 5 — upsert banks + preserves angles + never clobbers a longer transcript with a shorter one.
    rec = sb.upsert("https://youtu.be/PROOF", "youtube", long_raw())
    check("upsert writes a bank file", sb.bank_path(rec["source_id"]).exists())
    check("transcript_chars recorded", rec["transcript_chars"] == len(rec["full_transcript"]))
    rec["angles"] = [{"id": "ang-001", "angle": "x", "pillar": "science", "format": "reel",
                      "used": True, "job_id": "ACME-001"}]
    sb.save(rec)
    re2 = sb.upsert("https://youtu.be/PROOF", "youtube", long_raw(3))  # a thin re-scrape
    check("re-scrape preserves existing angles", len(re2["angles"]) == 1 and re2["angles"][0]["used"])
    check("thin re-scrape does NOT clobber the longer transcript", re2["transcript_chars"] > 4000)

    # 6 — serve/mark unused angles.
    rec3 = sb.upsert("https://youtu.be/Q", "youtube", long_raw(5))
    rec3["angles"] = [
        {"id": "ang-001", "angle": "a", "pillar": "science", "format": "reel", "used": False, "job_id": None},
        {"id": "ang-002", "angle": "b", "pillar": "proof", "format": "carousel", "used": False, "job_id": None},
        {"id": "ang-003", "angle": "c", "pillar": "trending", "format": "reel", "used": True, "job_id": "ACME-009"},
    ]
    sb.save(rec3)
    check("unused_angles excludes used", len(sb.unused_angles(rec3)) == 2)
    check("unused_angles filters by format", [a["id"] for a in sb.unused_angles(rec3, fmt="reel")] == ["ang-001"])
    sb.mark_used(rec3, "ang-001", "ACME-010")
    re3 = sb.load("https://youtu.be/Q")
    used = [a for a in re3["angles"] if a["id"] == "ang-001"][0]
    check("mark_used persists used + job_id", used["used"] and used["job_id"] == "ACME-010")

    # 7 — the compliance gate propose_angles relies on actually flags RED claims.
    check("red_hits flags a RED angle", bool(red_hits("This peptide cures inflammation and burns fat")))
    check("red_hits passes a compliant angle", not red_hits("Explain the alpha-MSH receptor pathway mechanism"))

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
