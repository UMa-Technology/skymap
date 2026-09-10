"""Star-suppressed high-pass used by the streak corrector and guardrails:
each channel minus its 31x31 median background (signed; positive part holds
stars/streaks). Identical recipe to the scanner's highpass()."""
import numpy as np
import cv2

def highpass(img, ksize=31):
    hp = np.empty(img.shape, np.float32)
    for c in range(3):
        ch = img[:, :, c].astype(np.uint8)
        bg = cv2.medianBlur(ch, ksize).astype(np.float32)
        hp[:, :, c] = img[:, :, c].astype(np.float32) - bg
    return hp

def response(img, ksize=31, polarity=1):
    """Max-over-channels positive high-pass response (polarity=-1 for dark artifacts)."""
    hp = highpass(img, ksize) * polarity
    return np.clip(hp.max(axis=2), 0, None)
