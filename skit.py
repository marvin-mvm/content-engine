#!/usr/bin/env python3
"""skit.py — config-driven multi-character talking-skit recreation (Higgsfield Veo 3.1).

Generalizes the one-off _skit_*.py creatordemo recreation into a reusable, credit-GATED
pipeline. One JSON spec describes the whole skit (characters + their reference frames +
per-shot line/duration/delivery/label); four stages do the work:

  probe    <spec>          download source + contact-sheet + whisper transcript   (0 credits)
  plan     <spec>          resolve ref frames + FREE per-shot cost preview         (0 credits)
  shoot    <spec> --go     upload refs, submit Veo shots, poll, download clips     (SPENDS)
  assemble <spec>          normalize + top-labels (+ optional --subtitles) + concat (0 credits)

`shoot` REFUSES to spend unless --go is passed (project rule: ASK before any Higgsfield
credit). Recipe + gotchas: docs/SKIT.md. Skill: acme-skit.

Spec schema (see schemas/examples/future_self_demo.skit.json):
{
  "name": "future_self_demo",
  "source_url": "https://www.instagram.com/reel/XXXX/",   # optional — only for probe/extract
  "aspect_ratio": "9:16", "model": "veo3_1", "model_variant": "veo-3-1-fast",
  "quality": "high",
  "base_prompt": "The man from the reference photo talks directly to the camera, casual "
                 "handheld selfie video, eye-level medium close-up",
  "wardrobe": "wearing a white ribbed tank top with a small black clip-on lav microphone",
  "safety_cues": "wholesome, tasteful, fully dressed",
  "characters": {
    "P": {"ref_ts": 1,  "room": "plain room with a green wall"},          # extract frame @1s
    "U": {"ref_image": "output/skits/.../ref_u.png", "room": "wood-slat wall"},  # local png
    "O": {"ref_id": "59f72b4c-...", "room": "wood-slat wall"}             # pre-uploaded media id
  },
  "shots": [
    {"char":"P","line":"No, don't do it.","dur":4,"delivery":"holding a syringe, alarmed",
     "label":"Choosing Your Future Self"},
    ...
  ]
}
"""
import argparse, json, os, subprocess, sys, time
from pathlib import Path

HF = "higgsfield"                      # raw CLI (/opt/homebrew/bin) — Veo generate/cost
HFPY = ["python3", "higgsfield.py"]    # wrapper — upload/credits/job
CONCURRENCY_CAP = 8                    # Ultra plan
NSFW_RETRIES = 8                       # flagged/failed clips auto-refund → just retry


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def credits():
    try:
        return json.loads(sh(HFPY + ["credits"]).stdout)["credits"]
    except Exception:
        return None


def load_spec(path):
    spec = json.loads(Path(path).read_text())
    spec.setdefault("aspect_ratio", "9:16")
    spec.setdefault("model", "veo3_1")
    spec.setdefault("model_variant", "veo-3-1-fast")
    spec.setdefault("quality", "high")
    spec.setdefault("safety_cues", "wholesome, tasteful, fully dressed")
    spec.setdefault("wardrobe", "")
    return spec


def wd_for(spec):
    wd = Path("output/skits") / spec["name"]
    wd.mkdir(parents=True, exist_ok=True)
    return wd


def build_prompt(spec, char, shot):
    """Compose the Veo prompt: framing + room + wardrobe + delivery + safety + verbatim line."""
    ch = spec["characters"][char]
    room = ch.get("room", "plain room")
    parts = [spec["base_prompt"].rstrip(". "), room]
    if spec.get("wardrobe"):
        parts.append(spec["wardrobe"].rstrip(". "))
    if shot.get("delivery"):
        parts.append(shot["delivery"].rstrip(". "))
    if spec.get("safety_cues"):
        parts.append(spec["safety_cues"].rstrip(". "))
    body = ", ".join(p for p in parts if p)
    return f'{body}. Natural lip-sync, clear speech. He says: "{shot["line"]}"'


