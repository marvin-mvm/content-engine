# Acme Content Engine — Operational Guide

> **Lineage.** This is **Devon's Implementation Guide v1.0** (For: Marvin · June 2026) — its
> *strategy* preserved in full, **reconfigured to the Acme / Claude-Code stack** we actually
> run. Devon's strategy holds; his proposed plumbing (Creatomate, Trigger.dev) is dropped and
> replaced with our tools. Source PDF: **[docs/Devon-Implementation-Guide-v1.0.pdf](docs/Devon-Implementation-Guide-v1.0.pdf)**
> (the original 25-page doc, with all tables). §0 = exactly what changed.
>
> **Source-of-truth split:** brand hard-rules (palette, fonts, the verbatim IMAGE/VIDEO prompt
> blocks, RUO, formats) → **[SOUL.md](SOUL.md)** (not duplicated here). Build status + sequencing
> → **[MIGRATION.md](MIGRATION.md)**. Production/publish recipes → **[PIPELINE_RUNBOOK.md](PIPELINE_RUNBOOK.md)**.
> This file = the *strategy + operational* layer.
>
> **GOAL (Devon):** 100,000 organic followers across **Instagram + TikTok** in 6 months via a
> self-improving engine posting **5×/day**. The difference between 6 vs 18 months: (1) content
> quality in the first 60 days, (2) **save rate** on Stack + Science, (3) **consistency — no
> missed days ever**.

---

## 0. What changed from Devon's v1.0 → our stack (the reconfiguration)

| Devon's v1.0 | Our stack | Why |
|---|---|---|
| **Creatomate** (visuals) | **HyperFrames + produce.py + Higgsfield** (M3–M5) | Our core renders brand-correct assets with synced captions Creatomate can't match. The point of the migration. |
| **Trigger.dev** (orchestration) | **Claude Code + macOS launchd** (F4) | A cloud runner can't call our local Higgsfield CLI / ffmpeg / HyperFrames / Playwright. The visual stage is local-only by necessity. |
| **Claude API direct** (Sonnet 4.5/4.6) | **OpenRouter** via `copywriter.py` | Same models, already wired + brand-voice/compliance enforced. |
| **Supabase** (8 tables + storage) | **Supabase** ✅ adopted (system-of-record) | Right tool for the relational scoring/feedback work. *Provisioning still pending.* |
| **Blotato** (publish) | **Blotato** ✅ via `publish.py` (F1, built) | Same tool, wrapped with a hard compliance gate. |
| **Apify / SearchAPI** | **apify.py / searchapi.py** ✅ + **firecrawl.py** added | Same approach; firecrawl added for full article scrapes. |
| **React + Supabase dashboard** | **Supabase Studio + query via Claude Code** | We don't need a custom React app to start; Studio + ad-hoc queries cover review. |
| **Physician quote / validation** (Pillars 4, Stage 3) | **❌ NEVER an Acme physician.** Social proof = **third-party published research framed as external** | Legally conservative line (Marvin). The engine never cites/names/implies a physician acting for Acme. |
| **Apify scrapes Devon's saved IG daily** | **Drop-a-link inbox** (Marvin/Devon paste viral URLs) **+ auto-mine YT/TikTok/Reddit** | Saved-IG scraping has no clean API + risks the account. Auto-mine where robust; human-curate the rest. |
| **Telegram = hard daily gate** | **Telegram (F2), built LAST.** Until then review is in Claude Code / job folders; trust-score ramp (SOUL §15) governs auto-publish. | Same A/R/E flow, sequenced last in our build order. |

**Unchanged hard rule:** **Labs content runs ORGANIC ONLY — never paid. Paid media is Acme
Health only.** The engine serves both brands; only Health can run paid.

---

## 1. Who we are talking to — the 3 personas (the targeting filter)

Every brief is **tagged with one persona before generation**. *(Now backfilled from the PDF —
these tables were blank in the text paste.)*

### P1 — The Optimizer (PRIMARY)
| | |
|---|---|
| Who they are | Male, 38–52. Founder, finance exec, tech operator, professional services |
| Income | Household $250K–$500K+ |
| Annual health spend | $15,000–$25,000 across longevity stack |
| Entry point | Acme Labs (peptides, hormone optimization) |
| Lifetime value | $8,000–$15,000 over 24 months |
| What they want | Best outcomes, integrated stack, time efficiency, data they understand |
| What they reject | Low-trust operators, inconsistent quality, fragmented experiences |
| Where online | Instagram, X/Twitter, LinkedIn, podcasts |
| Converts on | Protocol breakdowns, stack science, performance data, ROI framing |
| Conversion path | Labs → Curriculum → Health intake → Annual membership |

