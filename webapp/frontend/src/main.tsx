import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

/**
 * Hand the head over from the server's copy to React's, without losing anything.
 *
 * The backend injects a title, description, canonical, Open Graph, Twitter card
 * and Organization JSON-LD for each known route, so a client that never runs
 * JavaScript — Bing, an unfurler, a phishing classifier — sees a real page
 * instead of an empty shell (see `_shell_head_tags` in webapp/backend/main.py).
 *
 * Only the tags React renders itself are removed here. React 19 does not replace
 * a tag it did not create, so leaving those would put two <title>s in the DOM;
 * the stale server one would win and client-side navigation would never update
 * the tab.
 *
 * Everything else is deliberately LEFT IN PLACE. React renders no canonical and
 * no og:*, and Google indexes the RENDERED page — strip them here and the only
 * client that ever sees a canonical is one that does not run JS, which is
 * precisely backwards.
 */
const REPLACED_BY_REACT = [
  'title[data-ssr]',
  'meta[data-ssr][name="description"]',
  // LandingPage renders its own Organization block; the server's would double it.
  'script[data-ssr][type="application/ld+json"]',
].join(', ')

for (const tag of document.querySelectorAll(REPLACED_BY_REACT)) {
  tag.remove()
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
