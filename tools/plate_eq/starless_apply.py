"""Full-survey starless generation: 3072 N4 -> dss-starless (+ N3 pyramid + properties).

Usage: python starless_apply.py <ckpt> [--resume]
Writes lossless webp. Strict-protection violations are asserted per tile.
"""
import os, sys, time, shutil
import numpy as np, cv2
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SC)
sys.path.insert(0, "tools")
import starless_tile as st
from clean_dss.pyramid import child_ids, rebuild_parent

SRC = "apps/skydata/surveys/dss"
DST = "apps/skydata/surveys/dss-starless"

def dst4(npix): return os.path.join(DST, "Norder4", f"Dir{(npix//10000)*10000}", f"Npix{npix}.webp")
def dst3(npix): return os.path.join(DST, "Norder3", f"Dir{(npix//10000)*10000}", f"Npix{npix}.webp")

ckpt = sys.argv[1]
RESUME = "--resume" in sys.argv
st.load_model(ckpt)

t0 = time.time(); n = 0; viol = 0
for npix in range(3072):
    p = dst4(npix)
    if RESUME and os.path.exists(p):
        continue
    raw, comp, resid, sm, pm, holes = st.starless(npix)
    d = np.abs(comp - raw).max(axis=2)
    strict = pm & ~holes
    if strict.any() and d[strict].max() > 0.01:
        viol += 1
        print("VIOLATION npix %d max %.2f" % (npix, d[strict].max()), flush=True)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    ok = cv2.imwrite(p, np.rint(comp[:, :, ::-1]).astype(np.uint8),
                     [cv2.IMWRITE_WEBP_QUALITY, 101])
    if not ok:
        print("WRITE FAIL", npix, flush=True); break
    n += 1
    if n % 100 == 0:
        el = time.time() - t0
        print("N4 %d done (%.0fs, %.2fs/tile, ETA %.0f min)" %
              (n, el, el / n, (3072 - npix - 1) * el / n / 60), flush=True)

print("PASS1 starless N4:", n, "violations:", viol, flush=True)
n3 = 0
for parent in range(768):
    ch = [cv2.imread(dst4(k)) for k in child_ids(parent)]
    if any(x is None for x in ch):
        print("N3 skip", parent, flush=True); continue
    os.makedirs(os.path.dirname(dst3(parent)), exist_ok=True)
    cv2.imwrite(dst3(parent), rebuild_parent(ch), [cv2.IMWRITE_WEBP_QUALITY, 101])
    n3 += 1
for f in ("properties",):
    src = os.path.join(SRC, f)
    if os.path.exists(src):
        shutil.copy(src, os.path.join(DST, f))
print("DONE %ds N4=%d N3=%d violations=%d" % (time.time() - t0, n, n3, viol), flush=True)
