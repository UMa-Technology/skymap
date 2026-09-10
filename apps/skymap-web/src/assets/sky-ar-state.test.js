// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

import { describe, it, expect } from 'vitest'
import { clampOpacity, nextArState } from './sky-ar-state.js'

describe('clampOpacity', () => {
  it('区间内原样返回', () => {
    expect(clampOpacity(0.5)).toBe(0.5)
    expect(clampOpacity(0.2)).toBe(0.2)
    expect(clampOpacity(0.8)).toBe(0.8)
  })
  it('两端钳位', () => {
    expect(clampOpacity(0)).toBe(0.2)
    expect(clampOpacity(1)).toBe(0.8)
    expect(clampOpacity(-3)).toBe(0.2)
  })
  it('非数值退回上限', () => {
    expect(clampOpacity(undefined)).toBe(0.8)
    expect(clampOpacity(null)).toBe(0.8)
    expect(clampOpacity('abc')).toBe(0.8)
    expect(clampOpacity(NaN)).toBe(0.8)
  })
  it('数字字符串按数字处理', () => {
    expect(clampOpacity('0.6')).toBe(0.6)
  })
})

describe('nextArState', () => {
  const live = { atmosphere: true, landscapes: true }

  it('首次开启：存下原值，下发全关', () => {
    const r = nextArState(null, true, live)
    expect(r.saved).toEqual({ atmosphere: true, landscapes: true })
    expect(r.apply).toEqual({ atmosphere: false, landscapes: false })
  })

  it('重复开启：不覆盖已存的原值', () => {
    const saved = { atmosphere: true, landscapes: false }
    // 此时引擎的实时值已被上一轮压成 false
    const r = nextArState(saved, true, { atmosphere: false, landscapes: false })
    expect(r.saved).toEqual({ atmosphere: true, landscapes: false })
    expect(r.apply).toEqual({ atmosphere: false, landscapes: false })
  })

  it('关闭：还原原值并清空存档', () => {
    const saved = { atmosphere: true, landscapes: false }
    const r = nextArState(saved, false, { atmosphere: false, landscapes: false })
    expect(r.saved).toBe(null)
    expect(r.apply).toEqual({ atmosphere: true, landscapes: false })
  })

  it('未开启时关闭：无存档则不下发任何值', () => {
    const r = nextArState(null, false, live)
    expect(r.saved).toBe(null)
    expect(r.apply).toBe(null)
  })

  it('存下的是原值副本，后续改动不串味', () => {
    const source = { atmosphere: true, landscapes: true }
    const r = nextArState(null, true, source)
    source.atmosphere = false
    expect(r.saved.atmosphere).toBe(true)
  })
})
