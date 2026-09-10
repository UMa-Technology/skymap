"""Streak (satellite/aircraft/scratch trail) scanner for DSS tiles. Star-suppressed
directional-opening high-pass -> HoughLinesP -> merge -> weighted-PCA refine ->
perpendicular profile measure -> score. Size-parametric (512 tiles or the 1024 region
stitch) and +/- polarity (bright trails or dark artifacts). Ported from
docs/superpowers/plans/notes/dss-phase2-research/streaks/streaklib.py."""
import numpy as np
import cv2

from . import discriminate

DEFAULT_THRESH = 2.5
DEFAULT_MIN_LEN = 150
DEFAULT_MAX_GAP = 25
DENSE_BINFRAC = 0.10        # binary fraction above this = dense-texture tile (galactic plane)
DENSE_NGROUPS = 10


def highpass(img, ksize=31):
    hp = np.empty(img.shape, np.float32)
    for c in range(3):
        ch = img[:, :, c].astype(np.uint8)
        bg = cv2.medianBlur(ch, ksize).astype(np.float32)
        hp[:, :, c] = img[:, :, c].astype(np.float32) - bg
    return hp


_SES = {}
def _line_ses(line_len=15, n_angles=24):
    key = (line_len, n_angles)
    if key not in _SES:
        ses = []
        for a in np.linspace(0, 180, n_angles, endpoint=False):
            r = (line_len - 1) // 2
            t = np.deg2rad(a); dx, dy = np.cos(t), np.sin(t)
            se = np.zeros((line_len, line_len), np.uint8)
            for s in range(-r, r + 1):
                x = int(round(line_len // 2 + s * dx)); y = int(round(line_len // 2 + s * dy))
                se[y, x] = 1
            ses.append(se)
        _SES[key] = ses
    return _SES[key]


def streak_map(hp, polarity=1, line_len=15, n_angles=24):
    d = np.clip(hp.max(axis=2) if polarity > 0 else (-hp).max(axis=2), 0, None).astype(np.float32)
    resp = np.zeros_like(d)
    for se in _line_ses(line_len, n_angles):
        np.maximum(resp, cv2.morphologyEx(d, cv2.MORPH_OPEN, se), out=resp)
    return resp


def detect_lines(resp, thresh, min_len=DEFAULT_MIN_LEN, max_gap=DEFAULT_MAX_GAP):
    binm = (resp > thresh).astype(np.uint8) * 255
    lines = cv2.HoughLinesP(binm, 1, np.pi / 360, threshold=100,
                            minLineLength=min_len, maxLineGap=max_gap)
    if lines is None:
        return binm, []
    return binm, [tuple(int(v) for v in l) for l in np.asarray(lines).reshape(-1, 4)]


def merge_lines(lines, ang_tol=4.0, dist_tol=6.0):
    groups = []
    for (x1, y1, x2, y2) in lines:
        a = np.rad2deg(np.arctan2(y2 - y1, x2 - x1)) % 180.0
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        placed = False
        for g in groups:
            da = abs(a - g["angle"]); da = min(da, 180 - da)
            if da > ang_tol:
                continue
            t = np.deg2rad(g["angle"]); n = np.array([-np.sin(t), np.cos(t)])
            if abs(np.dot([mx - g["cx"], my - g["cy"]], n)) < dist_tol:
                g["segs"].append((x1, y1, x2, y2)); placed = True
                pts = np.array([(sx, sy) for s in g["segs"] for sx, sy in ((s[0], s[1]), (s[2], s[3]))], float)
                g["cx"], g["cy"] = pts[:, 0].mean(), pts[:, 1].mean()
                break
        if not placed:
            groups.append(dict(angle=a, cx=mx, cy=my, segs=[(x1, y1, x2, y2)]))
    return groups


def refine_line(resp, g, thresh, corridor=4):
    t = np.deg2rad(g["angle"]); u = np.array([np.cos(t), np.sin(t)]); n = np.array([-u[1], u[0]])
    yy, xx = np.nonzero(resp > thresh)
    if len(xx) == 0:
        return None
    rel = np.stack([xx - g["cx"], yy - g["cy"]], 1).astype(float)
    perp = rel @ n
    m = np.abs(perp) < corridor
    if m.sum() < 50:
        return None
    w = resp[yy[m], xx[m]]
    pts = np.stack([xx[m], yy[m]], 1).astype(float)
    c = np.average(pts, 0, weights=w)
    d = pts - c
    cov = (d * w[:, None]).T @ d / w.sum()
    _ev, evec = np.linalg.eigh(cov)
    u2 = evec[:, -1]
    al = d @ u2
    return dict(cx=float(c[0]), cy=float(c[1]),
                angle=float(np.rad2deg(np.arctan2(u2[1], u2[0])) % 180),
                u=np.array([u2[0], u2[1]]), n=np.array([-u2[1], u2[0]]),
                span=(float(al.min()), float(al.max())), support=int(m.sum()))


def measure(hp, resp, fit, size, thresh, half=12):
    u, n = fit["u"], fit["n"]; c = np.array([fit["cx"], fit["cy"]])
    a0, a1 = fit["span"]
    ts = np.arange(a0, a1, 4.0)
    offs = np.arange(-half, half + 0.5, 0.5)
    prof = np.full((3, len(offs), len(ts)), np.nan, np.float32)
    on_line = np.zeros(len(ts), bool)
    for k, t in enumerate(ts):
        pts = c + t * u + offs[:, None] * n[None, :]
        xs, ys = pts[:, 0], pts[:, 1]
        ok = (xs >= 0) & (xs < size - 1) & (ys >= 0) & (ys < size - 1)
        if not ok.any():
            continue
        xi, yi = xs[ok].astype(int), ys[ok].astype(int)
        for ch in range(3):
            prof[ch, ok, k] = hp[yi, xi, ch]
        pc = c + t * u
        if 0 <= pc[0] < size and 0 <= pc[1] < size:
            on_line[k] = resp[int(pc[1]), int(pc[0])] > thresh
    med = np.nanmedian(prof, axis=2); p75 = np.nanpercentile(prof, 75, axis=2)
    wings = np.abs(offs) > 8
    amps, amps75 = [], []
    for ch in range(3):
        amps.append(float(np.nanmax(med[ch, ~wings]) - np.nanmedian(med[ch, wings])))
        amps75.append(float(np.nanmax(p75[ch, ~wings]) - np.nanmedian(p75[ch, wings])))
    dom = int(np.argmax(amps))
    pr = med[dom] - np.nanmedian(med[dom, wings])
    pk = np.nanmax(pr[~wings]); above = offs[(pr >= pk / 2) & (np.abs(offs) <= 8)]
    fwhm = float(above.max() - above.min() + 0.5) if len(above) else float("nan")
    cov = float(on_line.mean()) if len(on_line) else 0.0
    p0 = (c + a0 * u).tolist(); p1 = (c + a1 * u).tolist()
    return dict(amps=amps, amps75=amps75, dom="RGB"[dom], fwhm=fwhm,
                length=float(a1 - a0), fill=cov,
                p0=[round(v, 1) for v in p0], p1=[round(v, 1) for v in p1],
                angle=round(float(fit["angle"]), 1))


def score_group(m):
    adom75 = max(m["amps75"])
    thin = 1.5 if (m["fwhm"] == m["fwhm"] and m["fwhm"] <= 6) else 0.5
    return round(adom75 * m["fill"] * thin, 2)


def scan_image(img, thresh=DEFAULT_THRESH, min_len=DEFAULT_MIN_LEN, max_gap=DEFAULT_MAX_GAP,
               polarity=1, max_groups=25):
    """Detect + localize + score all trail candidates in one image (512 or 1024).
    Returns {binfrac, ngroups, dense, groups:[{**measure, score, fit:{...},
    is_trail, features}]}. Each group additionally carries the trail-vs-DSO
    discriminator verdict (is_trail) and its features (discriminate.trail_vs_dso):
    is_trail False marks a DSO / dense-field false positive that must NOT be cleaned.
    Scoring/geometry keys are unchanged (the gate only ADDS keys)."""
    size = img.shape[0]
    hp = highpass(img)
    resp = streak_map(hp, polarity=polarity)
    binm, lines = detect_lines(resp, thresh, min_len, max_gap)
    binfrac = float((binm > 0).mean())
    groups = merge_lines(lines)
    recs = []
    hp_pol = hp * polarity                       # measure amplitudes in the trail's polarity
    # discriminator response: star-suppressed positive high-pass in the trail's polarity
    # (HP.response recipe), reused for every group so we don't recompute it per fit.
    disc_resp = np.clip((hp * polarity).max(axis=2), 0, None)
    for g in groups[:max_groups]:
        fit = refine_line(resp, g, thresh)
        if fit is None:
            continue
        m = measure(hp_pol, resp, fit, size, thresh)
        m["score"] = score_group(m)
        m["fit"] = fit
        # trail-vs-DSO gate: annotate (does NOT alter score/keys; adds is_trail+features)
        disc = discriminate.trail_vs_dso(img, fit, resp=disc_resp)
        m["is_trail"] = disc["is_trail"]
        m["features"] = disc["features"]
        recs.append(m)
    dense = (binfrac > DENSE_BINFRAC) or (len(groups) > DENSE_NGROUPS)
    return {"binfrac": round(binfrac, 4), "ngroups": len(groups), "dense": bool(dense),
            "groups": recs}
