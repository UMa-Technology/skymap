"""Full-survey apply: correct 3072 N4 tiles dss-clean -> dss-hybrid (only changed
tiles written; the layer was CoW-cloned so unchanged tiles already present),
then rebuild the affected N3 parents. Lossless webp during evaluation.

Contract check: reports max correction and per-tile counts; protect_mask guards
the colour transfer (bit-exact 0 inside protection); luminance leveling is
ungated but self-limited by the flat/length/magnitude/per-tile gates.
"""
import os, sys, json, numpy as np, cv2
from multiprocessing import Pool
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))
SRC = "apps/skydata/surveys/dss-clean"
DST = "apps/skydata/surveys/dss-hybrid"

def n4(base, p): return f"{base}/Norder4/Dir{(p//10000)*10000}/Npix{p}.webp"
def n3(base, p): return f"{base}/Norder3/Dir{(p//10000)*10000}/Npix{p}.webp"

def _one(npix):
    import assemble
    from hybrid_seam import correct_tile
    try:
        corr, edges = correct_tile(4, npix, SRC, use_protect=True)
    except Exception as e:
        return (npix, "err", repr(e)[:120])
    if corr is None:
        return (npix, "skip", (0, 0, 0.0))
    src = cv2.imread(n4(SRC, npix))[:, :, ::-1].astype(np.float32)
    dmax = float(np.abs(corr - src).max())
    bgr = np.clip(np.round(corr), 0, 255).astype(np.uint8)[:, :, ::-1]
    cv2.imwrite(n4(DST, npix), bgr, [cv2.IMWRITE_WEBP_QUALITY, 101])
    nL = sum(e['do_L'] for e in edges); nC = sum(e['do_RB'] for e in edges)
    return (npix, "wrote", (int(nL), int(nC), dmax))

if __name__ == "__main__":
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 3072
    with Pool(10) as pool:
        res = pool.map(_one, range(N))
    wrote = [r for r in res if r[1] == "wrote"]
    errs = [r for r in res if r[1] == "err"]
    changed = [r[0] for r in wrote]
    dmaxes = [r[2][2] for r in wrote]
    print("=== N4 apply ===")
    print("wrote %d | skip %d | err %d" % (len(wrote), sum(r[1] == "skip" for r in res), len(errs)))
    if dmaxes:
        print("per-tile dmax: p50 %.1f p95 %.1f max %.1f DN"
              % (np.percentile(dmaxes, 50), np.percentile(dmaxes, 95), max(dmaxes)))
    for e in errs[:10]:
        print("  ERR", e)
    json.dump({r[0]: r[2] for r in wrote}, open(SC + "/hybrid_applied.json", "w"))

    # ---- rebuild only the N3 parents whose children changed ----
    sys.path.insert(0, os.path.join(os.getcwd(), "tools"))
    from clean_dss.pyramid import child_ids, rebuild_parent
    parents = sorted({p // 4 for p in changed})
    nrb = 0
    for parent in parents:
        ch = [cv2.imread(n4(DST, k)) for k in child_ids(parent)]
        if any(c is None for c in ch):
            print("N3 skip", parent); continue
        os.makedirs(os.path.dirname(n3(DST, parent)), exist_ok=True)
        cv2.imwrite(n3(DST, parent), rebuild_parent(ch), [cv2.IMWRITE_WEBP_QUALITY, 101]); nrb += 1
    print("=== N3 rebuild: %d parents ===" % nrb)
    print("DONE")
