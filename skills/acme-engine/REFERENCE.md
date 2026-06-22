# acme-engine — full reference (V1)

The complete operating manual for the Acme Labs autonomous content engine: architecture, SOP,
compliance, branding, templates, Telegram, link-drops, feedback, commands, and troubleshooting.
This is the lazy-loaded companion to `SKILL.md` — load it when you need specifics.

---

## 0. Sources of truth (read order)

| Doc | Governs | Notes |
|---|---|---|
| **`Acme-Content-Engine-v2.pdf`** (~/Documents/Acme) | **Strategy / SOP** | The LIVE SOP — supersedes v1. Personas, pillars, cadence, pipeline, compliance, KPIs. |
| **`assets/Acme Labs Post Overlay Templates/acme-content.md`** | **Format / brand backbone** | Palette, fonts, templates, **dark vs light** rules. |
| **`SOUL.md`** | Consolidated brand + engine spec | The single auto-injected brand source. Edit brand rules HERE. |
| **`compliance.py`** | Claims policy (code) | The one authority for RED/YELLOW/GREEN — edit claim rules HERE. |
| This skill | Operating knowledge | Keep in sync when behavior changes. |

**Reconciliation already locked (2026-06-21):** engine is **Labs-only**; personas = **Optimizer +
Newcomer** only; governance = **always require Telegram approval**; dark/light = **by slot**; tooling =
**Claude Code + launchd + HyperFrames** (not Trigger.dev/Creatomate — Devon-approved in v2).

---

## 1. Architecture — the daily pipeline

Orchestrated by **Claude Code + macOS launchd** (4 jobs). All state is local files under `output/`
(gitignored). Supabase is the planned system-of-record (not yet provisioned — additive later).

| Time (PT) | launchd job | Command | Does |
|---|---|---|---|
| 05:30 | `co.acme.engine.produce` | `produce_daily.py run` | research → 5 pillar briefs + drained link-drops → render templates (0 credits) → captions → manifest |
| 07:00 | `co.acme.engine.review` | `telegram.py push-day` | push each produced post to the Telegram group for approval |
| every 5 min | `co.acme.engine.approvals` | `approvals.py poll` | apply A/R/E replies; capture pasted link-drops |
| 08/11/13/16/19 | `co.acme.engine.publish` | `publish_slot.py` | publish each APPROVED post for that slot (dry-run until `GO_LIVE`) |

`launchd/install.sh` (un)loads them. **Switches (flag files under `output/`):**
- `STOP` — halt the whole loop instantly (`touch output/STOP`; `rm` to resume).
- `GO_LIVE` — flip publishing from dry-run → live. Absent = safe test-mode.
- `REELS_LIVE` — allow Higgsfield video credit spend (reels). Absent = reels dry-run, 0 credits.

**Per-day spend caps** (`engine.py` DEFAULT_CAPS, override via `.env ENGINE_CAP_*`): copy 30 ·
searchapi 20 · apify 3 · reel 135 real Higgsfield credits (~1 reel/day).

### Module map
| Module | Role |
|---|---|
| `engine.py` | shared core: paths, slots, caps, flags, trust score, manifest, decision ledger, **alert/guard_main** |
| `research.py` | Mode A (topic discovery + scoring) · Mode B (viral-outlier/link clone) · pillar spread · drops consumer · recopy |
| `produce_daily.py` | morning orchestrator: produce, the copy→captions **bridge**, reel state-machine, image re-produce |
| `copywriter.py` | writes brand-voice copy/captions/hashtags/alt-text (OpenRouter LLM) — imports `compliance.py` |
| `compliance.py` | the single RED/YELLOW/GREEN claims authority + RUO |
| `post.py` | render a type=image job → PNG(s) via `produce.py` (0 credits) |
| `produce.py` | template renderer: single PNG, carousel (PNG/slide), **video-underlay** (overlay over clean video) |
| `reel.py` | reel finisher: overlay model (video inside template) or legacy burned-in captions |
| `reel_video.py` / `reel_captions.py` / `script.py` | reel b-roll (Higgsfield) / TTS+caption / spoken script |
| `telegram.py` / `approvals.py` | push review cards / read replies + link-drops (dedicated engine bot) |
| `decisions.py` + `engine` ledger | A/R/E learning ledger (`output/engine/decisions.jsonl`) |
| `drops.py` | manual link-drop queue (any TG user → Trending) |
| `apify.py` / `searchapi.py` / `firecrawl.py` / `blotato.py` | social/video scrape (incl. X) / discovery search / **article scrape (sole article extractor)** / publish+schedule CLI (no longer extracts) |
| `source_bank.py` | harvest a source's FULL transcript once, reuse angles (0 re-spend) |
| `publish.py` / `publish_slot.py` / `schedule.py` | publish one job / publish a slot / native Blotato schedule |
| `sheetlog.py` | **RETIRED** (no-op; Sheets path removed at cutover) |

