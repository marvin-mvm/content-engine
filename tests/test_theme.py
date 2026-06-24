#!/usr/bin/env python3
"""
test_theme.py — dark/light theme follows the ASSIGNED SLOT, not the pillar (content.md:
"morning feed is LIGHT"). Guards the same-pillar-day regression: a 4×trending day (the
bank-first/dedup flow) slots trending posts into the 08:00/11:00 morning slots, which must
STILL render light — the old pillar-keyed theme rendered them dark.

Pure: no network, no credits. Run:  python3 tests/test_theme.py   # exit 0 = pass, 1 = fail
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine as e            # noqa: E402
import produce_daily as pd    # noqa: E402

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


def main():
    # 1 — pure policy: morning slots light, midday/evening dark, Health always light.
    check("08:00 → light", e.theme_for_slot("08:00", "labs") == "light")
    check("11:00 → light", e.theme_for_slot("11:00", "labs") == "light")
    check("13:00 → dark", e.theme_for_slot("13:00", "labs") == "dark")
    check("16:00 → dark", e.theme_for_slot("16:00", "labs") == "dark")
    check("19:00 → dark", e.theme_for_slot("19:00", "labs") == "dark")
    check("unknown slot → dark (safe default)", e.theme_for_slot(None, "labs") == "dark")
    check("Health is light at every slot", all(
        e.theme_for_slot(s, "health") == "light" for s in e.SLOTS + [None]))

    # 2 — the same-pillar-day case: assign_slots spreads 4× trending across the 5 PT slots,
    #     putting two of them into the 08:00/11:00 morning slots.
    slotted = e.assign_slots([{"job_id": f"T{i}", "pillar": "trending", "brand": "labs"} for i in range(4)])
    by_slot = {j["slot"]: j["job_id"] for j in slotted}
    check("4× trending fills the morning slots too", "08:00" in by_slot and "11:00" in by_slot)

    # 3 — retheme_to_slot flips a trending morning card to light, leaves afternoon dark.
    tmp = Path(tempfile.mkdtemp(prefix="theme_"))

    def make(tpl, jid="J"):
        d = tmp / jid
        d.mkdir(parents=True, exist_ok=True)
        (d / "brief.json").write_text(json.dumps(
            {"type": "image", "pillar": "trending", "image": {"template": f"templates/src/{tpl}.html"}}))
        return d

    def tmpl(d):
        return Path(json.load(open(d / "brief.json"))["image"]["template"]).name

    d8 = make("story-poll-pro-dark", "m8")
    pd.retheme_to_slot(d8, "08:00", "labs")
    check("trending @08:00 dark→light", tmpl(d8) == "story-poll-pro-light.html")

    d11 = make("carousel-dark", "m11")
    pd.retheme_to_slot(d11, "11:00", "labs")
    check("trending @11:00 dark→light (carousel)", tmpl(d11) == "carousel-light.html")

    d13 = make("story-reel-dark", "a13")
    pd.retheme_to_slot(d13, "13:00", "labs")
    check("trending @13:00 stays dark", tmpl(d13) == "story-reel-dark.html")

    # already-correct light morning card is left untouched
    d8b = make("static-compound-light", "m8b")
    pd.retheme_to_slot(d8b, "08:00", "labs")
    check("already-light morning card untouched", tmpl(d8b) == "static-compound-light.html")

    # Health morning + evening → light either way
    dh = make("carousel-dark", "h19")
    pd.retheme_to_slot(dh, "19:00", "health")
    check("Health @19:00 → light", tmpl(dh) == "carousel-light.html")

    # 4 — no-op for a reel brief (overlay-themed elsewhere) and an unthemed template.
    dr = tmp / "reel"
    dr.mkdir(parents=True, exist_ok=True)
    (dr / "brief.json").write_text(json.dumps({"type": "reel", "overlay": {"template": "x-dark.html"}}))
    pd.retheme_to_slot(dr, "08:00", "labs")
    check("reel brief untouched", json.load(open(dr / "brief.json"))["overlay"]["template"] == "x-dark.html")

    du = make("story-poll", "unthemed")   # no -dark/-light suffix
    pd.retheme_to_slot(du, "08:00", "labs")
    check("unthemed template untouched", tmpl(du) == "story-poll.html")

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
