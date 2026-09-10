import numpy as np, cv2, os, subprocess, tempfile, sys, glob, time
sys.path.insert(0,"tools")
from clean_dss.background import upsample_smooth
from clean_dss.pyramid import child_ids, rebuild_parent
W=512; SCRATCH=os.environ["SCRATCH"]
dLum=np.load(f"{SCRATCH}/dLum512.npy")
def p1(n):
    n=n&0xffff;n=(n|(n<<8))&0x00FF00FF;n=(n|(n<<4))&0x0F0F0F0F
    n=(n|(n<<2))&0x33333333;n=(n|(n<<1))&0x55555555;return n
cy,cx=np.meshgrid(np.arange(32),np.arange(32),indexing='ij'); cellsub=(p1(cy)|(p1(cx)<<1)).ravel()
BASE="apps/skydata/surveys/dss"
def n4path(npix): return os.path.join(BASE,"Norder4",f"Dir{(npix//10000)*10000}",f"Npix{npix}.webp")
def n3path(npix): return os.path.join(BASE,"Norder3",f"Dir{(npix//10000)*10000}",f"Npix{npix}.webp")
def save_lossless(bgr,dst):
    with tempfile.NamedTemporaryFile(suffix=".png",delete=False) as tf:
        cv2.imwrite(tf.name,bgr); src=tf.name
    try:
        r=subprocess.run(["cwebp","-quiet","-lossless","-m","6","-o",dst,src],capture_output=True)
        if r.returncode!=0: raise RuntimeError(r.stderr.decode()[:200])
    finally: os.unlink(src)
t0=time.time()
changed_parents=set(); nchg=0
n4files=sorted(glob.glob(os.path.join(BASE,"Norder4","Dir*","Npix*.webp")))
for i,f in enumerate(n4files):
    npix=int(os.path.basename(f)[4:-5]); grid=dLum[npix*1024+cellsub].reshape(32,32)
    if np.abs(grid).max()<0.3: continue      # MW / untouched -> skip
    img=cv2.imread(f)
    up=upsample_smooth(grid,W)[...,None]     # add equally to B,G,R (preserve colour)
    out=np.clip(img.astype(np.float32)+up,0,255).astype(np.uint8)
    save_lossless(out,f); nchg+=1; changed_parents.add(npix//4)
    if nchg%400==0: print(f"  N4 changed {nchg}  {time.time()-t0:.0f}s",flush=True)
print(f"PASS1 done: {nchg} N4 tiles luminance-corrected  {time.time()-t0:.0f}s",flush=True)
# rebuild affected N3 from (updated) N4 children
for j,parent in enumerate(sorted(changed_parents)):
    kids=child_ids(parent); ch=[cv2.imread(n4path(k)) for k in kids]
    if any(c is None for c in ch): continue
    save_lossless(rebuild_parent(ch),n3path(parent))
    if (j+1)%200==0: print(f"  N3 {j+1}/{len(changed_parents)}  {time.time()-t0:.0f}s",flush=True)
print(f"DONE {time.time()-t0:.0f}s  N4 changed={nchg}  N3 rebuilt={len(changed_parents)}",flush=True)
