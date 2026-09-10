/* Stellarium Web Engine - Copyright (c) 2022 - Stellarium Labs SRL
 *
 * This program is licensed under the terms of the GNU AGPL v3, or
 * alternatively under a commercial licence.
 *
 * The terms of the AGPL v3 license can be found in the main directory of this
 * repository.
 */

#include "swe.h"

// Support embedding online photos in the sky.

typedef struct photo {
    obj_t       obj;
    texture_t   *img;
    fader_t     visible;
    // Steady per-photo opacity in [0, 1], multiplied on top of the visible
    // fader.  Set by the host; defaults to 1 (a 0-init photo would be hidden).
    double      opacity;
    // Mirror parity (astrometry "flipped"): reflect the image X axis and negate
    // the orientation so the overlay isn't left-right mirrored on the sky.
    bool        flipped;
    // Only render the shape if set.
    // Note: we could have more control, like rendering both the pic and
    // the shape at the same time.
    bool        render_shape;

    // calibration value as returned by astrometry.net api, but with the
    // units changed to rad.
    struct {
        double orientation;
        double pixscale;
        double ra;
        double dec;
    } calibration;
    // Projection uv -> sphere.  Computed from the calibration data.
    double      mat[4][4];
} photo_t;


static json_value *photo_fn_url(obj_t *obj, const attribute_t *attr,
                                const json_value *args)
{
    photo_t *photo = (void*)obj;
    char url[1024];
    if (args->u.array.length) {
        texture_release(photo->img);
        args_get(args, TYPE_STRING, &url);
        // TF_MIPMAP：照片在星图上通常处于数倍缩小（minification）状态，无 mipmap 的
        // GL_LINEAR 只取 1/N 采样，图像边缘一两个像素宽的内容会随屏幕相位/旋转角
        // 整段丢失（切换观测时刻导致场旋变化时尤其明显，表现为"图片周围像素被裁剪"）。
        photo->img = texture_from_url(url, TF_MIPMAP);
    }
    if (!photo->img) return NULL;
    return args_value_new(TYPE_STRING, photo->img->url);
}

static json_value *photo_fn_calibration(obj_t *obj, const attribute_t *attr,
                                        const json_value *args)
{
    photo_t *photo = (void*)obj;
    typeof(&photo->calibration) cal = &photo->calibration;
    json_value *val;
    double orientation, pixscale, ra, dec;

    val = args->u.array.length ? args->u.array.values[0] : NULL;
    if (val) {
        orientation = json_get_attr_f(val, "orientation", 0);
        pixscale = json_get_attr_f(val, "pixscale", 0);
        ra = json_get_attr_f(val, "ra", 0);
        dec = json_get_attr_f(val, "dec", 0);
        cal->orientation = orientation * DD2R;
        cal->pixscale = pixscale / 60 / 60 * DD2R;
        cal->ra = ra * DD2R;
        cal->dec = dec * DD2R;
    }

    val = json_object_new(0);
    json_object_push(val, "orientation",
                     json_double_new(cal->orientation * DR2D));
    json_object_push(val, "pixscale",
                     json_double_new(cal->pixscale * DR2D * 60 * 60));
    json_object_push(val, "ra", json_double_new(cal->ra * DR2D));
    json_object_push(val, "dec", json_double_new(cal->dec * DR2D));
    return val;
}

// Project the [0,1]^2 image UV to a 3D direction. map->mat holds the tangent-
// plane transform (centre + angular scale + orientation); apply it FIRST, then
// gnomonic-normalize. The transf post-step (see uv_map) rotates the resulting
// local frame onto the sky (R_center). Normalizing the raw UV first — as the
// original did — puts the image centre 35° off-axis and warps the quad.
static void photo_map(const uv_map_t *map, const double v[2], double out[4])
{
    double p[3] = {v[0], v[1], 1.0};
    mat3_mul_vec3(map->mat, p, p);
    vec3_normalize(p, p);
    vec3_copy(p, out);
    out[3] = 1.0;
}

