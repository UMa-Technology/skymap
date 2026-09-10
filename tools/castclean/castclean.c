/* castclean — plate colour-cast removal.  See castclean.h for the overview
 * and docs/superpowers/specs/2026-07-12-chroma-cast-removal-design.md for the
 * algorithm derivation.  Dependency-free C99. */
#include "castclean.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define PCT_BG 25              /* per-cell background percentile            */
#define SLOPE_WIN 7            /* local-slope window (cells)                */
#define MEMBRANE_ITERS 400     /* Jacobi iterations for local inpainting    */
#define GROW_MAX 64            /* hysteresis growth iteration cap           */

/* ------------------------------------------------------------------ utils */

static float *falloc(int n) { return (float *)calloc((size_t)n, sizeof(float)); }
static uint8_t *balloc(int n) { return (uint8_t *)calloc((size_t)n, 1); }

static int float_cmp(const void *a, const void *b)
{
    float fa = *(const float *)a, fb = *(const float *)b;
    return fa < fb ? -1 : fa > fb;
}

/* Box mean over a (2r+1)^2 window clamped to the domain (count-normalised),
 * via a double summed-area table.  sat must hold (w+1)*(h+1) doubles. */
static void box_mean(const float *src, float *dst, int w, int h, int r,
                     double *sat)
{
    int x, y;
    for (x = 0; x <= w; x++) sat[x] = 0.0;
    for (y = 1; y <= h; y++) {
        double row = 0.0;
        sat[y * (w + 1)] = 0.0;
        for (x = 1; x <= w; x++) {
            row += src[(y - 1) * w + (x - 1)];
            sat[y * (w + 1) + x] = sat[(y - 1) * (w + 1) + x] + row;
        }
    }
    for (y = 0; y < h; y++) {
        int y0 = y - r < 0 ? 0 : y - r, y1 = y + r + 1 > h ? h : y + r + 1;
        for (x = 0; x < w; x++) {
            int x0 = x - r < 0 ? 0 : x - r, x1 = x + r + 1 > w ? w : x + r + 1;
            double s = sat[y1 * (w + 1) + x1] - sat[y0 * (w + 1) + x1]
                     - sat[y1 * (w + 1) + x0] + sat[y0 * (w + 1) + x0];
            dst[y * w + x] = (float)(s / ((y1 - y0) * (double)(x1 - x0)));
        }
    }
}

/* 3x3 binary dilation / erosion, out-of-bounds neighbours ignored. */
static void dilate3(const uint8_t *m, uint8_t *out, int w, int h)
{
    int x, y, dx, dy;
    for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
        uint8_t v = 0;
        for (dy = -1; dy <= 1 && !v; dy++) for (dx = -1; dx <= 1; dx++) {
            int yy = y + dy, xx = x + dx;
            if (yy >= 0 && yy < h && xx >= 0 && xx < w && m[yy * w + xx]) {
                v = 1; break;
            }
        }
        out[y * w + x] = v;
    }
}

static void erode3(const uint8_t *m, uint8_t *out, int w, int h)
{
    int x, y, dx, dy;
    for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
        uint8_t v = 1;
        for (dy = -1; dy <= 1 && v; dy++) for (dx = -1; dx <= 1; dx++) {
            int yy = y + dy, xx = x + dx;
            if (yy >= 0 && yy < h && xx >= 0 && xx < w && !m[yy * w + xx]) {
                v = 0; break;
            }
        }
        out[y * w + x] = v;
    }
}

/* close + open + dilate cleanup used on evidence masks */
static void mask_cleanup(uint8_t *m, int w, int h, uint8_t *t1, uint8_t *t2)
{
    dilate3(m, t1, w, h); erode3(t1, t2, w, h);        /* close */
    erode3(t2, t1, w, h); dilate3(t1, t2, w, h);       /* open  */
    dilate3(t2, m, w, h);                              /* reach fringe cells */
}

/* -------------------------------------------------- DCT Poisson (global) */

/* Orthonormal DCT-II (fwd) / DCT-III (inv) along one axis, naive O(n^2) with
 * a cosine table — grids are small (tens of cells per side). */
static void dct1d(const float *x, float *X, int n, const float *cost, int fwd)
{
    int k, i;
    float s0 = (float)sqrt(1.0 / n), s = (float)sqrt(2.0 / n);
    if (fwd) {
        for (k = 0; k < n; k++) {
            double a = 0;
            for (i = 0; i < n; i++) a += x[i] * cost[k * n + i];
            X[k] = (float)(a * (k == 0 ? s0 : s));
        }
    } else {
        for (i = 0; i < n; i++) {
            double a = x[0] * s0;
            for (k = 1; k < n; k++) a += x[k] * s * cost[k * n + i];
            X[i] = (float)a;
        }
    }
}

static float *cos_table(int n)
{
    float *t = falloc(n * n);
    int k, i;
    if (!t) return NULL;
    for (k = 0; k < n; k++)
        for (i = 0; i < n; i++)
            t[k * n + i] = (float)cos(M_PI * (i + 0.5) * k / n);
    return t;
}

static void dct2d(float *f, int w, int h, const float *ctw, const float *cth,
                  float *tmp, int fwd)
{
    int x, y;
    float *line = tmp, *lout = tmp + (w > h ? w : h);
    for (y = 0; y < h; y++) {
        dct1d(f + y * w, lout, w, ctw, fwd);
        memcpy(f + y * w, lout, (size_t)w * sizeof(float));
    }
    for (x = 0; x < w; x++) {
        for (y = 0; y < h; y++) line[y] = f[y * w + x];
        dct1d(line, lout, h, cth, fwd);
        for (y = 0; y < h; y++) f[y * w + x] = lout[y];
    }
}

/* Solve grad(u) ~= (gx,gy) with homogeneous Neumann BC via DCT; mean-0
 * result.  gx are forward differences (gx[y][x] valid for x < w-1), gy
 * likewise for y < h-1.  Mirrors tools/clean_dss/correct.py. */
static void poisson_reconstruct(const float *gx, const float *gy, float *out,
                                int w, int h, const float *ctw,
                                const float *cth, float *tmp)
{
    int x, y;
    for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
        float fx = x == 0 ? gx[y * w] :
                   (x < w - 1 ? gx[y * w + x] - gx[y * w + x - 1]
                              : -gx[y * w + x - 1]);
        float fy = y == 0 ? gy[x] :
                   (y < h - 1 ? gy[y * w + x] - gy[(y - 1) * w + x]
                              : -gy[(y - 1) * w + x]);
        out[y * w + x] = fx + fy;
    }
    dct2d(out, w, h, ctw, cth, tmp, 1);
    for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
        double d = (2 * cos(M_PI * y / h) - 2) + (2 * cos(M_PI * x / w) - 2);
        out[y * w + x] = (y | x) ? (float)(out[y * w + x] / d) : 0.0f;
    }
    dct2d(out, w, h, ctw, cth, tmp, 0);
}

