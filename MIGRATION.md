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
| Engine code is NOT in git | `produce.py`, `render.py`, `copy.py`, `sheetlog.py`, `poll_video.py`, `templates/`, `skills/` all untracked. Only .md files committed. |
| Doc contradiction injected every turn | `TOOLS.md` still documents the old 11-col `A:K append` sheet schema; `SOUL.md` §17b mandates 12-col `A:L insert`. Live sheet verified 12-col. |
| Pipeline scripts themselves are solid | produce/render/copy/sheetlog reviewed line-by-line; all skill binaries are PATH wrappers exec'ing workspace scripts (no drift). They run standalone — **no OpenClaw dependency**. |

**Gap estimate (per Operator): >50% of the engine is unbuilt** — research automation, publishing automation, approvals, scheduling. What works today: brand-compliant asset generation on demand.

Known bugs to fix during the relevant phases (none are urgent):

1. ✅ **FIXED (Phase A4).** `poll_video.py` didn't pass `--prompt` to produce.py → Content Matrix col F got the local mp4 path instead of the generation prompt (which sat unused in `job["params"]["prompt"]`). Fix: extract the prompt from the completed job (`params.prompt`, verified against a real `generate list --json`; same lookup chain as `copy.py`) and pass it as `--prompt`. Backward-compatible (no prompt found → unchanged behavior; PENDING/FAILED/DONE contract + cron self-cleanup untouched; `--no-log` deliberately NOT added — it's the live-post path). Argv construction tested in isolation (`tests/test_poll_video.py`, no live-sheet write).
2. `copy.py --platform` lacks `linkedin` / `threads` (SOUL §6 requires 6 unique captions). Fix when publishing module is built.
3. `produce.py --model` help text says default `flux_1_1_pro`; actual default is `gpt_image_2`. Cosmetic.
4. Decoy templates `story-reel.html` / `story-reel-preview.html` still in `templates/src/` ("do NOT use" per MEMORY.md). Archive in Phase A0.
5. `render.py` fetches Google Fonts from network at render time; `hyperframes-captions/fonts/` shows the embedded-font pattern to copy. Optional.
6. `copy.py` banned-claims regex misses "treatment / prevention / heals" variants. Optional hardening.
7. Junk in repo root: stray `Sheet1!A1` file (accidental shell redirect), `overlay_preview_v2–7.jpg`, test mp4s. Clean in Phase A0.

---

## Part 1A — Content Strategy (ADOPTED from Devon's Implementation Guide v1.0)

**Decision (2026-06-11, Marvin):** adopt the strategy layer of Devon's guide wholesale. It is strong and stack-agnostic. We map it onto the existing Acme production core (Higgsfield → HyperFrames → produce.py) rather than onto Devon's proposed tools — see the reconciliation in Part 5 for what is rejected and why. This section is the *what/why*; Part 1 is the *how*. The North-Star goal is Devon's: **100K organic followers across Instagram + TikTok in 6 months via a self-improving engine posting 5×/day.**

**Scope (2026-06-16, Marvin):** run it **dual-brand on a combined account**, exactly as Devon's guide specifies — Labs and Health both. Brand-per-post routing stays (`copy.py --brand labs|health`): Labs = research/education content, organic only, RUO framing; Health = protocol/metabolic/results content, may run paid. Labs supplies credibility, Health carries the protocol/results pillars. (Labs-only was considered and rejected: RUO bars human-use content, which would gut the Stack-of-the-Day and Social-Proof pillars.)

**Physician/medical-claim policy (2026-06-16, Marvin) — legally conservative:** the engine will **never cite, name, or imply a physician acting for Acme**, and never present medical validation as Acme's own. Social Proof and any "physician/expert" angle is satisfied **only by third-party published research framed as external** ("a 2024 study found…", "researchers report…") — never "our doctor" / "Acme's physician" / "our medical team." This removes the only remaining Devon dependency entirely (see Part 5.1).

