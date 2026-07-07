#!/usr/bin/env python3
"""
catch_approvals.py — capture Devon's (@ceo_tg) 👍 picks as a SHORTLIST.

Supervised-mode capture. A 👍 from Devon (CEO) = approved and WILL be posted — but NOT
immediately: we compile/organize his picks + comments, then assign a proper slot + date and
schedule under supervision. This script only CAPTURES — it never writes a publish sign-off
(qc.json), never schedules, never posts; it only WRITES to the shortlist file below.

How it reads Telegram (deliberately non-destructive):
  • getUpdates is called WITHOUT an offset, so updates are NEVER confirmed/cleared.
    The engine's approvals_offset.json and the server-side queue are left untouched;
    we just observe and de-dupe by update_id in our own state file. (Only loss risk is
    Telegram's own 24h retention — so poll within a day of when Devon taps.)
  • Subscribes to message_reaction too (the bot is a group admin), so native 👍 reactions
    are visible as well as 👍 sent as a reply-message (what Devon used on 06-24).

Mapping a 👍 to a job:
  • reply-👍 message  → the AEVA id is read from the replied-to card's caption.  ✅ reliable
  • native reaction   → carries only message_id, NOT the card text, so it can't be mapped
                        to a job without a message_id→job map (we don't keep one yet). These
                        are logged under "unmapped_reactions" so nothing is silently dropped.

Buckets: pre-070i = ACME-NNN (no suffix); post-070i = ACME-NNNi.

Usage:
    python3 catch_approvals.py --once                 # single poll, write, exit
    python3 catch_approvals.py --minutes 50           # watch for 50 min, poll every 30s
"""
from __future__ import annotations
import argparse, json, re, time
from datetime import datetime, timezone
import engine as e

API = "https://api.telegram.org/bot{token}/{method}"
WATCH_USER = "ceo_tg"                       # Devon
STORE = e.ENGINE_DIR / "devon_shortlist.json"
STORE_MD = e.ENGINE_DIR / "devon_shortlist.md"

AEVA = re.compile(r"ACME-\d+[a-z]?", re.I)
THUMBS = ("👍", "👍👍", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿")
AFFIRM = {"ok", "yes", "good", "approved", "good to go"}     # soft yes (logged, flagged)
REJECT = re.compile(r"\b(reject|no\b|don'?t|do not)\b", re.I)
EDIT_HINT = re.compile(r"\b(can you|need|needs|change|make|add|video|animat|border|advise)\b", re.I)


def _norm_job(s: str) -> str:
    return re.sub(r"([A-Za-z])$", lambda m: m.group(1).lower(), s.upper())


def _bucket(job: str) -> str:
    return "post070i" if re.fullmatch(r"ACME-\d+[a-z]", job) else "pre070i"


def _load() -> dict:
    d = e.load_json(STORE) if STORE.exists() else None
    if not isinstance(d, dict):
        d = {}
    d.setdefault("picks", {})          # job -> {at, signal, via, update_id, raw}
    d.setdefault("rejects", {})        # job -> {...}
    d.setdefault("edits", {})          # job -> {...}
    d.setdefault("unmapped_reactions", [])
    d.setdefault("seen_update_ids", [])
    d.setdefault("live_status", {})    # job -> human note: already posted / scheduled in Blotato
    return d


def _save(d: dict) -> None:
    d["updated_at"] = e.now_iso()
    e.ENGINE_DIR.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2))
    _write_md(d)


def _write_md(d: dict) -> None:
    def ids(bucket_key, sect):
        return sorted(j for j, v in d[sect].items() if _bucket(j) == bucket_key)
    lines = [f"# Devon (@ceo_tg · CEO) approvals — 👍 = approved to post, QUEUED for scheduling (slot+date); not auto-posted",
             f"_updated {d.get('updated_at','')}_", ""]
    if d.get("live_status"):
        lines += ["## 🚀 Already live / scheduled — DO NOT re-schedule", ""]
        for j in sorted(d["live_status"]):
            lines.append(f"- **{j}** — {d['live_status'][j]}")
        lines += [""]
    for label, key in (("pre-070i (recycle, ACME-0NN)", "pre070i"),
                       ("post-070i (ACME-0NNi)", "post070i")):
        lines += [f"## {label}", ""]
        ap = ids(key, "picks")
        lines.append(f"**✅ 👍 shortlisted ({len(ap)}):** " + (", ".join(ap) if ap else "—"))
        ed = ids(key, "edits")
        if ed:
            lines.append("")
            lines.append(f"**✏️ edits requested ({len(ed)}):**")
            for j in ed:
                lines.append(f"- {j}: {d['edits'][j].get('raw','')}")
        rj = ids(key, "rejects")
        if rj:
            lines.append("")
            lines.append(f"**❌ rejected ({len(rj)}):**")
            for j in rj:
                lines.append(f"- {j}: {d['rejects'][j].get('raw','')}")
        lines.append("")
    if d["unmapped_reactions"]:
        lines += ["## ⚠️ native reactions (need message_id→job map to attribute)", ""]
        for r in d["unmapped_reactions"][-20:]:
            lines.append(f"- msg {r['message_id']} {r['emoji']} @ {r['at']}")
    STORE_MD.write_text("\n".join(lines))