### P2 — The Health-Forward Affluent Woman (SECONDARY)
| | |
|---|---|
| Who they are | Female, 35–55. Professional, entrepreneur, or affluent home executive |
| Income | Household $200,000–$400,000 |
| Annual health spend | $8,000–$18,000, weighted toward functional medicine |
| Entry point | Acme Health intake program, curriculum content |
| Lifetime value | $10,000–$20,000 over 24 months |
| What they want | Hormone optimisation, longevity, family-history-aware preventative care |
| What they reject | Bro-coded biohacker content, transactional medicine, gendered dismissal |
| Where online | Instagram, TikTok, Pinterest, Substack newsletters |
| Converts on | Clean science, hormone health, aesthetic-longevity, functional-medicine angles |
| Conversion path | Content → Health waitlist → Intake → Quarterly programs → Annual |

### P3 — The Curious Newcomer
| | |
|---|---|
| Who they are | Either gender, 30–45. Mid-career professional, GLP-1 curious, recently engaged |
| Income | Household $150,000–$300,000 |
| Annual health spend | $3,000–$8,000, growing |
| Entry point | Acme Labs single product or content engagement |
| Lifetime value | $2,000–$6,000 over 24 months |
| What they want | Education, gradual onboarding, lower-commitment entry points |
| What they reject | $5,000-quarter pricing, complex protocols, assumed baseline knowledge |
| Where online | TikTok, Instagram Reels, YouTube Shorts, Reddit |
| Converts on | Beginner explainers, "I tried this" formats, transformations, myth-busting |
| Conversion path | Content → Single product → Stack bundle → Curriculum → Health upgrade |

**SYSTEM RULE:** every brief is tagged with its persona before generation. Optimizer → data-dense
ROI language; Newcomer → plain English + curiosity hooks; Affluent Woman → aspirational/premium.

---

## 2. The five content pillars (one post per pillar per day)

| # | Pillar · slot PT | Persona | Function | Our templates |
|---|---|---|---|---|
| 1 | **Science Simplified** · 08:00 | All | Discovery + Trust (credibility engine) | `carousel-*`, `static-callout-*`, `static-compound-*`, `story-reel-*` |
| 2 | **Stack of the Day** · 11:00 | P1, P3 | Conversion — **SAVE-RATE is the KPI** | `carousel-*`, `static-compound-*` |
| 3 | **Trending Hook** · 13:00 | P3, P2 | Reach/Discovery — clone winning **format** | `story-reel-*`, `carousel-*` |
| 4 | **Social Proof & Results** · 16:00 | All | Conversion closer | `carousel-*`, `static-callout-*` |
| 5 | **Founder POV** · 19:00 | P1 | Authority + Retention (most shareable) | `story-reel-*` (text), `carousel-*` |

- **P1 Science** — research explainers ("5 things BPC-157 does, with citations"; "NAD+ decline after 40"). Hooks: *"Most people taking [X] are doing it wrong…"* · *"We looked at 47 studies on [X]…"*
- **P2 Stack** — stacks w/ research dosing *context*, timing, synergies (text-on-screen, no face). Hooks: *"The 4-compound stack every high-performance founder is quietly running."*
- **P3 Trending Hook** — **clone the FORMAT not the content** of viral niche posts → Acme voice. The growth engine. Format types: This-or-That, myth-bust "Stop X / Start Y", "things I wish I knew before [X]", controversial takes, reaction-to-study. *(Sourcing = our drop-a-link + auto-mine, §5 Stage 1.)*
- **P4 Social Proof** — early stage = research outcomes + frameworks + anonymised case studies. ⚠️ **OUR OVERRIDE:** never a physician quote/validation; social proof = external published research only.
- **P5 Founder POV** — opinion/POV from authority, no face. Voice: authoritative not arrogant, confident not clinical, never preachy/corporate/generic-wellness.

---

## 3. Calendar & posting schedule

**5 posts/day × 7 days = 35/week.** Rolling 7-day calendar built Sunday night, reviewed Monday
via Telegram.

