// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

// 构图圆环的几何与角度换算（纯函数，组件只管画和收手势）。
// 角度约定：PA 北向东为正；屏幕方位 = 从正上方起顺时针的度数。
// 星图上东在屏幕左侧，PA 增大是屏幕逆时针，所以 屏幕方位 = angleToNorth − PA。
// 标签显示 Δ = 当前 − 目标：正数 = 框比相机顺时针多转了 Δ（宿主需求文档业务规则 9）。

export const RING_MARGIN = 28 // 标签半高 16 + 离屏边 12
export const RING_MAX_R = 240 // 平板封顶，再大单手拖不过来
export const HIT_BAND = 22 // 圆环带热区：R ± 22

export function ringRadius (w, h) {
  return Math.min(Math.min(w, h) / 2 - RING_MARGIN, RING_MAX_R)
}

export function norm360 (a) {
  return ((a % 360) + 360) % 360
}

// (−180, 180]，不按画幅 180° 对称折叠：标签上的数就是旋转器要转的量
export function displayDelta (currentPa, targetPa) {
  let d = norm360(currentPa - targetPa)
  if (d > 180) d -= 360
  return Math.round(d)
}

export function deltaLabel (d) {
  if (Math.abs(d) <= 1) return '0°'
  return (d > 0 ? '+' : '−') + Math.abs(d) + '°'
}

// 目标入口（App 从序列目标进星图构图）：标签显示目标角度本身，0–359，不显示差值
export function absoluteAngleLabel (pa) {
  return `${Math.round(norm360(pa)) % 360}°`
}

export function screenAngleOfPa (angleToNorth, pa) {
  return angleToNorth - pa
}

// 标签沿切线倾斜；落到下半圈（|角| > 90）再转 180°，文字永远正着读
export function tagTextRotation (screenAngle) {
  let r = norm360(screenAngle)
  if (r > 180) r -= 360
  if (r > 90) r -= 180
  else if (r < -90) r += 180
  return r
}

export function pointerBearing (x, y, cx, cy) {
  return Math.atan2(x - cx, -(y - cy)) * 180 / Math.PI
}

export function bearingDelta (a, b) {
  let d = norm360(b - a)
  if (d > 180) d -= 360
  return d
}

export function onRingBand (x, y, cx, cy, r) {
  return Math.abs(Math.hypot(x - cx, y - cy) - r) <= HIT_BAND
}

export function pointOnRing (cx, cy, r, bearing) {
  const t = bearing * Math.PI / 180
  return [cx + r * Math.sin(t), cy - r * Math.cos(t)]
}
