import { describe, it, expect } from 'vitest'
import { euclideanModulus, altitudeAt } from './custom-horizon-geometry.js'

// Small already-groomed profile (sorted, has az=0 and az=360).
const P = [
  { az: 0, alt: 14 },
  { az: 5, alt: 69 },
  { az: 55, alt: 77 },
  { az: 90, alt: 70 },
  { az: 360, alt: 14 }
]

describe('euclideanModulus', () => {
  it('wraps into [0, 360)', () => {
    expect(euclideanModulus(-10, 360)).toBe(350)
    expect(euclideanModulus(370, 360)).toBe(10)
    expect(euclideanModulus(0, 360)).toBe(0)
    expect(euclideanModulus(360, 360)).toBe(0)
  })
})

describe('altitudeAt', () => {
  it('returns exact sample values', () => {
    expect(altitudeAt(P, 0)).toBe(14)
    expect(altitudeAt(P, 55)).toBe(77)
    expect(altitudeAt(P, 360)).toBe(14)
  })
  it('linearly interpolates between samples', () => {
    // between 5->69 and 55->77, t=(30-5)/50=0.5 => 73
    expect(altitudeAt(P, 30)).toBe(73)
  })
  it('wraps out-of-range azimuths', () => {
    expect(altitudeAt(P, -270)).toBe(70) // -270 mod 360 = 90
    expect(altitudeAt(P, 365)).toBe(69)  // 365 mod 360 = 5
  })
})

import { normalizeProfile } from './custom-horizon-geometry.js'

describe('normalizeProfile', () => {
  it('accepts [[az,alt]] pairs, sorts, dedups (last wins)', () => {
    const p = normalizeProfile([[10, 5], [20, 7], [10, 9]])
    expect(p.find((q) => q.az === 10).alt).toBe(9)
    expect(p.map((q) => q.az)).toEqual([0, 10, 20, 360])
  })
  it('accepts {points:[{az,alt}]} and fills the missing 360 anchor', () => {
    const p = normalizeProfile({ points: [{ az: 0, alt: 14 }, { az: 90, alt: 70 }] })
    expect(p.find((q) => q.az === 360).alt).toBe(14)
  })
  it('fills both 0 and 360 when neither is present', () => {
    const p = normalizeProfile([{ az: 90, alt: 10 }, { az: 180, alt: 20 }])
    expect(p.find((q) => q.az === 0).alt).toBe(10)
    expect(p.find((q) => q.az === 360).alt).toBe(10)
  })
  it('clamps altitude to [0,90]', () => {
    const p = normalizeProfile([{ az: 100, alt: -5 }, { az: 200, alt: 95 }])
    expect(p.find((q) => q.az === 100).alt).toBe(0)
    expect(p.find((q) => q.az === 200).alt).toBe(90)
  })
  it('returns null for fewer than 2 valid points', () => {
    expect(normalizeProfile([{ az: 5, alt: 5 }])).toBeNull()
    expect(normalizeProfile([])).toBeNull()
    expect(normalizeProfile(null)).toBeNull()
  })
  it('fills 0/360 from the nearest-to-360 end when it is closer', () => {
    // keys 40 and 350: 360-350=10 < 40, so the 350 value seeds both anchors
    const p = normalizeProfile([{ az: 40, alt: 5 }, { az: 350, alt: 25 }])
    expect(p.find((q) => q.az === 0).alt).toBe(25)
    expect(p.find((q) => q.az === 360).alt).toBe(25)
  })
  it('forces az=0 and az=360 equal when a profile supplies conflicting ends', () => {
    // north must stay single-valued (no silhouette tear); 360 is pinned to 0
    const p = normalizeProfile([{ az: 0, alt: 10 }, { az: 180, alt: 50 }, { az: 360, alt: 80 }])
    expect(p.find((q) => q.az === 0).alt).toBe(10)
    expect(p.find((q) => q.az === 360).alt).toBe(10)
  })
  it('skips points with non-finite az/alt', () => {
    const p = normalizeProfile([[10, NaN], [20, 7], [30, 9]])
    expect(p.some((q) => q.az === 10)).toBe(false)
    expect(p.find((q) => q.az === 20).alt).toBe(7)
  })
  it('wraps genuinely out-of-range azimuths into [0,360)', () => {
    const p = normalizeProfile([[370, 15], [180, 20], [-10, 25]])
    expect(p.some((q) => q.az < 0 || q.az > 360)).toBe(false)
    expect(p.find((q) => q.az === 10).alt).toBe(15) // 370 -> 10
    expect(p.find((q) => q.az === 350).alt).toBe(25) // -10 -> 350
  })
})