/* weighted median of d[] with weights wgt[] */
typedef struct { float d, w; } dw_t;
static int dw_cmp(const void *a, const void *b)
{
    float da = ((const dw_t *)a)->d, db = ((const dw_t *)b)->d;
    return da < db ? -1 : da > db;
}

static float weighted_median(const float *d, const float *wgt, int n, dw_t *buf)
{
    double tot = 0, acc = 0;
    int i;
    for (i = 0; i < n; i++) {
        buf[i].d = d[i];
        buf[i].w = wgt[i] + 1e-9f;
        tot += buf[i].w;
    }
    qsort(buf, (size_t)n, sizeof(dw_t), dw_cmp);
    for (i = 0; i < n; i++) {
        acc += buf[i].w;
        if (acc >= 0.5 * tot) return buf[i].d;
    }
    return buf[n - 1].d;
}

/* Global solve: cut EX/EY gradients and every gradient touching a membrane
 * cell, reintegrate, re-anchor DC by weighted median (healthy cells). */
static void solve_field(const float *field, const uint8_t *ex,
                        const uint8_t *ey, const uint8_t *membrane,
                        const float *anchor_w, float *out, int w, int h,
                        const float *ctw, const float *cth,
                        float *gx, float *gy, float *tmp, float *dbuf,
                        dw_t *dwbuf)
{
    int x, y, i, n = w * h;
    memset(gx, 0, (size_t)n * sizeof(float));
    memset(gy, 0, (size_t)n * sizeof(float));
    for (y = 0; y < h; y++) for (x = 0; x < w - 1; x++) {
        int cut = ex[y * (w - 1) + x] ||
                  membrane[y * w + x] || membrane[y * w + x + 1];
        gx[y * w + x] = cut ? 0.0f : field[y * w + x + 1] - field[y * w + x];
    }
    for (y = 0; y < h - 1; y++) for (x = 0; x < w; x++) {
        int cut = ey[y * w + x] ||
                  membrane[y * w + x] || membrane[(y + 1) * w + x];
        gy[y * w + x] = cut ? 0.0f : field[(y + 1) * w + x] - field[y * w + x];
    }
    poisson_reconstruct(gx, gy, out, w, h, ctw, cth, tmp);
    for (i = 0; i < n; i++) dbuf[i] = field[i] - out[i];
    float dc = weighted_median(dbuf, anchor_w, n, dwbuf);
    for (i = 0; i < n; i++) out[i] += dc;
}

/* Local harmonic (membrane) inpainting: Jacobi solve of the Laplace equation
 * on mask cells, Dirichlet boundary = observed values outside; neighbour
 * links across cut edges removed.  Non-mask cells returned untouched. */
static void membrane_local(const float *field, const uint8_t *mask,
                           const uint8_t *ex, const uint8_t *ey,
                           float *out, float *nxt, int w, int h)
{
    int it, x, y;
    memcpy(out, field, (size_t)w * h * sizeof(float));
    for (it = 0; it < MEMBRANE_ITERS; it++) {
        for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
            int i = y * w + x;
            if (!mask[i]) { nxt[i] = out[i]; continue; }
            float s = 0; int n = 0;
            if (x + 1 < w && !ex[y * (w - 1) + x])     { s += out[i + 1]; n++; }
            if (x > 0     && !ex[y * (w - 1) + x - 1]) { s += out[i - 1]; n++; }
            if (y + 1 < h && !ey[y * w + x])           { s += out[i + w]; n++; }
            if (y > 0     && !ey[(y - 1) * w + x])     { s += out[i - w]; n++; }
            nxt[i] = n ? s / n : out[i];
        }
        memcpy(out, nxt, (size_t)w * h * sizeof(float));
    }
}

/* ------------------------------------------------------------ full-res ops */

/* He et al. guided filter, scalar guide I, input p, output q.
 * mI/mp/ta/tb are scratch; all six buffers must be distinct. */
static void guided_filter(const float *I, const float *p, float *q,
                          int w, int h, int r, float eps,
                          float *mI, float *mp, float *ta, float *tb,
                          double *sat)
{
    int i, n = w * h;
    box_mean(I, mI, w, h, r, sat);
    box_mean(p, mp, w, h, r, sat);
    for (i = 0; i < n; i++) ta[i] = I[i] * p[i];
    box_mean(ta, tb, w, h, r, sat);                 /* mean(I*p) */
    for (i = 0; i < n; i++) ta[i] = I[i] * I[i];
    box_mean(ta, q, w, h, r, sat);                  /* mean(I*I) */
    for (i = 0; i < n; i++) {
        float a = (tb[i] - mI[i] * mp[i]) / (q[i] - mI[i] * mI[i] + eps);
        ta[i] = a;
        tb[i] = mp[i] - a * mI[i];
    }
    box_mean(ta, mI, w, h, r, sat);                 /* mean a */
    box_mean(tb, mp, w, h, r, sat);                 /* mean b */
    for (i = 0; i < n; i++) q[i] = mI[i] * I[i] + mp[i];
}

static void upsample_nearest(const float *cf, int gw, int gh, float *out,
                             int w, int h)
{
    int x, y;
    for (y = 0; y < h; y++) {
        int cy = y * gh / h; if (cy > gh - 1) cy = gh - 1;
        for (x = 0; x < w; x++) {
            int cx = x * gw / w; if (cx > gw - 1) cx = gw - 1;
            out[y * w + x] = cf[cy * gw + cx];
        }
    }
}

/* Smooth upsample: bilinear + 3 box blurs (~ bicubic + Gaussian of the Python
 * prototype; transition width about one cell). */
static void upsample_smooth(const float *cf, int gw, int gh, float *out,
                            int w, int h, float *tmp, double *sat)
{
    int x, y, cellw = w / gw;
    for (y = 0; y < h; y++) {
        float gy = (y + 0.5f) * gh / h - 0.5f;
        int y0 = (int)floorf(gy); float fy = gy - y0;
        int y1 = y0 + 1;
        if (y0 < 0) { y0 = 0; y1 = 0; fy = 0; }
        if (y1 > gh - 1) { y1 = gh - 1; if (y0 > y1) y0 = y1; }
        for (x = 0; x < w; x++) {
            float gx = (x + 0.5f) * gw / w - 0.5f;
            int x0 = (int)floorf(gx); float fx = gx - x0;
            int x1 = x0 + 1;
            if (x0 < 0) { x0 = 0; x1 = 0; fx = 0; }
            if (x1 > gw - 1) { x1 = gw - 1; if (x0 > x1) x0 = x1; }
            out[y * w + x] =
                (1 - fy) * ((1 - fx) * cf[y0 * gw + x0] + fx * cf[y0 * gw + x1]) +
                fy * ((1 - fx) * cf[y1 * gw + x0] + fx * cf[y1 * gw + x1]);
        }
    }
    {
        int r1 = cellw / 4 > 1 ? cellw / 4 : 1, r2 = cellw / 6 > 1 ? cellw / 6 : 1;
        box_mean(out, tmp, w, h, r1, sat);
        box_mean(tmp, out, w, h, r2, sat);
        box_mean(out, tmp, w, h, r2, sat);
        memcpy(out, tmp, (size_t)w * h * sizeof(float));
    }
}

