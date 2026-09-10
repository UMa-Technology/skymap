"""Stage A: aggressive residual DC solve. Stage B: per-seam membrane (ramp +-s/2 over band)."""
import os, numpy as np, healpy as hp
from scipy.sparse import csr_matrix, vstack, identity
from scipy.sparse.linalg import lsqr
SC=os.path.dirname(os.path.abspath(__file__))
NS=512; NPIX=hp.nside2npix(NS); ar=np.arange(NPIX)
z=np.load(SC+"/mapbase.npz"); d=np.load(SC+"/delta512.npz"); dL=np.load(SC+"/dLum512.npy")
dreg=np.load(SC+"/delta_regions_final.npz")
cur={'R':z['mapR'].astype(np.float64)+d['dR']+dL+dreg['dR'],
     'G':z['mapG'].astype(np.float64)+d['dG']+dL+dreg['dG'],
     'B':z['mapB'].astype(np.float64)+d['dB']+dL+dreg['dB']}
wr=np.load(SC+"/winner_red.npz",allow_pickle=True); wb=np.load(SC+"/winner_blue.npz",allow_pickle=True)
comb=wr['winner'].astype(np.int64)*(wb['winner'].max()+2)+(wb['winner'].astype(np.int64)+1)
u,lab=np.unique(comb,return_inverse=True); NL=len(u)
neighT=hp.get_all_neighbours(NS,ar,nest=True).T.copy()
P=[];Q=[]
for k in range(8):
    q=neighT[:,k]; ok=(q>=0)&(q>ar)&(lab[np.clip(q,0,NPIX-1)]!=lab)
    P.append(ar[ok]);Q.append(q[ok])
