"""Confirm protect_mask suppresses seam corrections inside protected DSO regions,
and render before | after(protect-on) for the colour-firing tiles."""
import os, sys, numpy as np, cv2
import apron as apron_mod, assemble
from chroma_seam import stf
from hybrid_seam import detect, apply, correct_tile
from protect_mask import protect_mask
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))
assemble.RAW = "apps/skydata/surveys/dss-clean"
WL, WG, WB = 0.299, 0.587, 0.114
lum = lambda a: WL*a[:,:,0]+WG*a[:,:,1]+WB*a[:,:,2]

npixs = [int(x) for x in sys.argv[1:]] or [169, 2068, 1890, 2688]
rows = []
for npix in npixs:
    sub, _ = apron_mod.assemble_apron(4, npix, 64); a = 64
    rgb = sub[:, :, :3].astype(np.float32)
    tile = rgb[a:a+512, a:a+512]
    pm, info = protect_mask(tile, sub[:, :, :3])
    corr_np, _ = correct_tile(4, npix, "apps/skydata/surveys/dss-clean", use_protect=False)  # no protect
    corr_p,  _ = correct_tile(4, npix, "apps/skydata/surveys/dss-clean", use_protect=True)    # protect
    if corr_p is None:
        print("t%d: no correction" % npix); continue
    dP = np.abs(corr_p - tile).max(axis=2)         # per-pixel max channel delta, protect-on
    dNP = np.abs(corr_np - tile).max(axis=2)
    print("t%d: protect %.1f%% | max|d| in-protect: unguarded %.1f -> guarded %.2f DN | max|d| outside %.1f DN"
          % (npix, 100*info['coverage'],
             dNP[pm].max() if pm.any() else 0, dP[pm].max() if pm.any() else 0, dP[~pm].max()))
    b = stf(tile[:, :, ::-1]); af = stf(corr_p[:, :, ::-1])
    # outline protected region on the after panel
    bnd = (pm ^ cv2.erode(pm.astype(np.uint8), np.ones((3,3),np.uint8)).astype(bool))
    af[cv2.dilate(bnd.astype(np.uint8), np.ones((3,3),np.uint8)).astype(bool)] = (0,255,0)
    cv2.putText(b, "t%d before" % npix, (6,22), 0, 0.7, (0,255,255), 2)
    cv2.putText(af, "after (protect green)", (6,22), 0, 0.7, (0,255,255), 2)
    rows.append(np.hstack([b, np.full((512,4,3),80,np.uint8), af]))
if rows:
    sheet = np.vstack([np.pad(r, ((0,6),(0,0),(0,0)), constant_values=80) for r in rows])
    cv2.imwrite(SC + "/diag8/protect_validate.png", sheet)
    print("wrote diag8/protect_validate.png")
