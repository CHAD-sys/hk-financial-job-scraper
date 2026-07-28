// Featured videos for the Learning page (/learning).
//
// These are the first six videos, in order, from the Club's own curated shelf at
// finexclub.org/onlineplatform — not the YouTube channel's latest uploads. That
// distinction matters: the channel's most recent six are four parts of one gold
// series posted the same day plus a CNY gathering, which reads as a dead channel.
// The Club has already done the curation on its own site, so we mirror that order
// rather than re-curating or calling the YouTube API (no key, no quota, no runtime
// failure mode).
//
// IDs were read from the embedded iframes on that page, each bound to the title
// printed beside it, so the pairing is the site's own rather than inferred from
// ordering. Publish dates are deliberately not shown anywhere — the shelf is
// curated, not a feed, and dates would only advertise staleness.
//
// Titles are kept as the Club publishes them, including the Chinese-language
// ones. Translating them would misrepresent what a viewer actually gets.

export interface FeaturedVideo {
  /** 11-character YouTube video ID, from the watch URL. */
  id: string
  /** Display title, as published by the Club. */
  title: string
  /** Two- or three-word topic tag, used as the card eyebrow. */
  topic: string
}

export const CHANNEL_URL = 'https://www.youtube.com/@finexclubhq'

/** The Club's own curated shelf these six are mirrored from. */
export const PLATFORM_URL = 'https://www.finexclub.org/onlineplatform'

/**
 * Credibility line for the Learning page, used instead of recency (see the note
 * above about the newest upload being months old).
 *
 * This is the Club's own stated figure, matching finexclub.org/about ("over
 * 50,000 subscribers"). For the record, YouTube reported 49.4K on 2026-07-27 —
 * noted here so nobody later "fixes" this against the API and wonders why the
 * two disagree. Owner's decision to use the Club's number.
 */
export const SUBSCRIBER_LINE = '50,000+ subscribers'

export const FEATURED_VIDEOS: FeaturedVideo[] = [
  {
    id: '6di-kHFF1lM',
    title: 'Break down the AI Reality and Confront the Threats',
    topic: 'AI & technology',
  },
  {
    id: 'Mc6Pc0GlpMI',
    title: 'Cambridge Professor on Climate Change and Sustainability Strategies',
    topic: 'Sustainability',
  },
  {
    id: 'x1q7-q1Ebnc',
    title: 'Banking Model and Fintech, Supply Chains, Global Trade Corridors, Advice to Young Bankers',
    topic: 'Banking & trade',
  },
  {
    id: 'SWVGD9z4iAI',
    title: '私募MD暢談私募股權和私募債Private Equity的投資策略與Private Credit在資產配置的市場價值',
    topic: 'Private markets',
  },
  {
    id: 'iZ1EyIODvaA',
    title: 'Web3.0大時代，正確認識穩定幣、央行數字貨幣、代幣化存款',
    topic: 'Digital assets',
  },
  {
    id: 'ZJp5UK1wog0',
    title: 'APAC CEO Talk: Asset Servicing前世今生及歷史性時刻',
    topic: 'Asset servicing',
  },
]

/** YouTube's still-frame CDN. No player JS, no cookies — see VideoFacade. */
export function thumbnailUrl(id: string): string {
  return `https://i.ytimg.com/vi/${id}/hqdefault.jpg`
}

export function watchUrl(id: string): string {
  return `https://www.youtube.com/watch?v=${id}`
}
