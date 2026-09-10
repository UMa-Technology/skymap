// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

<template>
  <div style="display: none"></div>
</template>
<script>
import jsbridge from '@/utils/jsbridge'
import swh from '@/assets/sw_helpers'

export default {
  components: {},
  data: function () {
    return {
      updateTimer: undefined
    }
  },
  beforeUnmount () {
    if (this.updateTimer) {
      clearInterval(this.updateTimer)
      this.updateTimer = undefined
    }
  },
  computed: {
    selectedObject: function () {
      return this.$store.state.selectedObject
    },
    showPointToButton: function () {
      if (!this.$store.state.stel.lock) return true
      if (this.$store.state.stel.lock !== this.$store.state.stel.selection) return true
      return false
    },
    stelSelectionId: function () {
      return this.$store.state.stel && this.$store.state.stel.selection ? this.$store.state.stel.selection : undefined
    }
  },
  watch: {
    selectedObject: function (newObject) {
      // 停止之前的定时器
      if (this.updateTimer) {
        clearInterval(this.updateTimer)
        this.updateTimer = undefined
      }

      if (newObject) {
        // 立即发送一次数据
        this.sendSelectedObjectData()
        // 启动定时器，每秒更新一次位置信息（ra/dec 和 az/alt 会随时间变化）
        this.updateTimer = setInterval(() => {
          this.sendSelectedObjectData()
        }, 3000)
      } else {
        jsbridge.postMessage('selectedObjectChanged', null)
        console.log('selectedObjectChanged', null)
      }
    },
    showPointToButton: function (show) {
      // 居中按钮是否显示,如果当前选中的天体没有居中，那就会要求显示这个按钮
      jsbridge.postMessage('showPointToButtonChanged', show)
    },
    stelSelectionId: function (s) {
      if (!this.$stel.core.selection) {
        this.$store.commit('setSelectedObject', 0)
        return
      }
      // 基座的 sweObj2SkySource 统一返回 Promise（离线时 resolve 本地数据）
      swh.sweObj2SkySource(this.$stel.core.selection).then(res => {
        this.$store.commit('setSelectedObject', res)
      }, err => {
        console.log("Couldn't find info for object " + s + ':' + err)
        this.$store.commit('setSelectedObject', 0)
      })
    }
  },
  methods: {
    // 发送选中天体数据给 App
    sendSelectedObjectData () {
      const newObject = this.selectedObject
      if (!newObject) return
      const that = this
      const obj = this.$stel.core.selection

      const result = {
        title: swh.namesForSkySource(this.selectedObject, 26),
        name: newObject.names || [],
        culturalNames: newObject.culturalNames || [],
        model: newObject.model || '',
        types: newObject.types || [],
        model_data: newObject.model_data || {},
        horizons_id: obj?.jsonData?.model_data?.horizons_id || null
      }
      const formatRA = function (a) {
        // Decimal hours = hours + minutes/60 + seconds/3600.
        const raf = that.$stel.a2tf(a, 1)
        return raf.hours + raf.minutes / 60 + raf.seconds / 3600
      }
      const formatDec = function (a) {
        const raf = that.$stel.a2af(a, 1)
        // 正确转换：十进制度 = degrees + arcminutes/60 + arcseconds/3600
        const decimalDegrees = Math.abs(raf.degrees) + raf.arcminutes / 60 + raf.arcseconds / 3600
        return raf.sign === '-' ? -decimalDegrees : decimalDegrees
      }
      const formatAz = function (a) {
        const raf = that.$stel.a2af(a, 1)
        // 正确转换：十进制度 = degrees + arcminutes/60 + arcseconds/3600
        const degrees = raf.degrees < 0 ? raf.degrees + 360 : raf.degrees
        return degrees + raf.arcminutes / 60 + raf.arcseconds / 3600
      }
      // 获取 Ra/Dec (赤经赤纬)
      if (obj) {
        // Get J2000 (ICRF) vector
        const vIcrf = obj.getInfo('radec')
        const radecIcrf = this.$stel.c2s(vIcrf)
        const raIcrf = this.$stel.anp(radecIcrf[0])
        const decIcrf = this.$stel.anpm(radecIcrf[1])

        // Get JNow vector
        const vJnow = this.$stel.convertFrame(this.$stel.core.observer, 'ICRF', 'JNOW', vIcrf)
        const radecJnow = this.$stel.c2s(vJnow)
        const raJnow = this.$stel.anp(radecJnow[0])
        const decJnow = this.$stel.anpm(radecJnow[1])

        result.ra = formatRA(raJnow)
        result.dec = formatDec(decJnow)
        result.ra_j2000 = formatRA(raIcrf)
        result.dec_j2000 = formatDec(decIcrf)

        // 获取 Az/Alt (方位角/高度角)
        const azalt = this.$stel.c2s(this.$stel.convertFrame(this.$stel.core.observer, 'ICRF', 'OBSERVED', obj.getInfo('radec')))
        result.az = formatAz(this.$stel.anp(azalt[0]))
        result.alt = formatDec(this.$stel.anpm(azalt[1]))

        // 获取 Magnitude (星等)
        const vmag = obj.getInfo('vmag')
        if (vmag && !isNaN(vmag)) {
          result.vmag = vmag
          result.magnitude = vmag
        }

        // 获取距离
        const distance = obj.getInfo('distance')
        if (distance && !isNaN(distance)) {
          result.distance = distance // 单位：AU
        }

        // 获取相位
        const phase = obj.getInfo('phase')
        if (phase && !isNaN(phase)) {
          result.phase = phase
        }

        // 获取 Visibility (可见性)
        const vis = obj.computeVisibility()
        if (vis && vis.length > 0) {
          if (vis[0].rise === null) {
            result.visibility = 'always_visible'
            result.visibilityInfo = {
              status: 'always_visible',
              rise: null,
              set: null
            }
          } else {
            // computeVisibility returns TT MJD, but setMJD expects UTC MJD;
            // convert with the observer's own ΔT (tt - utc, ~69s in 2026) or
            // the rise/set timestamps land about a minute late.
            const observer = this.$stel.core.observer
            const deltaTDays = observer.tt - observer.utc
            const toTimestamp = (ttMjd) => {
              if (ttMjd == null) return null
              const d = new Date()
              d.setMJD(ttMjd - deltaTDays)
              return d.getTime() // 11位时间戳（毫秒）
            }

            result.visibility = 'visible'
            result.visibilityInfo = {
              status: 'visible',
              rise: toTimestamp(vis[0].rise),
              set: toTimestamp(vis[0].set)
            }
          }
        } else {
          result.visibility = 'not_visible'
          result.visibilityInfo = {
            status: 'not_visible',
            rise: null,
            set: null
          }
        }
      }

      jsbridge.postMessage('selectedObjectChanged', result)
      console.log('selectedObjectChanged', JSON.stringify(result))
    }
  }
}
</script>
