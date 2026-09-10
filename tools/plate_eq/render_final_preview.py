"""Full-res before/after crops at user's spots. before = tile - delta (exact reconstruction)."""
import numpy as np, healpy as hp, cv2, os, sys
sys.path.insert(0,"tools")
from clean_dss.background import upsample_smooth
SC=os.environ["SCRATCH"]; W=512; NST=16
OUT="apps/web-frontend/public/plate-eq-review"
d=np.load(SC+"/delta_regions_final.npz"); dR,dG,dB=d['dR'],d['dG'],d['dB']
def p1(n):
    n=n&0xffff;n=(n|(n<<8))&0x00FF00FF;n=(n|(n<<4))&0x0F0F0F0F
    n=(n|(n<<2))&0x33333333;n=(n|(n<<1))&0x55555555;return n
cy,cx=np.meshgrid(np.arange(32),np.arange(32),indexing='ij'); cellsub=(p1(cy)|(p1(cx)<<1)).ravel()
BASE="apps/skydata/surveys/dss/Norder4"
def tilepath(npix): return os.path.join(BASE,f"Dir{(npix//10000)*10000}",f"Npix{npix}.webp")
def tile_pair(npix):
    img=cv2.imread(tilepath(npix))
    if img is None: return None,None
    base=npix*1024
    delta=np.stack([upsample_smooth(dB[base+cellsub].reshape(32,32),W),
                    upsample_smooth(dG[base+cellsub].reshape(32,32),W),
                    upsample_smooth(dR[base+cellsub].reshape(32,32),W)],2)
    before=np.clip(img.astype(np.float32)-delta,0,255)
    return before,img.astype(np.float32)
def subpix_sky(npix,step=2):
    xs=np.arange(0,W,step); X,Y=np.meshgrid(xs,xs)
    sub=(p1(Y.ravel())|(p1(X.ravel())<<1)); nest=npix*(W*W)+sub
    ra,dec=hp.pix2ang(NST*W,nest,nest=True,lonlat=True)
    return X.ravel(),Y.ravel(),ra,dec
def gno(r,de,r0,d0):
    r=np.radians(r);de=np.radians(de);rr=np.radians(r0);dd=np.radians(d0)
    cosc=np.sin(dd)*np.sin(de)+np.cos(dd)*np.cos(de)*np.cos(r-rr)
    return np.degrees(np.cos(de)*np.sin(r-rr)/cosc),np.degrees((np.cos(dd)*np.sin(de)-np.sin(dd)*np.cos(de)*np.cos(r-rr))/cosc)
def stretch(rgb):
    v=np.clip(rgb,0,255)/255.0; a=np.percentile(v,2);b=np.percentile(v,92)
    return (np.clip((v-a)/max(b-a,1e-3),0,1)**0.6*255).astype(np.uint8)
from scipy.spatial import cKDTree
def render(r0,d0,half,tag,px=42):
    vec=hp.ang2vec(r0,d0,lonlat=True)
    tiles=hp.query_disc(NST,vec,np.radians(half*1.5+3),nest=True,inclusive=True)
    XI=[];ETA=[];BEF=[];AFT=[]
    for t in tiles:
        bimg,aimg=tile_pair(int(t))
        if bimg is None: continue
        X,Y,ra,dec=subpix_sky(int(t))
        xi,eta=gno(ra,dec,r0,d0); sel=(np.abs(xi)<half)&(np.abs(eta)<half)
        if not sel.any(): continue
        X,Y=X[sel],Y[sel]
        BEF.append(bimg[Y,X]); AFT.append(aimg[Y,X]); XI.append(xi[sel]);ETA.append(eta[sel])
    XI=np.concatenate(XI);ETA=np.concatenate(ETA)
    BEF=np.concatenate(BEF);AFT=np.concatenate(AFT)
    N=int(2*half*px); GX,GY=np.meshgrid(np.linspace(-half,half,N),np.linspace(half,-half,N))
    qi=cKDTree(np.stack([XI,ETA],1)).query(np.stack([GX.ravel(),GY.ravel()],1))[1]
    b=stretch(BEF[qi].reshape(N,N,3)); a=stretch(AFT[qi].reshape(N,N,3))
    cv2.imwrite(os.path.join(OUT,"mwfix_%s.png"%tag),np.hstack([b,np.full((N,10,3),60,np.uint8),a]))
    print(tag,"done",flush=True)
SPOTS=[("M25",277.9,-19.1,5),("M7",268.5,-34.8,5),("NGC6167",248.6,-49.8,5),("NGC4463",187.5,-64.8,5),
       ("IC1805",38.2,61.5,5),("NGC6633",276.9,6.6,5),("IC2149",89.1,46.1,5),("HIP104871",318.9,-16.1,5),
       ("HIP43",0.1,1.1,5)]
for tag,r0,d0,h in SPOTS: render(r0,d0,h,tag)
print("ALL DONE")