### 3.1 Daily schedule (Devon's Stage 6 routing)
| Time PT | Pillar | Format | Persona | Platforms (target) |
|---|---|---|---|---|
| 08:00 | Science Simplified | Carousel / Single graphic | All | IG · TikTok · X |
| 11:00 | Stack of the Day | Carousel / Graphic | P1 + P3 | IG · TikTok |
| 13:00 | Trending Hook | Reel / Carousel | P3 + P2 | IG · TikTok |
| 16:00 | Social Proof | Carousel / Quote card | All | IG · X · Threads |
| 19:00 | Founder POV | Quote card / Reel | P1 | IG · X |

> ⚠️ **Reality now:** IG / Threads / Facebook **not connected** (Meta accounts under review) →
> `publish.py` posts only the **X + TikTok** legs and skips the rest with a warning. The table is
> the target once Meta is healthy.
>
> 🔴 **The "Reel" slots above are NOT daily** — video runs on **alternating days only** (≤1 reel/
> day). On a non-video day those slots ship a 0-credit image instead. See **§3.2 / §3.5**.

### 3.2 Weekly content-mix rotation (format per pillar per day)

> 🔴 **OVERRIDE — VIDEO RUNS ON ALTERNATING DAYS, NOT DAILY (Marvin 2026-06-19).** Devon's
> original grid below fired video reels up to 4 days/week (and twice on some days). At the real
> Higgsfield price — **a reel ≈ 135 credits** (3 stitched 10s clips × ~45) — daily video would
> cost ~4,050 credits/month and blow the **Ultra plan's 3,000-credit/month** allotment. So:
>
> - **Video (type=reel) is produced every OTHER calendar day**, 7-day week, never two days in a
>   row, alternating across week boundaries (engine `is_video_day()`, anchored to Mon 2026-06-22;
>   override `.env ENGINE_VIDEO_ANCHOR`). On a **non-video day, NO reel is produced** — every
>   pillar ships a 0-credit image/carousel/text-reel instead.
> - On a **video day, exactly ONE pillar carries the reel**, alternating **Trending ↔ Science**
>   across video days (`research.reel_pillar_today()`). At most **1 reel/day**.
> - Budget math: ~15 video-days/mo × 1 reel × 135 ≈ **2,025 credits/mo on video**, leaving ~975
>   for rejected-reel re-gens + image generation (see §3.5). Daily video (≈30 reels) ≈ 4,050 = over.
>
> The table below is the *format intent per pillar*; wherever it says **Reel**, that reel only
> fires if today is this pillar's video day (otherwise the pillar's non-reel format is used).

| Pillar | Mon | Tue | Wed | Thu | Fri | Sat | Sun |
|---|---|---|---|---|---|---|---|
| Science Simplified | Carousel | Single | Reel¹ | Carousel | Single | Carousel | Reel¹ |
| Stack of the Day | Carousel | Graphic | Carousel | Compare | Carousel | Graphic | Carousel |
| Trending Hook | Reel¹ | Carousel | Reel¹ | This/That | Reel¹ | Myth-bust | Reel¹ |
| Social Proof | Framework | Biomarker | Case Study | Quote | Framework | Outcome | Community Q |
| Founder POV | Opinion | Contrarian | Quote Card | Industry | Philosophy | Build Story | Hot Take |

> ¹ **Reel only on this pillar's alternating video day** (≤1 reel/day total). On any other day the
> "Reel" cell falls back to that pillar's image format (Trending → Carousel, Science → Carousel).

### 3.3 Monthly themes (overlaid on the daily pillars; in `content_strategy_config`)
| Month | Theme | Hero compound focus | Lead-magnet tie-in |
|---|---|---|---|
| 1 | The Foundation — what optimisation actually means | BPC-157, NAD+, Semaglutide | Biological Age Quiz |
| 2 | The Stack — building your personal protocol | Peptide stacks, GLP-1 combos | Stack Builder Tool |
| 3 | The Data — measuring what matters | Biomarker tracking, labs | Free Biomarker Guide |
| 4 | The Upgrade — going deeper | Advanced protocols, Health intake | Founding Member Pre-sale |
| 5 | The Community — what members achieve | Community results, case studies | Member testimonials |
| 6 | The System — the full Acme method | Full stack curriculum | Annual program launch |

