#!/usr/bin/env python3
"""
test_pillar_spread.py — the daily run must cover ALL FIVE pillars (v2 §2/§3.1), not just
science|stack. Guards research.plan_pillar_briefs: spread → one brief per non-trending pillar
(stack gets a compound), legacy → per-topic science|stack, explicit --pillar honoured.

Pure: no network, no credits. Run:  python3 tests/test_pillar_spread.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import research as r          # noqa: E402


def main():
    fails = []

    def check(name, cond):
        print(("ok  " if cond else "FAIL"), name)
        if not cond:
            fails.append(name)

    picks = [
        {"topic": "BPC-157", "compound": "BPC-157"},
        {"topic": "NAD+", "compound": "NAD+"},
        {"topic": "longevity mindset", "compound": None},
        {"topic": "Semaglutide", "compound": "Semaglutide"},
    ]

    # ── spread (the daily run): one brief per non-trending pillar, stack gets a compound ──
    plan = r.plan_pillar_briefs(picks, spread=True)
    pillars = [p for p, _ in plan]
    check("spread covers all 4 non-trending pillars",
          set(pillars) == {"stack", "science", "proof", "founder"})
    check("no pillar duplicated", len(pillars) == len(set(pillars)))
    check("stack carries a real compound", dict(plan)["stack"]["compound"] is not None)
    check("the non-compound topic still gets placed",
          any(s["compound"] is None for _, s in plan))

    # ── spread with too few picks: degrade gracefully (stack first, then science) ──
    plan2 = r.plan_pillar_briefs(picks[:2], spread=True)
    check("2 compound picks → stack + science only", [p for p, _ in plan2] == ["stack", "science"])

    # ── spread with NO compounds: stack is skipped (it needs a compound) ──
    others = [{"topic": "sleep", "compound": None}, {"topic": "fasting", "compound": None}]
    plan3 = r.plan_pillar_briefs(others, spread=True)
    check("no-compound day skips stack", "stack" not in [p for p, _ in plan3])

    # ── legacy (standalone topics): per-topic science|stack by compound-match ──
    legacy = r.plan_pillar_briefs(picks, spread=False)
    check("legacy compound → stack", legacy[0][0] == "stack")
    check("legacy non-compound → science", legacy[2][0] == "science")

    # ── explicit --pillar overrides everything ──
    exp = r.plan_pillar_briefs(picks, spread=False, explicit_pillar="proof")
    check("explicit --pillar honoured", all(p == "proof" for p, _ in exp))

    print("PASS" if not fails else f"FAIL: {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
