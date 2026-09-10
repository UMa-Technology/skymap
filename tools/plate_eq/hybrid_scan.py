"""Survey-wide census of what the hybrid corrector will touch (apron-accurate,
no protect / no write).  Emits per-tile (nL, nC, max|cL|, max|cRB|) + examples."""
import os, sys, json, numpy as np
from multiprocessing import Pool
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))
SRC = "apps/skydata/surveys/dss-clean"

def _one(npix):
    import apron as apron_mod, assemble
    from hybrid_seam import detect
    assemble.RAW = SRC
    try:
        sub, _ = apron_mod.assemble_apron(4, npix, 64)
    except Exception:
        return None
    edges = detect(sub[:, :, :3].astype(np.float32))
    nL = sum(e['do_L'] for e in edges); nC = sum(e['do_RB'] for e in edges)
    if nL == 0 and nC == 0:
        return (npix, 0, 0, 0.0, 0.0)
    mcL = max([abs(e['cL']) for e in edges if e['do_L']], default=0.0)
    mcC = max([abs(e['cRB']) for e in edges if e['do_RB']], default=0.0)
    return (npix, int(nL), int(nC), float(mcL), float(mcC))

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3072
    with Pool(10) as p:
        res = [r for r in p.map(_one, range(n)) if r is not None]
    arr = np.array([[r[1], r[2], r[3], r[4]] for r in res], float)
    np1 = np.array([r[0] for r in res])
    nL, nC, mcL, mcC = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]
    touched = (nL > 0) | (nC > 0)
    print("=== hybrid census over %d tiles ===" % len(res))
    print("touched: %d (%.1f%%) | luminance-level: %d tiles | colour-transfer: %d tiles"
          % (touched.sum(), 100*touched.mean(), (nL > 0).sum(), (nC > 0).sum()))
    print("only-L: %d | only-C: %d | both: %d"
          % (((nL > 0) & (nC == 0)).sum(), ((nC > 0) & (nL == 0)).sum(), ((nL > 0) & (nC > 0)).sum()))
    print("max |cL| p50/p95/max = %.1f/%.1f/%.1f | max |cRB| p50/p95/max = %.1f/%.1f/%.1f"
          % (np.percentile(mcL[nL > 0], 50) if (nL > 0).any() else 0,
             np.percentile(mcL[nL > 0], 95) if (nL > 0).any() else 0, mcL.max(),
             np.percentile(mcC[nC > 0], 50) if (nC > 0).any() else 0,
             np.percentile(mcC[nC > 0], 95) if (nC > 0).any() else 0, mcC.max()))
    # pure colour-cast examples (C only, strong) and big-L examples
    onlyC = np1[(nC > 0) & (nL == 0)]; onlyC_m = mcC[(nC > 0) & (nL == 0)]
    bigL = np1[nL > 0][np.argsort(mcL[nL > 0])[::-1][:12]]
    print("pure colour-cast (C-only) tiles, strongest 12:",
          list(onlyC[np.argsort(onlyC_m)[::-1][:12]].astype(int)))
    print("strongest luminance-seam tiles, top 12:", list(bigL.astype(int)))
    json.dump({int(r[0]): r[1:] for r in res}, open(SC + "/hybrid_census.json", "w"))
    print("saved hybrid_census.json")
