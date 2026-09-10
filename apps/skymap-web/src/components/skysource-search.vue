// Stellarium Web - Copyright (c) 2022 - Stellarium Labs SRL
//
// This program is licensed under the terms of the GNU AGPL v3, or
// alternatively under a commercial licence.
//
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

<template>
  <div style="position: relative;" v-click-outside="resetSearch">
    <v-text-field prepend-icon="mdi-magnify" :label="$t('Search...')" v-model="searchText" @keyup.esc="resetSearch()" hide-details single-line></v-text-field>
    <v-list density="compact" v-if="showList" lines="two" :style="listStyle">
      <v-list-item v-for="source in autoCompleteChoices" :key="source.names[0]" @click="sourceClicked(source)"
        :title="nameForSkySource(source)" :subtitle="typeToName(source.types[0])">
        <template #prepend><img :src="iconForSkySource(source)" style="margin-right: 12px;"/></template>
      </v-list-item>
    </v-list>
  </div>
</template>

<script>
import swh from '@/assets/sw_helpers.js'
import debounce from 'lodash/debounce'

export default {
  data: function () {
    return {
      autoCompleteChoices: [],
      searchText: '',
      lastQuery: undefined
    }
  },
  props: ['modelValue', 'floatingList'],
  emits: ['update:modelValue'],
  watch: {
    searchText: function () {
      if (this.searchText === '') {
        this.autoCompleteChoices = []
        this.lastQuery = undefined
        return
      }
      this.refresh()
    }
  },
  computed: {
    listStyle: function () {
      return this.floatingList ? 'position: absolute; z-index: 1000; margin-top: 8px' : ''
    },
    showList: function () {
      return this.searchText !== ''
    }
  },
  methods: {
    sourceClicked: function (val) {
      this.$emit('update:modelValue', val)
      this.resetSearch()
    },
    resetSearch: function () {
      this.searchText = ''
    },
    refresh: debounce(function () {
      var that = this
      let str = that.searchText
      str = str.toUpperCase()
      str = str.replace(/\s+/g, '')
      if (this.lastQuery === str) {
        return
      }
      this.lastQuery = str
      swh.querySkySources(str, 10).then(results => {
        if (str !== that.lastQuery) {
          console.log('Cancelled query: ' + str)
          return
        }
        that.autoCompleteChoices = results
      }, err => { console.log(err) })
    }, 200),
    nameForSkySource: function (s) {
      const cn = swh.cleanupOneSkySourceName(s.match)
      const n = swh.nameForSkySource(s)
      if (cn === n) {
        return n
      } else {
        return cn + ' (' + n + ')'
      }
    },
    typeToName: function (t) {
      return swh.nameForSkySourceType(t)
    },
    iconForSkySource: function (s) {
      return swh.iconForSkySource(s)
    }
  },
  mounted: function () {
    var that = this
    const onClick = e => {
      if (that.searchText !== '') {
        that.searchText = ''
      }
    }
    const guiParent = document.querySelector('stel') || document.body
    guiParent.addEventListener('click', onClick, false)
  },
  directives: {
    // Local Vue 3 replacement for the removed v-click-outside package.
    clickOutside: {
      mounted (el, binding) {
        el.__clickOutside = (e) => {
          if (!(el === e.target || el.contains(e.target))) binding.value(e)
        }
        document.addEventListener('click', el.__clickOutside, true)
      },
      unmounted (el) {
        document.removeEventListener('click', el.__clickOutside, true)
        delete el.__clickOutside
      }
    }
  }
}
</script>

<style>

</style>
