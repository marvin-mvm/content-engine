#!/usr/bin/env python3
"""reel_video.py — F7 RV3: generate the Seedance b-roll for a reel. THE credit spend.

This is the ONLY module in the whole engine that spends Higgsfield credits, so it is wrapped
in hard gates and is DRY-RUN by default. Credits are spent ONLY when you pass --go, and only
after every gate below passes:

  G1  brief is type=reel
  G2  concept_qc.json present + passed     — GATE 1 concept-approved (credit-first, MIGRATION 1.1)
  G3  engine not STOP and not compliance_hold
  G4  engine reel REAL-CREDIT cap has headroom — HARD 135 real credits/day (engine.budget_remaining)
  G5  preflight.py PASS (per clip)          — VIDEO block VERBATIM + route=video + seedance_2_0
                                              + --no-wait + --reuse-checked (its exit code IS the guard)
  G6  live Higgsfield wallet >= this reel's estimated cost (the actual money; wallet_balance())

A reel is no longer ONE looping clip (Marvin 2026-06-19: that looked generic + cheap). It is
N DISTINCT, premium, brand-aligned b-roll CLIPS (default 3 × 10s ≈ 30s) generated, then
stitched (concatenated, NO looping) so the footage covers the full voiceover with real visual
variety. Each clip costs REAL Higgsfield credits (~45 est; do_poll measures the true cost from
the wallet before/after). The engine reel cap counts REAL credits (135/day ≈ 1 reel/day).

Every prompt = the VIDEO Brand Prompt Block (printed VERBATIM by preflight.py --print-block
video) + a Seedance b-roll scene with NO face / NO people / NO on-screen text (Marvin
2026-06-18: no avatar/talking-head/DTC, and text in the video gets jumbled — keep it caption-
only). seedance_2_0 ignores aspect, so each result is cropped to 9:16 locally for free
(RUNBOOK §12.3) and the clips are concatenated into brief.video.

Config (overridable in .env):
  ENGINE_REEL_CLIPS             clips per reel   (default 3)
  ENGINE_REEL_CLIP_SECONDS      Seedance --duration per clip (default 10)
  ENGINE_REEL_CREDITS_PER_CLIP  est REAL credits per clip (default 45; calibrated by do_poll)
  ENGINE_CAP_REEL               real-credit daily ceiling (default 135)

Usage:
  reel_video.py <job_dir>                 # DRY-RUN: N scenes+prompts, preflight, gates, wallet, the
                                          #   exact higgsfield commands. 0 credits.
  reel_video.py <job_dir> --go            # SPEND: ~45 real credits per clip, submit each (--no-wait)
  reel_video.py <job_dir> --poll          # poll ALL clips; when all settle, crop + concat + cost
  reel_video.py <job_dir> --scene "..."   # force a single explicit b-roll scene (1 clip)
  reel_video.py <job_dir> --clips N --duration S   # override clip count / per-clip seconds
  reel_video.py <job_dir> --owned-clip FILE   # PROOF: 0-credit — crop an OWNED clip into brief.video
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import engine as e
import preflight as pf
from copywriter import call_openrouter, load_api_key, DEFAULT_MODEL
try:
    import product_images  # anchor the hero clip on the real product photo (Marvin 2026-06-21)
except Exception:
    product_images = None

WS = Path(__file__).parent.resolve()
PY = sys.executable or "python3"
MODEL = "seedance_2_0"
SIDE = "reel_video.json"  # per-job sidecar: the generation record (now multi-clip)


def product_ref_for(brief: dict) -> "str | None":
    """Higgsfield media id for the brief's compound's product photo (uploaded + cached), so the
    HERO clip can be image-to-video off the REAL vial — e.g. a Tirzepatide reel opens on the
    Tirzepatide product (Marvin: 'grab that image as reference and send to higgsfield'). The other
    clips stay abstract molecular b-roll for variety. None when there's no photo / upload fails."""
    compound = brief.get("compound")
    if not (product_images and compound):
        return None
    try:
        return product_images.higgsfield_ref(compound)
    except Exception as ex:
        e.log(f"product reference lookup failed for {compound}: {ex}")
        return None

