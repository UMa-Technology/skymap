/* Stellarium Web Engine - Copyright (c) 2022 - Stellarium Labs SRL
 *
 * This program is licensed under the terms of the GNU AGPL v3, or
 * alternatively under a commercial licence.
 *
 * The terms of the AGPL v3 license can be found in the main directory of this
 * repository.
 */

/*
 * Module that handles the movements from mouse and keyboard inputs
 * Should this be renamed to navigation?
 */

#include "swe.h"

/* —— 惯性阻尼参数 —— */
#define INERTIA_DAMP_K          7.0    /* 指数衰减常数 (1/s)，越大停得越快 */
#define INERTIA_START_EPS_RATIO 0.1    /* 启动阈值相对 fov 的系数 */
#define INERTIA_LINEAR_DECEL    1.0    /* 线性收尾减速度相对 fov 的系数 (1/s^2) */
#define INERTIA_MAX_DIST_RATIO  0.5    /* 单次滑行最大累计角距离相对 fov 的系数 */
#define INERTIA_BRAKE_DECEL     8.0    /* 接近距离上限时的制动减速度相对 fov 的系数 (1/s^2) */
#define INERTIA_MAX_SAMPLE_DT   0.15   /* 速度采样最大间隔 (秒) */
#define INERTIA_VEL_SMOOTH      0.6    /* 松手速度 EMA 平滑系数 */

typedef struct movements {
    obj_t           obj;
    gesture_t       gest_pan;
    gesture_t       gest_click;
    gesture_t       gest_pinch;

    /* —— 惯性阻尼状态 —— */
    bool            inertia_active;     /* 是否正在自动滑行 */
    double          velocity_yaw;       /* rad/s */
    double          velocity_pitch;     /* rad/s */
    double          inertia_dist;       /* 本次滑行累计角距离 (rad) */
    /* 速度采样：on_pan 在 GESTURE_UPDATE 时逐事件更新 */
    bool            vel_sampled;        /* 本次 pan 是否已取到首个速度样本 */
    double          last_yaw;
    double          last_pitch;
    double          last_pan_time;      /* sys_get_unix_time()，秒，子帧精度 */

    /* 拖动开关：false 时 on_pan 短路、正在进行的惯性滑行立即停止，
     * 缩放（pinch / on_zoom）不受影响 */
    bool            pan_enabled;
} movements_t;


// Convert screen position to mount coordinates.
static void screen_to_mount(
        const observer_t *obs, const projection_t *proj,
        const double screen_pos[2], double p[3])
{
    double pos[4] = {screen_pos[0], screen_pos[1]};
    unproject(proj, pos, pos);
    vec3_normalize(pos, pos);
    convert_frame(obs, FRAME_VIEW, FRAME_MOUNT, true, pos, p);
}