def _classify(txt: str, rep_txt: str):
    """Return (kind, job, raw) for a ceo_tg text/reply message. kind in pick/edit/reject/None."""
    m = AEVA.search(txt) or AEVA.search(rep_txt)
    job = _norm_job(m.group(0)) if m else None
    low = txt.strip().lower()
    has_thumb = any(t in txt for t in THUMBS)
    if not job:
        return None, None, txt
    if EDIT_HINT.search(txt) and not has_thumb:
        return "edit", job, txt
    if REJECT.search(txt) and not has_thumb:
        return "reject", job, txt
    if has_thumb or low in AFFIRM:
        return "pick", job, txt
    return None, job, txt


def poll_once(d: dict) -> int:
    tok = e.load_env("ENGINE_TELEGRAM_BOT_TOKEN")
    import requests
    r = requests.get(API.format(token=tok, method="getUpdates"),
                     params={"timeout": 0,
                             "allowed_updates": json.dumps(
                                 ["message", "channel_post", "message_reaction"])},
                     timeout=30, verify=e.tls_verify())
    ups = r.json().get("result", []) if r.status_code == 200 else []
    seen = set(d["seen_update_ids"])
    new = 0
    for u in ups:
        uid = u.get("update_id")
        if uid in seen:
            continue
        # native reaction
        if "message_reaction" in u:
            mr = u["message_reaction"]
            usr = (mr.get("user") or {})
            if (usr.get("username") or usr.get("first_name")) == WATCH_USER:
                if any((x.get("emoji") in THUMBS) for x in mr.get("new_reaction", [])):
                    d["unmapped_reactions"].append({
                        "message_id": mr.get("message_id"),
                        "emoji": "👍",
                        "at": e.now_iso(), "update_id": uid})
                    new += 1
            seen.add(uid); d["seen_update_ids"].append(uid)
            continue
        msg = u.get("message") or u.get("channel_post") or {}
        frm = (msg.get("from") or {})
        if (frm.get("username") or frm.get("first_name")) != WATCH_USER:
            seen.add(uid); d["seen_update_ids"].append(uid)
            continue
        txt = (msg.get("text") or msg.get("caption") or "").strip()
        rep = (msg.get("reply_to_message") or {})
        rep_txt = rep.get("caption") or rep.get("text") or ""
        kind, job, raw = _classify(txt, rep_txt)
        rec = {"at": e.now_iso(), "via": "reply" if rep_txt else "message",
               "update_id": uid, "raw": raw[:200]}
        if kind == "pick" and job:
            d["picks"][job] = rec
            d["rejects"].pop(job, None); d["edits"].pop(job, None)   # 👍 wins / supersedes
            new += 1
        elif kind == "edit" and job:
            if job not in d["picks"]:
                d["edits"][job] = rec; new += 1
        elif kind == "reject" and job:
            d["rejects"][job] = rec
            d["picks"].pop(job, None); new += 1
        seen.add(uid); d["seen_update_ids"].append(uid)
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--minutes", type=float, default=50)
    ap.add_argument("--interval", type=float, default=30)
    a = ap.parse_args()
    d = _load()
    if a.once:
        n = poll_once(d); _save(d)
        print(f"poll: {n} new signal(s). picks={len(d['picks'])} edits={len(d['edits'])} "
              f"rejects={len(d['rejects'])} -> {STORE}")
        return
    deadline = time.time() + a.minutes * 60
    total = 0
    while time.time() < deadline:
        try:
            n = poll_once(d)
            if n:
                total += n; _save(d)
                print(f"[{datetime.now(timezone.utc):%H:%M:%S}] +{n} new (total {total})", flush=True)
        except Exception as ex:                    # never die on a transient network blip
            print(f"poll error (continuing): {ex}", flush=True)
        time.sleep(a.interval)
    _save(d)
    print(f"watch ended. total new this run={total}. picks={len(d['picks'])} "
          f"edits={len(d['edits'])} rejects={len(d['rejects'])} -> {STORE}")


if __name__ == "__main__":
    main()
