import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

// ESLint 9 flat config (replaces the old vue-cli eslintConfig).
// Vue 2.7 project -> use eslint-plugin-vue's vue2 flat presets.
export default [
  {
    ignores: [
      'dist/**',
      'public/**',
      'src/assets/js/**' // generated emscripten glue
    ]
  },
  ...pluginVue.configs['flat/vue2-recommended'],
  {
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.node
      }
    },
    rules: {
      'vue/multi-word-component-names': 'off',
      'vue/no-v-html': 'off',
      'vue/require-explicit-emits': 'off'
    }
  }
]
