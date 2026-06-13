import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Served by FastAPI: built assets live under /ui (StaticFiles mount), the SPA shell is
// returned at / and /dashboard. base=/ui/ makes emitted asset URLs resolve against that mount.
// The dev server proxies /api and /manual to the engine on :7790. Hash routing (router.ts)
// means the server only ever serves index.html — no SPA-fallback config needed.
export default defineConfig({
  base: '/ui/',
  plugins: [vue()],
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 1200 },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:7790',
      '/manual': 'http://127.0.0.1:7790',
    },
  },
})
