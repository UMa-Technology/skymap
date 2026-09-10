// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

// App.vue is the only emitter of 'initProgress'. Static check: every emission
// carries the base identity so the host can run the handshake on the very
// first message (Spec 2 §4.5).
const src = readFileSync(fileURLToPath(new URL('./App.vue', import.meta.url)), 'utf8')

describe('initProgress carries window.SkymapBase', () => {
  it('all four emissions pass base', () => {
    const calls = src.match(/postMessage\('initProgress',\s*\{[^}]*\}/g) || []
    expect(calls).toHaveLength(4)
    for (const call of calls) expect(call).toContain('base: window.SkymapBase')
  })
})
