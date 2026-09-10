import numpy as np
import cv2

CELL = 16
GRID = 512 // CELL            # 32
PCT  = 25                     # low percentile => star (bright outlier) robust

def coarse_bg(img_uint8, cell=CELL, pct=PCT):
    """Per-channel star-robust coarse background, shape (GRID,GRID,3) float32."""
    img = img_uint8.astype(np.float32)
    h = (img.shape[0] // cell) * cell
    w = (img.shape[1] // cell) * cell
    gh, gw = h // cell, w // cell
    v = img[:h, :w].reshape(gh, cell, gw, cell, 3)
    return np.percentile(v, pct, axis=(1, 3)).astype(np.float32)

def upsample_smooth(lo, size):
    """Smoothly upsample a coarse (GRID,GRID) map to (size,size) — bicubic then blur.
    Bicubic avoids block edges; the blur guarantees no residual cell steps."""
    up = cv2.resize(lo.astype(np.float32), (size, size), interpolation=cv2.INTER_CUBIC)
    k = max(3, (size // lo.shape[0]) | 1)
    return cv2.GaussianBlur(up, (k, k), 0)