static int on_pan(const gesture_t *gest, void *user)
{
    movements_t *movs = user;
    double sal, saz, dal, daz;
    double pos[3];
    static double start_pos[3];
    projection_t proj;
    double now, sample_dt;

    if (!movs->pan_enabled) return 0;

    core_get_proj(&proj);
    screen_to_mount(core->observer, &proj, gest->pos, pos);
    if (gest->state == GESTURE_BEGIN)
        /* 基准取手指最初按下点(start_pos)，BEGIN 帧即把越过拖动死区的
         * 那段位移补上，消除起手延迟、让星图立刻咬住手指。 */
        screen_to_mount(core->observer, &proj, gest->start_pos[0], start_pos);

    vec3_to_sphe(start_pos, &saz, &sal);
    vec3_to_sphe(pos, &daz, &dal);
    core->observer->yaw += (saz - daz);
    core->observer->pitch += (sal - dal);
    core->observer->pitch = clamp(core->observer->pitch, -M_PI / 2, +M_PI / 2);

    obj_set_attr(&core->obj, "lock", NULL);
    observer_update(core->observer, true);

    /* —— 速度采样 ——
     * 用 sys_get_unix_time() 取逐事件时间戳：core->clock 每帧只更新一次，
     * 而触摸事件在两帧间成批派发，全部读到同一 core->clock，会让 sample_dt=0
     * 把速度判 0，惯性永远启动不了。 */
    now = sys_get_unix_time();
    if (gest->state == GESTURE_BEGIN) {
        /* 新 pan 开始：清惯性、重置采样基线 */
        movs->inertia_active = false;
        movs->velocity_yaw = 0;
        movs->velocity_pitch = 0;
        movs->vel_sampled = false;
        movs->last_yaw = core->observer->yaw;
        movs->last_pitch = core->observer->pitch;
        movs->last_pan_time = now;
    } else if (gest->state == GESTURE_UPDATE) {
        /* 仅 UPDATE 采样：抬手(END)那一下没有位移，重算只会把速度冲成 0 */
        sample_dt = now - movs->last_pan_time;
        if (sample_dt > 1e-4) {
            if (sample_dt < INERTIA_MAX_SAMPLE_DT) {
                /* Unwrap the yaw delta to the shortest signed angle: yaw jumps
                 * by ~2π when the pan crosses the azimuth seam (due south) or
                 * passes over the zenith, which would otherwise spike the
                 * sampled velocity and fling the view in a random direction. */
                double inst_yaw =
                    eraAnpm(core->observer->yaw - movs->last_yaw) / sample_dt;
                double inst_pitch =
                    (core->observer->pitch - movs->last_pitch) / sample_dt;
                if (!movs->vel_sampled) {
                    /* 首个样本直接播种，避免 EMA 冷启动低估快速甩动 */
                    movs->velocity_yaw = inst_yaw;
                    movs->velocity_pitch = inst_pitch;
                    movs->vel_sampled = true;
                } else {
                    movs->velocity_yaw = INERTIA_VEL_SMOOTH * inst_yaw +
                        (1 - INERTIA_VEL_SMOOTH) * movs->velocity_yaw;
                    movs->velocity_pitch = INERTIA_VEL_SMOOTH * inst_pitch +
                        (1 - INERTIA_VEL_SMOOTH) * movs->velocity_pitch;
                }
            } else {
                /* 移动间隔过长（中途停顿）：丢弃旧速度，等待重新采样 */
                movs->velocity_yaw = 0;
                movs->velocity_pitch = 0;
                movs->vel_sampled = false;
            }
            movs->last_yaw = core->observer->yaw;
            movs->last_pitch = core->observer->pitch;
            movs->last_pan_time = now;
        }
    }

    /* —— GESTURE_END 时决定是否启动惯性 —— */
    if (gest->state == GESTURE_END) {
        double idle = now - movs->last_pan_time;   /* 距最后一次移动的时间 */
        double v2 = movs->velocity_yaw * movs->velocity_yaw +
                    movs->velocity_pitch * movs->velocity_pitch;
        double start_eps = INERTIA_START_EPS_RATIO * core->fov;
        bool second_finger = core->inputs.touches[1].id != 0;
        if (movs->vel_sampled && idle < INERTIA_MAX_SAMPLE_DT &&
            v2 > start_eps * start_eps && !second_finger) {
            movs->inertia_active = true;
            movs->inertia_dist = 0;
        } else {
            movs->inertia_active = false;
            movs->velocity_yaw = 0;
            movs->velocity_pitch = 0;
        }
    }

    /* Notify the changes. */
    module_changed(&core->observer->obj, "pitch");
    module_changed(&core->observer->obj, "yaw");
    return 0;
}

static int on_click(const gesture_t *gest, void *user)
{
    obj_t *obj;
    bool r = false;
    if (core->on_click)
        r = core->on_click(gest->pos[0], gest->pos[1]);
    // Default behavior: select an object.
    if (!r) {
        obj = core_get_obj_at(gest->pos[0], gest->pos[1], 18);
        obj_set_attr(&core->obj, "selection", obj);
        obj_release(obj);
    }
    core->clicks++;
    module_changed((obj_t*)core, "clicks");
    return 0;
}

static int on_pinch(const gesture_t *gest, void *user)
{
    movements_t *movs = user;
    static double start_fov = 0;
    projection_t proj;
    if (gest->state == GESTURE_BEGIN) {
        start_fov = core->fov;
        /* pinch 开始：清零正在进行的惯性 */
        movs->inertia_active = false;
        movs->velocity_yaw = 0;
        movs->velocity_pitch = 0;
    }
    core->fov = start_fov / gest->pinch;
    core_get_proj(&proj);
    core->fov = clamp(core->fov, proj.klass->min_ui_fov ?: CORE_MIN_FOV,
                      proj.klass->max_ui_fov);
    module_changed((obj_t*)core, "fov");
    return 0;
}

