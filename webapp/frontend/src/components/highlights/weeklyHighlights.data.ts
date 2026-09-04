/**
 * V1 seed content for the "This week at FinEx" band.
 *
 * WHY THIS IS A FILE AND NOT AN ENDPOINT (yet)
 * -------------------------------------------
 * The four things the band shows do not share a source today, and two of them
 * have no source at all:
 *
 *   roles   — REAL. Curated by hand from jobs.db on 2026-09-04: open, primary,
 *             board-visible Roles posted inside two weeks, priced at or above
 *             the HK$40k floor the brief set, spread deliberately across pay
 *             levels (40k → 200k) and across desks rather than stacking the
 *             top payers. Every `source`/`source_id` is a live deep link.
 *   video   — REAL. Taken from /api/learning, which already serves the
 *             YouTube feed the Learning page renders.
 *   course  — REAL. Also /api/learning (its `events` half).
 *   coaches — REAL. The current 32-person FinEx Club coach roster, sourced
 *             from finexclub.org/career-coach on 2026-09-04. It deliberately
 *             lives in its own rail below the editorial drop, rather than
 *             interrupting the roles, videos and training cards.
 *
 * The point of V1 is to settle the SHAPE and the MOTION. Once those are
 * approved, roles should come from a `/api/highlights` read model (the same
 * board predicate the rest of the product uses, so the band can never feature
 * a Role a visitor cannot open), video and course from the Learning feed
 * already in `fetchLearningContent`, and the coach from wherever the club
 * decides coaches live.
 *
 * Until then: hand-written, dated, and honest about which half is which.
 */

/** Every card is one of these four. The shell is shared; the body is not. */
export type HighlightKind = 'role' | 'coach' | 'video' | 'course'

interface HighlightBase {
  id: string
  kind: HighlightKind
  /** Where the whole card goes when clicked. Never a dead card. */
  href: string
}

export interface RoleHighlight extends HighlightBase {
  kind: 'role'
  company: string
  title: string
  /** Editorial desk label. Deliberately NOT `job_category`, whose vocabulary
   *  ("Finance", "Other") is too coarse to be worth a chip on a hero card. */
  desk: string
  salaryMin: number
  salaryMax: number
  seniority: string
  location: string
}

export interface CoachHighlight extends HighlightBase {
  kind: 'coach'
  name: string
  role: string
  focus: string
  image: string
}

export interface VideoHighlight extends HighlightBase {
  kind: 'video'
  title: string
  topic: string
  thumbnail: string
  publishedAt: string
}

export interface CourseHighlight extends HighlightBase {
  kind: 'course'
  title: string
  venue: string
  date: string
  image: string
}

export type Highlight = RoleHighlight | CoachHighlight | VideoHighlight | CourseHighlight

/** Wix serves responsive transforms from the original asset. Keeping the
 * source URL here lets the coach rail show the official portrait at a sharp,
 * appropriately small size without copying 32 third-party image files into
 * this app. */
const coachImage = (asset: string, name: string) => {
  const extension = asset.endsWith('.jpg') ? '.jpg' : '.png'
  return `https://static.wixstatic.com/media/${asset}/v1/fill/w_280,h_280,al_c,q_85,usm_0.66_1.00_0.01,enc_avif,quality_auto/${encodeURIComponent(name)}${extension}`
}

const roleHref = (
  source: string,
  sourceId: string,
  relatedSearch: string,
  title: string,
  lookupSearch = title,
) => {
  const params = new URLSearchParams({
    q: relatedSearch,
    role_source: source,
    role_id: sourceId,
    role_lookup: lookupSearch,
  })
  return `/jobs?${params.toString()}`
}

/**
 * The order IS the edit.
 *
 * A marquee is read in passing, so the sequence matters more than it would in
 * a grid: the biggest number leads, the non-role cards are spaced so a viewer
 * never sees two of the same kind in a row, and the pay levels rise and fall
 * rather than descending — a strictly descending list reads as "and now the
 * cheap ones" by the halfway point.
 */
