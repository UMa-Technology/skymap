// Stellarium Web - Copyright (c) 2022 - Stellarium Labs SRL
//
// This program is licensed under the terms of the GNU AGPL v3, or
// alternatively under a commercial licence.
//
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

<template>
  <!-- Time readout + picker entry. Transparent button; the picker floats down
       from it (activator lives top-right, below the toolbar). -->
  <v-menu :close-on-content-click="false" transition="v-slide-y-transition" location="bottom end" offset="6">
    <template v-slot:activator="{ props }">
      <v-btn variant="text" rounded="pill" class="text-white" style="background: rgba(66,66,66,0.5) !important; padding: 6px 18px; height: auto;" v-bind="props">
        <v-icon start>mdi-clock-outline</v-icon>
        <span style="text-align: left; line-height: 1.1;">
          <div class="text-subtitle-2">{{ time }}</div>
          <div class="text-caption">{{ date }}</div>
        </span>
      </v-btn>
    </template>
    <date-time-picker v-model="pickerDate" :location="$store.state.currentLocation"></date-time-picker>
  </v-menu>
</template>

<script>

import DateTimePicker from '@/components/date-time-picker.vue'
import Moment from 'moment'

export default {
  components: { DateTimePicker },
  computed: {
    time: function () {
      return this.getLocalTime().format('HH:mm:ss')
    },
    date: function () {
      return this.getLocalTime().format('YYYY-MM-DD')
    },
    pickerDate: {
      get: function () {
        const t = this.getLocalTime()
        t.milliseconds(0)
        return t.format()
      },
      set: function (v) {
        const m = Moment(v)
        m.local()
        m.milliseconds(this.getLocalTime().milliseconds())
        this.$stel.core.observer.utc = m.toDate().getMJD()
      }
    }
  },
  methods: {
    // The MomentJS time in local time
    getLocalTime: function () {
      var d = new Date()
      d.setMJD(this.$store.state.stel.observer.utc)
      const m = Moment(d)
      m.local()
      return m
    }
  }
}
</script>