static int movements_init(obj_t *obj, json_value *args)
{
    movements_t *movs = (void*)obj;
    movs->pan_enabled = true;
    movs->gest_pan = (gesture_t) {
        .type = GESTURE_PAN,
        .callback = on_pan,
    };
    movs->gest_click = (gesture_t) {
        .type = GESTURE_CLICK,
        .callback = on_click,
    };
    movs->gest_pinch = (gesture_t) {
        .type = GESTURE_PINCH,
        .callback = on_pinch,
    };
    return 0;
}

static int get_touch_index(int id)
{
    int i;
    assert(id != 0);
    for (i = 0; i < ARRAY_SIZE(core->inputs.touches); i++) {
        if (core->inputs.touches[i].id == id) return i;
    }
    // Create new touch.
    for (i = 0; i < ARRAY_SIZE(core->inputs.touches); i++) {
        if (!core->inputs.touches[i].id) {
            core->inputs.touches[i].id = id;
            return i;
        }
    }
    return -1; // No more space.
}

static int movements_on_mouse(obj_t *obj, int id, int state,
                              double x, double y, int buttons)
{
    movements_t *movs = (void*)obj;
    if (buttons != 1) return 0;
    id = get_touch_index(id + 1);
    if (id == -1) return 0;
    if (state == -1) state = core->inputs.touches[id].down[0];
    if (state == 0) core->inputs.touches[id].id = 0; // Remove.
    core->inputs.touches[id].pos[0] = x;
    core->inputs.touches[id].pos[1] = y;
    core->inputs.touches[id].down[0] = state == 1;
    if (core->gui_want_capture_mouse) return 0;
    gesture_t *gs[] = {&movs->gest_pan, &movs->gest_pinch, &movs->gest_click};
    gesture_on_mouse(3, gs, id, state, x, y, movs);
    return 0;
}

static int movements_on_zoom(obj_t *obj, double k, double x, double y)
{
    double fov, pos_start[3], pos_end[3];
    double sal, saz, dal, daz;
    projection_t proj;

    core_get_proj(&proj);
    screen_to_mount(core->observer, &proj, VEC(x, y), pos_start);
    obj_get_attr(&core->obj, "fov", &fov);
    fov /= k;
    fov = clamp(fov, proj.klass->min_ui_fov ?: CORE_MIN_FOV,
                proj.klass->max_ui_fov);
    obj_set_attr(&core->obj, "fov", fov);
    core_get_proj(&proj);
    screen_to_mount(core->observer, &proj, VEC(x, y), pos_end);

    // Adjust lat/az to keep the mouse point at the same position.
    vec3_to_sphe(pos_start, &saz, &sal);
    vec3_to_sphe(pos_end, &daz, &dal);
    core->observer->yaw += (saz - daz);
    core->observer->pitch += (sal - dal);
    core->observer->pitch = clamp(core->observer->pitch, -M_PI / 2, +M_PI / 2);

    // Notify the changes.
    module_changed(&core->observer->obj, "pitch");
    module_changed(&core->observer->obj, "yaw");
    return 0;
}