/* --------------------------------------------------------------- pipeline */

void castclean_params_init(castclean_params *p)
{
    memset(p, 0, sizeof(*p));
    p->cell = 16;
    p->confirmed = 0;
    p->strength_floor = 1.0f;
    p->dead_strict = 1.5f;
    p->dead_abs = 2.5f;
    p->dead_frac = 0.08f;
    p->dead_slope = 0.35f;
    p->dead_varmin = 4.0f;
    p->dead_gmin = 8.0f;
    p->detect_dead_r = 0;
    p->weak_frac = 0.4f;
    p->weak_u = 8.0f;
    p->seam_t1 = 6.0f;
    p->seam_ratio = 2.0f;
    p->seam_t2 = 18.0f;
    p->seam_scales = 3;
    p->fix_blue = 1;
    p->cast_thresh = 2.5f;
    p->base_u_min = -1.0f;
    p->base_v_max = 1.0f;
    p->grow_iters = 3;
    p->grow_thresh = 4.0f;
    p->fix_luminance = 1;
    p->lum_floor = 1.0f;
    p->lum_cap = 6.0f;
    p->lum_reach = 4;
    p->guide_radius = 12;
    p->guide_eps = 36.0f;
    p->prior = NULL;
}

/* Per-cell background: PCT_BG-th percentile per channel via a histogram
 * (star-robust: bright outliers land in the upper bins and are ignored). */
static void coarse_bg(const uint8_t *rgb, int stride, int cell,
                      int gw, int gh, float *R, float *G, float *B)
{
    int cx, cy, x, y, c;
    int hist[3][256];
    for (cy = 0; cy < gh; cy++) for (cx = 0; cx < gw; cx++) {
        memset(hist, 0, sizeof(hist));
        for (y = cy * cell; y < (cy + 1) * cell; y++) {
            const uint8_t *row = rgb + (size_t)y * stride + (size_t)cx * cell * 3;
            for (x = 0; x < cell; x++) {
                hist[0][row[x * 3 + 0]]++;
                hist[1][row[x * 3 + 1]]++;
                hist[2][row[x * 3 + 2]]++;
            }
        }
        {
            int count = cell * cell, target = (count * PCT_BG + 99) / 100;
            float *dst[3];
            dst[0] = R; dst[1] = G; dst[2] = B;
            for (c = 0; c < 3; c++) {
                int acc = 0, v = 0;
                while (v < 255 && acc + hist[c][v] < target) acc += hist[c][v++];
                dst[c][cy * gw + cx] = (float)v;
            }
        }
    }
}

/* local regression slope of Y on X and local var(X), SLOPE_WIN box */
static void local_slope(const float *Y, const float *X, float *slope,
                        float *varX, int w, int h, float *ta, float *tb,
                        float *tc, double *sat)
{
    int i, n = w * h, r = SLOPE_WIN / 2;
    box_mean(X, ta, w, h, r, sat);                     /* mX  */
    box_mean(Y, tb, w, h, r, sat);                     /* mY  */
    for (i = 0; i < n; i++) tc[i] = X[i] * Y[i];
    box_mean(tc, slope, w, h, r, sat);                 /* mXY */
    for (i = 0; i < n; i++) tc[i] = X[i] * X[i];
    box_mean(tc, varX, w, h, r, sat);                  /* mXX */
    for (i = 0; i < n; i++) {
        float cov = slope[i] - ta[i] * tb[i];
        varX[i] = varX[i] - ta[i] * ta[i];
        slope[i] = cov / (varX[i] + 1e-3f);
    }
}

/* halve a grid by 2x2 averaging (truncating odd sizes) */
static void halve(const float *f, int w, int h, float *out, int *ow, int *oh)
{
    int x, y;
    *ow = w / 2; *oh = h / 2;
    for (y = 0; y < *oh; y++) for (x = 0; x < *ow; x++)
        out[y * *ow + x] = 0.25f *
            (f[2 * y * w + 2 * x] + f[2 * y * w + 2 * x + 1] +
             f[(2 * y + 1) * w + 2 * x] + f[(2 * y + 1) * w + 2 * x + 1]);
}

/* chroma-only seam edges at multiple scales, mapped back to fine edges.
 * A plate boundary is a strong (u,v) step with no matching luminance step. */
static int seam_edges(const float *u, const float *v, const float *L,
                      int gw, int gh, const castclean_params *p,
                      uint8_t *EX, uint8_t *EY)
{
    int s, x, y, w = gw, h = gh;
    /* confirmed images tolerate a more aggressive cut: faint plate blocks
     * have chroma steps well below the scan-safe threshold */
    float t1 = p->confirmed ? p->seam_t1 * 0.5f : p->seam_t1;
    float t2 = p->confirmed ? p->seam_t2 * 0.5f : p->seam_t2;
    float *uu = falloc(gw * gh), *vv = falloc(gw * gh), *ll = falloc(gw * gh);
    float *tt = falloc(gw * gh);
    if (!uu || !vv || !ll || !tt) {
        free(uu); free(vv); free(ll); free(tt);
        return -1;
    }
    memcpy(uu, u, (size_t)gw * gh * sizeof(float));
    memcpy(vv, v, (size_t)gw * gh * sizeof(float));
    memcpy(ll, L, (size_t)gw * gh * sizeof(float));
    memset(EX, 0, (size_t)gh * (gw - 1));
    memset(EY, 0, (size_t)(gh - 1) * gw);
    for (s = 0; s < p->seam_scales && w >= 4 && h >= 4; s++) {
        int f = 1 << s;
        for (y = 0; y < h; y++) for (x = 0; x < w - 1; x++) {
            float gux = uu[y * w + x + 1] - uu[y * w + x];
            float gvx = vv[y * w + x + 1] - vv[y * w + x];
            float glx = fabsf(ll[y * w + x + 1] - ll[y * w + x]);
            float cx = hypotf(gux, gvx);
            if ((cx > t1 && cx > p->seam_ratio * glx) || cx > t2) {
                int col = (x + 1) * f - 1, rr;
                if (col < gw - 1)
                    for (rr = y * f; rr < (y + 1) * f && rr < gh; rr++)
                        EX[rr * (gw - 1) + col] = 1;
            }
        }
        for (y = 0; y < h - 1; y++) for (x = 0; x < w; x++) {
            float guy = uu[(y + 1) * w + x] - uu[y * w + x];
            float gvy = vv[(y + 1) * w + x] - vv[y * w + x];
            float gly = fabsf(ll[(y + 1) * w + x] - ll[y * w + x]);
            float cy = hypotf(guy, gvy);
            if ((cy > t1 && cy > p->seam_ratio * gly) || cy > t2) {
                int row = (y + 1) * f - 1, cc;
                if (row < gh - 1)
                    for (cc = x * f; cc < (x + 1) * f && cc < gw; cc++)
                        EY[row * gw + cc] = 1;
            }
        }
        {
            int nw, nh;
            halve(uu, w, h, tt, &nw, &nh);
            memcpy(uu, tt, (size_t)nw * nh * sizeof(float));
            halve(vv, w, h, tt, &nw, &nh);
            memcpy(vv, tt, (size_t)nw * nh * sizeof(float));
            halve(ll, w, h, tt, &nw, &nh);
            memcpy(ll, tt, (size_t)nw * nh * sizeof(float));
            w = nw; h = nh;
        }
    }
    free(uu); free(vv); free(ll); free(tt);
    return 0;
}

