import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    // Allow tunnel hosts (cloudflared trycloudflare.com, ngrok) to reach the dev server.
    allowedHosts: true,
    // Relative /api calls are proxied to the FastAPI backend, so a single tunnel
    // on :5173 serves both UI and API from one origin (no CORS needed).
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
