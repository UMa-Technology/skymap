"""Render every corrected tile's on-disk before(dss-clean)|after(dss-hybrid) into
labeled montages (6 tiles each) for verification review."""
import os, sys, json, numpy as np, cv2
from chroma_seam import stf
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))
ap = json.load(open(SC + "/hybrid_applied.json"))
tiles = sorted(int(k) for k in ap)
def path(base, p): return f"apps/skydata/surveys/{base}/Norder4/Dir{(p//10000)*10000}/Npix{p}.webp"
os.makedirs(SC + "/diag8/verify", exist_ok=True)
PER = 6
groups = [tiles[i:i+PER] for i in range(0, len(tiles), PER)]
manifest = []
for gi, grp in enumerate(groups):
    rows = []
    for p in grp:
        a = cv2.imread(path("dss-clean", p))[:, :, ::-1].astype(np.float32)
        b = cv2.imread(path("dss-hybrid", p))[:, :, ::-1].astype(np.float32)
        dm = float(np.abs(a - b).max())
        bl = stf(a[:, :, ::-1]); al = stf(b[:, :, ::-1])
        cv2.putText(bl, "t%d BEFORE" % p, (6, 24), 0, 0.7, (0, 255, 255), 2)
        cv2.putText(al, "t%d AFTER d%.0f" % (p, dm), (6, 24), 0, 0.7, (0, 255, 255), 2)
        rows.append(np.hstack([bl, np.full((512, 4, 3), 90, np.uint8), al]))
    sheet = np.vstack([np.pad(r, ((0, 6), (0, 0), (0, 0)), constant_values=90) for r in rows])
    fn = SC + "/diag8/verify/grp%02d.png" % gi
    cv2.imwrite(fn, sheet)
    manifest.append({"group": gi, "file": fn, "tiles": grp})
json.dump(manifest, open(SC + "/verify_manifest.json", "w"))
print("rendered %d groups covering %d tiles -> diag8/verify/grp*.png" % (len(groups), len(tiles)))
