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

