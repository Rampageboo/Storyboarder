import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

const rootDir = path.dirname(fileURLToPath(import.meta.url))

/** Build workspace helpers as a static ESM module for scene3d.js. */
export default defineConfig({
  build: {
    lib: {
      entry: path.resolve(rootDir, 'src/scene3d/workspace/staticEntry.ts'),
      formats: ['es'],
      fileName: () => 'scene3d_workspace.js',
    },
    outDir: path.resolve(rootDir, '../storyboard_tool/web/static/runtime'),
    emptyOutDir: false,
    rollupOptions: {
      external: (id) => id.startsWith('/static/'),
    },
  },
})
