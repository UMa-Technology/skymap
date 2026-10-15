// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

// 马赛克格中心的天球偏移（纯函数）。角度约定同 framing-ring-math.js：PA 北向东为正，
// 星图上东在屏幕左侧，PA 增大是屏幕逆时针。
// 网格整体与框同向：框上沿朝 PA，所以「向右」的单位向量 = 北·sin(PA) − 东·cos(PA)，
// 「向上」= 北·cos(PA) + 东·sin(PA)。offsetX 向右、offsetY 向下（框坐标系，单位任意）。
// 返回 { north, east }：north 即赤纬增量；east 是东向角距，换赤经要除 cos(dec)

export function mosaicSkyOffset (offsetX, offsetY, paDeg) {
  const t = (paDeg || 0) * Math.PI / 180
  return {
    north: offsetX * Math.sin(t) - offsetY * Math.cos(t),
    east: -offsetX * Math.cos(t) - offsetY * Math.sin(t)
  }
}

// 马赛克在屏幕上的排布（纯函数）：网格刚性，格位与每格框都按同一个角度转——
// rotation = 中心北向的屏幕角 angleToNorth − 网格 PA（屏幕坐标 y 向下，顺时针为正，同 framing-ring-math 的屏幕方位）。
// 返回该格中心相对画布中心的偏移 { dx, dy } 与框的 CSS 旋转角 rotation
export function mosaicScreenLayout ({ col, row, x, y, stepXPx, stepYPx, angleToNorth, gridPa }) {
  const rotation = angleToNorth - (gridPa || 0)
  const ox = (col - (x - 1) / 2) * stepXPx
  const oy = (row - (y - 1) / 2) * stepYPx
  const r = rotation * Math.PI / 180
  return {
    dx: ox * Math.cos(r) - oy * Math.sin(r),
    dy: ox * Math.sin(r) + oy * Math.cos(r),
    rotation
  }
}

// 切平面（日晷投影）反投影（纯函数，弧度）：以 (ra0, dec0) 为切点，平面坐标 xi 朝东、eta 朝北，
// 返回天球坐标 { ra, dec }。马赛克格中心按它算：刚性网格画在以网格中心为切点的平面上，
// 原来的「dec + 北偏移、ra + 东偏移 ÷ cos(中心赤纬)」平面近似在高赤纬会让同一排的格子一宽一窄、留缝
export function tangentPlaneToRaDec (ra0, dec0, xi, eta) {
  const rho = Math.hypot(xi, eta)
  if (rho === 0) return { ra: ra0, dec: dec0 }
  const denom = Math.cos(dec0) - eta * Math.sin(dec0)
  return {
    ra: ra0 + Math.atan2(xi, denom),
    dec: Math.atan2(Math.sin(dec0) + eta * Math.cos(dec0), Math.hypot(xi, denom))
  }
}