---

## 2. Strategy / SOP

### Personas (Labs targets only — tag every post)
- **P1 — The Optimizer** (primary): male 38–52, founder/exec, $250–500K HH, already buying the
  longevity stack. Voice: **data-dense, mechanism + numbers, ROI**. "When in doubt, write for P1."
- **P3 — The Curious Newcomer** (secondary): 30–45, GLP-1-curious, entering optimization. Voice:
  **plain English, curiosity hooks, define every term**.
- **P2 — The Health-Forward Affluent Woman**: documented for awareness only; **future Acme Health**
  target, **never** auto-targeted by Labs content.

Each day's 5 posts cover **both** active personas (founder always P1, trending always P3; science/stack/
proof rotate P1/P3). Code: `research.PERSONA_BY_DAY` / `persona_for()`.

### The 5 pillars (one post per pillar per day)
| Slot | Pillar | Persona | Platforms | Function |
|---|---|---|---|---|
| 08:00 | **Science Simplified** | All active | IG·TikTok·X | discovery + trust; research explainers, every post cites real research |
| 11:00 | **Stack of the Day** | P1+P3 | IG·TikTok | conversion; compound combos as research protocols (save-rate pillar) |
| 13:00 | **Trending Hook** | P3 | IG·TikTok | reach; clone the FORMAT of viral posts / dropped links (never copy content) |
| 16:00 | **Research Spotlight** | All active | IG·X·Threads | credibility; external published research only — **no physician/medical validation as ours** |
| 19:00 | **Founder POV** | P1 | IG·X | authority; opinion/contrarian, grounded in research, never personal health advice |

Daily generation: `research.py run` → `plan_pillar_briefs` spreads Mode-A topics across stack/science/
proof/founder; trending comes from link-drops (preferred) or YouTube outliers.

### Weekly format mix (§3.2, code: `WEEKLY_FORMATS`)
Science: Carousel/Single/Reel rotation · Stack: Carousel/Graphic/Compare · Trending: Reel/Carousel/
This-or-That/Myth-bust · Research Spotlight: Framework/Quote/Callout · Founder: Quote/Opinion/Carousel.
Reels run **alternating days only** (`engine.is_video_day`), one pillar carries it (trending↔science).

### Cadence & governance
- **5 posts/day, 7 days/week.** `engine_state.posting_rate_per_day = 5`.
- **Governance = always approve.** Telegram approval is mandatory on every post, permanently. The
  trust score (SOUL §16, `engine.apply_trust_event`) is a **quality signal only** — it is never read
  to bypass the gate (`schedule.py`/`publish_slot.py` publish only `status=approved`).

### Growth targets (v2 §8 — measured once the feedback loop is on)
100K IG+TikTok followers in 6 months; key levers: content quality in first 60 days, save-rate on
Stack/Science, zero missed days. Weekly KPIs: posts/week 35, engagement/save/share rate, follower
growth, profile visits, link clicks.

---

## 3. Branding (hard constraints)

**Palette (only these):** Deep Forest `#1A2E1E` · Forest `#2D6A4A` · Accent `#3D9E6E` · Sage Mint
`#C8DDD0` · Warm Cream `#F2EDE4` · Cream White `#EDE8DF` · Dark Text `#1A2820` · Muted `#6B8F7A`.
**Never:** plain white background, gold/yellow/amber/purple/pink/red/orange, gradients (except the
approved sage→cream light bg).

**Fonts (only these):** DM Sans (headlines/UI/body) · **Cormorant Garamond Bold Italic** (emphasis
words within headlines ONLY) · DM Mono (data, compound names, COA, tagline). Never Inter/Roboto/Helvetica.

