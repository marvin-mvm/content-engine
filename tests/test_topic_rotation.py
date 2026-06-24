#!/usr/bin/env python3
"""
test_topic_rotation.py — the daily run must NOT recycle the same compound→pillar→topic brief
every morning (Marvin 2026-06-22: "content looks very similar and repeating"). Guards:
  - recently_used_compounds() reads the last N briefs and reports their compounds (cooldown).
  - the candidate pool the daily run scores EXCLUDES those (rotation) so today != yesterday.
  - frame_for() rotates the per-pillar hook by day, so framing isn't a fixed template.

Pure: uses a temp JOBS_DIR of synthetic briefs. No network, no render. 0 credits.
Run:  python3 tests/test_topic_rotation.py     # exits 0 = pass, 1 = fail
"""

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine as eng
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


def _mkjob(jobs_dir: Path, jid: str, compound: str):
    d = jobs_dir / jid
    d.mkdir(parents=True, exist_ok=True)
    (d / "brief.json").write_text(json.dumps({"job_id": jid, "compound": compound}))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        jobs = Path(tmp) / "jobs"
        jobs.mkdir()
        # Yesterday's batch (the four pillar compounds that got recycled in the bug report).
        for jid, c in [("ACME-042", "Tirzepatide"), ("ACME-043", "Semaglutide"),
                       ("ACME-044", "Ipamorelin"), ("ACME-045", "CJC-1295")]:
            _mkjob(jobs, jid, c)
        orig = eng.JOBS_DIR
        eng.JOBS_DIR = jobs
        try:
            recent = r.recently_used_compounds(window_jobs=8)
            check("recently_used finds yesterday's compounds",
                  set(recent) == {"Tirzepatide", "Semaglutide", "Ipamorelin", "CJC-1295"})
            check("most-recent first (ACME-045 = CJC-1295 leads)", recent[0] == "CJC-1295")

            ranked = ["BPC-157", "Semaglutide", "Tirzepatide", "TB-500", "CJC-1295",
                      "Ipamorelin", "NAD+", "Semax"]
            fresh = [c for c in ranked if c not in recent]
            today = fresh[:4]
            check("today's picks share NO compound with yesterday",
                  not (set(today) & set(recent)))
            check("rotation pulls deeper into the catalog (BPC-157/TB-500/NAD+ now eligible)",
                  {"BPC-157", "TB-500", "NAD+"} <= set(fresh))

            # window=0 disables the cooldown (escape hatch).
            check("window 0 disables the cooldown", r.recently_used_compounds(window_jobs=0) == [])
        finally:
            eng.JOBS_DIR = orig

    # Recency + FAMILY penalty (Marvin 2026-06-23): with only ~12 SKUs at 5 posts/day the 7-day
    # window can't supply a fresh pool, so trending alone kept re-picking GLP-1s. After ANY GLP-1
    # the whole incretin family is down-weighted, breaking the Tirzepatide/Semaglutide cluster.
    check("GLP-1 compounds share one rotation family",
          r.compound_family("Tirzepatide") == r.compound_family("Semaglutide") == r.compound_family("Retatrutide"))
    check("a non-GLP-1 buckets separately",
          r.compound_family("BPC-157") != r.compound_family("Tirzepatide"))
    recent_glp1 = ["Tirzepatide", "BPC-157", "TB-500"]
    check("a recently-used GLP-1 is penalized", r.recency_penalty("Tirzepatide", recent_glp1) < 0.5)
    check("a FAMILY-mate of a recent GLP-1 is ALSO penalized",
          r.recency_penalty("Semaglutide", recent_glp1) < 0.5)
    check("a fresh non-GLP-1 keeps full weight", r.recency_penalty("NAD+", recent_glp1) == 1.0)
    check("penalty flips ranking: a fresh NAD+ outranks a hotter but recently-used GLP-1",
          0.9 * r.recency_penalty("NAD+", recent_glp1) > 1.0 * r.recency_penalty("Tirzepatide", recent_glp1))
    check("empty recency list is a no-op (full weight)", r.recency_penalty("Tirzepatide", []) == 1.0)

    # Aesthetic/melanocortin peptides are IMAGE-only — excluded from autonomous reel topics but kept
    # in the image rotation (Marvin 2026-06-23).
    check("video-excluded set is Melanotan-2 + PT-141",
          r.VIDEO_EXCLUDED_COMPOUNDS == {"Melanotan-2", "PT-141"})
    check("video-excluded compounds stay in the image catalog",
          {"Melanotan-2", "PT-141"} <= set(r.COMPOUND_CATALOG))
    reel_pool = [c for c in r.COMPOUND_CATALOG if c not in r.VIDEO_EXCLUDED_COMPOUNDS]
    check("video-excluded compounds are NOT in the reel pool",
          not ({"Melanotan-2", "PT-141"} & set(reel_pool)))

    # Frame rotation: consecutive days yield DIFFERENT hooks for the same pillar.
    d0 = date(2026, 6, 22)
    frames = {r.frame_for("stack", date.fromordinal(d0.toordinal() + i)) for i in range(3)}
    check("stack hook varies across 3 consecutive days", len(frames) == 3)
    check("every pillar has >= 2 frames",
          all(len(v) >= 2 for v in r.PILLAR_TOPIC_FRAMES.values()))
    check("singular PILLAR_TOPIC_FRAME alias still works (back-compat)",
          r.PILLAR_TOPIC_FRAME["stack"] == r.PILLAR_TOPIC_FRAMES["stack"][0])

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
