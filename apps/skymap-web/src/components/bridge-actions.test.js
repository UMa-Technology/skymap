// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

// 钉死对外协议：window.StellariumActions 的 49 个键与 getState 回包的 33 个键。
// 取景功能拆出去之后，两份清单由 jsbridge.vue 与 framing-overlay.vue 共同凑齐，
// 且两边不许重名。纯静态：读源码、正则提取，不起 Vue、不碰 DOM。
import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (name) => {
  const p = join(here, name)
  return existsSync(p) ? readFileSync(p, 'utf8') : ''
}

// 从 `startMarker` 起、到第一处 `endMarker` 止的文本；缺任一标记返回 ''。
function slice (src, startMarker, endMarker) {
  const a = src.indexOf(startMarker)
  if (a < 0) return ''
  const b = src.indexOf(endMarker, a + startMarker.length)
  return b < 0 ? '' : src.slice(a, b)
}

// 块内固定缩进的对象键。indent 是空格数；action 键后面跟 `(`（可能另起一行），state 键不跟。
function keysAt (block, indent, arrowOnly) {
  const re = new RegExp(`^ {${indent}}([A-Za-z0-9_]+):${arrowOnly ? '\\s*\\(' : ' '}`, 'gm')
  const out = []
  let m
  while ((m = re.exec(block)) !== null) out.push(m[1])
  return out
}

const bridge = read('jsbridge.vue')
const framing = read('framing-overlay.vue')

const bridgeActions = keysAt(
  slice(bridge, 'registerBridgeActions () {', '\n    },\n'), 8, true)
const framingActions = keysAt(
  slice(framing, '    actions () {', '\n    },\n'), 8, true)

const bridgeState = keysAt(
  slice(bridge, 'updateState () {', "jsbridge.postMessage('getState'"), 10, false)
const framingState = keysAt(
  slice(framing, '    stateFields () {', '\n    },\n'), 8, false)

const GOLDEN_ACTIONS = [
  'toggleConstellationLines', 'toogleMilkyway', 'toggleStars', 'toggleStarLabels',
  'toggleSatellites',
  'setSatelliteTLE', 'toggleEquatorLine', 'toggleMeridian', 'toggleEcliptic',
  'setDsoCatalog', 'setSkyCulture', 'toggleConstellationArt', 'toggleAtmosphere', 'toggleLandscape',
  'setCustomHorizon', 'showCustomHorizon', 'clearCustomHorizon', 'toggleAzimuthalGrid',
  'toggleEquatorialGrid', 'toggleEquatorialJ2000Grid', 'toggleNightMode', 'enableARMode',
  'toggleCenterFov', 'scaleFov2Target', 'restoreScaledFov', 'drawRectWithAltAndAz',
  'clearOffCenterRect', 'showMosaic', 'hideMosaic', 'getMosaicCenters',
  'updateArMode', 'gotoByAltAndAzWithArMode', 'gotoByAltAndAz', 'gotoAndLock',
  'lockToSelection', 'unselect', 'updateFov', 'setLocation', 'setSkyLanguage',
  'setDateTime', 'speedTime', 'zoomIn', 'zoomOut', 'stopZoom', 'lockView', 'getState',
  'enableTouch', 'drawLines', 'clearLines'
]

const GOLDEN_STATE = [
  'toggleConstellationLines', 'toggleConstellationArt', 'toggleAtmosphere',
  'toggleLandscape', 'toogleMilkyway', 'toggleStars', 'toggleStarLabels',
  'toggleSatellites',
  'toggleEquatorLine', 'toggleMeridian', 'toggleEcliptic', 'toggleAzimuthalGrid',
  'toggleEquatorialGrid', 'toggleEquatorialJ2000Grid', 'dsoCatalog', 'dsoCatalogItems',
  'hasCustomHorizon', 'showCustomHorizon', 'toggleNightMode', 'currentTime', 'location',
  'speedTime', 'fov', 'fovX', 'fovY', 'arMode', 'enableArMode', 'currentLocation',
  'direction', 'drawSelectedTargetLine', 'showMosaic', 'mosaicConfig', 'skyCulture'
]

const sorted = (xs) => [...xs].sort()

describe('window.StellariumActions 的键集合', () => {
  it('黄金清单恰好 49 个', () => {
    expect(GOLDEN_ACTIONS).toHaveLength(49)
    expect(new Set(GOLDEN_ACTIONS).size).toBe(49)
  })
  it('基座与取景模块不重名', () => {
    const dup = bridgeActions.filter((k) => framingActions.includes(k))
    expect(dup).toEqual([])
  })
  it('两边合起来等于黄金清单', () => {
    expect(sorted([...bridgeActions, ...framingActions])).toEqual(sorted(GOLDEN_ACTIONS))
  })
})

describe('getState 回包的键集合', () => {
  it('黄金清单恰好 33 个', () => {
    expect(GOLDEN_STATE).toHaveLength(33)
    expect(new Set(GOLDEN_STATE).size).toBe(33)
  })
  it('基座与取景模块不重名', () => {
    const dup = bridgeState.filter((k) => framingState.includes(k))
    expect(dup).toEqual([])
  })
  it('两边合起来等于黄金清单', () => {
    expect(sorted([...bridgeState, ...framingState])).toEqual(sorted(GOLDEN_STATE))
  })
})