**Dark vs light = by SLOT** (`research.theme_for`, content.md §9/§18-20): morning feed (**science 08:00,
stack 11:00**) = **light**; midday/evening (**trending, proof, founder**) = **dark**. (Acme Health, if
ever used, stays light.) This replaced the old brand→theme tie.

**Brand bar** on every template: logomark + `ACME LABS` (DM Mono caps) + tagline
`PEPTIDES · PERFORMANCE · LONGEVITY` + `acmelabs.co`. Voice: scientific precision + accessible
education; premium biotech, not spa-wellness; confident not clinical.

---

## 4. Templates (all render dark + light; `templates/src/`)

| Family | File | Size | Use |
|---|---|---|---|
| Carousel | `carousel-{dark,light}.html` | 1080×1350/slide | multi-slide deck (`produce.py --carousel slides.json`) |
| Static callout | `static-callout-{dark,light}.html` | 1080×1080 | stat/data card |
| Static compound | `static-compound-{dark,light}.html` | 1080×1350 | product/compound feature (class + COA chips, price) |
| Story/reel card | `story-reel-{dark,light}.html` | 1080×1920 | story card / reel cover |
| Story poll | `story-poll-pro-{dark,light}.html` | 1080×1920 | this-or-that / comparison |
| Story product | `story-product-{dark,light}.html` | 1080×1920 | product story |
| Reel overlay (b-roll) | `reel-overlay-broll-{dark,light}.html` | 1080×1920 | **transparent overlay** composited over clean video |
| Reel overlay (studio) | `reel-overlay-studio-{dark,light}.html` | 1080×1920 | same, for talking-head footage |
| Reel caption overlay | `reel-caption-overlay.html` | — | synced caption strip |
| Story poll (legacy) | `story-poll.html` | 1080×1920 | legacy |

All verified rendering (dark+light) at 0 credits. The image brief points `post.py` at the template via
`brief.image.template` (+ `carousel: slides.json` for decks).

---

## 5. Reels — the overlay model (default since 2026-06-20)

**Overlay model (correct):** the **clean video** is the underlay; a **transparent brand template**
(`reel-overlay-broll-*`) is composited OVER it via `produce.py --video-underlay`. The video sits INSIDE
the template's design window (top 20% / sides 18% / bottom 20%); the **caption lives in the template,
never burned into the video.** Brief carries `brief.overlay = {template, EYEBROW, HOOK_LINE_1/2_ITALIC/3,
SUBTITLE_TEXT, CTA_LABEL, HANDLE, BRAND_NAME}`. Output: `<job>-final.mp4` + `thumb.png`.

**Legacy model:** `brief.cover` + `caption_data.json` → karaoke captions burned in via hyperframes-captions.
Kept; `reel.py` auto-detects overlay vs legacy.

**Reel gates:** GATE 1 (concept approval, pre-credit) → GATE 2 (final approval). RV3 (Higgsfield b-roll)
only spends with `REELS_LIVE` + the 135-credit/day cap + a live-wallet check. TTS voiceover (Kokoro)
runs on the Mac Mini only. REVISE on a reel clears the stale render and re-renders.

**Script vs. narrator vs. caption — how the words get into a reel (read this before touching reel audio):**
- **Higgsfield/Seedance NEVER narrates and NEVER renders text.** RV3 generates **silent, faceless**
  b-roll only. The script is never sent to Higgsfield for a voice, and we never let it improvise speech
  then transcribe it back.
- The **narrator audio** = **Kokoro TTS of `brief.script`** (`reel_captions.py` RV4 → `narration.wav` →
  muxed over the b-roll → `voiced.mp4`).
- The **on-screen caption** = the SAME `brief.script`, composited in the transparent template overlay
  (`produce.py --captions-script`). Overlay reels **do not Whisper-transcribe** — we own the script, so the
  caption is exact by construction. (Only the legacy burned-in path transcribes + reconciles.)
- ⚠️ **TTS number trap (ACME-041, 2026-06-21):** Kokoro voices a **decimal as separate cardinals** —
  `2.5%` came out "two … five percent" (heard as "5%") while the caption correctly showed `2.5%`, so audio
  and caption disagreed. **Fix is in place:** `reel_captions.tts_normalize()` spells numbers/percent/units
  into words **only for the voiceover** (`2.5%` → "two point five percent"); `brief.script`/the caption keep
  the clean glyph. **When you remake or QC a reel with figures, transcribe the new `narration.wav`
  (`hyperframes transcribe`) and confirm the spoken numbers match the caption.** Known follow-up (lower
  priority): Kokoro also clips the brand name to "EVARA" — a separate pronunciation tweak, not yet applied.