import { altitudeAtGreatCircle } from './custom-horizon-geometry.js'

describe('altitudeAtGreatCircle', () => {
  it('hits the profile vertices exactly', () => {
    expect(altitudeAtGreatCircle(P, 0)).toBe(14)
    expect(altitudeAtGreatCircle(P, 5)).toBe(69)
    expect(altitudeAtGreatCircle(P, 55)).toBe(77)
    expect(altitudeAtGreatCircle(P, 360)).toBe(14)
  })
  it('stays taut above the az/alt-linear path near the zenith', () => {
    // Linear interp of (5,69)->(55,77) at az=30 gives 73, but that path sags
    // ~2.4 deg below the great circle (verified against a slerp ground truth).
    expect(altitudeAt(P, 30)).toBe(73)
    expect(altitudeAtGreatCircle(P, 30)).toBeCloseTo(75.355, 2)
    expect(altitudeAtGreatCircle(P, 75)).toBeCloseTo(74.446, 2)
  })
  it('nearly matches linear interpolation at low altitude', () => {
    const Q = [{ az: 0, alt: 5 }, { az: 20, alt: 8 }, { az: 360, alt: 5 }]
    const gc = altitudeAtGreatCircle(Q, 10)
    expect(Math.abs(gc - altitudeAt(Q, 10))).toBeLessThan(0.15)
  })
  it('falls back to linear interpolation for spans wider than 90 deg', () => {
    const Q = [{ az: 0, alt: 10 }, { az: 200, alt: 50 }, { az: 360, alt: 10 }]
    expect(altitudeAtGreatCircle(Q, 100)).toBe(altitudeAt(Q, 100)) // 30, exactly
  })
  it('never deviates more than 3 deg from the linear (2D chart) model', () => {
    // Sparse wide-and-high segment: raw GC would render 83.05 at az 45 vs the
    // chart's 47.5 — the bound keeps map/chart editing parity.
    const Q = [{ az: 0, alt: 10 }, { az: 90, alt: 85 }, { az: 180, alt: 10 }, { az: 360, alt: 10 }]
    for (let az = 0; az <= 180; az += 1) {
      expect(Math.abs(altitudeAtGreatCircle(Q, az) - altitudeAt(Q, az))).toBeLessThanOrEqual(3 + 1e-9)
    }
    expect(altitudeAtGreatCircle(Q, 45)).toBeCloseTo(49.68, 1)
  })
  it('caps the bulge of a flat high ridge (GC above both drawn vertices)', () => {
    // (0,70)-(90,70): raw GC bulges to 75.57 mid-span; capped at 70 + 3.
    const Q = [{ az: 0, alt: 70 }, { az: 90, alt: 70 }, { az: 360, alt: 70 }]
    expect(altitudeAtGreatCircle(Q, 45)).toBeCloseTo(73, 5)
  })
  it('tames a clamped zenith vertex instead of building an alt-90 wall', () => {
    // A vertex clamped to alt 90 makes the raw GC return 90 across the whole
    // adjacent span; bounded, it stays within 3 deg of the drawn ramp.
    const Q = [{ az: 0, alt: 90 }, { az: 40, alt: 70 }, { az: 360, alt: 90 }]
    const drawn = altitudeAt(Q, 20) // 80
    expect(altitudeAtGreatCircle(Q, 20)).toBeLessThanOrEqual(drawn + 3 + 1e-9)
    expect(altitudeAtGreatCircle(Q, 20)).toBeLessThan(90)
  })
  it('keeps a horizon-level segment at altitude 0', () => {
    const Q = [{ az: 0, alt: 0 }, { az: 80, alt: 0 }, { az: 360, alt: 0 }]
    expect(altitudeAtGreatCircle(Q, 40)).toBeCloseTo(0, 9)
  })
  it('wraps out-of-range azimuths like altitudeAt', () => {
    expect(altitudeAtGreatCircle(P, 365)).toBe(69) // 365 -> 5, a vertex
    expect(altitudeAtGreatCircle(P, -330)).toBeCloseTo(altitudeAtGreatCircle(P, 30), 9)
  })
})

