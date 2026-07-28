// Content for the Learning page (/learning).
//
// Everything here is transcribed from the Financial Executive Club's own site on
// 2026-07-28 — finexclub.org/education, /TechTraining and /event-list. It is the
// Club's copy, not ours: course blurbs and the trainer's credentials are quoted
// close to verbatim, and event titles/venues are exactly as published.
//
// Hardcoded rather than fetched. The Club's site is Wix and renders these lists
// client-side, so there is no feed to read; scraping it at runtime would add a
// network dependency and a failure mode to a page that changes a few times a
// year. When the Club updates a programme, edit this file.

export const EDUCATION_URL = 'https://www.finexclub.org/education'
export const TECH_TRAINING_URL = 'https://www.finexclub.org/TechTraining'
export const EVENTS_URL = 'https://www.finexclub.org/event-list'

/** The Club's own framing of what its education arm is for. */
export const MISSION =
  'We bridge the gap between academic theory and global financial practice through a ' +
  'dynamic ecosystem of digital and in-person initiatives.'

// ── The three programme strands (finexclub.org/education) ────────────────────

export interface Strand {
  /** Editorial numbering, decorative. */
  index: string
  name: string
  /** What form it takes — sits under the name as an eyebrow. */
  format: string
  body: string
  /** Topics the Club lists for this strand. */
  topics: string[]
}

export const STRANDS: Strand[] = [
  {
    index: '01',
    name: 'Mastermind Roundtable',
    format: 'Interview series',
    body:
      'The Club’s signature interview series, featuring elite business executives ' +
      'and finance leaders.',
    topics: [
      'Career acceleration',
      'Wealth & retirement planning',
      'Emerging industry trends',
      'AI',
      'Digital assets',
      'Advanced financial literacy',
    ],
  },
  {
    index: '02',
    name: 'Theme-based Seminars & Webinars',
    format: 'In-person & online',
    body:
      'Sessions run in person through strategic partnerships, hosted at the ' +
      'institutions the topics concern.',
    topics: [
      'Private market investments',
      'AI in finance & risk management',
      'Real-world asset (RWA) tokenisation',
      'Macroeconomics',
      'Geopolitical instability',
      'Commodity trends',
    ],
  },
  {
    index: '03',
    name: 'AI / Tech Workshops',
    format: 'Master trainers',
    body:
      'Custom workshops built with expert trainers, meeting the demand for tech ' +
      'upskilling across the finance function.',
    topics: ['GenAI', 'Agentic AI', 'Cloud', 'Data science', 'Python / R'],
  },
]

// ── AI/Tech training catalogue (finexclub.org/TechTraining) ──────────────────

export interface Course {
  index: string
  title: string
  /** The Club's own one-line framing, e.g. "AI-Native Marketing Funnel". */
  lede: string
  body: string
  /** Verbatim from the Club — these are the only two shapes offered. */
  duration: string
}

export const COURSES: Course[] = [
  {
    index: '01',
    title: 'Practical Generative AI Skills Training',
    lede: 'Latest AI Innovations & Skills',
    body:
      'Practical generative AI skills using the latest GenAI tools for text, image, ' +
      'video and speech generation.',
    duration: 'Half-day or full-day',
  },
  {
    index: '02',
    title: 'Agentic AI Training for Executives',
    lede: 'Agentic Workflows, Automating the Executive’s Day',
    body:
      'A practical workshop on how executives can leverage GenAI tools to automate ' +
      'their daily work.',
    duration: 'Half-day or full-day',
  },
  {
    index: '03',
    title: 'AI-Native Marketing Strategy',
    lede: 'AI-Native Marketing Funnel',
    body:
      'How to leverage GenAI tools to automate your marketing funnel — marketing ' +
      'creative, content creation, social media optimisation.',
    duration: 'Half-day or full-day',
  },
  {
    index: '04',
    title: 'Hands-on Cloud Computing Training',
    lede: 'Hands-on Cloud Computing',
    body: 'Practical cloud skills, taught on AWS or Azure.',
    duration: '3-hour or 10-hour',
  },
  {
    index: '05',
    title: 'Practical Python / R Training for Data Scientists',
    lede: 'Practical Python / R',
    body: 'Practical training on Python or R and the popular data science stack.',
    duration: '3-hour or 10-hour',
  },
]

/**
 * The named trainer behind the AI/Tech track. Credentials are the Club's own
 * listing — they are the trust signal for this section, so they are quoted
 * rather than summarised.
 */
export const TRAINER = {
  name: 'Sunny Ng',
  role: 'Master Trainer',
  education: [
    'M.Sc. Computer Science, University of Hong Kong',
    'MFA New Media Design & Technology, City University of Hong Kong',
    'B.Sc. (Hon) Computer Science, University of Hertfordshire, UK',
  ],
  certifications: [
    'Accredited AWS Academy Educator',
    'AWS Certified Solutions Architect – Associate',
    'AWS Certified Developer – Associate',
    'AWS Certified Data Engineer – Associate',
    'AWS Certified Machine Learning Engineer – Associate',
    'AWS Certified AI Practitioner',
    'Educator, Microsoft Learn for Educators',
  ],
} as const

// ── Events (finexclub.org/event-list) ────────────────────────────────────────

export interface ClubEvent {
  title: string
  /** ISO date, so the page can sort and format rather than trusting a string. */
  date: string
  venue: string
  /** True when the session ran online rather than at a venue. */
  online?: boolean
}

/**
 * Every event the Club currently lists, newest first.
 *
 * IMPORTANT: as of 2026-07-28 all of these have already happened — the most
 * recent ran on 16 July 2026. The page therefore presents them as a track record
 * ("where the Club has convened"), never as "upcoming". If you add a future
 * date here, split the list on today's date rather than relabelling the section;
 * advertising a past seminar as upcoming is the one failure mode this section has.
 */
export const EVENTS: ClubEvent[] = [
  {
    title: 'FinEx Club Exclusive Cocktail Reception — FSAB Executives and Guests',
    date: '2026-07-16',
    venue: 'The Refinery Club',
  },
  {
    title: 'AI, Automation, and the Evolving Role of Finance: Risks, Controls, and Opportunities',
    date: '2026-06-04',
    venue: 'Baker Tilly Hong Kong',
  },
  {
    title: 'Real-World Asset (RWA) Tokenization Seminar',
    date: '2026-05-20',
    venue: 'Central Plaza',
  },
  {
    title: 'FinEx Accelerator: Empower Change & Wine Tasting',
    date: '2026-04-21',
    venue: 'Leeder Quay Flagship Store',
  },
  {
    title: '13th CTWeek Hong Kong',
    date: '2026-04-15',
    venue: 'JW Marriott Hotel Hong Kong',
  },
  {
    title: 'FinEx Club Seminar: Private Markets Strategies and Innovations',
    date: '2026-03-26',
    venue: 'State Street Bank and Trust Company',
  },
  {
    title: "Navigating 2026's Mega Trends – Gold Boom, Rate Normalization & Yuan Strength",
    date: '2026-03-18',
    venue: 'Webinar',
    online: true,
  },
]
