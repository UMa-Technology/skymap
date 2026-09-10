"""Rebuild an order-k HiPS tile from its four order-(k+1) children.
Verified empirically on Npix161 (MSE 2.6/255): quadrants
(TL,TR,BL,BR) = children (0,2,1,3), then 2x INTER_AREA downsample."""
import numpy as np
import cv2

def child_ids(parent_npix):
    return [4*parent_npix + k for k in range(4)]

def rebuild_parent(children):
    """children: list of 4 uint8 (512,512,3) arrays in child order [0,1,2,3]."""
    c0, c1, c2, c3 = children
    top = np.concatenate([c0, c2], axis=1)     # TL=c0, TR=c2
    bot = np.concatenate([c1, c3], axis=1)     # BL=c1, BR=c3
    canvas = np.concatenate([top, bot], axis=0)  # 1024x1024
    return cv2.resize(canvas, (512, 512), interpolation=cv2.INTER_AREA)
