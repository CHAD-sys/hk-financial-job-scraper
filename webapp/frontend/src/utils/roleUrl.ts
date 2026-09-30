/** The public, permanent URL for a Role — safe to share outside the SPA. */
export function rolePagePath(source: string, sourceId: string): string {
  return `/jobs/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}`
}

/**
 * The in-app detail screen. Unlike the public Role URL above, this route is
 * intentionally client-owned: it carries the Role access grant obtained from
 * an already-authorised discovery surface and can present the phone-first
 * reading experience without colliding with the server's SEO teaser route.
 */
export function roleDetailPath(source: string, sourceId: string): string {
  return `/roles/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}`
}

export function rolePageUrl(source: string, sourceId: string): string {
  return `${window.location.origin}${rolePagePath(source, sourceId)}`
}
