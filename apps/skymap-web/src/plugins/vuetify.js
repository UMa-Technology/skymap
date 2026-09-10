// Subset of @mdi/font with only the icons this app + Vuetify's defaults use
// (2.9 KB woff2 instead of the full 404 KB + 350 KB css). Regenerate with
// tools/make-mdi-subset.py after adding icons or upgrading Vuetify.
import '@/assets/mdi/mdi-subset.css'
import 'vuetify/styles'
import { createVuetify } from 'vuetify'
import { aliases, mdi } from 'vuetify/iconsets/mdi'

// Pin the Vuetify 2 dark palette so the UI keeps its colours under Vuetify 3
// (v3's default dark theme dropped `accent` and shifted primary/secondary).
export default createVuetify({
  theme: {
    defaultTheme: 'dark',
    themes: {
      dark: {
        dark: true,
        colors: {
          primary: '#1976D2',
          secondary: '#424242',
          accent: '#82B1FF',
          error: '#FF5252',
          info: '#2196F3',
          success: '#4CAF50',
          warning: '#FB8C00'
        }
      }
    }
  },
  icons: {
    defaultSet: 'mdi',
    aliases,
    sets: { mdi }
  }
})
