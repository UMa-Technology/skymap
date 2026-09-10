// Stellarium Web - Copyright (c) 2022 - Stellarium Labs SRL
//
// This program is licensed under the terms of the GNU AGPL v3, or
// alternatively under a commercial licence.
//
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

<template>

<div style="position:absolute; width: 100%; height: 100%; background: #000;">
  <v-container style="width: 100%; height: 100%;">
    <div class="d-flex flex-column align-center justify-center" style="width: 100%; height: 100%;">
      <div v-if="$store.state.wasmSupport">
        <v-progress-circular indeterminate v-bind:size="35" v-bind:width="4" class="text-grey"/>
      </div>
      <v-card v-else style="margin: auto;">
        <v-card-title primary-title>
          <div class="text-h5"><h1>{{ $t('Could not show the Online Star Map') }}</h1></div>
          <div class="text-h5" style="margin-top: 30px"><v-icon size="large">mdi-alert</v-icon> {{ $t('It seems that your browser cannot load Web Assembly!') }}</div>
        </v-card-title>
        <v-card-text>
          <div class="d-flex flex-column align-center" style="width: 100%; height: 100%;">
            <p class="text-grey">{{ $t('Web assembly is necessary for Stellarium Web to display the star map. Please upgrade your web browser and try again!') }}</p>
            <p><i18n-t keypath="In the meantime, you can try the {0}!"><a href="https://stellarium.org">{{ $t('desktop version') }}</a></i18n-t></p>
          </div>
        </v-card-text>
      </v-card>
    </div>
  </v-container>
</div>

</template>

<script>
export default {
}
</script>

<style>
</style>
