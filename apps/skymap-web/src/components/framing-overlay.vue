// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

<template>
  <div
    ref="overlay"
    class="jsbridge-overlay"
    style="overflow: hidden; position: fixed; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; display: flex; align-items: center; justify-content: center; z-index: 1001;"
  >
    <div
      v-if="showCenterFov && !showMosaic"
      :style="fovBoxStyle"
    >
      <div
        v-if="centerFovLabel || (rotatable && manualCenterRotation !== null)"
        :style="centerFovLabelBoxStyle"
      >
        <!-- 取整后再 % 360：359.5-359.99 经 toFixed(0) 会显示成 360，需回绕到 0（角度显示范围 0-359） -->
        {{ centerFovLabel }}<span v-if="rotatable && manualCenterRotation !== null"> {{ Math.round(Number(manualCenterRotation)) % 360 }}°</span>
      </div>
      <template v-if="rotatable">
        <div :style="rotationLineStyle" />
        <!-- 外层 56×56 只做触摸热区（透明），内层 44×44 才是可见圆形把手 -->
        <div
          :style="rotationHandleStyle"
          @pointerdown="onRotationPointerDown"
          @pointermove="onRotationPointerMove"
          @pointerup="onRotationPointerUp"
          @pointercancel="onRotationPointerUp"
        >
          <div :style="rotationHandleCircleStyle" />
        </div>
      </template>
    </div>
    <div
      v-if="showOffCenterRect"
      :style="offCenterRectStyle"
    >
      <div
        v-if="offCenterRectLabel"
        :style="offCenterRectLabelStyle"
      >
        {{ offCenterRectLabel }}
      </div>
    </div>
    <!-- Mosaic Grid -->
    <div
      v-for="tile in mosaicTiles"
      :key="tile.index"
      :style="tile.style"
      class="mosaic-tile"
    >
      <span class="mosaic-label">{{ tile.index }}</span>
    </div>
  </div>
</template>
<script>
// 取景 overlay：主镜取景框（含 PA 旋转把手）/ 赤道仪当前指向框 / 马赛克瓦片。
//
// 对 jsbridge.vue 只暴露四个方法：actions() / stateFields() / tick() /
// cameraLongEdgeDeg()。对基座的反向需求只有一条——改视场——走公开桥
// window.StellariumActions.updateFov，和 App 的用法一样，不碰父组件。
//
// rAF 循环只在任一取景框可见时跑（anyVisible）。原先挂载即启动、卸载才停，
// 什么都不显示时也每帧回调；引擎侧静态天空已压到 3 秒 1 帧，这里不该拖后腿。
import jsbridge from '@/utils/jsbridge'
import rotateHandIcon from '@/assets/images/rotate_hand.png'