export const WEEKLY_HIGHLIGHTS: Highlight[] = [
  {
    id: 'role-jpm', kind: 'role', href: roleHref(
      'linkedin', '4443781178', 'Private Banking',
      'International Private Bank, Investor for China Market, Managing Director',
    ),
    company: 'JPMorganChase',
    title: 'International Private Bank, Investor for China Market, Managing Director',
    desk: 'Private Banking', salaryMin: 150000, salaryMax: 200000,
    seniority: 'Managing Director', location: 'Hong Kong',
  },
  {
    id: 'video-cuhk', kind: 'video',
    href: 'https://www.youtube.com/watch?v=m5Bntb8ZMWY',
    title: '與CUHK商學院助理院長對話：當代商業教育與高管教育如何擴展全球視野',
    topic: 'FinEx Club', thumbnail: 'https://i2.ytimg.com/vi/m5Bntb8ZMWY/hqdefault.jpg',
    publishedAt: '2026-08-30',
  },
  {
    id: 'role-citi', kind: 'role', href: roleHref(
      'efinancialcareers', '24612710', 'Equity Finance Technology',
      'APAC Head of Equity Finance Technology',
    ),
    company: 'Citi', title: 'APAC Head of Equity Finance Technology',
    desk: 'Equity Finance Technology', salaryMin: 120000, salaryMax: 150000,
    seniority: 'Head of', location: 'Hong Kong',
  },
  {
    id: 'role-dbs', kind: 'role', href: roleHref(
      'efinancialcareers', '24666611', 'Rates Trading',
      'SVP, Interest Rate Trader, Global Financial Markets',
      'SVP, Interest Rate Trader, GFM',
    ),
    company: 'DBS Bank', title: 'SVP, Interest Rate Trader, Global Financial Markets',
    desk: 'Rates Trading', salaryMin: 105000, salaryMax: 163500,
    seniority: 'SVP', location: 'Hong Kong',
  },
  {
    id: 'role-ubs', kind: 'role', href: roleHref(
      'linkedin', '4442287464', 'Fixed Income', 'Fixed Income Structurer',
    ),
    company: 'UBS', title: 'Fixed Income Structurer',
    desk: 'Fixed Income', salaryMin: 140000, salaryMax: 160000,
    seniority: 'Senior', location: 'Hong Kong',
  },
  {
    id: 'role-schroders', kind: 'role', href: roleHref(
      'linkedin', '4450262973', 'Wealth Management', 'Client Director — Wealth, Hong Kong',
    ),
    company: 'Schroders', title: 'Client Director — Wealth, Hong Kong',
    desk: 'Wealth Management', salaryMin: 119000, salaryMax: 140000,
    seniority: 'Director', location: 'Hong Kong',
  },
  {
    id: 'role-cmb', kind: 'role', href: roleHref(
      'efinancialcareers', '24589080', 'Debt Capital Markets',
      'Vice President, Debt Capital Markets',
    ),
    company: 'CMB Wing Lung Bank', title: 'Vice President, Debt Capital Markets',
    desk: 'Debt Capital Markets', salaryMin: 125000, salaryMax: 166500,
    seniority: 'Vice President', location: 'Hong Kong',
  },
  {
    id: 'role-futu', kind: 'role', href: roleHref(
      'efinancialcareers', '22525899', 'Investment Advisory', 'Investment Advisor',
    ),
    company: 'Futu Securities', title: 'Investment Advisor',
    desk: 'Investment Advisory', salaryMin: 57000, salaryMax: 142500,
    seniority: 'Mid-level', location: 'Hong Kong',
  },
  {
    id: 'role-fidelity', kind: 'role', href: roleHref(
      'efinancialcareers', '24686254', 'Marketing', 'Head of Marketing, Hong Kong',
    ),
    company: 'Fidelity International', title: 'Head of Marketing, Hong Kong',
    desk: 'Marketing', salaryMin: 65000, salaryMax: 120000,
    seniority: 'Head of', location: 'Hong Kong',
  },
  {
    id: 'role-macquarie', kind: 'role', href: roleHref(
      'linkedin', '4429043109', 'People & Culture',
      'Regional People & Culture Transformation Lead',
    ),
    company: 'Macquarie Group', title: 'Regional People & Culture Transformation Lead',
    desk: 'People & Culture', salaryMin: 90000, salaryMax: 110000,
    seniority: 'Lead', location: 'Hong Kong',
  },
  {
    id: 'role-deloitte', kind: 'role', href: roleHref(
      'linkedin', '4420274039', 'Risk & Regulation',
      'Manager / Senior Manager — Regulatory & Financial Risk',
    ),
    company: 'Deloitte', title: 'Manager / Senior Manager — Regulatory & Financial Risk',
    desk: 'Risk & Regulation', salaryMin: 50000, salaryMax: 100000,
    seniority: 'Senior Manager', location: 'Hong Kong',
  },
  {
    id: 'role-gs-legal', kind: 'role', href: roleHref(
      'linkedin', '4424562303', 'Legal',
      'Legal, Global Banking & Markets, Vice President',
    ),
    company: 'Goldman Sachs', title: 'Legal, Global Banking & Markets, Vice President',
    desk: 'Legal', salaryMin: 40000, salaryMax: 80000,
    seniority: 'Vice President', location: 'Hong Kong',
  },
]

