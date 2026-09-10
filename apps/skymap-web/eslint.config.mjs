import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

// ESLint 9 flat config (replaces the old vue-cli eslintConfig).
// Vue 3.5 project -> eslint-plugin-vue's Vue 3 flat preset.
export default [
  {
    ignores: [
      'dist/**',
      'public/**',
      'src/assets/js/**' // generated emscripten glue
    ]
  },
  ...pluginVue.configs['flat/recommended'],
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
