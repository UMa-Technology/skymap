// Stellarium Web - Copyright (c) 2022 - Stellarium Labs SRL
//
// This program is licensed under the terms of the GNU AGPL v3, or
// alternatively under a commercial licence.
//
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

<template>
  <div class="target-search" ref="box" style="position: relative;">
    <v-text-field v-model="searchText" prepend-inner-icon="mdi-magnify"
      :placeholder="$t('Search...')" autocomplete="off"
      density="compact" variant="plain" hide-details single-line
      @update:model-value="onInput" @focus="onFocus" @blur="onBlur"
      @keyup.enter="onEnter" @keyup.esc="close"></v-text-field>
    <!-- Teleported to <body> so the toolbar's overflow can't clip it. Positioned
         (fixed) 12px below the top nav bar, anchored to the box's right edge. -->
    <teleport to="body">
      <v-list v-if="showList" class="search-results" :style="menuStyle"
        density="compact" @mousedown.prevent>
        <v-list-item v-for="r in results" :key="r.key" :title="r.label"
          @click="select(r)"></v-list-item>
      </v-list>
    </teleport>
  </div>
</template>

<script>
import swh from '@/assets/sw_helpers.js'
import debounce from 'lodash/debounce'

export default {
  data: function () {
    return {
      searchText: '',
      results: [],
      focused: false,
      menuStyle: {}
    }
  },
  computed: {
    showList: function () {
      return this.focused && this.results.length > 0
    }
  },
  methods: {
    onFocus: function () {
      this.focused = true
      const that = this
      swh.ensureSearchIndex().then(function () { that.refresh(that.searchText) })
    },
    onBlur: function () {
      // Delay so a click on a result still registers before we close. The list's
      // @mousedown.prevent keeps the field focused during the click, so this
      // only fires for clicks truly outside the box.
      const that = this
      setTimeout(function () { that.focused = false }, 150)
    },
    onInput: function (val) {
      this.refresh(val)
    },
    refresh: debounce(function (val) {
      this.results = swh.searchSkySuggestions(val, 12)
      this.updatePosition()
    }, 120),
    updatePosition: function () {
      if (!this.$refs.box) return
      const box = this.$refs.box.getBoundingClientRect()
      // 12px below the top nav bar (#toolbar-image), right-aligned to the box.
      const bar = document.getElementById('toolbar-image')
      const top = (bar ? bar.getBoundingClientRect().bottom : box.bottom) + 12
      this.menuStyle = {
        top: top + 'px',
        right: (window.innerWidth - box.right) + 'px'
      }
    },
    onEnter: function () {
      if (this.results.length) { this.select(this.results[0]); return }
      const obj = swh.searchSkyObject(this.searchText)
      if (obj) { swh.setSweObjAsSelection(obj); this.close() }
    },
    // A result was clicked: resolve + centre on it, then close cleanly.
    select: function (r) {
      this.selectByKey(r.key, 6)
      this.close()
    },
    // getObj can miss on the first try if the object's DSO survey tile is still
    // loading (the search itself kicks off the async load), so retry briefly.
    selectByKey: function (key, tries) {
      const obj = swh.searchSkyObject(key)
      if (obj) { swh.setSweObjAsSelection(obj); return }
      if (tries > 0) {
        const that = this
        setTimeout(function () { that.selectByKey(key, tries - 1) }, 250)
      }
    },
    close: function () {
      // Clear the text + results (which hides the list); leave `focused` as-is
      // so a follow-up search in the still-focused box shows results again.
      // Clicking outside blurs the field, and onBlur clears `focused`.
      this.searchText = ''
      this.results = []
    }
  }
}
</script>

<style>
.target-search .v-field__input {
  font-size: 14px;
  min-height: 32px;
  padding-top: 4px;
}
/* Teleported results list: opaque, 28px rounded, no inner top/bottom padding,
   wider than the 120px box so the names read against the sky. */
.search-results.v-list {
  position: fixed;
  z-index: 2000;
  min-width: 220px;
  max-height: 320px;
  overflow-y: auto;
  background: #424242 !important;
  border-radius: 28px !important;
  color: white;
  padding-top: 0 !important;
  padding-bottom: 0 !important;
}
</style>
