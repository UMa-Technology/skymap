// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

import { describe, it, expect } from 'vitest'
import { PROTOCOL, skymapBase } from './protocol.js'

describe('skymapBase', () => {
  it('protocol is 1', () => {
    expect(PROTOCOL).toBe(1)
  })
  it('carries the build version and the protocol number', () => {
    expect(skymapBase('v1.0.0')).toEqual({ version: 'v1.0.0', protocol: 1 })
  })
  it('is frozen', () => {
    expect(Object.isFrozen(skymapBase('v1.0.0'))).toBe(true)
  })
  it('falls back to 0.0.0-local when no version is known', () => {
    expect(skymapBase(undefined).version).toBe('0.0.0-local')
    expect(skymapBase('').version).toBe('0.0.0-local')
  })
})
