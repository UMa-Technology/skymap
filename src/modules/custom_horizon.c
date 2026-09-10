/* Stellarium Web Engine - Copyright (c) 2022 - Stellarium Labs SRL
 *
 * This program is licensed under the terms of the GNU AGPL v3, or
 * alternatively under a commercial licence.
 *
 * The terms of the AGPL v3 license can be found in the main directory of this
 * repository.
 */

#include "swe.h"

/*
 * Module: custom_horizon
 *
 * Renders a user-supplied per-azimuth horizon silhouette (the "custom horizon"
 * from the companion app) as a translucent fill from the true horizon (alt 0)
 * up to the ridge, plus a ridge outline.
 *
 * The ridge is supplied from JS as an array of altitudes (degrees) sampled at
 * uniform azimuths (az_i = i / count * 360); it is interpolated on the fly.
 *
 * RENDERING STRATEGY (learned the hard way; do not "simplify"):
 *
 * The fill is drawn as a grid of SMALL azimuth x altitude TILES, each a
 * paint_quad in FRAME_OBSERVED_GEOM — the engine's own tile-and-cull pattern
 * (like HiPS surveys), NOT one sky-spanning primitive:
 *
 * - geojson/paint_mesh cannot draw this: paint_mesh antimeridian-cuts any
 *   mesh whose bounding cap crosses the projection discontinuity, mangling
 *   sky-spanning fills at wide FOV.
 * - One big paint_quad cannot draw this either: the projection shaders
 *   (e.g. stereographic in projections.glsl) map directions near the VIEW
 *   ANTIPODE to huge radii with w=1 (no GL clipping), so any grid cell
 *   straddling the antipode rasterizes as a screen-crossing smear. Analytic
 *   "carve the antipode out of one quad" schemes leave discontinuous column
 *   transitions that smear the same way.
 * - With small tiles the fix is trivial: a tile whose region contains (or
 *   comes within CH_SKIP_MARGIN of) the antipode is SKIPPED. Every point of
 *   such a tile is within ~tile-diagonal of the antipode, i.e. at least
 *   180 - ~35 = 145 deg away from the view center — far beyond the widest
 *   viewport corner (~111 deg at FOV 180), so skipping is never visible.
 *   All kept tiles stay clear of the antipode, so their projection is
 *   bounded and smear-free at every FOV.
 */

// Max uniform azimuth samples of the ridge accepted from JS.
#define CH_MAX_SAMPLES 1024
// Tiling of the band: azimuth sectors x altitude rows.
#define CH_AZ_SECTORS  32                 // 11.25 deg per sector
#define CH_ALT_STEP    (30.0 * DD2R)      // rows: 0-30, 30-60, 60-90 deg
// Grid split of each tile's paint_quad. Keep small: the renderer's index
// buffers are GL_UNSIGNED_SHORT (gl_buf_1i casts to uint16_t), so a quad
// grid must keep (split+1)^2 <= 65536 or indices silently wrap.
#define CH_TILE_SPLIT  16                 // 17^2 = 289 vertices per tile
// Skip tiles whose region comes within this margin of the view antipode.
#define CH_SKIP_MARGIN (4.0 * DD2R)

typedef struct custom_horizon {
    obj_t       obj;
    fader_t     visible;
    double      ridge[CH_MAX_SAMPLES];  // ridge altitude (radians), by azimuth
    int         count;                  // number of ridge samples (0 = none)
    json_value  *profile_json;          // raw copy of the last set, for the getter
    double      fill_color[4];          // RGBA
    double      line_color[4];          // RGBA
} custom_horizon_t;

// Interpolated ridge altitude (radians) at an azimuth (radians), with wrap.
static double ridge_at(const custom_horizon_t *ch, double az)
{
    double x, f;
    int i0, i1;
    az = fmod(az, 2 * M_PI);
    if (az < 0) az += 2 * M_PI;
    x = az / (2 * M_PI) * ch->count;
    i0 = ((int)floor(x)) % ch->count;
    i1 = (i0 + 1) % ch->count;
    f = x - floor(x);
    return ch->ridge[i0] * (1 - f) + ch->ridge[i1] * f;
}

/*
 * One tile of the band. The tile spans azimuths [a0, a1]; the fill spans
 * altitudes [t0, min(ridge(az), t1)] (degenerate where the ridge dips below
 * t0). Contour tiles (ridge_top) span [0, ridge(az)] so their v=1 edge is
 * the ridge line itself.
 */
typedef struct {
    const custom_horizon_t *ch;
    double a0, a1;      // azimuth range (radians)
    double t0, t1;      // altitude range (radians)
    bool   ridge_top;   // contour variant: v=1 follows the ridge
} ch_tile_t;

