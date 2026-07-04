import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // `npm start` (Railway) serves the built SPA with `vite preview`.
  preview: {
    host: true,          // bind 0.0.0.0 inside the container
    allowedHosts: true,  // allow the *.up.railway.app demo host
  },
})
