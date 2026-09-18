import { ArrowUpRight, CalendarClock, MapPin, Search, SlidersHorizontal } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import Nav from '../components/Nav'
import CareerCoachingTag from '../components/CareerCoachingTag'
import MTOpenEmployerBanner, { type MTOpenEmployer } from '../components/MTOpenEmployerBanner'
import MTProgrammeCard from '../components/MTProgrammeCard'
import { fetchManagementTraineeRoles, type Job } from '../api/client'
import { MT_OPENINGS } from '../content/mtOpenings'
import { LINKED_MT_PROGRAMMES, MT_INDUSTRIES, MT_PROGRAMMES } from '../content/managementTraineePrograms'

const STATUS_FILTERS = ['All statuses', 'Open now', 'Not currently open'] as const

function formatDate(date: string) {
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Hong_Kong',
  }).format(new Date(`${date}T00:00:00+08:00`))
}

function formatPostedAt(date: string | null) {
  if (!date) return 'Posted date not stated'
  return `Posted ${new Intl.DateTimeFormat('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Hong_Kong',
  }).format(new Date(date))}`
}

function openingId(key: string) {
  return `mt-opening-${key.replace(/[^a-z0-9]+/gi, '-').replace(/(^-|-$)/g, '').toLocaleLowerCase()}`
}

interface EmployerEntry extends MTOpenEmployer {
  urgency: number
}

function openEmployers(liveRoles: readonly Job[] | null): MTOpenEmployer[] {
  const entries = [
    ...(liveRoles ?? []).map(role => ({
      company: role.company,
      targetId: openingId(`${role.source}-${role.source_id}`),
      urgency: role.posted_at
        ? Number.MAX_SAFE_INTEGER - new Date(role.posted_at).getTime()
        : Number.MAX_SAFE_INTEGER,
    })),
    ...MT_OPENINGS.map(opening => ({
      company: opening.company,
      targetId: openingId(opening.id),
      urgency: opening.deadline ? new Date(`${opening.deadline}T00:00:00+08:00`).getTime() : Number.MAX_SAFE_INTEGER,
    })),
  ]
  const employers = new Map<string, EmployerEntry>()
  for (const entry of entries) {
    const key = entry.company.trim().toLocaleLowerCase()
    const current = employers.get(key)
    employers.set(key, !current
      ? { ...entry, roleCount: 1 }
      : entry.urgency < current.urgency
        ? { ...entry, roleCount: current.roleCount + 1 }
        : { ...current, roleCount: current.roleCount + 1 })
  }
  return [...employers.values()].map(({ urgency: _urgency, ...employer }) => employer)
}