COMPLETED = {"completed", "done", "ready", "succeeded", "success"}
# 'nsfw'/'moderated' are TERMINAL — Higgsfield's content filter can false-flag clean lab b-roll
# (Marvin 2026-06-21 system test, ACME-041 clip 3). Without these in FAILED, do_poll treats the
# rejected clip as forever-pending and the whole reel hangs; here it's dropped and the reel
# finalizes from the clips that did complete.
FAILED = {"failed", "error", "canceled", "cancelled", "ip_detected", "blocked", "rejected",
          "nsfw", "moderated", "content_moderation", "flagged"}


def _int_env(key: str, default: int) -> int:
    try:
        v = (e.load_env(key) or "").strip()
        return int(v) if v else default
    except (ValueError, TypeError):
        return default


N_CLIPS = _int_env("ENGINE_REEL_CLIPS", 3)            # distinct b-roll shots stitched per reel
CLIP_SECONDS = _int_env("ENGINE_REEL_CLIP_SECONDS", 10)  # Seedance --duration per clip
# REAL Higgsfield credits an estimated single 10s Seedance generation costs. The engine `reel`
# budget + the daily cap are denominated in REAL credits (not a generation count), so we spend
# this much per clip. ~45 is Marvin's figure; do_poll measures the TRUE cost on the first live
# run (wallet before/after) so this can be calibrated. Tune via .env ENGINE_REEL_CREDITS_PER_CLIP.
CREDITS_PER_CLIP = _int_env("ENGINE_REEL_CREDITS_PER_CLIP", 45)


def wallet_balance() -> "int | None":
    """Live Higgsfield credit balance (account status), or None if it can't be read. The real
    backstop behind the engine's estimated daily cap — refuse to spend if the wallet is short."""
    try:
        r = subprocess.run([PY, str(WS / "higgsfield.py"), "credits"], capture_output=True, text=True)
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout or "{}")
        c = data.get("credits")
        return int(c) if c is not None else None
    except Exception:
        return None

# Local guard: a b-roll scene must never imply a human or on-screen text (preflight is the
# backstop, but reject the obvious tokens before we ever build the prompt).
_BAD_SCENE = re.compile(
    r"\b(face|person|people|man|woman|men|women|girl|boy|human|model\s+(?:wearing|holding)|"
    r"spokes\w*|presenter|host|influencer|selfie|portrait|talking[-\s]?head|actor|hand|hands|finger)\b"
    r"|\b(text|caption|subtitle|typography|title\s*card|words?\s+on\s+screen|lettering|logo)\b",
    re.IGNORECASE,
)


def _scene_rejected(scene: str) -> str | None:
    """Reason a scene is unusable, else None. Mirrors the REAL M3 gate (preflight.AD_PERSON +
    TEXT_REQUEST, imported so they never drift) ON TOP of the local _BAD_SCENE guard — so a
    scene we PICK actually clears preflight. This is what stops one stray LLM word (e.g.
    'molecular model') from blocking the whole multi-clip batch at generation time."""
    if _BAD_SCENE.search(scene):
        return "implies a human or on-screen text"
    if pf.AD_PERSON.search(scene):
        return "reads like a person/product ad (preflight AD_PERSON)"
    if pf.TEXT_REQUEST.search(scene) and not pf.NEGATION_NEAR.search(scene):
        return "requests on-screen text (preflight TEXT_REQUEST)"
    return None

