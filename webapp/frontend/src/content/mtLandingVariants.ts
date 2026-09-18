export type MTLandingVariant = 1 | 2 | 3 | 4 | 5 | 6

export const MT_LANDING_VARIANTS: Record<MTLandingVariant, string> = {
  1: 'Announcement + showcase',
  2: 'MT-first editorial hero',
  3: 'Quiet classified notice',
  4: 'Dark deadline desk',
  5: 'Graduate gateway',
  6: 'Programme index masthead',
}

export function getMTLandingVariant(): MTLandingVariant {
  const query = typeof window === 'undefined'
    ? null
    : new URLSearchParams(window.location.search).get('mtConcept')
  const candidate = Number(query ?? import.meta.env.VITE_MT_LANDING_VARIANT ?? 1)
  return candidate >= 1 && candidate <= 6 ? candidate as MTLandingVariant : 1
}
