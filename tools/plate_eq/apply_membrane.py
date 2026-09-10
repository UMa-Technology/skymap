import numpy as np, cv2, os, subprocess, tempfile, sys, glob, time
sys.path.insert(0,"tools")
from clean_dss.background import upsample_smooth
from clean_dss.pyramid import child_ids, rebuild_parent
SC=os.environ["SCRATCH"]; W=512
d=np.load(SC+"/delta_membrane.npz"); dR,dG,dB=d['dR'],d['dG'],d['dB']
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
t0=time.time(); n=0
files=sorted(glob.glob(os.path.join(BASE,"Norder4","Dir*","Npix*.webp")))
print("N4 files:",len(files),flush=True)
for f in files:
    npix=int(os.path.basename(f)[4:-5]); base=npix*1024
    img=cv2.imread(f)
    if img is None: continue
    delta=np.stack([upsample_smooth(dB[base+cellsub].reshape(32,32),W),
                    upsample_smooth(dG[base+cellsub].reshape(32,32),W),
                    upsample_smooth(dR[base+cellsub].reshape(32,32),W)],2)
    save_lossless(np.clip(img.astype(np.float32)+delta,0,255).astype(np.uint8),f)
    n+=1
    if n%400==0: print("N4",n,int(time.time()-t0),"s",flush=True)
print("N4 done:",n,flush=True)
n3files=sorted(glob.glob(os.path.join(BASE,"Norder3","Dir*","Npix*.webp")))
for j,f in enumerate(n3files):
    parent=int(os.path.basename(f)[4:-5])
    ch=[cv2.imread(n4path(k)) for k in child_ids(parent)]
    if any(c is None for c in ch): continue
    save_lossless(rebuild_parent(ch),f)
    if (j+1)%200==0: print("N3",j+1,flush=True)
print("DONE %ds N4=%d N3=%d"%(time.time()-t0,n,len(n3files)),flush=True)
