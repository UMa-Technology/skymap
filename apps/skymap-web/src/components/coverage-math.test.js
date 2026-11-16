// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

import { describe, it, expect } from 'vitest'
import { coverageOutlineAltAz, screenRingsToPath } from './coverage-math'

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
  it('有断点不闭合、分段', () => {
    expect(screenRingsToPath([[[0, 0], null, [5, 5], [6, 6]]])).toBe('M0.0 0.0M5.0 5.0L6.0 6.0')
  })
  it('空输入回空串', () => {
    expect(screenRingsToPath([])).toBe('')
  })
})
