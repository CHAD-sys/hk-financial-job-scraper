const MORRIS_HUI = {
  name: 'Morris Hui, CFA',
  href: 'https://www.finexclub.org/morris-hui',
} as const

/**
 * A deliberately narrow employer-to-coach recommendation. It is not a
 * matching algorithm: these are the four institutions for which FinEx has
 * explicitly chosen Morris as the most relevant coach.
 */
export function recommendedCoachForCompany(company: string) {
  const normalized = company.toLocaleLowerCase()
  return /(?:hong kong jockey club|\bhkjc\b|hong kong monetary authority|\bhkma\b|standard chartered|\bscb\b|\bhsbc\b)/.test(normalized)
    ? MORRIS_HUI
    : null
}
