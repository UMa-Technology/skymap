"""before | v2 (per-channel DC, removes luminance+color step) | v3 (L-conserving
color-only transfer).  Shows the philosophical tradeoff on one tile."""
import os, sys, numpy as np, cv2
from chroma_seam import stf
import chroma_seam2 as v2
import chroma_seam3 as v3
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))
npix = int(sys.argv[1]) if len(sys.argv) > 1 else 2635
im = cv2.imread(f"apps/skydata/surveys/dss-clean/Norder4/Dir0/Npix{npix}.webp")
rgb = im[:, :, ::-1].astype(np.float32)

e2 = v2.detect(rgb); c2 = v2.apply(rgb, e2, band=8.0)
e3 = v3.detect(rgb); c3 = v3.apply(rgb, e3, sel='all')

WL, WG, WB = 0.299, 0.587, 0.114
lum = lambda a: WL*a[:,:,0]+WG*a[:,:,1]+WB*a[:,:,2]
print("v2 max|dL|=%.1f DN (levels luminance)  v3 max|dL|=%.2f DN (holds luminance)"
      % (np.abs(lum(c2)-lum(rgb)).max(), np.abs(lum(c3)-lum(rgb)).max()))

before = stf(rgb[:,:,::-1]); a2 = stf(c2[:,:,::-1]); a3 = stf(c3[:,:,::-1])
cv2.putText(before,"before",(6,22),0,0.7,(0,255,255),2)
cv2.putText(a2,"v2: level L+color DC",(6,22),0,0.7,(0,255,255),2)
cv2.putText(a3,"v3: L-conserving color",(6,22),0,0.7,(0,255,255),2)
sep = np.full((512,5,3),80,np.uint8)
cv2.imwrite(SC+f"/diag8/v2v3_{npix}.png", np.hstack([before,sep,a2,sep,a3]))
print("wrote diag8/v2v3_%d.png" % npix)
