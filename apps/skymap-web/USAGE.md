# JSBridge 使用说明

### 0.核心
核心代码在 jsbridge.vue 和 jsbridge-selected-object.vue 中

jsbridge.vue 中的主要交互

```angular2html
toggleConstellationLines - 切换星座线显示与否
toggleConstellationArt - 切换星座图显示与否
toggleAtmosphere - 切换大气层显示与否
toggleLandscape - 切换地形显示与否
toggleAzimuthalGrid - 切换方位网格显示与否
zoomOut - 缩小视图 参数值越大，缩小范围越小(参考值:0 < x < 1)
zoomIn - 放大视图 参数值越大，放大范围越小(参考值:0 < x < 1)
toggleEquatorialGrid - 切换赤道网格显示与否
toggleEquatorialJ2000Grid - 切换J2000赤道网格显示与否
toggleNightMode - 切换夜间模式显示与否
setLocation - 设置你当前的地理位置
{   "lat": 31.2304,
    "lng": 121.4737,
    "short_name": "Shanghai",
    "country": "China"
}
setDateTime - 设置当前的日期和时间isoString 格式 "2024-06-01T12:00:00Z"
getState - 获取当前应用的状态信息
gotoAndLock - 导航并锁定到指定的天体
```

gotoAndLock具体格式如下:
```angular2html
 {
  "match": "M 31",
  "model": "dso",
  "model_data": {
    "Bmag": 4.36,
      "Umag": 4.86,
      "Vmag": 3.44,
      "angle": 35.0,
      "de": 41.26875,
      "dimx": 177.83,
      "dimy": 69.66,
      "morpho": "SA(s)b ",
      "ra": 10.6847083,
      "rv": -300.0
    },
"names": [
"NAME Andromeda Nebula",
"M 31",
"NAME Andromeda Galaxy",
],
},

匹配原则：
1. 匹配model，如果是star,dso,minor_planet,tle_satellite,meteor-shower 类型，则会去从上往下匹配 names
star 恒星 dso 深空天体 minor_planet 小行星 tle_satellite 卫星（TLE轨道） meteor-shower 流星雨
2. 如果是coordinates，则代表没法匹配名称，直接使用坐标进行跳转，格式如下：
```angular2html
{
  "model": "coordinates",
  "model_data": {
    "ra": 10.6847083, //ra要求是读，就是 j2000*15
    "de": 41.26875
    }
}
3.如果你也不知道有没有匹配到，那就正确书写model，如果匹配不到，最后一步会当作coordinates来处理
4.当 goto 成功之后，jsbridge-selected-object.vue中的 selectedObjectChanged 会被触发，返回对应的信息
```


### 1. 简介
JSBridge 是一个用于在 JavaScript 和原生应用（如 iOS 和 Android）之间进行通信的桥接工具。它允许 JavaScript 代码调用原生功能，同时也允许原生代码调用 JavaScript 函数。

## 宿主契约（嵌入方必读）

以下内容均取自源码，行号供核对（相对本仓库当前提交）。

#### 1. 就绪三阶段与两条通道

`booting`（wasm 下载/实例化）→ `engineReady`（`window.$stel` 可用，此时才可安全下发
经纬度/时间/语言）→ `firstFrame`（首帧已绘制，可揭开 WebView/关闭原生 splash），失败为
`error`。window 全局量（`src/assets/sw_helpers.js:61-74,81-91`）：
`window.StellariumInitPhase`（四态字符串）、`window.StellariumReady`（布尔，到
`firstFrame` 置 `true`）、`window.__stelReady`（`Promise`，模块加载时即创建，首帧时以
引擎实例 resolve，供注入式宿主无竞态拿到就绪信号）。postMessage
（`src/App.vue:143,156,339-345,360`）：四个时间点各发一次 `initProgress {phase, base,
reason?}`（`reason` 仅 `error` 时出现，当前唯一值 `wasm-unsupported`），首帧时额外发一次
`ready {fov, location, mjd}`（角度制 FOV、`currentLocation`、儒略日）。

#### 2. 握手

`window.SkymapBase = {version, protocol}`（`src/protocol.js:16-21` 的 `skymapBase()`，
模块加载时挂上，同一对象也是每条 `initProgress` 的 `base` 字段）；`version` 是构建时
打入的 git tag（本地构建 `'0.0.0-local'`），`protocol` 是 wire-protocol 版本号（当前
`PROTOCOL = 1`，`src/protocol.js:11`）。宿主应精确比对 `protocol`、对 `version` 要求
最低值；升级规则见根 README「Releases and the handshake」。

#### 3. 出站消息通道（页面 → 原生）

`src/utils/jsbridge.js:9-16`：iOS 走
`window.webkit.messageHandlers.stellarium.postMessage(message)`，其它平台走
`window.stellarium.postMessage(message)`；消息体为
`JSON.stringify({action, data})`（`jsbridge.js:10`）。

#### 4. 入站（原生 → 页面）

本文件上方列出的动作注册为 `window.StellariumActions.<action>(data)`
（`jsbridge.js:19-21`）。引擎就绪后 `sw_helpers.js:136-139` 依次挂上四个全局对象：

- `window.CustomHorizon = { set, show, clear }` — 自定义地平线廓线
  （`src/assets/custom-horizon.js:63,69,75,98`）
- `window.SkyPhotos = { add, setOpacity, setVisible, remove, clear }` — 叠加照片
  （`src/assets/sky-photos.js:81,137,145,152,166,175`）
- `window.SkyAR = { enable, setSkyOpacity }` — AR 开关与星图整体透明度
  （`src/assets/sky-ar.js:35,44,70`）
- `window.Satellites = { setTLE, clear }` — 运行期推送最新 TLE
  （`src/assets/satellites.js:101,113,135`）

#### 5. URL 播种参数

`src/App.vue:setStateFromQueryArgs`（`46-94`）解析的 query：`date`（`54-55`）、
`lat`/`lng`/`elev`（`60-61`）、`az`（`67`）、`alt`（`68`）、`fov`（`69`，均角度制）、
`lang`（`76-78`）、`sc`（`263-267`，skyculture key），以及路由路径 `/skysource/<name>`
（`83-93`）。初值必须走 URL：页面加载到 `engineReady` 之前宿主发出的
`postMessage`/`StellariumActions` 事件没有队列缓冲会直接丢失，只有 URL 能保证首帧渲染
前生效。

- `webgui=1`：只给开发用，挂上完整 web GUI；宿主不要传。

#### 6. 为什么必须经 HTTP 服务加载、`file://` 不行

入口脚本是 `<script type="module" crossorigin>`，`file://` 页面 origin 为 `null`，会被
module script 的 CORS 检查拦截；wasm 与 `skydata/*`/`sky-i18n/*.json` 等数据源均用
`fetch()` 加载，不支持 `file:`；Flutter 的 `loadFlutterAsset` 拼不出带 query 的 URL，
第 5 节的 URL 播种参数也就无法工作。

