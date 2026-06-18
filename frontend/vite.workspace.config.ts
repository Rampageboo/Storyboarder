import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

const rootDir = path.dirname(fileURLToPath(import.meta.url))

/**
 * Build the Scene3D workspace TypeScript source to a single static ESM bundle.
 * Output: storyboard_tool/web/static/runtime/scene3d_workspace.js (committed — do not hand-edit).
 * Source: frontend/src/scene3d/workspace/staticEntry.ts
 * Vendor /static/ imports are kept external (served at runtime).
 */
export default defineConfig({
  publicDir: false,
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
