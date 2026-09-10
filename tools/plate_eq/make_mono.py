import numpy as np, cv2, os, subprocess, tempfile, sys, glob, time, shutil
sys.path.insert(0,"tools")
from clean_dss.pyramid import child_ids, rebuild_parent
SRC="apps/skydata/surveys/dss"; DST="apps/skydata/surveys/dss-mono"
def save_lossless(bgr,dst):
    os.makedirs(os.path.dirname(dst),exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".png",delete=False) as tf:
        cv2.imwrite(tf.name,bgr); s=tf.name
    try:
        r=subprocess.run(["cwebp","-quiet","-lossless","-m","6","-o",dst,s],capture_output=True)
        if r.returncode!=0: raise RuntimeError(r.stderr.decode()[:200])
    finally: os.unlink(s)
t0=time.time(); n=0
files=sorted(glob.glob(os.path.join(SRC,"Norder4","Dir*","Npix*.webp")))
print("N4:",len(files),flush=True)
for f in files:
    img=cv2.imread(f)
    if img is None: continue
    L=(0.114*img[:,:,0]+0.587*img[:,:,1]+0.299*img[:,:,2]).astype(np.float32)
    mono=np.repeat(np.clip(L,0,255).astype(np.uint8)[:,:,None],3,axis=2)
    save_lossless(mono, f.replace(SRC,DST))
    n+=1
    if n%400==0: print("N4",n,int(time.time()-t0),"s",flush=True)
def n4path(npix): return os.path.join(DST,"Norder4",f"Dir{(npix//10000)*10000}",f"Npix{npix}.webp")
n3files=sorted(glob.glob(os.path.join(SRC,"Norder3","Dir*","Npix*.webp")))
for j,f in enumerate(n3files):
    parent=int(os.path.basename(f)[4:-5])
    ch=[cv2.imread(n4path(k)) for k in child_ids(parent)]
    if any(c is None for c in ch): continue
    save_lossless(rebuild_parent(ch), f.replace(SRC,DST))
    if (j+1)%200==0: print("N3",j+1,flush=True)
shutil.copy(os.path.join(SRC,"properties"), os.path.join(DST,"properties"))
tot=sum(os.path.getsize(p) for p in glob.glob(DST+"/Norder*/Dir*/Npix*.webp"))
print("DONE %ds  N4=%d  size=%.0fMB"%(time.time()-t0,n,tot/1e6),flush=True)
