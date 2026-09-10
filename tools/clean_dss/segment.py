"""Segment a KNOWN-seam tile's coarse background into colour regions, for the
semi-automatic repair. Runs ONLY on tiles a human confirmed contain plate-seam
colour blocks, so there is no false-positive risk: the job is to find the block
regions (by colour), not to decide whether a seam exists. K-means on the coarse-bg
opponent-colour channels groups cells sharing a colour balance; a plate block is one
such group with an anomalous cast, which correct_seam then levels."""
import numpy as np
import cv2

def chroma_features(bg):
    """Opponent-colour channels normalised by brightness: ~flat for grey sky, jump
    across a colour-cast seam. Returns (GRID,GRID,2) float32."""
    R, G, B = bg[..., 0], bg[..., 1], bg[..., 2]
    s = R + G + B + 1e-3
    return np.stack([(R - G) / np.sqrt(s), (B - G) / np.sqrt(s)], -1).astype(np.float32)

def segment(bg, k=6, seed=0):
    """Return (GRID,GRID) int region labels via k-means on coarse-bg chroma.
    Deterministic (fixed cv2 RNG seed). k is clamped to [1, cell count]."""
    g = bg.shape[0]
    feat = chroma_features(bg).reshape(-1, 2)
    k = int(max(1, min(k, g * g)))
    if k == 1:
        return np.zeros((g, g), int)
    cv2.setRNGSeed(seed)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    _, labels, _ = cv2.kmeans(feat, k, None, crit, 5, cv2.KMEANS_PP_CENTERS)
    return labels.reshape(g, g).astype(int)