P=np.concatenate(P);Q=np.concatenate(Q)
la=lab[P];lb=lab[Q]; a=np.minimum(la,lb);b=np.maximum(la,lb)
key=a*NL+b; uk,pairidx=np.unique(key,return_inverse=True)
pa=(uk//NL).astype(np.int64);pb=(uk%NL).astype(np.int64); NPAIR=len(uk)
pairof=np.full(NPIX,-1,np.int64); depth=np.full(NPIX,127,np.int8)
seedpix=np.concatenate([P,Q]); seedpair=np.concatenate([pairidx,pairidx])
o=np.argsort(seedpix,kind='stable'); sp=seedpix[o];pp=seedpair[o]
fi=np.unique(sp,return_index=True)[1]
pairof[sp[fi]]=pp[fi]; depth[sp[fi]]=0; frontier=sp[fi]
MAXD=6
for dcur in range(1,MAXD+1):
    nb=neighT[frontier].ravel(); src=np.repeat(frontier,8)
    okn=nb>=0; nb=nb[okn];src=src[okn]
    ok2=(depth[nb]==127)&(lab[nb]==lab[src]); nb=nb[ok2];src=src[ok2]
    if len(nb)==0: break
    oo=np.argsort(nb,kind='stable'); nb=nb[oo];src=src[oo]
    fi=np.unique(nb,return_index=True)[1]; nb=nb[fi];src=src[fi]
    pairof[nb]=pairof[src]; depth[nb]=dcur; frontier=nb
band=(depth>=1)&(depth<=MAXD)&(pairof>=0)
bp=np.where(band)[0]; pid=pairof[bp]; sideA=(lab[bp]==pa[pid]); dep=depth[bp].astype(np.float64)
kps=pid*2+sideA.astype(np.int64)
oo=np.argsort(kps,kind='stable'); kps_s=kps[oo]; bp_s=bp[oo]; dep_s=dep[oo]
ukp,stt=np.unique(kps_s,return_index=True)
segpix=np.split(bp_s,stt[1:]); segdep=np.split(dep_s,stt[1:])
TEX=4.0; SLP=1.5
def measure(vals):
    est={}
    for kk,pixs,deps in zip(ukp,segpix,segdep):
        if len(pixs)<6: continue
        v=vals[pixs]; med=np.median(v); mad=np.median(np.abs(v-med))+1e-6
        keep=np.abs(v-med)<4*mad
        if keep.sum()<6: continue
        vv=v[keep]; dd=deps[keep]
        A=np.stack([np.ones_like(dd),dd],1)
        c=np.linalg.lstsq(A,vv,rcond=None)[0]
        est[int(kk)]=(c[0],c[1],mad,len(vv))
    s=np.zeros(NPAIR); wgt=np.zeros(NPAIR)
    for i in range(NPAIR):
        ea=est.get(i*2+1); eb=est.get(i*2+0)
        if not ea or not eb: continue
        conf=1.0/(1.0+((ea[2]+eb[2])/TEX)**2+(abs(ea[1]-eb[1])/SLP)**2)
        s[i]=ea[0]-eb[0]; wgt[i]=conf*min(ea[3],eb[3])
    return s,wgt
HUBER=6.0; ANCHOR=0.08; CAP=8.0
def solveA(ch):
    s,wgt=measure(cur[ch]); ok=wgt>0.3
    idx=np.where(ok)[0]; s0=s[idx]; w0=np.sqrt(wgt[idx])
    off=np.zeros(NL)
    for it in range(3):
        r=(off[pa[idx]]-off[pb[idx]])+s0
        hw=np.where(np.abs(r)<HUBER,1.0,HUBER/np.maximum(np.abs(r),1e-9))
        w=w0*np.sqrt(hw)
        rows=np.repeat(np.arange(len(idx)),2); cols=np.concatenate([pa[idx][:,None],pb[idx][:,None]],1).ravel()
        valm=np.empty(2*len(idx)); valm[0::2]=w; valm[1::2]=-w
        A=csr_matrix((valm,(rows,cols)),shape=(len(idx),NL))
        lamw=ANCHOR*np.median(w0)
        Afull=vstack([A,identity(NL,format='csr')*lamw])
        off=off+lsqr(Afull,np.concatenate([-w*r,-lamw*off]),iter_lim=8000)[0]
    return np.clip(off-np.median(off),-CAP,CAP)
# smoothstep weight by depth: w(0)=1 -> w(MAXD)=0
wd=np.zeros(NPIX); m=(depth<=MAXD)&(pairof>=0)
t=1.0-depth[m].astype(np.float64)/ (MAXD+1)
wd[m]=t*t*(3-2*t)
signA=np.zeros(NPIX)  # +1 if pixel on pa side, -1 if pb side
mm=pairof>=0
signA[mm]=np.where(lab[mm]==pa[pairof[mm]],1.0,-1.0)
def stageB(vals):
    s,wgt=measure(vals)
    conf=np.clip(wgt/ (wgt+8.0),0,1)     # soft confidence 0..1
    s_eff=np.clip(s,-8,8)*conf
    c=np.zeros(NPIX)
    c[mm]=-signA[mm]*s_eff[pairof[mm]]/2.0*wd[mm]
    return c
out={}
for ch in ('R','G','B'):
    offA=solveA(ch)
    vA=cur[ch]+offA[lab]
    cB=stageB(vA)
    v2=vA+cB
    s0,w0=measure(cur[ch]); s2,_=measure(v2)
    okw=w0>0.3
    print("%s: RMS %.3f -> %.3f | A p90 %.2f  B |c| p99 %.2f"%(ch,
        np.sqrt(np.average(s0[okw]**2,weights=w0[okw])),
        np.sqrt(np.average(s2[okw]**2,weights=w0[okw])),
        np.percentile(np.abs(offA),90),np.percentile(np.abs(cB),99)),flush=True)
    out[ch]=offA[lab]+cB
np.savez(SC+"/delta_stageAB.npz", dR=out['R'].astype(np.float32),dG=out['G'].astype(np.float32),dB=out['B'].astype(np.float32))
print("saved delta_stageAB.npz")
