import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The production build is served by FastAPI under /react (see storyboard_tool/api.py).
// `base` rewrites built asset URLs to /react/assets/...; outDir writes into the backend's web dir.
export default defineConfig({
  plugins: [react()],
  base: '/react/',
  build: {
    outDir: '../storyboard_tool/web/dist',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