# Curated premium b-roll DECK — deep-forest-green + warm-cream, single bright-green accent,
# anamorphic shallow-DOF, clinical/molecular/clean-product, NO people/text. Used to top up to
# N distinct scenes when the LLM is unavailable or its scenes trip the no-face/no-text guard
# (the old single-fallback path is what made ACME-022 look generic — Marvin 2026-06-19).
_SCENE_DECK = {
    "science": [
        "slow macro dolly across a rack of frosted glass vials on a deep-forest matte surface, condensation beading, soft cream side light, anamorphic flare",
        "rotating 3D molecular peptide structure, shallow depth of field, particles drifting through a clean forest-green void",
        "extreme close-up of a single droplet falling from a glass pipette into a vial, concentric ripples in slow motion, cool clinical key light",
        "cryogenic vapor curling off a chilled sealed vial on a dark forest surface, backlit rim glow, cinematic slow motion",
        "overhead slow push-in on three lyophilized peptide vials on warm cream stone, long soft shadows, generous negative space",
        "abstract cream and forest-green fluid swirling inside sealed glass, refracted light, ultra slow motion",
    ],
    "trending": [
        "rotating 3D molecular peptide chain dissolving into drifting particles, shallow depth of field, clean clinical forest-green background",
        "fast macro tracking shot along a row of sealed amber vials in a cream tray, rim-lit by a single bright-green accent glow",
        "kinetic close-up of liquid swirling and refracting green light inside a glass vial, ultra slow motion, deep negative space",
        "abstract forest-green and cream fluid dynamics, smooth ferromagnetic ripples, premium biotech mood, soft volumetric light",
        "slow orbit around a frosted vial suspended in a clean clinical void, bright-green accent reflection, anamorphic flare",
        "macro dolly across condensation forming on chilled glass, soft cream backlight, cinematic depth of field",
    ],
    "proof": [
        "extreme close-up of a pipette releasing a single precise droplet into a vial, concentric ripples, cool clinical lighting",
        "macro pan across a row of sealed vials in a clinical tray, soft cream light, shallow depth of field, ordered and precise",
        "slow push-in on a single droplet suspended mid-fall above a vial, frozen ripple, bright-green rim light",
        "overhead slow rotation of three lyophilized vials on cream stone, long soft shadows, premium clinical mood",
        "macro tracking along frosted glass vials with condensation, single forest-green accent reflection, anamorphic flare",
        "abstract clinical fluid refracting green light in slow motion, deep negative space, calm authoritative pacing",
    ],
    "founder": [
        "quiet editorial pan across a minimalist biotech lab bench, ordered glass instruments, generous negative space, soft cream window light",
        "slow dolly through a calm clinical lab, frosted vials in soft-focus foreground, forest-green walls, cinematic depth",
        "overhead still-life push-in on three peptide vials on warm cream stone, long shadows, editorial biotech mood",
        "macro across condensation on a chilled vial by a sunlit cream surface, soft anamorphic flare",
        "slow orbit around a single frosted vial on a deep-forest plinth, museum lighting, bright-green accent glow",
        "abstract cream and forest-green light washing across brushed clinical surfaces, calm authoritative pacing",
    ],
    "stack": [
        "overhead slow push-in on three lyophilized peptide vials arranged on cream stone, soft long shadows",
        "macro tracking shot along a neat row of sealed amber vials in a cream tray, rim-lit by a bright-green accent glow",
        "slow rotation of a curated trio of frosted vials on a deep-forest surface, anamorphic flare, generous negative space",
        "extreme close-up of condensation beading on stacked chilled vials, cool clinical backlight, slow motion",
        "clean product orbit around sealed vials floating in a forest-green void, soft volumetric light, premium biotech mood",
        "overhead flat-lay slow drift across vials and a folded cream cloth, ordered minimal composition, soft shadows",
    ],
}


def fail(msg: str) -> "NoReturn":
    sys.exit(f"[reel-video] ERROR: {msg}")


def _load_brief(job: Path) -> dict:
    bp = job / "brief.json"
    if not bp.exists():
        fail(f"no brief.json in {job}")
    brief = json.loads(bp.read_text())
    if brief.get("type") != "reel":
        fail(f"brief type is {brief.get('type')!r}; reel_video.py only handles type=reel")
    return brief


