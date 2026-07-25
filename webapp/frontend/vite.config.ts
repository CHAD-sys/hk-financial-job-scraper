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
  // `npm start` (Railway) serves the built SPA with `vite preview`.
  preview: {
    host: true,          // bind 0.0.0.0 inside the container
    allowedHosts: true,  // allow the *.up.railway.app demo host
  },
})
