// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

import { describe, it, expect } from 'vitest'
import { mosaicSkyOffset, mosaicScreenLayout, tangentPlaneToRaDec } from './mosaic-math'

// 网格与框同向：offsetX 向右、offsetY 向下（框坐标系），框上沿朝 PA（北向东）
describe('mosaicSkyOffset', () => {
  it('PA 0：向右 = 西、向下 = 南（与原来不转的网格一致）', () => {
    const r = mosaicSkyOffset(2, 0, 0)
    expect(r.east).toBeCloseTo(-2)
    expect(r.north).toBeCloseTo(0)
    const d = mosaicSkyOffset(0, 3, 0)
    expect(d.north).toBeCloseTo(-3)
    expect(d.east).toBeCloseTo(0)
  })

  it('PA 90：框上沿朝东——向上的格在东边，向右的格在北边', () => {
    const up = mosaicSkyOffset(0, -1, 90)
    expect(up.east).toBeCloseTo(1)
    expect(up.north).toBeCloseTo(0)
    const right = mosaicSkyOffset(1, 0, 90)
    expect(right.north).toBeCloseTo(1)
    expect(right.east).toBeCloseTo(0)
  })

  it('PA 30：整个网格绕中心转，格距不变', () => {
    const r = mosaicSkyOffset(4, 3, 30)
    expect(Math.hypot(r.north, r.east)).toBeCloseTo(5)
    // 上下两格在 PA ≠ 0 时赤纬不再相同
    const a = mosaicSkyOffset(-1, -1, 30)
    const b = mosaicSkyOffset(1, -1, 30)
    expect(a.north).not.toBeCloseTo(b.north)
  })

  it('PA 缺省按 0', () => {
    expect(mosaicSkyOffset(1, 0, undefined).east).toBeCloseTo(-1)
    expect(mosaicSkyOffset(1, 0, null).east).toBeCloseTo(-1)
  })
})

// 屏幕排布：网格刚性，格位与每格框都按「中心北向的屏幕角 − 网格 PA」转（屏幕坐标 y 向下，角度顺时针为正）
describe('mosaicScreenLayout', () => {
  it('PA 0、北朝上：2×1 网格左右排开，框不转', () => {
    const a = mosaicScreenLayout({ col: 0, row: 0, x: 2, y: 1, stepXPx: 100, stepYPx: 60, angleToNorth: 0, gridPa: 0 })
    const b = mosaicScreenLayout({ col: 1, row: 0, x: 2, y: 1, stepXPx: 100, stepYPx: 60, angleToNorth: 0, gridPa: 0 })
    expect(a.dx).toBeCloseTo(-50)
    expect(b.dx).toBeCloseTo(50)
    expect(a.dy).toBeCloseTo(0)
    expect(a.rotation).toBeCloseTo(0)
  })

  it('PA 90（北朝上）：网格整体逆时针转 90°，左右排开变成上下排开，各格框同一个角度', () => {
    const a = mosaicScreenLayout({ col: 0, row: 0, x: 2, y: 1, stepXPx: 100, stepYPx: 60, angleToNorth: 0, gridPa: 90 })
    const b = mosaicScreenLayout({ col: 1, row: 0, x: 2, y: 1, stepXPx: 100, stepYPx: 60, angleToNorth: 0, gridPa: 90 })
    expect(a.rotation).toBeCloseTo(-90)
    expect(b.rotation).toBeCloseTo(-90)
    // 「向右」的格转到屏幕上方（框上沿朝东 = 屏幕左，右侧 = 上）
    expect(b.dx).toBeCloseTo(0)
    expect(b.dy).toBeCloseTo(-50)
    expect(a.dy).toBeCloseTo(50)
  })

  it('北向不朝上时整体跟着北向转，PA 再在其上逆时针转', () => {
    const r = mosaicScreenLayout({ col: 1, row: 0, x: 2, y: 1, stepXPx: 100, stepYPx: 60, angleToNorth: 40, gridPa: 30 })
    expect(r.rotation).toBeCloseTo(10)
    expect(Math.hypot(r.dx, r.dy)).toBeCloseTo(50)
  })

  it('PA 缺省按 0', () => {
    expect(mosaicScreenLayout({ col: 0, row: 0, x: 1, y: 1, stepXPx: 1, stepYPx: 1, angleToNorth: 25, gridPa: null }).rotation).toBeCloseTo(25)
  })
})

// 切平面（日晷投影）反投影：格中心按刚性网格落在以网格中心为切点的平面上（phase 5 review I-4）
describe('tangentPlaneToRaDec', () => {
  const R = Math.PI / 180
  // 正投影（独立实现）：天球点 → 以 (ra0, dec0) 为切点的平面坐标
  const forward = (ra0, dec0, ra, dec) => {
    const cosc = Math.sin(dec0) * Math.sin(dec) + Math.cos(dec0) * Math.cos(dec) * Math.cos(ra - ra0)
    return {
      xi: Math.cos(dec) * Math.sin(ra - ra0) / cosc,
      eta: (Math.cos(dec0) * Math.sin(dec) - Math.sin(dec0) * Math.cos(dec) * Math.cos(ra - ra0)) / cosc
    }
  }

  it('切点本身原样返回', () => {
    const p = tangentPlaneToRaDec(1.2, 0.5, 0, 0)
    expect(p.ra).toBeCloseTo(1.2)
    expect(p.dec).toBeCloseTo(0.5)
  })

  it('近天极 +82° 与中赤纬都能往返（正投影回来等于输入）', () => {
    for (const dec0 of [82 * R, 30 * R, -45 * R]) {
      for (const [xi, eta] of [[0.03, -0.016], [-0.03, -0.016], [0.028, 0.02], [-0.05, 0.04]]) {
        const p = tangentPlaneToRaDec(0.3, dec0, xi, eta)
        const f = forward(0.3, dec0, p.ra, p.dec)
        expect(f.xi).toBeCloseTo(xi, 9)
        expect(f.eta).toBeCloseTo(eta, 9)
      }
    }
  })

  it('+82° 南排左右两格关于中心对称：到中心的角距相等（平面近似会一宽一窄留缝）', () => {
    const dec0 = 82 * R
    const a = tangentPlaneToRaDec(0, dec0, 0.028, -0.016)
    const b = tangentPlaneToRaDec(0, dec0, -0.028, -0.016)
    const dist = (p) => Math.acos(Math.sin(dec0) * Math.sin(p.dec) + Math.cos(dec0) * Math.cos(p.dec) * Math.cos(p.ra))
    expect(dist(a)).toBeCloseTo(dist(b), 12)
    expect(a.dec).toBeCloseTo(b.dec, 12)
  })
})