def _set_brief_video(job: Path, rel_path: str) -> None:
    bp = job / "brief.json"
    brief = json.loads(bp.read_text())
    brief["video"] = rel_path
    bp.write_text(json.dumps(brief, ensure_ascii=False, indent=2))


# ── scenes + prompts ──────────────────────────────────────────────────────────
def pick_deck(pillar: str, n: int, exclude=()) -> list[str]:
    """N DISTINCT premium curated scenes for this pillar (topped up from the global pool if a
    single pillar's deck is short). Deterministic — the no-LLM safety net for visual variety."""
    deck = _SCENE_DECK.get(pillar) or _SCENE_DECK["science"]
    seen = list(exclude)
    out: list[str] = []
    for s in deck:
        if len(out) >= n:
            break
        if s not in seen and s not in out:
            out.append(s)
    if len(out) < n:  # exhausted this pillar — borrow distinct scenes from the rest
        for s in (s for lst in _SCENE_DECK.values() for s in lst):
            if len(out) >= n:
                break
            if s not in seen and s not in out:
                out.append(s)
    return out[:n]


def _parse_scene_array(raw: str) -> list:
    """Tolerant parse of a JSON array of scene strings (handles code fences / surrounding prose)."""
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip(), flags=re.MULTILINE).strip()
    try:
        v = json.loads(raw)
        if isinstance(v, list):
            return v
    except Exception:
        pass
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if m:
        try:
            v = json.loads(m.group(0))
            if isinstance(v, list):
                return v
        except Exception:
            pass
    return []


def propose_scenes(brief: dict, n: int) -> list[str]:
    """N DISTINCT vivid Seedance b-roll scenes for the topic — all faceless, no text. LLM-proposed
    (reuse copywriter's OpenRouter), guard-filtered, then topped up from the curated deck so we
    ALWAYS return n distinct premium scenes (never a single repeated clip)."""
    pillar = brief.get("pillar", "science")
    topic = brief.get("topic", "")
    chosen: list[str] = []
    try:
        api_key = load_api_key()
        sys_p = (
            f"You write {n} DISTINCT short cinematic B-ROLL scenes for an AI video generator "
            "(Seedance) that will be STITCHED into ONE premium biotech reel. HARD RULES: each "
            "scene is lab / molecular / clinical / clean-product footage ONLY — absolutely NO "
            "people, NO faces, NO hands, NO on-screen text/words/logos. Each is one or two "
            "sentences with a vivid camera move + lighting, deep-forest-green and warm-cream "
            "palette, single bright-green accent, anamorphic shallow-depth-of-field premium mood. "
            "The scenes must be VISUALLY DIFFERENT from each other (different subject AND camera "
            f"move). Output ONLY a JSON array of exactly {n} strings."
        )
        user = f"Pillar: {pillar}. Reel topic: {topic}. Write the {n} distinct faceless b-roll scenes."
        resp = call_openrouter([{"role": "system", "content": sys_p},
                                {"role": "user", "content": user}], DEFAULT_MODEL, api_key)
        raw = resp["choices"][0]["message"]["content"] or ""
        for s in _parse_scene_array(raw):
            s = " ".join(str(s).split()).strip().strip('"')
            if s and not _scene_rejected(s) and s not in chosen:
                chosen.append(s[:300])
    except Exception as ex:  # network / key / parse — fall back to the curated deck
        e.log(f"scene LLM unavailable ({ex}) — using the curated deck")
    if len(chosen) < n:
        if chosen:
            e.log(f"only {len(chosen)}/{n} LLM scenes passed the no-face/no-text guard — topping up from the curated deck")
        chosen += pick_deck(pillar, n - len(chosen), exclude=chosen)
    return chosen[:n]