### 3.4 Platform rules (enforced in `copywriter.py --platform`, SOUL §6)
- **Instagram** — carousels 5–10 slides (slide 1 hook, last CTA); reels 15–45s, hook in 2s, text on screen; caption = hook + 2–3 short paragraphs + CTA + 20–30 hashtags; reshare to Stories within 1h; bio link → acmehealth.co or acmelabs.co by content type.
- **TikTok** — same video, TikTok-native (no watermark), 3–5 targeted hashtags, text hook on first frame.
- **X/Twitter** — quote cards + strong opinion only (not all 5); thread for Science (each carousel slide → a tweet); **0 hashtags**; reply-engage within 2h.
- **Threads** — Social Proof + Founder POV only; short punchy repurpose of the IG caption.

### 3.5 Credit budget & generator routing (Ultra plan — Marvin 2026-06-19)
**Monthly ceiling: 3,000 Higgsfield credits (Ultra).** The engine protects it on three fronts:

1. **Video = alternating days, ≤1 reel/day** (§3.2). ~15 reels/mo × ~135 ≈ **2,025 credits/mo**.
2. **Rejection allowance.** A rejected reel must be re-generated, so budget a buffer — assume up
   to ~20% of reels bounce: ~3 re-gens/mo × 135 ≈ **~400 credits/mo** held back. (2,025 + 400 ≈
   2,425, leaving ~575/mo for image generation.) Concept approval **before** any spend (GATE 1)
   keeps most rejections free — only a *final*-gate rejection of an already-generated reel costs.
3. **Image generator rotation — ~80% Higgsfield / ~20% Blotato.** Most images render locally at
   **0 credits** (carousels/statics/text-reels via `post.py`, `bg_policy: plain|reuse`). When an
   image truly needs a *generated* background, the engine spreads the spend on a **rolling 4:1**:
   **4 of every 5 → Higgsfield, the 5th → Blotato** (its own quota), to conserve Higgsfield credits.
   This is `engine.image_source()` (a persisted rolling counter — a true 4:1, not random), consumed
   by `produce.py --bg-prompt` (`--bg-source auto`). **Activation:** set `.env BLOTATO_IMAGE_TEMPLATE_ID`
   to a Blotato image template; until then the 5th image safely falls back to Higgsfield (logged).
   Tune the ratio with `.env ENGINE_IMAGE_BLOTATO_EVERY` (default 5 = 1-in-5).

Hard daily backstop (independent of the above): `engine.py` `reel` cap = **135 real credits/day**
+ a live-wallet gate (refuse if the Higgsfield balance is short). See `reel_video.py`.

### 3.6 Reel approval & publishing — the TWO gates (Marvin 2026-06-23)

A reel/video is a **two-approval** flow (images are single-approval — just the posting one):

1. **GATE 1 — concept/script.** The concept card (spoken script + b-roll prompts) goes to Telegram
   *before* any spend. `APPROVE` → `concept_approved`; **trust-neutral**, spends nothing, only
   **unlocks generation** (`status==awaiting_concept` routes A/R/E to the concept gate).
2. **Generation.** `produce_daily.py reel` (RV3 Seedance/Kling b-roll → RV4 TTS+captions → render)
   pushes the finished **video** to Telegram → `status=pushed`.
3. **GATE 2 — posting.** You review the actual rendered reel; `APPROVE` writes the publish sign-off
   (`qc.json`), advances to `approved`, and **slots it** at its pillar slot.
4. **Publish.** `publish_slot.py` posts it to Blotato (x, tiktok) **at the slot**, exactly like an
   image (dry-run until `output/GO_LIVE`).

Two guards make this safe:
- **No premature posting APPROVE (the double-APPROVE fix).** `approvals.apply_command` refuses a
  final-gate `APPROVE` on a `type=reel` unless `status=="pushed"` **and** a render exists
  (`{job}-final.mp4`/`captioned.mp4`). A 2nd APPROVE on a concept-approved-but-un-generated reel can
  no longer write `qc.json` / mark it `approved`.
