import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

/**
 * Drop the head tags the server wrote into index.html before handing over.
 *
 * The backend injects a title, description, canonical, Open Graph and JSON-LD
 * for each known route so a client that never runs JavaScript — Bing, an
 * unfurler, a phishing classifier — sees a real page instead of an empty
 * shell (see `_shell_head_tags` in webapp/backend/main.py).
 *
 * React sets the same tags itself once it boots, and React 19 does not replace
 * a tag it did not create. Left alone, the DOM would carry two <title>s and the
 * stale server one would win, so client-side navigation would never update the
 * tab. Removing them here means exactly one of each survives, owned by React.
 */
for (const tag of document.querySelectorAll('[data-ssr]')) {
  tag.remove()
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