# ---------------------------------------------------------------- source / refs
def download_source(spec, wd):
    src = wd / "source.mp4"
    if src.exists():
        return src
    url = spec.get("source_url")
    if not url:
        sys.exit("no source.mp4 and no source_url in spec — supply ref frames instead")
    print(f"scraping {url} …")
    r = sh(["python3", "apify.py", "scrape", url, "--raw"])
    try:
        data = json.loads(r.stdout)
        item = data[0] if isinstance(data, list) else data
        vurl = item.get("videoUrl") or item.get("video_url") or item.get("videoUrlHd")
    except Exception:
        vurl = None
    if not vurl:
        sys.exit(f"could not find videoUrl in apify response:\n{r.stdout[:300]}")
    sh(["curl", "-sL", vurl, "-o", str(src)])
    print(f"→ {src}")
    return src


def extract_frame(src, ts, out):
    sh(["ffmpeg", "-y", "-ss", str(ts), "-i", str(src),
        "-frames:v", "1", str(out), "-loglevel", "error"])
    return out


def resolve_refs(spec, wd, upload=False):
    """Return {char: ref}  where ref is an uploaded media id (upload=True) or a local path.
    Priority: ref_id (already uploaded) > ref_image (local png) > ref_ts (extract from source)."""
    src = None
    refs = {}
    for char, ch in spec["characters"].items():
        if ch.get("ref_id"):
            refs[char] = ch["ref_id"]
            continue
        if ch.get("ref_image"):
            path = Path(ch["ref_image"])
        elif "ref_ts" in ch:
            if src is None:
                src = download_source(spec, wd)
            path = extract_frame(src, ch["ref_ts"], wd / f"ref_{char}.png")
        else:
            sys.exit(f"character {char} has no ref_id / ref_image / ref_ts")
        if upload:
            rid = json.loads(sh(HFPY + ["upload", str(path)]).stdout)["id"]
            refs[char] = rid
        else:
            refs[char] = str(path)
    return refs


# ---------------------------------------------------------------- stages
def stage_probe(spec):
    wd = wd_for(spec)
    src = download_source(spec, wd)
    sheet = wd / "contact_sheet.png"
    sh(["ffmpeg", "-y", "-i", str(src), "-vf", "fps=1/2,scale=320:-1,tile=5x5",
        str(sheet), "-loglevel", "error"])
    txt = wd / "transcript.txt"
    r = sh(["python3", "-c",
            "import whisper,sys;print(whisper.load_model('tiny')"
            ".transcribe(sys.argv[1])['text'])", str(src)])
    txt.write_text(r.stdout.strip() or r.stderr[:500])
    print(f"contact sheet → {sheet}\ntranscript    → {txt}")
    print("Eyeball the sheet, pick ONE clean frame per character, set ref_ts in the spec, "
          "then run:  python3 skit.py plan <spec>")


def stage_plan(spec):
    wd = wd_for(spec)
    refs = resolve_refs(spec, wd, upload=False)
    plan, total = [], 0.0
    for i, shot in enumerate(spec["shots"], 1):
        char = shot["char"]
        prompt = build_prompt(spec, char, shot)
        cost = _cost(spec, refs[char], shot["dur"], prompt)
        total += cost or 0
        plan.append({"n": i, "char": char, "dur": shot["dur"], "line": shot["line"],
                     "label": shot.get("label", ""), "ref": refs[char],
                     "prompt": prompt, "cost": cost})
        print(f"shot {i:>2} [{char}] {shot['dur']}s  ~{cost}cr  {shot['line'][:48]}")
    (wd / "plan.json").write_text(json.dumps(plan, indent=2))
    bal = credits()
    print(f"\n{len(plan)} shots · estimated ~{round(total)} credits total "
          f"(balance {bal}) · plan → {wd/'plan.json'}")
    print("Nothing spent yet. To generate:  python3 skit.py shoot <spec> --go")


def _cost(spec, ref, dur, prompt):
    r = sh([HF, "generate", "cost", spec["model"], "--image", ref, "--model",
            spec["model_variant"], "--quality", spec["quality"], "--duration", str(dur),
            "--aspect_ratio", spec["aspect_ratio"], "--prompt", prompt, "--json"])
    try:
        d = json.loads(r.stdout)
        d = d[0] if isinstance(d, list) else d
        return d.get("cost") or d.get("credits") or d.get("total_cost")
    except Exception:
        return None