- **Reels now auto-publish like images** (supersedes "reels are manual-only / out of the auto-publish
  loop"): `engine.ensure_slotted_in_manifest` slots reels and `publish_slot.collect_due` includes them.

---

## 4. Tech stack (Devon's proposal → ours)

| Layer | Devon's tool (est. cost) | **Our tool** |
|---|---|---|
| Orchestration | Trigger.dev ($29–99) | **Claude Code + launchd** (F4) |
| Database | Supabase ($25) | **Supabase** ✅ |
| Social scraping | Apify ($50–100) | **apify.py** ✅ |
| Trend intel | SearchAPI ($50) | **searchapi.py** ✅ (+ **firecrawl.py**) |
| AI generation | Claude API Sonnet ($50–150) | **OpenRouter** via `copywriter.py` |
| Visual production | Creatomate ($39–99) | **HyperFrames + produce.py + Higgsfield** |
| Publishing | Blotato (active) | **publish.py → Blotato** ✅ |
| Review gate | Telegram bot (free) | **Telegram** (F2, last) |
| Analytics scraping | Apify (incl.) | **apify.py** scrape-back |
| Dashboard | React + Supabase | **Supabase Studio + Claude Code queries** |

Devon's est. total **~$250–550/month**. (Ours differs: no Creatomate/Trigger.dev; add Higgsfield
credits as a managed lever; OpenRouter instead of Anthropic-direct.)

---

## 5. Pipeline — Devon's 8 stages → our modules + the Supabase output each writes

