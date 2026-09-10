"""Pure per-seam membrane: local ramp +-s/2 within band, zero beyond. 2 iterations. No region-wide shifts."""
import os, numpy as np, healpy as hp
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
MAXD=10
for dcur in range(1,MAXD+1):
    nb=neighT[frontier].ravel(); src=np.repeat(frontier,8)
    okn=nb>=0; nb=nb[okn];src=src[okn]
    ok2=(depth[nb]==127)&(lab[nb]==lab[src]); nb=nb[ok2];src=src[ok2]
    if len(nb)==0: break
    oo=np.argsort(nb,kind='stable'); nb=nb[oo];src=src[oo]
    fi=np.unique(nb,return_index=True)[1]; nb=nb[fi];src=src[fi]
    pairof[nb]=pairof[src]; depth[nb]=dcur; frontier=nb
# measurement band uses depth 1..6 (close), ramp uses full 0..MAXD
mband=(depth>=1)&(depth<=6)&(pairof>=0)
bp=np.where(mband)[0]; pid=pairof[bp]; sideA=(lab[bp]==pa[pid]); dep=depth[bp].astype(np.float64)
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
mm=pairof>=0
t=np.zeros(NPIX); t[mm]=1.0-depth[mm].astype(np.float64)/(MAXD+1)
wd=np.zeros(NPIX); wd[mm]=t[mm]*t[mm]*(3-2*t[mm])
signA=np.zeros(NPIX); signA[mm]=np.where(lab[mm]==pa[pairof[mm]],1.0,-1.0)
def membrane(vals):
    s,wgt=measure(vals)
    conf=np.clip(wgt/(wgt+6.0),0,1)
    s_eff=np.clip(s,-8,8)*conf
    c=np.zeros(NPIX)
    c[mm]=-signA[mm]*s_eff[pairof[mm]]/2.0*wd[mm]
    return c,s,wgt
out={}
for ch in ('R','G','B'):
    c1,s0,w0=membrane(cur[ch])
    v1=cur[ch]+c1
    c2,_,_=membrane(v1)
    v2=v1+c2
    s2,_=measure(v2)
    okw=w0>0.3
    print("%s: seam RMS %.3f -> %.3f | |c| p99 %.2f max %.2f"%(ch,
        np.sqrt(np.average(s0[okw]**2,weights=w0[okw])),
        np.sqrt(np.average(s2[okw]**2,weights=w0[okw])),
        np.percentile(np.abs(c1+c2),99),np.abs(c1+c2).max()),flush=True)
    out[ch]=(c1+c2).astype(np.float32)
np.savez(SC+"/delta_membrane.npz", dR=out['R'],dG=out['G'],dB=out['B'])
print("saved delta_membrane.npz")
