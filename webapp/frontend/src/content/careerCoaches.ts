import {
  COACH_HIGHLIGHTS,
  type CoachHighlight,
} from '../components/highlights/weeklyHighlights.data'

const ALL_COACH_DOMAINS = [
  'Accounting & Finance',
  'Risk & Compliance',
  'Treasury & Markets',
  'Investment',
  'Investment Banking',
  'Private Equity, Family Offices, Wealth',
  'Custody, Funds, and Assets Servicing',
  'Digital Assets & FinTech',
  'Insurance & Actuarial',
  'Institutional Banking & Sales',
  'Strategy, Transformation & Consulting',
] as const

export type CoachDomain = (typeof ALL_COACH_DOMAINS)[number]

/** Categories currently offered in the public directory. Paused categories
 * remain valid internal assignments so they can be restored without rebuilding
 * the roster. */
export const COACH_DOMAINS = [
  'Accounting & Finance',
  'Risk & Compliance',
  'Treasury & Markets',
  'Investment',
  'Private Equity, Family Offices, Wealth',
  'Custody, Funds, and Assets Servicing',
  'Digital Assets & FinTech',
  'Institutional Banking & Sales',
  'Strategy, Transformation & Consulting',
] as const satisfies readonly CoachDomain[]

export type PublicCoachDomain = (typeof COACH_DOMAINS)[number]
export type CoachDomainFilter = PublicCoachDomain | 'All expertise'

export interface CareerCoach extends CoachHighlight {
  primaryDomain: PublicCoachDomain
  domains: readonly CoachDomain[]
  appointmentUrl: string
}

interface CoachExpertise {
  primaryDomain: PublicCoachDomain
  domains: readonly CoachDomain[]
}

const EXPERTISE_BY_COACH_ID: Readonly<Record<string, CoachExpertise>> = {
  'coach-01': expertise('Risk & Compliance'),
  'coach-02': expertise('Risk & Compliance', 'Investment Banking', 'Investment'),
  'coach-03': expertise('Institutional Banking & Sales'),
  'coach-04': expertise('Risk & Compliance', 'Insurance & Actuarial'),
  'coach-05': expertise('Institutional Banking & Sales', 'Strategy, Transformation & Consulting'),
  'coach-06': expertise('Treasury & Markets'),
  'coach-07': expertise('Accounting & Finance'),
  'coach-08': expertise('Strategy, Transformation & Consulting', 'Insurance & Actuarial'),
  'coach-09': expertise('Custody, Funds, and Assets Servicing'),
  'coach-10': expertise('Investment', 'Insurance & Actuarial'),
  'coach-11': expertise('Accounting & Finance', 'Strategy, Transformation & Consulting'),
  'coach-12': expertise('Accounting & Finance', 'Custody, Funds, and Assets Servicing', 'Strategy, Transformation & Consulting'),
  'coach-13': expertise('Private Equity, Family Offices, Wealth', 'Investment', 'Strategy, Transformation & Consulting'),
  'coach-14': expertise('Digital Assets & FinTech'),
  'coach-15': expertise('Digital Assets & FinTech', 'Strategy, Transformation & Consulting'),
  'coach-16': expertise('Investment', 'Digital Assets & FinTech'),
  'coach-17': expertise('Digital Assets & FinTech', 'Institutional Banking & Sales'),
  'coach-18': expertise('Custody, Funds, and Assets Servicing'),
  'coach-19': expertise('Treasury & Markets'),
  'coach-20': expertise('Custody, Funds, and Assets Servicing', 'Strategy, Transformation & Consulting'),
  'coach-21': expertise('Custody, Funds, and Assets Servicing'),
  'coach-22': expertise('Treasury & Markets', 'Investment Banking', 'Investment', 'Institutional Banking & Sales', 'Strategy, Transformation & Consulting'),
  'coach-23': expertise('Custody, Funds, and Assets Servicing'),
  'coach-24': expertise('Treasury & Markets', 'Digital Assets & FinTech'),
  'coach-25': expertise('Private Equity, Family Offices, Wealth'),
  'coach-26': expertise('Custody, Funds, and Assets Servicing'),
  'coach-27': expertise('Investment', 'Private Equity, Family Offices, Wealth'),
  'coach-28': expertise('Risk & Compliance', 'Insurance & Actuarial'),
  'coach-29': expertise('Accounting & Finance', 'Investment Banking'),
  'coach-30': expertise('Treasury & Markets', 'Institutional Banking & Sales'),
  'coach-31': expertise('Institutional Banking & Sales'),
  'coach-32': expertise('Strategy, Transformation & Consulting'),
}

const APPOINTMENT_URL = 'https://www.finexclub.org/mentor-program'

function expertise(primaryDomain: PublicCoachDomain, ...relatedDomains: CoachDomain[]): CoachExpertise {
  return { primaryDomain, domains: Array.from(new Set([primaryDomain, ...relatedDomains])) }
}

export function isPublicCoachDomain(domain: string): domain is PublicCoachDomain {
  return (COACH_DOMAINS as readonly string[]).includes(domain)
}

export const CAREER_COACHES: CareerCoach[] = COACH_HIGHLIGHTS.map((coach) => {
  const assignedExpertise = EXPERTISE_BY_COACH_ID[coach.id]
  if (!assignedExpertise) throw new Error(`Missing expertise assignment for ${coach.name}`)

  return { ...coach, ...assignedExpertise, appointmentUrl: APPOINTMENT_URL }
})

export const CAREER_COACH_GROUPS = COACH_DOMAINS.map(domain => ({
  domain,
  coaches: CAREER_COACHES.filter(coach => coach.domains.includes(domain)),
})).filter(group => group.coaches.length > 0)

/** The public FinEx focus phrases are retained verbatim for precise filtering. */
export const COACH_SPECIALTIES = Array.from(new Set(
  CAREER_COACHES.flatMap(coach => coach.focus.split(' · ')),
)).sort((left, right) => left.localeCompare(right))

export type CoachSpecialtyFilter = (typeof COACH_SPECIALTIES)[number] | 'All specialties'

export interface CoachFilters {
  domain?: CoachDomainFilter
  specialty?: CoachSpecialtyFilter
  query?: string
}

export function coachesForDomain(domain: CoachDomainFilter): CareerCoach[] {
  if (domain === 'All expertise') return CAREER_COACHES
  return CAREER_COACHES.filter(coach => coach.domains.includes(domain))
}

export function coachCountForDomain(domain: CoachDomainFilter): number {
  return coachesForDomain(domain).length
}

export function coachesForFilters({
  domain = 'All expertise',
  specialty = 'All specialties',
  query = '',
}: CoachFilters): CareerCoach[] {
  const normalizedQuery = query.trim().toLocaleLowerCase()

  return coachesForDomain(domain).filter(coach => {
    const matchesSpecialty = specialty === 'All specialties' || coach.focus.split(' · ').includes(specialty)
    const searchableText = `${coach.name} ${coach.role} ${coach.focus}`.toLocaleLowerCase()
    return matchesSpecialty && (!normalizedQuery || searchableText.includes(normalizedQuery))
  })
}
