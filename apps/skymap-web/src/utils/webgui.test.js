// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

import { describe, it, expect } from 'vitest'
import { wantsWebGui } from './webgui.js'

describe('wantsWebGui', () => {
  it('is on only for webgui=1', () => {
    expect(wantsWebGui('?webgui=1')).toBe(true)
    expect(wantsWebGui('?lat=31&webgui=1&fov=60')).toBe(true)
  })
  it('is off by default and for any other value', () => {
    expect(wantsWebGui('')).toBe(false)
    expect(wantsWebGui(undefined)).toBe(false)
    expect(wantsWebGui('?webgui=0')).toBe(false)
    expect(wantsWebGui('?webgui=true')).toBe(false)
  })
})
