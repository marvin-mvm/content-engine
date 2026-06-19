#!/usr/bin/env python3
"""
decisions.py — read the human A/R/E decision ledger (the learning corpus).

Every Telegram approve / revise / reject / hold (both the reel CONCEPT gate and the FINAL
gate) is appended by approvals.py to output/engine/decisions.jsonl with a snapshot of the
content it judged — topic/angle, the script + generation prompts, the caption, slide copy.
This is the local successor to the old Sheets Content-Matrix log, kept so the system can
learn from what got approved vs rejected (e.g. seed prompts/scripts from past approvals,
steer away from past rejections).

    decisions.py show  [--verb approve|revise|reject|hold] [--gate concept|final]
                       [--job ACME-NNN] [--field script|video_prompts|caption_x|...]
                       [--limit N] [--full]
    decisions.py stats                      counts by verb/gate + approval rate
    decisions.py prompts [--approved|--rejected]   just the scripts/prompts, by verdict

0 Higgsfield credits. Read-only.
"""
from __future__ import annotations

import argparse
import json
import sys

import engine as e

APPROVE_VERBS = {"approve"}
REJECT_VERBS = {"reject", "revise"}


def _match(d: dict, args) -> bool:
    if args.verb and d.get("verb") != args.verb:
        return False
    if args.gate and d.get("gate") != args.gate:
        return False
    if args.job and d.get("job_id") != args.job.upper():
        return False
    return True


def cmd_show(args):
    rows = [d for d in e.read_decisions() if _match(d, args)]
    if args.limit:
        rows = rows[-args.limit:]
    if not rows:
        print("no decisions match.")
        return
    for d in rows:
        c = d.get("content", {})
        head = f"{d['at']}  {d['verb'].upper():7} [{d.get('gate','?')}]  {d['job_id']}  by {d.get('who','?')}"
        if d.get("note"):
            head += f"  — {d['note']}"
        print(head)
        if args.field:
            v = c.get(args.field)
            if v is not None:
                print(f"    {args.field}: {json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}")
        elif args.full:
            print(f"    {json.dumps(c, ensure_ascii=False, indent=2)}")
        else:
            bits = []
            for k in ("topic", "format", "script", "video_prompts", "caption_x"):
                if c.get(k):
                    s = c[k] if isinstance(c[k], str) else json.dumps(c[k], ensure_ascii=False)
                    bits.append(f"{k}={s[:80] + ('…' if len(s) > 80 else '')}")
            if bits:
                print("    " + "  ·  ".join(bits))
        print()


def cmd_stats(args):
    rows = e.read_decisions()
    if not rows:
        print("no decisions recorded yet.")
        return
    by_verb: dict[str, int] = {}
    by_gate: dict[str, int] = {}
    for d in rows:
        by_verb[d.get("verb", "?")] = by_verb.get(d.get("verb", "?"), 0) + 1
        by_gate[d.get("gate", "?")] = by_gate.get(d.get("gate", "?"), 0) + 1
    appr = sum(by_verb.get(v, 0) for v in APPROVE_VERBS)
    rej = sum(by_verb.get(v, 0) for v in REJECT_VERBS)
    print(f"decisions: {len(rows)} total")
    print("  by verb: " + ", ".join(f"{k}={v}" for k, v in sorted(by_verb.items())))
    print("  by gate: " + ", ".join(f"{k}={v}" for k, v in sorted(by_gate.items())))
    if appr + rej:
        print(f"  approval rate (approve / approve+revise+reject): {appr / (appr + rej):.0%}")


def cmd_prompts(args):
    """The learning slice: scripts + generation prompts grouped by verdict."""
    want = None
    if args.approved:
        want = APPROVE_VERBS
    elif args.rejected:
        want = REJECT_VERBS
    for d in e.read_decisions():
        if want and d.get("verb") not in want:
            continue
        c = d.get("content", {})
        script = c.get("script")
        prompts = c.get("video_prompts") or c.get("bg_prompt")
        if not script and not prompts:
            continue
        print(f"{d['verb'].upper():7} {d['job_id']}  ({c.get('topic','?')})"
              + (f" — {d['note']}" if d.get("note") else ""))
        if script:
            print(f"    script: {script[:300]}{'…' if len(script) > 300 else ''}")
        if prompts:
            print(f"    prompts: {json.dumps(prompts, ensure_ascii=False)}")
        print()


def main():
    ap = argparse.ArgumentParser(prog="decisions", description="Read the A/R/E decision ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("show", help="List decisions (filterable)")
    ps.add_argument("--verb", choices=["approve", "revise", "reject", "hold"])
    ps.add_argument("--gate", choices=["concept", "final"])
    ps.add_argument("--job")
    ps.add_argument("--field", help="Print one content field verbatim (script/video_prompts/caption_x/...)")
    ps.add_argument("--limit", type=int, help="Only the most recent N")
    ps.add_argument("--full", action="store_true", help="Dump the full content snapshot")
    ps.set_defaults(func=cmd_show)

    pt = sub.add_parser("stats", help="Counts by verb/gate + approval rate")
    pt.set_defaults(func=cmd_stats)

    pp = sub.add_parser("prompts", help="Scripts + generation prompts grouped by verdict")
    g = pp.add_mutually_exclusive_group()
    g.add_argument("--approved", action="store_true", help="Only approved")
    g.add_argument("--rejected", action="store_true", help="Only revised/rejected")
    pp.set_defaults(func=cmd_prompts)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
