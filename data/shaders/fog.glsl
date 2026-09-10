/* Stellarium Web Engine - Copyright (c) 2022 - Stellarium Labs SRL
 *
 * This program is licensed under the terms of the GNU AGPL v3, or
 * alternatively under a commercial licence.
 *
 * The terms of the AGPL v3 license can be found in the main directory of this
 * repository.
 */

#ifdef GL_ES
precision mediump float;
#endif

uniform lowp    vec4        u_color;

// Interpolate the sky direction's up-component (z = sin(altitude)) and do the
// horizon falloff PER FRAGMENT. Computing the smoothstep per vertex and linearly
// interpolating it made the coarse fog tessellation show as banded facets; a
// per-pixel smoothstep is smooth regardless of tile density. highp keeps the
// interpolated ramp free of precision steps.
varying highp   float       v_sky_z;

#ifdef VERTEX_SHADER

#includes "projections.glsl"

attribute highp   vec4       a_pos;
attribute highp   vec3       a_sky_pos;

void main()
{
    gl_Position = proj(a_pos.xyz);
    v_sky_z = a_sky_pos.z;
}

#endif
#ifdef FRAGMENT_SHADER

void main()
{
    const highp float height = 0.2;   // fades out by |sin(alt)| = 0.2 (~11.5°)
    const highp float max_alpha = 0.15;
    // abs() => symmetric band straddling the horizon (z = 0).
    highp float d = smoothstep(height, 0.0, abs(v_sky_z));
    highp float a = u_color.a * max_alpha * d;
    // Ordered value-noise dither on the alpha to break up 8-bit gradient banding
    // across the large, low-opacity ramp.
    highp float dither = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233)))
                               * 43758.5453);
    a += (dither - 0.5) / 255.0;
    gl_FragColor = vec4(u_color.rgb, a);
}

#endif
