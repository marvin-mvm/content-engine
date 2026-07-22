"""Reshoot the 5 Present-self shots with the correct young-Creator frame; poll those + the 2
Optimized reshoots (6,9); download all, overwriting shot_NN.mp4."""
import subprocess, json, time
from pathlib import Path
WD = Path("output/hf_skit_test")
def sh(c): return subprocess.run(c, capture_output=True, text=True)

PID = json.loads(sh(["python3","higgsfield.py","upload",str(WD/"ref_present2.png")]).stdout)["id"]
print("present ref:", PID)

def submit(line,dur,deliv):
    p=("The man from the reference photo talks directly to the camera, casual handheld selfie video, "
       "eye-level medium close-up, plain room with a green wall, wearing a white ribbed tank top with a small "
       f"black clip-on lav microphone. {deliv}. Natural lip-sync, clear speech. He says: \"{line}\"")
    r=sh(["higgsfield","generate","create","veo3_1","--image",PID,"--model","veo-3-1-fast","--quality","high",
          "--duration",str(dur),"--aspect_ratio","9:16","--prompt",p,"--json"])
    try: return json.loads(r.stdout)[0]
    except: return None

PRESENT = {
 1:("No, don't do it.",4,"holding a syringe, looking alarmed"),
 5:("Okay, now who's this guy?",4,"confused, turning to look, hands free"),
 7:("I mean, that does sound pretty awesome. And this guy looks like shit.",6,"amused, gesturing, hands free"),
 8:("Okay, so you're telling me nothing goes wrong with this whole peptide thing?",6,"skeptical, hands free"),
 11:("Hmm. Yeah.",4,"considering, nodding, hands free"),
}
pending = {6:"5463a00a-ad24-41f4-80bf-277fb8e3c00b", 9:"04fc8fbb-0159-4d35-aba5-93e6078f9c7b"}
for n,(line,dur,deliv) in PRESENT.items():
    for _ in range(30):
        jid=submit(line,dur,deliv)
        if jid: pending[n]=jid; print(f"present shot {n} -> {jid}"); break
        print(f"shot {n} rate-limited, wait 25s"); time.sleep(25)

def stat(jid):
    r=sh(["python3","higgsfield.py","job",jid])
    try: d=json.loads(r.stdout); return d.get("status"),d.get("url")
    except: return None,None

done=[]
for _ in range(160):
    for n,jid in list(pending.items()):
        st,url=stat(jid)
        if st=="completed" and url:
            sh(["curl","-s",url,"-o",str(WD/f"shot_{n:02d}.mp4")]); done.append(n); del pending[n]; print(f"shot {n} DONE")
        elif st in ("failed","canceled","nsfw"):
            print(f"shot {n} {st}"); del pending[n]
    if not pending: break
    time.sleep(15)
print("done:", sorted(done))
print("credits:", json.loads(sh(["python3","higgsfield.py","credits"]).stdout)["credits"])