static int movements_update(obj_t *obj, double dt)
{
    movements_t *movs = (void*)obj;
    const double ZOOM_FACTOR = 1.05;
    const double MOVE_SPEED  = 1 * DD2R;

    /* —— 惯性阻尼推进 —— */
    if (movs->inertia_active) {
        /* 退出守卫：拖动被禁用 / lock / 动画时让位，正在滑行的惯性立即停止 */
        if (!movs->pan_enabled ||
                core->target.lock || core->target.src_time != 0) {
            movs->inertia_active = false;
            movs->velocity_yaw = 0;
            movs->velocity_pitch = 0;
        } else {
            double decay, speed, lin, dyaw, dpitch;

            /* a. yaw / pitch 推进，并累计已滑行角距离 */
            dyaw   = movs->velocity_yaw   * dt;
            dpitch = movs->velocity_pitch * dt;
            core->observer->yaw   += dyaw;
            core->observer->pitch += dpitch;
            movs->inertia_dist += sqrt(dyaw * dyaw + dpitch * dpitch);

            /* b. pitch clamp，撞顶/底清零对应轴 */
            if (core->observer->pitch >  M_PI / 2) {
                core->observer->pitch =  M_PI / 2;
                movs->velocity_pitch = 0;
            }
            if (core->observer->pitch < -M_PI / 2) {
                core->observer->pitch = -M_PI / 2;
                movs->velocity_pitch = 0;
            }

            /* c. 指数衰减：高速段快速收速 */
            decay = exp(-INERTIA_DAMP_K * dt);
            movs->velocity_yaw   *= decay;
            movs->velocity_pitch *= decay;

            /* d. 线性收尾：低速段匀减速到 0，消除指数长尾末端的
             *    "慢速漂移 + 突停"卡顿，让停止平滑 */
            speed = sqrt(movs->velocity_yaw   * movs->velocity_yaw +
                         movs->velocity_pitch * movs->velocity_pitch);
            lin = INERTIA_LINEAR_DECEL * core->fov * dt;
            if (speed <= lin) {
                movs->inertia_active = false;
                movs->velocity_yaw = 0;
                movs->velocity_pitch = 0;
            } else {
                double scale = (speed - lin) / speed;
                movs->velocity_yaw   *= scale;
                movs->velocity_pitch *= scale;
            }

            /* e. 滑行距离软着陆：接近上限时按匀减速曲线
             *    v_allow = sqrt(2 * a * remain) 限制速度，剩余距离越小允许
             *    速度越低，到上限处速度恰好归零，平滑停止而非硬停。 */
            {
                double remain = INERTIA_MAX_DIST_RATIO * core->fov -
                                movs->inertia_dist;
                if (remain <= 0) {
                    movs->inertia_active = false;
                    movs->velocity_yaw = 0;
                    movs->velocity_pitch = 0;
                } else {
                    double v_allow = sqrt(2 * INERTIA_BRAKE_DECEL *
                                          core->fov * remain);
                    speed = sqrt(movs->velocity_yaw * movs->velocity_yaw +
                                 movs->velocity_pitch * movs->velocity_pitch);
                    if (speed > v_allow && speed > 1e-9) {
                        double scale = v_allow / speed;
                        movs->velocity_yaw   *= scale;
                        movs->velocity_pitch *= scale;
                    }
                }
            }

            /* f. 通知变更 */
            module_changed(&core->observer->obj, "yaw");
            module_changed(&core->observer->obj, "pitch");
        }
    }

    /* —— 原有键盘逻辑（PC 端，非本次目标但保留） —— */
    if (core->inputs.keys[KEY_RIGHT])
        core->observer->yaw += MOVE_SPEED * core->fov;
    if (core->inputs.keys[KEY_LEFT])
        core->observer->yaw -= MOVE_SPEED * core->fov;
    if (core->inputs.keys[KEY_UP])
        core->observer->pitch += MOVE_SPEED * core->fov;
    if (core->inputs.keys[KEY_DOWN])
        core->observer->pitch -= MOVE_SPEED * core->fov;
    if (core->inputs.keys[KEY_PAGE_UP])
        core->fov /= ZOOM_FACTOR;
    if (core->inputs.keys[KEY_PAGE_DOWN])
        core->fov *= ZOOM_FACTOR;
    return 0;
}

/*
 * Meta class declarations.
 */
static obj_klass_t movements_klass = {
    .id             = "movements",
    .size           = sizeof(movements_t),
    .flags          = OBJ_IN_JSON_TREE | OBJ_MODULE,
    .init           = movements_init,
    .on_mouse       = movements_on_mouse,
    .on_zoom        = movements_on_zoom,
    .update         = movements_update,
    .render_order   = -1,
    .attributes = (attribute_t[]){
        PROPERTY(pan_enabled, TYPE_BOOL, MEMBER(movements_t, pan_enabled)),
        {}
    },
};
OBJ_REGISTER(movements_klass);
