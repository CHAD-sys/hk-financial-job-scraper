/** The public, permanent URL for a Role — safe to share outside the SPA. */
export function rolePagePath(source: string, sourceId: string): string {
  return `/jobs/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}`
}

export function rolePageUrl(source: string, sourceId: string): string {
  return `${window.location.origin}${rolePagePath(source, sourceId)}`
}
