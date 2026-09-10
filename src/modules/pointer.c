/* Stellarium Web Engine - Copyright (c) 2022 - Stellarium Labs SRL
 *
 * This program is licensed under the terms of the GNU AGPL v3, or
 * alternatively under a commercial licence.
 *
 * The terms of the AGPL v3 license can be found in the main directory of this
 * repository.
 */

#include "swe.h"

// Render a pointer around the selected object.
// This is convenient to put this as a module, because it has to be rendered
// Before the UI.

typedef struct pointer {
    obj_t           obj;
    bool            visible;
} pointer_t;

static int pointer_init(obj_t *obj, json_value *args)
{
    pointer_t *pointer = (void*)obj;
    pointer->visible = true;
    return 0;
}

static int pointer_update(obj_t *obj, double dt)
{
    const pointer_t *pointer = (const pointer_t*)obj;
    // The marker pulses/spins continuously (wall-clock driven, see render):
    // report it as a running animation (core_update return value) whenever it
    // is shown, so the render loop keeps a moderate frame rate instead of
    // freezing the marker on the static-sky tier.
    return (pointer->visible && core->selection) ? 1 : 0;
}

static int pointer_render(obj_t *obj, const painter_t *painter_)
{
    int i;
    double win_pos[2], win_size[2], angle;
    const double T = 2.0;    // Animation period.
    double r, transf[3][3];
    const pointer_t *pointer = (const pointer_t*)obj;
    obj_t *selection = core->selection;
    painter_t painter = *painter_;

    if (!pointer->visible) return 0;
    vec4_set(painter.color, 0.957, 0.506, 0.137, 1); // #F48123 (selection marker)
    if (!selection) return 0;

    // If the selection has a custom rendering method, we use it.
    if (selection->klass->render_pointer) {
        selection->klass->render_pointer(selection, &painter);
        return 0;
    }

    obj_get_2d_ellipse(selection, painter.obs, painter.proj,
                       win_pos, win_size, &angle);
    r = fmax(win_size[0], win_size[1]);
    r += 5;
    r = fmax(r, 8);
    // Pulsing "zoom" of the whole marker (breathing in/out). Stronger amplitude
    // than before (0.4 -> 3.0) for a more pronounced scale effect. Computed once
    // so all four strokes pulse together at the same radius.
    r += 3.0 * (sin(sys_get_unix_time() / T * 2 * M_PI) + 1.1);

    // Slow clockwise rotation of the strokes around the object.
    const double spin = sys_get_unix_time() / 8.0 * 2 * M_PI;

    // Draw all four strokes around the object (no longer skip the top one).
    for (i = 0; i < 4; i++) {
        mat3_set_identity(transf);
        mat3_itranslate(transf, win_pos[0], win_pos[1]);
        mat3_rz(i * 90 * DD2R + spin, transf, transf);
        mat3_itranslate(transf, r, 0);
        mat3_iscale(transf, 9.6, 1, 1); // 1.2x the original stroke length (8)
        painter.lines.width = 3;
        paint_2d_line(&painter, transf, VEC(0, 0), VEC(1, 0));
    }
    return 0;
}

/*
 * Meta class declarations.
 */

static obj_klass_t pointer_klass = {
    .id = "pointer",
    .size = sizeof(pointer_t),
    .flags = OBJ_IN_JSON_TREE | OBJ_MODULE,
    .init = pointer_init,
    .update = pointer_update,
    .render = pointer_render,
    .render_order = 199, // Just before the ui.
    .attributes = (attribute_t[]) {
        PROPERTY(visible, TYPE_BOOL, MEMBER(pointer_t, visible)),
        {}
    },
};

OBJ_REGISTER(pointer_klass)