export default function ManagementTraineePage() {
  const [query, setQuery] = useState('')
  const [industry, setIndustry] = useState('All industries')
  const [status, setStatus] = useState<(typeof STATUS_FILTERS)[number]>('All statuses')
  const [liveRoles, setLiveRoles] = useState<Job[] | null>(null)
  const [liveRolesError, setLiveRolesError] = useState(false)
  const [highlightedOpening, setHighlightedOpening] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    Promise.resolve()
      .then(fetchManagementTraineeRoles)
      .then(response => { if (active) setLiveRoles(response.jobs) })
      .catch(() => { if (active) setLiveRolesError(true) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!highlightedOpening) return undefined
    document.getElementById(highlightedOpening)?.focus({ preventScroll: true })
    const timeout = window.setTimeout(() => setHighlightedOpening(null), 4_000)
    return () => window.clearTimeout(timeout)
  }, [highlightedOpening])

  const programmes = useMemo(() => {
    const term = query.trim().toLocaleLowerCase()
    return MT_PROGRAMMES.filter(programme => {
      const matchesIndustry = industry === 'All industries' || programme.industry === industry
      const matchesQuery = !term || `${programme.company} ${programme.companyChinese}`.toLocaleLowerCase().includes(term)
      const matchesStatus = status === 'All statuses'
        || (status === 'Open now' && programme.application?.status === 'open')
        || (status === 'Not currently open' && programme.application?.status !== 'open')
      return matchesIndustry && matchesQuery && matchesStatus
    })
  }, [industry, query, status])
  const employers = useMemo(() => openEmployers(liveRoles), [liveRoles])

  return (
    <div className="mt-directory-page">
      <title>Hong Kong Management Trainee Programmes | FinEx Careers</title>
      <meta name="description" content={`Explore Management Trainee programmes from ${MT_PROGRAMMES.length} Hong Kong employers across eight industries.`} />
      <Nav />
      <main id="main-content">
        <header className="mt-directory-hero">
          <div className="mx-auto max-w-7xl px-6 py-16 lg:px-8 lg:py-20">
            <p className="mt-directory-hero__kicker">The MT deadline desk</p>
            <h1>Start where tomorrow&rsquo;s<br />leaders start.</h1>
            <div className="mt-directory-hero__summary">
              <p>A focused directory of Hong Kong Management Trainee programmes—built for candidates who cannot afford to miss an application window.</p>
            </div>
          </div>
        </header>

        <MTOpenEmployerBanner
          employers={employers}
          logoCompanies={MT_PROGRAMMES.map(programme => programme.company)}
          onSelect={setHighlightedOpening}
        />

        <section className="mt-openings" aria-labelledby="mt-openings-heading">
          <div className="mx-auto max-w-7xl px-6 py-12 lg:px-8 lg:py-16">
            <div className="mt-openings__heading">
              <div>
                <p>Active &amp; available</p>
                <h2 id="mt-openings-heading">MT roles from the live careers database.</h2>
              </div>
              <p>Active Management Trainee Roles flow here from the same daily pipeline that runs the Careers board.</p>
            </div>
            <div className="mt-openings__subhead">
              <div>
                <h3>Active roles in FinEx Careers</h3>
                <p>These entries are still active in the normal jobs database and include direct application destinations.</p>
              </div>
              <p aria-live="polite">
                {liveRoles ? `${liveRoles.length} active ${liveRoles.length === 1 ? 'role' : 'roles'} from the careers database` : 'Refreshing active roles…'}
              </p>
            </div>
            {liveRolesError ? (
              <p className="mt-openings__feed-error" role="status">The live careers feed is temporarily unavailable. Curated application links remain available below.</p>
            ) : liveRoles ? (
              liveRoles.length ? (
                <ol className="mt-openings__list">
                  {liveRoles.map(role => {
                    const id = openingId(`${role.source}-${role.source_id}`)
                    const selected = highlightedOpening === id
                    return (
                    <li id={id} key={`${role.source}-${role.source_id}`} tabIndex={-1} className={`mt-opening mt-opening--board${selected ? ' mt-opening--selected' : ''}`}>
                      {selected && <span className="mt-opening__selection" role="status">Selected from employer gallery</span>}
                      <div className="mt-opening__status" aria-label="Role is active in the careers database">Active</div>
                      <div className="mt-opening__role">
                        <p>{role.company}</p>
                        <h3>{role.title}</h3>
                      </div>
                      <div className="mt-opening__meta">
                        <span><MapPin size={15} aria-hidden="true" /> {role.locations.length ? role.locations.join(' · ') : 'Hong Kong'}</span>
                        <span><CalendarClock size={15} aria-hidden="true" /> {formatPostedAt(role.posted_at)}</span>
                      </div>
                      <CareerCoachingTag company={role.company} />
                      <a href={role.url} target="_blank" rel="noopener noreferrer" aria-label={`${role.application_label ?? 'View or apply'}: ${role.title} at ${role.company}`}>
                        {role.application_label ?? 'View or apply'} <ArrowUpRight size={16} aria-hidden="true" />
                      </a>
                    </li>
                    )
                  })}
                </ol>
              ) : <p className="mt-openings__feed-error" role="status">No active Management Trainee Roles are currently flowing from the careers database.</p>
            ) : <div className="mt-openings__loading" aria-live="polite" aria-label="Loading active MT roles" />}

            <div className="mt-openings__curated">
              <div className="mt-openings__subhead">
                <div>
                  <h3>Curated application links</h3>
                  <p>Additional current intakes maintained separately while their source-specific checks are being automated.</p>
                </div>
              </div>
              <ol className="mt-openings__list">
                {MT_OPENINGS.map(opening => {
                  const id = openingId(opening.id)
                  const selected = highlightedOpening === id
                  return (
                  <li id={id} key={opening.id} tabIndex={-1} className={`mt-opening${selected ? ' mt-opening--selected' : ''}`}>
                    {selected && <span className="mt-opening__selection" role="status">Selected from employer gallery</span>}
                    <div className="mt-opening__status" aria-label="Application currently open">Open</div>
                    <div className="mt-opening__role">
                      <p>{opening.company}</p>
                      <h3>{opening.role}</h3>
                      {opening.note && <span>{opening.note}</span>}
                    </div>
                    <div className="mt-opening__meta">
                      <span><MapPin size={15} aria-hidden="true" /> {opening.location}</span>
                      <span><CalendarClock size={15} aria-hidden="true" /> {opening.deadline ? `Closes ${formatDate(opening.deadline)}` : 'Deadline not stated'}</span>
                    </div>
                    <CareerCoachingTag company={opening.company} />
                    <a href={opening.applicationUrl} target="_blank" rel="noopener noreferrer" aria-label={`${opening.applicationLabel ?? 'Apply now'}: ${opening.role} at ${opening.company}`}>
                      {opening.applicationLabel ?? 'Apply now'} <ArrowUpRight size={16} aria-hidden="true" />
                    </a>
                  </li>
                  )
                })}
              </ol>
            </div>
            <p className="mt-openings__provenance">The live feed follows the normal jobs database lifecycle; “active” is a current database state, not an invented deadline.</p>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-6 py-12 lg:px-8" aria-labelledby="mt-directory-heading">
          <div className="mt-directory-toolbar">
            <div>
              <h2 id="mt-directory-heading">Programme directory</h2>
              <p>{programmes.length} {programmes.length === 1 ? 'employer' : 'employers'} shown</p>
            </div>
            <div className="mt-directory-controls">
              <label>
                <span className="sr-only">Search employers</span>
                <Search size={18} aria-hidden="true" />
                <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search employers" />
              </label>
              <label>
                <span className="sr-only">Filter by industry</span>
                <SlidersHorizontal size={18} aria-hidden="true" />
                <select value={industry} onChange={event => setIndustry(event.target.value)}>
                  <option>All industries</option>
                  {MT_INDUSTRIES.map(item => <option key={item}>{item}</option>)}
                </select>
              </label>
              <label>
                <span className="sr-only">Filter by application status</span>
                <select value={status} onChange={event => setStatus(event.target.value as (typeof STATUS_FILTERS)[number])}>
                  {STATUS_FILTERS.map(item => <option key={item}>{item}</option>)}
                </select>
              </label>
            </div>
          </div>

            <div className="mt-directory-notice" role="note">
            <strong>Directory status is evidence-led.</strong> {LINKED_MT_PROGRAMMES.length} employers are linked. “Not currently open” means no current opening has been verified—it does not claim that an employer has ended its programme.
          </div>

          {programmes.length ? (
            <div className="mt-directory-grid">
              {programmes.map(programme => <MTProgrammeCard key={programme.id} programme={programme} compact />)}
            </div>
          ) : (
            <div className="mt-directory-empty">
              <h3>No employers match those filters.</h3>
              <button type="button" onClick={() => { setQuery(''); setIndustry('All industries'); setStatus('All statuses') }}>Clear search and filters</button>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
