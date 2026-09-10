"""One-shot quantization repair: rebuild every colour N4 tile as
rint(clip(HEAD_tile + upsample(sum of ALL float correction fields))) — a single
rounding quantization instead of 5-6 accumulated floor-truncations (which sank
tiles ~2-3 DN and left ~0.5 DN steps along the tile grid where stages were
threshold-skipped). Then rebuild all N3 and regenerate the mono survey.

Usage: python repair_quantization.py [extra_field.npz]
  optional extra_field.npz with dR,dG,dB (nside-512 nested) is added to the chain
  (used later to fold in the SeamNet correction with the same single quantization).
"""
import numpy as np, cv2, os, subprocess, tempfile, sys, glob, time
sys.path.insert(0, "tools")
from clean_dss.background import upsample_smooth
from clean_dss.pyramid import child_ids, rebuild_parent

SC = os.environ["SCRATCH"]
W = 512
d = np.load(SC + "/delta512.npz")
dL0 = np.load(SC + "/dLum512.npy")
dreg = np.load(SC + "/delta_regions_final.npz")
dm = np.load(SC + "/delta_membrane.npz")
base = np.load(SC + "/dDarkDC.npy") + np.load(SC + "/dDarkDC2.npy")
FR = (d['dR'] + dL0 + dreg['dR'] + dm['dR'] + base).astype(np.float32)
FG = (d['dG'] + dL0 + dreg['dG'] + dm['dG'] + base).astype(np.float32)
FB = (d['dB'] + dL0 + dreg['dB'] + dm['dB'] + base).astype(np.float32)
if len(sys.argv) > 1:
    ex = np.load(sys.argv[1])
    FR = FR + ex['dR'].astype(np.float32)
    FG = FG + ex['dG'].astype(np.float32)
    FB = FB + ex['dB'].astype(np.float32)
    print("extra field folded in:", sys.argv[1], flush=True)

def p1(n):
    n = n & 0xffff; n = (n | (n << 8)) & 0x00FF00FF; n = (n | (n << 4)) & 0x0F0F0F0F
    n = (n | (n << 2)) & 0x33333333; n = (n | (n << 1)) & 0x55555555; return n
cy, cx = np.meshgrid(np.arange(32), np.arange(32), indexing='ij')
cellsub = (p1(cy) | (p1(cx) << 1)).ravel()

SRC = "apps/skydata/surveys/dss"; DSTM = "apps/skydata/surveys/dss-mono"

def save_lossless(bgr, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        cv2.imwrite(tf.name, bgr); s = tf.name
    try:
        r = subprocess.run(["cwebp", "-quiet", "-lossless", "-m", "6", "-o", dst, s],
                           capture_output=True)
        if r.returncode != 0: raise RuntimeError(r.stderr.decode()[:200])
    finally:
        os.unlink(s)

def n4path(npix): return os.path.join(SRC, "Norder4", f"Dir{(npix//10000)*10000}", f"Npix{npix}.webp")
def n3path(npix): return os.path.join(SRC, "Norder3", f"Dir{(npix//10000)*10000}", f"Npix{npix}.webp")

t0 = time.time(); n = 0
for npix in range(3072):
    rel = n4path(npix)
    r = subprocess.run(["git", "show", "HEAD:" + rel], capture_output=True)
    if r.returncode != 0:
        print("NO HEAD TILE", npix, flush=True); continue
    head = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR).astype(np.float32)
    base_i = npix * 1024
    up = np.stack([upsample_smooth(F[base_i + cellsub].reshape(32, 32), W)
                   for F in (FB, FG, FR)], 2)
    save_lossless(np.rint(np.clip(head + up, 0, 255)).astype(np.uint8), rel)
    n += 1
    if n % 300 == 0: print("N4", n, int(time.time() - t0), "s", flush=True)
print("PASS1 colour N4 rebuilt:", n, flush=True)

for parent in range(768):
    ch = [cv2.imread(n4path(k)) for k in child_ids(parent)]
    if any(x is None for x in ch): print("MISS child of", parent, flush=True); continue
    save_lossless(rebuild_parent(ch), n3path(parent))
print("PASS2 colour N3 rebuilt: 768", flush=True)

nm = 0
for f in sorted(glob.glob(os.path.join(SRC, "Norder4", "Dir*", "Npix*.webp"))):
    img = cv2.imread(f)
    if img is None: continue
    L = (0.114 * img[:, :, 0] + 0.587 * img[:, :, 1] + 0.299 * img[:, :, 2]).astype(np.float32)
    mono = np.repeat(np.rint(np.clip(L, 0, 255)).astype(np.uint8)[:, :, None], 3, axis=2)
    save_lossless(mono, f.replace(SRC, DSTM)); nm += 1
    if nm % 600 == 0: print("monoN4", nm, flush=True)

def m4path(npix): return os.path.join(DSTM, "Norder4", f"Dir{(npix//10000)*10000}", f"Npix{npix}.webp")
for f in sorted(glob.glob(os.path.join(SRC, "Norder3", "Dir*", "Npix*.webp"))):
    parent = int(os.path.basename(f)[4:-5])
    ch = [cv2.imread(m4path(k)) for k in child_ids(parent)]
    if any(x is None for x in ch): continue
    save_lossless(rebuild_parent(ch), f.replace(SRC, DSTM))
print("DONE %ds colourN4=%d monoN4=%d" % (time.time() - t0, n, nm), flush=True)
