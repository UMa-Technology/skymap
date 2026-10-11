// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

import { describe, it, expect } from 'vitest'
import {
  ringRadius, displayDelta, deltaLabel, screenAngleOfPa, tagTextRotation,
  pointerBearing, bearingDelta, onRingBand, pointOnRing
} from './framing-ring-math'

describe('ringRadius', () => {
  it('手机横屏 852×393 → 短边一半减 28 = 168.5', () => {
    expect(ringRadius(852, 393)).toBeCloseTo(168.5)
  })
  it('平板封顶 240', () => {
    expect(ringRadius(1133, 744)).toBe(240)
  })
})

describe('displayDelta：当前 − 目标，(−180, 180]，取整', () => {
  it('目标比当前小 25 → +25（框顺时针多转了 25°）', () => {
    expect(displayDelta(123, 98)).toBe(25)
  })
  it('跨 0/360', () => {
    expect(displayDelta(10, 350)).toBe(20)
    expect(displayDelta(350, 10)).toBe(-20)
  })
  it('不按 180° 对称折叠：差 130 就是 130', () => {
    expect(displayDelta(130, 0)).toBe(130)
  })
  it('边界 180 取 +180', () => {
    expect(displayDelta(180, 0)).toBe(180)
  })
})

describe('deltaLabel', () => {
  it('|Δ| ≤ 1 显示 0°', () => {
    expect(deltaLabel(1)).toBe('0°')
    expect(deltaLabel(-1)).toBe('0°')
  })
  it('正数带 +，负数用真正的减号', () => {
    expect(deltaLabel(25)).toBe('+25°')
    expect(deltaLabel(-35)).toBe('−35°')
  })
})

describe('screenAngleOfPa / tagTextRotation', () => {
  it('PA 增大屏幕逆时针：screen = angleToNorth − pa', () => {
    expect(screenAngleOfPa(30, 10)).toBe(20)
  })
  it('倾角跟切线，超过 ±90 翻 180，文字不倒立', () => {
    expect(tagTextRotation(25)).toBe(25)
    expect(tagTextRotation(-35)).toBe(-35)
    expect(tagTextRotation(130)).toBe(-50)
    expect(tagTextRotation(-130)).toBe(50)
    expect(tagTextRotation(270)).toBe(-90)
  })
})

describe('指针方位与增量', () => {
  it('正上方 0、右边 90、下方 180', () => {
    expect(pointerBearing(100, 0, 100, 100)).toBeCloseTo(0)
    expect(pointerBearing(200, 100, 100, 100)).toBeCloseTo(90)
    expect(Math.abs(pointerBearing(100, 200, 100, 100))).toBeCloseTo(180)
  })
  it('增量取最短：350 → 10 是 +20', () => {
    expect(bearingDelta(350, 10)).toBeCloseTo(20)
    expect(bearingDelta(10, 350)).toBeCloseTo(-20)
  })
  it('圆环带 R ± 22 命中，环内环外不命中', () => {
    expect(onRingBand(100, 100 - 168, 100, 100, 168)).toBe(true)
    expect(onRingBand(100, 100 - 168 + 21, 100, 100, 168)).toBe(true)
    expect(onRingBand(100, 100, 100, 100, 168)).toBe(false)
    expect(onRingBand(100, 100 - 168 - 30, 100, 100, 168)).toBe(false)
  })
  it('pointOnRing 与 pointerBearing 互逆', () => {
    const [x, y] = pointOnRing(100, 100, 50, 90)
    expect(x).toBeCloseTo(150)
    expect(y).toBeCloseTo(100)
  })
})
