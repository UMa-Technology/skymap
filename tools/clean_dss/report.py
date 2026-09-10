"""Before/after contact sheets for changed tiles: [before | after | 8x diff]."""
import os
import numpy as np
from PIL import Image
from .io import load_rgb


def write_contact_sheet(src, out, changed, report_dir, order=4):
    os.makedirs(report_dir, exist_ok=True)
    for n in sorted(changed):
        b = load_rgb(f"{src}/Norder{order}/Dir0/Npix{n}.webp").astype(np.float32)
        a = load_rgb(f"{out}/Norder{order}/Dir0/Npix{n}.webp").astype(np.float32)
        diff = np.clip(np.abs(a - b) * 8, 0, 255)
        strip = np.concatenate([b, a, diff], axis=1).astype(np.uint8)
        Image.fromarray(strip).save(f"{report_dir}/Npix{n}.png")