/* Per-image luminance-conditioned chroma baseline as a binned-median LUT
 * over non-mask cells: healthy background chroma RISES with luminance
 * (bright star clouds are warm), so corrections must preserve that relation
 * or the result reads too cold.  Equal weights per healthy cell — weighting
 * by chroma-consistency was tried and biases the fit cold (it down-weights
 * exactly the warm cells the baseline must learn from). */
#define LUT_NB 12
typedef struct {
    float centers[LUT_NB];
    float u[LUT_NB], v[LUT_NB];
} chroma_lut;

static void lut_build(const float *u, const float *v, const float *L,
                      const uint8_t *mask, int n, float *scratch,
                      chroma_lut *lut, float u_min, float v_max)
{
    float lmax = 0;
    int i, b, nh = 0;
    for (i = 0; i < n; i++) if (!mask[i]) scratch[nh++] = L[i];
    if (nh == 0) { nh = n; for (i = 0; i < n; i++) scratch[i] = L[i]; }
    qsort(scratch, (size_t)nh, sizeof(float), float_cmp);
    lmax = scratch[(int)(0.99 * (nh - 1))] + 1e-3f;
    for (b = 0; b < LUT_NB; b++)
        lut->centers[b] = lmax * (b + 0.5f) / LUT_NB;
    for (b = 0; b < LUT_NB; b++) {
        int m = 0;
        const float *f[2]; float *dst[2];
        int c;
        f[0] = u; f[1] = v; dst[0] = lut->u; dst[1] = lut->v;
        for (c = 0; c < 2; c++) {
            m = 0;
            for (i = 0; i < n; i++) {
                int bi = (int)(L[i] / lmax * LUT_NB);
                if (bi > LUT_NB - 1) bi = LUT_NB - 1;
                if (!mask[i] && bi == b) scratch[m++] = f[c][i];
            }
            if (m >= 8) {
                qsort(scratch, (size_t)m, sizeof(float), float_cmp);
                dst[c][b] = scratch[m / 2];
            } else {
                dst[c][b] = 1e30f;      /* gap: fill below */
            }
        }
    }
    /* fill gaps with the nearest valid bin */
    for (b = 0; b < LUT_NB; b++) {
        if (lut->u[b] < 1e29f) continue;
        int d, j = -1;
        for (d = 1; d < LUT_NB && j < 0; d++) {
            if (b - d >= 0 && lut->u[b - d] < 1e29f) j = b - d;
            else if (b + d < LUT_NB && lut->u[b + d] < 1e29f) j = b + d;
        }
        if (j < 0) { lut->u[b] = 0; lut->v[b] = 0; }
        else { lut->u[b] = lut->u[j]; lut->v[b] = lut->v[j]; }
    }
    /* blue-side clamp: when a cast covers MOST of the image the per-image
     * baseline absorbs it (residuals ~ 0, nothing gets selected).  Healthy
     * sky background in a scanned survey is never blue on average, so bound
     * the baseline from the blue side; warm dust stays untouched. */
    for (b = 0; b < LUT_NB; b++) {
        if (lut->u[b] < u_min) lut->u[b] = u_min;
        if (lut->v[b] > v_max) lut->v[b] = v_max;
    }
}

static void lut_eval(const chroma_lut *lut, float Lq, float *pu, float *pv)
{
    float t;
    int b;
    if (Lq <= lut->centers[0]) { *pu = lut->u[0]; *pv = lut->v[0]; return; }
    if (Lq >= lut->centers[LUT_NB - 1]) {
        *pu = lut->u[LUT_NB - 1]; *pv = lut->v[LUT_NB - 1];
        return;
    }
    b = 0;
    while (b < LUT_NB - 2 && lut->centers[b + 1] < Lq) b++;
    t = (Lq - lut->centers[b]) / (lut->centers[b + 1] - lut->centers[b]);
    *pu = lut->u[b] * (1 - t) + lut->u[b + 1] * t;
    *pv = lut->v[b] * (1 - t) + lut->v[b + 1] * t;
}

/* Spatially-local healthy chroma-vs-luminance gain cov(c,L)/var(L) over a
 * SLOPE_WIN window of non-mask cells, membrane-filled into the mask (and
 * into low-support cells).  Drives the resynthesis texture term: chroma
 * fluctuation = gain * luminance fluctuation, so bright grain inside a
 * corrected region stays warm exactly like its surroundings.  (A
 * luminance-binned gain was tried first: bimodal images — warm cloud +
 * blue star field — give huge spurious slopes at bin transitions.) */
static void local_gain_grid(const float *c, const float *L,
                            const uint8_t *mask, float *k, int w, int h,
                            float *ta, float *tb, float *tc, float *td,
                            float *te, uint8_t *mfill,
                            const uint8_t *ex0, const uint8_t *ey0,
                            double *sat)
{
    int i, n = w * h, r = SLOPE_WIN / 2;
    for (i = 0; i < n; i++) ta[i] = mask[i] ? 0.0f : 1.0f;
    box_mean(ta, tb, w, h, r, sat);                     /* Sw          */
    for (i = 0; i < n; i++) tc[i] = ta[i] * L[i];
    box_mean(tc, td, w, h, r, sat);                     /* mean(w*L)   */
    for (i = 0; i < n; i++) tc[i] = ta[i] * c[i];
    box_mean(tc, te, w, h, r, sat);                     /* mean(w*c)   */
    for (i = 0; i < n; i++) tc[i] = ta[i] * L[i] * c[i];
    box_mean(tc, k, w, h, r, sat);                      /* mean(w*L*c) */
    for (i = 0; i < n; i++) tc[i] = ta[i] * L[i] * L[i];
    box_mean(tc, tc, w, h, r, sat);                     /* mean(w*L*L) */
    for (i = 0; i < n; i++) {
        float sw = tb[i] + 1e-6f;
        float mL = td[i] / sw, mc = te[i] / sw;
        float cov = k[i] / sw - mL * mc;
        float var = tc[i] / sw - mL * mL;
        float kk = cov / (var + 1e-3f);
        int good = tb[i] > 8.0f / (SLOPE_WIN * SLOPE_WIN) && var > 4.0f;
        if (kk > 1.5f) kk = 1.5f;
        if (kk < -1.0f) kk = -1.0f;
        k[i] = kk;
        mfill[i] = (uint8_t)(!good || mask[i]);
    }
    membrane_local(k, mfill, ex0, ey0, ta, tb, w, h);
    for (i = 0; i < n; i++) {
        float kk = ta[i];
        if (kk > 1.5f) kk = 1.5f;
        if (kk < -1.0f) kk = -1.0f;
        k[i] = kk;
    }
}

