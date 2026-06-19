#!/usr/bin/env python3
"""reel_video.py — F7 RV3: generate the Seedance b-roll for a reel. THE credit spend.

This is the ONLY module in the whole engine that spends a Higgsfield credit, so it is
wrapped in hard gates and is DRY-RUN by default. A credit is spent ONLY when you pass
--go, and only after every gate below passes:

  G1  brief is type=reel
  G2  concept_qc.json present + passed     — GATE 1 concept-approved (credit-first, MIGRATION 1.1)
  G3  engine not STOP and not compliance_hold
  G4  engine reel cap not exhausted        — HARD 2 reels/day (engine.budget_remaining('reel'))
  G5  preflight.py PASS                     — VIDEO block VERBATIM + route=video + seedance_2_0
                                              + --no-wait + --reuse-checked (its exit code IS the guard)

The prompt = the VIDEO Brand Prompt Block (printed VERBATIM by preflight.py --print-block
video) + a Seedance b-roll scene with NO face / NO people / NO on-screen text (Marvin
2026-06-18: no avatar/talking-head/DTC route). seedance_2_0 ignores aspect, so the result
is cropped to 9:16 locally for free (RUNBOOK §12.3) into brief.video.

Usage:
  reel_video.py <job_dir>                 # DRY-RUN: scene+prompt, preflight, gates, print the exact
                                          #   higgsfield command. 0 credits.
  reel_video.py <job_dir> --go            # SPEND: engine.spend('reel') then submit seedance --no-wait
  reel_video.py <job_dir> --poll          # poll the submitted job; on completion download + 9:16 crop
  reel_video.py <job_dir> --scene "..."   # override the auto b-roll scene
  reel_video.py <job_dir> --owned-clip FILE   # PROOF: 0-credit — crop an OWNED clip into brief.video
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import engine as e
from copywriter import call_openrouter, extract_json, load_api_key, DEFAULT_MODEL

WS = Path(__file__).parent.resolve()
PY = sys.executable or "python3"
MODEL = "seedance_2_0"
SIDE = "reel_video.json"  # per-job sidecar: the generation record

COMPLETED = {"completed", "done", "ready", "succeeded", "success"}
FAILED = {"failed", "error", "canceled", "cancelled", "ip_detected", "blocked", "rejected"}

# Local guard: a b-roll scene must never imply a human or on-screen text (preflight is the
# backstop, but reject the obvious tokens before we ever build the prompt).
_BAD_SCENE = re.compile(
    r"\b(face|person|people|man|woman|men|women|girl|boy|human|model\s+(?:wearing|holding)|"
    r"spokes\w*|presenter|host|influencer|selfie|portrait|talking[-\s]?head|actor|hand|hands|finger)\b"
    r"|\b(text|caption|subtitle|typography|title\s*card|words?\s+on\s+screen|lettering|logo)\b",
    re.IGNORECASE,
)

# Deterministic fallback scenes (used only if the LLM is unavailable) — all faceless, no text.
_FALLBACK_SCENE = {
    "science":  "slow macro dolly across a rack of frosted glass vials on a deep-forest lab surface, condensation, soft side light",
    "trending": "rotating 3D molecular peptide chain, shallow depth of field, clean clinical background, particles drifting",
    "proof":    "extreme close-up of a pipette releasing a single droplet into a vial, ripples, cool clinical lighting",
    "founder":  "quiet editorial pan across a minimalist biotech lab bench, ordered instruments, generous negative space",
    "stack":    "overhead slow push-in on three lyophilized peptide vials arranged on cream stone, soft shadows",
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


# ── scene + prompt ───────────────────────────────────────────────────────────
def propose_scene(brief: dict) -> str:
    """One vivid Seedance b-roll scene matching the topic — faceless, no text. LLM-proposed
    (reuse copywriter's OpenRouter), with a deterministic per-pillar fallback."""
    pillar = brief.get("pillar", "science")
    topic = brief.get("topic", "")
    try:
        api_key = load_api_key()
        sys_p = (
            "You write ONE short cinematic B-ROLL scene for an AI video generator (Seedance). "
            "HARD RULES: lab / molecular / clinical / clean-product footage ONLY. Absolutely NO "
            "people, NO faces, NO hands, NO on-screen text/words/logos. One or two sentences, "
            "vivid camera + lighting, premium biotech mood. Output ONLY the scene description."
        )
        user = f"Pillar: {pillar}. Reel topic: {topic}. Write the faceless b-roll scene."
        resp = call_openrouter([{"role": "system", "content": sys_p},
                                {"role": "user", "content": user}], DEFAULT_MODEL, api_key)
        scene = (resp["choices"][0]["message"]["content"] or "").strip().strip('"')
        scene = " ".join(scene.split())
        if scene and not _BAD_SCENE.search(scene):
            return scene[:300]
        e.log(f"scene rejected by guard or empty ({scene[:60]!r}) — using fallback")
    except Exception as ex:  # network / key / parse — fall back deterministically
        e.log(f"scene LLM unavailable ({ex}) — using fallback")
    return _FALLBACK_SCENE.get(pillar, _FALLBACK_SCENE["science"])


def video_block() -> str:
    r = subprocess.run([PY, str(WS / "preflight.py"), "--print-block", "video"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        fail("could not read the VIDEO brand block from preflight.py")
    return r.stdout.strip()


def build_prompt(scene: str) -> str:
    """Brand VIDEO block VERBATIM (by construction) + the faceless b-roll scene."""
    if _BAD_SCENE.search(scene):
        fail(f"scene implies a human or on-screen text — refused: {scene!r}")
    return f"{video_block()} {scene}"


def preflight_ok(prompt: str) -> bool:
    """Run the canonical M3 gate. Its exit code (0 + PREFLIGHT-OK) is the go-token."""
    r = subprocess.run(
        [PY, str(WS / "preflight.py"), "--route", "video", "--prompt", prompt,
         "--model", MODEL, "--aspect", "9:16", "--no-wait", "--reuse-checked"],
        capture_output=True, text=True)
    sys.stderr.write(r.stderr)
    return r.returncode == 0 and "PREFLIGHT-OK" in r.stdout


# ── gates ────────────────────────────────────────────────────────────────────
def check_gates(job: Path, brief: dict, *, require_concept=True) -> list[str]:
    fails = []
    job_id = job.name
    if require_concept:
        cqc = e.load_json(job / "concept_qc.json") or {}
        if not cqc.get("passed"):
            fails.append("G2 concept not approved — no concept_qc.json (run GATE 1 first; credit-first)")
    if e.stop_engaged():
        fails.append("G3 STOP engaged — engine halted")
    if e.compliance_hold():
        fails.append("G3 compliance hold active — only the owner can RESUME")
    if e.budget_remaining("reel") <= 0:
        fails.append(f"G4 reel cap exhausted — {e.budget_remaining('reel')} of "
                     f"2/day remaining (engine spend budget)")
    return fails


# ── 9:16 crop ────────────────────────────────────────────────────────────────
def crop_916(src: Path, dst: Path) -> None:
    """Free local cover-crop to exactly 1080x1920 (RUNBOOK §12.3). seedance ignores aspect."""
    r = subprocess.run(
        ["ffmpeg", "-i", str(src), "-vf", "scale=-2:1920,crop=1080:1920",
         "-c:a", "copy", "-y", str(dst)],
        capture_output=True, text=True)
    if r.returncode != 0 or not dst.exists():
        fail(f"ffmpeg 9:16 crop failed:\n{r.stderr[-800:]}")


# ── subcommands ──────────────────────────────────────────────────────────────
def do_plan(job: Path, brief: dict, scene: str, go: bool) -> int:
    """Build + preflight + gate-check. With go=False this is the 0-credit DRY RUN."""
    prompt = build_prompt(scene)
    print(f"\n[reel-video] {job.name} · scene:\n  {scene}\n")
    print(f"[reel-video] full prompt ({len(prompt)} chars):\n  {prompt}\n")

    gate_fails = check_gates(job, brief)
    pf = preflight_ok(prompt)
    print(f"\n[reel-video] preflight: {'PASS' if pf else 'BLOCK'}")
    for g in gate_fails:
        print(f"[reel-video] gate FAIL: {g}")
    if not pf:
        gate_fails.append("G5 preflight BLOCK")

    cmd = [PY, "higgsfield.py", "video", prompt, "--model", MODEL, "--no-cinematic", "--no-wait"]
    print(f"\n[reel-video] command that {'WILL' if go and not gate_fails else 'WOULD'} run:")
    print("  " + " ".join((repr(c) if " " in c else c) for c in cmd))

    if not go:
        rem = e.budget_remaining("reel")
        print(f"\n[reel-video] DRY-RUN — 0 credits spent. reel budget left today: {rem}/2.")
        print("[reel-video] re-run with --go (and Marvin's explicit OK) to actually spend ONE credit.")
        return 0 if not gate_fails else 1
    if gate_fails:
        fail("gates not satisfied — refusing to spend a credit:\n  - " + "\n  - ".join(gate_fails))
    return submit(job, brief, prompt, scene)


def submit(job: Path, brief: dict, prompt: str, scene: str) -> int:
    """Spend ONE reel credit and submit the seedance job (--no-wait). Records the sidecar."""
    if not e.spend("reel"):  # atomic cap check + record; False => would breach 2/day
        fail("reel cap would be breached — refusing (engine.spend('reel') returned False)")
    e.log(f"{job.name}: SPENDING 1 reel credit — submitting seedance_2_0 (--no-wait)")
    r = subprocess.run([PY, str(WS / "higgsfield.py"), "video", prompt,
                        "--model", MODEL, "--no-cinematic", "--no-wait"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"higgsfield submit failed (credit may or may not have spent — check `higgsfield.py jobs`):\n{r.stderr[-800:]}")
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        fail(f"could not parse higgsfield submit output:\n{r.stdout[-800:]}")
    job_id = out.get("job_id") or out.get("id")
    if not job_id:
        fail(f"no job_id in submit output: {out}")
    (job / SIDE).write_text(json.dumps({
        "higgsfield_job_id": job_id, "model": MODEL, "scene": scene, "prompt": prompt,
        "aspect": "9:16", "status": "pending", "submitted_at": e.now_iso(), "source": "seedance",
    }, ensure_ascii=False, indent=2))
    print(f"[reel-video] submitted · higgsfield_job_id={job_id} · status=pending")
    print(f"[reel-video] poll with:  python3 reel_video.py {job} --poll")
    return 0


def do_poll(job: Path) -> int:
    side = e.load_json(job / SIDE) or {}
    job_id = side.get("higgsfield_job_id")
    if not job_id:
        fail(f"no {SIDE} with a higgsfield_job_id — submit with --go first")
    r = subprocess.run([PY, str(WS / "higgsfield.py"), "job", job_id], capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"higgsfield job query failed:\n{r.stderr[-500:]}")
    info = json.loads(r.stdout or "{}")
    status = (info.get("status") or "").lower()
    if status in FAILED:
        side["status"] = "failed"
        (job / SIDE).write_text(json.dumps(side, ensure_ascii=False, indent=2))
        print(f"FAILED {status}")
        return 0
    if status not in COMPLETED:
        print(f"PENDING {status or '—'}")
        return 0
    url = info.get("url")
    if not url:
        fail("job completed but no result url")
    raw = job / "broll_raw.mp4"
    _download(url, raw)
    out = job / "broll_916.mp4"
    crop_916(raw, out)
    rel = str(out.relative_to(WS))
    _set_brief_video(job, rel)
    side.update(status="done", result_url=url, video=rel, completed_at=e.now_iso())
    (job / SIDE).write_text(json.dumps(side, ensure_ascii=False, indent=2))
    print(f"DONE {rel}")
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
    ap = argparse.ArgumentParser(description="F7 RV3 — Seedance b-roll generation (the credit spend; dry-run by default)")
    ap.add_argument("job_dir", help="Job folder with a type=reel brief.json")
    ap.add_argument("--go", action="store_true", help="ACTUALLY spend ONE reel credit + submit (needs Marvin's OK)")
    ap.add_argument("--poll", action="store_true", help="Poll the submitted job; on completion download + 9:16 crop")
    ap.add_argument("--scene", help="Override the auto-proposed b-roll scene")
    ap.add_argument("--owned-clip", help="0-credit PROOF: crop an OWNED clip into brief.video (no generation)")
    args = ap.parse_args()

    job = Path(args.job_dir).resolve()
    brief = _load_brief(job)

    if args.owned_clip:
        sys.exit(do_owned_clip(job, Path(args.owned_clip).resolve()))
    if args.poll:
        sys.exit(do_poll(job))
    scene = args.scene or propose_scene(brief)
    sys.exit(do_plan(job, brief, scene, go=args.go))


if __name__ == "__main__":
    main()
