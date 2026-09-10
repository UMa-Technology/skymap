/* castclean — plate colour-cast removal for sky-survey RGB imagery.
 *
 * Removes the two families of plate-level colour casts found in scanned
 * photographic sky surveys (e.g. DSS2 colour composites):
 *
 *  - "dead channel" regions: one plate is missing so a channel carries no
 *    data (typically B -> saturated orange).  The channel background is
 *    literally black while the other channels show a star field.
 *  - seam casts: straight-edged plate footprints whose colour balance is
 *    shifted (orange or blue blocks / diamonds).
 *
 * Method (documented in the internal design notes for the full derivation
 * and tuning history):
 * star-robust cell backgrounds -> opponent space (u=R-G, v=B-G) -> dead-
 * channel evidence (level + texture tests, hysteresis growth) + chroma-only
 * seam edges (chroma step without a luminance step, multiscale) -> membrane /
 * Poisson correction of the chroma fields -> luminance-preserving, guided,
 * edge-sharp application at full resolution.  Genuine colour (warm star
 * clouds, blue reflection nebulae, galaxies) is preserved by construction:
 * corrections happen only where plate evidence exists.
 *
 * The module is dependency-free C99 and operates in place on 8-bit
 * interleaved RGB.  Typical use:
 *
 *     castclean_params p;
 *     castclean_params_init(&p);
 *     p.confirmed = 1;                     // human vouched this image
 *     castclean_report rep;
 *     castclean_rgb8(pix, w, h, w * 3, &p, &rep);
 *
 * Two modes:
 *  - scan mode (confirmed=0, default): conservative.  Only regions with
 *    physics-certain dead-channel evidence are corrected, via local harmonic
 *    inpainting of the chroma fields; every other pixel is bit-untouched.
 *    Images with no evidence are left unchanged (rep.changed == 0).
 *    Safe to run blindly over a whole survey; use the report to rank
 *    candidates for human review.
 *  - confirmed mode (confirmed=1): full correction for images a human has
 *    confirmed defective: global Poisson chroma levelling across detected
 *    seam edges + dead regions, direction-aware defect growth, optional
 *    luminance seam levelling.
 */
#ifndef CASTCLEAN_H
#define CASTCLEAN_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Optional survey-wide luminance-conditioned chroma prior.  Used only to
 * weight the DC anchoring of the global Poisson solve in confirmed mode
 * (cells consistent with the prior count as "healthy").  When absent,
 * per-image robust statistics are used instead, which is adequate. */
typedef struct {
    int          nbins;    /* number of luminance bins                     */
    float        lmax;     /* luminance covered by the bins: [0, lmax]     */
    const float *med_u;    /* per-bin median of u = R-G   (nbins values)   */
    const float *mad_u;    /* per-bin MAD*1.4826 of u, >= 1                */
    const float *med_v;    /* per-bin median of v = B-G                    */
    const float *mad_v;
} castclean_prior;

typedef struct {
    /* --- general ------------------------------------------------------ */
    int   cell;            /* analysis cell size in px             (16)    */
    int   confirmed;       /* 0 = scan mode, 1 = confirmed mode    (0)     */
    float strength_floor;  /* ignore chroma deltas below this      (1.0)   */

    /* --- dead-channel (missing plate) detection ------------------------ */
    float dead_strict;     /* channel bg below this = strictly dead (1.5)  */
    float dead_abs;        /* weak level test: bg < max(dead_abs,          */
    float dead_frac;       /*                        dead_frac*G)  (2.5,   */
                           /*                                       0.08)  */
    float dead_slope;      /* weak: local slope(chan on G) below   (0.35)  */
    float dead_varmin;     /* weak: local var(G) above             (4.0)   */
    float dead_gmin;       /* G background above                   (8.0)   */
    int   detect_dead_r;   /* also auto-detect dead R              (0)     */
                           /* (off: a strict-zero R test false-positives   */
                           /*  on bright blue reflection nebulae)          */
    float weak_frac;       /* hysteresis growth: chan < weak_frac*G (0.4)  */
    float weak_u;          /* ... and u (resp. -v) above           (8.0)   */

    /* --- blue-cast repair (confirmed mode only) ------------------------- */
    int   fix_blue;        /* repair soft blue plate casts         (1)     */
                           /* NO automatic discriminator separates a soft  */
                           /* blue plate cast from genuine dim blue        */
                           /* nebulosity (e.g. Pleiades halo): set to 0    */
                           /* for images containing real blue nebulae —    */
                           /* their strongly blue pixels are then also     */
                           /* protected from chroma resynthesis.           */
    float cast_thresh;     /* blue-cast residual threshold         (2.5)   */
    float base_u_min;      /* blue-side clamps on the per-image baseline:  */
    float base_v_max;      /* healthy survey sky is never blue on average, */
                           /* so a majority-blue image cannot absorb its   */
                           /* own cast into the baseline (-1.0, +1.0;      */
                           /* set to +-1e30 to disable for other data)     */

    /* --- seam-edge detection (chroma step without luminance step) ------ */
    float seam_t1;         /* chroma gradient threshold            (6.0)   */
    float seam_ratio;      /* ... and > seam_ratio * |lum gradient| (2.0)  */
    float seam_t2;         /* unconditional chroma gradient        (18.0)  */
    int   seam_scales;     /* multiscale levels                    (3)     */

    /* --- confirmed-mode extras ----------------------------------------- */
    int   grow_iters;      /* direction-aware growth iterations    (3)     */
    float grow_thresh;     /* residual needed to grow              (4.0)   */
    int   fix_luminance;   /* level the seam luminance step too    (1)     */
    float lum_floor;       /* ignore luminance deltas below        (1.0)   */
    float lum_cap;         /* cap on the leveling step: bigger steps are   */
                           /* object luminance, not plate sky      (6.0)   */
    int   lum_reach;       /* apply within this many cells of mask (4)     */

    /* --- application ---------------------------------------------------- */
    int   guide_radius;    /* guided-filter radius at full res     (12)    */
    float guide_eps;       /* guided-filter regularisation         (36.0)  */

    const castclean_prior *prior;  /* optional, may be NULL                */
} castclean_params;

typedef struct {
    int   changed;         /* any pixel modified                            */
    float mask_frac;       /* fraction of cells in the defect mask          */
    float dead_frac;       /* fraction of cells with dead-channel evidence  */
    float max_du, max_dv;  /* largest applied chroma deltas (cell scale)    */
    float mean_abs_delta;  /* mean |output-input| over all pixels/channels  */
} castclean_report;

/* Fill *p with the tuned defaults listed above. */
void castclean_params_init(castclean_params *p);

/* Clean the image in place.
 *   rgb    : interleaved 8-bit RGB, rows separated by `stride` bytes
 *   width  : image width  in px  (>= 4*cell)
 *   height : image height in px  (>= 4*cell)
 *   stride : row stride in bytes (>= 3*width)
 *   params : NULL for defaults
 *   report : optional, may be NULL
 * Returns 0 on success, -1 on bad arguments or allocation failure. */
int castclean_rgb8(uint8_t *rgb, int width, int height, int stride,
                   const castclean_params *params, castclean_report *report);

#ifdef __cplusplus
}
#endif

#endif /* CASTCLEAN_H */
