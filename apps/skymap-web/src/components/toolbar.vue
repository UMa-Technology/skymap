// Stellarium Web - Copyright (c) 2022 - Stellarium Labs SRL
//
// This program is licensed under the terms of the GNU AGPL v3, or
// alternatively under a commercial licence.
//
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

<template>
  <div id="toolbar-image">
    <v-toolbar color="transparent" density="compact">
      <!-- 0: logo, then the two-line FOV right next to it (12px gap) -->
      <img class="tbtitle" id="stellarium-web-toolbar-logo" src="@/assets/images/logo.svg" width="30" height="30" alt="Stellarium Web Logo"/>
      <div v-if="fov" style="margin-left: 12px; line-height: 1.05; user-select: none; white-space: nowrap;">
        <div style="color: rgba(255,255,255,0.7); font-size: 13px; font-weight: 500;">{{ fov }}</div>
        <div style="color: rgba(255,255,255,0.5); font-size: 10px; letter-spacing: 1px; margin-top: 4px;">FOV</div>
      </div>
      <v-spacer></v-spacer>
      <!-- Offline cross-language object search (index built from the shipped
           sky-i18n catalogs; see sw_helpers ensureSearchIndex). -->
      <target-search style="width:160px; max-width:160px; flex:0 0 auto; margin-right:12px;"></target-search>
      <!-- FPS (dev diagnostic, off by default); FOV moved to the top-left HUD -->
      <div v-if="$store.state.showFPS" class="subheader text-grey pr-2" style="user-select: none;">FPS {{ $store.state.stel ? $store.state.stel.fps.toFixed(1) : '?' }}</div>
      <!-- 4: language selector (lat/lon moved into the Settings popover) -->
      <v-select v-model="skyLang" :items="skyLangs" item-title="text" item-value="value"
        @update:model-value="onSkyLangChange" v-model:menu="langMenu" :menu-props="{ offset: 16 }"
        density="compact" variant="plain" hide-details class="lang-select"
        style="width:130px; max-width:130px; flex:0 0 auto; margin-right:12px;"></v-select>
      <!-- 5: View Settings (floating popover anchored to this button) -->
      <v-menu v-model="settingsMenu" :close-on-content-click="false" location="bottom end" offset="8">
        <template v-slot:activator="{ props }">
          <v-btn icon v-bind="props"><v-icon>mdi-cog</v-icon></v-btn>
        </template>
        <view-settings-dialog></view-settings-dialog>
      </v-menu>
    </v-toolbar>
  </div>
</template>

<script>

import swh from '@/assets/sw_helpers.js'
import ViewSettingsDialog from '@/components/view-settings-dialog.vue'
import TargetSearch from '@/components/target-search.vue'

export default {
  components: { ViewSettingsDialog, TargetSearch },
  data: function () {
    return {
      skyLang: 'en',
      skyLangs: [
        { text: 'English', value: 'en' },
        { text: '简体中文', value: 'zh_cn' },
        { text: '繁體中文', value: 'zh_tw' },
        { text: 'Polski', value: 'pl' },
        { text: 'Français', value: 'fr' },
        { text: 'Deutsch', value: 'de' },
        { text: '日本語', value: 'ja' },
        { text: 'Русский', value: 'ru' },
        { text: 'Italiano', value: 'it' },
        { text: '한국어', value: 'ko' },
        { text: 'Español', value: 'es' }
      ],
      settingsMenu: false,
      langMenu: false
    }
  },
  watch: {
    settingsMenu: function () { this.syncTopPopup() },
    langMenu: function () { this.syncTopPopup() }
  },
  computed: {
    // fovX/fovY are written directly on the engine core each frame (no property
    // change event), so read them LIVE; depend on per-frame fps (+ fov) so this
    // recomputes as the view/window changes. Return only the dimensions (the
    // "FOV" label is rendered separately). Empty until the engine has real
    // values (both start at 0) so we never flash a bogus "0.00° x 120°".
    fov: function () {
      const s = this.$store.state.stel
      if (!s || !this.$stel) return ''
      void s.fps; void s.fov
      const core = this.$stel.core
      if (!core.fovX || !core.fovY) return ''
      const x = (core.fovX * 180 / Math.PI).toPrecision(3)
      const y = (core.fovY * 180 / Math.PI).toPrecision(3)
      return x + '° × ' + y + '°'
    }
  },
  methods: {
    // Sky-map text language selector.
    onSkyLangChange: function (lang) {
      swh.setSkyLanguage(lang)
    },
    // Hide the top-right time entry while the Settings/language popover is open
    // so the two (both anchored top-right) don't overlap.
    syncTopPopup: function () {
      this.$store.commit('setValue', { varName: 'topRightPopupOpen', newValue: this.settingsMenu || this.langMenu })
    }
  }
}
</script>

<style>
#toolbar-image {
  background: url("../assets/images/header.png") center;
  background-position-x: 55px;
  background-position-y: 0px;
  height: 48px;
  z-index: 1;
  position: absolute;
  top: 0px;
  left: 0px;
  width: 100%;
}

#stellarium-web-toolbar-logo {
  margin-left: 8px;
  user-select: none;
}

/* Language selector: right-align the current language so it sits next to the
   dropdown icon with an 8px gap (default is left-aligned with a wide gap). */
.lang-select .v-field__input {
  justify-content: flex-end;
  text-align: right;
  padding-inline-end: 8px;
}
.lang-select .v-field__append-inner {
  padding-inline-start: 0;
}

</style>