/* anchor weights: 1/(1+z^2) against the survey prior when given, else
 * against per-image robust (median/MAD) chroma statistics */
static void anchor_weights(const float *u, const float *v, const float *L,
                           int n, const castclean_prior *prior, float *w,
                           float *scratch)
{
    int i, c;
    if (prior && prior->nbins > 1) {
        for (i = 0; i < n; i++) {
            float t = L[i] / prior->lmax * prior->nbins - 0.5f;
            int b = (int)floorf(t);
            float fr = t - b;
            if (b < 0) { b = 0; fr = 0; }
            if (b > prior->nbins - 2) { b = prior->nbins - 2; fr = 1; }
            {
                float pu = prior->med_u[b] * (1 - fr) + prior->med_u[b + 1] * fr;
                float pv = prior->med_v[b] * (1 - fr) + prior->med_v[b + 1] * fr;
                float su = prior->mad_u[b] * (1 - fr) + prior->mad_u[b + 1] * fr;
                float sv = prior->mad_v[b] * (1 - fr) + prior->mad_v[b + 1] * fr;
                float zu, zv;
                if (su < 1) su = 1;
                if (sv < 1) sv = 1;
                zu = (u[i] - pu) / su; zv = (v[i] - pv) / sv;
                w[i] = 1.0f / (1.0f + zu * zu + zv * zv);
            }
        }
        return;
    }
    {
        float med[2], mad[2];
        const float *f[2];
        f[0] = u; f[1] = v;
        for (c = 0; c < 2; c++) {
            memcpy(scratch, f[c], (size_t)n * sizeof(float));
            qsort(scratch, (size_t)n, sizeof(float), float_cmp);
            med[c] = scratch[n / 2];
            for (i = 0; i < n; i++) scratch[i] = fabsf(f[c][i] - med[c]);
            qsort(scratch, (size_t)n, sizeof(float), float_cmp);
            mad[c] = 1.4826f * scratch[n / 2];
            if (mad[c] < 1) mad[c] = 1;
        }
        for (i = 0; i < n; i++) {
            float zu = (u[i] - med[0]) / mad[0], zv = (v[i] - med[1]) / mad[1];
            w[i] = 1.0f / (1.0f + zu * zu + zv * zv);
        }
    }
}

