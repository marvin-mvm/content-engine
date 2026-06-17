#!/usr/bin/env python3
"""
poll_video.py — one poll-and-finish cycle for an async Higgsfield video job.

Designed to be run on a short cron tick (every ~2m). Does exactly ONE check:
  - queries `higgsfield generate get JOB_ID --json`
  - PENDING  → prints "PENDING <status>" and exits 0 (cron keeps ticking)
  - FAILED   → prints "FAILED <reason>" and exits 0 (caller notifies + removes cron)
  - completed→ downloads the mp4, runs produce.py --video to attach the branded
               thumbnail, prints "DONE <final_mp4_path>" and exits 0

No internal loop — one call per invocation, so it never blocks the agent.

Usage:
  poll_video.py JOB_ID --template templates/src/story-reel-dark.html
                       [--json /tmp/copy.json] [--set KEY=VALUE ...]
                       [--out output/name.mp4]

Exit code is always 0 on a clean check (PENDING/FAILED/DONE all expected);
non-zero only on an unexpected error (bad job id, network, parse failure).
"""

import argparse
import json
import os
import ssl
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).parent
OUTPUT_DIR = WORKSPACE / "output"
PRODUCE = str(WORKSPACE / "produce.py")

COMPLETED = {"completed", "done", "ready", "succeeded", "success"}
FAILED = {"failed", "error", "canceled", "cancelled", "ip_detected", "blocked", "rejected"}


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def higgsfield_get(job_id: str) -> dict | None:
    """Return the job dict, or None if the job is gone/unreadable (terminal)."""
    result = subprocess.run(
        ["higgsfield", "generate", "get", job_id, "--json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # "Job not found" or any get failure → terminal; caller treats as FAILED.
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return data[0] if isinstance(data, list) and data else data


def extract_prompt(job: dict) -> str:
    """Return the generation prompt recorded on a completed job, or "" if absent.

    Higgsfield stores the submitted prompt under params.prompt for video jobs
    (verified against `higgsfield generate list --json`); some job shapes use a
    top-level "prompt" or an "input" object instead. Same lookup chain copy.py
    uses. This is the value Content Matrix col F must record — without it,
    produce.py --video falls back to logging the local mp4 path (bug #1).
    """
    if not isinstance(job, dict):
        return ""
    prompt = job.get("prompt")
    for container in ("params", "input"):
        if not prompt and isinstance(job.get(container), dict):
            prompt = job[container].get("prompt")
    return prompt or ""


def build_produce_cmd(template, raw_mp4, final, json_file=None, pairs=None, prompt=""):
    """Construct the produce.py --video argv.

    NOTE: deliberately NO --no-log — this is OpenClaw's real-post path and must
    keep writing the live Content Matrix row. The col-F fix (bug #1) is passing
    the recovered generation --prompt so col F logs the prompt, not the mp4 path.
    Omitting prompt leaves behavior exactly as before (produce.py falls back to
    args.video), so the fix is backward-compatible.
    """
    cmd = [sys.executable, PRODUCE, template, "--video", str(raw_mp4), str(final)]
    if prompt:
        cmd += ["--prompt", prompt]
    if json_file:
        cmd += ["--json", json_file]
    for pair in (pairs or []):
        cmd += ["--set", pair]
    return cmd


def download(url: str, dest: Path):
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=_ssl_context())
    )
    with opener.open(url) as r, open(dest, "wb") as f:
        f.write(r.read())


def remove_cron(name: str):
    """Resolve a cron job's ID by name and remove it (rm requires ID, not name)."""
    try:
        listed = subprocess.run(
            ["openclaw", "cron", "list", "--json"],
            capture_output=True, text=True, timeout=20,
        )
        data = json.loads(listed.stdout)
        jobs = data if isinstance(data, list) else data.get("jobs", [])
        for j in jobs:
            if j.get("name") == name:
                subprocess.run(["openclaw", "cron", "rm", j["id"]],
                               capture_output=True, text=True, timeout=20)
                print(f"[poll] removed cron {name} ({j['id']})", file=sys.stderr)
                return
    except Exception as e:
        print(f"[poll] WARNING: could not remove cron {name}: {e}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="One poll-and-finish cycle for an async Higgsfield video job")
    ap.add_argument("job_id")
    ap.add_argument("--template", required=True, help="HTML template for the branded thumbnail")
    ap.add_argument("--json", dest="json_file", help="copy.py JSON for overlay tokens")
    ap.add_argument("--set", metavar="KEY=VALUE", action="append", default=[], dest="pairs")
    ap.add_argument("--out", help="Final mp4 path (default: output/<job_id>.mp4)")
    ap.add_argument("--cron-name", help="If set, remove this cron job on DONE/FAILED (self-cleanup)")
    args = ap.parse_args()

    job = higgsfield_get(args.job_id)
    if job is None:
        # Job doesn't exist (bad/hallucinated id, or expired) — terminal, stop polling.
        if args.cron_name:
            remove_cron(args.cron_name)
        print("FAILED job-not-found")
        return
    status = str(job.get("status", "")).lower()

    if status in FAILED:
        reason = job.get("fail_reason") or job.get("error") or "unknown"
        if args.cron_name:
            remove_cron(args.cron_name)
        print(f"FAILED {reason}")
        return

    if status not in COMPLETED:
        print(f"PENDING {status or 'unknown'}")
        return

    # Completed — find the video URL
    url = (job.get("result_url") or job.get("url")
           or job.get("output_url") or job.get("media_url"))
    if not url:
        if args.cron_name:
            remove_cron(args.cron_name)
        print(f"FAILED completed-but-no-url")
        return

    OUTPUT_DIR.mkdir(exist_ok=True)
    raw_mp4 = OUTPUT_DIR / f"{args.job_id}_raw.mp4"
    download(url, raw_mp4)

    final = args.out or str(OUTPUT_DIR / f"{args.job_id}.mp4")

    # Bug #1 fix: recover the generation prompt from the job record and pass it
    # as --prompt so Content Matrix col F logs the prompt, not the local mp4 path.
    prompt = extract_prompt(job)
    cmd = build_produce_cmd(args.template, raw_mp4, final,
                            json_file=args.json_file, pairs=args.pairs, prompt=prompt)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"ERROR: produce.py failed:\n{result.stderr.strip() or result.stdout.strip()}")

    if args.cron_name:
        remove_cron(args.cron_name)
    print(f"DONE {final}")


if __name__ == "__main__":
    main()
