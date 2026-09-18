import {
  COACH_HIGHLIGHTS,
  type CoachHighlight,
} from '../components/highlights/weeklyHighlights.data'

export const COACH_DOMAINS = [
  'Accounting & Finance',
  'Risk & Compliance',
  'Treasury & Markets',
  'Investment',
  'Investment Banking',
  'Private Banking & Wealth',
  'Custody & Funds',
  'Digital Assets & FinTech',
  'Insurance & Actuarial',
  'Institutional Banking & Sales',
  'Strategy & Transformation',
] as const

export type CoachDomain = (typeof COACH_DOMAINS)[number]
export type CoachDomainFilter = CoachDomain | 'All expertise'

export interface CareerCoach extends CoachHighlight {
  primaryDomain: CoachDomain
  domains: readonly CoachDomain[]
  appointmentUrl: string
}

interface CoachExpertise {
  primaryDomain: CoachDomain
  domains: readonly CoachDomain[]
}

const EXPERTISE_BY_COACH_ID: Readonly<Record<string, CoachExpertise>> = {
  'coach-01': expertise('Risk & Compliance'),
  'coach-02': expertise('Risk & Compliance', 'Investment Banking'),
  'coach-03': expertise('Institutional Banking & Sales'),
  'coach-04': expertise('Risk & Compliance', 'Insurance & Actuarial', 'Investment'),
  'coach-05': expertise('Institutional Banking & Sales', 'Strategy & Transformation'),
  'coach-06': expertise('Treasury & Markets', 'Institutional Banking & Sales'),
  'coach-07': expertise('Accounting & Finance', 'Strategy & Transformation'),
  'coach-08': expertise('Insurance & Actuarial', 'Strategy & Transformation'),
  'coach-09': expertise('Custody & Funds', 'Institutional Banking & Sales'),
  'coach-10': expertise('Investment', 'Insurance & Actuarial'),
  'coach-11': expertise('Accounting & Finance', 'Strategy & Transformation'),
  'coach-12': expertise('Accounting & Finance', 'Custody & Funds', 'Strategy & Transformation'),
  'coach-13': expertise('Private Banking & Wealth', 'Investment'),
  'coach-14': expertise('Digital Assets & FinTech', 'Institutional Banking & Sales'),
  'coach-15': expertise('Digital Assets & FinTech', 'Strategy & Transformation'),
  'coach-16': expertise('Investment', 'Digital Assets & FinTech'),
  'coach-17': expertise('Digital Assets & FinTech', 'Institutional Banking & Sales'),
  'coach-18': expertise('Strategy & Transformation', 'Institutional Banking & Sales'),
  'coach-19': expertise('Treasury & Markets'),
  'coach-20': expertise('Custody & Funds', 'Strategy & Transformation'),
  'coach-21': expertise('Custody & Funds', 'Risk & Compliance'),
  'coach-22': expertise('Investment Banking', 'Treasury & Markets', 'Investment'),
  'coach-23': expertise('Custody & Funds', 'Accounting & Finance', 'Investment'),
  'coach-24': expertise('Treasury & Markets', 'Digital Assets & FinTech'),
  'coach-25': expertise('Private Banking & Wealth', 'Accounting & Finance'),
  'coach-26': expertise('Custody & Funds', 'Digital Assets & FinTech'),
  'coach-27': expertise('Investment', 'Private Banking & Wealth'),
  'coach-28': expertise('Risk & Compliance', 'Insurance & Actuarial'),
  'coach-29': expertise('Accounting & Finance', 'Investment Banking'),
  'coach-30': expertise('Treasury & Markets', 'Institutional Banking & Sales'),
  'coach-31': expertise('Institutional Banking & Sales', 'Private Banking & Wealth'),
  'coach-32': expertise('Strategy & Transformation'),
}

const APPOINTMENT_URL = 'https://www.finexclub.org/mentor-program'

function expertise(primaryDomain: CoachDomain, ...relatedDomains: CoachDomain[]): CoachExpertise {
  return { primaryDomain, domains: [primaryDomain, ...relatedDomains] }
}

export const CAREER_COACHES: CareerCoach[] = COACH_HIGHLIGHTS.map((coach) => {
  const assignedExpertise = EXPERTISE_BY_COACH_ID[coach.id]
  if (!assignedExpertise) throw new Error(`Missing expertise assignment for ${coach.name}`)

  return { ...coach, ...assignedExpertise, appointmentUrl: APPOINTMENT_URL }
})

export const CAREER_COACH_GROUPS = COACH_DOMAINS.map(domain => ({
  domain,
  coaches: CAREER_COACHES.filter(coach => coach.primaryDomain === domain),
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
