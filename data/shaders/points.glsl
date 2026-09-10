/* Stellarium Web Engine - Copyright (c) 2022 - Stellarium Labs SRL
 *
 * This program is licensed under the terms of the GNU AGPL v3, or
 * alternatively under a commercial licence.
 *
 * The terms of the AGPL v3 license can be found in the main directory of this
 * repository.
 */

uniform lowp vec4 u_color;

// Size of the core point, not including the halo relative to the total
// size of the rendered point.
// 0 -> only halo (not supported), 1 -> no halo
uniform lowp float u_core_size;

// Strength of the additive halo/glow around bright points (0 -> no halo).
// Runtime-tunable per point batch (stars use core.star_glow_scale); lower
// values make bright stars less glary.
uniform lowp float u_glow;

varying lowp    vec4 v_color;

#ifdef VERTEX_SHADER

attribute lowp    vec4  a_color;
attribute mediump float a_size;

#ifdef IS_3D
    #include "projections.glsl"
    attribute highp   vec3  a_pos;
#else
    attribute highp   vec2  a_pos;
#endif

void main()
{
    #ifdef IS_3D
        gl_Position = proj(a_pos);
    #else
        gl_Position = vec4(a_pos, 1.0, 1.0);
    #endif

    gl_PointSize = a_size * 2.0 / u_core_size;
    v_color = a_color * u_color;
}

#endif
#ifdef FRAGMENT_SHADER

void main()
{
    mediump float dist;
    mediump float k;
    dist = 2.0 * distance(gl_PointCoord, vec2(0.5, 0.5));

    // One continuous intensity profile in units of the star radius (d = 1 at the
    // nominal core edge). A smooth colored peak (no solid disc, no white centre)
    // plus a dim, wide tail for bright stars. Because the color is constant and
    // the alpha falls off smoothly, there is no hard "ring" and no white block,
    // even on a hugely magnified bright star.
    mediump float d = dist / u_core_size;
    mediump float core = 1.0 - smoothstep(0.0, 2.0, d);
    // The glow falloff is defined in sprite units (dist), NOT core units: the
    // sprite/core ratio (points_halo) is lowered for large bodies like the
    // Sun, and a core-unit glow would get truncated by the square sprite edge
    // (visible as a square halo). Radius 0.5 of the sprite fades well within
    // it for any points_halo, so the halo stays round.
    mediump float glow = 1.0 - smoothstep(0.0, 0.6, dist);
    glow = glow * glow;
    k = core + glow * v_color.a * u_glow;

    gl_FragColor.rgb = v_color.rgb;
    gl_FragColor.a = v_color.a * clamp(k, 0.0, 1.0);
}

#endif
