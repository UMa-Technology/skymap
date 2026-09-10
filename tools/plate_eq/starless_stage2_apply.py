"""Full-sky Stage 2: starless -> seam-DC-level (true boundary) -> fog-flatten -> dss-clean.

Pass 1 (parallel): read dss-starless, seam_correction(res=256), write dss-seam.
Pass 2 (parallel): fog flatten (medium) reading dss-seam aprons, write dss-clean N4.
Pass 3: rebuild dss-clean N3 pyramid + copy properties. Cleanup dss-seam optional.
Usage: python starless_stage2_apply.py [pass1|pass2|pass3|all]
"""
import os, sys, time, shutil
import numpy as np, cv2
import multiprocessing as mp
SC = os.environ["SCRATCH"]

STARLESS = "apps/skydata/surveys/dss-starless"
SEAM = "apps/skydata/surveys/dss-seam"
CLEAN = "apps/skydata/surveys/dss-clean"
RES = 256
PRESET = "medium"
NPROC = max(1, min(10, mp.cpu_count() - 2))

def n4(base, p): return os.path.join(base, "Norder4", f"Dir{(p//10000)*10000}", f"Npix{p}.webp")
def n3(base, p): return os.path.join(base, "Norder3", f"Dir{(p//10000)*10000}", f"Npix{p}.webp")

# ---------- Pass 1 worker ----------
def _seam_worker(npix):
    import seam_fix as sf
    src = n4(STARLESS, npix)
    im = cv2.imread(src)
    if im is None:
        return (npix, None)
    rgb = im[:, :, ::-1].astype(np.float32)
    aR, aG, aB, _ = sf.seam_correction(npix, rgb, res=RES)
    out = np.clip(rgb + np.stack([aR, aG, aB], 2), 0, 255)
    dst = n4(SEAM, npix); os.makedirs(os.path.dirname(dst), exist_ok=True)
    cv2.imwrite(dst, np.rint(out[:, :, ::-1]).astype(np.uint8), [cv2.IMWRITE_WEBP_QUALITY, 101])
    d = np.abs(out - rgb).max()
    return (npix, float(d))

# ---------- Pass 2 worker ----------
def _flat_init():
    import assemble
    assemble.RAW = os.path.abspath(SEAM)
    assemble.CAST = "/nonexistent"

def _flat_worker(npix):
    import stage2_flatten as s2
    import assemble
    assemble.RAW = os.path.abspath(SEAM); assemble.CAST = "/nonexistent"
    try:
        raw, comp, gate, pm, _ = s2.flatten(npix, preset=PRESET)
    except Exception as e:
        return (npix, "ERR:" + str(e)[:80])
    dst = n4(CLEAN, npix); os.makedirs(os.path.dirname(dst), exist_ok=True)
    cv2.imwrite(dst, np.rint(comp[:, :, ::-1]).astype(np.uint8), [cv2.IMWRITE_WEBP_QUALITY, 101])
    dmax = float(np.abs(comp - raw)[pm].max()) if pm.any() else 0.0
    return (npix, dmax)

def run_pass(tag, worker, init=None):
    t0 = time.time(); done = 0; maxv = 0.0; viol = 0
    with mp.Pool(NPROC, initializer=init) as pool:
        for npix, v in pool.imap_unordered(worker, range(3072), chunksize=8):
            done += 1
            if isinstance(v, str) and v.startswith("ERR"):
                print("ERR", npix, v, flush=True)
            elif v is not None:
                maxv = max(maxv, v)
                if tag == "pass2" and v > 0.01:
                    viol += 1
            if done % 300 == 0:
                el = time.time() - t0
                print("%s %d/3072 (%.0fs, %.2fs/tile, ETA %.0fmin) maxΔ %.1f"
                      % (tag, done, el, el / done, (3072 - done) * el / done / 60, maxv), flush=True)
    print("%s DONE %ds maxΔ %.1f protect-viol %d" % (tag, time.time() - t0, maxv, viol), flush=True)

def pass3():
    sys.path.insert(0, "tools")
    from clean_dss.pyramid import child_ids, rebuild_parent
    t0 = time.time(); n = 0
    for parent in range(768):
        ch = [cv2.imread(n4(CLEAN, k)) for k in child_ids(parent)]
        if any(x is None for x in ch):
            print("N3 skip", parent, flush=True); continue
        dst = n3(CLEAN, parent); os.makedirs(os.path.dirname(dst), exist_ok=True)
        cv2.imwrite(dst, rebuild_parent(ch), [cv2.IMWRITE_WEBP_QUALITY, 101]); n += 1
    for f in ("properties",):
        s = os.path.join(STARLESS, f)
        if os.path.exists(s): shutil.copy(s, os.path.join(CLEAN, f))
    print("PASS3 N3 %d (%ds)" % (n, time.time() - t0), flush=True)

if __name__ == "__main__":
    sys.path.insert(0, SC)
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("pass1", "all"):
        run_pass("pass1", _seam_worker)
    if mode in ("pass2", "all"):
        run_pass("pass2", _flat_worker, init=_flat_init)
    if mode in ("pass3", "all"):
        pass3()
    print("STAGE2 COMPLETE", flush=True)