/** The full public FinEx Club coach roster. Each card keeps its official
 * destination, so a visitor can go straight to that coach's profile rather
 * than landing on a generic enquiry page. */
export const COACH_HIGHLIGHTS: CoachHighlight[] = [
  { id: 'coach-01', kind: 'coach', name: 'Andrew Chan', role: 'Governor, HK Institute of Internal Auditors; Head of Internal Audit & Risk Management (former)', focus: 'Internal Audit · Risk & Governance', image: coachImage('e83ee7_402d698ee3f84fc1805d7624937cf316~mv2.jpg', 'Andrew Chan'), href: 'https://www.finexclub.org/andrew-chan' },
  { id: 'coach-02', kind: 'coach', name: 'Apple Lo', role: 'Group Director, Financial and Credit Risk', focus: 'Credit Risk & Ratings · ESG · Investment Banking', image: coachImage('e83ee7_d7ba510d91174c1cbee1fb9db27fc2b4~mv2.png', 'Apple Lo'), href: 'https://www.finexclub.org/career-coach/apple-lo' },
  { id: 'coach-03', kind: 'coach', name: 'Arthur Tan', role: 'Executive Director (former)', focus: 'Institutional Banking · Sales & Client Coverage', image: coachImage('e83ee7_271a7e3db31e4dee84d76d9b48d5e0ac~mv2.jpg', 'Arthur Tan'), href: 'https://www.finexclub.org/career-coach/arthur-tan' },
  { id: 'coach-04', kind: 'coach', name: 'Benjamin Chung', role: 'Chief Risk Officer', focus: 'Enterprise Risk Management · Insurance · Asset Management', image: coachImage('e83ee7_37367b82a568428ba68e3d789dd2b6f2~mv2.png', 'Benjamin Chung'), href: 'https://www.finexclub.org/career-coach/benjamin-chung' },
  { id: 'coach-05', kind: 'coach', name: 'Biswajyoti (BJ) Upadhyay', role: 'Managing Director & Regional Head (former)', focus: 'Institutional Banking · Regional Sales & Transformation', image: coachImage('e83ee7_85cb41a419934d75a6e8ac59a5832425~mv2.png', 'Biswajyoti (BJ) Upadhyay (based in Dubai)'), href: 'https://www.finexclub.org/bj-upadhyay' },
  { id: 'coach-06', kind: 'coach', name: 'Byron Gardiner', role: 'Executive Director / Global Head (former)', focus: 'Treasury & Banking · Corporate Treasury Advisory', image: coachImage('e83ee7_d0535f305b53452eb02240ed956f3ecd~mv2.png', 'Byron Gardiner (based in Singapore)'), href: 'https://www.finexclub.org/byron-gardiner' },
  { id: 'coach-07', kind: 'coach', name: 'Calvin Lee', role: 'Financial Controller & Head of Finance (former)', focus: 'Finance & Accounting · Strategic Planning', image: coachImage('e83ee7_8292059406c449f4a956a5d64ce22dfc~mv2.png', 'Calvin Lee'), href: 'https://www.finexclub.org/calvin-lee' },
  { id: 'coach-08', kind: 'coach', name: 'Cammy Tong', role: 'Senior Regional Director & Head of Life Insurance', focus: 'Insurance & Operations · Customer Experience', image: coachImage('e83ee7_b0c20b5acf154325a22aa6d5fa9673a5~mv2.png', 'Cammy Tong'), href: 'https://www.finexclub.org/career-coach/cammy-tong' },
  { id: 'coach-09', kind: 'coach', name: 'Connie Mak', role: 'Head of Relationship Management (former)', focus: 'Securities Services · Client Relationship Management', image: coachImage('e83ee7_62a368184e3e4ecf98adce7044452d7e~mv2.png', 'Connie Mak'), href: 'https://www.finexclub.org/connie-mak' },
  { id: 'coach-10', kind: 'coach', name: 'Dennis Luk', role: 'Chief Investment Officer', focus: 'Life Insurance · Investment Management', image: coachImage('e83ee7_6bd302864ab343e5a3bb0bca6fa475b6~mv2.png', 'Dennis Luk'), href: 'https://www.finexclub.org/dennis-luk' },
  { id: 'coach-11', kind: 'coach', name: 'Dicky Lee', role: 'CFO & Head of Operations', focus: 'Finance & Operations Leadership', image: coachImage('e83ee7_1261dbda39d74d64bd8d75ce8ffb112b~mv2.png', 'Dicky Lee'), href: 'https://www.finexclub.org/dicky-lee' },
  { id: 'coach-12', kind: 'coach', name: 'Doris Kuo', role: 'Business Consultant & Finance Leader (former)', focus: 'Business Consulting · Accounting · Securities Services', image: coachImage('e83ee7_db32d539531e4c7c96feab7b99f4037a~mv2.png', 'Doris Kuo'), href: 'https://www.finexclub.org/career-coach/doris-kuo' },
  { id: 'coach-13', kind: 'coach', name: 'Edward Lee', role: 'Chief Investment Officer', focus: 'Family Office · Investment · Wealth Management', image: coachImage('e83ee7_49427045c28c4696b2816b14a630e688~mv2.png', 'Edward Lee'), href: 'https://www.finexclub.org/edward-lee' },
  { id: 'coach-14', kind: 'coach', name: 'Hannah Hui', role: 'CEO / Managing Director', focus: 'Fintech & Digital Assets · Virtual Banking', image: coachImage('e83ee7_7b953fdad53f433f9d12174a315abb7c~mv2.png', 'Hannah Hui'), href: 'https://www.finexclub.org/hannah-hui' },
  { id: 'coach-15', kind: 'coach', name: 'Jame DiBiasio', role: 'Founder, Editor & Board Director', focus: 'Fintech Media & Entrepreneurship', image: coachImage('e83ee7_97007c12a5ce4098aaba3014928ed6dc~mv2.png', 'Jame DiBiasio'), href: 'https://www.finexclub.org/jame-dibiasio' },
  { id: 'coach-16', kind: 'coach', name: 'Jeremy Wong', role: 'Founder & CEO; Hedge Fund Manager (former)', focus: 'Fintech · Equity Long/Short · Equity Research', image: coachImage('fe3fd5_becd89718b3348619b18bca182f2b15a~mv2.png', 'Jeremy Wong'), href: 'https://www.finexclub.org/career-coach' },
  { id: 'coach-17', kind: 'coach', name: 'John Wong', role: 'Managing Director', focus: 'Transaction Banking & Fintech · Web3', image: coachImage('e83ee7_a8339fae8bdd48429b037288a7b286cc~mv2.png', 'John Wong'), href: 'https://www.finexclub.org/career-coach/john-wong' },
  { id: 'coach-18', kind: 'coach', name: 'Katherine Lee', role: 'Executive Director, Product Management', focus: 'Product & Relationship Management · Program Leadership', image: coachImage('e83ee7_0e1fe10bc0ed47fda64da46d852135e9~mv2.png', 'Katherine Lee'), href: 'https://www.finexclub.org/katherine-lee' },
  { id: 'coach-19', kind: 'coach', name: 'Ken Cheung', role: 'Chief Asian FX Strategist (former)', focus: 'Global Markets · FX Strategy', image: coachImage('e83ee7_80543a22c5a047288a62f0143cac51e2~mv2.png', 'Ken Cheung'), href: 'https://www.finexclub.org/ken-cheung' },
  { id: 'coach-20', kind: 'coach', name: 'Lawrence Au', role: 'Asia-Pacific CEO, Securities Services (former)', focus: 'Securities Services · Regional Leadership', image: coachImage('e83ee7_bf0cfd6e857f45fa8e41bf7aa98064f7~mv2.png', 'Lawrence Au'), href: 'https://www.finexclub.org/career-coach/lawrence-au' },
  { id: 'coach-21', kind: 'coach', name: 'Margaret Chan', role: 'Executive Director', focus: 'Securities Services · Pricing & Risk Management', image: coachImage('e83ee7_d1a6ad4e9c674b08959cbe8d5b62f61e~mv2.png', 'Margaret Chan'), href: 'https://www.finexclub.org/margaret-chan' },
  { id: 'coach-22', kind: 'coach', name: 'Morris Hui, CFA', role: 'Founder / Group Treasurer / Portfolio Manager', focus: 'Entrepreneurship · Finance · Investment Banking', image: coachImage('e83ee7_c4ed07bf2bea4023ab947d15860b95b8~mv2.png', 'Morris Hui, CFA'), href: 'https://www.finexclub.org/morris-hui' },
  { id: 'coach-23', kind: 'coach', name: 'Nelson Chau', role: 'Chief Operating Officer (former)', focus: 'Investment Operations · Fund Accounting', image: coachImage('e83ee7_6837d6f800154701918282892a67b071~mv2.png', 'Nelson Chau (based in Australia)'), href: 'https://www.finexclub.org/career-coach/nelson-chau' },
  { id: 'coach-24', kind: 'coach', name: 'Nicholas Yip', role: 'Corporate Treasurer & Director, Digital Assets', focus: 'Corporate Treasury · Fintech & Digital Assets', image: coachImage('e83ee7_cf268e15f7c14bd2a1817f01d6cc9586~mv2.png', 'Nicholas Yip'), href: 'https://www.finexclub.org/nicholas-yip' },
  { id: 'coach-25', kind: 'coach', name: 'Patrick Leung', role: 'Wealth Management Advisor', focus: 'Finance & Wealth Management', image: coachImage('e83ee7_085bf1f5c45e47e9b95e148970cf74d2~mv2.png', 'Patrick Leung'), href: 'https://www.finexclub.org/patrick-leung' },
  { id: 'coach-26', kind: 'coach', name: 'Raymong Chung', role: 'General Manager', focus: 'Securities Services · Digital Assets · Tokenization', image: coachImage('e83ee7_ef2da9f15b724535a280b605fa5b5749~mv2.png', 'Raymong Chung'), href: 'https://www.finexclub.org/raymond-chung' },
  { id: 'coach-27', kind: 'coach', name: 'Shannon Chow', role: 'Managing Director', focus: 'Private Markets · Investment Solutions', image: coachImage('e83ee7_350ec338396e48f9803ec04b635061c1~mv2.png', 'Shannon Chow'), href: 'https://www.finexclub.org/shannon-chow' },
  { id: 'coach-28', kind: 'coach', name: 'Simon Cheung', role: 'Head of Risk Management', focus: 'Insurance Risk · Enterprise Risk & Actuarial', image: coachImage('e83ee7_029f3022df224e3eb5e64a9ae81bd60b~mv2.png', 'Simon Cheung'), href: 'https://www.finexclub.org/simon-cheung' },
  { id: 'coach-29', kind: 'coach', name: 'Simon Tung', role: 'Audit Partner', focus: 'Audit & Assurance · Capital Markets & IPO', image: coachImage('e83ee7_80928bc0c7e2430f8de14bb70d7ab4ee~mv2.png', 'Simon Tung'), href: 'https://www.finexclub.org/simon-tung' },
  { id: 'coach-30', kind: 'coach', name: 'Timothy Chan', role: 'Head of Global Markets Sales', focus: 'Global Markets (FICC) · Sales & Green Finance', image: coachImage('e83ee7_b6e1e929af2f4bbfb021f4dc79feb5e1~mv2.png', 'Timothy Chan'), href: 'https://www.finexclub.org/timothy-chan' },
  { id: 'coach-31', kind: 'coach', name: 'Vera Lau', role: 'Head of Sales', focus: 'Sales & Relationship Management', image: coachImage('e83ee7_c3284de5a3c94c5cb0d3c9867b77598c~mv2.png', 'Vera Lau'), href: 'https://www.finexclub.org/vera-lau' },
  { id: 'coach-32', kind: 'coach', name: 'Vincent Huen', role: 'Consulting Partner (former)', focus: 'Management Consulting (TMT) · Transformation & Strategy', image: coachImage('e83ee7_4403b66d2f8a4f78954d6a80bcc23cbb~mv2.png', 'Vincent Huen'), href: 'https://www.finexclub.org/vincent-huen' },
]
