---
name: acme-engine
description: "Acme Labs autonomous content engine — operation, SOP, compliance, branding, Telegram review, link-drops, feedback. Read this to run or reason about the engine. Full detail in REFERENCE.md."
metadata:
  {
    "openclaw":
      {
        "emoji": "⚙️",
        "requires": { "bins": [] }
      }
  }
---

# acme-engine — operating guide (V1)

The autonomous content engine for **Acme Labs** (RUO research-peptide brand). It runs
**research → content creation → Telegram review → publish**, 5 posts/day, fully local at ~0 cost
except the few Higgsfield videos. This file is the operating stub; **deep detail is in
[REFERENCE.md](REFERENCE.md)** (load it when you need specifics on compliance, templates, modules,
or Telegram commands).

> ## ⚠️ V1 NOTE — what's still missing (honest list — mostly setup steps, not bugs)
> These are **not broken code** — they are setup/decisions left:
> - **Connect Instagram + Threads + Facebook in Blotato** (your step). Today only **X / TikTok /
>   YouTube** publish — so every post currently reaches only those. **Instagram is your #1 goal.**
> - **Turn publishing ON** — it's in safe test-mode until you create `output/GO_LIVE` (and
>   `output/REELS_LIVE` for videos).
> - **Test one real Threads link** (IG + FB are proven; Threads is wired but never run with a real link).
> - **Supabase database** — still using local files (works fine; the v2 plan wants Supabase as the
>   real database — add after go-live).
> - **Measure + feedback loop** — still off on purpose (the "get smarter from results" part).
> - **Monthly themes (§3.3)** — not wired yet (small).
>
> The engine code itself is in good shape: research → 5 pillars + link-drops → templates (all render,
> dark/light, video-in-template) → compliance gate (now stricter) → Telegram review → publish, with
> **failure alerts** so you'll know if anything breaks. The biggest remaining items are the **Blotato
> connections** and **flipping go-live** — those are yours to do.

---

## The one rule that never changes
**Nothing publishes without human approval in Telegram.** The trust score is only a quality signal —
it never bypasses the Telegram gate. (v2 SOP Stage 4 / Task 25; see REFERENCE §Governance.)

## What it does each day (PT, via launchd)
| Time | Job | What happens |
|---|---|---|
| 05:30 | **produce** | fresh research (Sun = bank-first) → write a text draft → **de-duplicate it** vs the last 7 days → write 5 posts (1 per pillar) → render templates (0 credits) |
| 07:00 | **review** | each post is pushed to the Telegram group for approval |
| every 5 min | **approvals** | reads your Telegram replies (Approve/Reject/Revise) + captures dropped links |
| 08/11/13/16/19 | **publish** | publishes each APPROVED post at its slot (dry-run until `output/GO_LIVE`) |

**No more repeats (Marvin 2026-06-22).** Each post is drafted as text first, then checked against the
**last 7 days** of approved + produced posts. A near-duplicate **hook/body/script** is auto-revised in
place (a genuine **follow-up/continuation passes**); the TG card shows `♻️ Dedup:` when it does. Products
rotate on a **7-day window** (no same SKU within a week), and **Sundays** pull from the internal research
**bank** before searching externally. The duplication gate lives in `dedup.py` (`.env ENGINE_DEDUP=0` to
disable). See [REFERENCE.md](REFERENCE.md) §9.

## The 5 pillars (one post each, every day)
`08:00` **Science Simplified** · `11:00` **Stack of the Day** · `13:00` **Trending Hook** ·
`16:00` **Research Spotlight** · `19:00` **Founder POV**. Each post targets **The Optimizer (P1)**
or **The Curious Newcomer (P3)** — both are covered every day. (P2 "Affluent Woman" = future Acme
Health, never targeted here. v2 = Labs-only.)

