import numpy as np, cv2, os, subprocess, tempfile, sys, glob, time, shutil
sys.path.insert(0,"tools")
from clean_dss.background import upsample_smooth
from clean_dss.pyramid import child_ids, rebuild_parent
SC=os.environ["SCRATCH"]; W=512
c=np.load(SC+"/dDarkDC.npy")
def p1(n):
    n=n&0xffff;n=(n|(n<<8))&0x00FF00FF;n=(n|(n<<4))&0x0F0F0F0F
    n=(n|(n<<2))&0x33333333;n=(n|(n<<1))&0x55555555;return n
cy,cx=np.meshgrid(np.arange(32),np.arange(32),indexing='ij'); cellsub=(p1(cy)|(p1(cx)<<1)).ravel()
SRC="apps/skydata/surveys/dss"; DSTM="apps/skydata/surveys/dss-mono"
def save_lossless(bgr,dst):
    os.makedirs(os.path.dirname(dst),exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".png",delete=False) as tf:
        cv2.imwrite(tf.name,bgr); s=tf.name
    try:
        r=subprocess.run(["cwebp","-quiet","-lossless","-m","6","-o",dst,s],capture_output=True)
        if r.returncode!=0: raise RuntimeError(r.stderr.decode()[:200])
    finally: os.unlink(s)
def n4path(npix): return os.path.join(SRC,"Norder4",f"Dir{(npix//10000)*10000}",f"Npix{npix}.webp")
def n3path(npix): return os.path.join(SRC,"Norder3",f"Dir{(npix//10000)*10000}",f"Npix{npix}.webp")
t0=time.time(); changed=set(); n=0
files=sorted(glob.glob(os.path.join(SRC,"Norder4","Dir*","Npix*.webp")))
for f in files:
    npix=int(os.path.basename(f)[4:-5]); grid=c[npix*1024+cellsub].reshape(32,32)
    if np.abs(grid).max()<0.05: continue
    img=cv2.imread(f)
    if img is None: continue
    up=upsample_smooth(grid,W)[...,None]
    save_lossless(np.clip(img.astype(np.float32)+up,0,255).astype(np.uint8),f)
    changed.add(npix//4); n+=1
    if n%400==0: print("N4",n,int(time.time()-t0),"s",flush=True)
print("PASS1 colour N4 changed:",n,flush=True)
for j,parent in enumerate(sorted(changed)):
    ch=[cv2.imread(n4path(k)) for k in child_ids(parent)]
    if any(x is None for x in ch): continue
    save_lossless(rebuild_parent(ch),n3path(parent))
print("PASS2 colour N3 rebuilt:",len(changed),flush=True)
# regenerate mono from colour
nm=0
for f in sorted(glob.glob(os.path.join(SRC,"Norder4","Dir*","Npix*.webp"))):
    img=cv2.imread(f)
    if img is None: continue
    L=(0.114*img[:,:,0]+0.587*img[:,:,1]+0.299*img[:,:,2]).astype(np.float32)
    mono=np.repeat(np.clip(L,0,255).astype(np.uint8)[:,:,None],3,axis=2)
    save_lossless(mono, f.replace(SRC,DSTM)); nm+=1
    if nm%600==0: print("monoN4",nm,flush=True)
def m4path(npix): return os.path.join(DSTM,"Norder4",f"Dir{(npix//10000)*10000}",f"Npix{npix}.webp")
for f in sorted(glob.glob(os.path.join(SRC,"Norder3","Dir*","Npix*.webp"))):
    parent=int(os.path.basename(f)[4:-5])
    ch=[cv2.imread(m4path(k)) for k in child_ids(parent)]
    if any(x is None for x in ch): continue
    save_lossless(rebuild_parent(ch), f.replace(SRC,DSTM))
print("DONE %ds colourN4=%d monoN4=%d"%(time.time()-t0,n,nm),flush=True)
