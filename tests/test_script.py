#!/usr/bin/env python3
"""
test_script.py — the F7 RV2 reel-script generator must (a) structure + size a clean
script, and (b) BLOCK a RED compliance claim before it can reach a credit spend.

Pure: monkeypatches script.call_openrouter / load_api_key so no network, no OpenRouter
call, 0 credits. Proves the compliance retry + hard-fail path deterministically.

Run:  python3 tests/test_script.py     # exits 0 = pass, 1 = fail
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import script as sc

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


def fake_resp(beats: dict):
    import json
    return {"choices": [{"message": {"content": json.dumps(beats)}}]}


def main():
    sc.load_api_key = lambda: "test-key"  # never read the real .env

    # 1 — a clean script: structured, sized, no RED.
    clean = {
        "hook": "Most peptide advice online is wrong.",
        "build": "Research in preclinical models suggests BPC-157 may support tissue-repair markers in study subjects.",
        "payoff": "The mechanism is signaling, not stimulation — it modulates growth-factor pathways.",
        "cta": "Follow Acme Labs for the science. For research use only.",
        "full_text": ("Most peptide advice online is wrong. Research in preclinical models suggests "
                      "BPC-157 may support tissue-repair markers in study subjects. The mechanism is "
                      "signaling, not stimulation — it modulates growth-factor pathways. Follow Acme "
                      "Labs for the science. For research use only."),
    }
    sc.call_openrouter = lambda messages, model, key: fake_resp(clean)
    beats, warnings = sc.generate(topic="BPC-157 mechanism", pillar="science", persona="P1",
                                  brand="labs", seconds=28)
    check("clean script returned", beats["full_text"].startswith("Most peptide advice"))
    check("word + est_seconds computed", beats["words"] > 0 and beats["est_seconds"] > 0)
    check("Labs RUO framing satisfied (no RUO warning)",
          not any("research use only" in w.lower() for w in warnings))

    # 2 — a RED script that STAYS red on retry must raise (blocks the credit spend).
    red = dict(clean)
    red["full_text"] = "This peptide cures inflammation and burns fat fast. Guaranteed results."
    sc.call_openrouter = lambda messages, model, key: fake_resp(red)
    raised = False
    try:
        sc.generate(topic="x", pillar="science", persona="P1", brand="labs", seconds=28)
    except sc.ScriptComplianceError as e:
        raised = True
        check("RED error carries the offending hits", bool(e.red))
    check("RED script (survives retry) raises ScriptComplianceError", raised)

    # 3 — a RED first draft that the retry FIXES should pass (one retry, then clean).
    calls = {"n": 0}

    def flaky(messages, model, key):
        calls["n"] += 1
        return fake_resp(red if calls["n"] == 1 else clean)

    sc.call_openrouter = flaky
    beats2, _ = sc.generate(topic="x", pillar="science", persona="P1", brand="labs", seconds=28)
    check("retry recovers a fixable RED draft", calls["n"] == 2 and "cures" not in beats2["full_text"])

    # 4 — pure helper.
    check("_target_words scales with seconds", sc._target_words(30) > sc._target_words(15))

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