## Telegram (TG) — your 3 jobs
1. **Approve / Reject / Revise** each post: reply `APPROVE ACME-021`, `REJECT ACME-021 reason`,
   `REVISE ACME-021 your note`. REVISE re-makes the post from your note (images **and** reels). Each
   post arrives as ONE message (card = the image's caption) and the commands are **tap-to-copy** lines.
   - **Reels/video = TWO approvals** (Marvin 2026-06-23): ① `APPROVE` the **concept card** (script +
     prompts) — unlocks generation, spends nothing → ② the engine generates + pushes the finished
     **video**, which you `APPROVE` again to **schedule it to Blotato** at its slot. A posting-APPROVE
     is refused until the reel is actually rendered (closes the double-APPROVE hole). Images = ONE
     approval. Topics rotate the **18 live compounds** (`PRODUCTS.md`); **Melanotan-2 & PT-141 never
     appear in reels** (image/carousel only).
2. **Drop links** for research: paste any IG/TikTok/YouTube/X/Reddit/FB/Threads link — it becomes the
   next **Trending** post. Works for **any** group member.
3. **Alerts**: the engine messages you when something publishes or **fails** (failure alerts are live).

## Non-negotiables (hard gates — see REFERENCE for the full rules)
- **Compliance**: never "treats/cures/heals", never weight-loss promises ("lose 20 lbs", "melts fat"),
  never imply a physician acts for Acme, always RUO footer ("For research use only — not for human
  consumption.") on every Labs post. Framed as research only. The publish gate **blocks** violations.
- **Branding**: forest-green/cream palette only (no white bg, no gold/red/purple); fonts = DM Sans +
  Cormorant Garamond Italic (emphasis) + DM Mono (data). **Dark/light by slot**: morning (science,
  stack) = light, midday/evening (trending, proof, founder) = dark.
- **Governance**: always require Telegram approval (above).

## Viral-outlier sourcing (where the hooks come from — Marvin 2026-06-21)
Don't search topic-nouns and hope. Source every post with this **3-step method** (full version in
[REFERENCE.md](REFERENCE.md) §8.1; encoded in `research.py` `OUTLIER_YT_QUERIES`):
1. **Outlier** — rank by **velocity vs niche-baseline median** (not raw views); outlier = **≥2×**,
   bigger ratio = louder signal (a 37× explainer is category-defining). Mine YouTube/TikTok/Reddit/X + drops.
2. **Throughline** — name the ONE narrative the niche is circling now. Ours (durable): **"the hype is
   outrunning the evidence"** — celebrity buzz (Rogan/BPC-157, Ozempic→tirzepatide) vs. what studies
   show (SURMOUNT-5, the GLP1R variant). Clone the *throughline*, not one post.
3. **Edge (filter)** — Acme **is the evidence side** (COA + RUO + sourced), so we win when the frame
   is "hype vs. evidence." Keep outliers we can answer with **data** (myth-bust / "what it actually
   does" / "X vs Y" / "the part nobody mentions"); **reject anything needing an outcome claim** (off-brand
   *and* a compliance RED). Clone the hook STRUCTURE (`FORMAT_ARCHETYPES`) into an Acme-owned topic.

Refresh the lead queries + the throughline statement as the conversation shifts — they're a mid-2026
snapshot, not a fixed truth.

## Hook doctrine (what makes a post trend — Marvin 2026-06-21)
Every post lives or dies on its **hook** (the headline + the caption's first line). The hook must
**stop the scroll** and sound **human and witty**, never technical or medical:
- **Hook = grade 6–8, plain, witty.** Write it like a smart friend talking. **Never** open with
  jargon, a mechanism, a chemical/Latin name, a receptor, or a percentage — those go in the body.
- **Use a viral pattern:** myth-bust/contradiction ("Everyone's wrong about ___"), a *specific*
  curiosity gap ("What ___ actually does"), a question ("Why is nobody talking about ___?"), or
  plain-truth contrast ("The hype says ___. The studies say ___.").
- **Acme's honest-and-viral angle:** everyone is selling the hype; *we* show the real research
  and the COA. Lead with that tension — it's both on-brand (Research Pharmacist) and scroll-stopping.
- **Wit comes from curiosity + contrast, never exaggeration.** All compliance hard-stops still
  apply: no hype/miracle/cure words, no promised outcomes, RUO on every Labs post. The **body stays
  rigorous and sourced** — only the hook gets the human voice.
- Source the angle from **viral outliers** (YouTube/X/TikTok) — clone the *structure* of what's
  already trending, pour an Acme-owned topic into it. Encoded in `copywriter.py` (BRAND_SYSTEM +
  CAROUSEL_SYSTEM "HOOK DOCTRINE").

## How to give feedback (here or in TG)
- **In TG**: REJECT/REVISE with a reason — the engine records it and **steers future content away from
  rejected angles** (the live learning loop). Drop links to steer topics.
- **Here (Claude Code)**: edit the engine code/config, update `SOUL.md` (brand source of truth), or
  update this skill. To change a rule permanently, change it in code + this skill, not just in chat.

## Run it by hand (common commands)
```bash
python3 produce_daily.py run                 # full morning produce (research → 5 posts → render)
python3 research.py drops --max 1            # turn the next dropped link into a Trending post
python3 approvals.py poll                    # apply Telegram replies + capture link-drops now
python3 publish_slot.py --slot 08:00         # publish that slot's approved posts (dry-run until GO_LIVE)
python3 engine.py                            # status: caps, trust score, today's manifest
touch output/STOP                            # kill-switch: halt the whole loop instantly
```

**Everything else — full pipeline, every module, the complete compliance framework, all templates,
every Telegram command, the reel overlay model, the document hierarchy, and troubleshooting — is in
[REFERENCE.md](REFERENCE.md).**