def _submit(spec, ref_id, dur, prompt):
    r = sh([HF, "generate", "create", spec["model"], "--image", ref_id, "--model",
            spec["model_variant"], "--quality", spec["quality"], "--duration", str(dur),
            "--aspect_ratio", spec["aspect_ratio"], "--prompt", prompt, "--json"])
    try:
        return json.loads(r.stdout)[0], None
    except Exception:
        return None, (r.stdout + r.stderr)[:200]


def _job(jid):
    r = sh(HFPY + ["job", jid])
    try:
        d = json.loads(r.stdout)
        return d.get("status"), d.get("url")
    except Exception:
        return None, None


def stage_shoot(spec, go):
    wd = wd_for(spec)
    if not go:
        sys.exit("REFUSING to spend credits. Re-run `plan` to preview, then add --go to shoot.")
    before = credits()
    print(f"credits before: {before}")
    refs = resolve_refs(spec, wd, upload=True)          # uploads reference frames
    (wd / "refs.json").write_text(json.dumps(refs, indent=2))

    jobs = []
    for i, shot in enumerate(spec["shots"], 1):
        prompt = build_prompt(spec, shot["char"], shot)
        jid = None
        for _ in range(30):                              # retry while concurrency-capped
            jid, err = _submit(spec, refs[shot["char"]], shot["dur"], prompt)
            if jid:
                break
            if err and "rate_limit" in err:
                print(f"shot {i} rate-limited (cap {CONCURRENCY_CAP}); wait 25s")
                time.sleep(25)
            else:
                print(f"shot {i} ERR {err}")
                time.sleep(8)
        jobs.append({"n": i, "char": shot["char"], "line": shot["line"], "dur": shot["dur"],
                     "delivery": shot.get("delivery", ""), "label": shot.get("label", ""),
                     "job_id": jid, "attempts": 1})
        print(f"shot {i:>2} [{shot['char']}] -> {jid or 'FAILED'}")
    (wd / "jobs.json").write_text(json.dumps(jobs, indent=2))

    # poll + download; retry nsfw/failed (auto-refunded) up to NSFW_RETRIES
    pending = {j["n"]: j["job_id"] for j in jobs if j["job_id"]}
    retries = {j["n"]: 0 for j in jobs}
    done = {}
    by_n = {j["n"]: j for j in jobs}
    for _ in range(240):
        for n, jid in list(pending.items()):
            st, url = _job(jid)
            if st == "completed" and url:
                sh(["curl", "-sL", url, "-o", str(wd / f"shot_{n:02d}.mp4")])
                done[n] = jid
                del pending[n]
                print(f"shot {n} DONE")
            elif st in ("failed", "canceled", "nsfw"):
                del pending[n]
                if retries[n] < NSFW_RETRIES:
                    retries[n] += 1
                    sj = by_n[n]
                    prompt = build_prompt(spec, sj["char"],
                                          {"line": sj["line"], "delivery": sj["delivery"]})
                    jid2, _ = _submit(spec, refs[sj["char"]], sj["dur"], prompt)
                    if jid2:
                        pending[n] = jid2
                        print(f"shot {n} {st} → retry {retries[n]}/{NSFW_RETRIES}")
                else:
                    print(f"shot {n} {st} — gave up after {NSFW_RETRIES} retries")
        if not pending:
            break
        time.sleep(15)

    after = credits()
    print(f"\ndownloaded {len(done)}/{len(jobs)} shots · credits {before} → {after} "
          f"(spent ~{None if None in (before, after) else round(before - after)})")
    if len(done) < len(jobs):
        print("MISSING:", sorted(set(range(1, len(jobs) + 1)) - set(done)),
              "— re-run shoot --go (completed shots are skipped-safe? no: it re-submits all; "
              "delete good shot_NN.mp4 only if you want them redone)")
    else:
        print("all shots down. assemble:  python3 skit.py assemble <spec>"
              " [--subtitles]")


# ---------------------------------------------------------------- assemble
def _font():
    for f in ["/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
              "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/Library/Fonts/Arial Bold.ttf"]:
        if os.path.exists(f):
            return f
    return None


