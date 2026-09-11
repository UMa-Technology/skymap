// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

// 离线跨语言天体搜索的纯逻辑：建索引、排名、把用户输入归一成引擎认的星表编号。
// 不碰 DOM、不碰引擎实例、不发请求，便于在 node 环境下单测（vitest 配的是
// environment: 'node'）。取数据与调 getObj 在 sw_helpers.js。
// 与 sky-ar-state.js / custom-horizon-geometry.js 的拆分方式一致。

// 目录里不是可选中天体的条目：方位基点与三条有名字的线。
export const NON_OBJECT_KEYS = new Set([
  'N', 'E', 'S', 'W', 'NE', 'SE', 'SW', 'NW', 'Meridian', 'Ecliptic', 'Equator'
])

// 太阳系天体，走 getObj('NAME <body>') 解析。sky-i18n 目录里还混着 stellarium
// 自带、而本仓数据里并没有的 DSO 别名（如 'Mars Observer'、'Ghost of Mars
// Nebula'），点了也选不中；索引只收能解析的：在 skyculture common_names 里的
// （DSO + 有专名的恒星）、下面这些天体、或彗星编号。
export const PLANET_NAMES = new Set([
  'Sun', 'Moon', 'Mercury', 'Venus', 'Earth', 'Mars', 'Jupiter', 'Saturn',
  'Uranus', 'Neptune', 'Pluto', 'Ceres', 'Vesta', 'Pallas', 'Juno',
  'Io', 'Europa', 'Ganymede', 'Callisto', 'Mimas', 'Enceladus', 'Tethys',
  'Dione', 'Rhea', 'Titan', 'Hyperion', 'Iapetus', 'Phoebe', 'Miranda',
  'Ariel', 'Umbriel', 'Titania', 'Oberon', 'Triton', 'Proteus', 'Nereid',
  'Charon', 'Phobos', 'Deimos'
])

export const COMET_KEY_RE = /^(\d+[PCDXAI](-[A-Z0-9]+)?\/|[PCDXAI]\/\d{4})/

// 空间站（ISS + 天宫）的补充索引行。它们在卫星模块里，不在 sky-i18n 目录里，
// buildSearchEntries 扫不到。key 是引擎认得的名字（searchSkyObject 会补 'NAME '
// 前缀），同时用它去 skyCatalog 取当前语言的显示名（skyCatalog['ISS']='国际空间站'，
// 来自 tools/add-sky-i18n-satellites.py）。每个可搜别名各占一行，按 key 去重，
// 所以一次查询每个空间站只出一条。
export const SATELLITE_SEARCH_ENTRIES = [
  { key: 'ISS', t: 'iss' },
  { key: 'ISS', t: 'international space station' },
  { key: 'ISS', t: '国际空间站' },
  { key: 'ISS', t: '国际太空站' },
  { key: 'Tiangong', t: 'tiangong' },
  { key: 'Tiangong', t: 'css' },
  { key: 'Tiangong', t: 'chinese space station' },
  { key: 'Tiangong', t: '天宫' },
  { key: 'Tiangong', t: '天宫空间站' },
  { key: 'Tiangong', t: '中国空间站' }
]

export function isResolvableKey (key, commonNameToDesignation) {
  return (key.toLowerCase() in commonNameToDesignation) ||
    PLANET_NAMES.has(key) || COMET_KEY_RE.test(key)
}

// 当前语言目录的反查：本地化名（小写）-> 英文源名。让搜索框能把用户按当前天空
// 语言输入的名字翻回英文源名再去解析。
export function buildSkyCatalogReverse (cat) {
  const rev = {}
  for (const k in cat) {
    const v = cat[k]
    if (typeof v === 'string') rev[v.toLowerCase()] = k
  }
  return rev
}

// 英文专名（小写）-> 星表编号，取自 western skyculture 的 common_names。
// DSO 的 eph id 里只有星表编号（M 31、NGC 224），没有专名，所以按专名选中必须先
// 映射回编号。（恒星的 eph names 里带 'NAME <专名>'，本来就能直接解析。）
export function buildCommonNameReverse (cn) {
  const rev = {}
  for (const desig in cn) {
    const arr = cn[desig]
    if (!Array.isArray(arr)) continue
    for (let i = 0; i < arr.length; i++) {
      const en = arr[i] && arr[i].english
      // 一个名字被多条共用时（例如某个成组天体的各成员）只留第一个编号。
      if (en && !(en.toLowerCase() in rev)) rev[en.toLowerCase()] = desig
    }
  }
  return rev
}

