import numpy as np, healpy as hp, os
from PIL import Image
TW=512
ROOT=os.path.abspath(os.path.join(os.path.dirname(__file__),"..",".."))
RAW=os.path.join(ROOT,"apps","skydata","surveys","dss")
CAST=os.path.join(ROOT,"dss-cast-cleaned")

def tile_path(order,pix):
    c=f"{CAST}/Norder{order}/Dir0/Npix{pix}.webp"
    return c if os.path.exists(c) else f"{RAW}/Norder{order}/Dir0/Npix{pix}.webp"
def load(order,pix,gray=False):
    im=Image.open(tile_path(order,pix)).convert("L" if gray else "RGB")
    return np.asarray(im).astype(np.float32)
def nest2xyf(nside,pix):
    ix,iy,f=hp.pix2xyf(nside,pix,nest=True); return int(ix),int(iy),int(f)
def pix_vec(order,pix,r,c):
    nside=1<<order; ndeep=nside*TW; ix,iy,f=nest2xyf(nside,pix)
    return np.array(hp.pix2vec(ndeep,hp.xyf2pix(ndeep,ix*TW+r,iy*TW+c,f,nest=True),nest=True))
def ang(a,b): return np.degrees(np.arccos(np.clip(np.dot(a,b),-1,1)))
def orient(img,k):  # dihedral group
    return np.rot90(img,k) if k<4 else np.rot90(np.fliplr(img),k-4)

DIRNAMES=["SW","W","NW","N","NE","E","SE","S"]
# edge (diagonal-healpy) dir -> image block position (row,col) in 3x3, and the block's touching border
DIR2BLOCK={'SW':(0,1,'T'),'NE':(2,1,'B'),'NW':(1,2,'R'),'SE':(1,0,'L')}

def best_dihedral(order,cpix,npx,cside):
    """dihedral k for neighbour so its (opposite) border matches center's cside border."""
    samp=np.linspace(4,TW-5,9).astype(int)
    if cside=='T': cB=[(0,c) for c in samp];      nB=[(TW-1,c) for c in samp]
    elif cside=='B': cB=[(TW-1,c) for c in samp]; nB=[(0,c) for c in samp]
    elif cside=='R': cB=[(c,TW-1) for c in samp]; nB=[(c,0) for c in samp]
    elif cside=='L': cB=[(c,0) for c in samp];    nB=[(c,TW-1) for c in samp]
    cv=[pix_vec(order,cpix,r,c) for r,c in cB]
    ridx=np.repeat(np.arange(TW)[:,None],TW,1); cidx=np.repeat(np.arange(TW)[None,:],TW,0)
    bk,bd=0,1e9
    for k in range(8):
        ro,co=orient(ridx,k),orient(cidx,k)
        nv=[pix_vec(order,npx,int(ro[r,c]),int(co[r,c])) for r,c in nB]
        d=np.mean([ang(a,b) for a,b in zip(cv,nv)])
        if d<bd: bd,bk=d,k
    return bk,bd

def assemble_neighbourhood(order,cpix,gray=False):
    """Return (canvas, center_slice) : 3x3 tile canvas with center at block(1,1).
    Edge neighbours always present; corner neighbours filled when available."""
    nside=1<<order
    ch = 1 if gray else 3
    canvas=np.zeros((3*TW,3*TW)+(() if gray else (3,)),np.float32)
    nb=hp.get_all_neighbours(nside,cpix,nest=True)
    canvas[TW:2*TW,TW:2*TW]=load(order,cpix,gray)  # center
    placed={}
    for di,dn in enumerate(DIRNAMES):
        npx=int(nb[di])
        if npx<0: continue
        if dn in DIR2BLOCK:
            br,bc,cside=DIR2BLOCK[dn]
            k,d=best_dihedral(order,cpix,npx,cside)
            img=orient(load(order,npx,gray),k)
            canvas[br*TW:(br+1)*TW, bc*TW:(bc+1)*TW]=img
            placed[dn]=(npx,k,round(d,4))
    center_slice=(slice(TW,2*TW),slice(TW,2*TW))
    return canvas,center_slice,placed

# ---- END-TO-END SEAM TEST on assembled canvas ----
def canvas_seams(order,cpix):
    cv,_,placed=assemble_neighbourhood(order,cpix,gray=True)
    # internal seams between center block and its 4 edge blocks
    top=np.mean(np.abs(cv[TW-1,TW:2*TW]-cv[TW,TW:2*TW]))       # top block/center
    bot=np.mean(np.abs(cv[2*TW-1,TW:2*TW]-cv[2*TW,TW:2*TW]))   # center/bottom block
    left=np.mean(np.abs(cv[TW:2*TW,TW-1]-cv[TW:2*TW,TW]))
    right=np.mean(np.abs(cv[TW:2*TW,2*TW-1]-cv[TW:2*TW,2*TW]))
    return top,bot,left,right,placed

if __name__ == "__main__":
    tests={
     'equatorial-interior(face4)':305,
     'equatorial-edge(face4/face0 bound)':309,
     'north-polar interior(face0)':21,
     'north-polar corner(face0 ix0iy0)':0,
     'south-polar(face11)':767,
    }
    for label,cpix in tests.items():
        t,b,l,r,placed=canvas_seams(3,cpix)
        ks=[f"{d}:k{v[1]}" for d,v in placed.items()]
        print(f"{label:36s} pix{cpix}: seams T{t:.2f} B{b:.2f} L{l:.2f} R{r:.2f} | transforms {ks}")
