"""Dark leveling v3: anisotropic subcells = per-region quartile bands ALONG GALACTIC LATITUDE
(variation axis per orientation analysis), |b|-banded caps."""
import os, numpy as np, healpy as hp
from scipy.sparse import csr_matrix, vstack, identity
from scipy.sparse.linalg import lsqr
SC=os.path.dirname(os.path.abspath(__file__))
NS=512; NPIX=hp.nside2npix(NS); ar=np.arange(NPIX)
z=np.load(SC+"/mapbase.npz"); d=np.load(SC+"/delta512.npz"); dL0=np.load(SC+"/dLum512.npy")
dreg=np.load(SC+"/delta_regions_final.npz"); dm=np.load(SC+"/delta_membrane.npz")
ddc=np.load(SC+"/dDarkDC.npy"); ddc2=np.load(SC+"/dDarkDC2.npy")
base=ddc+ddc2
R=z['mapR'].astype(np.float64)+d['dR']+dL0+dreg['dR']+dm['dR']+base
G=z['mapG'].astype(np.float64)+d['dG']+dL0+dreg['dG']+dm['dG']+base
B=z['mapB'].astype(np.float64)+d['dB']+dL0+dreg['dB']+dm['dB']+base
L=0.299*R+0.587*G+0.114*B
gb=z['gb'].astype(np.float64)
wr=np.load(SC+"/winner_red.npz",allow_pickle=True); wb=np.load(SC+"/winner_blue.npz",allow_pickle=True)
comb=wr['winner'].astype(np.int64)*(wb['winner'].max()+2)+(wb['winner'].astype(np.int64)+1)
u,lab0=np.unique(comb,return_inverse=True); NL0=len(u)
# per-region b quartile band index (0..3)
order0=np.argsort(lab0,kind='stable'); lo0=lab0[order0]; gbo=gb[order0]; pix_o=ar[order0]
starts0=np.unique(lo0,return_index=True)[1]
band=np.zeros(NPIX,np.int64)
for k,seg_pix,seg_gb in zip(np.unique(lo0),np.split(pix_o,starts0[1:]),np.split(gbo,starts0[1:])):
    if len(seg_pix)<8: continue
    qs=np.percentile(seg_gb,[25,50,75])
    band[seg_pix]=np.digitize(seg_gb,qs)
lab=lab0*4+band
us,lab=np.unique(lab,return_inverse=True); NL=len(us)
order=np.argsort(lab,kind='stable'); lo=lab[order]; Lo=L[order]; gbo2=np.abs(gb[order])
starts=np.unique(lo,return_index=True)[1]
darkmed=np.full(NL,1e9); tex=np.zeros(NL); size=np.zeros(NL); babs=np.zeros(NL)
for k,segL,segb in zip(np.unique(lo),np.split(Lo,starts[1:]),np.split(gbo2,starts[1:])):
    if len(segL)<12: continue
    darkmed[k]=np.median(segL[segL<=np.percentile(segL,40)])
    tex[k]=np.percentile(segL,75)-np.percentile(segL,25); size[k]=len(segL); babs[k]=np.median(segb)
eligible=(darkmed<16.0)&(tex<18.0)&(size>=12)
cap=np.where(babs<20,5.0,2.5)
print("subbands:",NL," eligible:",int(eligible.sum()))
neighT=hp.get_all_neighbours(NS,ar,nest=True).T
P=[];Q=[]
for k in range(8):
    q=neighT[:,k]; ok=(q>=0)&(q>ar)&(lab[np.clip(q,0,NPIX-1)]!=lab)
    P.append(ar[ok]);Q.append(q[ok])
P=np.concatenate(P);Q=np.concatenate(Q)
a=np.minimum(lab[P],lab[Q]);b=np.maximum(lab[P],lab[Q])
key=a*NL+b; uk=np.unique(key)
pa=(uk//NL).astype(np.int64);pb=(uk%NL).astype(np.int64)
okp=eligible[pa]&eligible[pb]; idx=np.where(okp)[0]
off=np.zeros(NL)
for it in range(2):
    dmed=darkmed+off
    s=dmed[pa[idx]]-dmed[pb[idx]]
    w=np.ones(len(idx))
    rows=np.repeat(np.arange(len(idx)),2); cols=np.concatenate([pa[idx][:,None],pb[idx][:,None]],1).ravel()
    val=np.empty(2*len(idx)); val[0::2]=w; val[1::2]=-w
    A=csr_matrix((val,(rows,cols)),shape=(len(idx),NL))
    lam=0.3
    Afull=vstack([A,identity(NL,format='csr')*lam])
    doff=lsqr(Afull,np.concatenate([-s,np.zeros(NL)]),iter_lim=8000)[0]
    doff[~eligible]=0.0
    off=np.clip(off+doff,-cap,cap)
    res=(off[pa[idx]]-off[pb[idx]])+(darkmed[pa[idx]]-darkmed[pb[idx]])
    print("iter%d: RMS %.3f -> %.3f"%(it,np.sqrt(np.mean((darkmed[pa[idx]]-darkmed[pb[idx]])**2)),np.sqrt(np.mean(res**2))))
c=off[lab]
cs=hp.reorder(hp.smoothing(hp.reorder(c,n2r=True),fwhm=np.radians(0.3)),r2n=True)
np.save(SC+"/dDarkDC3.npy",cs.astype(np.float32))
print("saved dDarkDC3  |c| p95=%.2f max=%.2f"%(np.percentile(np.abs(cs),95),np.abs(cs).max()))