def video_block() -> str:
    r = subprocess.run([PY, str(WS / "preflight.py"), "--print-block", "video"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        fail("could not read the VIDEO brand block from preflight.py")
    return r.stdout.strip()


def build_prompt(scene: str) -> str:
    """Brand VIDEO block VERBATIM (by construction) + the faceless b-roll scene."""
    reason = _scene_rejected(scene)
    if reason:
        fail(f"scene refused ({reason}): {scene!r}")
    return f"{video_block()} {scene}"


def _hf_args(prompt: str, duration: int) -> list[str]:
    return ["video", prompt, "--model", MODEL, "--no-cinematic", "--no-wait", "--duration", str(duration)]


def preflight_ok(prompt: str) -> bool:
    """Run the canonical M3 gate. Its exit code (0 + PREFLIGHT-OK) is the go-token."""
    r = subprocess.run(
        [PY, str(WS / "preflight.py"), "--route", "video", "--prompt", prompt,
         "--model", MODEL, "--aspect", "9:16", "--no-wait", "--reuse-checked"],
        capture_output=True, text=True)
    sys.stderr.write(r.stderr)
    return r.returncode == 0 and "PREFLIGHT-OK" in r.stdout


# ── gates ────────────────────────────────────────────────────────────────────
def check_gates(job: Path, brief: dict, *, require_concept=True, need_credits=0) -> list[str]:
    """`need_credits` is the estimated REAL Higgsfield cost of this reel (clips × CREDITS_PER_CLIP).
    G4 is the engine's daily real-credit ceiling; G6 is the live wallet (the actual money)."""
    fails = []
    if require_concept:
        cqc = e.load_json(job / "concept_qc.json") or {}
        if not cqc.get("passed"):
            fails.append("G2 concept not approved — no concept_qc.json (run GATE 1 first; credit-first)")
    if e.stop_engaged():
        fails.append("G3 STOP engaged — engine halted")
    if e.compliance_hold():
        fails.append("G3 compliance hold active — only the owner can RESUME")
    rem = e.budget_remaining("reel")
    if rem < need_credits:
        fails.append(f"G4 reel daily credit cap — need ~{need_credits} real credits, only {rem} of "
                     f"{e._caps()['reel']}/day left (engine spend budget)")
    bal = wallet_balance()
    if bal is not None and bal < need_credits:
        fails.append(f"G6 live Higgsfield wallet too low — balance {bal} < ~{need_credits} this reel needs")
    elif bal is None:
        e.log("could not read the live Higgsfield wallet — relying on the engine daily cap (G4) only")
    return fails


# ── 9:16 crop + concat ───────────────────────────────────────────────────────
def crop_916(src: Path, dst: Path) -> None:
    """Free local cover-crop to exactly 1080x1920 (RUNBOOK §12.3). seedance ignores aspect.
    Drops audio — the b-roll's own track is irrelevant (RV4 muxes the narration)."""
    r = subprocess.run(
        ["ffmpeg", "-i", str(src), "-an", "-vf", "scale=-2:1920,crop=1080:1920",
         "-c:v", "libx264", "-r", "30", "-pix_fmt", "yuv420p", "-y", str(dst)],
        capture_output=True, text=True)
    if r.returncode != 0 or not dst.exists():
        fail(f"ffmpeg 9:16 crop failed:\n{r.stderr[-800:]}")


def concat_clips(crops: list[Path], out: Path) -> None:
    """Stitch N already-9:16 crops into one clip (NO looping). Re-encode via the concat filter so
    independently-encoded clips join cleanly. Each crop is 1080x1920/30fps; the result covers the
    full voiceover with real visual variety (Marvin 2026-06-19)."""
    args = ["ffmpeg"]
    for c in crops:
        args += ["-i", str(c)]
    n = len(crops)
    filt = "".join(f"[{i}:v:0]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    args += ["-filter_complex", filt, "-map", "[v]",
             "-c:v", "libx264", "-r", "30", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", "-y", str(out)]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        fail(f"ffmpeg concat failed:\n{r.stderr[-800:]}")


# ── subcommands ──────────────────────────────────────────────────────────────
def do_plan(job: Path, brief: dict, scenes: list[str], *, go: bool, duration: int) -> int:
    """Build + preflight + gate-check every clip. With go=False this is the 0-credit DRY RUN."""
    plans = [{"scene": s, "prompt": build_prompt(s)} for s in scenes]
    n = len(plans)
    need = n * CREDITS_PER_CLIP
    print(f"\n[reel-video] {job.name} · {n} clip(s) × {duration}s ≈ {n * duration}s — "
          f"est ~{need} REAL Higgsfield credits ({n} × ~{CREDITS_PER_CLIP})")
    bal = wallet_balance()
    if bal is not None:
        print(f"[reel-video] live Higgsfield wallet: {bal} credits")
    for i, p in enumerate(plans, 1):
        print(f"  clip {i}: {p['scene']}")

    gate_fails = check_gates(job, brief, need_credits=need)
    pf_all = True
    for i, p in enumerate(plans, 1):
        ok = preflight_ok(p["prompt"])
        print(f"[reel-video] clip {i} preflight: {'PASS' if ok else 'BLOCK'}")
        pf_all = pf_all and ok
    for g in gate_fails:
        print(f"[reel-video] gate FAIL: {g}")
    if not pf_all:
        gate_fails.append("G5 preflight BLOCK")

    print("\n[reel-video] command(s) that " + ("WILL" if go and not gate_fails else "WOULD") + " run:")
    for i, p in enumerate(plans, 1):
        cmd = ["python3", "higgsfield.py"] + _hf_args(p["prompt"], duration)
        print(f"  clip {i}: " + " ".join((repr(c) if " " in c else c) for c in cmd))

    if not go:
        rem = e.budget_remaining("reel")
        print(f"\n[reel-video] DRY-RUN — 0 credits spent. reel daily budget left: {rem}/{e._caps()['reel']} "
              f"real credits (need ~{need}).")
        print(f"[reel-video] re-run with --go (and Marvin's explicit OK) to spend ~{need} real credits.")
        return 0 if not gate_fails else 1
    if gate_fails:
        fail("gates not satisfied — refusing to spend credits:\n  - " + "\n  - ".join(gate_fails))
    return submit_all(job, brief, plans, duration)


def submit_all(job: Path, brief: dict, plans: list[dict], duration: int) -> int:
    """Spend ~CREDITS_PER_CLIP REAL credits per clip and submit each seedance job (--no-wait).
    Records the multi-clip sidecar + the live wallet balance BEFORE spending, so do_poll can
    report the TRUE cost. The per-clip e.spend('reel', CREDITS_PER_CLIP) is the atomic daily-cap
    enforcement (G4)."""
    balance_before = wallet_balance()
    hero_ref = product_ref_for(brief)  # real product photo → image-to-video on clip 1 only
    if hero_ref:
        e.log(f"{job.name}: hero clip anchored on product photo (higgsfield media {hero_ref})")
    clips = []
    for i, p in enumerate(plans, 1):
        if not e.spend("reel", CREDITS_PER_CLIP):  # atomic real-credit cap — False => would breach the ceiling
            e.log(f"{job.name}: reel daily credit cap reached after {len(clips)} clip(s) — "
                  f"stopping (submitted {len(clips)}/{len(plans)})")
            break
        e.log(f"{job.name}: SPENDING ~{CREDITS_PER_CLIP} real credits — clip {i}/{len(plans)} "
              f"seedance_2_0 {duration}s (--no-wait)")
        hf_args = _hf_args(p["prompt"], duration)
        if i == 1 and hero_ref:                    # anchor the opening shot on the real vial
            hf_args += ["--image", hero_ref]
        r = subprocess.run([PY, str(WS / "higgsfield.py")] + hf_args,
                           capture_output=True, text=True)
        if r.returncode != 0:
            e.log(f"{job.name}: clip {i} submit FAILED — {r.stderr[-300:]}")
            continue
        try:
            out = json.loads(r.stdout)
        except json.JSONDecodeError:
            e.log(f"{job.name}: clip {i} submit returned unparseable output — skipping")
            continue
        jid = out.get("job_id") or out.get("id")
        if not jid:
            e.log(f"{job.name}: clip {i} submit returned no job_id — skipping")
            continue
        clips.append({"i": i, "scene": p["scene"], "prompt": p["prompt"],
                      "higgsfield_job_id": jid, "status": "pending",
                      "result_url": None, "crop": f"broll_916_{i}.mp4"})
    if not clips:
        fail("no clips submitted — nothing in flight (check `higgsfield.py jobs`)")
    (job / SIDE).write_text(json.dumps({
        "model": MODEL, "duration": duration, "aspect": "9:16", "source": "seedance",
        "credits_per_clip_estimate": CREDITS_PER_CLIP, "est_credits": len(clips) * CREDITS_PER_CLIP,
        "wallet_before": balance_before, "clips": clips, "status": "pending",
        "submitted_at": e.now_iso(), "video": None,
    }, ensure_ascii=False, indent=2))
    print(f"[reel-video] submitted {len(clips)} clip(s) · status=pending")
    print(f"[reel-video] poll with:  python3 reel_video.py {job} --poll")
    return 0


def _hf_job(job_id: str) -> dict:
    r = subprocess.run([PY, str(WS / "higgsfield.py"), "job", job_id], capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"higgsfield job query failed:\n{r.stderr[-500:]}")
    return json.loads(r.stdout or "{}")


def do_poll(job: Path) -> int:
    side = e.load_json(job / SIDE) or {}
    clips = side.get("clips")
    if not clips and side.get("higgsfield_job_id"):  # legacy single-clip sidecar → unify
        clips = side["clips"] = [{
            "i": 1, "scene": side.get("scene", ""), "prompt": side.get("prompt", ""),
            "higgsfield_job_id": side["higgsfield_job_id"], "status": "pending",
            "result_url": None, "crop": "broll_916_1.mp4"}]
    if not clips:
        fail(f"no {SIDE} with clips — submit with --go first")

    pending = 0
    for c in clips:
        if c.get("status") in ("done", "failed"):
            continue
        info = _hf_job(c["higgsfield_job_id"])
        status = (info.get("status") or "").lower()
        if status in FAILED:
            c["status"] = "failed"
            e.log(f"{job.name}: clip {c['i']} FAILED ({status})")
        elif status in COMPLETED:
            url = info.get("url")
            if not url:
                c["status"] = "failed"
                e.log(f"{job.name}: clip {c['i']} completed but no result url — marking failed")
            else:
                raw = job / f"broll_raw_{c['i']}.mp4"
                _download(url, raw)
                crop_916(raw, job / c["crop"])
                c.update(status="done", result_url=url)
                e.log(f"{job.name}: clip {c['i']} downloaded + 9:16 cropped")
        else:
            pending += 1
    (job / SIDE).write_text(json.dumps(side, ensure_ascii=False, indent=2))

    if pending:
        print(f"PENDING {pending}/{len(clips)} clip(s) still rendering")
        return 0

    done = [c for c in clips if c.get("status") == "done"]
    if not done:
        side["status"] = "failed"
        (job / SIDE).write_text(json.dumps(side, ensure_ascii=False, indent=2))
        print("FAILED all clips failed")
        return 0

    crops = [job / c["crop"] for c in sorted(done, key=lambda c: c["i"])]
    out = job / "broll_916.mp4"
    if len(crops) == 1:
        shutil.copyfile(crops[0], out)
    else:
        concat_clips(crops, out)
    rel = str(out.relative_to(WS))
    _set_brief_video(job, rel)
    side.update(status="done", video=rel, completed_at=e.now_iso())
    # Measure the TRUE Higgsfield cost (wallet before submit → now). Calibrates the ~45 estimate.
    wallet_after = wallet_balance()
    side["wallet_after"] = wallet_after
    before = side.get("wallet_before")
    if isinstance(before, int) and isinstance(wallet_after, int):
        actual = before - wallet_after
        side["actual_credits_used"] = actual
        side["actual_credits_per_clip"] = round(actual / len(done), 1) if done else None
        e.log(f"{job.name}: ACTUAL Higgsfield credits for this reel ≈ {actual} "
              f"({side['actual_credits_per_clip']}/clip; estimate was {CREDITS_PER_CLIP}) — "
              f"wallet {before}→{wallet_after}. If it diverges, tune ENGINE_REEL_CREDITS_PER_CLIP.")
    if len(done) < len(clips):
        side["note"] = f"{len(clips) - len(done)} clip(s) failed; stitched {len(done)}"
        e.log(f"{job.name}: {len(clips) - len(done)} clip(s) failed — stitched the {len(done)} that succeeded")
    (job / SIDE).write_text(json.dumps(side, ensure_ascii=False, indent=2))
    print(f"DONE {rel} ({len(done)} clip(s) stitched)")
    return 0


def do_owned_clip(job: Path, clip: Path) -> int:
    """0-credit PROOF: substitute an OWNED clip for the generated b-roll (A1/A3 principle)."""
    if not clip.exists():
        fail(f"owned clip not found: {clip}")
    out = job / "broll_916.mp4"
    crop_916(clip, out)
    rel = str(out.relative_to(WS))
    _set_brief_video(job, rel)
    (job / SIDE).write_text(json.dumps({
        "source": "owned-clip", "owned_clip": str(clip), "video": rel, "aspect": "9:16",
        "status": "done", "credits": 0, "completed_at": e.now_iso(),
        "note": "0-credit proof substitution — NOT a Higgsfield generation",
    }, ensure_ascii=False, indent=2))
    print(f"DONE {rel}  (0 credits — owned-clip proof)")
    return 0


def _download(url: str, dst: Path) -> None:
    import ssl
    import urllib.request
    # Verify with the certifi CA bundle (the repo pattern — bare urllib has no local issuer
    # cert and fails on the Higgsfield CDN). ENGINE_INSECURE_SSL=1 disables it for a sandbox.
    if (e.load_env("ENGINE_INSECURE_SSL") or "").strip() == "1":
        ctx = ssl._create_unverified_context()
    else:
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(url, timeout=180, context=ctx) as resp, dst.open("wb") as f:
            f.write(resp.read())
    except Exception as ex:
        fail(f"download failed: {ex}")


def main():
    ap = argparse.ArgumentParser(description="F7 RV3 — Seedance multi-clip b-roll generation (the credit spend; dry-run by default)")
    ap.add_argument("job_dir", help="Job folder with a type=reel brief.json")
    ap.add_argument("--go", action="store_true", help="ACTUALLY spend reel credits (1/clip) + submit (needs Marvin's OK)")
    ap.add_argument("--poll", action="store_true", help="Poll ALL submitted clips; when all settle, crop + concat")
    ap.add_argument("--scene", help="Force a single explicit b-roll scene (1 clip / 1 credit)")
    ap.add_argument("--clips", type=int, help=f"Clips per reel (default {N_CLIPS}; ignored with --scene)")
    ap.add_argument("--duration", type=int, help=f"Seedance seconds per clip (default {CLIP_SECONDS})")
    ap.add_argument("--owned-clip", help="0-credit PROOF: crop an OWNED clip into brief.video (no generation)")
    args = ap.parse_args()

    job = Path(args.job_dir).resolve()
    brief = _load_brief(job)

    if args.owned_clip:
        sys.exit(do_owned_clip(job, Path(args.owned_clip).resolve()))
    if args.poll:
        sys.exit(do_poll(job))

    duration = args.duration or CLIP_SECONDS
    if args.scene:
        scenes = [args.scene]
    else:
        n = args.clips or N_CLIPS
        scenes = propose_scenes(brief, n)
    sys.exit(do_plan(job, brief, scenes, go=args.go, duration=duration))


if __name__ == "__main__":
    main()
