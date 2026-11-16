// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

// 拍摄覆盖轮廓（纯函数）：一块地平坐标范围（方位跨度 × 高度上下限）的边界取样，
// 交给 framing-overlay.vue 逐点投影成屏幕路径。角度一律用度，方位自北向东。

// 从 start 到 end 等分取样，不含 end（下一条边从这里接上）
function edge (start, end, stepDeg, at) {
  const n = Math.max(1, Math.ceil(Math.abs(end - start) / stepDeg))
  const pts = []
  for (let i = 0; i < n; i++) pts.push(at(start + (end - start) * i / n))
  return pts
}

// 返回闭合环数组，每环是 [az, alt] 点列（首尾不重复）。方位不取模、保持连续，
// 跨 0° 时也不会跳回，免得投影后连出横穿全屏的线。
// azSpan ≥ 360：没有左右边，回 altMin 与 altMax 两圈（altMax ≥ 90 时只回下圈）；
// altMax ≥ 90：上缘收成天顶一点
export function coverageOutlineAltAz ({ az0, azSpan, altMin, altMax, stepDeg = 2 }) {
  if (azSpan >= 360) {
    const circle = (alt) => edge(az0 - 180, az0 + 180, stepDeg, (az) => [az, alt])
    return altMax >= 90 ? [circle(altMin)] : [circle(altMin), circle(altMax)]
  }
  const azL = az0 - azSpan / 2
  const azR = az0 + azSpan / 2
  const zenith = altMax >= 90
  const top = zenith ? 90 : altMax
  const ring = [
    ...edge(azL, azR, stepDeg, (az) => [az, altMin]),
    ...edge(altMin, top, stepDeg, (alt) => [azR, alt])
  ]
  if (zenith) ring.push([az0, 90])
  else ring.push(...edge(azR, azL, stepDeg, (az) => [az, altMax]))
  const left = edge(top, altMin, stepDeg, (alt) => [azL, alt])
  ring.push(...(zenith ? left.slice(1) : left))
  return [ring]
}

// 屏幕点列 → SVG path。null 是断点（投影奇点附近的点）：环内无断点才用 Z 闭合
export function screenRingsToPath (rings) {
  let d = ''
  for (const ring of rings) {
    let penUp = true
    for (const p of ring) {
      if (!p) { penUp = true; continue }
      d += (penUp ? 'M' : 'L') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)
      penUp = false
    }
    if (ring.length && !ring.includes(null)) d += 'Z'
  }
  return d
}
