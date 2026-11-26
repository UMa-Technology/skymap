// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

// 可编辑马赛克（showMosaicLayout）的纯函数：格坐标、屏幕投影正反算、手势判别。
// 网格钉在天上：锚点（网格中心）是一个天球坐标，格位在以锚点为切点的平面上按网格坐标排，
// 与 mosaic-math.js 的刚性网格同一模型（mosaicSkyOffset + tangentPlaneToRaDec）。

// 位移不超过它（CSS px）松手算点击；超过就是拖动
export const TAP_MAX_MOVE = 10
// 按住不动这么久进入单格微调（宿主开 tileEdit 才生效）
export const LONG_PRESS_MS = 400
// 格子短边小于它就不接手手势（手势回给星图），宿主提示放大后再编辑
export const MIN_HIT_PX = 44

// 格在网格坐标里的位置（单位 = 一格步距），原点是网格中心。dx / dy 是单格微调
export function gridCoord (tile, cols, rows) {
  return {
    gx: tile.col - (cols - 1) / 2 + (tile.dx || 0),
    gy: tile.row - (rows - 1) / 2 + (tile.dy || 0)
  }
}

// 引擎的屏幕投影（立体投影，同 framing-overlay.vue viewToScreen）：焦距 f = 视口高 / (4·tan(视场/4))。
// VIEW 系 -z 朝屏幕里；视线背后（z/|v| > 0.95）返回 null
export function screenFromView (v, width, height, fovYRad) {
  const n = Math.hypot(v[0], v[1], v[2])
  if (!(n > 0) || v[2] / n > 0.95) return null
  const f = height / (4 * Math.tan(fovYRad / 4))
  const k = 2 * f / (1 - v[2] / n)
  return [width / 2 + k * v[0] / n, height / 2 - k * v[1] / n]
}

// screenFromView 的反算：屏幕点 → VIEW 系单位向量。拖网格时用它把手指位置换回天球
export function viewFromScreen (sx, sy, width, height, fovYRad) {
  const f = height / (4 * Math.tan(fovYRad / 4))
  const x = (sx - width / 2) / (2 * f)
  const y = -(sy - height / 2) / (2 * f)
  const r2 = x * x + y * y
  return [2 * x / (1 + r2), 2 * y / (1 + r2), -(1 - r2) / (1 + r2)]
}

// 屏幕上的位移 → 网格坐标位移（单位 = 一格步距）。rotationDeg 是网格的屏幕角（CSS 顺时针为正）
export function screenDeltaToGrid (ddx, ddy, rotationDeg, stepXPx, stepYPx) {
  const r = rotationDeg * Math.PI / 180
  const c = Math.cos(r)
  const s = Math.sin(r)
  return {
    gx: (ddx * c + ddy * s) / stepXPx,
    gy: (-ddx * s + ddy * c) / stepYPx
  }
}

// 一个按压当前该算什么：还在判断（pending）/ 拖动（drag）
export function pressMode (moved) {
  return moved > TAP_MAX_MOVE ? 'drag' : 'pending'
}

// 格子够不够大、接不接手手势（易达性：短边 < 44 pt 点不准）
export function tileHittable (widthPx, heightPx) {
  return Math.min(widthPx, heightPx) >= MIN_HIT_PX
}

// 外接框占屏比例超过 maxFraction 时要放大视场的倍数（≤ 1 不用缩）
export function fitScale (bboxW, bboxH, width, height, maxFraction = 0.7) {
  if (!(width > 0) || !(height > 0)) return 1
  return Math.max(bboxW / (width * maxFraction), bboxH / (height * maxFraction))
}

// 单个格配置的规整：缺省字段补齐，非法值丢掉。宿主传错一格不该拖垮整个网格
export function normalizeTile (t) {
  if (!t || typeof t !== 'object' || t.key === undefined || t.key === null) return null
  const col = Number(t.col)
  const row = Number(t.row)
  if (!Number.isFinite(col) || !Number.isFinite(row)) return null
  const state = ['normal', 'selected', 'warn', 'slot'].includes(t.state) ? t.state : 'normal'
  return {
    key: String(t.key),
    col,
    row,
    dx: Number.isFinite(Number(t.dx)) ? Number(t.dx) : 0,
    dy: Number.isFinite(Number(t.dy)) ? Number(t.dy) : 0,
    enabled: state === 'slot' ? false : t.enabled !== false,
    label: t.label === undefined || t.label === null ? '' : String(t.label),
    state
  }
}
