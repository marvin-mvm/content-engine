# MIGRATION.md — Acme Content Engine: OpenClaw → Claude Code

> **Status: PLANNED — NOT STARTED.** This is a planning document only. Nothing in it has been executed.
>
> **⚠️ Note for the Acme agent (OpenClaw):** this file is a migration plan authored and executed in **Claude Code sessions only**. It is NOT an instruction file for you. Do not act on it, do not register crons from it, do not modify any file because of it. Your operating rules remain `SOUL.md` + `TOOLS.md`, unchanged.
>
> **Non-interference guarantee:** until explicit cutover (Part 4), the running OpenClaw system is untouched — no edits to `SOUL.md`, `TOOLS.md`, `AGENTS.md`, `IDENTITY.md`, `USER.md`, `HEARTBEAT.md`, `MEMORY.md`, `openclaw.json`, agent bindings, or Telegram wiring. MIGRATION.md is not in OpenClaw's auto-injected bootstrap set, so it adds zero context cost to the running agent.

Authored: 2026-06-11 · Owner: Operator · Executor: Claude Code (VSCode extension / CLI, this repo)

---

## Part 0 — Why (current-state audit, verified 2026-06-11)

Findings from a full review of the workspace + OpenClaw orchestrator:

| Finding | Evidence |
|---|---|
| The "autonomous daily engine" never runs | `openclaw cron list` = **0 jobs**; `HEARTBEAT.md` empty. Everything is on-demand Telegram. |
| Trust-score system is dead code | `engine_state.json` → `trust_score: 0`, `last_updated: ""`. No script implements §15/§16 events. |
| Orchestrator model too weak for multi-step | Acme agent = `gemini-2.5-flash` carrying ~86KB auto-injected context/turn. Git history is a string of guardrail patches ("Harden DTC routing", "Add explicit routing", …) compensating for missed routing. |
| Multi-step chains fail under OpenClaw | Image→template composites and video→subtitles→overlay chains are exactly where the flash agent breaks. |
| Engine code is NOT in git | `produce.py`, `render.py`, `copywriter.py`, `sheetlog.py`, `poll_video.py`, `templates/`, `skills/` all untracked. Only .md files committed. |
| Doc contradiction injected every turn | `TOOLS.md` still documents the old 11-col `A:K append` sheet schema; `SOUL.md` §17b mandates 12-col `A:L insert`. Live sheet verified 12-col. |
| Pipeline scripts themselves are solid | produce/render/copy/sheetlog reviewed line-by-line; all skill binaries are PATH wrappers exec'ing workspace scripts (no drift). They run standalone — **no OpenClaw dependency**. |

**Gap estimate (per Operator): >50% of the engine is unbuilt** — research automation, publishing automation, approvals, scheduling. What works today: brand-compliant asset generation on demand.

Known bugs to fix during the relevant phases (none are urgent):

1. ✅ **FIXED (Phase A4).** `poll_video.py` didn't pass `--prompt` to produce.py → Content Matrix col F got the local mp4 path instead of the generation prompt (which sat unused in `job["params"]["prompt"]`). Fix: extract the prompt from the completed job (`params.prompt`, verified against a real `generate list --json`; same lookup chain as `copywriter.py`) and pass it as `--prompt`. Backward-compatible (no prompt found → unchanged behavior; PENDING/FAILED/DONE contract + cron self-cleanup untouched; `--no-log` deliberately NOT added — it's the live-post path). Argv construction tested in isolation (`tests/test_poll_video.py`, no live-sheet write).
2. ✅ **FIXED (F1).** `copywriter.py --platform` lacked `x` / `threads` / `facebook` / `linkedin` (SOUL §6 requires a unique caption per platform). Fix: added all four (plus a `PLATFORM_SHAPES` map injected into the prompt so each channel gets the right shape — X ≤280/0-hashtags, etc.; `x` aliases `twitter`). Backward-compatible — the existing 4 platforms and the output JSON keys are unchanged.
3. `produce.py --model` help text says default `flux_1_1_pro`; actual default is `gpt_image_2`. Cosmetic.
4. Decoy templates `story-reel.html` / `story-reel-preview.html` still in `templates/src/` ("do NOT use" per MEMORY.md). Archive in Phase A0.
5. `render.py` fetches Google Fonts from network at render time; `hyperframes-captions/fonts/` shows the embedded-font pattern to copy. Optional.
6. `copywriter.py` banned-claims regex misses "treatment / prevention / heals" variants. Optional hardening.
7. Junk in repo root: stray `Sheet1!A1` file (accidental shell redirect), `overlay_preview_v2–7.jpg`, test mp4s. Clean in Phase A0.

---

## Part 1A — Content Strategy (ADOPTED from Devon's Implementation Guide v1.0)

