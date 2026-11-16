// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

import { describe, it, expect } from 'vitest'
import { coverageOutlineAltAz, screenRingsToPath, regionContainsAltAz } from './coverage-math'

const ARCH = { az0: 261.4, azSpan: 240, altMin: -16, altMax: 90 }
const EPS = 1e-9

describe('coverageOutlineAltAz', () => {
  it('一般跨度只回一个闭合环', () => {
    const rings = coverageOutlineAltAz(ARCH)
    expect(rings).toHaveLength(1)
    const ring = rings[0]
    for (const [az, alt] of ring) {
      expect(alt).toBeGreaterThanOrEqual(-16 - EPS)
      expect(alt).toBeLessThanOrEqual(90 + EPS)
      expect(az).toBeGreaterThanOrEqual(141.4 - EPS)
      expect(az).toBeLessThanOrEqual(381.4 + EPS)
    }
    expect(ring[0][0]).toBeCloseTo(141.4, 9)
    expect(ring[0][1]).toBeCloseTo(-16, 9)
  })

  it('相邻点角距不超过步长', () => {
    const ring = coverageOutlineAltAz(ARCH)[0]
    for (let i = 0; i < ring.length; i++) {
      const a = ring[i]
      const b = ring[(i + 1) % ring.length]
      if (a[1] === 90 || b[1] === 90) continue
      expect(Math.abs(a[0] - b[0])).toBeLessThanOrEqual(2 + EPS)
      expect(Math.abs(a[1] - b[1])).toBeLessThanOrEqual(2 + EPS)
    }
  })

  it('上缘到天顶收成一点', () => {
    const ring = coverageOutlineAltAz(ARCH)[0]
    expect(ring.filter(([, alt]) => alt === 90)).toHaveLength(1)
  })

  it('上缘不到天顶走等高线', () => {
    const ring = coverageOutlineAltAz({ ...ARCH, altMax: 70 })[0]
    expect(ring.filter(([, alt]) => alt === 70)).toHaveLength(240 / 2 + 1)
  })

  it('跨 0° 方位连续', () => {
    const ring = coverageOutlineAltAz({ ...ARCH, az0: 350 })[0]
    for (let i = 0; i < ring.length; i++) {
      const a = ring[i]
      const b = ring[(i + 1) % ring.length]
      if (a[1] === 90 || b[1] === 90) continue
      expect(Math.abs(a[0] - b[0])).toBeLessThanOrEqual(2 + EPS)
    }
  })

  it('整圈回两个环', () => {
    const rings = coverageOutlineAltAz({ az0: 0, azSpan: 360, altMin: -10, altMax: 60 })
    expect(rings).toHaveLength(2)
    expect(rings[0]).toHaveLength(180)
    expect(rings[1]).toHaveLength(180)
    expect(rings[0].every(([, alt]) => alt === -10)).toBe(true)
    expect(rings[1].every(([, alt]) => alt === 60)).toBe(true)
  })

  it('整圈到天顶只回一个环', () => {
    const rings = coverageOutlineAltAz({ az0: 0, azSpan: 400, altMin: -10, altMax: 90 })
    expect(rings).toHaveLength(1)
  })
})

describe('screenRingsToPath', () => {
  it('无断点闭合', () => {
    expect(screenRingsToPath([[[0, 0], [10, 0], [10, 10]]])).toBe('M0.0 0.0L10.0 0.0L10.0 10.0Z')
  })
  it('有断点不闭合，从断点后起笔让首尾那段连上', () => {
    expect(screenRingsToPath([[[0, 0], null, [5, 5], [6, 6]]])).toBe('M5.0 5.0L6.0 6.0L0.0 0.0')
    expect(screenRingsToPath([[[0, 0], [1, 1], null, [5, 5], null, [7, 7]]]))
      .toBe('M5.0 5.0M7.0 7.0L0.0 0.0L1.0 1.0')
  })
  it('全是断点回空串', () => {
    expect(screenRingsToPath([[null, null]])).toBe('')
  })
  it('空输入回空串', () => {
    expect(screenRingsToPath([])).toBe('')
  })
})

describe('regionContainsAltAz', () => {
  const R = { az0: 0, azSpan: 240, altMin: -16, altMax: 90 }
  it('方位与高度都在范围内', () => {
    expect(regionContainsAltAz(R, 350, 10)).toBe(true)
    expect(regionContainsAltAz(R, 119, 89)).toBe(true)
  })
  it('方位出界', () => {
    expect(regionContainsAltAz(R, 180, 10)).toBe(false)
  })
  it('高度出界', () => {
    expect(regionContainsAltAz(R, 0, -20)).toBe(false)
    expect(regionContainsAltAz({ ...R, altMax: 60 }, 0, 70)).toBe(false)
  })
  it('整圈只看高度', () => {
    expect(regionContainsAltAz({ ...R, azSpan: 360, altMax: 60 }, 180, 30)).toBe(true)
  })
})
