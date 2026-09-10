import numpy as np, healpy as hp, cv2, os, subprocess, tempfile, sys, glob, time
sys.path.insert(0,"tools")
from clean_dss.background import upsample_smooth
from clean_dss.pyramid import child_ids, rebuild_parent
SC=os.environ["SCRATCH"]; W=512
NS=512
z=np.load(SC+"/mapbase.npz"); ro=np.load(SC+"/region_offsets5.npz"); lab=ro['lab']; gb=z['gb']
def smf(m): return hp.reorder(hp.smoothing(hp.reorder(m,n2r=True),fwhm=np.radians(0.4)),r2n=True)
dR=smf(ro['offR'][lab].astype(np.float64)); dG=smf(ro['offG'][lab].astype(np.float64)); dB=smf(ro['offB'][lab].astype(np.float64))
# neutral re-anchor: keep high-|b| median shifts equal across channels & zero-mean overall
hb=np.abs(gb)>35
mR,mG,mB=np.median(dR[hb]),np.median(dG[hb]),np.median(dB[hb])
m0=(mR+mG+mB)/3.0
dR+= (m0-mR); dG+=(m0-mG); dB+=(m0-mB)
print("neutral re-anchor shifts:",round(m0-mR,3),round(m0-mG,3),round(m0-mB,3),flush=True)
dR=dR.astype(np.float32);dG=dG.astype(np.float32);dB=dB.astype(np.float32)
np.savez(SC+"/delta_regions_final.npz",dR=dR,dG=dG,dB=dB)
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
t0=time.time(); changed=set(); n=0
files=sorted(glob.glob(os.path.join(BASE,"Norder4","Dir*","Npix*.webp")))
for f in files:
    npix=int(os.path.basename(f)[4:-5]); base=npix*1024
    gR=dR[base+cellsub].reshape(32,32); gG=dG[base+cellsub].reshape(32,32); gB=dB[base+cellsub].reshape(32,32)
    if max(np.abs(gR).max(),np.abs(gG).max(),np.abs(gB).max())<0.3: continue
    img=cv2.imread(f)
    if img is None: continue
    delta=np.stack([upsample_smooth(gB,W),upsample_smooth(gG,W),upsample_smooth(gR,W)],2)
    save_lossless(np.clip(img.astype(np.float32)+delta,0,255).astype(np.uint8),f)
    changed.add(npix//4); n+=1
    if n%400==0: print("N4",n,int(time.time()-t0),"s",flush=True)
print("N4 changed:",n,flush=True)
for j,parent in enumerate(sorted(changed)):
    ch=[cv2.imread(n4path(k)) for k in child_ids(parent)]
    if any(c is None for c in ch): continue
    save_lossless(rebuild_parent(ch),n3path(parent))
    if (j+1)%200==0: print("N3",j+1,"/",len(changed),flush=True)
print("DONE %ds N4=%d N3=%d"%(time.time()-t0,n,len(changed)),flush=True)