---

## 6. Compliance (the hard gate — `compliance.py`)

Runs at **produce** (warn) and **publish** (`publish.py` — hard BLOCK; `--go` cannot bypass). Three tiers:

**🔴 RED — hard block (never publish):**
- Disease action verbs: cure/treat/heal/prevent/diagnose/remedy/fix (any tense).
- Outcome promises: "proven to", "guaranteed", "you'll feel/see/lose/gain", "miracle/breakthrough".
- **Weight-loss promises**: "lose/drop/shed N lb/kg", "melts/torch/incinerate/blast (away) fat/pounds/weight".
  (Research framing is fine: "subjects lost 15 pounds", "a weight-loss study", "fat metabolism".)
- Body/specific claims: "burns fat", "builds muscle", "regrows hair", "boosts testosterone",
  "repairs your tendons", "reverses aging", "safe for humans", asserting "for human/personal use".
- **Physician-as-ours**: "our/Acme's doctor/physician/medical team" — never imply a physician acts for
  Acme or present medical validation as our own (v2 §9).
- Testimonials: "I healed/cured…".

**🟡 YELLOW — efficacy verbs OK only with framing:** allowed if a research-subject attribution or hedge
is present ("research suggests", "studies indicate", "research subjects … may …"); else flagged.

**🟢 GREEN — approved language:** "research suggests/indicates", "data shows", "studies/researchers
found", "published in [journal]", "a 2024 study", "protocols used by", "optimisation".

**Always:** RUO footer on **every Labs post** — `For research use only — not for human consumption.`
(`engine.ensure_ruo` forces it; the regex accepts "research use only" / "not for human consumption" / "RUO").
**COA/product link** folded into every caption (live SKU page). Never target under-18; never name a
competitor. Platform notes: TikTok is strictest on outcome language; IG no before/after weight-loss
imagery; X most lenient but still no medical claims.

---

## 7. Telegram (the dedicated engine bot — `ENGINE_TELEGRAM_*`, separate from OpenClaw's)

**Three functions:**
1. **Review (A/R/E)** — the engine pushes a card per post (hook, caption preview, pillar, persona,
   slot, source). Reply:
   - `APPROVE ACME-NNN` → writes `qc.json` + `status=approved` → publishes at its slot (+trust).
   - `REJECT ACME-NNN reason` → discarded; reason logged (−trust); steers future content away.
   - `REVISE ACME-NNN note` → re-made from your note (images **and** reels), re-pushed.
   - `HOLD ACME-NNN` → defer, no score change.
   Reels have the same A/R/E at **GATE 1** (concept, pre-credit) then **GATE 2** (final).
2. **Link-drops** — any group member pastes a content URL → captured into the drop queue → becomes the
   next Trending post. The bot must be a **group admin** (or privacy off) to see members' messages.
3. **Alerts** — "published" / "failed" notices. **Failure alerts are live** (`engine.alert` /
   `guard_main`): a crashed job or failed render pings the group.

Approval window: posts never auto-publish without approval; if you're unavailable they're held.

---

## 8. Link-drops (research from dropped links — `drops.py`)

- **Capture (0 cost):** `approvals.py poll` sees any non-command message; extracts content URLs
  (IG/TikTok/YouTube/X/Reddit/FB/Threads), dedups, queues to `output/engine/manual_drops.json`
  (`status=pending`, `priority_bonus=3`). Acks "📥 Queued …".
- **Consume:** the morning run drains the oldest pending drop into the **Trending pillar**
  (`research.py drops --max 1`), Apify-budget-gated; it **replaces** the YouTube outlier for that day.
  Extraction routes by URL: social/video → Apify (IG/FB live-proven; Threads + X/Twitter wired), article/blog → Firecrawl; full text **banked** to the Source Bank
  for reuse (re-runs cost $0). Failed URLs are marked so they never retry forever.

---

## 8.1 Viral-outlier sourcing doctrine — how to find what trends (Marvin 2026-06-21)

