// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

import { describe, it, expect } from 'vitest'
import {
  isResolvableKey, buildSkyCatalogReverse, buildCommonNameReverse,
  buildSearchEntries, matchRank, rankSuggestions, designationForms
} from './sky-search.js'

// 一份贴近真实数据形状的 common_names：DSO 用星表编号，恒星用 HIP。
const CN = {
  'M 31': [{ english: 'Andromeda Galaxy' }],
  'M 45': [{ english: 'Pleiades' }],
  'HIP 91262': [{ english: 'Vega' }]
}
const REV = buildCommonNameReverse(CN)
const identity = (k) => k

describe('buildCommonNameReverse', () => {
  it('英文专名（小写）映射到星表编号', () => {
    expect(REV['andromeda galaxy']).toBe('M 31')
    expect(REV.vega).toBe('HIP 91262')
  })
  it('同名被多条共用时只留第一个编号', () => {
    const r = buildCommonNameReverse({
      'M 31': [{ english: 'Twin' }],
      'M 32': [{ english: 'Twin' }]
    })
    expect(r.twin).toBe('M 31')
  })
  it('值不是数组就跳过，不抛', () => {
    expect(buildCommonNameReverse({ 'M 1': null, 'M 2': 'x' })).toEqual({})
  })
})

describe('buildSkyCatalogReverse', () => {
  it('本地化名（小写）映射回英文源名', () => {
    const r = buildSkyCatalogReverse({ Vega: '织女一', Mars: '火星' })
    expect(r['织女一']).toBe('Vega')
    expect(r['火星']).toBe('Mars')
  })
  it('非字符串值被忽略', () => {
    expect(buildSkyCatalogReverse({ a: 1, b: null, c: 'x' })).toEqual({ x: 'c' })
  })
})

describe('isResolvableKey', () => {
  it('common_names 里的专名可解析', () => {
    expect(isResolvableKey('Andromeda Galaxy', REV)).toBe(true)
  })
  it('行星与卫星可解析', () => {
    expect(isResolvableKey('Mars', REV)).toBe(true)
    expect(isResolvableKey('Titan', REV)).toBe(true)
  })
  it('彗星编号可解析', () => {
    expect(isResolvableKey('1P/Halley', REV)).toBe(true)
    expect(isResolvableKey('C/2023 A3', REV)).toBe(true)
  })
  it('本仓数据里没有的 stellarium 别名不可解析', () => {
    expect(isResolvableKey('Ghost of Mars Nebula', REV)).toBe(false)
  })
})

describe('matchRank', () => {
  it('名字以查询开头 = 0', () => {
    expect(matchRank('andromeda galaxy', 'and')).toBe(0)
  })
  it('名字中某个词以查询开头 = 1', () => {
    expect(matchRank('andromeda galaxy', 'gal')).toBe(1)
  })
  it('不匹配 = -1', () => {
    expect(matchRank('andromeda galaxy', 'zzz')).toBe(-1)
  })
  it('刻意不做词中匹配：CJK 复合名不会被巧合命中', () => {
    // 「火星」落在「烟花星系」中间，不能当成命中 Mars。
    expect(matchRank('烟花星系', '火星')).toBe(-1)
    expect(matchRank('烈火星云', '火星')).toBe(-1)
    // 但「火星」本身照样以它开头。
    expect(matchRank('火星', '火星')).toBe(0)
  })
})

describe('buildSearchEntries', () => {
  const cats = [
    { Vega: '织女一', 'Andromeda Galaxy': '仙女座星系', N: '北', Meridian: '子午线', 'Ghost of Mars Nebula': '火星幽灵星云' },
    { Vega: 'ベガ', 'Andromeda Galaxy': 'アンドロメダ銀河' }
  ]
  const entries = buildSearchEntries(cats, REV)
  const tOf = (key) => entries.filter(e => e.key === key).map(e => e.t)

  it('收录每种语言的名字', () => {
    expect(tOf('Vega')).toEqual(expect.arrayContaining(['织女一', 'ベガ']))
  })
  it('英文源名只收一次', () => {
    expect(tOf('Vega').filter(t => t === 'vega')).toHaveLength(1)
  })
  it('剔除方位基点与有名字的线', () => {
    expect(entries.some(e => e.key === 'N' || e.key === 'Meridian')).toBe(false)
  })
  it('剔除本仓数据里选不中的 stellarium 别名', () => {
    expect(entries.some(e => e.key === 'Ghost of Mars Nebula')).toBe(false)
  })
  it('补星表编号行，带空格与不带空格两种写法', () => {
    // 直接输 'M31' 或 'M 31' 都要有候选可点，而不是只能盲按回车。
    expect(tOf('Andromeda Galaxy')).toEqual(expect.arrayContaining(['m 31', 'm31']))
    expect(tOf('Vega')).toEqual(expect.arrayContaining(['hip 91262', 'hip91262']))
  })
})

describe('rankSuggestions', () => {
  const entries = [
    { key: 'Ghost of Jupiter Nebula', t: 'ghost of jupiter nebula' },
    { key: 'Jupiter', t: 'jupiter' },
    { key: 'Jupiter', t: '木星' }
  ]

  it('前缀命中排在词首命中之前', () => {
    const r = rankSuggestions(entries, 'jupiter', 12, identity)
    expect(r.map(x => x.key)).toEqual(['Jupiter', 'Ghost of Jupiter Nebula'])
  })
  it('按 key 去重：一个天体只出一条', () => {
    const r = rankSuggestions(entries, 'j', 12, identity)
    expect(r.filter(x => x.key === 'Jupiter')).toHaveLength(1)
  })
  it('跨语言：中文查询命中同一个英文 key', () => {
    expect(rankSuggestions(entries, '木星', 12, identity).map(x => x.key)).toEqual(['Jupiter'])
  })
  it('label 走 labelFor，key 保持英文源名', () => {
    const r = rankSuggestions(entries, '木星', 12, (k) => '显示:' + k)
    expect(r[0]).toEqual({ label: '显示:Jupiter', key: 'Jupiter' })
  })
  it('遵守 limit', () => {
    const many = Array.from({ length: 50 }, (_, i) => ({ key: 'k' + i, t: 'aa' + i }))
    expect(rankSuggestions(many, 'aa', 5, identity)).toHaveLength(5)
  })
  it('空查询与空索引返回空数组', () => {
    expect(rankSuggestions(entries, '', 12, identity)).toEqual([])
    expect(rankSuggestions(entries, '   ', 12, identity)).toEqual([])
    expect(rankSuggestions(null, 'jupiter', 12, identity)).toEqual([])
  })
})

describe('designationForms', () => {
  it("'M31' 归一出 'M 31'（引擎只认带空格的写法）", () => {
    expect(designationForms('M31')).toContain('M 31')
  })
  it("'ngc224' 归一出 'NGC 224'", () => {
    expect(designationForms('ngc224')).toContain('NGC 224')
  })
  it('去掉编号前导零', () => {
    expect(designationForms('M 031')).toContain('M 31')
  })
  it("补 'NAME ' 前缀（卫星只认这种写法）", () => {
    expect(designationForms('ISS')).toContain('NAME ISS')
  })
  it('原样也要试（恒星专名直接命中）', () => {
    expect(designationForms('Vega')[0]).toBe('Vega')
  })
  it('不产生重复形式', () => {
    const f = designationForms('M 31')
    expect(new Set(f).size).toBe(f.length)
  })
  it('空输入返回空数组', () => {
    expect(designationForms('')).toEqual([])
    expect(designationForms('   ')).toEqual([])
    expect(designationForms(null)).toEqual([])
  })
})