> **The full strategy, reconfigured to our stack, is saved as [CONTENT_ENGINE_GUIDE.md](CONTENT_ENGINE_GUIDE.md)** (Devon's guide verbatim-ish + our stack mapping + the per-pillar formats/hooks + the 8-stage→our-modules map). This section is the decision log; that guide is the operational reference. ⚠️ Devon's persona detail tables (1A.1) remain blank in the source — still to fill from Devon.

**Decision (2026-06-11, Marvin):** adopt the strategy layer of Devon's guide wholesale. It is strong and stack-agnostic. We map it onto the existing Acme production core (Higgsfield → HyperFrames → produce.py) rather than onto Devon's proposed tools — see the reconciliation in Part 5 for what is rejected and why. This section is the *what/why*; Part 1 is the *how*. The North-Star goal is Devon's: **100K organic followers across Instagram + TikTok in 6 months via a self-improving engine posting 5×/day.**

**Scope (2026-06-16, Marvin):** run it **dual-brand on a combined account**, exactly as Devon's guide specifies — Labs and Health both. Brand-per-post routing stays (`copywriter.py --brand labs|health`): Labs = research/education content, organic only, RUO framing; Health = protocol/metabolic/results content, may run paid. Labs supplies credibility, Health carries the protocol/results pillars. (Labs-only was considered and rejected: RUO bars human-use content, which would gut the Stack-of-the-Day and Social-Proof pillars.)

**Physician/medical-claim policy (2026-06-16, Marvin) — legally conservative:** the engine will **never cite, name, or imply a physician acting for Acme**, and never present medical validation as Acme's own. Social Proof and any "physician/expert" angle is satisfied **only by third-party published research framed as external** ("a 2024 study found…", "researchers report…") — never "our doctor" / "Acme's physician" / "our medical team." This removes the only remaining Devon dependency entirely (see Part 5.1).

**Data layer (2026-06-16, Marvin) — Supabase, Sheets dropped:** the system-of-record for all structured data (Devon's 7 tables: discovery_queue, daily_brief, content_drafts, ready_to_publish, published_posts, performance_data, content_strategy_config — **plus an 8th, `review_decisions`, added 2026-06-19**) is **cloud Postgres on Supabase**, not Google Sheets.

> **`review_decisions` (8th table — the A/R/E learning ledger, 2026-06-19, Marvin).** Every Telegram approve/revise/reject/hold (both the reel **concept** gate and the **final** gate) is recorded by `approvals.py`→`engine.record_decision()` with a snapshot of the content it judged (topic/angle, **script**, **generation prompts**, X caption, slide copy). **Build-time system-of-record is local append-only JSONL** at `output/engine/decisions.jsonl` (one line = one row; contract in [`schemas/decision.schema.json`](schemas/decision.schema.json), maps 1:1 to the table). Columns: `decided_at timestamptz · job_id text · verb text · gate text · who text · note text · content jsonb`. At cutover `db.py` replays/streams these rows into Supabase — **there is no other path for the review history to reach Supabase, so it must be captured now** (the live JSONL is that capture). **F5 use:** `engine.rejected_lessons()/rejected_topics()` mine this table REJECTED-FIRST (rejections ≪ approvals, so it's cheap) to steer generation away from past mistakes — `research.py` skips re-proposing a hard-rejected angle, `script.py` injects the few rejected-reel lessons into the script prompt. Approved-example seeding is a later, optional add (rejected-avoidance is the priority — Marvin 2026-06-19). Schema is managed via the **Supabase CLI** (migration files → `db push`); the engine reads/writes rows at runtime via a small `db.py` (supabase-py), not the CLI. Human review is via querying Claude Code or the Supabase Studio dashboard — **no Sheet.** Rationale: the feedback loop is relational query work (30-day GROUP BY aggregations) that Sheets does badly, and Sheets-as-DB already caused a real cost problem (`acme-token-cost-fix`: $0.50/call from unbounded reads). **All "sheet"/"Content Matrix"/"cols K/L" references in Parts 1–3 and the F-series below now mean Supabase tables.** ⚠️ **Sequencing + OpenClaw safety:** dropping the Sheet is a **cutover action** (Part 4), not a build-time one — the live OpenClaw engine still writes to the Sheet via `sheetlog.py`/`produce.py`. During the build Supabase is **additive**: new Claude Code modules log to Supabase; the shared scripts keep their Sheet path until cutover, then it's removed. The content-generation module (Part 1) stays DB-light (job folders + one log row); Supabase matters mainly for F3/F4/F5.

### 1A.1 Personas — tag EVERY brief before generation

The system must know who it is writing for; persona drives voice and hook style.

| ID | Persona | Voice for this persona |
|----|---------|------------------------|
| P1 | **The Optimizer** (primary) | Data-dense, ROI/return language, mechanism + numbers |
| P2 | **The Health-Forward Affluent Woman** (secondary) | Aspirational, premium, outcome- and lifestyle-framed |
| P3 | **The Curious Newcomer** | Plain English, curiosity hooks, define everything |

> ✅ **Resolved 2026-06-18 (Marvin):** Devon's detailed persona definitions (demographics/psychographics/voice, tables 1.1–1.3) are now **backfilled in [CONTENT_ENGINE_GUIDE.md §1](CONTENT_ENGINE_GUIDE.md)** (from the source PDF). The `brief.json` field stays `P1/P2/P3`; F3 carries each persona's voice rule into the copy step. No separate `DAN_STRATEGY.md` — the guide is Devon's strategy as saved. Persona is a hard `brief.json` field (see M1).

### 1A.2 The Five Pillars → brief presets (one post per pillar per day)

Each pillar is a reusable brief preset mapping to existing templates. This **replaces the current 3-slot model** (SOUL.md §5: 8/13/18) with a 5-slot model.

| # | Pillar | Slot (PT) | Persona(s) | Function | Maps to template |
|---|--------|-----------|------------|----------|------------------|
| 1 | **Science Simplified** | 08:00 | All | Discovery + trust (credibility engine) | `carousel-*`, `story-reel-*`, `static-callout-*` |
| 2 | **Stack of the Day** | 11:00 | P1, P3 | Conversion — **save-rate is the KPI** | `carousel-*`, `static-compound-*` |
| 3 | **Trending Hook** | 13:00 | P3, P2 | Reach/discovery — clone winning *format*, not content | `story-reel-*`, `carousel-*` |
| 4 | **Social Proof & Results** | 16:00 | All | Conversion closer (frameworks/case studies) | `carousel-*`, `static-callout-*` |
| 5 | **Founder POV** | 19:00 | P1 | Authority + retention (opinion, no face) | `story-reel-*` (text-on-screen), `carousel-*` |

Pillar definitions, sample hooks, and format menus are taken verbatim from Devon's Section 2 and become the body of each preset.

### 1A.3 Calendar & volume

- **5 posts/day × 7 days = 35/week.** Rolling 7-day calendar built weekly, reviewed Monday via Telegram.
- ⚠️ **This is a +67% volume increase over current (3×/day).** Higgsfield credits are a **managed budget lever, not a hard ceiling** (Part 5.2 — Acme is on the $145 tier and Devon can upgrade). The discipline is still **mandatory as good economics**: most daily posts are carousels/statics/text-reels rendered locally at **0 credits**, with paid Higgsfield generation reserved for the few posts that truly need new footage. Two structural savers: (1) render free by default; (2) approve the concept *before* spending a generation (see 1.1 ordering note).

### 1A.4 Per-platform variants (one post → N captions)

| Platform | Rules | Status |
|----------|-------|--------|
| Instagram | Carousel 5–10 slides (slide 1 = hook, last = CTA); Reel 15–45s, hook in 2s, text on screen; 20–30 hashtags; Stories reshare within 1h | 🔧 connect in Blotato (easy — Marvin) |
| TikTok | Same video, native upload, 3–5 hashtags, scroll-stop first frame | ✅ connected (43061) |
| X / Twitter | Quote/opinion only (not all 5); threads for Science; **0 hashtags**; human reply engagement | ✅ connected (18688) |
| Threads | Social Proof + Founder POV only; short punchy repurpose of IG caption | 🔧 connect in Blotato (easy — Marvin) |
| Facebook | Optional extra reach if wanted | 🔧 connect in Blotato (easy — Marvin) |

IG / Threads / FB are a simple Blotato account connection Marvin owns — **not** an external Meta-review blocker. `copywriter.py` gains `--platform threads` and `--platform x` variants; per-platform caption generation is a hard requirement (never the same text verbatim).

### 1A.5 Compliance — Devon's rules consolidated (ALIGNS with SOUL.md, no conflict)

Adds two things on top of the existing SOUL.md hard-stops, nothing contradicts:

- **Labs content:** caption footer `For research use only. Not for human consumption.` + **organic only, NEVER paid ads.**
- **Health content:** physician-oversight framing where applicable; **may run paid**; GLP-1 content carries no specific human dosing.
- Reaffirmed (already in SOUL.md): no treats/cures/heals/prevents; research framing only; no medical before/after; no under-18 targeting; banned words `treats, cures, heals, fixes, proven to, guaranteed`.

### 1A.6 Feedback loop — adopted as a LITE weighted-scoring updater (NOT an "intelligence layer")

Devon's Stage 8 is real but oversold. Implement it as an extension of the pattern you already have (`engine_state.json` → `topic_weights` + trust score), not a new AI brain:

- Weekly job reads performance data (once the analytics module exists, F-series) and nudges: **pillar weights · format preferences by platform · topic/compound boosts · winning hook patterns · persona weighting.**
- Honest expectation: meaningful signal needs **months** of 35-posts/week data; early weeks are noise. Build the mechanism now, trust it later.
- Weekly Telegram report (Mon): top 3 / bottom 3 posts, follower delta, save-rate trend, recommended adjustments.

---

## Part 1 — ACTIVE PLAN (revised): Content Generation Module first

**Decision (2026-06-11):** focus exclusively on content generation. Research is a separate later module (topics can be fed manually). Publishing to Blotato is straightforward and deferred. Telegram comes last. Scheduling only after the module is boringly reliable.

**Driving constraint: Higgsfield credits are the only expensive, irreversible spend.** Everything downstream of generation (HyperFrames captions, produce.py overlay, thumbnails, QC) is free and local.

**Principle: prove the entire downstream chain on assets already owned (0 credits). Only let Higgsfield fire once the chain is known-good.** When generation runs for real, its output drops into a validated pipeline — if the result is wrong, the prompt is the suspect, not the plumbing.

### 1.1 Module chain

```
M1 brief.json ──► M2 copywriter.py ──► M3 visual ──► M4 HyperFrames ──► M5 produce.py ──► M6 QC gate
   (manual input)    (free)        (CREDITS,      captions          overlay/thumb      (free)
                                    gated)         (free, video)     (free)
                                      │
                                      ├─ reuse existing asset ......... 0 credits
                                      ├─ plain palette background ..... 0 credits
                                      └─ generate new .... credits, preflight-gated
```

Each module reads/writes one job folder: `output/jobs/ACME-NNN/`. Modules are independently runnable and re-runnable. Telegram review and Blotato publishing bolt onto M6's output later without touching M1–M5.

**⚠️ Ordering for credit-bearing posts (adopted from Devon's Stage 4→5):** when a post needs **new Higgsfield generation** (`bg_policy: generate` / a fresh reel), approve the **concept/brief first, then fire generation** — i.e. M1→M2→(review)→M3→M4→M5. Never spend a generation on a concept that gets rejected. For **free local renders** (plain-bg / reuse / carousels / statics / text-reels), order doesn't matter cost-wise, so the simple produce-then-review flow (M1→M5→M6→review) stands. This is the credit-safety lever referenced in 1A.3.

### 1.2 Module specs

**M1 — Brief contract (manual input interface).** One `brief.json` per job:

```json
{
  "type": "reel | image",
  "brand": "labs | health",
  "pillar": "science | stack | trending | proof | founder",
  "persona": "P1 optimizer | P2 affluent-woman | P3 newcomer",
  "topic": "BPC-157 tissue repair research",
  "template": "templates/src/story-reel-dark.html",
  "platforms": ["instagram", "tiktok", "x", "threads"],
  "script": "(optional) exact voiceover text, if it was part of the video prompt",
  "bg_policy": "plain | reuse | generate",
  "source_job_id": "(optional) existing Higgsfield job to use instead of generating",
  "product_feature": false,
  "compound": "BPC-157", "class": "PENTADECAPEPTIDE"
}
```

`pillar` + `persona` are **required** (Part 1A) — they drive voice, hook style, and template choice. A pillar implies a default template + slot, so a brief can be as small as `{type, brand, pillar, persona, topic}` and the preset fills the rest.

**M2 — Copy.** `copywriter.py "<topic>" --brand … > jobs/ACME-NNN/copy.json` — overlay tokens + caption + hashtags + alt text, compliance-enforced. Cost: OpenRouter pennies.

**M3 — Visual (THE ONLY CREDIT SPEND), preflight-gated.** Hard gate before any submit, all must pass:

- [ ] Reuse check ran: `higgsfield generate list --json` + `asset_cache/` + Metabolic Support Stack `7d01b600-…` — nothing existing fits
- [ ] `bg_policy` honored (plain = no generation at all)
- [ ] Brand Prompt Block prepended verbatim (IMAGE or VIDEO block)
- [ ] **No rendered text requested in the prompt** (models hallucinate text; it's burned in M4/M5)
- [ ] Correct route: product/Nova ad → DTC Ads Engine; b-roll/background → raw `gpt_image_2`/`seedance_2_0`; product photography → `product-photoshoot`
- [ ] Aspect matches template (9:16 story · 4:5 carousel/compound · 1:1 callout)
- [ ] Video: submit `--no-wait`, never block

Any check fails → no submit, no spend.

**M4 — HyperFrames subtitles (video only, free).** Pre-wired project `hyperframes-captions/` (fonts embedded, palette set, `caption-editorial-emphasis` rebranded). Two paths, per the video:

- **(a) Video has voiceover audio** → `hyperframes transcribe <mp4>` → word-level timestamps.
- **(b) Script was part of the video prompt** → still transcribe for timing, then reconcile transcript words against the known script (fixes Whisper mishears, keeps timings).

Claude judgment steps (the part OpenClaw/flash could never do): word-grouping into caption beats; choosing 1–3 emphasis keywords per group → Cormorant Garamond 700 Italic `#3D9E6E`; body DM Sans 600 `#F2EDE4`; captions in the §14 subtitle zone (68–80% height). Then `npm run check` → `hyperframes render` → `jobs/ACME-NNN/captioned.mp4`.

**M5 — Brand overlay / thumbnail (free).** `produce.py <template> --video captioned.mp4 --json copy.json --prompt "<generation prompt>"` → final mp4 with embedded cover art + standalone `thumb.png` + auto log row (prompt recorded — fixes bug #1 behavior). (During the build, produce.py still logs to the Sheet for OpenClaw's sake per line 49; the new modules also write the job to Supabase. At cutover, only Supabase remains.) Image jobs: `produce.py <template> --json copy.json [--bg-file|--bg-url|--bg-prompt]`.

**M6 — QC gate + package (free).** Claude **visually inspects the rendered output** (Read the PNG; ffmpeg-extract frames from the mp4) against SOUL §21: palette only forest/cream · brand bar present · correct fonts · RUO line on product posts · correct format/aspect · captions legible · compliance language clean. Pass → job folder is marked review-ready (this folder IS the future Telegram package). Fail → fix locally; **regeneration is the last resort and never automatic.**

### 1.3 Build phases (with grades + credit budget)

| Phase | Steps | Effort | Higgsfield credits |
|---|---|---|---|
| **A0 — Safety** | `.gitignore` (output/, asset_cache/, *.mp4, memory/, junk, .env, credentials) · archive decoy templates · delete junk · **git commit the engine code** | 🟢 Easy (~30 min) | 0 |
| **A1 — Prove the reel chain on an existing video** | Pick a finished asset already owned (local mp4 or completed Higgsfield job — free retrieval) → M4 captions → M5 thumbnail → visual review → iterate caption look/zones until approved | 🟡 Medium (iteration is the work) | **0** |
| **A2 — Wrap it** | Encode proven steps as the `brief.json` contract + job-folder layout + M6 checklist; re-run start-to-finish from a brief to confirm repeatability | 🟢 Easy | 0 |
| **A3 — Image pipeline same treatment ✅** | Plain-bg + reuse-bg variants through M5+M6; validates all 5 template families (story, poll, carousel, callout, compound). **DONE** — `post.py` runner + `render.py detect_size` fix + runbook §9. | 🟢 Easy | 0 |
| **A4 — Preflight gate ✅** | M3 checklist as a hard scripted gate (`preflight.py`); fix `poll_video.py` col-F bug (#1). **DONE** — standalone hard-wall gate + col-F fix, both tested 0-credit (`tests/`). Runbook §10. | 🟢 Easy | 0 |
| **A5 — First live fire ✅ (video proven)** | ONE image generation → full chain → QC. Then ONE video generation → full chain → QC | 🟢 Easy | **Video half DONE** (ACME-012, real seedance_2_0 gen → 9:16 → captions → cover → QC → published to X). Image render chain proven free (A3 + ACME-011 carousel, published). Dedicated `produce.py --bg-prompt` single-image generation still optional. ⚠️ Double-spent on the video (2 gens) via a since-fixed `higgsfield.py` bug — see A5 note. |
| **A6 — Skill-ify ✅** | **DONE 2026-06-18.** Four thin Claude Code skills in `acme/.claude/skills/` encoding the proven recipes: `acme-preflight` (§10), `acme-reel` (§1), `acme-post` (§9), `acme-publish` (§11.5). Each = `name`+`description` frontmatter + a thin body that points at its RUNBOOK section (no brand-rule duplication — those stay in SOUL.md). The repo `CLAUDE.md` stub is **untouched** (OpenClaw-era pointer; replaced only at cutover, Part 4); the OpenClaw `skills/` dir is untouched. | 🟢 Easy | 0 |

**Credits are touched exactly once, in A5, after everything downstream is proven.**

- **A5 status (2026-06-17 — video half DONE):** first real Higgsfield spend, gated through `preflight.py`. **Video:** ACME-012 BPC-157 b-roll — `seedance_2_0` generation → cropped 16:9→9:16 locally (free; seedance ignores aspect, RUNBOOK §12 V3) → HyperFrames captions → branded `story-reel-dark` cover → M6 QC → **published to X** (single video post; `x.com/acmelabs/status/2067406700601114651`). **Image:** the render chain is proven free (A3) and ACME-011 BPC-157 carousel was rendered + **published** (X tweet + TikTok scheduled); a dedicated `produce.py --bg-prompt` single-image *generation* was not run (optional — A3 already proves the chain). ⚠️ **Double-spend lesson:** the video was generated twice — `higgsfield.py` crashed on the CLI's bare-string job-id, hiding a created job, and `generate list` doesn't show pending jobs, so a re-run double-submitted. **Both fixed** (commit `dbd5c11`) + documented (RUNBOOK §12 V1/V2). Publishing findings in §11; video recipe in §12.
- **A4 status (DONE 2026-06-17, 0 credits):** built `preflight.py` — the M3 hard gate that protects the A5 spend. **Wiring (decided with Operator): standalone**, not integrated into `produce.py`, because (1) it stays purely additive — the shared OpenClaw scripts are untouched, zero risk to the live system; (2) validating the *plan* (not one code path) covers **every** route, including A5's actual video route (`produce.py` integration would cover neither raw video nor DTC). **Strictness: hard wall** — any failed check → exit 1, reasons to stderr, empty stdout; all pass → exit 0 + `PREFLIGHT-OK`. Checks: bg_policy honored · IMAGE/VIDEO block prepended verbatim (with a `--print-block` helper) · no rendered text · correct route (product/Nova→DTC, b-roll→raw, photog→product-photoshoot, medium↔model sanity) · aspect matches template · video `--no-wait` · informed reuse ack. Demo + tests prove BLOCK vs PASS (`tests/test_preflight.py`). Also fixed bug #1 (see Part 0). Both verified at **0 credits**. Recipe in PIPELINE_RUNBOOK §10. A6 wraps the gate as the `acme-preflight` skill.

Open decisions before A1 starts:
- Which test video: **RESOLVED 2026-06-16 (Operator): `Properly made review with Nova and the Product.mp4`.** Chosen because it carries real spoken audio, which exercises the full M4 transcribe→caption path *and* the M5 overlay — the truest end-to-end validation. (Alternatives `acme_007_v5.mp4` and the latest Higgsfield job were not used.) Status: **A0 committed (branch `acme-migration`, 9cba238); A1 not yet started.**
- Caption style: **RESOLVED 2026-06-17 (Operator): ALL-CREAM uniform captions** (no green emphasis on talking-head reels; `UNIFORM_CREAM=true`). Deviates from SOUL.md's documented green "signature emphasis" → formal brand-book amendment deferred to cutover (Part 4), Devon's nod advised. Green retained on designed templates/covers. Recipe + every A1 gotcha captured in `PIPELINE_RUNBOOK.md`.
- **A1 status:** M4→M5 chain proven on ACME-007 (`output/jobs/ACME-007/`), 0 credits. Composition + runbook + this decision pending the A1 git commit.
- **A3 status (DONE 2026-06-17, 0 credits):** all 5 template families validated brand-correct through M5+M6 (`output/a3_qc/`, 15 renders, plain + reuse). Found + fixed a real bug — `render.py detect_size` was returning the 1080×1920 default for every non-9:16 template (carousel/callout/compound rendered with a banned white band); backward-compatible fix, story/poll templates unchanged. Wrapped into `post.py` (image analogue of `reel.py`: `brief.json type=image`, `bg_policy plain|reuse`, refuses `generate` so it can never spend a credit). Two brand calls resolved (Operator): (1) **story-poll brought into SOUL compliance** — added the brand bar (leaf badge + `ACME LABS` + `@acmelabs · acmelabs.co`), so all 5 families now carry the mandatory brand mark; (2) **reuse-bg = generic brand b-roll only** — product/spokesperson heroes are dynamic per-SKU content, never used as a `--bg-file` background. Image recipe + gotchas in PIPELINE_RUNBOOK §9.

---

## Part 2 — FUTURE PLAN (deferred modules, in order)

These build on the Content Generation Module's job-folder output. None are started until Part 1 is done and stable. Build order is F1 → F5; **F6 (cutover) is always last.**

| # | Module | What it is | Effort | Notes |
|---|---|---|---|---|
| F1 | **Publishing (Blotato)** ✅ built | Per-job: `publish.py` from the M6 package, per-platform captions, hard compliance gate, record `published_posts` | 🟡 Medium | **BUILT 2026-06-17** (0 credits). Flow first PROVEN on ACME-011 (→ X live + TikTok scheduled, Operator signed off) via a supervised semi-manual run, then **wrapped into `publish.py`** — one command, **dry-run by default** (`--go` to post), with a hard **compliance gate** (QC-pass flag · RUO on all Labs posts · Labs organic-only · banned-claims scan · media exists+aspect · X ≤280/0-hashtags) that runs in both modes. `copywriter.py` **bug #2 fixed** (per-platform captions: x/threads/facebook/linkedin). `blotato.py` bridge from F1 prototyping: `upload` (presigned PUT), `scheduleTime`→`scheduledTime`, post-status arg. Findings (RUNBOOK §11): **X threads DO chain** (follow-ups need per-post mediaUrls — `--also` is text-only, an enhancement); **YouTube = video only**; no first-comment field (hashtags in caption); can't delete a published post. **Still to build:** Instagram/Threads/FB Blotato connection (Operator's manual step — `publish.py` skips them with a warning); per-post thread images on X; post-status tracking; `published_posts` → **Supabase** (now logged to `<job>/published_posts.json`). |
| F2 | **Telegram review layer** ✅ built | `telegram.py` (`sendMediaGroup` + a review card) pushes each M6 package to a **DEDICATED** engine bot + private group (`ENGINE_TELEGRAM_BOT_TOKEN`/`ENGINE_TELEGRAM_CHAT_ID` — **separate from OpenClaw's FROZEN bot, never reused**); `approvals.py` parses `APPROVE/REJECT/REVISE/HOLD ACME-NNN` via `getUpdates` (idempotent offset) → **APPROVE writes `qc.json {"passed":true}`** (the M6 sign-off `publish.py` requires) + per-job `status.json` + note; `engine.py` applies §16 trust events to `engine_state.json` (no separate `trust.py`). | 🟡 Medium | **BUILT 2026-06-18** with F4 (0 credits). The human's eyes in Telegram REPLACE the M6 visual-QC step. Status/notes are local `status.json` (Supabase additive later). Recipe: PIPELINE_RUNBOOK §14. |
| F3 | **Research module** ✅ built | Manual-topic replacement: `research.py`, two modes, **0 Higgsfield credits**. **Mode A (topics)** — searchapi sweep (trends+news, cached) → the six SOUL §8 factors × `engine_state.topic_weights`, respects `blocked_topics`, prints a per-topic breakdown → top N. **Mode B (outliers/inbox)** — auto-mine YouTube by **view-velocity vs set median** + a **drop-a-link inbox** (any URL via `apify scrape` for social / `firecrawl scrape` for articles — was `blotato source`, swapped 2026-06-22) → extract pattern → **reconfigure** (clone the FORMAT, strip the claims, copywriter.py rewrites the hook in Research-Pharmacist voice + compliance) → Trending brief. Both → 1A.2 pillar presets (pillar→template+persona) + brand routing (labs RUO / health) → validated `brief.json` (+ `copy.json` + `research.json` provenance) → logged to `discovery_queue` + `daily_brief`. | 🟡🔴 Medium-Hard | **BUILT 2026-06-18** (0 credits). Decisions (Marvin): **local-JSON-first** (rows under `output/research/<date>/` via a storage-agnostic `DiscoveryStore`; Supabase `db.py` plugs in additively later) · **personas P1/P2/P3** (voice carried into copywriter.py; detail in `CONTENT_ENGINE_GUIDE §1`) · **auto-mine YouTube only**, TikTok/Reddit/IG/FB via drop-a-link (apify is priciest → fired once/URL, cached 7d). PROVEN both chains on one real run each: **ACME-013** (Mode A: Semaglutide 0.686 → stack/labs static-compound → rendered) + **ACME-014** (Mode B: 124.6× YouTube outlier → cloned `this_or_that` → Epithalon trending/labs story-reel → rendered), both brand-correct PNGs via `post.py`. **Deferred:** Supabase `db.py`; per-follower outlier normalization (needs a follower field apify doesn't expose — view-velocity used instead); carousel `slides.json` copy-gen (single-card fallback for now); auto TikTok/Reddit mining. Recipe: `PIPELINE_RUNBOOK.md §13`. |
| F4 | **Scheduling** ✅ built | **pure-Python launchd** (NOT headless `claude -p` — Marvin's call 2026-06-18: the only LLM cost stays `copywriter.py`, zero agent tokens): 4 jobs in `launchd/` — `produce` 05:30 → `review` 07:00 → `approvals` poll every 5m → `publish` at 08:00/11:00/13:00/16:00/19:00 PT (each slot publishes its own approved jobs). `install.sh` (un)loads them; permissions allowlist in `.claude/settings.json`. | 🟢 Easy (after F1–F3) | **BUILT 2026-06-18** (0 credits). Orchestrators: `produce_daily.py` (the `copy.json`→`captions.json` **bridge** + RUO on every Labs caption + X-fit) · `publish_slot.py` (slot inference, never double-posts, SOUL §19). **Supervised**: publish stays dry-run until `output/GO_LIVE`; `output/STOP` kill-switch; per-day caps (copy 30 / searchapi 20 / apify 3). 23:00 measure + Mon analytics are F5-era. Cloud `/schedule` unsuitable (local creds). Recipe: PIPELINE_RUNBOOK §14. |
| F5 | **Feedback loop (lite)** | Weekly weighted-scoring updater (Part 1A.6): reads `performance_data` → nudges pillar weights / format prefs / topic boosts / hook patterns / persona weighting in the `content_strategy_config` table (Supabase); Monday Telegram report | 🟡 Medium | Adopted from Devon's Stage 8 but de-scoped from "intelligence layer" to a weights updater. Needs months of data to matter. |
| F6 | **Parallel run + cutover** | 2–3 days dry-run (publish disabled) → 1 supervised live day → decommission (Part 4); drop the Sheet, keep only Supabase | 🟢 Easy, time-gated | OpenClaw stays fully operational until this point. The single switching moment. |
| F7 | **Autonomous reel (video) pipeline** | Extends Part 1 (`reel.py`) + F3 (research) + F4 (loop) so the engine RESEARCHES → SCRIPTS → generates → captions → posts **video reels**, not only images. The **only credit-bearing autonomous path** (Higgsfield) → concept is approved **before** any spend. | 🔴 Hard | **✅ BUILT 2026-06-18 — see "Module F7" below.** Reuses existing machinery (`higgsfield.py video`, `preflight.py`, `reel.py`, Whisper); net-new = `source_bank.py`/`script.py`/`reel_video.py`/`reel_captions.py` + reel-brief wiring. Proven 0-credit (79 tests); awaiting Marvin's OK for the first real Seedance generation (`REELS_LIVE`). |

### Module F7 — **autonomous reel (video) pipeline** · ✅ BUILT 2026-06-18

> **Status: BUILT & proven 0-credit; awaiting Marvin's OK for the first real Seedance generation.**
> New files (all additive): `source_bank.py` (RV0), `script.py` (RV2), `reel_video.py` (RV3),
> `reel_captions.py` (RV4) + tests `tests/test_{source_bank,script,concept_gate,reel_video,reel_captions,reel_push,reel_loop}.py`.
> Co-owned edits (additive, backward-compatible): `research.py` (Source Bank + `assemble_reel_brief`
> + `research.py bank` + `--reel`/weekly-mix), `engine.py` (`reel` 2/day cap + `reels_live()` switch
> + concept statuses), `telegram.py` (concept card + reel final-push via `sendVideo` + dict-caption
> fix), `approvals.py` (status-gated concept gate), `produce_daily.py` (reel state machine),
> `schemas/brief.schema.json` (`youtube` platform).
>
> **Flow:** `research.py {bank --format reel | inbox/outliers --reel}` → `type=reel` brief →
> `produce_daily.py run` (or `reel <job>`): **PHASE A** RV2 script → captions → **GATE 1** concept
> card (Telegram, "APPROVE spends ~1 credit") → APPROVE → **PHASE B** RV3 `reel_video.py` (preflight +
> VIDEO-block-verbatim + Seedance b-roll, no face/text; **only credit spend**; hard 2/day cap) →
> RV4 `reel_captions.py` (Kokoro TTS → mux → Whisper → reconcile-to-script → auto beat-group →
> `reel.py`) → **GATE 2** final video review → APPROVE → `publish.py` (TikTok + X + YouTube).
>
> **Two supervised switches (independent):** `output/GO_LIVE` (publishing) and **`output/REELS_LIVE`**
> (autonomous credit generation). Without `REELS_LIVE` the loop dry-runs RV3 (0 credits) and parks
> concept-approved reels. The concept gate is trust-neutral (trust moves only at the final gate).
>
> **Proven 0-credit:** Source Bank on the paid Diary-of-a-CEO source (5 angles, RED dropped, mined to
> ACME-020/021/022); RV1 schema-valid reel brief; RV2 script (RED-gated); GATE 1 (concept_qc, no trust,
> both gates coexist); RV3 dry-run (preflight PASS, gates block/pass) + `--owned-clip` 9:16 crop; RV4
> live Whisper transcribe→beats; GATE 2 video push + publish dry-run PASS (X/TikTok/YouTube); LOOP live
> Phase A. 79 F7 tests green. **Env-gated on the build box only** (the real Mac mini has them, like
> reel.py for ACME-007/012): Kokoro TTS (`kokoro-onnx`+`soundfile`) and the `reel.py` render browser.

### Planned module F7 (2026-06-18, Marvin) — **autonomous reel (video) pipeline**

**Why:** Devon's weekly mix (CONTENT_ENGINE_GUIDE §3.2) is **reel-heavy** — Trending Hook is mostly
reels; Science + Founder run reels weekly. But the 0-credit auto-loop (F4) makes only images/
carousels (`produce_daily.py` skips `type=reel`). Video *production* already works **manually**
(`reel.py`, proven on ACME-007/012) — it just isn't autonomous. F7 wires it, reusing every existing
tool; the only **net-new generation** is the spoken script + auto beat-grouping.

**Reuses (already built):** `research.py` (F3 — discovery is universal; **Mode B is already
video-native**: it scrapes a viral video → transcript + hook + structure + format) · Whisper
(`hyperframes transcribe`) · `higgsfield.py video` (seedance/kling + the verbatim brand VIDEO block)
· `poll_video.py` · `preflight.py` (the credit gate) · `reel.py` (caption-beats → `captioned.mp4` +
cover) · `publish.py` (already video-capable; YouTube = video-only).

**Chain (follows Devon stages 1→6 + the credit-first ordering, MIGRATION 1.1):**
- **RV1 · research → reel brief.** `research.py` emits a `type=reel` brief when the slot/weekly-mix
  calls for video (Devon §3.2). Mode B (outlier mining) is the natural source — it already clones a
  viral video's format. Brief carries topic/pillar/persona/brand/`reference` + the format recipe.
- **RV2 · script (NET-NEW).** A new `copywriter.py --kind script` (or `script.py`): researched angle
  + format recipe → a **15–45s spoken script, hook in the first 2s**, hook→build→payoff→CTA
  (VIRAL_FRAMEWORK retention structure), Research-Pharmacist voice + compliance (same engine as
  captions). Writes `brief.script`.
- **GATE 1 · concept approval BEFORE any credit.** TG card shows script + concept + `reference`;
  Marvin APPROVEs the *concept*. **No Higgsfield credit is spent on a rejected concept** (Devon
  stage 4→5; MIGRATION 1.1). This is the whole reason reels are concept-first.
- **RV3 · video prompt + gated generation (CREDITS).** Build the Higgsfield VIDEO prompt = brand
  VIDEO block **verbatim** (SOUL) + a **Seedance b-roll scene — NO face** (Marvin 2026-06-18; matches
  "Founder POV, no face"; no avatar/Soul/DTC route), **no on-screen text in the prompt** (burned in
  later). `preflight.py` → `higgsfield.py video --model seedance_2_0` (9:16) → `poll_video.py`.
  Governed by a **hard cap of 2 reels/day (1 typical)** in `engine.py` (Marvin 2026-06-18). Devon gives
  no explicit number, but his weekly mix (§3.2) works out to ~1–2 reels/day (Trending is a reel most
  days; Science adds a 2nd only Wed/Sun) — so 2/day is the ceiling. All other posts stay 0-credit.
- **RV4 · captions (reuse + NET-NEW beat-grouping).** Whisper transcribe → reconcile against
  `brief.script` (the schema's `script` field exists for exactly this) → **auto beat-group** (new
  LLM step: 3–5 words/beat, ≤2 lines, `UNIFORM_CREAM`, PIPELINE_RUNBOOK §2 rules) → `caption_data.json`
  → `reel.py` renders `captioned.mp4` + cover.
- **GATE 2 · final review.** TG card with the finished reel → Marvin APPROVEs → publish.
- **RV5 · publish.** `publish.py` (already video-capable) → TikTok + X (+ YouTube video-only).

**Governance:** reels are the ONLY autonomous credit spend → (a) concept-approved before generation,
(b) **hard 2 reels/day cap** in `engine.py`, (c) `preflight.py` unchanged, (d) **two** approval gates
(concept + final) vs one for free images. `STOP` / compliance-hold apply as everywhere.

### Planned sub-system (2026-06-18, Marvin) — **Source Bank: transcript harvest & reuse** (F3 + F7)

**Why (Marvin):** one expensive extraction on a long source — a 1-hour interview/podcast, long
YouTube — contains **far more than one post's worth** of material. Today Mode B scrapes a source, uses
a sliver, and discards the rest (and `apify.py`/`blotato.py` even truncate the transcript to ~4k/3k
chars). Bank the **full** extraction once, then mine it many times at **0 extraction cost** — this is
the main credit-saver for long-format sources, and it feeds BOTH carousels/images (F3) and reels (F7).

> **Update 2026-06-22:** the article extractor is now **Firecrawl** (`firecrawl.py scrape --raw`,
> markdown body), not Blotato — `normalize_payload` reads it. Social/video stays Apify. Read every
> `blotato source` mention below as Firecrawl-for-articles / Apify-for-social.

**Design:**
- **Extract once → bank.** When `research.py` mines/drops a source it pulls the **full** transcript via
  `apify scrape --raw` (social/video) / `firecrawl scrape --raw` (articles) and stores it in a source
  bank: `output/research/sources/<sha-url>.json` = `{ url, platform, scraped_at, full_transcript,
  caption, engagement, reference, angles:[] }`. (Local-JSON now; a Supabase `sources` table later — same
  additive path as `DiscoveryStore`.)
- **Propose angles.** A `copywriter.py` pass reads the transcript and proposes **N distinct content
  seeds** — each `{ angle, pillar, format (carousel|reel|callout), used:false }` — appended to `angles`.
  One scrape → a backlog of briefs.
- **Spend once, reuse N times.** Each brief is built from ONE unused angle, which is marked
  `used:true` + tagged with its `job_id`. Later runs (`research.py bank`) pull unused angles → new
  briefs with **zero extraction spend** (only the cheap copywriter call). A source is re-scraped only
  when stale (TTL) or exhausted; the existing apify 7-day cache already blocks accidental re-spend.
- **Provenance.** The `reference` block already carries the source `url`; add a segment/angle id so
  every produced post traces back to the **exact part** of the source it used.

**Open question for Marvin (before build):** keep beat-grouping **auto** from day one, or
**human-author the caption beats** for the first weeks (safer, semi-manual) while everything else runs
autonomously?

### Planned enhancement (2026-06-18, Marvin) — **reference provenance** (spans F3 → F2 → F1)

Every Mode-B post must record **the exact video that inspired it + why we picked it**, keep it
reviewable, surface it at approval time, and **never leak it into the published post.** Spec:

- **F3 (producer) — ✅ BUILT 2026-06-18.** A single `reference` object is attached to each
  `brief.json` + the `daily_brief` row (and to `research.json`):
  `{ url, platform, description (title + view/velocity), selection_rationale (one sentence, e.g.
  "124.57× the niche-baseline view velocity on youtube; scored 34/40; cloned the This-or-That
  structure"), cloned_format, extracted_hook (reference-only), scoring_breakdown }`. Mode A carries
  `selection_rationale` + signals, **no `url`**. Added an optional `reference` property to
  `brief.schema.json` (additive, backward-compatible). Proven: ACME-016 (Mode A) + ACME-017 (Mode B)
  carry it; the source claim *"tortures belly fat"* stayed in `extracted_hook` and was **absent from
  the caption** (copywriter.py never sees the reference). `daily_brief` mirrors it as
  `reference_url`/`reference_description`/`selection_rationale`.
- **Supabase** (still TODO) — when `db.py` lands, add `reference_url`, `reference_description`,
  `selection_rationale` (or a single JSONB `reference`) to `daily_brief`; propagate to `content_drafts`.
  The local `daily_brief.json` already carries these columns.
- **F2 (Telegram review)** — ✅ **DONE 2026-06-18.** `telegram.py build_card` reads `brief.reference`
  (fallback `research.json`) and appends **`📎 Reference: <description>`** + the reviewable URL for
  Mode B, or **`📎 Why: <selection_rationale>`** for Mode A (no source video). `research.py` also
  mirrors `source_url`/`source_platform`/`cloned_format` flat into `research.json` for legacy readers.
  (Old/pre-reference jobs like ACME-015 show no URL — correct, they predate the block + are Mode A.)
- **F1 (publish)** (still TODO) — the reference is **metadata only**; add a hard assertion to the
  publish compliance gate that no `reference_*` text appears in the caption. (Already true by
  construction — copywriter.py never receives the reference — but the gate should enforce it explicitly.)

> Sequencing: the **F3-producer half is done**; the **Supabase columns + F2 surfacing + F1 publish
> guard** land with F2/F1 work, after F4 (in flight in a parallel session).

### Social drop-link extraction — Apify + Blotato (2026-06-18, IG verdict corrected 2026-06-21)

> **⚠️ SUPERSEDED 2026-06-22 — historical record only.** Blotato is **no longer an extractor**. The
> shipped routing is: crawler-accessible text (article/blog/website) → **Firecrawl** (`firecrawl.py
> scrape`, the sole article reader); social/video (YouTube, Instagram, TikTok, Facebook, Threads,
> **X/Twitter** via the new `apidojo~tweet-scraper` actor) → **Apify**. Blotato = publish/schedule +
> backup images only; its `source` subcommand is deprecated and invoked by no pipeline path. The
> "Follow-up" at the end of this section is **VOID** (the opposite was implemented). See
> `skills/acme-engine/REFERENCE.md` §module-map + `TOOLS.md` for the live rule.

**Two extractors cover a dropped social link — Apify AND Blotato — and they overlap on the core video
platforms:**

- **`apify scrape` ([apify.py](apify.py))** — purpose-built actors for **YouTube, Instagram, TikTok,
  Facebook** (the `ACTORS` map). This is where `research.py` routes social URLs today. Priciest tool
  (`ENGINE_CAP_APIFY` = 3/day, a fresh paid actor run per URL, no per-URL cache).
- **`blotato source` ([blotato.py](blotato.py))** — **YouTube + TikTok are first-class and
  auto-detected** (`cmd_source`). It also accepts an explicit `--type`, passed straight through to
  Blotato's `create_source` as `sourceType` — so **IG/FB can be extracted through Blotato too** when
  the type is named. Cheaper than Apify and not on the 3/day cap, so **for YouTube + TikTok, Blotato is
  the preferred extractor**; reserve Apify for what Blotato can't do.

**IG correction (the old verdict was wrong).** The earlier line — "IG **cannot** ride the Blotato
link-drop" — was a mis-diagnosis. The 2026-06-18 failure (an IG reel coming back as a login-wall
`article` with title `"Down chevron icon"`) was the **auto-detector falling through to
`sourceType=article`** for the IG URL, NOT a hard Blotato limitation: `blotato.py cmd_source` only
auto-detects youtube/tiktok/article/text, so an `instagram.com` URL defaults to `article` (the login
wall). Naming the **explicit Instagram/Facebook type** makes Blotato use the right extractor. So IG/FB
**can** be link-dropped — via Apify (already wired) or Blotato-with-explicit-type.

**Honest caveat (unchanged):** Meta is auth-gated + JS-rendered, so IG/FB extraction is **best-effort**
on either tool — treat the result as fragile and lead with the human's one-line note. (Bulk-scraping a
user's *saved* IG collection is still not viable — that needs login/cookies, Part 5.1 — but a single
public IG/FB reel URL is fine.)

> **Follow-up (optional, not yet wired):** (1) add `instagram`/`facebook` branches to
> `blotato.py cmd_source` auto-detect so an IG/FB URL no longer defaults to `article`; (2) route
> `research.py` YouTube + TikTok drops to the cheaper `blotato source` (keeping Apify as fallback).
> Both need the exact Blotato `sourceType` strings confirmed against the live API before committing.
>
> **❌ VOID (2026-06-22):** neither was done — the engine went the **opposite** way. Blotato was
> removed from the extraction path entirely; ALL social/video (incl. X/Twitter) now extracts via Apify
> and all article/blog text via Firecrawl. See the SUPERSEDED banner at the top of this section.

---

## Part 3 — Architecture after full migration

```
launchd (Mac mini, always-on — same requirement OpenClaw has today)
  └─ headless `claude -p` runs (Claude Code CLI)
       ├─ research run ──► brief.json files            (F3)
       ├─ production run ──► M1→M6 job folders         (Part 1 — built first)
       ├─ review run ──► telegram.py previews          (F2)
       ├─ publish runs ──► approvals.py → blotato      (F1+F2)
       ├─ weekly analytics ──► performance_data (Supabase)  (F4)
       └─ weekly feedback ──► content_strategy_config       (F5)
```

What improves vs OpenClaw: Claude orchestrator (multi-step chains actually work; can visually QC rendered output), native CLAUDE.md injection (no more 61KB SOUL workaround), schedule that actually exists, fewer moving parts (no gateway/agent-routing daemon). Known trade-off: approvals become slot-synchronized instead of conversational chat — consistent with §15's existing 2-hour approval window. Cost: bounded number of headless runs/day vs flash-per-turn; watch the first week.

---

## Part 4 — OpenClaw non-interference & cutover rules

**Until cutover, the following are frozen (the running system must keep working):**

- `SOUL.md`, `TOOLS.md`, `AGENTS.md`, `IDENTITY.md`, `USER.md`, `HEARTBEAT.md`, `MEMORY.md` (workspace) — no edits
- `~/.openclaw/openclaw.json`, agent definitions, Telegram bindings, bot tokens — no edits
- No OpenClaw crons added/removed (there are currently none)
- Shared scripts (`produce.py`, `render.py`, `copywriter.py`, `sheetlog.py`, `sheets.py`, wrappers in `/opt/homebrew/bin`) — bug fixes only, backward-compatible, since OpenClaw calls the same files
- New files added by this plan (`MIGRATION.md`, `brief.json` jobs, `.claude/skills/*`, later `telegram.py`/`approvals.py`/`trust.py`) are **additive only** and not in OpenClaw's bootstrap set — invisible to the running agent

**Cutover (end of F6) is the single switching moment:** retire the `acme` agent binding in OpenClaw, drop the Google Sheet (Supabase becomes sole system-of-record), restructure `CLAUDE.md`/`ENGINE.md` for Claude Code as the sole orchestrator, and fold the TOOLS.md schema fix in then. Until that day, both systems coexist: OpenClaw = live operations, Claude Code = build + validation.

---

## Part 5 — Reconciliation with Devon's Implementation Guide v1.0

Devon's guide specifies a stack (Supabase + Trigger.dev + Creatomate + Claude API) that largely duplicates or conflicts with the engine already built. **We adopt his strategy (Part 1A) and his data layer (Supabase); we reject his orchestration/rendering plumbing (Trigger.dev, Creatomate).** Mapping of his 8 pipeline stages to our modules:

| Devon's stage | Our module | Verdict |
|---|---|---|
| 1 · DISCOVER (Apify/SearchAPI scrape) | F3 Research | ✅ Adopt — same tools. ⚠️ except scraping Devon's *saved IG posts* (see blockers). |
| 2 · SCORE & SELECT (persona/niche/intent scoring) | F3 + Part 1A.1 personas | ✅ Adopt scoring criteria into the brief-selection step. |
| 3 · GENERATE (copy + visual direction) | M2 copywriter.py + M1 brief | ✅ Adopt — `copywriter.py` already enforces brand voice + compliance. |
| 4 · TELEGRAM REVIEW (A/R/E approval) | F2 approvals.py | ✅ Adopt — maps to APPROVE/REJECT/REVISE flow. |
| 5 · PRODUCE VISUALS (**Creatomate**) | **M3–M5 Higgsfield + HyperFrames + produce.py** | ❌ **Reject Creatomate.** Our core already does this and Creatomate can't match HyperFrames synced captions. This is the whole point of Part 1. |
| 6 · SCHEDULE & PUBLISH (Blotato) | F1 Publishing | ✅ Adopt — same tool. |
| 7 · MEASURE (Apify scrape-back) | F4 analytics backfill | ✅ Adopt — fragile but same approach we planned. |
| 8 · FEEDBACK LOOP | F5 Feedback (lite) | ⚠️ Adopt de-scoped — weights updater, not an intelligence layer. |
| Infra: **Supabase** (7 tables + storage) | **Supabase cloud Postgres** (system-of-record) + `output/jobs/` for media files | ✅ **Adopt** (decided 2026-06-16). Sheets dropped at cutover. Schema via CLI migrations; runtime via `db.py`/supabase-py. Right tool for the relational scoring/feedback work. |
| Infra: **Trigger.dev** (orchestration) | Claude Code + launchd (F4) | ❌ **Reject.** Cloud workflow runner can't call local higgsfield CLI / Playwright / ffmpeg / HyperFrames. Visual stage is local-only by physical necessity. |
| Infra: **Claude API** | OpenRouter (copywriter.py) | ⚠️ Keep OpenRouter — same models, already wired. |

### Part 5.1 — External dependencies

**Owned by Marvin (no Devon needed):**
- **IG / Threads / FB publishing** — simple Blotato account connection, easy. Not a Meta-review blocker.
- **Trending-Hook source videos** — Marvin pulls curated videos manually (scraping Devon's saved IG posts is not viable: no API, cookie-scraping risks the account). Optional upgrade later: Devon drops links into a Telegram channel the engine reads.

**Physician validation — fully solved by the research engine + Marvin's policy. NO Devon dependency (decided 2026-06-16):**
- Social Proof / "physician" angle is satisfied **only** by third-party published research framed as external (handled by F3: `acme-searchapi` + `acme-firecrawl` + PubMed, SOUL §7 — same machinery as Pillar 1).
- The engine **never** cites, names, or implies a physician *for Acme*, and never presents medical validation as Acme's own. This is the legally conservative line Marvin set (Part 1A). It removes the prior one-line Devon confirmation — there is now **zero external Devon blocker** for the content build.

### Part 5.2 — Volume / cost reality

Devon's 5×/day = +67% over current 3×/day. Higgsfield credits are a **budget lever, not a hard ceiling** — Acme is on the $145 tier (2nd-highest) and Devon can upgrade if needed. So credits are *managed*, not a blocker. We still default to free local rendering as good economics: most daily posts render at **0 credits** (carousels, statics, text-on-screen reels via produce.py); paid generation is reserved for posts that genuinely need new footage. No reason to spend a credit on something produce.py renders for free.
