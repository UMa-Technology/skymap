import numpy as np, cv2, os, subprocess, tempfile, sys, glob, time
sys.path.insert(0,"tools")
from clean_dss.background import upsample_smooth
from clean_dss.pyramid import child_ids, rebuild_parent
W=512; SCRATCH=os.environ["SCRATCH"]
d=np.load(f"{SCRATCH}/delta512.npz"); dR,dG,dB=d['dR'],d['dG'],d['dB']
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
def apply_n4(npix):
    img=cv2.imread(n4path(npix)); 
    if img is None: return None
    base=npix*1024
    uR=upsample_smooth(dR[base+cellsub].reshape(32,32),W)
    uG=upsample_smooth(dG[base+cellsub].reshape(32,32),W)
    uB=upsample_smooth(dB[base+cellsub].reshape(32,32),W)
    return np.clip(img.astype(np.float32)+np.stack([uB,uG,uR],2),0,255).astype(np.uint8)

t0=time.time()
# PASS 1: all N4 in place
n4files=sorted(glob.glob(os.path.join(BASE,"Norder4","Dir*","Npix*.webp")))
print(f"PASS1 N4: {len(n4files)} tiles",flush=True)
for i,f in enumerate(n4files):
    npix=int(os.path.basename(f)[4:-5]); c=apply_n4(npix)
    if c is not None: save_lossless(c,f)
    if (i+1)%400==0: print(f"  N4 {i+1}/{len(n4files)}  {time.time()-t0:.0f}s",flush=True)
# PASS 2: rebuild all N3 from corrected N4
n3files=sorted(glob.glob(os.path.join(BASE,"Norder3","Dir*","Npix*.webp")))
print(f"PASS2 N3: {len(n3files)} tiles",flush=True)
for i,f in enumerate(n3files):
    parent=int(os.path.basename(f)[4:-5]); kids=child_ids(parent)
    ch=[cv2.imread(n4path(k)) for k in kids]
    if any(c is None for c in ch): 
        print("  skip N3",parent,"missing child",flush=True); continue
    save_lossless(rebuild_parent(ch),f)
    if (i+1)%200==0: print(f"  N3 {i+1}/{len(n3files)}  {time.time()-t0:.0f}s",flush=True)
# total size
tot=sum(os.path.getsize(f) for f in glob.glob(os.path.join(BASE,"Norder*","Dir*","Npix*.webp")))
print(f"DONE {time.time()-t0:.0f}s  survey size now {tot/1e6:.0f} MB",flush=True)