**Data layer (2026-06-16, Marvin) — Supabase, Sheets dropped:** the system-of-record for all structured data (Devon's 7 tables: discovery_queue, daily_brief, content_drafts, ready_to_publish, published_posts, performance_data, content_strategy_config) is **cloud Postgres on Supabase**, not Google Sheets. Schema is managed via the **Supabase CLI** (migration files → `db push`); the engine reads/writes rows at runtime via a small `db.py` (supabase-py), not the CLI. Human review is via querying Claude Code or the Supabase Studio dashboard — **no Sheet.** Rationale: the feedback loop is relational query work (30-day GROUP BY aggregations) that Sheets does badly, and Sheets-as-DB already caused a real cost problem (`acme-token-cost-fix`: $0.50/call from unbounded reads). **All "sheet"/"Content Matrix"/"cols K/L" references in Parts 1–3 and the F-series below now mean Supabase tables.** ⚠️ **Sequencing + OpenClaw safety:** dropping the Sheet is a **cutover action** (Part 4), not a build-time one — the live OpenClaw engine still writes to the Sheet via `sheetlog.py`/`produce.py`. During the build Supabase is **additive**: new Claude Code modules log to Supabase; the shared scripts keep their Sheet path until cutover, then it's removed. The content-generation module (Part 1) stays DB-light (job folders + one log row); Supabase matters mainly for F3/F4/F5.

### 1A.1 Personas — tag EVERY brief before generation

The system must know who it is writing for; persona drives voice and hook style.

| ID | Persona | Voice for this persona |
|----|---------|------------------------|
| P1 | **The Optimizer** (primary) | Data-dense, ROI/return language, mechanism + numbers |
| P2 | **The Health-Forward Affluent Woman** (secondary) | Aspirational, premium, outcome- and lifestyle-framed |
| P3 | **The Curious Newcomer** | Plain English, curiosity hooks, define everything |

> ⚠️ Devon's detailed persona definitions (demographics/psychographics tables 1.1–1.3) were **blank in the source paste** — fill from his real tables before build. Until then, only the names/roles + voice rule above are captured. Persona is a hard `brief.json` field (see M1).

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

IG / Threads / FB are a simple Blotato account connection Marvin owns — **not** an external Meta-review blocker. `copy.py` gains `--platform threads` and `--platform x` variants; per-platform caption generation is a hard requirement (never the same text verbatim).

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
M1 brief.json ──► M2 copy.py ──► M3 visual ──► M4 HyperFrames ──► M5 produce.py ──► M6 QC gate
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

**M2 — Copy.** `copy.py "<topic>" --brand … > jobs/ACME-NNN/copy.json` — overlay tokens + caption + hashtags + alt text, compliance-enforced. Cost: OpenRouter pennies.

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
| **A5 — First live fire** | ONE image generation → full chain → QC. Then ONE video generation → full chain → QC | 🟢 Easy | **1 image + 1 video — the entire validation budget** |
| **A6 — Skill-ify** | `.claude/skills/acme-reel` + `.claude/skills/acme-post` encoding the recipes; new Claude-Code-local `CLAUDE.local` notes if needed. **Do NOT edit the repo `CLAUDE.md` stub yet** (OpenClaw-era pointer; replaced only at cutover, Part 4) | 🟢 Easy | 0 |

**Credits are touched exactly once, in A5, after everything downstream is proven.**

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
| F1 | **Publishing (Blotato)** 🟡 prototyped | Per-job: `acme-blotato publish` from the M6 package, per-platform captions, write `published_posts` row in Supabase | 🟡 Medium | **Flow PROVEN 2026-06-17** (ACME-011 → X live + TikTok scheduled, 0 credits, Operator signed off) via a supervised semi-manual run. ✅ Confirmed: `blotato.py` needs **public URLs** → added `upload` (presigned PUT). Fixed real bugs: `scheduleTime`→`scheduledTime`, post-status arg. Findings (PIPELINE_RUNBOOK §11): **X threads don't chain via Blotato** (use single opinion tweet); **YouTube = video only** (no image/community posts); no first-comment field (hashtags in caption); can't delete a published post. **Still to build:** the `publish.py` runner (dry-run default + compliance gate + `published_posts` log), `copy.py` per-platform captions (bug #2: x/threads/fb/linkedin), Instagram connection. |
| F2 | **Telegram review layer** | `telegram.py` (sendPhoto/sendVideo/sendMediaGroup using existing bot token in `.env`) posts M6 packages to the managers' group; `approvals.py` parses `APPROVE/REJECT/REVISE ACME-NNN` replies via `getUpdates` → updates `content_drafts.status` + `review_notes` in Supabase; `trust.py` applies §16 score events | 🟡 Medium | Implemented LAST per Operator. Until then: review happens directly in Claude Code / job folders. |
| F3 | **Research module** | Manual-topic replacement: searchapi/firecrawl/apify sweep per SOUL §7, scoring per §8 → `discovery_queue` + `daily_brief` rows in Supabase → `brief.json` files | 🟡🔴 Medium-Hard | Fully separable — M1 contract means research just *produces briefs*. |
| F4 | **Scheduling** | macOS launchd → headless `claude -p` runs: 05:00 research · 05:30 production (5 pillars) · 07:00 review packages · **publish at 08:00 / 11:00 / 13:00 / 16:00 / 19:00 PT** (5 pillar slots, Part 1A) each preceded by an approval check · 23:00 measure (Stage 7) · Mon 09:00 analytics + weekly report. Permissions allowlist in `.claude/settings.json` so runs never stall | 🟢 Easy (after F1–F3) | Cloud `/schedule` routines are NOT suitable (no local higgsfield/ffmpeg/Playwright/creds). Local launchd only. |
| F5 | **Feedback loop (lite)** | Weekly weighted-scoring updater (Part 1A.6): reads `performance_data` → nudges pillar weights / format prefs / topic boosts / hook patterns / persona weighting in the `content_strategy_config` table (Supabase); Monday Telegram report | 🟡 Medium | Adopted from Devon's Stage 8 but de-scoped from "intelligence layer" to a weights updater. Needs months of data to matter. |
| F6 | **Parallel run + cutover** | 2–3 days dry-run (publish disabled) → 1 supervised live day → decommission (Part 4); drop the Sheet, keep only Supabase | 🟢 Easy, time-gated | OpenClaw stays fully operational until this point. The single switching moment. |

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
- Shared scripts (`produce.py`, `render.py`, `copy.py`, `sheetlog.py`, `sheets.py`, wrappers in `/opt/homebrew/bin`) — bug fixes only, backward-compatible, since OpenClaw calls the same files
- New files added by this plan (`MIGRATION.md`, `brief.json` jobs, `.claude/skills/*`, later `telegram.py`/`approvals.py`/`trust.py`) are **additive only** and not in OpenClaw's bootstrap set — invisible to the running agent

**Cutover (end of F6) is the single switching moment:** retire the `acme` agent binding in OpenClaw, drop the Google Sheet (Supabase becomes sole system-of-record), restructure `CLAUDE.md`/`ENGINE.md` for Claude Code as the sole orchestrator, and fold the TOOLS.md schema fix in then. Until that day, both systems coexist: OpenClaw = live operations, Claude Code = build + validation.

---

## Part 5 — Reconciliation with Devon's Implementation Guide v1.0

Devon's guide specifies a stack (Supabase + Trigger.dev + Creatomate + Claude API) that largely duplicates or conflicts with the engine already built. **We adopt his strategy (Part 1A) and his data layer (Supabase); we reject his orchestration/rendering plumbing (Trigger.dev, Creatomate).** Mapping of his 8 pipeline stages to our modules:

| Devon's stage | Our module | Verdict |
|---|---|---|
| 1 · DISCOVER (Apify/SearchAPI scrape) | F3 Research | ✅ Adopt — same tools. ⚠️ except scraping Devon's *saved IG posts* (see blockers). |
| 2 · SCORE & SELECT (persona/niche/intent scoring) | F3 + Part 1A.1 personas | ✅ Adopt scoring criteria into the brief-selection step. |
| 3 · GENERATE (copy + visual direction) | M2 copy.py + M1 brief | ✅ Adopt — `copy.py` already enforces brand voice + compliance. |
| 4 · TELEGRAM REVIEW (A/R/E approval) | F2 approvals.py | ✅ Adopt — maps to APPROVE/REJECT/REVISE flow. |
| 5 · PRODUCE VISUALS (**Creatomate**) | **M3–M5 Higgsfield + HyperFrames + produce.py** | ❌ **Reject Creatomate.** Our core already does this and Creatomate can't match HyperFrames synced captions. This is the whole point of Part 1. |
| 6 · SCHEDULE & PUBLISH (Blotato) | F1 Publishing | ✅ Adopt — same tool. |
| 7 · MEASURE (Apify scrape-back) | F4 analytics backfill | ✅ Adopt — fragile but same approach we planned. |
| 8 · FEEDBACK LOOP | F5 Feedback (lite) | ⚠️ Adopt de-scoped — weights updater, not an intelligence layer. |
| Infra: **Supabase** (7 tables + storage) | **Supabase cloud Postgres** (system-of-record) + `output/jobs/` for media files | ✅ **Adopt** (decided 2026-06-16). Sheets dropped at cutover. Schema via CLI migrations; runtime via `db.py`/supabase-py. Right tool for the relational scoring/feedback work. |
| Infra: **Trigger.dev** (orchestration) | Claude Code + launchd (F4) | ❌ **Reject.** Cloud workflow runner can't call local higgsfield CLI / Playwright / ffmpeg / HyperFrames. Visual stage is local-only by physical necessity. |
| Infra: **Claude API** | OpenRouter (copy.py) | ⚠️ Keep OpenRouter — same models, already wired. |

### Part 5.1 — External dependencies

**Owned by Marvin (no Devon needed):**
- **IG / Threads / FB publishing** — simple Blotato account connection, easy. Not a Meta-review blocker.
- **Trending-Hook source videos** — Marvin pulls curated videos manually (scraping Devon's saved IG posts is not viable: no API, cookie-scraping risks the account). Optional upgrade later: Devon drops links into a Telegram channel the engine reads.

**Physician validation — fully solved by the research engine + Marvin's policy. NO Devon dependency (decided 2026-06-16):**
- Social Proof / "physician" angle is satisfied **only** by third-party published research framed as external (handled by F3: `acme-searchapi` + `acme-firecrawl` + PubMed, SOUL §7 — same machinery as Pillar 1).
- The engine **never** cites, names, or implies a physician *for Acme*, and never presents medical validation as Acme's own. This is the legally conservative line Marvin set (Part 1A). It removes the prior one-line Devon confirmation — there is now **zero external Devon blocker** for the content build.

### Part 5.2 — Volume / cost reality

Devon's 5×/day = +67% over current 3×/day. Higgsfield credits are a **budget lever, not a hard ceiling** — Acme is on the $145 tier (2nd-highest) and Devon can upgrade if needed. So credits are *managed*, not a blocker. We still default to free local rendering as good economics: most daily posts render at **0 credits** (carousels, statics, text-on-screen reels via produce.py); paid generation is reserved for posts that genuinely need new footage. No reason to spend a credit on something produce.py renders for free.