export default {
  data: function () {
    return {
      showCenterFov: false,
      targetFovX: -1,
      targetFovY: -1,
      minFov: 0.1,
      maxFov: 50,
      fovBoxStyle: {
        width: '0px',
        height: '0px',
        background: 'rgba(244, 129, 35, 0.05)',
        border: '2px solid rgba(244, 129, 35, 0.7)',
        transform: 'rotate(0deg)',
        pointerEvents: 'none'
      },
      manualCenterRotation: null,
      // 中心框是否可拖动旋转（native 经 toggleCenterFov 的 rotatable 字段控制）
      rotatable: false,
      // 旋转把手拖动状态（pointerId），null = 未在拖
      rotationDrag: null,
      // 拖动中回传节流时间戳
      lastRotationPost: 0,
      isCenterCircle: false,
      centerFovLabel: '',
      centerFovLabelStyle: {
        position: 'absolute',
        bottom: '100%',
        left: '50%',
        transform: 'translateX(-50%)',
        whiteSpace: 'nowrap',
        textAlign: 'center',
        color: 'rgba(244, 129, 35, 0.9)',
        // 13 号加粗 + 星图字体：与 canvas 内星名/线标签同一字体家族（App.vue @font-face）
        fontSize: '13px',
        fontWeight: 'bold',
        fontFamily: "'SkyFont', sans-serif",
        marginBottom: '4px',
        pointerEvents: 'none'
      },
      // 旋转把手热区：框顶边中点上方，随框一起旋转；是 overlay 内唯一接收触摸的元素。
      // 56×56 全透明只为放大手指命中范围，可见圆形由内层 rotationHandleCircleStyle 画（44×44）。
      // 连接线长 18px：热区比圆大 6px（(56-44)/2），所以热区底边只抬 18-6=12px，
      // 圆的底边才正好落在框顶上方 18px
      rotationHandleStyle: {
        position: 'absolute',
        left: '50%',
        bottom: 'calc(100% + 12px)',
        transform: 'translateX(-50%)',
        width: '56px',
        height: '56px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        pointerEvents: 'auto',
        touchAction: 'none',
        cursor: 'grab'
      },
      // 可见把手：44×44 橙色圆 + 中心 24×24 旋转手势图标
      rotationHandleCircleStyle: {
        width: '44px',
        height: '44px',
        borderRadius: '50%',
        boxSizing: 'border-box',
        border: '2px solid rgba(244, 129, 35, 0.7)',
        background: `rgba(244, 129, 35, 0.3) url(${rotateHandIcon}) no-repeat center / 24px 24px`,
        pointerEvents: 'none'
      },
      rotationLineStyle: {
        position: 'absolute',
        left: '50%',
        bottom: '100%',
        transform: 'translateX(-50%)',
        width: '1px',
        height: '18px',
        background: 'rgba(244, 129, 35, 0.7)',
        pointerEvents: 'none'
      },
      fovAnimationId: null,
      lastRectParams: null,
      savedFovBeforeScale: null,
      showOffCenterRect: false,
      offCenterRectStyle: {
        position: 'absolute',
        width: '0px',
        height: '0px',
        background: 'rgba(60, 131, 255, 0.05)',
        border: '2px solid rgba(60, 131, 255, 0.7)',
        transform: 'translate(-50%, -50%) rotate(0deg)',
        left: '50%',
        top: '50%',
        overflow: 'visible',
        pointerEvents: 'none'
      },
      offCenterRectParams: null,
      offCenterRectLabel: '',
      offCenterRectLabelStyle: {
        position: 'absolute',
        top: '100%',
        left: '50%',
        transform: 'translateX(-50%)',
        whiteSpace: 'nowrap',
        textAlign: 'center',
        color: 'rgba(60, 131, 255, 0.9)',
        // 13 号加粗 + 星图字体，与中心框（Target）标签一致
        fontSize: '13px',
        fontWeight: 'bold',
        fontFamily: "'SkyFont', sans-serif",
        marginTop: '4px',
        pointerEvents: 'none'
      },
      // 马赛克网格数据
      showMosaic: false,
      mosaicConfig: {
        x: 2, // 横向个数
        y: 2, // 纵向个数
        overlap: 10 // 重叠百分比
      },
      mosaicTiles: [], // 存储每个 tile 的样式和信息
      lastMosaicUpdate: 0
    }
  },
  computed: {
    // 中心框标签位置：常规态挂在框上方（下方留给蓝框自己的 Current 标签，避免两条文字糊一起）；
    // 构图态（rotatable）改挂框下方并加粗放大 —— 此时框上方被旋转把手占住，
    // 且蓝框在构图模式下不带标签，下方是空的
    centerFovLabelBoxStyle () {
      if (!this.rotatable) return this.centerFovLabelStyle
      return {
        ...this.centerFovLabelStyle,
        bottom: 'auto',
        top: '100%',
        marginBottom: '0',
        marginTop: '6px',
        fontSize: '15px',
        fontWeight: 'bold'
      }
    },
    anyVisible () {
      return this.showCenterFov || this.showOffCenterRect || this.showMosaic
    }
  },
  watch: {
    anyVisible (v) {
      if (v) this.startFovAnimation()
      else this.stopFovAnimation()
    },
    '$store.state.stel.fov': function () {
      this.updateFovBox()
    }
  },
  mounted () {
    // 将 overlay 移到 body 层级，脱离 #app 的 stacking context
    // 这样 z-index:1001 能正确覆盖 #nightmode(z-index:1000)，不被夜间模式 multiply 混合影响
    if (this.$refs.overlay) {
      document.body.appendChild(this.$refs.overlay)
    }
    if (this.anyVisible) this.startFovAnimation()
  },
  beforeUnmount () {
    this.stopFovAnimation()
    // 清理：将 overlay 从 body 移除
    if (this.$refs.overlay && this.$refs.overlay.parentNode === document.body) {
      document.body.removeChild(this.$refs.overlay)
    }
  },
  methods: {
    // ── 对 jsbridge.vue 的接口 ──────────────────────────────────────────
    actions () {
      return {
        // 配置中心视场框的显示与否，以及大小
        toggleCenterFov: (data) => {
          if (typeof data === 'boolean') {
            this.showCenterFov = data
            this.isCenterCircle = false
            this.rotatable = false
          } else if (typeof data === 'object') {
            this.showCenterFov = true
            const fovX = Number(data.fovX)
            const fovY = Number(data.fovY)
            // 形状由 `shape` 说了算：'circle' 画圆，其余（含不传）画矩形。
            //
            // 圆要按给的尺寸画。**目镜的真实视场从 0.2° 到 3° 都有**，而下面那个
            // -1 哨兵只会画 2° ——给望远镜用户看一个固定 2° 的圈等于给他一个假数。
            const wantCircle = data.shape === 'circle'
            // 老哨兵：fovX 与 fovY 都是 -1 时画一个 2° 的圆。**留着不动**，
            // 宿主里还有按它调的旧代码；新代码一律走 `shape`。
            if (fovX === -1 && fovY === -1) {
              this.targetFovX = 2
              this.targetFovY = 2
              this.isCenterCircle = true
            } else {
              if (data.fovX !== undefined) {
                this.targetFovX = this.getFovLimit(fovX)
              }
              if (data.fovY !== undefined) {
                this.targetFovY = this.getFovLimit(fovY)
              }
              // 圆只认一个直径：取两边里大的那个，免得宿主传了不等的宽高之后
              // 画出一个椭圆——那不是任何一只目镜的视场。
              if (wantCircle) {
                const d = Math.max(this.targetFovX, this.targetFovY)
                this.targetFovX = d
                this.targetFovY = d
              }
              this.isCenterCircle = wantCircle
            }
            if (data.rotation !== undefined) {
              this.manualCenterRotation = data.rotation
            } else {
              this.manualCenterRotation = null
            }
            if (data.label !== undefined) {
              this.centerFovLabel = data.label
            } else {
              this.centerFovLabel = ''
            }
            this.rotatable = data.rotatable === true
          }

          if (this.showCenterFov) {
            this.updateFovBox()
          }
        },
        scaleFov2Target: () => {
          if (!this.lastRectParams) {
            console.warn('scaleFov2Target: No lastRectParams')
            return
          }

          // 1. Get Center View Vector in OBSERVED frame
          const vCenterView = [0, 0, -1]
          const vCenterObs = this.$stel.convertFrame(this.$stel.core.observer, 'VIEW', 'OBSERVED', vCenterView)

          // 2. Get Target Vector in OBSERVED frame
          const { alt, az, fovX, fovY } = this.lastRectParams
          const toRad = Math.PI / 180
          const vTargetObs = this.$stel.s2c(az * toRad, alt * toRad)

          // 3. Calculate Angle between current view center and target center
          const dot = vCenterObs[0] * vTargetObs[0] + vCenterObs[1] * vTargetObs[1] + vCenterObs[2] * vTargetObs[2]
          const val = Math.min(Math.max(dot, -1), 1)
          const angleRad = Math.acos(val)
          const angleDeg = angleRad / toRad

          // 4. Calculate new FOV based on:
          // - The angle from view center to target center
          // - The target rectangle's own size (need to see the entire rectangle)
          // The target's furthest corner is approximately at: angleDeg + max(fovX, fovY)/2
          const targetHalfSize = Math.max(fovX || 0, fovY || 0) / 2
          const maxDistance = angleDeg + targetHalfSize

          // To see a point at maxDistance from center, FOV needs to be 2 * maxDistance
          // Add 20% margin so the target is not at the very edge
          let newFov = maxDistance * 1.5

          if (newFov < 10) newFov = 10
          if (newFov > 80) newFov = 80

          const currentFov = this.$store.state.stel.fov * 180 / Math.PI

          if (currentFov > newFov) {
            return
          }

          // 保存当前 FOV，用于之后恢复
          this.savedFovBeforeScale = currentFov
          window.StellariumActions.updateFov(newFov)
        },
        // 恢复 scaleFov2Target 执行前的 FOV 值
        restoreScaledFov: () => {
          if (this.savedFovBeforeScale === null) {
            console.warn('restoreFov: No saved FOV to restore')
            return
          }
          window.StellariumActions.updateFov(this.savedFovBeforeScale)
          this.savedFovBeforeScale = null
        },
        /// 根据 app 的赤道仪的位置，实时绘制一个矩形，表示当前相机的视场范围
        /// 使用 DOM 元素渲染，避免大 FOV 时的形变
        drawRectWithAltAndAz: (ss) => {
          const alt = Number(ss.alt)
          const az = Number(ss.az)
          let fovX = Number(ss.fovX)
          let fovY = Number(ss.fovY)

          const rotation = ss.rotation !== undefined ? Number(ss.rotation) : (ss.angle !== undefined ? Number(ss.angle) : null)

          if (isNaN(alt) || isNaN(az)) {
            this.showOffCenterRect = false
            return
          }

          // 当 fovX 和 fovY 都为 -1 时，绘制一个 2° 的圆
          let isCircle = false
          if (fovX === -1 && fovY === -1) {
            fovX = 2
            fovY = 2
            isCircle = true
          } else {
            if (isNaN(fovX) || isNaN(fovY) || fovX < 0 || fovY < 0) {
              this.showOffCenterRect = false
              return
            }
            fovX = this.getFovLimit(fovX)
            fovY = this.getFovLimit(fovY)
          }

          this.lastRectParams = { alt, az, fovX, fovY, rotation }
          // Store params for animation loop update
          this.offCenterRectParams = { alt, az, fovX, fovY, rotation, isCircle }

          if (ss.label !== undefined) {
            this.offCenterRectLabel = ss.label
          } else {
            this.offCenterRectLabel = ''
          }

          this.showOffCenterRect = true
          this.updateOffCenterRect()
        },
        // 清除 off-center 矩形
        clearOffCenterRect: () => {
          this.showOffCenterRect = false
          this.offCenterRectParams = null
          this.offCenterRectLabel = ''
        },
        // 显示马赛克网格
        // 参数: { x: 横向个数, y: 纵向个数, overlap: 重叠百分比 }
        showMosaic: (config) => {
          if (!config || typeof config !== 'object') {
            this.showMosaic = false
            return
          }

          const x = Number(config.x) || 1
          const y = Number(config.y) || 1
          const overlap = Number(config.overlap) || 0

          // 验证参数
          if (x <= 0 || y <= 0 || overlap < 0 || overlap >= 100) {
            console.warn('showMosaic: Invalid config', config)
            return
          }

          // 如果传入了 fovX/fovY，更新 targetFovX/targetFovY
          if (config.fovX !== undefined) {
            this.targetFovX = this.getFovLimit(Number(config.fovX))
          }
          if (config.fovY !== undefined) {
            this.targetFovY = this.getFovLimit(Number(config.fovY))
          }

          // 支持 rotation 和 angle 两种字段名，与 toggleCenterFov 保持一致
          const rotation = config.rotation !== undefined ? Number(config.rotation) : (config.angle !== undefined ? Number(config.angle) : null)
          this.mosaicConfig = { x, y, overlap, rotation }
          this.showMosaic = true
          this.updateMosaic(true)
        },
        // 隐藏马赛克网格
        hideMosaic: () => {
          this.showMosaic = false
          this.mosaicTiles = []
        },
        // 获取马赛克 tile 中心坐标
        getMosaicCenters: () => {
          const centers = this.getMosaicTileCenters()
          jsbridge.postMessage('mosaicCenters', centers)
        }
      }
    },
    stateFields () {
      return {
        showMosaic: this.showMosaic,
        mosaicConfig: this.mosaicConfig
      }
    },
    tick () {
      this.updateFovBox()
    },
    cameraLongEdgeDeg () {
      return Math.max(this.targetFovX, this.targetFovY)
    },
    // ── overlay 方法从 jsbridge.vue 搬来 ────────────────────────────────
    // 在屏幕中心点绘制一个矩形 fov (DOM overlay with real-time rotation)
    updateFovBox () {
      if (!this.showCenterFov || !this.$stel || !this.$stel.canvas) return

      // Use buffer dimensions for precise aspect ratio
      const canvasWidth = this.$stel.canvas.width
      const canvasHeight = this.$stel.canvas.height
      const aspect = canvasWidth / canvasHeight

      // Use client dimensions for CSS pixel scaling (handles DPR)
      const clientHeight = this.$stel.canvas.clientHeight

      const targetFovXRad = (this.targetFovX || 10) * Math.PI / 180
      const targetFovYRad = (this.targetFovY || 5) * Math.PI / 180

      const fovYRad = this.$store.state.stel.fov
      let currentFovYRad = fovYRad

      // Handle aspect ratio effect on FOV definition in Stellarium
      if (aspect < 1) {
        currentFovYRad = 4 * Math.atan(Math.tan(fovYRad / 4) / aspect)
      }

      // Combined stereographic + perspective formula
      // Note: use clientHeight (CSS px) instead of canvasHeight (physical px) to fix 3x size issue
      const widthPx = clientHeight * Math.tan(targetFovXRad / 4) / Math.tan(currentFovYRad / 4)
      const heightPx = clientHeight * Math.tan(targetFovYRad / 4) / Math.tan(currentFovYRad / 4)

      // Calculate rotation to align with Alt-Az Up (Zenith)
      let angleDeg = 0
      if (this.manualCenterRotation !== null && this.manualCenterRotation !== undefined) {
        // manualCenterRotation 是 PA（自北起、向东为正）。calculateFovRotation 给出的是
        // 让框顶指北的 CSS 角；星图里东在屏幕左侧，而 CSS 正角顺时针，所以 PA 要减。
        const angleToNorth = this.calculateFovRotation()
        angleDeg = angleToNorth - this.manualCenterRotation
      } else {
        angleDeg = this.calculateFovRotation()
      }

      this.fovBoxStyle = {
        width: widthPx + 'px',
        height: heightPx + 'px',
        background: 'rgba(244, 129, 35, 0.05)',
        border: '2px solid rgba(244, 129, 35, 0.7)',
        borderRadius: this.isCenterCircle ? '50%' : '0',
        transform: `rotate(${angleDeg}deg) translateZ(0)`,
        willChange: 'transform',
        pointerEvents: 'none'
      }
    },
    // Calculate the rotation angle to align FOV box's long edge towards celestial north pole
    calculateFovRotation () {
      if (!this.$stel || !this.$stel.core) return 0

      const obs = this.$stel.core.observer

      // 1. Get screen center in ICRF coordinates
      const vCenterView = [0, 0, -1] // VIEW frame center direction
      const vCenterIcrf = this.$stel.convertFrame(obs, 'VIEW', 'ICRF', vCenterView)

      // 2. Calculate current center's RA/Dec
      const radec = this.$stel.c2s(vCenterIcrf)
      const ra = radec[0]
      const dec = radec[1]

      // 3. Create a point slightly north (higher dec) along the same RA
      const decOffset = 0.01 // Small offset in radians (~0.5 degrees)
      const northPointIcrf = this.$stel.s2c(ra, dec + decOffset)

      // 4. Convert both points to VIEW frame
      const centerView = this.$stel.convertFrame(obs, 'ICRF', 'VIEW', vCenterIcrf)
      const northView = this.$stel.convertFrame(obs, 'ICRF', 'VIEW', northPointIcrf)

      // 5. Calculate direction vector in VIEW frame
      const dx = northView[0] - centerView[0]
      const dy = northView[1] - centerView[1]

      // 6. Convert to screen coordinates (Y is flipped in screen space)
      const screenDx = dx
      const screenDy = -dy

      // 7. Calculate angle to align Top of FOV box towards north
      // Default: Width (fovX) is X-axis, Height (fovY) is Y-axis (down)
      // Top of box is -Y axis (up relative to box)
      // We want Top (-Y) to point towards North
      // Box X-axis (Width) is 90 degrees clockwise from Top (-Y)
      // So if North is at angle 'a', we want X-axis at 'a + 90'
      const angleRad = Math.atan2(screenDy, screenDx)
      return (angleRad * 180 / Math.PI) + 90
    },
    // 旋转把手拖动开始：锁定 pointer capture，阻止事件穿透到星图 canvas
    onRotationPointerDown (e) {
      e.target.setPointerCapture(e.pointerId)
      this.rotationDrag = { pointerId: e.pointerId }
      e.preventDefault()
      e.stopPropagation()
    },
    // 旋转把手拖动中：按指针相对屏幕中心方位角换算 PA，节流 100ms 回传 native
    onRotationPointerMove (e) {
      if (!this.rotationDrag || e.pointerId !== this.rotationDrag.pointerId) return
      const cx = window.innerWidth / 2
      const cy = window.innerHeight / 2
      const theta = Math.atan2(e.clientY - cy, e.clientX - cx) * 180 / Math.PI
      const cssAngle = theta + 90
      const angleToNorth = this.calculateFovRotation()
      let pa = angleToNorth - cssAngle
      pa = ((pa % 360) + 360) % 360
      this.manualCenterRotation = pa
      const now = Date.now()
      if (now - this.lastRotationPost > 100) {
        jsbridge.postMessage('centerFovRotation', { pa })
        this.lastRotationPost = now
      }
    },
    // 旋转把手抬手：结束拖动，回传终值（不受节流限制，保证最终帧一定送达）
    onRotationPointerUp (e) {
      if (!this.rotationDrag || e.pointerId !== this.rotationDrag.pointerId) return
      this.rotationDrag = null
      if (this.manualCenterRotation !== null) {
        jsbridge.postMessage('centerFovRotation', { pa: this.manualCenterRotation })
      }
    },
    // Update off-center rectangle position and size using DOM (like updateFovBox)
    updateOffCenterRect () {
      if (!this.showOffCenterRect || !this.offCenterRectParams || !this.$stel || !this.$stel.canvas) {
        return
      }

      const { alt, az, fovX, fovY, rotation, isCircle } = this.offCenterRectParams
      const toRad = Math.PI / 180

      // 1. Convert Alt/Az to direction vector in OBSERVED frame
      const azR = az * toRad
      const altR = alt * toRad
      const vObserved = this.$stel.s2c(azR, altR)

      // 2. Convert to VIEW frame
      const obs = this.$stel.core.observer
      const vView = this.$stel.convertFrame(obs, 'OBSERVED', 'VIEW', vObserved)

      // 3. Check if the point is in front of the camera (z < 0 in VIEW frame means visible)
      if (vView[2] >= 0) {
        // Point is behind the camera, hide the rect
        this.offCenterRectStyle = {
          ...this.offCenterRectStyle,
          display: 'none'
        }
        return
      }

      // 4. Project to screen coordinates using Stellarium's projection
      // The simplest approach: use the canvas project function if available
      // Alternative: manual projection using stereographic formula

      // Get canvas dimensions
      const canvas = this.$stel.canvas
      const clientWidth = canvas.clientWidth
      const clientHeight = canvas.clientHeight

      // Simple perspective projection from VIEW frame to screen
      // VIEW frame: z points towards viewer, x points right, y points up
      // Screen: origin at top-left, x points right, y points down
      // For stereographic projection: r = 2 * f * tan(theta/2) where theta is angle from center

      // Using the stereographic projection formula
      const fovYRad = this.$store.state.stel.fov

      // Account for aspect ratio in FOV calculation
      // When aspect < 1 (portrait), core->fov is actually fovX (shorter edge),
      // so we need to compute the real vertical FOV first
      const aspect = canvas.width / canvas.height
      let currentFovYRad = fovYRad
      if (aspect < 1) {
        currentFovYRad = 4 * Math.atan(Math.tan(fovYRad / 4) / aspect)
      }

      // Calculate the focal length in pixels using the real vertical FOV
      // In stereographic projection: r_screen = 2 * f * tan(theta/2)
      // At the edge, theta = fov/2, r_screen = height/2
      // So: height/2 = 2 * f * tan(fov/4)
      // f = height / (4 * tan(fov/4))
      const focalLength = clientHeight / (4 * Math.tan(currentFovYRad / 4))

      // Project the center point
      // vView is [x, y, z] where z is negative for visible points
      // Stereographic projection: screen_x = 2 * f * (vView.x / (1 - vView.z/|v|))
      const vNorm = Math.sqrt(vView[0] * vView[0] + vView[1] * vView[1] + vView[2] * vView[2])
      const factor = 2 * focalLength / (1 - vView[2] / vNorm)
      const screenX = clientWidth / 2 + factor * vView[0]
      const screenY = clientHeight / 2 - factor * vView[1] // Y is flipped

      // 5. Calculate rectangle size in screen pixels
      // Use the same formula as updateFovBox
      const targetFovXRad = fovX * toRad
      const targetFovYRad = fovY * toRad

      const widthPx = clientHeight * Math.tan(targetFovXRad / 4) / Math.tan(currentFovYRad / 4)
      const heightPx = clientHeight * Math.tan(targetFovYRad / 4) / Math.tan(currentFovYRad / 4)

      // 6. Calculate rotation angle
      // Similar to calculateFovRotation but at the specified Alt/Az position
      let angleDeg = 0
      if (rotation !== null && rotation !== undefined && !isNaN(rotation)) {
        // If manual rotation is provided, use it relative to North
        const angleToNorth = this.calculateFovRotationAt(az, alt)
        angleDeg = angleToNorth - rotation
      } else {
        angleDeg = this.calculateFovRotationAt(az, alt)
      }

      // 7. Update style
      this.offCenterRectStyle = {
        position: 'absolute',
        width: widthPx + 'px',
        height: heightPx + 'px',
        background: 'rgba(60, 131, 255, 0.05)',
        border: '2px solid rgba(60, 131, 255, 0.7)',
        borderRadius: isCircle ? '50%' : '0',
        transform: `translate(-50%, -50%) rotate(${angleDeg}deg) translateZ(0)`,
        willChange: 'transform',
        left: screenX + 'px',
        top: screenY + 'px',
        display: 'block',
        overflow: 'visible',
        pointerEvents: 'none'
      }
    },
    // Calculate FOV rotation at a specific Alt/Az position
    calculateFovRotationAt (azDeg, altDeg) {
      if (!this.$stel || !this.$stel.core) return 0

      const obs = this.$stel.core.observer
      const toRad = Math.PI / 180

      // 1. Get position in ICRF coordinates
      const azR = azDeg * toRad
      const altR = altDeg * toRad
      const vObserved = this.$stel.s2c(azR, altR)
      const vCenterIcrf = this.$stel.convertFrame(obs, 'OBSERVED', 'ICRF', vObserved)

      // 2. Calculate current position's RA/Dec
      const radec = this.$stel.c2s(vCenterIcrf)
      const ra = radec[0]
      const dec = radec[1]

      // 3. Create a point slightly north (higher dec) along the same RA
      const decOffset = 0.01 // Small offset in radians (~0.5 degrees)
      const northPointIcrf = this.$stel.s2c(ra, dec + decOffset)

      // 4. Convert both points to VIEW frame
      const centerView = this.$stel.convertFrame(obs, 'ICRF', 'VIEW', vCenterIcrf)
      const northView = this.$stel.convertFrame(obs, 'ICRF', 'VIEW', northPointIcrf)

      // 5. Calculate direction vector in VIEW frame
      const dx = northView[0] - centerView[0]
      const dy = northView[1] - centerView[1]

      // 6. Convert to screen coordinates (Y is flipped in screen space)
      const screenDx = dx
      const screenDy = -dy

      // 7. Calculate angle to align Top of FOV box towards north
      const angleRad = Math.atan2(screenDy, screenDx)
      return (angleRad * 180 / Math.PI) + 90
    },
    // Start real-time animation loop for FOV box rotation
    startFovAnimation () {
      // 幂等守卫：重复调用会用新 id 覆盖 fovAnimationId，导致第一个 rAF 循环
      // 再也不会被 stopFovAnimation 取消，从而常开一个不受控的 rAF
      if (this.fovAnimationId) return
      const animate = () => {
        if (this.showCenterFov) {
          this.updateFovBox()
        }
        if (this.showOffCenterRect) {
          this.updateOffCenterRect()
        }
        if (this.showMosaic) {
          this.updateMosaic(false)
        }
        this.fovAnimationId = requestAnimationFrame(animate)
      }
      this.fovAnimationId = requestAnimationFrame(animate)
    },
    // Stop animation loop
    stopFovAnimation () {
      if (this.fovAnimationId) {
        cancelAnimationFrame(this.fovAnimationId)
        this.fovAnimationId = null
      }
    },
    // 更新马赛克网格
    updateMosaic (needUpdateFov = false) {
      if (!this.showMosaic || !this.$stel || !this.$stel.canvas) {
        this.mosaicTiles = []
        return
      }

      const { x, y, overlap, rotation: mosaicRotation } = this.mosaicConfig
      if (x <= 0 || y <= 0) {
        this.mosaicTiles = []
        return
      }

      const canvas = this.$stel.canvas
      const clientWidth = canvas.clientWidth
      const clientHeight = canvas.clientHeight

      // 获取当前 FOV
      const fovYRad = this.$store.state.stel.fov
      const aspect = canvas.width / canvas.height
      let currentFovYRad = fovYRad
      if (aspect < 1) {
        currentFovYRad = 4 * Math.atan(Math.tan(fovYRad / 4) / aspect)
      }

      // 单个 tile 的角度大小（与 centerFov 相同）
      const targetFovXRad = (this.targetFovX || 10) * Math.PI / 180
      const targetFovYRad = (this.targetFovY || 5) * Math.PI / 180

      // 计算单个 tile 的屏幕尺寸
      const tileWidthPx = clientHeight * Math.tan(targetFovXRad / 4) / Math.tan(currentFovYRad / 4)
      const tileHeightPx = clientHeight * Math.tan(targetFovYRad / 4) / Math.tan(currentFovYRad / 4)

      // 计算有效步进（考虑重叠）- 角度空间
      const overlapFactor = 1 - overlap / 100
      const stepXAngle = (this.targetFovX || 10) * overlapFactor // 角度步进
      const stepYAngle = (this.targetFovY || 5) * overlapFactor
      // 屏幕步进
      const stepXPx = tileWidthPx * overlapFactor
      const stepYPx = tileHeightPx * overlapFactor

      // 生成 tiles
      const tiles = []
      let index = 1

      // 获取中心 FOV 框的旋转角度（作为参考）
      const centerRotation = this.calculateFovRotation()

      let minScreenX = Infinity
      let maxScreenX = -Infinity
      let minScreenY = Infinity
      let maxScreenY = -Infinity

      for (let row = 0; row < y; row++) {
        for (let col = 0; col < x; col++) {
          // 计算相对于中心的屏幕偏移（未旋转）
          const offsetXPx = (col - (x - 1) / 2) * stepXPx
          const offsetYPx = (row - (y - 1) / 2) * stepYPx

          // 应用中心旋转变换来获得屏幕位置（用于绘制）
          const rotRad = centerRotation * Math.PI / 180
          const rotatedOffsetX = offsetXPx * Math.cos(rotRad) - offsetYPx * Math.sin(rotRad)
          const rotatedOffsetY = offsetXPx * Math.sin(rotRad) + offsetYPx * Math.cos(rotRad)

          // 屏幕坐标（相对于画布中心）
          const screenX = clientWidth / 2 + rotatedOffsetX
          const screenY = clientHeight / 2 + rotatedOffsetY

          // 计算该 tile 中心的 RA/Dec 和 Alt/Az
          // 使用角度偏移直接在 VIEW frame 中计算，而不是用旋转后的屏幕坐标逆投影
          const offsetXAngle = (col - (x - 1) / 2) * stepXAngle * Math.PI / 180
          const offsetYAngle = (row - (y - 1) / 2) * stepYAngle * Math.PI / 180
          const tileCenter = this.calculateTileCenter(offsetXAngle, offsetYAngle)

          // 计算该 tile 位置的独立 PA
          let tileRotation = centerRotation
          if (tileCenter && tileCenter.az !== undefined && tileCenter.alt !== undefined) {
            tileRotation = this.calculateFovRotationAt(tileCenter.az, tileCenter.alt)
            // 如果有手动设置的旋转角度，应用它（优先使用 mosaic 自己的 rotation，否则使用 centerFov 的）
            const effectiveRotation = (mosaicRotation !== null && mosaicRotation !== undefined) ? mosaicRotation : this.manualCenterRotation
            if (effectiveRotation !== null && effectiveRotation !== undefined) {
              tileRotation = tileRotation - effectiveRotation
            }
          }

          // 计算 bounding box
          const w = tileWidthPx / 2
          const h = tileHeightPx / 2
          const rad = tileRotation * Math.PI / 180
          const cos = Math.cos(rad)
          const sin = Math.sin(rad)

          const corners = [
            { x: w, y: -h },
            { x: -w, y: -h },
            { x: -w, y: h },
            { x: w, y: h }
          ]

          corners.forEach(p => {
            const rx = p.x * cos - p.y * sin
            const ry = p.x * sin + p.y * cos
            const cx = screenX + rx
            const cy = screenY + ry

            if (cx < minScreenX) minScreenX = cx
            if (cx > maxScreenX) maxScreenX = cx
            if (cy < minScreenY) minScreenY = cy
            if (cy > maxScreenY) maxScreenY = cy
          })

          tiles.push({
            index,
            col,
            row,
            screenX,
            screenY,
            ra: tileCenter ? tileCenter.ra : null,
            dec: tileCenter ? tileCenter.dec : null,
            az: tileCenter ? tileCenter.az : null,
            alt: tileCenter ? tileCenter.alt : null,
            pa: tileRotation,
            style: {
              position: 'absolute',
              width: tileWidthPx + 'px',
              height: tileHeightPx + 'px',
              left: screenX + 'px',
              top: screenY + 'px',
              transform: `translate(-50%, -50%) rotate(${tileRotation}deg) translateZ(0)`,
              willChange: 'transform',
              border: '1px dashed rgba(244, 129, 35, 0.7)',
              background: 'rgba(244, 129, 35, 0.05)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxSizing: 'border-box',
              pointerEvents: 'none'
            }
          })
          index++
        }
      }

      this.mosaicTiles = tiles

      // 节流发送 mosaic tiles 数据给 native (10fps)
      const now = Date.now()
      if (now - this.lastMosaicUpdate > 500) {
        jsbridge.postMessage('mosaicCenters', this.getMosaicTileCenters())
        this.lastMosaicUpdate = now
      }

      if (needUpdateFov === false) return
      // 自动调整 FOV 逻辑
      // 计算 bounding box 的宽和高
      const mosaicWidth = maxScreenX - minScreenX
      const mosaicHeight = maxScreenY - minScreenY

      // 如果马赛克超出屏幕，计算需要的缩放比例
      if (mosaicWidth > clientWidth || mosaicHeight > clientHeight) {
        // 计算需要的缩放系数（增加一点 padding，例如 1.05）
        const scaleX = mosaicWidth / clientWidth
        const scaleY = mosaicHeight / clientHeight
        const requiredScale = Math.max(scaleX, scaleY) * 1.05

        if (requiredScale > 1.01) { // 设置一个小阈值防止抖动
          // 根据缩放系数计算新的 FOV
          // 公式: tan(newFov/4) = tan(currentFov/4) * requiredScale
          const newTan = Math.tan(currentFovYRad / 4) * requiredScale
          const newFovRad = 4 * Math.atan(newTan)
          const newFovDeg = newFovRad * 180 / Math.PI

          // 限制最大 FOV
          if (newFovDeg <= 180) {
            this.$stel.zoomTo(newFovRad, 0.5)
          }
        }
      }
    },
    // 根据角度偏移计算 tile 中心的 RA/Dec 和 Alt/Az
    // offsetXAngle, offsetYAngle: 相对于屏幕中心的角度偏移（弧度）
    // 这个方法直接在 VIEW frame 中计算，避免屏幕坐标旋转后再逆投影导致的误差
    calculateTileCenter (offsetXAngle, offsetYAngle) {
      if (!this.$stel || !this.$stel.core) return null

      const obs = this.$stel.core.observer

      // 1. 获取屏幕中心的 VIEW 方向
      const vCenterView = [0, 0, -1]

      // 2. 获取屏幕中心的 ICRF 坐标
      const vCenterIcrf = this.$stel.convertFrame(obs, 'VIEW', 'ICRF', vCenterView)
      const centerRaDec = this.$stel.c2s(vCenterIcrf)
      const centerRa = centerRaDec[0]
      const centerDec = centerRaDec[1]

      // 3. 计算 tile 在赤道坐标系中的偏移
      // 屏幕 X 正向（向右）对应天球西方，RA 减小
      // 屏幕 Y 正向（向下）对应 Dec 减小
      // 注意：RA 偏移需要除以 cos(dec) 来修正
      const cosDec = Math.cos(centerDec)
      const raOffset = cosDec > 0.01 ? -offsetXAngle / cosDec : -offsetXAngle
      const decOffset = -offsetYAngle

      // 4. 计算新的 RA/Dec
      const tileRa = centerRa + raOffset
      const tileDec = centerDec + decOffset

      // 5. 转换回 ICRF 笛卡尔坐标
      const vTileIcrf = this.$stel.s2c(tileRa, tileDec)

      // 6. 转换到 OBSERVED frame 获取 Alt/Az
      const vTileObs = this.$stel.convertFrame(obs, 'ICRF', 'OBSERVED', vTileIcrf)
      const azalt = this.$stel.c2s(vTileObs)

      return {
        // Normalize RA into [0, 2π) before reporting: centerRa comes from
        // atan2 (range (-π, π]) and tileRa can fall outside it, so without anp
        // a tile in the RA 12h–24h half would post a negative hour value.
        ra: this.$stel.anp(tileRa) * 180 / Math.PI / 15, // 转换为小时（1h = 15°）
        dec: tileDec * 180 / Math.PI,
        az: this.$stel.anp(azalt[0]) * 180 / Math.PI,
        alt: azalt[1] * 180 / Math.PI
      }
    },
    // 获取所有马赛克 tile 的中心坐标
    getMosaicTileCenters () {
      return this.mosaicTiles.map(tile => ({
        index: tile.index,
        ra: tile.ra,
        dec: tile.dec,
        az: tile.az,
        alt: tile.alt,
        pa: tile.pa
      }))
    },
    getFovLimit: function (fov) {
      let newFov = fov
      if (newFov < this.minFov) newFov = this.minFov
      if (newFov > this.maxFov) newFov = this.maxFov
      return newFov
    }
  }
}
</script>

<style scoped>
.mosaic-tile {
  pointer-events: none;
  will-change: transform;
  -webkit-transform: translateZ(0);
  transform: translateZ(0);
  -webkit-backface-visibility: hidden;
  backface-visibility: hidden;
}

.mosaic-label {
  color: rgba(244, 129, 35, 0.9);
  font-size: 14px;
  font-weight: bold;
  text-shadow: 0 0 3px black, 0 0 6px black;
  user-select: none;
  pointer-events: none;
}
</style>
