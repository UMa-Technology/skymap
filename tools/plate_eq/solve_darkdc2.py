"""Dark-region leveling v2: regions split into 2x2 tangent quadrants (piecewise-constant ~ plane),
graph solve on dark-pixel medians, 2 iterations."""
import os, numpy as np, healpy as hp
from scipy.sparse import csr_matrix, vstack, identity
from scipy.sparse.linalg import lsqr
SC=os.path.dirname(os.path.abspath(__file__))
NS=512; NPIX=hp.nside2npix(NS); ar=np.arange(NPIX)
z=np.load(SC+"/mapbase.npz"); d=np.load(SC+"/delta512.npz"); dL0=np.load(SC+"/dLum512.npy")
dreg=np.load(SC+"/delta_regions_final.npz"); dm=np.load(SC+"/delta_membrane.npz"); ddc=np.load(SC+"/dDarkDC.npy")
R=z['mapR'].astype(np.float64)+d['dR']+dL0+dreg['dR']+dm['dR']+ddc
G=z['mapG'].astype(np.float64)+d['dG']+dL0+dreg['dG']+dm['dG']+ddc
B=z['mapB'].astype(np.float64)+d['dB']+dL0+dreg['dB']+dm['dB']+ddc
L=0.299*R+0.587*G+0.114*B
wr=np.load(SC+"/winner_red.npz",allow_pickle=True); wb=np.load(SC+"/winner_blue.npz",allow_pickle=True)
comb=wr['winner'].astype(np.int64)*(wb['winner'].max()+2)+(wb['winner'].astype(np.int64)+1)
u,lab0=np.unique(comb,return_inverse=True); NL0=len(u)
# region centroids -> tangent quadrant sublabels
vec=np.array(hp.pix2vec(NS,ar,nest=True)).T
cent=np.zeros((NL0,3))
np.add.at(cent,lab0,vec)
cent/=np.linalg.norm(cent,axis=1,keepdims=True).clip(1e-9)
cv=cent[lab0]
east=np.cross([0,0,1.0],cent); east/=np.linalg.norm(east,axis=1,keepdims=True).clip(1e-9)
north=np.cross(cent,east)
uu=np.einsum('ij,ij->i',vec,east[lab0]); vv=np.einsum('ij,ij->i',vec,north[lab0])
quad=(uu>0).astype(np.int64)+2*(vv>0).astype(np.int64)
lab=lab0*4+quad
us,lab=np.unique(lab,return_inverse=True); NL=len(us)
print("sublabels:",NL)
order=np.argsort(lab,kind='stable'); lo=lab[order]; Lo=L[order]
starts=np.unique(lo,return_index=True)[1]
darkmed=np.full(NL,1e9); tex=np.zeros(NL); size=np.zeros(NL)
for k,seg in zip(np.unique(lo),np.split(Lo,starts[1:])):
    if len(seg)<16: continue
    dk=seg[seg<=np.percentile(seg,40)]
    darkmed[k]=np.median(dk); tex[k]=np.percentile(seg,75)-np.percentile(seg,25); size[k]=len(seg)
eligible=(darkmed<16.0)&(tex<18.0)&(size>=16)
print("eligible subcells: %d/%d"%(eligible.sum(),NL))
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
    off=np.clip(off+doff,-5,5)
    res=(off[pa[idx]]-off[pb[idx]])+(darkmed[pa[idx]]-darkmed[pb[idx]])
    print("iter%d: dark-pair RMS %.3f -> resid %.3f"%(it,np.sqrt(np.mean(((darkmed[pa[idx]]-darkmed[pb[idx]]))**2)),np.sqrt(np.mean(res**2))))
c=off[lab]
cs=hp.reorder(hp.smoothing(hp.reorder(c,n2r=True),fwhm=np.radians(0.3)),r2n=True)
np.save(SC+"/dDarkDC2.npy",cs.astype(np.float32))
print("saved dDarkDC2.npy  |c| p95=%.2f max=%.2f"%(np.percentile(np.abs(cs),95),np.abs(cs).max()))
