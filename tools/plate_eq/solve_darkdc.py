"""Interior-dark per-region DC solve for in-band dark zones (Musca-type plateaus)."""
import os, numpy as np, healpy as hp
from scipy.sparse import csr_matrix, vstack, identity
from scipy.sparse.linalg import lsqr
SC=os.path.dirname(os.path.abspath(__file__))
NS=512; NPIX=hp.nside2npix(NS); ar=np.arange(NPIX)
z=np.load(SC+"/mapbase.npz"); d=np.load(SC+"/delta512.npz"); dL0=np.load(SC+"/dLum512.npy")
dreg=np.load(SC+"/delta_regions_final.npz"); dm=np.load(SC+"/delta_membrane.npz")
R=z['mapR'].astype(np.float64)+d['dR']+dL0+dreg['dR']+dm['dR']
G=z['mapG'].astype(np.float64)+d['dG']+dL0+dreg['dG']+dm['dG']
B=z['mapB'].astype(np.float64)+d['dB']+dL0+dreg['dB']+dm['dB']
L=0.299*R+0.587*G+0.114*B
wr=np.load(SC+"/winner_red.npz",allow_pickle=True); wb=np.load(SC+"/winner_blue.npz",allow_pickle=True)
comb=wr['winner'].astype(np.int64)*(wb['winner'].max()+2)+(wb['winner'].astype(np.int64)+1)
u,lab=np.unique(comb,return_inverse=True); NL=len(u)
# per-region stats over DARK pixels (lowest 40% within region)
order=np.argsort(lab,kind='stable'); lo=lab[order]; Lo=L[order]
starts=np.unique(lo,return_index=True)[1]
darkmed=np.zeros(NL); q80=np.zeros(NL); tex=np.zeros(NL); size=np.zeros(NL)
for k,seg in zip(np.unique(lo),np.split(Lo,starts[1:])):
    if len(seg)<30: darkmed[k]=1e9; continue
    d40=np.percentile(seg,40)
    dk=seg[seg<=d40]
    darkmed[k]=np.median(dk); q80[k]=np.percentile(seg,80)
    tex[k]=np.percentile(seg,75)-np.percentile(seg,25); size[k]=len(seg)
eligible=(darkmed<16.0)&(tex<18.0)&(size>=30)
print("eligible regions: %d/%d"%(eligible.sum(),NL))
# adjacency
neighT=hp.get_all_neighbours(NS,ar,nest=True).T
P=[];Q=[]
for k in range(8):
    q=neighT[:,k]; ok=(q>=0)&(q>ar)&(lab[np.clip(q,0,NPIX-1)]!=lab)
    P.append(ar[ok]);Q.append(q[ok])
P=np.concatenate(P);Q=np.concatenate(Q)
a=np.minimum(lab[P],lab[Q]);b=np.maximum(lab[P],lab[Q])
key=a*NL+b; uk=np.unique(key)
pa=(uk//NL).astype(np.int64);pb=(uk%NL).astype(np.int64)
# observations: darkmed difference for eligible-eligible pairs
okp=eligible[pa]&eligible[pb]
s=darkmed[pa]-darkmed[pb]
idx=np.where(okp)[0]
w=np.ones(len(idx))
rows=np.repeat(np.arange(len(idx)),2); cols=np.concatenate([pa[idx][:,None],pb[idx][:,None]],1).ravel()
val=np.empty(2*len(idx)); val[0::2]=w; val[1::2]=-w
A=csr_matrix((val,(rows,cols)),shape=(len(idx),NL))
lam=0.3
Afull=vstack([A,identity(NL,format='csr')*lam])
off=lsqr(Afull,np.concatenate([-s[idx],np.zeros(NL)]),iter_lim=8000)[0]
off[~eligible]=0.0
off=np.clip(off,-4,4)
# residual check
res=(off[pa[idx]]-off[pb[idx]])+s[idx]
print("dark-pair step RMS %.3f -> %.3f | off p50/p95/max %.2f/%.2f/%.2f"%(
    np.sqrt(np.mean(s[idx]**2)),np.sqrt(np.mean(res**2)),
    np.percentile(np.abs(off[eligible]),50),np.percentile(np.abs(off[eligible]),95),np.abs(off).max()))
c=off[lab]
cs=hp.reorder(hp.smoothing(hp.reorder(c,n2r=True),fwhm=np.radians(0.35)),r2n=True)
np.save(SC+"/dDarkDC.npy",cs.astype(np.float32))
print("saved dDarkDC.npy")