static void tile_map(const uv_map_t *map, const double v[2], double out[4])
{
    const ch_tile_t *t = map->user;
    // Azimuth runs BACKWARD with u: FRAME_OBSERVED_GEOM is left-handed (see
    // circle.c's right_handed flip), so a forward-azimuth grid winds its
    // triangles clockwise on screen and GL_CULL_FACE culls the whole fill.
    double az = t->a1 - v[0] * (t->a1 - t->a0);
    double ridge = ridge_at(t->ch, az);
    double lo, hi, alt;
    if (t->ridge_top) {
        lo = 0.0;
        hi = ridge;
    } else {
        lo = t->t0;
        hi = fmax(fmin(ridge, t->t1), t->t0);
    }
    alt = lo + v[1] * (hi - lo);
    vec3_from_sphe(az, alt, out); // FRAME_OBSERVED_GEOM basis: X=N, Y=E, Z=up
    out[3] = 0.0;                 // direction at infinity, like the ground
}

// Conservative bounding cap of a tile region (corners + 5 deg padding).
static void tile_cap(const ch_tile_t *t, double top, double cap[4])
{
    double pts[4][3];
    int i;
    double d, ang;
    vec3_from_sphe(t->a0, t->t0, pts[0]);
    vec3_from_sphe(t->a1, t->t0, pts[1]);
    vec3_from_sphe(t->a0, top, pts[2]);
    vec3_from_sphe(t->a1, top, pts[3]);
    vec4_set(cap, 0, 0, 0, 1);
    for (i = 0; i < 4; i++) vec3_add(cap, pts[i], cap);
    vec3_normalize(cap, cap);
    cap[3] = 1.0;
    for (i = 0; i < 4; i++) {
        d = vec3_dot(cap, pts[i]);
        if (d < cap[3]) cap[3] = d;
    }
    ang = acos(fmin(1.0, fmax(-1.0, cap[3]))) + 5.0 * DD2R;
    cap[3] = ang >= M_PI ? -1.0 : cos(ang);
}

static int custom_horizon_init(obj_t *obj, json_value *args)
{
    custom_horizon_t *ch = (void*)obj;
    fader_init(&ch->visible, false); // hidden until shown
    vec4_set(ch->fill_color, 0xF4 / 255.0, 0x81 / 255.0, 0x23 / 255.0, 0.05);
    vec4_set(ch->line_color, 0xF4 / 255.0, 0x81 / 255.0, 0x23 / 255.0, 0.10);
    return 0;
}

static void custom_horizon_del(obj_t *obj)
{
    custom_horizon_t *ch = (void*)obj;
    if (ch->profile_json) json_value_free(ch->profile_json);
}

static int custom_horizon_update(obj_t *obj, double dt)
{
    custom_horizon_t *ch = (void*)obj;
    return fader_update(&ch->visible, dt);
}

/*
 * Attribute: profile
 * Settable array of ridge altitudes (degrees) at uniform azimuths
 * (az_i = i / n * 360). Passing an empty array clears it. Modeled on
 * geojson.c's data_fn: NULL args = get, an array = set.
 */
static json_value *profile_fn(obj_t *obj, const attribute_t *attr,
                              const json_value *args)
{
    custom_horizon_t *ch = (void*)obj;
    int i, n;
    if (!args) {
        // get. Must NEVER return NULL: module_get_tree_json pushes the returned
        // value verbatim into the json tree, and a NULL value serializes as a
        // missing value ("profile":,) which breaks JSON.parse in getTree() and
        // aborts the whole frontend engine init. Return [] when unset.
        return ch->profile_json ? json_copy(ch->profile_json)
                                : json_array_new(0);
    }
    // set (an array; empty => clear)
    if (ch->profile_json) { json_value_free(ch->profile_json); ch->profile_json = NULL; }
    ch->count = 0;
    if (args->type == json_array && args->u.array.length) {
        int src_len = args->u.array.length;
        ch->profile_json = json_copy(args);
        // The renderer interprets ridge[i] as the altitude at azimuth
        // i/count*360, so a horizon with more than CH_MAX_SAMPLES points must
        // be UNIFORMLY downsampled across the whole circle — naively keeping
        // the first CH_MAX_SAMPLES would stretch a fraction of the azimuths
        // over the full 360°.
        n = src_len > CH_MAX_SAMPLES ? CH_MAX_SAMPLES : src_len;
        for (i = 0; i < n; i++) {
            // Maps [0,n) uniformly onto [0,src_len); equals i when n == src_len.
            int j = (int)((int64_t)i * src_len / n);
            const json_value *a = args->u.array.values[j];
            double alt = a->type == json_double  ? a->u.dbl :
                         a->type == json_integer ? (double)a->u.integer : 0.0;
            ch->ridge[i] = fmin(90.0, fmax(0.0, alt)) * DD2R;
        }
        ch->count = n;
    }
    module_changed(obj, "profile");
    return NULL;
}