int castclean_rgb8(uint8_t *rgb, int width, int height, int stride,
                   const castclean_params *params, castclean_report *report)
{
    castclean_params def;
    const castclean_params *p = params;
    int gw, gh, gn, n, i, x, y, ok = -1;

    /* grid-scale buffers */
    float *R = NULL, *G = NULL, *B = NULL, *u = NULL, *v = NULL, *L = NULL;
    float *t1 = NULL, *t2 = NULL, *t3 = NULL, *t4 = NULL;
    float *u2 = NULL, *v2 = NULL, *du = NULL, *dv = NULL;
    float *aw = NULL, *aw2 = NULL;
    float *uh = NULL, *vh = NULL, *ruf = NULL, *rvf = NULL;
    float *kug = NULL, *kvg = NULL;
    uint8_t *ex0 = NULL, *ey0 = NULL;
    chroma_lut lut;
    uint8_t *dead = NULL, *weak = NULL, *mask = NULL, *m1 = NULL, *m2 = NULL;
    uint8_t *EX = NULL, *EY = NULL;
    double *gsat = NULL;
    float *ctw = NULL, *cth = NULL, *gx = NULL, *gy = NULL, *ptmp = NULL;
    dw_t *dwbuf = NULL;
    /* full-res buffers */
    float *ufull = NULL, *vfull = NULL, *Lfull = NULL, *Wg = NULL;
    float *fa = NULL, *fb = NULL, *fc = NULL, *fd = NULL;
    float *fe = NULL, *ff = NULL, *fg = NULL, *fh = NULL;
    float *fi = NULL, *fj = NULL;
    double *isat = NULL;

    if (!p) { castclean_params_init(&def); p = &def; }
    if (report) memset(report, 0, sizeof(*report));
    if (!rgb || p->cell < 4 || width < 4 * p->cell || height < 4 * p->cell ||
        stride < 3 * width)
        return -1;

    gw = width / p->cell; gh = height / p->cell; gn = gw * gh;
    n = width * height;

    R = falloc(gn); G = falloc(gn); B = falloc(gn);
    u = falloc(gn); v = falloc(gn); L = falloc(gn);
    t1 = falloc(gn); t2 = falloc(gn); t3 = falloc(gn); t4 = falloc(gn);
    u2 = falloc(gn); v2 = falloc(gn); du = falloc(gn); dv = falloc(gn);
    aw = falloc(gn); aw2 = falloc(gn);
    uh = falloc(gn); vh = falloc(gn); ruf = falloc(gn); rvf = falloc(gn);
    kug = falloc(gn); kvg = falloc(gn);
    ex0 = balloc(gh * (gw - 1)); ey0 = balloc((gh - 1) * gw);
    dead = balloc(gn); weak = balloc(gn); mask = balloc(gn);
    m1 = balloc(gn); m2 = balloc(gn);
    EX = balloc(gh * (gw - 1)); EY = balloc((gh - 1) * gw);
    gsat = (double *)calloc((size_t)(gw + 1) * (gh + 1), sizeof(double));
    dwbuf = (dw_t *)calloc((size_t)gn, sizeof(dw_t));
    if (!R || !G || !B || !u || !v || !L || !t1 || !t2 || !t3 || !t4 ||
        !u2 || !v2 || !du || !dv || !aw || !aw2 || !uh || !vh || !ruf ||
        !rvf || !kug || !kvg || !ex0 || !ey0 || !dead || !weak || !mask ||
        !m1 || !m2 || !EX || !EY || !gsat || !dwbuf)
        goto done;

    /* ---- 1. star-robust coarse background, opponent fields ---- */
    coarse_bg(rgb, stride, p->cell, gw, gh, R, G, B);
    for (i = 0; i < gn; i++) {
        u[i] = R[i] - G[i];
        v[i] = B[i] - G[i];
        L[i] = (R[i] + G[i] + B[i]) / 3.0f;
    }

    /* ---- 2. dead-channel (missing plate) evidence ---- */
    {
        int fam, nfam = p->detect_dead_r ? 2 : 1;
        for (fam = 0; fam < nfam; fam++) {
            const float *C = fam == 0 ? B : R;
            local_slope(C, G, t1, t2, gw, gh, t3, t4, u2, gsat);
            for (i = 0; i < gn; i++) {
                int strict = C[i] < p->dead_strict;
                float lvl = p->dead_abs > p->dead_frac * G[i] ?
                            p->dead_abs : p->dead_frac * G[i];
                int wk = C[i] < lvl && t1[i] < p->dead_slope &&
                         t2[i] > p->dead_varmin;
                m1[i] = (uint8_t)((strict || wk) && G[i] > p->dead_gmin);
            }
            mask_cleanup(m1, gw, gh, m2, mask);
            for (i = 0; i < gn; i++) dead[i] |= m1[i];
        }
        memset(mask, 0, (size_t)gn);
    }

    /* ---- 3. hysteresis growth through connected weakly-dead warm cells ---- */
    for (i = 0; i < gn; i++) {
        int wb = B[i] < p->weak_frac * G[i] && u[i] > p->weak_u &&
                 G[i] > p->dead_gmin;
        int wr = p->detect_dead_r && R[i] < p->weak_frac * G[i] &&
                 -u[i] > p->weak_u && G[i] > p->dead_gmin;
        weak[i] = (uint8_t)(wb || wr);
    }
    dilate3(weak, m1, gw, gh); erode3(m1, weak, gw, gh);   /* close */
    memcpy(mask, dead, (size_t)gn);
    for (i = 0; i < GROW_MAX; i++) {
        int changed = 0;
        dilate3(mask, m1, gw, gh);
        for (x = 0; x < gn; x++) {
            uint8_t nv = (uint8_t)(m1[x] && (weak[x] || mask[x]));
            if (nv && !mask[x]) changed = 1;
            m2[x] = nv;
        }
        memcpy(mask, m2, (size_t)gn);
        if (!changed) break;
    }

    {
        int any = 0, ndead = 0;
        for (i = 0; i < gn; i++) { any |= mask[i]; ndead += dead[i]; }
        if (report) report->dead_frac = (float)ndead / gn;
        if (!p->confirmed && !any) { ok = 0; goto done; }  /* untouched */
    }

    /* ---- 4. seam edges + anchor weights ---- */
    if (seam_edges(u, v, L, gw, gh, p, EX, EY) != 0) goto done;
    anchor_weights(u, v, L, gn, p->prior, aw, t3);

    /* ---- 4b. luminance-conditioned chroma baseline (healthy cells) ----
     * Corrections run on the RESIDUAL relative to this baseline, so the
     * "brighter = warmer" relation of genuine star clouds survives; only the
     * anomaly is removed (otherwise corrected regions come out too cold). */
    lut_build(u, v, L, mask, gn, t3, &lut, p->base_u_min, p->base_v_max);
    for (i = 0; i < gn; i++) {
        lut_eval(&lut, L[i], &uh[i], &vh[i]);
        ruf[i] = u[i] - uh[i];
        rvf[i] = v[i] - vh[i];
    }

    /* ---- 5. corrected chroma fields (residual space) ---- */
    if (p->confirmed) {
        int it;
        ctw = cos_table(gw); cth = cos_table(gh);
        gx = falloc(gn); gy = falloc(gn);
        ptmp = falloc(2 * (gw > gh ? gw : gh));
        if (!ctw || !cth || !gx || !gy || !ptmp) goto done;
        for (it = 0; it < p->grow_iters; it++) {
            int changed = 0;
            for (i = 0; i < gn; i++) aw2[i] = mask[i] ? 0.0f : aw[i];
            solve_field(ruf, EX, EY, mask, aw2, u2, gw, gh, ctw, cth,
                        gx, gy, ptmp, t3, dwbuf);
            solve_field(rvf, EX, EY, mask, aw2, v2, gw, gh, ctw, cth,
                        gx, gy, ptmp, t3, dwbuf);
            /* direction-aware growth: a candidate's residual must point the
             * same way as the neighbouring masked cells' cast (an orange
             * region cannot swallow an adjacent genuine blue nebula) */
            for (i = 0; i < gn; i++) {
                t1[i] = ruf[i] - u2[i];
                t2[i] = rvf[i] - v2[i];
                t3[i] = mask[i] ? 1.0f : 0.0f;
            }
            for (i = 0; i < gn; i++) t4[i] = t3[i] * t1[i];
            box_mean(t4, du, gw, gh, 1, gsat);         /* mean(mask*ru) */
            for (i = 0; i < gn; i++) t4[i] = t3[i] * t2[i];
            box_mean(t4, dv, gw, gh, 1, gsat);         /* mean(mask*rv) */
            box_mean(t3, t4, gw, gh, 1, gsat);         /* mean(mask)    */
            dilate3(mask, m1, gw, gh);
            for (i = 0; i < gn; i++) {
                float res, mu, mv, dot;
                if (!m1[i] || mask[i]) continue;
                res = hypotf(t1[i], t2[i]);
                if (res <= p->grow_thresh) continue;
                mu = du[i] / (t4[i] + 1e-6f);
                mv = dv[i] / (t4[i] + 1e-6f);
                dot = t1[i] * mu + t2[i] * mv;
                if (dot > 0.6f * res * hypotf(mu, mv)) {
                    mask[i] = 1;
                    changed = 1;
                }
            }
            if (!changed) break;
        }
        if (p->fix_blue) {
            /* pass 2: soft blue plate casts (R suppressed AND B elevated
             * vs the baseline) join the resynthesis mask so their
             * off-colour texture is replaced too.  Soft-edged diamonds
             * cannot be found by edge enclosure; the residual direction is
             * unambiguous, and genuine warm dust is opposite-signed.
             * Small isolated speckles are dropped. */
            int nnew = 0, sp;
            for (i = 0; i < gn; i++)
                m1[i] = (uint8_t)(ruf[i] < -p->cast_thresh &&
                                  rvf[i] > 0.5f * p->cast_thresh);
            dilate3(m1, m2, gw, gh); erode3(m2, m1, gw, gh);   /* close */
            erode3(m1, m2, gw, gh); dilate3(m2, m1, gw, gh);   /* open  */
            /* drop connected components smaller than 6 cells */
            for (i = 0; i < gn; i++) m2[i] = 0;   /* visited */
            for (sp = 0; sp < gn; sp++) {
                int head, count, j2;
                if (!m1[sp] || m2[sp]) continue;
                /* BFS using dwbuf as an int queue (gn entries fit) */
                {
                    int *q = (int *)dwbuf;
                    head = 0; count = 0;
                    q[count++] = sp; m2[sp] = 1;
                    while (head < count) {
                        int c0 = q[head++], cy = c0 / gw, cx0 = c0 % gw;
                        int dy2, dx2;
                        for (dy2 = -1; dy2 <= 1; dy2++)
                            for (dx2 = -1; dx2 <= 1; dx2++) {
                                int yy = cy + dy2, xx = cx0 + dx2, j3;
                                if (yy < 0 || yy >= gh || xx < 0 || xx >= gw)
                                    continue;
                                j3 = yy * gw + xx;
                                if (m1[j3] && !m2[j3]) { m2[j3] = 1; q[count++] = j3; }
                            }
                    }
                    if (count < 6)
                        for (j2 = 0; j2 < count; j2++) m1[q[j2]] = 0;
                }
            }
            /* hysteresis: grow surviving seeds through connected weakly-blue
             * cells so soft cast fringes and faint blue blocks are covered */
            {
                int it2, ch2;
                for (it2 = 0; it2 < GROW_MAX; it2++) {
                    ch2 = 0;
                    dilate3(m1, m2, gw, gh);
                    for (i = 0; i < gn; i++) {
                        int wk = ruf[i] < -0.5f * p->cast_thresh &&
                                 rvf[i] > 0.25f * p->cast_thresh;
                        uint8_t nv = (uint8_t)(m2[i] && (wk || m1[i]));
                        if (nv && !m1[i]) ch2 = 1;
                        m2[i] = nv;
                    }
                    memcpy(m1, m2, (size_t)gn);
                    if (!ch2) break;
                }
            }
            dilate3(m1, m2, gw, gh);
            for (i = 0; i < gn; i++) {
                if (m2[i] && !mask[i]) nnew++;
                m2[i] |= mask[i];
            }
            if (nnew > 0) {
                int nh2 = 0;
                memcpy(mask, m2, (size_t)gn);
                for (i = 0; i < gn; i++) nh2 += !mask[i];
                if (nh2 >= gn / 4) {        /* refit baseline off the casts */
                    lut_build(u, v, L, mask, gn, t3, &lut, p->base_u_min, p->base_v_max);
                    for (i = 0; i < gn; i++) {
                        lut_eval(&lut, L[i], &uh[i], &vh[i]);
                        ruf[i] = u[i] - uh[i];
                        rvf[i] = v[i] - vh[i];
                    }
                }
                for (i = 0; i < gn; i++) aw2[i] = mask[i] ? 0.0f : aw[i];
                solve_field(ruf, EX, EY, mask, aw2, u2, gw, gh, ctw, cth,
                            gx, gy, ptmp, t3, dwbuf);
                solve_field(rvf, EX, EY, mask, aw2, v2, gw, gh, ctw, cth,
                            gx, gy, ptmp, t3, dwbuf);
            }
        }
    } else {
        membrane_local(ruf, mask, EX, EY, u2, t3, gw, gh);
        membrane_local(rvf, mask, EX, EY, v2, t3, gw, gh);
    }

    for (i = 0; i < gn; i++) {
        u2[i] += uh[i];                       /* residual -> chroma space */
        v2[i] += vh[i];
        du[i] = u[i] - u2[i];
        dv[i] = v[i] - v2[i];
        if (fabsf(du[i]) < p->strength_floor) du[i] = 0;
        if (fabsf(dv[i]) < p->strength_floor) dv[i] = 0;
    }

    /* ---- 6. full-resolution application ---- */
    ufull = falloc(n); vfull = falloc(n); Lfull = falloc(n); Wg = falloc(n);
    fa = falloc(n); fb = falloc(n); fc = falloc(n); fd = falloc(n);
    fe = falloc(n); ff = falloc(n); fg = falloc(n); fh = falloc(n);
    fi = falloc(n); fj = falloc(n);
    isat = (double *)calloc((size_t)(width + 1) * (height + 1), sizeof(double));
    if (!ufull || !vfull || !Lfull || !Wg || !fa || !fb || !fc || !fd ||
        !fe || !ff || !fg || !fh || !fi || !fj || !isat)
        goto done;

    for (y = 0; y < height; y++) {
        const uint8_t *row = rgb + (size_t)y * stride;
        for (x = 0; x < width; x++) {
            float r = row[x * 3], g = row[x * 3 + 1], b = row[x * 3 + 2];
            ufull[y * width + x] = r - g;
            vfull[y * width + x] = b - g;
            Lfull[y * width + x] = (r + g + b) / 3.0f;
            Wg[y * width + x] = r - b;
        }
    }

    /* additive deltas, pixel-sharp at true plate edges (guide = warmth W) */
    upsample_nearest(du, gw, gh, fa, width, height);
    guided_filter(Wg, fa, fb, width, height, p->guide_radius, p->guide_eps,
                  fc, fd, fe, ff, isat);               /* fb = du_full */
    for (i = 0; i < n; i++) ufull[i] -= fb[i];         /* u_corr */
    upsample_nearest(dv, gw, gh, fa, width, height);
    guided_filter(Wg, fa, fb, width, height, p->guide_radius, p->guide_eps,
                  fc, fd, fe, ff, isat);               /* fb = dv_full */
    for (i = 0; i < n; i++) vfull[i] -= fb[i];         /* v_corr */

    /* resynthesis targets: smooth corrected chroma + texture term (local
     * healthy gain * luminance fluctuation) so grain inside the region
     * matches its surroundings instead of reading flat/cold */
    upsample_smooth(u2, gw, gh, fa, width, height, fb, isat);   /* fa = u_res */
    upsample_smooth(v2, gw, gh, fg, width, height, fb, isat);   /* fg = v_res */
    local_gain_grid(u, L, mask, kug, gw, gh, t1, t2, t3, t4, aw2,
                    m1, ex0, ey0, gsat);
    local_gain_grid(v, L, mask, kvg, gw, gh, t1, t2, t3, t4, aw2,
                    m1, ex0, ey0, gsat);
    upsample_smooth(L, gw, gh, fi, width, height, fb, isat);    /* L coarse   */
    box_mean(Lfull, fj, width, height, 2, isat);                /* L box5     */
    for (i = 0; i < n; i++) fj[i] -= fi[i];                     /* fluct      */
    upsample_smooth(kug, gw, gh, fi, width, height, fb, isat);
    for (i = 0; i < n; i++) fa[i] += fi[i] * fj[i];
    upsample_smooth(kvg, gw, gh, fi, width, height, fb, isat);
    for (i = 0; i < n; i++) fg[i] += fi[i] * fj[i];
    /* fj keeps the luminance fluctuation for the bright-blob protection in
     * the blend below; fi becomes the dead-region weight (bright blobs
     * INSIDE dead regions are the defect itself — never protected) */
    for (i = 0; i < gn; i++) t3[i] = dead[i] ? 1.0f : 0.0f;
    upsample_smooth(t3, gw, gh, fi, width, height, fb, isat);

    /* blend weight: guided-upsampled mask, hard-confined to mask support */
    for (i = 0; i < gn; i++) t3[i] = mask[i] ? 1.0f : 0.0f;
    upsample_nearest(t3, gw, gh, fb, width, height);
    guided_filter(Wg, fb, fh, width, height, p->guide_radius, p->guide_eps,
                  fc, fd, fe, ff, isat);               /* fh = guided mask */
    upsample_smooth(t3, gw, gh, fb, width, height, fc, isat);   /* soft mask */
    for (y = 0; y < height; y++) {
        const uint8_t *row = rgb + (size_t)y * stride;
        for (x = 0; x < width; x++) {
            int j = y * width + x;
            float ub, vb, prot;
            float wm = fh[j], hard = fb[j] * 1.3f;
            float rr0 = row[x * 3], gg0 = row[x * 3 + 1], bb0 = row[x * 3 + 2];
            float vi = bb0 - gg0, ui = rr0 - gg0;
            if (hard > 1) hard = 1;
            if (hard < 0) hard = 0;
            if (wm > 1) wm = 1;
            if (wm < 0) wm = 0;
            wm *= hard;
            ub = wm * fa[j] + (1 - wm) * ufull[j];         /* blended u */
            vb = wm * fg[j] + (1 - wm) * vfull[j];         /* blended v */
            /* bright + strongly-blue pixels are genuine nebulosity
             * (reflection nebulae are bright; blue plate casts sit on a dim
             * background) — they keep their ORIGINAL chroma entirely,
             * shielding them from resynthesis AND the additive delta */
            {
                float li = (rr0 + gg0 + bb0) / 3.0f;
                float pb = (vi - 20.0f) / 25.0f;
                float pl = (li - 40.0f) / 30.0f;
                if (pb > 1) pb = 1;
                if (pb < 0) pb = 0;
                if (pl > 1) pl = 1;
                if (pl < 0) pl = 0;
                prot = pb * pl;
                if (!p->fix_blue) {
                    /* operator declared genuine blue present: shield any
                     * strongly blue pixel regardless of brightness */
                    float p2 = (vi - 10.0f) / 20.0f;
                    if (p2 > 1) p2 = 1;
                    if (p2 < 0) p2 = 0;
                    if (p2 > prot) prot = p2;
                }
                /* compact bright objects (nebula cores, clusters): their
                 * luminance fluctuation is far above star-field grain and
                 * synthesising chroma from luminance would tint them; keep
                 * their original colour — except inside dead regions,
                 * where the original colour IS the defect */
                {
                    float p3 = (fj[j] - 25.0f) / 25.0f;
                    float nd = 1.0f - fi[j];
                    if (p3 > 1) p3 = 1;
                    if (p3 < 0) p3 = 0;
                    if (nd < 0) nd = 0;
                    if (nd > 1) nd = 1;
                    p3 *= nd;
                    if (p3 > prot) prot = p3;
                }
            }
            ufull[j] = prot * ui + (1 - prot) * ub;        /* u_out */
            vfull[j] = prot * vi + (1 - prot) * vb;        /* v_out */
        }
    }

    /* optional seam-luminance levelling (confirmed mode only) */
    if (p->confirmed && p->fix_luminance) {
        memset(m1, 0, (size_t)gn);
        for (i = 0; i < gn; i++) aw2[i] = mask[i] ? 0.0f : aw[i];
        solve_field(L, EX, EY, m1, aw2, t1, gw, gh, ctw, cth,
                    gx, gy, ptmp, t3, dwbuf);
        for (i = 0; i < gn; i++) {
            t2[i] = L[i] - t1[i];
            if (fabsf(t2[i]) < p->lum_floor) t2[i] = 0;
            /* bigger steps across a cut are object luminance (a glow
             * clipped by the seam), not plate sky mismatch — cap them */
            if (t2[i] > p->lum_cap) t2[i] = p->lum_cap;
            if (t2[i] < -p->lum_cap) t2[i] = -p->lum_cap;
        }
        memcpy(m1, mask, (size_t)gn);
        for (i = 0; i < p->lum_reach; i++) {
            dilate3(m1, m2, gw, gh);
            memcpy(m1, m2, (size_t)gn);
        }
        for (i = 0; i < gn; i++) if (!m1[i]) t2[i] = 0;
        upsample_nearest(t2, gw, gh, fb, width, height);
        guided_filter(Lfull, fb, fc, width, height, p->guide_radius,
                      p->guide_eps, fd, fe, ff, fh, isat);
        for (i = 0; i < n; i++) Lfull[i] -= fc[i];
    }

    /* ---- 7. reconstruct, clip, report ---- */
    {
        double acc = 0;
        for (y = 0; y < height; y++) {
            uint8_t *row = rgb + (size_t)y * stride;
            for (x = 0; x < width; x++) {
                int j = y * width + x, r8, g8, b8;
                float m = (ufull[j] + vfull[j]) / 3.0f;
                float rr = Lfull[j] + ufull[j] - m;
                float gg = Lfull[j] - m;
                float bb = Lfull[j] + vfull[j] - m;
                r8 = (int)lrintf(rr < 0 ? 0 : (rr > 255 ? 255 : rr));
                g8 = (int)lrintf(gg < 0 ? 0 : (gg > 255 ? 255 : gg));
                b8 = (int)lrintf(bb < 0 ? 0 : (bb > 255 ? 255 : bb));
                acc += abs(r8 - row[x * 3]) + abs(g8 - row[x * 3 + 1]) +
                       abs(b8 - row[x * 3 + 2]);
                row[x * 3] = (uint8_t)r8;
                row[x * 3 + 1] = (uint8_t)g8;
                row[x * 3 + 2] = (uint8_t)b8;
            }
        }
        if (report) {
            int nmask = 0;
            float mdu = 0, mdv = 0;
            for (i = 0; i < gn; i++) {
                nmask += mask[i];
                if (fabsf(du[i]) > mdu) mdu = fabsf(du[i]);
                if (fabsf(dv[i]) > mdv) mdv = fabsf(dv[i]);
            }
            report->mask_frac = (float)nmask / gn;
            report->max_du = mdu;
            report->max_dv = mdv;
            report->mean_abs_delta = (float)(acc / (3.0 * n));
            report->changed = acc > 0;
        }
    }
    ok = 0;

done:
    free(R); free(G); free(B); free(u); free(v); free(L);
    free(t1); free(t2); free(t3); free(t4);
    free(u2); free(v2); free(du); free(dv); free(aw); free(aw2);
    free(uh); free(vh); free(ruf); free(rvf);
    free(kug); free(kvg); free(ex0); free(ey0);
    free(fi); free(fj);
    free(dead); free(weak); free(mask); free(m1); free(m2);
    free(EX); free(EY); free(gsat); free(dwbuf);
    free(ctw); free(cth); free(gx); free(gy); free(ptmp);
    free(ufull); free(vfull); free(Lfull); free(Wg);
    free(fa); free(fb); free(fc); free(fd);
    free(fe); free(ff); free(fg); free(fh);
    free(isat);
    return ok;
}
