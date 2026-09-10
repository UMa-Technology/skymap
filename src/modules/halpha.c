/* Stellarium Web Engine - Copyright (c) 2022 - Stellarium Labs SRL
 *
 * This program is licensed under the terms of the GNU AGPL v3, or
 * alternatively under a commercial licence.
 *
 * The terms of the AGPL v3 license can be found in the main directory of this
 * repository.
 */

#include "swe.h"

// Hα narrow-band sky-survey overlay.
//
// A near-clone of dss.c: a thin wrapper around a single HiPS survey, with the
// generic tile loading/rendering living in hips.c. The survey is a monochrome
// narrow-band Hα mosaic (MDW in the north; WHAM in the south, added later),
// star-removed so it composites cleanly over the engine's own star field.
//
// Two display modes, selected by the `red` property: a deep-red tint matching
// the ~656nm Hα line, or a neutral grayscale like the optical DSS. The layer is
// independent of dss.c, so both can be shown at once (narrow-band over optical),
// and it is hidden by default (an opt-in overlay).

typedef struct halpha {
    obj_t       obj;
    fader_t     visible;
    hips_t      *hips;
    bool        red;        // true: deep-red Hα tint; false: neutral grayscale.
} halpha_t;

static int halpha_init(obj_t *obj, json_value *args)
{
    halpha_t *ha = (void*)obj;
    fader_init(&ha->visible, false); // Opt-in overlay: hidden by default.
    ha->red = true;                  // Deep-red Hα look by default.
    return 0;
}

static int halpha_render(obj_t *obj, const painter_t *painter)
{
    double visibility;
    const halpha_t *ha = (const halpha_t*)obj;
    painter_t painter2 = *painter;
    double lum, c, sep;
    int render_order, split_order;

    if (ha->visible.value == 0.0) return 0;
    if (!ha->hips) return 0;

    // Only show the survey once zoomed in enough for framing (hidden >= 30 deg,
    // fully shown <= 27 deg); wide fields skip it to save fill-rate.
    visibility = smoothstep(30 * DD2R, 27 * DD2R, core->fov);
    painter2.color[3] *= ha->visible.value;

    // Deep-red Hα tint on the monochrome survey. This is a constant hue (a flat
    // colour multiply can't desaturate per-pixel), so keep green/blue high
    // enough that bright cores read as a warm scarlet carrying luminance detail,
    // rather than clipping to a flat, saturated "dead" red. Neutral mode leaves
    // the colour white so it renders like the optical DSS.
    if (ha->red) {
        painter2.color[1] *= 0.30;
        painter2.color[2] *= 0.20;
    }

    // Match the DSS brightness model (eye adaptation + Bortle) so the overlay
    // sits at a comparable exposure to the optical survey.
    lum = 0.02;
    lum *= core->telescope.light_grasp;
    lum /= pow(core->telescope.magnification, 2);
    c = tonemapper_map(&core->tonemapper, lum);
    c *= 1.0 / (6.0 / 8.0) * (9.0 - core->bortle_index) / 8.0;
    c = fmax(0, c);
    c *= visibility;
    c = fmin(c, 1.2);

    vec4_mul(c, painter2.color, painter2.color);

    // Not bright enough to draw yet: warm the tiles instead, so the layer
    // fades in without a blank flash. The survey is bundled/same-origin (see
    // the matching hips_set_no_delay() below), so prefetching costs nothing
    // extra; once the layer actually renders, hips_render does the identical
    // traversal itself, so prefetching then would only double the work.
    if (painter2.color[3] < 3.0 / 255) {
        if (core->fov < 40 * DD2R)
            hips_prefetch(ha->hips, painter);
        return 0;
    }

    // Tessellate each HEALPix cell finely enough that the flat-quad
    // approximation of the curved cell is accurate and, crucially, CONSISTENT
    // across render-order changes. dss.c's heuristic collapses to split=1 (a
    // single quad per cell) at mid latitudes; that quad's interior mis-maps by a
    // different amount at each order, so the image visibly JUMPS when the render
    // order switches (e.g. Norder4->5 near ~7 deg FOV). DSS never shows this
    // because it caps at order 4 and never refines; this layer goes to order 7.
    // Force >= 8x8 subdivision per cell (more near the poles, where cells are
    // most distorted) so every order converges to the same true position.
    sep = fmin(vec3_sep(painter->clip_info[FRAME_ICRF].bounding_cap,
                      VEC(0, 0, +1)),
               vec3_sep(painter->clip_info[FRAME_ICRF].bounding_cap,
                      VEC(0, 0, -1)));
    split_order = mix(12, 4, clamp(sep / (40 * DD2R), 0, 1));

    // Use the survey-clamped order: past the survey's max order the rendered
    // tiles stop refining, so an unclamped base would keep doubling the split
    // per zoom octave (uint16 vertex-index wrap, then OOM-sized grids).
    render_order = hips_get_render_order_clamped(ha->hips, painter);
    split_order = fmax(split_order, render_order + 3);
    split_order = fmin(split_order, render_order + 4);

    hips_render(ha->hips, &painter2, NULL, split_order);
    return 0;
}

static int halpha_update(obj_t *obj, double dt)
{
    halpha_t *ha = (halpha_t*)obj;
    return fader_update(&ha->visible, dt);
}

static int halpha_add_data_source(obj_t *obj, const char *url, const char *key)
{
    halpha_t *ha = (halpha_t*)obj;
    hips_delete(ha->hips);
    ha->hips = hips_create(url, 0, NULL);
    // Bundled/same-origin survey: skip the per-tile download delay (it only adds
    // a visible blank as the layer fades in, with no remote server to protect).
    hips_set_no_delay(ha->hips, true);
    return 0;
}

/*
 * Meta class declarations.
 */

static obj_klass_t halpha_klass = {
    .id = "halpha",
    .size = sizeof(halpha_t),
    .flags = OBJ_IN_JSON_TREE | OBJ_MODULE,
    .init = halpha_init,
    .update = halpha_update,
    .render = halpha_render,
    .render_order = 6,
    .add_data_source = halpha_add_data_source,
    .attributes = (attribute_t[]) {
        PROPERTY(visible, TYPE_BOOL, MEMBER(halpha_t, visible.target)),
        PROPERTY(red, TYPE_BOOL, MEMBER(halpha_t, red)),
        {}
    },
};
OBJ_REGISTER(halpha_klass)
