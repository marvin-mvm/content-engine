"""Assemble the recreated skit: overlay version labels (top-center) on intro shots,
normalize every clip to 1080x1920@30, and concat 1..11 in order."""
import subprocess, os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

WD = Path("output/hf_skit_test")
LABELS = {1:"Choosing Your Future Self", 2:"Unoptimized Version", 4:"Optimized Version"}

FONT = next((f for f in [
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
    "/System/Library/Fonts/Supplemental/Baskerville.ttc",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
] if os.path.exists(f)), None)

def make_label(text, path, W=1080):
    img = Image.new("RGBA", (W, 260), (0,0,0,0)); d = ImageDraw.Draw(img)
    fnt = ImageFont.truetype(FONT, 66) if FONT else ImageFont.load_default()
    words = text.split(" ")
    lines = [text] if len(text) <= 18 else [" ".join(words[:len(words)//2]), " ".join(words[len(words)//2:])]
    y = 16
    for ln in lines:
        bb = d.textbbox((0,0), ln, font=fnt); w = bb[2]-bb[0]; x = (W-w)//2
        d.text((x+3,y+3), ln, font=fnt, fill=(0,0,0,170))
        d.text((x,y), ln, font=fnt, fill=(255,255,255,255))
        y += (bb[3]-bb[1]) + 16
    img.save(path)

NORM = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
segs = []
for n in range(1, 12):
    src = WD/f"shot_{n:02d}.mp4"; out = WD/f"seg_{n:02d}.mp4"
    if n in LABELS:
        lp = WD/f"label_{n}.png"; make_label(LABELS[n], lp)
        subprocess.run(["ffmpeg","-y","-i",str(src),"-i",str(lp),
            "-filter_complex", f"[0]{NORM}[v];[v][1]overlay=(W-w)/2:150[o]",
            "-map","[o]","-map","0:a?","-c:v","libx264","-crf","18","-preset","fast",
            "-c:a","aac","-ar","44100","-r","30",str(out),"-loglevel","error"], check=True)
    else:
        subprocess.run(["ffmpeg","-y","-i",str(src),"-vf",NORM,"-c:v","libx264","-crf","18",
            "-preset","fast","-c:a","aac","-ar","44100","-r","30",str(out),"-loglevel","error"], check=True)
    segs.append(out)

lst = WD/"concat.txt"; lst.write_text("".join(f"file '{s.resolve()}'\n" for s in segs))
final = WD/"creator_skit_recreation.mp4"
subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(lst),
    "-c:v","libx264","-crf","18","-preset","medium","-c:a","aac","-ar","44100","-r","30",
    str(final),"-loglevel","error"], check=True)
dur = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(final)],capture_output=True,text=True).stdout.strip()
print(f"FINAL: {final}  duration={dur}s  font={FONT}")