// 从所有语言目录建跨语言索引：每行是 {key（英文源名）, t（某种语言的名字，小写）}。
// 从目录而不是只从 common_names 取，是为了把所有可搜天体都收进来——行星、彗星、
// 恒星和 DSO；英文 key 再由 searchSkyObject 去解析（DSO 的专名会先映射成星表编号，
// 其余走 'NAME <key>'）。
//
// 另外按 common_names 补一批星表编号行（M 31 / NGC 224 / HIP 91262 …），外加它们
// 的去空格形式，这样直接输编号也有候选可点——否则 'M31' 只能盲按回车。
export function buildSearchEntries (cats, commonNameToDesignation) {
  const entries = []
  const keySeen = {}
  for (let c = 0; c < cats.length; c++) {
    const cat = cats[c]
    for (const key in cat) {
      if (NON_OBJECT_KEYS.has(key) ||
          !isResolvableKey(key, commonNameToDesignation)) continue
      const v = cat[key]
      if (typeof v === 'string') entries.push({ key: key, t: v.toLowerCase() })
      if (keySeen[key]) continue
      keySeen[key] = true
      entries.push({ key: key, t: key.toLowerCase() })
      // 星表编号行。必须在这个循环里补、用目录里原样大小写的 key：
      // commonNameToDesignation 的键是小写化过的，拿它当 key 会和目录行算成两个
      // 不同天体（去重是按 key），标签也会退成小写。
      const desig = commonNameToDesignation[key.toLowerCase()]
      if (!desig) continue
      const lower = desig.toLowerCase()
      entries.push({ key: key, t: lower })
      // 'm 31' -> 'm31'：用户不打空格也能出候选（喂给引擎时的空格由
      // designationForms 补回来）。
      const tight = lower.replace(/\s+/g, '')
      if (tight !== lower) entries.push({ key: key, t: tight })
    }
  }
  return entries
}

// 把查询串和名字比：0 = 名字以它开头，1 = 名字里某个词以它开头，-1 = 不匹配。
// 刻意不做词中匹配：CJK 复合名没有空格，纯子串会冒出一堆巧合命中
// （比如「火星」落在 烟花星系 / 烈火星云 里面），这正是要避开的噪声。
export function matchRank (t, q) {
  const pos = t.indexOf(q)
  if (pos === 0) return 0
  if (pos > 0 && t.charCodeAt(pos - 1) === 32) return 1
  return -1
}

// 按索引给出候选：前缀命中排在词首命中之前，按 key 去重。labelFor 把英文源名换成
// 当前显示语言的标签。返回 [{label, key}]，key 交给 searchSkyObject 解析。
export function rankSuggestions (entries, query, limit, labelFor) {
  const q = (query || '').trim().toLowerCase()
  if (!q || !entries) return []
  limit = limit || 12
  const prefix = []
  const other = []
  const seen = {}
  for (let i = 0; i < entries.length && prefix.length < limit; i++) {
    const e = entries[i]
    if (seen[e.key]) continue
    const r = matchRank(e.t, q)
    if (r < 0) continue
    if (r === 0) {
      seen[e.key] = true
      prefix.push({ label: labelFor(e.key), key: e.key })
    } else if (other.length < limit) {
      seen[e.key] = true
      other.push({ label: labelFor(e.key), key: e.key })
    }
  }
  return prefix.concat(other).slice(0, limit)
}

// 一个名字要拿去喂 getObj 的所有形式。core_search 是精确匹配（大小写不敏感、
// 空格敏感），所以同一个天体必须试多种写法：
//   'Vega'     -> 恒星专名直接命中
//   'NAME ISS' -> 卫星要 'NAME ' 前缀
//   'M31'      -> 归一成 'M 31' 才命中
export function designationForms (base) {
  const forms = []
  const add = function (s) { if (s && forms.indexOf(s) === -1) forms.push(s) }
  const b = (base || '').trim()
  if (!b) return forms
  add(b)
  add('NAME ' + b)
  const up = b.toUpperCase().replace(/\s+/g, ' ').trim()
  add(up)
  add('NAME ' + up)
  // 'M31' -> 'M 31'，'NGC224' -> 'NGC 224'，'M 031' -> 'M 31'。
  const spaced = up.replace(/^([A-Z]+)\s*0*([0-9].*)$/, '$1 $2')
  add(spaced)
  add('NAME ' + spaced)
  return forms
}