The single biggest lever on whether a post trends is **what you choose to clone**. Don't search
topic-nouns and hope; run this **three-step method** every time you source (it's how the Mon/Tue
2026-06-22 batch was built, and it's encoded in `research.py` `OUTLIER_YT_QUERIES` + `find_outliers`):

1. **OUTLIER — the quantitative pass.** Rank candidates by **velocity vs the niche-baseline median**
   (`views / age_days`, then the ratio to the set median), **never raw views**. An outlier is
   **≥2× baseline**; the *bigger the ratio, the louder the signal* (a 37× explainer is a
   category-defining piece, not noise). Mine YouTube (`searchapi`), TikTok/Reddit (`apify`), X, and the
   drop-a-link inbox. Raw-view leaders are often just old — velocity finds what's hot *now*.

2. **THROUGHLINE — the qualitative pass.** Read the top outliers + a quick web scan across
   YouTube/X/TikTok and **name the ONE narrative the whole niche is circling right now.** You clone the
   *throughline*, not any single post. Ours (durable through 2026): **"the hype is outrunning the
   evidence"** — celebrity-driven buzz (Rogan healed an injury with BPC-157; Ozempic → tirzepatide;
   "peptide therapy" +459% on TikTok YoY) **vs. what the studies actually show** (SURMOUNT-5's
   head-to-head; the GLP1R gene variant in *Nature*; "human trial data lags the claims"). The named
   narrative is what makes the hooks land — find it *before* writing.

3. **EDGE — the strategic pass (the filter).** Acme **is the evidence side**: COA on every lot,
   RUO, sourced, under-claiming. So **we win whenever the frame is "hype vs. evidence."** Keep only the
   outliers we can **answer with data** — myth-bust, "what it actually does," "X vs Y," "the part nobody
   mentions," "is it worth it / a scam." **Reject anything that would require us to make an outcome
   claim** (that's off-brand *and* a compliance RED). Then clone the **hook STRUCTURE** (map to
   `FORMAT_ARCHETYPES`: this_or_that → poll, myth_bust → story-reel, study_reaction → callout, …) and
   pour an **Acme-owned topic** into it. The hook gets the human voice; the **body stays rigorous and
   sourced** (see "Hook doctrine" in SKILL.md / `copywriter.py`).

**Search inputs (refresh as the throughline shifts).** `OUTLIER_YT_QUERIES` now **leads with throughline
framings** — "what peptides actually do", "tirzepatide vs semaglutide", "are peptides worth it",
"peptide myths debunked", "scientists react to GLP-1 study" — because those surface the convertible
angles; topic-noun seeds follow for breadth. The default sweep mines the first **3**. When you spot the
throughline drifting (a new compound, a new study, a new celebrity moment), **update those lead queries
and the throughline statement above** — they reflect the mid-2026 conversation, not a fixed truth.

**Why current news rides along.** Mode A topic discovery (the non-trending pillars) pulls **recent news**
(SOUL §8 recency weight + `firecrawl`/`searchapi`), so the science/proof cards cite *fresh* sources
(e.g. the 06-20 Ozempic/Wegovy-and-bone studies). Outliers give the *format*; news gives the *proof*.

---

## 9. Feedback loop — what's wired vs not

**Wired (live):**
- **A/R/E learning** — every approve/reject/revise is recorded to `decisions.jsonl` with a content
  snapshot. `engine.rejected_lessons()/rejected_topics()` mine REJECTED items so `research.py` skips
  re-proposing a rejected angle and `script.py` injects "avoid this" lessons. So **rejecting/revising in
  TG genuinely steers future content.**
- **Topic rotation (anti-repeat, Marvin 2026-06-22)** — the daily candidate pool was `sorted(topic_weights)`
  with the weights all tied at 1.0, so it scored the **same top compounds every day** → identical
  compound→pillar→template briefs morning after morning (only a hard TG REJECT broke the cycle). Now
  `research.recently_used_compounds()` holds back any compound featured in the **last ~8 jobs** (cooldown,
  `.env ENGINE_TOPIC_COOLDOWN_JOBS`) so the run rotates through the catalog, and `frame_for()` rotates the
  per-pillar **hook** by day (`PILLAR_TOPIC_FRAMES`, 3 each) so framing isn't a fixed template. Applies to
  both the image run (`cmd_topics`) and `reel-today`. ⚠️ Note `topic_weights` are still flat (the Stage-8
  weighting that would auto-prioritise compounds from performance is deferred) — rotation is what currently
  drives variety.
- **Link-drops** — steer topics by dropping links.

