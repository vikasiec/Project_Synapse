import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies /v1 and /health to the stdlib Python backend
// (`python -m synapse serve`, default port 8787 -- see synapse/cli.py) so
// `npm run dev` can hit the real API without CORS config. Production build
// output (dist/) is served by synapse/api.py's existing static handler --
// see STATIC_DIR.
export default defineConfig({
  plugins: [react()],
  // Served at /app/ alongside the legacy synapse/static/index.html at /
  // (kept until this UI reaches panel parity -- see Active_File.md row 43).
  base: '/app/',
  server: {
    proxy: {
      '/v1': 'http://127.0.0.1:8787',
      '/health': 'http://127.0.0.1:8787',
    },
  },
  build: {
    outDir: 'dist',
  },
})
