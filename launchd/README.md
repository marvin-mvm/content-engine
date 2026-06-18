# Acme engine — launchd schedule (F4)

Local macOS `launchd` jobs that drive the autonomous **produce → review → publish** loop.
Cloud `/schedule` routines are unsuitable (no local higgsfield/ffmpeg/Playwright/creds) —
this is local-only by physical necessity (MIGRATION F4). **0 Higgsfield credits.**

> launchd fires on the machine's **local time**. This Mac is `America/Los_Angeles`, so the
> hours below are PT directly. If the machine TZ ever changes, re-derive the hours.

| Job (`co.acme.engine.*`) | When (PT) | Runs | What |
|---|---|---|---|
| `produce`   | 05:30 daily        | `produce_daily.py run --carousel` | research → render → captions.json bridge → manifest |
| `review`    | 07:00 daily        | `telegram.py push-day`            | push the day's produced jobs to the review group |
| `approvals` | every 5 min        | `approvals.py poll`               | drain APPROVE/REJECT/REVISE replies (writes qc.json) |
| `publish`   | 08/11/13/16/19     | `publish_slot.py`                 | publish that slot's APPROVED jobs (X + TikTok) |

## Operate

```bash
./install.sh install     # generate plists for THIS checkout + load all 4 jobs
./install.sh status      # show what's loaded
./install.sh uninstall   # unload + remove
```

## Safety switches (all live under `output/`, all gitignored)

- **`output/STOP`** — kill-switch. `touch output/STOP` halts every step instantly; `rm` resumes.
- **`output/GO_LIVE`** — go-live switch. **Absent ⇒ publishing is DRY-RUN (supervised).**
  `touch output/GO_LIVE` flips `publish_slot.py` to live `--go`. Flip this only after you've
  watched a few supervised days (publishing to Blotato is irreversible — RUNBOOK §11 P4).
- **Spend caps** — `engine.py` enforces per-day ceilings (copy 30 / searchapi 20 / apify 3),
  overridable via `.env` (`ENGINE_CAP_COPY` …). Inspect: `python3 engine.py`.
- **Compliance hold** (SOUL §16) — if `engine_state.compliance_hold` is true, `publish_slot`
  refuses to post until the owner clears it (RESUME PUBLISHING).

## Prerequisite — the DEDICATED bot

`review` + `approvals` need a bot **separate from OpenClaw's** (frozen). Create
`AcmeContentBot` via @BotFather + a private review group, then add to `.env`:

```
ENGINE_TELEGRAM_BOT_TOKEN=...
ENGINE_TELEGRAM_CHAT_ID=...     # the private group's chat id
```

Until those exist, `review`/`approvals` no-op safely; `produce` + supervised `publish`
(dry-run) still work. **Never** reuse `TELEGRAM_BOT_TOKEN` (OpenClaw's).

## Recommended bring-up order

1. Create the bot + group; add `ENGINE_TELEGRAM_*` to `.env`.
2. `./install.sh install` — timers start; publishing stays dry-run (no `GO_LIVE`).
3. Watch a few days: produce fires 05:30, review pushes 07:00, you APPROVE in Telegram,
   publish slots show "WOULD publish" in `logs/engine.publish.log`.
4. When satisfied: `touch output/GO_LIVE` to go live. `rm` it (or `touch output/STOP`) to stop.
