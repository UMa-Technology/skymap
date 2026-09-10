"""Re-encode every webp under the given HiPS layer dir(s) to quality-90 (lossy)
for production. Evaluation was done on lossless; q90 is ~1/5 the size and has no
material effect on the already-lossy-JPEG-sourced DSS. In place, multiprocess."""
import os, sys, glob, cv2
from multiprocessing import Pool

def _one(path):
    im = cv2.imread(path)                      # decode lossless
    if im is None:
        return (path, -1, -1)
    before = os.path.getsize(path)
    cv2.imwrite(path, im, [cv2.IMWRITE_WEBP_QUALITY, 90])
    return (path, before, os.path.getsize(path))

if __name__ == "__main__":
    dirs = sys.argv[1:] or ["apps/skydata/surveys/dss"]
    files = []
    for d in dirs:
        files += glob.glob(os.path.join(d, "Norder*", "**", "*.webp"), recursive=True)
    print("re-encoding %d webp under %s ..." % (len(files), ", ".join(dirs)), flush=True)
    with Pool(10) as p:
        res = p.map(_one, files)
    ok = [r for r in res if r[1] >= 0]
    b = sum(r[1] for r in ok); a = sum(r[2] for r in ok)
    print("done: %d tiles | %.1f MB -> %.1f MB (%.1fx smaller) | %d errors"
          % (len(ok), b / 1e6, a / 1e6, b / max(a, 1), len(res) - len(ok)))