def _text_png(text, path, W, size, pad_top=16):
    from PIL import Image, ImageDraw, ImageFont
    fp = _font()
    fnt = ImageFont.truetype(fp, size) if fp else ImageFont.load_default()
    # wrap to <= ~2 lines
    words, lines, cur = text.split(), [], ""
    tmp = ImageDraw.Draw(Image.new("RGBA", (W, 10)))
    for w in words:
        t = (cur + " " + w).strip()
        if tmp.textbbox((0, 0), t, font=fnt)[2] > W - 80 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = t
    lines.append(cur)
    line_h = size + 18
    img = Image.new("RGBA", (W, pad_top * 2 + line_h * len(lines)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = pad_top
    for ln in lines:
        w = d.textbbox((0, 0), ln, font=fnt)[2]
        x = (W - w) // 2
        d.text((x + 3, y + 3), ln, font=fnt, fill=(0, 0, 0, 180))
        d.text((x, y), ln, font=fnt, fill=(255, 255, 255, 255))
        y += line_h
    img.save(path)
    return img.size


def stage_assemble(spec, subtitles):
    wd = wd_for(spec)
    W, H = (1080, 1920) if spec["aspect_ratio"] == "9:16" else (1920, 1080)
    norm = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1")
    segs = []
    for i, shot in enumerate(spec["shots"], 1):
        src = wd / f"shot_{i:02d}.mp4"
        if not src.exists():
            sys.exit(f"missing {src} — run shoot first")
        out = wd / f"seg_{i:02d}.mp4"
        overlays, filters = [], [f"[0]{norm}[base]"]
        last = "base"
        inputs = ["-i", str(src)]
        idx = 1
        if shot.get("label"):
            lp = wd / f"label_{i}.png"
            _text_png(shot["label"], lp, W, 66)
            inputs += ["-i", str(lp)]
            filters.append(f"[{last}][{idx}]overlay=(W-w)/2:150[l{i}]")
            last = f"l{i}"
            idx += 1
        if subtitles and shot.get("line"):
            sp = wd / f"sub_{i}.png"
            _, sh_h = _text_png(shot["line"], sp, W, 52)
            inputs += ["-i", str(sp)]
            filters.append(f"[{last}][{idx}]overlay=(W-w)/2:H-h-160[s{i}]")
            last = f"s{i}"
            idx += 1
        fc = ";".join(filters)
        cmd = ["ffmpeg", "-y"] + inputs + ["-filter_complex", fc, "-map", f"[{last}]",
               "-map", "0:a?", "-c:v", "libx264", "-crf", "18", "-preset", "fast",
               "-c:a", "aac", "-ar", "44100", "-r", "30", str(out), "-loglevel", "error"]
        subprocess.run(cmd, check=True)
        segs.append(out)

    lst = wd / "concat.txt"
    lst.write_text("".join(f"file '{s.resolve()}'\n" for s in segs))
    final = wd / f"{spec['name']}.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-c:a", "aac",
                    "-ar", "44100", "-r", "30", str(final), "-loglevel", "error"], check=True)
    dur = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=noprint_wrappers=1:nokey=1", str(final)]).stdout.strip()
    mb = final.stat().st_size / 1e6
    if mb > 49:  # Telegram bot 50MB ceiling — recompress
        comp = wd / f"{spec['name']}_tg.mp4"
        subprocess.run(["ffmpeg", "-y", "-i", str(final), "-c:v", "libx264", "-crf", "28",
                        "-preset", "medium", "-c:a", "aac", "-b:a", "96k", str(comp),
                        "-loglevel", "error"], check=True)
        print(f"compressed for TG → {comp} ({comp.stat().st_size/1e6:.1f}MB)")
    print(f"FINAL → {final}  duration={dur}s  {mb:.1f}MB  subtitles={subtitles}")


# ---------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(prog="skit", description="Higgsfield Veo-3.1 talking-skit recreation")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("probe", "plan", "shoot", "assemble"):
        sp = sub.add_parser(name)
        sp.add_argument("spec")
        if name == "shoot":
            sp.add_argument("--go", action="store_true", help="actually spend credits")
        if name == "assemble":
            sp.add_argument("--subtitles", action="store_true", help="burn in dialogue subtitles")
    args = ap.parse_args()
    spec = load_spec(args.spec)
    if args.cmd == "probe":
        stage_probe(spec)
    elif args.cmd == "plan":
        stage_plan(spec)
    elif args.cmd == "shoot":
        stage_shoot(spec, args.go)
    elif args.cmd == "assemble":
        stage_assemble(spec, args.subtitles)


if __name__ == "__main__":
    main()
