#!/usr/bin/env python3
"""
test_extraction_routing.py — the EXTRACTION ("read inside a link") router.

Proves the RV1 routing rule end-to-end, with NO network / NO credits (research.run_tool
is monkeypatched to canned payloads):

  • article / blog / website URL          → firecrawl.py scrape   (NEVER blotato)
  • social / video URL (yt/ig/tt/fb/th)   → apify.py scrape
  • Firecrawl's markdown body is what normalize_payload banks as the transcript
  • extract_pattern's fallback also reads `markdown` when the --raw bank came back empty

Run:  python3 tests/test_extraction_routing.py     # exits 0 = pass, 1 = fail
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import research            # noqa: E402
import source_bank as sb   # noqa: E402

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


ARTICLE_MD = "# Hype vs evidence\n\nThe COA tells the real story. " + ("Body paragraph. " * 400)
FALLBACK_MD = "Fallback article body recovered via the non-raw firecrawl re-scrape. " * 5
SRT = ("1\n00:00:00,000 --> 00:00:02,000\nThis is the spoken transcript.\n\n"
       "2\n00:00:02,000 --> 00:00:04,000\nA second narrated line.\n")

CALLS = []


def fake_run_tool(script, args, ttl=None, fresh=False):
    """Record every tool invocation; return a canned payload per tool. The 7-day TTL is
    asserted on the call record so cost-parity with apify is preserved."""
    CALLS.append({"script": script, "args": list(args), "ttl": ttl})
    args = list(args)
    url = args[1] if len(args) > 1 else ""
    raw = "--raw" in args
    if script == "firecrawl.py":
        if "empty-raw" in url and raw:                      # force the extract_pattern fallback
            return {"success": True, "data": {"markdown": "", "metadata": {}}}
        if "empty-raw" in url and not raw:                  # the fallback re-scrape (trimmed shape)
            return {"url": url, "title": "Fb", "description": "blurb", "markdown": FALLBACK_MD}
        return {"success": True, "data": {"markdown": ARTICLE_MD,
                                          "metadata": {"title": "T", "description": "d"}}}
    if script == "apify.py":
        return [{"url": url, "subtitles": [{"language": "en", "srt": SRT}], "viewCount": "1200000"}]
    return None


def scripts_called():
    return [c["script"] for c in CALLS]


def main():
    # Isolate the bank + neutralise every paid subprocess.
    sb.SOURCES_DIR = Path(tempfile.mkdtemp(prefix="routetest_"))
    research.run_tool = fake_run_tool
    EXPECTED_TTL = 7 * research.CACHE_TTL

    # 1 — ARTICLE URL → firecrawl --raw, NEVER blotato/apify; markdown banked as transcript.
    CALLS.clear()
    rec = research.bank_source("https://www.nature.com/articles/d41586")
    check("article routes to firecrawl.py", scripts_called() == ["firecrawl.py"])
    check("article never touches blotato", "blotato.py" not in scripts_called())
    check("article never touches apify", "apify.py" not in scripts_called())
    check("firecrawl called with scrape --raw", CALLS[0]["args"][:1] == ["scrape"] and "--raw" in CALLS[0]["args"])
    check("firecrawl banked at the 7-day TTL", CALLS[0]["ttl"] == EXPECTED_TTL)
    check("banked platform is 'article'", rec and rec["platform"] == "article")
    check("normalize_payload banks the FULL firecrawl markdown", rec and rec["full_transcript"] == ARTICLE_MD)

    # 2 — SOCIAL URL → apify --raw, NEVER firecrawl/blotato.
    CALLS.clear()
    rec2 = research.bank_source("https://youtu.be/PROOF42")
    check("social routes to apify.py", scripts_called() == ["apify.py"])
    check("social never touches firecrawl", "firecrawl.py" not in scripts_called())
    check("social never touches blotato", "blotato.py" not in scripts_called())
    check("apify banked at the 7-day TTL", CALLS[0]["ttl"] == EXPECTED_TTL)
    check("social transcript parsed from SRT", rec2 and "spoken transcript" in rec2["full_transcript"])

    # 2b — X / Twitter is now SOCIAL → apify (previously mis-routed to the article path).
    CALLS.clear()
    recx = research.bank_source("https://x.com/user/status/123")
    check("x/twitter routes to apify.py", scripts_called() == ["apify.py"])
    check("x never touches firecrawl/blotato",
          "firecrawl.py" not in scripts_called() and "blotato.py" not in scripts_called())
    check("x banked platform is 'x'", recx and recx["platform"] == "x")
    check("twitter.com also routes to apify",
          (research._detect_platform("https://twitter.com/u/status/9") == "x"))

    # 3 — extract_pattern on an article yields the markdown-derived pattern (primary path).
    CALLS.clear()
    pat = research.extract_pattern("https://blog.example.com/peptide-myths")
    check("extract_pattern article → not None", bool(pat))
    check("extract_pattern platform 'article'", pat and pat["platform"] == "article")
    check("extract_pattern text comes from markdown", pat and "COA tells the real story" in pat["text"])
    check("extract_pattern never called blotato", "blotato.py" not in scripts_called())

    # 4 — fallback path: when the --raw bank is empty, the re-scrape reads `markdown` (trap #2).
    CALLS.clear()
    patf = research.extract_pattern("https://blog.example.com/empty-raw-post")
    check("fallback extract_pattern → not None", bool(patf))
    check("fallback reads firecrawl markdown", patf and "Fallback article body" in patf["text"])
    check("fallback used a non-raw firecrawl re-scrape",
          {"script": "firecrawl.py", "args": ["scrape", "https://blog.example.com/empty-raw-post"]}
          in [{"script": c["script"], "args": c["args"]} for c in CALLS])
    check("fallback never called blotato", "blotato.py" not in scripts_called())

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
