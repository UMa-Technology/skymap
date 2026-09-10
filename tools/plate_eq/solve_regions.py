"""Production per-region per-channel offset solve on GSSS winner-region boundaries."""
import os, sys
import numpy as np, healpy as hp
from scipy.sparse import csr_matrix, vstack, identity
from scipy.sparse.linalg import lsqr
SC=os.path.dirname(os.path.abspath(__file__))
NS=512; NPIX=hp.nside2npix(NS); ar=np.arange(NPIX)
CAP=float(os.environ.get("CAP","5.0")); ANCHOR=float(os.environ.get("ANCHOR","0.15"))
HUBER=float(os.environ.get("HUBER","4.5")); TEX=float(os.environ.get("TEX","2.5")); SLP=float(os.environ.get("SLP","0.8"))
z=np.load(SC+"/mapbase.npz"); d=np.load(SC+"/delta512.npz"); dL=np.load(SC+"/dLum512.npy")
cur={'R':z['mapR'].astype(np.float64)+d['dR']+dL,'G':z['mapG'].astype(np.float64)+d['dG']+dL,'B':z['mapB'].astype(np.float64)+d['dB']+dL}
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
for dcur in range(1,7):
    nb=neighT[frontier].ravel(); src=np.repeat(frontier,8)
    okn=nb>=0; nb=nb[okn];src=src[okn]
    ok2=(depth[nb]==127)&(lab[nb]==lab[src]); nb=nb[ok2];src=src[ok2]
    if len(nb)==0: break
    oo=np.argsort(nb,kind='stable'); nb=nb[oo];src=src[oo]
    fi=np.unique(nb,return_index=True)[1]; nb=nb[fi];src=src[fi]
    pairof[nb]=pairof[src]; depth[nb]=dcur; frontier=nb
band=(depth>=1)&(depth<=6)&(pairof>=0)
bp=np.where(band)[0]; pid=pairof[bp]; sideA=(lab[bp]==pa[pid]); dep=depth[bp].astype(np.float64)
kps=pid*2+sideA.astype(np.int64)
oo=np.argsort(kps,kind='stable'); kps_s=kps[oo]; bp_s=bp[oo]; dep_s=dep[oo]
ukp,stt=np.unique(kps_s,return_index=True)
segpix=np.split(bp_s,stt[1:]); segdep=np.split(dep_s,stt[1:])
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
def solve(ch):
    s,wgt=measure(cur[ch]); ok=wgt>0.5
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
    off=np.clip(off-np.median(off),-CAP,CAP)
    v=cur[ch]+off[lab]; s2,_=measure(v)
    print("%s: RMS %.3f->%.3f | off p50/p90/p99/max %.2f/%.2f/%.2f/%.2f | cap%%=%.1f"%(ch,
      np.sqrt(np.average(s0**2,weights=wgt[idx])), np.sqrt(np.average(s2[idx]**2,weights=wgt[idx])),
      np.percentile(np.abs(off),50),np.percentile(np.abs(off),90),np.percentile(np.abs(off),99),
      np.abs(off).max(),100*np.mean(np.abs(off)>=CAP-1e-6)),flush=True)
    return off
offs={ch:solve(ch) for ch in ('R','G','B')}
np.savez(SC+"/region_offsets5.npz", lab=lab, offR=offs['R'], offG=offs['G'], offB=offs['B'])
print("saved region_offsets5.npz")
