import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite config used by `tauri dev` and `tauri build`.
// The Python backend is expected on STORYBOARD_DEV_PORT (default 8000) in dev mode.
const devPort = parseInt(process.env.STORYBOARD_DEV_PORT ?? '8000', 10)

export default defineConfig({
  plugins: [react()],
  base: '/',
  build: {
    outDir: 'dist-tauri',
    emptyOutDir: true,
  },
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      ignored: ['**/src-tauri/**'],
    },
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${devPort}`,
        changeOrigin: true,
      },
      '/static': {
        target: `http://127.0.0.1:${devPort}`,
        changeOrigin: true,
      },
    },
  },
})