| Stage (Devon) | Runs | Our module | Writes (Supabase) | Status |
|---|---|---|---|---|
| **1 · DISCOVER** | 06:00 | `research.py` sweep (apify/searchapi/firecrawl): viral-outlier mining + topic discovery. **Sundays = bank-first** (`serve_bank_day` reuses the week's banked angles before any external search; used angles are archived + removed) | `discovery_queue` | **F3 — next** |
| **2 · SCORE & SELECT** | 06:30 | `research.py` scoring → top 5 (one/pillar) → `brief.json` files | `daily_brief` | **F3 — next** |
| **3 · GENERATE** | 07:00 | `copywriter.py` (caption + overlay tokens + hashtags + platform variants) → **text draft** (`draft.md`) | `content_drafts` | copywriter.py ✅; per-job M2 |
| **3.5 · DEDUP GATE** | inline | `dedup.py` — compare the draft to the last-7-day approved/produced posts + REJECTED; surgically revise any near-duplicate hook/body/script (follow-ups pass); fail-open | `content_drafts` (revised) | ✅ Marvin 2026-06-22 |
| **4 · TELEGRAM REVIEW** | 08:00 | `telegram.py` + `approvals.py` (A/R/E); card shows `♻️ Dedup:` on auto-revise | `approved_drafts` / `content_drafts.status` | **F2 — last** |
| **5 · PRODUCE VISUALS** | post-approval | `produce.py`/`reel.py`/`post.py` + HyperFrames (**not Creatomate**) | `ready_to_publish` | ✅ built (A1–A5) |
| **6 · SCHEDULE & PUBLISH** | staggered | `publish.py` → Blotato (per §3.1 routing) | `published_posts` | ✅ **F1 built** |
| **7 · MEASURE** | 23:00 | `apify.py` scrape-back (after 12–16h) | `performance_data` | F4-era backfill |
| **8 · FEEDBACK LOOP** | midnight | weekly weighted-scoring updater | `content_strategy_config` | **F5** (lite, needs data) |

**Stage 1 sources (our version):** auto-mine YouTube (`searchapi`), TikTok + Reddit (`apify`)
for posts *far above baseline* engagement (velocity + per-follower, not raw views) — subreddits
r/Peptides, r/longevity, r/Biohackers, r/nootropics; hashtag seed set #longevity #biohacking
#peptides #GLP1 #NADplus #healthoptimization #antiaging #performanceoptimization #functionalmed
#longevitylifestyle #biologicalage #hormonehealth #peptidetherapy #longevityhacks. **Plus** the
drop-a-link inbox (any URL → social/video via `apify.py scrape`, article/blog via `firecrawl.py scrape` → hook + structure).

**Sourcing doctrine — the 3-step method (Marvin 2026-06-21; full version acme-engine REFERENCE §8.1):**
don't mine topic-nouns and hope — mine the *framings* that go viral, because those are the ones we can
win. **(1) Outlier:** rank by **velocity vs the niche-baseline median**, never raw views; outlier = ≥2×,
bigger ratio = louder signal. **(2) Throughline:** name the ONE narrative the niche is circling now —
ours is **"the hype is outrunning the evidence"** (celebrity buzz vs. what studies show); clone the
throughline, not one post. **(3) Edge/filter:** Acme *is* the evidence side (COA + RUO + sourced), so
keep only outliers we can answer with **data** (myth-bust / "what it actually does" / "X vs Y" / "the part
nobody mentions") and **reject anything needing an outcome claim**; clone the hook STRUCTURE
(`FORMAT_ARCHETYPES`) into an Acme-owned topic, body stays rigorous. The lead `OUTLIER_YT_QUERIES` and
the throughline statement are a mid-2026 snapshot — refresh them as the conversation shifts.

**Stage 2 scoring — viral opportunities (Mode B, Devon):** niche fit (1–10) · persona fit (1–10) ·
format adaptability (1–10) · buyer-intent (1–10) · recency +2 (<24h) · curated-link +3.
**Topic scoring (Mode A, SOUL §8):** trending 0.25 · comment-bait 0.20 · search 0.20 ·
educational 0.15 · product-tie 0.10 · recency 0.10. Both print their breakdown.

**Stage 3 GENERATE produces (per brief):** hook (first line/frame — most important) · full
caption (hook + 2–3 paras + CTA + compliance footer) · hashtags (25 IG / 3–5 TikTok / 0 X) ·
carousel slide copy (headline + 3 bullets/slide) · visual direction (template, overlay, image
description) · platform variants. CTA links **acmehealth.co OR acmelabs.co — never both**.

---

## 6. Supabase schema — the **8 tables** (build before the pipeline depends on them)

*(Backfilled with exact fields from the PDF. Note: Devon has **8** tables — `approved_drafts` is
separate from `content_drafts`. We may fold approval into `content_drafts.status` + `review_notes`
— a data-layer design call.)*

| Table | Key fields | Purpose |
|---|---|---|
| `discovery_queue` | id, source_url, platform, caption, engagement_rate, save_count, share_count, content_type, format_type, scraped_at | Raw scraped content (Stage 1) |
| `daily_brief` | id, pillar, persona_target, source_url, format_type, hook_angle, scoring_breakdown, created_at | 5 selected briefs/day (Stage 2) |
| `content_drafts` | id, brief_id, pillar, persona, brand, hook, caption, hashtags, slide_copy, visual_direction, platform_variants (JSON), status, review_notes | Generated copy (Stage 3) |
| `approved_drafts` | id, draft_id, approved_at, marvin_notes | Approved content (Stage 4) |
| `ready_to_publish` | id, draft_id, asset_url, asset_type, platform, scheduled_time, status | Copy + visual asset ready (Stage 6) |
| `published_posts` | id, draft_id, platform, published_at, platform_post_id, pillar, persona, brand | Live posts reference table |
| `performance_data` | id, post_id, likes, comments, shares, saves, reach, impressions, profile_visits, link_clicks, engagement_rate, save_rate, share_rate, composite_score, pillar, persona, format_type, brand, recorded_at | Engagement data (Stage 7) |
| `content_strategy_config` | id, pillar_weights (JSON), format_preferences (JSON), topic_boosts (JSON), hook_patterns (JSON), persona_weights (JSON), updated_at | Feedback-loop output (Stage 8) |

> **Sequencing:** Supabase is **additive during the build** — new modules log to it; shared
> OpenClaw scripts keep their Google-Sheet path until cutover (F6), then the Sheet is dropped.
> *Not yet provisioned — a Marvin/Devon setup step (Supabase project `acme-content-engine`).*

---

## 7. Build order — Devon's Weeks 1–4 (25 tasks) → our phases + status

| Devon's week / task | Our phase | Status |
|---|---|---|
| **W1** — Supabase tables · Apify hashtag + saved-IG scrapers · SearchAPI Reddit/X · wire to `discovery_queue` | Data layer + **F3** | ⬜ next (Supabase pending; saved-IG → drop-a-link) |
| **W2** — Stage 2 scoring · Stage 3 generation · Telegram bot + Stage 4 review · test 1–4 | M1–M2 (`research.py`/`copywriter.py`) ✅ partial · **F2** Telegram ⬜ | partial |
| **W3** — 5 brand templates · Stage 5 production · confirm Blotato 4 platforms · Stage 6 publish · first test week | A1–A6 ✅ (HyperFrames, **not Creatomate**) · **F1** ✅ | **done** (templates exist; Blotato = X/TikTok now, Meta pending) |
| **W4** — Apify post-publish scraper · Stage 8 feedback · wire weights into scoring · weekly report · dashboard · go-live | **F5** ⬜ · Supabase Studio (no React app) | ⬜ later |

**Our actual phase status:** A0 safety · A1 reel chain · A2 reel.py · A3 image/post.py · A4
preflight · A5 first live-fire · A6 skills · **F1 publishing** — all ✅. **Next:** F3 research →
F4 scheduling → F2 Telegram → F5 feedback → F6 cutover. (Full detail in [MIGRATION.md](MIGRATION.md).)

---

## 8. Growth targets, milestones & KPIs

| Milestone | Target | Key driver |
|---|---|---|
| End of Month 1 | 1,000–3,000 followers | System live; quality establishing; Trending Hook driving reach |
| End of Month 2 | 5,000–10,000 | Feedback loop improving; Stack + Science building save rate |
| End of Month 3 | 15,000–25,000 | Compounding; algorithm rewarding save rate |
| End of Month 4 | 35,000–55,000 | Viral content more frequent; monthly theme arc retaining |
| End of Month 5 | 60,000–80,000 | Social proof converting; community content starting |
| End of Month 6 | **100,000+** | Full compound effect; 6 months of performance data optimising daily |

**Weekly KPIs Marvin tracks** (Month 1 → 3 → 6):
| KPI | M1 | M3 | M6 |
|---|---|---|---|
| Posts published / week | 35 | 35 | 35 |
| Avg engagement rate (IG) | 3%+ | 5%+ | 7%+ |
| **Avg save rate (IG)** | 1%+ | 2.5%+ | 4%+ |
| **Avg share rate (TikTok)** | 2%+ | 4%+ | 6%+ |
| Follower growth / week | 100–300 | 500–1,000 | 2,000–5,000 |
| Profile visits from content | 500+ | 2,000+ | 10,000+ |
| Link-in-bio clicks | 50+ | 300+ | 1,500+ |

**Calculated scores:** engagement rate = (likes+comments+shares+saves)/reach · **save rate =
saves/reach (most important for IG)** · **share rate = shares/reach (most important for TikTok)** ·
composite 1–10 vs pillar benchmark.

---

## 9. Compliance — non-negotiable (hardcoded + manually checked)

Full hard-rules in **[SOUL.md](SOUL.md) §12/§21**; `copywriter.py` + `publish.py` enforce them.

**All content (Labs + Health):** never "treats / cures / heals / fixes / prevents / proven to /
guaranteed"; educational framing only ("research suggests", "studies indicate", "protocols used
by"); no medical before/after; no specific patient outcomes unless anonymous/non-identifying;
never target under-18s. **Never imply a physician acting for Acme** (our override — §0).

**Acme Labs:** caption footer **"For research use only — not for human consumption."** (canonical
in `copywriter.py` = `RUO · NOT FOR HUMAN CONSUMPTION`); **organic only, NEVER paid**; no human-use
implication; no influencer/celebrity use claims; no weight-loss/condition targeting.

**Acme Health:** physician-*oversight* framing where applicable (never naming an Acme
physician); **may run paid**; no promised outcomes; GLP-1 content carries no specific human dosing.

**Platform:** IG — no weight-loss before/after; TikTok — aggressive on health, research framing
only; X — most lenient, still no direct medical claims. **When in doubt, cut it out** (reject →
flag Devon).

---

## 10. Accounts & environment (setup checklist)

**Accounts to create/confirm:** Supabase project `acme-content-engine` · Apify (set $100/mo
cap) · SearchAPI (confirm Reddit + X endpoints) · Blotato (confirm IG/TikTok/X/Threads connected
— *Meta currently down*) · Telegram bot via @BotFather, name `AcmeContentBot`. **Dropped from
Devon's list (our stack):** Trigger.dev, Creatomate, Anthropic-direct (→ OpenRouter). **Added:**
Higgsfield, Firecrawl, OpenRouter.

**Env var names** (values live in `.env`, never committed): `SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`, `APIFY_API_TOKEN`, `SEARCHAPI_KEY`, `BLOTATO_API_KEY`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `INSTAGRAM_ACCOUNT_ID` — **plus ours:**
`OPENROUTER_API_KEY`, `FIRECRAWL_API_KEY`, Higgsfield creds. *(Devon's `ANTHROPIC_API_KEY` +
`CREATOMATE_API_KEY` are N/A for our stack.)*

---

*Devon's closing intent: the system runs without him day-to-day; his only touchpoint is the Monday
9am Telegram report. Marvin builds, maintains, and escalates only what can't be resolved —
borderline compliance → reject; bug → fix; 3+ days of significant performance drop → escalate.*
