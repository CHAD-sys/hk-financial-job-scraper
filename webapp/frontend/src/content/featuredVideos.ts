// Featured videos for the Professional L&D section on the landing page.
//
// Deliberately a hardcoded array, not a YouTube API call. Rationale:
//   - no API key to manage, no quota to exhaust, no failure mode at runtime
//   - the channel's *latest* six videos are four parts of one gold series
//     posted the same day plus a CNY gathering, which reads as a dead channel;
//     these six are hand-picked for topical range instead
//   - publish dates are deliberately not shown anywhere (newest upload is
//     2026-03-21), so the section doesn't advertise its own staleness
//
// Swapping the featured set is a one-line edit here. The ideal replacements are
// six Mastermind Roundtable episodes — the Club's flagship interview series,
// named on finexclub.org/education — which are older than the 15 videos the
// channel's RSS feed exposes and so weren't visible when this list was built.

export interface FeaturedVideo {
  /** 11-character YouTube video ID, from the watch URL. */
  id: string
  /** Display title. Cleaned of hashtags and "Part N:" noise, still recognisable. */
  title: string
  /** Two- or three-word topic tag, used as the card eyebrow. */
  topic: string
}

export const CHANNEL_URL = 'https://www.youtube.com/@finexclubhq'

/** Claimed on finexclub.org/about. Used as the credibility line instead of recency. */
export const SUBSCRIBER_LINE = '50,000+ subscribers'

export const FEATURED_VIDEOS: FeaturedVideo[] = [
  {
    id: 'qovCchwibjI',
    title: 'The Gold & Silver Rally — catalysts and trends to watch',
    topic: 'Precious metals',
  },
  {
    id: 'alQ0eelrn1E',
    title: 'Fed rate policy 2026 — gold sensitivity and allocation',
    topic: 'Rates & macro',
  },
  {
    id: 'FAD997mf050',
    title: "Hong Kong's gold hub strategy — tokenised gold and blockchain trades",
    topic: 'Tokenisation',
  },
  {
    id: '6di-kHFF1lM',
    title: 'Breaking down the AI reality — and confronting the threats',
    topic: 'AI & technology',
  },
  {
    id: 'smQFHpX06B8',
    title: 'Inside the Private Markets Committee',
    topic: 'Private markets',
  },
  {
    id: 'F5y2IZW0Myc',
    title: 'Inside the Fintech & DeFi Committee',
    topic: 'Fintech & DeFi',
  },
]

/** YouTube's still-frame CDN. No player JS, no cookies — see VideoFacade. */
export function thumbnailUrl(id: string): string {
  return `https://i.ytimg.com/vi/${id}/hqdefault.jpg`
}

export function watchUrl(id: string): string {
  return `https://www.youtube.com/watch?v=${id}`
}