static int custom_horizon_render(obj_t *obj, const painter_t *painter_)
{
    custom_horizon_t *ch = (void*)obj;
    painter_t painter = *painter_;
    double view_dir[4] = {0, 0, -1, 0}; // view center in FRAME_VIEW
    double antipode[3];
    double a0, a1, ridge_max, ridge_min, t0, t1, top, cap[4], ang;
    double fill[4], line[4];
    int s, i, i0, i1;

    if (ch->visible.value <= 0 || ch->count < 2) return 0;

    // Locate the view antipode in the alt/az frame (see the header comment).
    convert_frame(painter.obs, FRAME_VIEW, FRAME_OBSERVED_GEOM, true,
                  view_dir, view_dir);
    vec3_mul(-1, view_dir, antipode);

    vec4_emul(painter_->color, ch->fill_color, fill);
    fill[3] *= ch->visible.value;
    vec4_emul(painter_->color, ch->line_color, line);
    line[3] *= ch->visible.value;

    for (s = 0; s < CH_AZ_SECTORS; s++) {
        a0 = s * 2 * M_PI / CH_AZ_SECTORS;
        a1 = (s + 1) * 2 * M_PI / CH_AZ_SECTORS;

        // Ridge altitude range over the sector (scan the covered samples).
        i0 = (int)floor(a0 / (2 * M_PI) * ch->count);
        i1 = (int)ceil(a1 / (2 * M_PI) * ch->count);
        ridge_max = 0;
        ridge_min = M_PI_2;
        for (i = i0; i <= i1; i++) {
            ridge_max = fmax(ridge_max, ch->ridge[i % ch->count]);
            ridge_min = fmin(ridge_min, ch->ridge[i % ch->count]);
        }
        if (ridge_max <= 0) continue; // no obstruction in this sector

        // Fill tiles.
        for (t0 = 0; t0 < ridge_max; t0 += CH_ALT_STEP) {
            t1 = t0 + CH_ALT_STEP;
            top = fmin(t1, ridge_max);
            ch_tile_t tile = { ch, a0, a1, t0, t1, false };
            uv_map_t map = { .map = tile_map, .user = &tile };
            tile_cap(&tile, top, cap);
            // Skip tiles containing/near the antipode (3D test against the
            // tile's bounding cap): such tiles are entirely outside any
            // possible viewport, and drawing them would smear (see header).
            ang = acos(fmin(1.0, fmax(-1.0, cap[3])));
            if (vec3_dot(cap, antipode) >=
                    cos(fmin(M_PI, ang + CH_SKIP_MARGIN)))
                continue;
            if (painter_is_cap_clipped(&painter, FRAME_OBSERVED_GEOM, cap))
                continue;
            vec4_copy(fill, painter.color);
            paint_quad(&painter, FRAME_OBSERVED_GEOM, &map, CH_TILE_SPLIT);
        }

        // Ridge outline piece for this sector (the v=1 edge of a ridge_top
        // tile). Its bounding cap only needs to cover the ridge curve
        // [ridge_min, ridge_max]; skipped near the antipode like the fill.
        ch_tile_t rtile = { ch, a0, a1, ridge_min, ridge_max, true };
        uv_map_t rmap = { .map = tile_map, .user = &rtile };
        tile_cap(&rtile, ridge_max, cap);
        ang = acos(fmin(1.0, fmax(-1.0, cap[3])));
        if (vec3_dot(cap, antipode) >= cos(fmin(M_PI, ang + CH_SKIP_MARGIN)))
            continue;
        if (painter_is_cap_clipped(&painter, FRAME_OBSERVED_GEOM, cap))
            continue;
        vec4_copy(line, painter.color);
        painter.lines.width = 2;
        paint_quad_contour(&painter, FRAME_OBSERVED_GEOM, &rmap,
                           CH_TILE_SPLIT, 1 << 2);
    }
    return 0;
}

static obj_klass_t custom_horizon_klass = {
    .id           = "customhorizon", // -> stel.core.customhorizon (hyphen-free)
    .size         = sizeof(custom_horizon_t),
    .flags        = OBJ_IN_JSON_TREE | OBJ_MODULE,
    .init         = custom_horizon_init,
    .del          = custom_horizon_del,
    .update       = custom_horizon_update,
    .render       = custom_horizon_render,
    .render_order = 45, // after landscape(40)/atmosphere(35), before cardinal(50)
    .attributes   = (attribute_t[]) {
        PROPERTY(visible, TYPE_BOOL, MEMBER(custom_horizon_t, visible.target)),
        PROPERTY(profile, TYPE_JSON, .fn = profile_fn),
        PROPERTY(color, TYPE_COLOR, MEMBER(custom_horizon_t, fill_color)),
        PROPERTY(line_color, TYPE_COLOR, MEMBER(custom_horizon_t, line_color)),
        {},
    },
};
OBJ_REGISTER(custom_horizon_klass)