**Not wired (deferred on purpose):**
- **Measure (Stage 7)** — Apify scrape-back of likes/saves/shares. Off.
- **Feedback updater (Stage 8)** — weekly weighted-scoring that auto-tunes pillar/format/persona weights
  from performance. Off (needs weeks of data + Supabase).
- **Direction commands** ("focus today on X", "avoid Y this week") — not parsed yet; use link-drops +
  REVISE notes, or edit config in Claude Code.

**To change a rule permanently:** edit the code + this skill, not just chat. Claims → `compliance.py`.
Brand → `SOUL.md`. Pillars/personas/themes → `research.py`. Schedule → `launchd/`.

---

## 10. Operating commands

```bash
# Produce / research
python3 produce_daily.py run [--posts 4] [--dry-run] [--generate-reels]   # full morning produce
python3 research.py run --select 4                  # 4 non-trending pillar briefs (+ trending elsewhere)
python3 research.py drops --max 1                   # consume next dropped link → Trending
python3 research.py inbox <URL>                     # manually clone one link now
python3 research.py recopy output/jobs/ACME-NNN --note "…"   # re-make a revised image's copy
python3 research.py reel-today                      # mint the day's reel brief (video days)

# Review / publish
python3 telegram.py push output/jobs/ACME-NNN       # push one post for review (--dry-run prints)
python3 approvals.py poll                           # apply A/R/E + capture link-drops now
python3 approvals.py apply "APPROVE ACME-NNN note"  # apply one command directly
python3 publish_slot.py --slot 13:00               # publish that slot's approved posts
python3 publish.py output/jobs/ACME-NNN [--go]      # publish one job (dry-run unless --go)

# Render / inspect
python3 post.py output/jobs/ACME-NNN                # render image PNG(s)
python3 reel.py output/jobs/ACME-NNN               # finish a reel (overlay or legacy)
python3 produce.py templates/src/<tmpl>.html out.png --set KEY=VAL   # render any template
python3 engine.py                                  # status: caps, trust, today's manifest

# Switches
touch output/STOP        # halt loop      | rm output/STOP      to resume
touch output/GO_LIVE     # publishing LIVE | rm to return to dry-run (supervised)
touch output/REELS_LIVE  # allow reel credit spend
```

---

## 11. Failure alerts & troubleshooting

- **Failure alerting (live):** each orchestrator is wrapped in `engine.guard_main` — an uncaught crash
  sends `🛑 Acme engine — <step> FAILED: …` to Telegram and re-raises (launchd logs the traceback).
  produce also alerts on a research-run failure or any job that fails to render/caption.
- **Logs:** `logs/engine.{produce,review,approvals,publish}.log`.
- **Nothing posts to Instagram?** IG/Threads/FB are not connected in Blotato (see V1 note) — only
  X/TikTok/YouTube publish today.
- **Nothing publishes at all?** `GO_LIVE` is absent (safe test-mode) — that's expected until you flip it.
- **A reel stays dry-run / no video?** `REELS_LIVE` off, or TTS (Kokoro) only on the Mac Mini.
- **Tests:** `python3 -m pytest tests/ -q` (+ the script-style `tests/test_*.py`, exit 0 = pass).

---

## 12. ⚠️ V1 NOTE — what's still missing (honest list — mostly your steps, not bugs)

These are **not broken code** — they are setup/decisions left:
- **Connect Instagram + Threads + Facebook in Blotato** (your step). Today only **X / TikTok / YouTube**
  publish — so every post currently reaches only those. **Instagram is your #1 goal.**
- **Turn publishing ON** — it's in safe test-mode until you create `output/GO_LIVE` (and
  `output/REELS_LIVE` for videos).
- **Test one real Threads link** (IG + FB are proven; Threads is wired but never run with a real link).
- **Supabase database** — still using local files (works fine; the v2 plan wants Supabase as the real
  database — add after go-live).
- **Measure + feedback loop** — still off on purpose (the "get smarter from results" part).
- **Monthly themes (§3.3)** — not wired yet (small).

The engine code itself is in good shape: research → 5 pillars + link-drops → templates (all render,
dark/light, video-in-template) → compliance gate (now stricter) → Telegram review → publish, with
failure alerts so you'll know if anything breaks. The biggest remaining items are the **Blotato
connections** and **flipping go-live** — those are yours to do.
