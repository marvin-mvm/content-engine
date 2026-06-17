#!/usr/bin/env python3
"""
test_poll_video.py — isolated unit test for the poll_video.py col-F fix (bug #1).

Asserts the prompt-extraction + produce.py argv construction in ISOLATION:
mocked job dicts only. No subprocess, no network, no produce.py run, NO live
Content Matrix write — poll_video.py runs produce.py WITHOUT --no-log (it's
OpenClaw's real-post path), so this test must never execute that path.

Run:  python3 tests/test_poll_video.py     # exits 0 = pass, 1 = fail
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import poll_video as pv

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


# Real shape verified against `higgsfield generate list --json`: a completed
# video job nests the submitted prompt under params.prompt.
JOB_PARAMS = {
    "id": "3ba2d12b-4e10-44a5-ad47-43fda2f5ee31",
    "status": "completed",
    "result_url": "https://cdn.example/hf.mp4",
    "params": {"prompt": "Lab b-roll, deep forest green, slow dolly", "model": "seedance_2_0"},
}
JOB_TOP = {"id": "x", "status": "completed", "prompt": "top-level prompt form"}
JOB_INPUT = {"id": "y", "status": "completed", "input": {"prompt": "input-object prompt form"}}
JOB_NONE = {"id": "z", "status": "completed", "result_url": "https://cdn.example/hf.mp4"}

GEN_PROMPT = JOB_PARAMS["params"]["prompt"]


def test_extract_prompt():
    print("extract_prompt:")
    check("reads params.prompt (the real video-job shape)", pv.extract_prompt(JOB_PARAMS) == GEN_PROMPT)
    check("reads top-level prompt", pv.extract_prompt(JOB_TOP) == "top-level prompt form")
    check("reads input.prompt", pv.extract_prompt(JOB_INPUT) == "input-object prompt form")
    check("returns '' when no prompt present", pv.extract_prompt(JOB_NONE) == "")
    check("returns '' on non-dict", pv.extract_prompt(None) == "")


def test_build_cmd_passes_prompt():
    print("build_produce_cmd — the fix (col F gets the prompt):")
    prompt = pv.extract_prompt(JOB_PARAMS)
    cmd = pv.build_produce_cmd(
        "templates/src/story-reel-dark.html",
        "output/JOB_raw.mp4", "output/JOB.mp4",
        json_file="/tmp/copy.json", pairs=["EYEBROW=RESEARCH USE ONLY"], prompt=prompt,
    )
    # --prompt present and immediately followed by the exact generation prompt
    check("argv contains --prompt", "--prompt" in cmd)
    check("--prompt value is the generation prompt (not the mp4 path)",
          cmd[cmd.index("--prompt") + 1] == GEN_PROMPT)
    check("prompt is NOT the mp4 path (the bug)", cmd[cmd.index("--prompt") + 1] != "output/JOB_raw.mp4")
    # Contract preserved: still --video, still passes --json / --set, and crucially NO --no-log.
    check("still uses --video", "--video" in cmd)
    check("passes through --json", "--json" in cmd and "/tmp/copy.json" in cmd)
    check("passes through --set pairs", "--set" in cmd and "EYEBROW=RESEARCH USE ONLY" in cmd)
    check("does NOT add --no-log (preserves the live-post contract)", "--no-log" not in cmd)


def test_build_cmd_backward_compatible():
    print("build_produce_cmd — backward compatible when no prompt:")
    # Job with no recoverable prompt → no --prompt flag → produce.py falls back
    # to args.video exactly as it did before the fix.
    cmd = pv.build_produce_cmd(
        "templates/src/story-reel-dark.html", "output/JOB_raw.mp4", "output/JOB.mp4",
        prompt=pv.extract_prompt(JOB_NONE),
    )
    check("no --prompt flag when prompt is empty", "--prompt" not in cmd)
    check("still a valid --video argv", cmd[:4] == [sys.executable, pv.PRODUCE, "templates/src/story-reel-dark.html", "--video"])
    check("does NOT add --no-log", "--no-log" not in cmd)


if __name__ == "__main__":
    test_extract_prompt()
    test_build_cmd_passes_prompt()
    test_build_cmd_backward_compatible()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
