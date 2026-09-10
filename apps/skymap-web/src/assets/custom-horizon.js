// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

// Engine glue for the custom horizon silhouette.
// Drives the engine's `customhorizon` C module (which renders the fill with
// paint_quad — robust at all FOV) and exposes the window.CustomHorizon host
// bridge. Flutter (embedding webview) calls window.CustomHorizon.set/show/clear.

import { normalizeProfile, altitudeAtGreatCircle, smoothAdaptiveCircular, euclideanModulus } from './custom-horizon-geometry.js'

// Uniform azimuth samples of the ridge pushed to the engine module.
const SAMPLES = 512

// Altitude-adaptive corner rounding (degrees). Low parts of the ridge (valleys)
// are rounded with SMOOTH_MAX so gentle/obtuse corners look soft; high parts
// near the zenith are rounded with only SMOOTH_MIN so a tall apex stays sharp —
// rounding a near-zenith apex flattens it just enough to project as a spurious
// "double bump" at wide FOV. The radius ramps linearly between ALT_LO and ALT_HI.
const SMOOTH_MAX = 3
const SMOOTH_MIN = 1
const SMOOTH_ALT_LO = 40
const SMOOTH_ALT_HI = 70

function sigmaSamplesForAlt (altDeg) {
  const t = Math.min(1, Math.max(0, (altDeg - SMOOTH_ALT_LO) / (SMOOTH_ALT_HI - SMOOTH_ALT_LO)))
  const deg = SMOOTH_MAX + t * (SMOOTH_MIN - SMOOTH_MAX)
  return deg / (360 / SAMPLES)
}

let stel = null
let mod = null

// JS 侧留存的最近一次重采样廓线（度，SAMPLES 个均匀方位采样）与显示状态，
// 供 customHorizonAltAt 查询用（引擎 C 模块的 profile 属性读回代价高且格式不同）。
let lastProfile = null
let isVisible = false

function ensureModule () {
  if (mod) return mod
  if (!stel) return null
  mod = (stel.core && stel.core.customhorizon) ||
        (stel.getModule && stel.getModule('customhorizon')) || null
  return mod
}

// Resample the profile to SAMPLES altitudes (degrees) at uniform azimuths
// (az_i = i / SAMPLES * 360). The engine module interpolates between them.
// Great-circle interpolation between vertices keeps each ridge edge taut on
// the sphere — az/alt-linear segments sag visibly near the zenith.
// Returns null for an invalid profile.
function resample (profile) {
  const p = normalizeProfile(profile)
  if (!p) return null
  const out = new Array(SAMPLES)
  for (let i = 0; i < SAMPLES; i++) out[i] = altitudeAtGreatCircle(p, (i * 360) / SAMPLES)
  return smoothAdaptiveCircular(out, sigmaSamplesForAlt)
}

// profile: [[az,alt]] | [{az,alt}] | {points:[{az,alt}]}. Invalid -> cleared.
function set (profile) {
  lastProfile = resample(profile)
  if (!ensureModule()) return
  mod.profile = lastProfile || [] // empty array clears it in C
}

function show (v) {
  isVisible = !!v
  if (!ensureModule()) return
  mod.visible = isVisible
}

function clear () {
  lastProfile = null
  if (!ensureModule()) return
  mod.profile = []
}

// 当前生效的自定义地平线在方位角 azDeg（度，0=北 90=东）处的高度（度）。
// 未设置或未显示时返回 null；调用方据此回落到几何地平线判定。
export function customHorizonAltAt (azDeg) {
  if (!isVisible || !lastProfile || !lastProfile.length) return null
  const n = lastProfile.length
  const x = euclideanModulus(azDeg, 360) / 360 * n
  const i0 = Math.floor(x) % n
  const i1 = (i0 + 1) % n
  const t = x - Math.floor(x)
  return lastProfile[i0] * (1 - t) + lastProfile[i1] * t
}

// Called once from the engine onReady callback (sw_helpers.js).
export function installCustomHorizon (stelInstance) {
  stel = stelInstance
  ensureModule()
  if (typeof window !== 'undefined') {
    window.CustomHorizon = { set, show, clear }
  }
}
