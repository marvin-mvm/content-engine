# SYSTEM_CONTEXT — Acme Content Engine (pointer)

> **Consolidated into [SOUL.md](SOUL.md).**
>
> The full engine spec — §1 pipeline, §3 tool stack, §4 daily run sequence, §5 slots & content mix, §6 platform/caption specs, §7 research pipeline, §8 topic scoring, §9 viral structures, §10 caption rules, §11 hashtags, §12 compliance, §13 templates, §14 layout specs, §15 trust score, §16 score events, §17 production router (incl. the video `--no-wait` + self-removing cron poll flow), §18 Blotato package spec, §19 failure handling, §20 Telegram commands, §21 QC checklist, §22 VA SOP — now lives in `SOUL.md` (section "ENGINE SPEC") as the single source of truth.
>
> **Why:** OpenClaw does not auto-inject `SYSTEM_CONTEXT.md` (only `AGENTS/SOUL/TOOLS/IDENTITY/USER/HEARTBEAT/MEMORY` are auto-loaded). The engine spec was moved into `SOUL.md`, which is always in context every turn.
>
> **Do not duplicate engine content here.** Edit `SOUL.md`.
>
> Platform reminder (also in SOUL.md): this engine runs on **OpenClaw**, not a standalone `engine.js`. No local Puppeteer renderer — all media via Higgsfield; text burned in post via `overlay.py`/ffmpeg or a Blotato template; publishing via Blotato; research via searchapi/firecrawl/apify.
