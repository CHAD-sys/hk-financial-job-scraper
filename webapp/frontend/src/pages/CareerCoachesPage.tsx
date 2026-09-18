/**
 * THESIS: A finance-expertise ledger makes the right human legible; it refuses
 * the anonymous, undifferentiated headshot grid.
 * OWN-WORLD: FinEx navy and warm-white fields, real portraits, gold indexing,
 * rectangular filter tabs, and hairline-led profile cards.
 * STORY: Choose a domain, compare proven specialties, then request a meeting
 * from the coach's own FinEx profile.
 * FIRST VIEWPORT: A dark editorial introduction faces three named coach
 * portraits; the complete expertise filter begins immediately below it.
 * FORM: First-ranked direct structure—grouped expertise ledger, precisely
 * specified extension, so no concept seed was needed.
 */
import { ArrowDown, Search, Sparkles } from 'lucide-react'
import { useMemo, useState } from 'react'
import CareerCoachCard from '../components/CareerCoachCard'
import Nav from '../components/Nav'
import {
  CAREER_COACHES,
  CAREER_COACH_GROUPS,
  COACH_DOMAINS,
  COACH_SPECIALTIES,
  coachCountForDomain,
  coachesForFilters,
  type CoachDomainFilter,
  type CoachSpecialtyFilter,
} from '../content/careerCoaches'

const FEATURED_COACHES = ['Morris Hui, CFA', 'Benjamin Chung', 'Byron Gardiner'].map(name => (
  CAREER_COACHES.find(coach => coach.name === name)!
))

export default function CareerCoachesPage() {
  const [activeDomain, setActiveDomain] = useState<CoachDomainFilter>('All expertise')
  const [specialty, setSpecialty] = useState<CoachSpecialtyFilter>('All specialties')
  const [query, setQuery] = useState('')

  const visibleCoaches = useMemo(() => coachesForFilters({
    domain: activeDomain,
    specialty,
    query,
  }), [activeDomain, query, specialty])
  const hasRefinements = specialty !== 'All specialties' || Boolean(query.trim())

  const visibleGroups = useMemo(() => (
    activeDomain === 'All expertise' && !hasRefinements
      ? CAREER_COACH_GROUPS
      : [{ domain: activeDomain === 'All expertise' ? 'Matching coaches' : activeDomain, coaches: visibleCoaches }]
  ), [activeDomain, hasRefinements, visibleCoaches])

  const visibleCount = visibleCoaches.length
  const resetFilters = () => {
    setActiveDomain('All expertise')
    setSpecialty('All specialties')
    setQuery('')
  }

  return (
    <div className="coach-directory-page">
      <title>Career Coaches by Finance Expertise | FinEx Careers</title>
      <meta name="description" content="Find a FinEx career coach by domain expertise, from accounting and risk to markets, investment, wealth, custody and digital assets." />
      <Nav />
      <main id="main-content">
        <header className="coach-directory-hero">
          <div className="mx-auto max-w-7xl px-6 py-16 lg:px-8 lg:py-20">
            <div className="coach-directory-hero__layout">
              <div className="coach-directory-hero__copy">
                <p><Sparkles size={16} aria-hidden="true" /> FinEx career consultation</p>
                <h1>Find the perspective<br />your next move needs.</h1>
                <p>
                  Browse {CAREER_COACHES.length} senior finance leaders by the work they know firsthand—from
                  accounting and risk to investment, markets, wealth, custody, and digital assets.
                </p>
                <a href="#coach-directory-filters">
                  Browse expertise
                  <ArrowDown size={17} aria-hidden="true" />
                </a>
              </div>

              <div className="coach-directory-hero__portraits" aria-label="Featured FinEx career coaches">
                {FEATURED_COACHES.map((coach, index) => (
                  <figure key={coach.id}>
                    <img src={coach.image} alt="" width={280} height={280} />
                    <figcaption>
                      <span>{String(index + 1).padStart(2, '0')}</span>
                      <strong>{coach.name}</strong>
                      <small>{coach.primaryDomain}</small>
                    </figcaption>
                  </figure>
                ))}
              </div>
            </div>
          </div>
        </header>

        <section className="coach-directory" aria-labelledby="coach-directory-heading">
          <div className="mx-auto max-w-7xl px-6 py-12 lg:px-8 lg:py-16">
            <div className="coach-directory__intro">
              <div>
                <h2 id="coach-directory-heading">Browse by domain expertise</h2>
                <p>Every coach has one primary group and may appear in related filters where their experience crosses disciplines.</p>
              </div>
              <p className="coach-directory__count" aria-live="polite">
                <strong>{visibleCount}</strong> {visibleCount === 1 ? 'coach matches' : 'coaches match'} {hasRefinements ? 'these filters' : 'this field'}
              </p>
            </div>

            <div id="coach-directory-filters" className="coach-directory__filters" aria-label="Filter coaches by expertise">
              {(['All expertise', ...COACH_DOMAINS] as CoachDomainFilter[]).map(domain => (
                <button
                  key={domain}
                  type="button"
                  aria-pressed={activeDomain === domain}
                  onClick={() => setActiveDomain(domain)}
                >
                  <span>{domain}</span>
                  <strong>{coachCountForDomain(domain)}</strong>
                </button>
              ))}
            </div>

            <fieldset className="coach-directory__refine" aria-label="Refine coach results">
              <legend>Refine your match</legend>
              <label className="coach-directory__search">
                <Search size={16} aria-hidden="true" />
                <span className="sr-only">Search coaches</span>
                <input
                  type="search"
                  value={query}
                  onChange={event => setQuery(event.target.value)}
                  placeholder="Search name, role, or focus"
                  aria-label="Search coaches"
                />
              </label>
              <label className="coach-directory__select">
                <span>Specialty</span>
                <select value={specialty} onChange={event => setSpecialty(event.target.value as CoachSpecialtyFilter)}>
                  <option>All specialties</option>
                  {COACH_SPECIALTIES.map(item => <option key={item}>{item}</option>)}
                </select>
              </label>
              <button
                type="button"
                className="coach-directory__clear"
                onClick={resetFilters}
                disabled={activeDomain === 'All expertise' && !hasRefinements}
              >
                Clear filters
              </button>
            </fieldset>

            <div id="coach-directory-results" className="coach-directory__groups">
              {visibleCount > 0 ? visibleGroups.map(group => (
                <section key={group.domain} className="coach-domain-group" aria-labelledby={`coach-domain-${slugify(group.domain)}`}>
                  <header>
                    <h2 id={`coach-domain-${slugify(group.domain)}`}>{group.domain}</h2>
                    <span>{group.coaches.length} {group.coaches.length === 1 ? 'coach' : 'coaches'}</span>
                  </header>
                  <div className="coach-domain-group__grid">
                    {group.coaches.map(coach => <CareerCoachCard key={coach.id} coach={coach} />)}
                  </div>
                </section>
              )) : (
                <div className="coach-directory__empty" role="status">
                  <h2>No coaches match these filters.</h2>
                  <p>Try a broader specialty or clear the filters to return to the full directory.</p>
                </div>
              )}
            </div>
          </div>
        </section>
      </main>
    </div>
  )
}

function slugify(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '')
}
