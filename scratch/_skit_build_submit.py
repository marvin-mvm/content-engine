"""Submit all Veo 3.1 shots to recreate the creatordemo 'Choosing Your Future Self' skit.
One reference frame per character (consistent face) + verbatim line -> faithful talking clip."""
import subprocess, json, time
from pathlib import Path

WD = Path("output/hf_skit_test")
TARGET = WD / "target_creator.mp4"

def sh(cmd): return subprocess.run(cmd, capture_output=True, text=True)

def extract(ts, name):
    out = WD / name
    sh(["ffmpeg","-y","-ss",str(ts),"-i",str(TARGET),"-frames:v","1",str(out),"-loglevel","error"])
    return out

def upload(path):
    r = sh(["python3","higgsfield.py","upload",str(path)])
    return json.loads(r.stdout)["id"]

def credits():
    r = sh(["python3","higgsfield.py","credits"])
    return json.loads(r.stdout)["credits"]

print("credits before:", credits())

# One consistent reference frame per character
REFS = {
    "P": upload(extract(22, "ref_present.png")),      # present-day self (fair hair, beard)
    "U": upload(extract(6,  "ref_unoptimized.png")),  # bald, gaunt
    "O": "59f72b4c-ce56-4cb3-bf6e-5250c705481b",      # optimized (already uploaded, 32s)
}
print("refs:", REFS)
ROOM = {"P":"plain room with a green wall", "U":"room with a wood-slat wall", "O":"room with a wood-slat wall"}

# char, line, duration, delivery, top-label
SHOTS = [
 ("P","No, don't do it.",4,"holding a syringe, looking alarmed","Choosing Your Future Self"),
 ("U","I'm the version that didn't do peptides. Trust me.",6,"older, balding, gaunt and tired, raspy","Unoptimized Version"),
 ("U","The government is trying to kill you.",4,"paranoid, wide-eyed","Unoptimized Version"),
 ("O","Oh, shut up. Do the peptides. Definitely do the peptides.",6,"confident and smug","Optimized Version"),
 ("P","Okay, now who's this guy?",4,"confused, turning to look","" ),
 ("O","I'm the version of you that continued to optimize. And honestly, we just kept getting younger, more jacked, and rich.",8,"smug and proud",""),
 ("P","I mean, that does sound pretty awesome. And this guy looks like shit.",6,"amused, gesturing",""),
 ("P","Okay, so you're telling me nothing goes wrong with this whole peptide thing?",6,"skeptical",""),
 ("O","Oh no, tons of stuff goes wrong. Just not for us.",6,"casual and confident",""),
 ("O","Because we never took any of the contaminated cheap stuff.",4,"matter-of-fact",""),
 ("P","Hmm. Yeah.",4,"considering, nodding",""),
]

def submit(ref_id, line, dur, room, delivery):
    prompt = (f"The man from the reference photo talks directly to the camera, casual handheld selfie video, "
              f"eye-level medium close-up, {room}, wearing a white ribbed tank top with a small black clip-on "
              f"lav microphone on his chest. {delivery}. Natural lip-sync, clear speech. He says: \"{line}\"")
    r = sh(["higgsfield","generate","create","veo3_1","--image",ref_id,"--model","veo-3-1-fast",
            "--quality","high","--duration",str(dur),"--aspect_ratio","9:16","--prompt",prompt,"--json"])
    try:
        return json.loads(r.stdout)[0], None
    except Exception:
        return None, (r.stdout + r.stderr)[:200]

jobs = []
for i,(c,line,dur,delivery,label) in enumerate(SHOTS,1):
    jid,err = submit(REFS[c], line, dur, ROOM[c], delivery)
    jobs.append({"n":i,"char":c,"line":line,"dur":dur,"label":label,"job_id":jid,"err":err})
    print(f"shot {i:>2} [{c}] {dur}s -> {jid or ('ERR '+str(err))}")
    time.sleep(1)

(WD/"skit_jobs.json").write_text(json.dumps(jobs,indent=2))
ok = sum(1 for j in jobs if j["job_id"])
print(f"\nsubmitted {ok}/{len(jobs)} shots")
print("credits after:", credits())
