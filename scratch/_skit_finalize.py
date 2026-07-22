"""Resubmit rate-limited shots (retry as concurrency frees), poll all Veo jobs, download clips."""
import subprocess, json, time
from pathlib import Path

WD = Path("output/hf_skit_test")
def sh(c): return subprocess.run(c, capture_output=True, text=True)

jobs = json.loads((WD/"skit_jobs.json").read_text())
REFS = {"P":"1249c190-1e90-4138-b1ad-73655e02c415",
        "U":"4c3d441d-4589-4d17-92fe-ab047ae382a6",
        "O":"59f72b4c-ce56-4cb3-bf6e-5250c705481b"}
ROOM = {"P":"plain room with a green wall","U":"room with a wood-slat wall","O":"room with a wood-slat wall"}
DELIV = {9:"casual and confident",10:"matter-of-fact",11:"considering, nodding"}

def prompt(c,line,deliv):
    return (f"The man from the reference photo talks directly to the camera, casual handheld selfie video, "
            f"eye-level medium close-up, {ROOM[c]}, wearing a white ribbed tank top with a small black clip-on "
            f"lav microphone on his chest. {deliv}. Natural lip-sync, clear speech. He says: \"{line}\"")

def submit(c,line,dur,deliv):
    r = sh(["higgsfield","generate","create","veo3_1","--image",REFS[c],"--model","veo-3-1-fast",
            "--quality","high","--duration",str(dur),"--aspect_ratio","9:16","--prompt",prompt(c,line,deliv),"--json"])
    try: return json.loads(r.stdout)[0], None
    except: return None, (r.stdout + r.stderr)

# 1) resubmit failed shots, retrying while rate-limited
for j in jobs:
    if not j["job_id"]:
        for _ in range(30):
            jid,err = submit(j["char"], j["line"], j["dur"], DELIV.get(j["n"],""))
            if jid:
                j["job_id"]=jid; j["err"]=None; print(f"resubmit shot {j['n']} -> {jid}"); break
            if "rate_limit" in str(err):
                print(f"shot {j['n']} rate-limited; wait 25s"); time.sleep(25)
            else:
                print(f"shot {j['n']} ERR {str(err)[:140]}"); time.sleep(10)
(WD/"skit_jobs.json").write_text(json.dumps(jobs,indent=2))

# 2) poll all, download
def stat(jid):
    r = sh(["python3","higgsfield.py","job",jid])
    try: d=json.loads(r.stdout); return d.get("status"), d.get("url")
    except: return None, None

pending = {j["n"]: j["job_id"] for j in jobs if j["job_id"]}
done = {}
for _ in range(160):
    for n,jid in list(pending.items()):
        st,url = stat(jid)
        if st=="completed" and url:
            out = WD/f"shot_{n:02d}.mp4"; sh(["curl","-s",url,"-o",str(out)]); done[n]=str(out)
            print(f"shot {n} DONE"); del pending[n]
        elif st in ("failed","canceled"):
            print(f"shot {n} {st}"); del pending[n]
    if not pending: break
    time.sleep(15)
print(f"\ndownloaded {len(done)}/{len(jobs)} shots:", sorted(done))
r = sh(["python3","higgsfield.py","credits"]);
try: print("credits now:", json.loads(r.stdout)["credits"])
except: pass
