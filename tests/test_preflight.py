#!/usr/bin/env python3
"""
test_preflight.py — the M3 gate must BLOCK bad submits and PASS clean ones.

Pure: exercises preflight.run_checks() with crafted generation plans. No network,
no generator call, 0 credits (run_checks does not touch the reuse-inventory network
path — that is best-effort UX in main()).

Run:  python3 tests/test_preflight.py     # exits 0 = pass, 1 = fail
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import preflight as pf

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


def plan(**kw):
    base = dict(route="image", prompt="", model=None, aspect=None, template=None,
                bg_policy=None, no_wait=False, reuse_checked=True)
    base.update(kw)
    return SimpleNamespace(**base)


IMG = pf.IMAGE_BLOCK
VID = pf.VIDEO_BLOCK

CLEAN_IMAGE = plan(
    route="image", model="gpt_image_2", aspect="9:16",
    template="templates/src/story-reel-dark.html", bg_policy="generate", reuse_checked=True,
    prompt=IMG + " cold-chain peptide vial on a deep-forest surface, soft side lighting, "
                 "generous negative space, editorial product still",
)
CLEAN_VIDEO = plan(
    route="video", model="seedance_2_0", aspect="9:16", no_wait=True, reuse_checked=True,
    prompt=VID + " clinical lab b-roll, slow dolly across glass vials, shallow depth of field",
)


def reasons(p):
    return pf.run_checks(p)


def test_clean_pass():
    print("clean submits PASS (no blocking reasons):")
    check("clean IMAGE plan passes", reasons(CLEAN_IMAGE) == [])
    check("clean VIDEO plan passes", reasons(CLEAN_VIDEO) == [])


def has(rs, frag):
    return any(frag.lower() in r.lower() for r in rs)


def test_blocks():
    print("bad submits BLOCK (with the right reason):")

    # bg_policy plain/reuse → no spend
    p = plan(**{**CLEAN_IMAGE.__dict__, "bg_policy": "plain"})
    check("bg_policy=plain blocks", has(reasons(p), "bg_policy=plain"))
    p = plan(**{**CLEAN_IMAGE.__dict__, "bg_policy": "reuse"})
    check("bg_policy=reuse blocks", has(reasons(p), "no generation needed"))

    # brand block missing
    p = plan(**{**CLEAN_IMAGE.__dict__, "prompt": "cold-chain vial, soft lighting"})
    check("missing IMAGE block blocks", has(reasons(p), "Brand Prompt Block is not prepended"))
    p = plan(**{**CLEAN_VIDEO.__dict__, "prompt": "lab b-roll, slow dolly"})
    check("missing VIDEO block blocks", has(reasons(p), "Brand Prompt Block is not prepended"))
    # wrong block for the medium
    p = plan(**{**CLEAN_VIDEO.__dict__, "prompt": IMG + " lab b-roll"})
    check("IMAGE block on a video route blocks", has(reasons(p), "VIDEO Brand Prompt Block"))

    # rendered text requested
    p = plan(**{**CLEAN_IMAGE.__dict__,
                "prompt": IMG + ' vial with the headline text "RECOVERY" across the top'})
    rs = reasons(p)
    check("text request blocks", has(rs, "requests rendered text"))
    check("quoted literal flagged", has(rs, "recovery") or has(rs, "quoted literal"))
    # negation is allowed
    p = plan(**{**CLEAN_IMAGE.__dict__, "prompt": IMG + " clean vial, no text, no lettering"})
    check("'no text' does NOT block", not has(reasons(p), "requests rendered text"))

    # routing: person/ad in raw route → DTC
    p = plan(**{**CLEAN_IMAGE.__dict__,
                "prompt": IMG + " Nova the spokesperson holding the product, smiling to camera"})
    check("spokesperson in raw image route blocks", has(reasons(p), "DTC Ads Engine"))

    # medium↔model mismatch
    p = plan(**{**CLEAN_IMAGE.__dict__, "model": "seedance_2_0"})
    check("video model on image route blocks", has(reasons(p), "is a VIDEO model"))
    p = plan(**{**CLEAN_VIDEO.__dict__, "model": "gpt_image_2"})
    check("image model on video route blocks", has(reasons(p), "is an IMAGE model"))

    # aspect mismatch vs template
    p = plan(**{**CLEAN_IMAGE.__dict__, "aspect": "1:1"})
    check("aspect 1:1 vs 9:16 story template blocks", has(reasons(p), "template requires 9:16"))

    # video must be --no-wait
    p = plan(**{**CLEAN_VIDEO.__dict__, "no_wait": False})
    check("video without --no-wait blocks", has(reasons(p), "--no-wait"))

    # reuse not acknowledged
    p = plan(**{**CLEAN_IMAGE.__dict__, "reuse_checked": False})
    check("missing --reuse-checked blocks", has(reasons(p), "reuse check not acknowledged"))


def test_block_lists_all_failures():
    print("a fully-bad plan reports MANY reasons (hard wall, all checks):")
    p = plan(route="image", prompt="just a bare creative prompt with caption text",
             model="seedance_2_0", aspect="1:1",
             template="templates/src/story-reel-dark.html", bg_policy="plain",
             no_wait=False, reuse_checked=False)
    rs = reasons(p)
    check("reports 5+ blocking reasons", len(rs) >= 5)


def test_print_block_matches_produce():
    print("IMAGE block stays in sync with produce.py (no drift):")
    check("preflight IMAGE block == verbatim literal", pf.IMAGE_BLOCK == pf._IMAGE_BLOCK_LITERAL)


if __name__ == "__main__":
    test_clean_pass()
    test_blocks()
    test_block_lists_all_failures()
    test_print_block_matches_produce()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
