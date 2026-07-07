# Acme Knowledge Base — Index

> Map of content for the whole repo. One topic = one file; everything is linked
> from here. Root-level `.md` files are the OpenClaw auto-injected set and stay
> at root — everything on-demand lives under `docs/`.

## Always-loaded (repo root — OpenClaw auto-injects these every turn)

| File | What it is |
|------|------------|
| [SOUL.md](../SOUL.md) | **Single source of truth**: brand hard-constraints, verbatim IMAGE/VIDEO Brand Prompt Blocks, full brand book, full engine spec (§1–§22). Edit rules HERE. |
| [AGENTS.md](../AGENTS.md) | Who the agent is, operating modes, red lines. |
| [TOOLS.md](../TOOLS.md) | Tool/skill command reference. |
| [MEMORY.md](../MEMORY.md) | Agent long-term facts + workflow conventions. |
| [IDENTITY.md](../IDENTITY.md) / [USER.md](../USER.md) / [HEARTBEAT.md](../HEARTBEAT.md) | OpenClaw bootstrap: identity, operator, heartbeat cadence. |
| [CLAUDE.md](../CLAUDE.md) | Pointer stub for Claude Code sessions → SOUL.md + this index. |

## Operations (read on demand)

- **[PIPELINE_RUNBOOK.md](PIPELINE_RUNBOOK.md)** — every production recipe with gotchas: §1 reel build, §2 caption rules, §5 visual QC, §9 post/carousel render, §10 preflight gate, §11 publish/schedule. The `.claude/skills/acme-*` skills are thin wrappers over these sections.
- **[TEMPLATES.md](TEMPLATES.md)** — template-family tracker: what exists in `templates/src/`, wiring status, rendering guardrails.
- **[PRODUCTS.md](PRODUCTS.md)** — product catalog reference (class, spec, price, `/shop/` slug, COA framing). Synced from the live-site JS bundle 2026-06-23; **the live site acmelabs.co/shop always wins** — re-pull the bundle if in doubt. Rotation pool = `engine_state.topic_weights`, not this file.
- [launchd/README.md](../launchd/README.md) — timer install/uninstall (currently **uninstalled — MANUAL mode** since 2026-06-23).

## Strategy

- **[CONTENT_ENGINE_GUIDE.md](CONTENT_ENGINE_GUIDE.md)** — Devon's implementation guide v1, adapted to our stack (personas, scoring, format rotation).
- **[VIRAL_FRAMEWORK.md](VIRAL_FRAMEWORK.md)** — the full @instacoachmike viral playbook; read before producing any short-form/viral content (only summarized in SOUL.md §9).

## Archive (superseded / historical — do not edit)

- [MIGRATION.md](archive/MIGRATION.md) — the OpenClaw → Claude Code migration plan. Historical: the Claude Code engine has been production since 2026-06-18.
- [BRAND.md](archive/BRAND.md) / [SYSTEM_CONTEXT.md](archive/SYSTEM_CONTEXT.md) — pointer stubs; their content was consolidated verbatim into SOUL.md.
- [Devon-Implementation-Guide-v1.0.pdf](archive/Devon-Implementation-Guide-v1.0.pdf) — source PDF for CONTENT_ENGINE_GUIDE (v2 PDF is the live SOP, held by Marvin).

## Code map

| Path | Contents |
|------|----------|
| `*.py` (root) | Live engine modules — flat imports, launchd-referenced; **do not move**. Core: `engine.py`, `research.py`, `produce_daily.py`, `produce.py`, `publish.py`, `telegram.py`, `approvals.py`, `compliance.py` (claims authority), `catch_approvals.py` (Devon 👍 watcher). |
| `templates/src/` | Render templates (story-reel, carousel square/vertical, statics, covers, post sets). `templates/archive/` = retired explorations. |
| `assets/` | Brand SVGs (logo icon, wordmark cream/forest) + `product_images/<SKU>/` real product photos. |
| `skills/` | OpenClaw skills (acme-* ours; higgsfield-*/nano-banana installed, gitignored). |
| `.claude/skills/` | Claude Code recipe skills: acme-post / acme-preflight / acme-publish / acme-reel → wrap PIPELINE_RUNBOOK sections. |
| `schemas/` | brief / decision JSON schemas. |
| `tests/` | pytest suite. |
| `launchd/` | Timer plists + install.sh (uninstalled while in MANUAL mode). |
| `scratch/` | One-off scripts + retired experiments — see [scratch/README.md](../scratch/README.md). Nothing live. |
| `output/`, `logs/`, `memory/`, `asset_cache/` | Gitignored runtime state. Job folders in `output/engine/<JOB-ID>/`; live trackers: `output/engine/reels_tracker.md`, `decisions.jsonl`, `devon_shortlist.md`. |
| `engine_state.json` | Gitignored live state; tracked seed = `engine_state.example.json`. |

## Conventions (second-brain rules for this KB)

1. **One source of truth per fact.** Brand/engine rules → SOUL.md. Product facts → live site (PRODUCTS.md is a synced mirror). Recipes → PIPELINE_RUNBOOK.md. Never duplicate — link.
2. **New knowledge goes in `docs/`** as its own `.md`, linked from this index the same day.
3. **Superseded ≠ deleted** — move it to `docs/archive/` with a banner saying what replaced it.
4. **Runtime state never goes in docs** — it lives in `output/` / `engine_state.json` and is gitignored.
