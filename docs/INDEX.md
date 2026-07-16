# Acme Knowledge Base — Index

> Map of content for the whole repo. One topic = one file; everything is linked
> from here. Root-level `.md` files are the OpenClaw auto-injected set and stay
> at root — everything on-demand lives under `docs/`.

## Always-loaded (repo root — OpenClaw auto-injects these every turn)

> **Removed for publication.** In production, a set of agent-identity files lived at the repo
> root (`SOUL.md` — the single-source brand + engine spec, `AGENTS.md`, `TOOLS.md`, `MEMORY.md`,
> `IDENTITY.md`, `USER.md`, `HEARTBEAT.md`, `CLAUDE.md`) and were auto-injected into the agent's
> context every turn. They contained the client's brand book and operator details, so they are
> not part of the public edition. References to `SOUL §n` throughout the docs point to them.

## Operations (read on demand)

- **[PIPELINE_RUNBOOK.md](PIPELINE_RUNBOOK.md)** — every production recipe with gotchas: §1 reel build, §2 caption rules, §5 visual QC, §9 post/carousel render, §10 preflight gate, §11 publish/schedule. The `.claude/skills/acme-*` skills are thin wrappers over these sections.
- **[TEMPLATES.md](TEMPLATES.md)** — template-family tracker: what exists in `templates/src/`, wiring status, rendering guardrails.
- **[PRODUCTS.md](PRODUCTS.md)** — product catalog reference (class, spec, price, `/shop/` slug, COA framing). Synced from the live-site JS bundle 2026-06-23; **the live site acmelabs.co/shop always wins** — re-pull the bundle if in doubt. Rotation pool = `engine_state.topic_weights`, not this file.
- [launchd/README.md](../launchd/README.md) — timer install/uninstall (currently **uninstalled — MANUAL mode** since 2026-06-23).

## Strategy

- **[CONTENT_ENGINE_GUIDE.md](CONTENT_ENGINE_GUIDE.md)** — Devon's implementation guide v1, adapted to our stack (personas, scoring, format rotation).
- **[VIRAL_FRAMEWORK.md](VIRAL_FRAMEWORK.md)** — the full @instacoachmike viral playbook; read before producing any short-form/viral content (only summarized in SOUL.md §9).

## Archive (superseded / historical)

> **Removed for publication** — `docs/archive/` held the OpenClaw→Claude Code migration plan,
> brand-book pointer stubs, and the client's strategy PDF (the source for CONTENT_ENGINE_GUIDE.md).

## Code map

| Path | Contents |
|------|----------|
| `*.py` (root) | Live engine modules — flat imports, launchd-referenced; **do not move**. Core: `engine.py`, `research.py`, `produce_daily.py`, `produce.py`, `publish.py`, `telegram.py`, `approvals.py`, `compliance.py` (claims authority), `catch_approvals.py` (Devon 👍 watcher). |
| `templates/src/` | Render templates (story-reel, carousel square/vertical, statics, covers, post sets). `templates/archive/` = retired explorations. |
| `assets/` | **Removed for publication** — brand SVGs and real product photography. |
| `skills/` | OpenClaw skills (acme-* ours; higgsfield-*/nano-banana installed, gitignored). |
| `.claude/skills/` | **Removed for publication** — Claude Code recipe skills (post / preflight / publish / reel) that wrapped PIPELINE_RUNBOOK sections. |
| `schemas/` | brief / decision JSON schemas. |
| `tests/` | pytest suite. |
| `launchd/` | Timer plists + install.sh (uninstalled while in MANUAL mode). |
| `scratch/` | **Removed for publication** — one-off scripts + retired experiments. Nothing live. |
| `output/`, `logs/`, `memory/`, `asset_cache/` | Gitignored runtime state. Job folders in `output/engine/<JOB-ID>/`; live trackers: `output/engine/reels_tracker.md`, `decisions.jsonl`, `devon_shortlist.md`. |
| `engine_state.json` | Gitignored live state; tracked seed = `engine_state.example.json`. |

## Conventions (second-brain rules for this KB)

1. **One source of truth per fact.** Brand/engine rules → SOUL.md. Product facts → live site (PRODUCTS.md is a synced mirror). Recipes → PIPELINE_RUNBOOK.md. Never duplicate — link.
2. **New knowledge goes in `docs/`** as its own `.md`, linked from this index the same day.
3. **Superseded ≠ deleted** — move it to `docs/archive/` with a banner saying what replaced it.
4. **Runtime state never goes in docs** — it lives in `output/` / `engine_state.json` and is gitignored.
