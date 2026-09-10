"""WebP tile IO for the DSS cleaner. Encoding matches make-dss-survey.py's recipe
(cwebp -q 90 -m 6) so cleaned tiles are consistent with the rest of the survey."""
import hashlib
import os
import subprocess
import tempfile
import numpy as np
from PIL import Image


def load_rgb(path):
    return np.asarray(Image.open(path).convert("RGB"))


def save_webp_q90(img_uint8, dst, q=90):
    """Encode via cwebp -q 90 -m 6 (byte-comparable pipeline to make-dss-survey.py).
    Feed a temp PNG to cwebp."""
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        Image.fromarray(img_uint8).save(tf.name)
        src = tf.name
    try:
        r = subprocess.run(["cwebp", "-quiet", "-q", str(q), "-m", "6", "-o", dst, src],
                           capture_output=True)
        if r.returncode != 0:
            raise RuntimeError(f"cwebp failed: {r.stderr.decode()[:200]}")
    finally:
        os.unlink(src)


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()