static int photo_render(obj_t *obj, const painter_t *painter)
{
     photo_t *photo = (photo_t*)obj;
    typeof(&photo->calibration) calibration = &photo->calibration;
    uv_map_t map = {};
    painter_t painter2 = *painter;

    fader_update(&photo->visible, 0.06);
    painter2.color[3] *= photo->visible.value * photo->opacity;
    if (painter2.color[3] == 0.0) return 0;

    // We can only compute the projection matrix once we get the texture?
    if (!photo->img || !texture_load(photo->img, NULL)) return 0;

    // R_center: rotate the local gnomonic frame onto the sky. Only the centre
    // RA/Dec lives here; scale + orientation go in the tangent transform below.
    if (photo->mat[3][3] == 0) {
        mat4_set_identity(photo->mat);
        mat4_rz(calibration->ra,  photo->mat, photo->mat);
        mat4_ry(90 * DD2R - calibration->dec, photo->mat, photo->mat);
        mat4_rz(-90 * DD2R, photo->mat, photo->mat);
    }

    // Tangent-plane transform applied to the UV before the gnomonic normalize
    // (see photo_map): centre the image, scale to its angular size, rotate by
    // the plate orientation.
    // Flipped plates: NEGATE the solver's angle — a mirror and a rotation do
    // not commute (Reflect∘Rotate(θ) = Rotate(−θ)∘Reflect), so the position
    // angle of a parity-flipped solution winds the opposite way through our
    // rot180-texture flip path.  Empirically calibrated on the Rosette plate:
    // with +θ every star sat ~2θ·r off (30" at r=0.3°); with −θ they coincide
    // with the engine's catalog stars to plate-solve accuracy (~4").
    mat3_set_identity(map.mat);
    mat3_rz(photo->flipped ? -calibration->orientation
                           :  calibration->orientation, map.mat, map.mat);
    mat3_iscale(map.mat, calibration->pixscale * photo->img->w,
                         calibration->pixscale * photo->img->h, 1.0);
    mat3_itranslate(map.mat, -0.5, -0.5);

    map.transf = &photo->mat;
    map.map = photo_map;

    if (!photo->render_shape) {
        // Flipped parity: remap the texture, never the geometry — a mirrored
        // quad flips its winding and gets back-face culled (invisible).
        // Empirically calibrated on the Rosette plate (astrometry "Parity:
        // Flipped"): the correct sampling is (u,v) -> (1-u, 1-v).  A U-only
        // mirror left the image correct E-W but reversed N-S (user verified
        // against star-name labels over an opaque overlay).
        // NOTE: mat3_mul_vec3 is COLUMN-major (out[i] = sum_j mat[j][i]*v[j]);
        // this is the column-major form of [[-1,0,1],[0,-1,1],[0,0,1]].  A
        // row-major literal makes tex coords negative, which CLAMP_TO_EDGE
        // smears into streaks.
        static const double uv_flip[3][3] = {{-1, 0, 0}, {0, -1, 0}, {1, 1, 1}};
        painter_set_texture(&painter2, PAINTER_TEX_COLOR, photo->img,
                            photo->flipped ? uv_flip : NULL);
        // FRAME_ASTROM, not FRAME_ICRF: the plate solve maps pixels to CATALOG
        // (astrometric) directions, and the stars module projects catalog
        // directions in FRAME_ASTROM (stars.c).  Painting in FRAME_ICRF adds a
        // spurious astrometric_to_apparent() step (annual aberration, up to
        // ~20.5"), visibly shifting the photo stars off the engine's stars.
        paint_quad(&painter2, FRAME_ASTROM, &map, 4);
    } else {
        paint_quad_contour(&painter2, FRAME_ASTROM, &map, 8, 15);
        painter2.color[3] *= 0.25;
        paint_quad(&painter2, FRAME_ASTROM, &map, 8);
    }

    return 0;
}

static int photo_init(obj_t *obj, json_value *args)
{
    photo_t *photo = (photo_t*)obj;
    // Default to fully opaque; a zero-initialised opacity would hide the photo.
    photo->opacity = 1.0;
    return 0;
}

/*
 * Meta class declarations.
 */

static obj_klass_t photo_klass = {
    .id         = "photo",
    .size       = sizeof(photo_t),
    .init       = photo_init,
    .render     = photo_render,
    .attributes = (attribute_t[]) {
        PROPERTY(visible, TYPE_BOOL, MEMBER(photo_t, visible.target)),
        PROPERTY(opacity, TYPE_FLOAT, MEMBER(photo_t, opacity)),
        PROPERTY(flipped, TYPE_BOOL, MEMBER(photo_t, flipped)),
        PROPERTY(url, TYPE_STRING_PTR, .fn = photo_fn_url),
        PROPERTY(calibration, TYPE_JSON, .fn = photo_fn_calibration),
        PROPERTY(render_shape, TYPE_BOOL, MEMBER(photo_t, render_shape)),
        // Default properties.
        PROPERTY(radec),
        {}
    },
};
OBJ_REGISTER(photo_klass)
