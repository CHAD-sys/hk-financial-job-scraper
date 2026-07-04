/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend API base URL, injected at build time (see .env.example). */
  readonly VITE_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
