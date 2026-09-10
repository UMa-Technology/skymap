"""Production-config render: before | after(protect-on) for a spread."""
import os, sys, numpy as np, cv2
import assemble
from chroma_seam import stf
from hybrid_seam import detect, correct_tile, _raw_rgb
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))
assemble.RAW = "apps/skydata/surveys/dss-clean"
npixs = [int(x) for x in sys.argv[1:]] or [2635]
rows = []
for npix in npixs:
    raw = _raw_rgb("apps/skydata/surveys/dss-clean", npix)     # honest before = the tile itself
    corr, edges = correct_tile(4, npix, "apps/skydata/surveys/dss-clean", use_protect=True)
    nL = sum(e['do_L'] for e in edges); nC = sum(e['do_RB'] for e in edges)
    before = stf(raw[:, :, ::-1])
    after = before.copy() if corr is None else stf(corr[:, :, ::-1])
    d = 0.0 if corr is None else float(np.abs(corr - raw).max())
    cv2.putText(before, "t%d" % npix, (6, 22), 0, 0.7, (0, 255, 255), 2)
    cv2.putText(after, "L%d C%d dmax%.0f" % (nL, nC, d), (6, 22), 0, 0.7, (0, 255, 255), 2)
    rows.append(np.hstack([before, np.full((512, 4, 3), 80, np.uint8), after]))
    print("t%d L=%d C=%d dmax=%.1f" % (npix, nL, nC, d))
sheet = rows[0] if len(rows) == 1 else np.vstack([np.pad(r, ((0,6),(0,0),(0,0)), constant_values=80) for r in rows])
cv2.imwrite(SC + "/diag8/render_hybrid.png", sheet)
print("wrote diag8/render_hybrid.png")