import { sampleProfile } from './custom-horizon-geometry.js'

describe('sampleProfile', () => {
  it('samples 0..360 inclusive at the given step', () => {
    const s = sampleProfile(P, 90)
    expect(s.map((q) => q.az)).toEqual([0, 90, 180, 270, 360])
    expect(s[0].alt).toBe(14)
    expect(s[1].alt).toBe(70)
    expect(s[4].alt).toBe(14)
  })
  it('does not hang on a non-positive step (finite sample count)', () => {
    const s = sampleProfile(P, 0)
    expect(Number.isFinite(s.length)).toBe(true)
    expect(s.length).toBeGreaterThan(2)
    expect(s[s.length - 1].az).toBe(360)
  })
})

import { smoothCircular } from './custom-horizon-geometry.js'

describe('smoothCircular', () => {
  it('is a no-op copy for sigma <= 0', () => {
    const v = [1, 2, 3, 4]
    const s = smoothCircular(v, 0)
    expect(s).toEqual(v)
    expect(s).not.toBe(v)
  })
  it('preserves a constant array and its mean', () => {
    const s = smoothCircular([5, 5, 5, 5, 5, 5], 1.5)
    for (const x of s) expect(x).toBeCloseTo(5, 9)
  })
  it('rounds a corner: reduces a lone spike and lifts its neighbours, mean kept', () => {
    const v = new Array(64).fill(0)
    v[32] = 10
    const s = smoothCircular(v, 2)
    expect(s[32]).toBeLessThan(10) // peak lowered
    expect(s[31]).toBeGreaterThan(0) // neighbour lifted
    const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length
    expect(mean(s)).toBeCloseTo(mean(v), 9) // energy conserved
  })
  it('wraps circularly across the seam', () => {
    const v = new Array(8).fill(0)
    v[0] = 8
    const s = smoothCircular(v, 1)
    expect(s[7]).toBeGreaterThan(0) // index 0 bleeds into the last index
    expect(s[1]).toBeCloseTo(s[7], 9) // symmetric about the seam
  })
})

import { smoothAdaptiveCircular } from './custom-horizon-geometry.js'

describe('smoothAdaptiveCircular', () => {
  it('leaves samples untouched where the chosen sigma is <= 0', () => {
    const v = [1, 5, 2, 8, 3]
    const s = smoothAdaptiveCircular(v, () => 0)
    expect(s).toEqual(v)
    expect(s).not.toBe(v)
  })
  it('rounds a low corner more than a high one (altitude-adaptive)', () => {
    // two identical spikes; the "high" one gets sigma 0, the "low" one sigma 2
    const n = 64
    const low = new Array(n).fill(10)
    const high = new Array(n).fill(80)
    low[32] = 0 // a deep valley in a low ridge
    high[32] = 70 // an equally deep valley in a high ridge
    const sig = (alt) => (alt > 40 ? 0 : 2) // high => no smoothing
    const sl = smoothAdaptiveCircular(low, sig)
    const sh = smoothAdaptiveCircular(high, sig)
    expect(sl[32]).toBeGreaterThan(0) // low valley lifted (rounded)
    expect(sh[32]).toBe(70) // high valley untouched (kept sharp)
  })
})
