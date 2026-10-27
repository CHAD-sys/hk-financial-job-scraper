import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowRight, BookOpen, BriefcaseBusiness, GraduationCap, MessageCircleMore, Search, TrendingUp } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { Job } from '../api/client'
import { fetchHighPayingRoles } from '../api/client'
import JobCard from './JobCard'
import MTWorkbookProgrammeCard from './MTWorkbookProgrammeCard'
import { MTOpenEmployerLogoBand } from './MTOpenEmployerBanner'
import {
  compareMTProgrammePrestige,
  groupMTWorkbookProgrammesByEmployer,
  MT_WORKBOOK_PROGRAMMES,
} from '../content/mtWorkbookProgrammes'
import { CAREER_COACH_GROUPS, COACH_DOMAINS, type CoachDomainFilter } from '../content/careerCoaches'
import { STRANDS } from '../content/learning'
import WeeklyHighlights from './highlights/WeeklyHighlights'
import { scrollToTop } from '../utils/scroll'

type DestinationId = 'hot' | 'mt' | 'coaching' | 'education'

const DESTINATIONS: Array<{
  id: DestinationId
  label: string
  desktopLabel: string
  summary: string
  icon: typeof TrendingUp
}> = [
  {
    id: 'hot', label: 'Hot jobs', desktopLabel: 'Hot jobs', summary: 'Salary-led roles', icon: TrendingUp,
  },
  {
    id: 'mt', label: 'MT', desktopLabel: 'MT programmes', summary: 'Graduate pathways', icon: GraduationCap,
  },
  {
    id: 'coaching', label: 'Coaching', desktopLabel: 'Coaching', summary: 'Expert perspective', icon: MessageCircleMore,
  },
  {
    id: 'education', label: 'Education', desktopLabel: 'Education', summary: 'Skills and insight', icon: BookOpen,
  },
]

interface Props {
  onSearch: (query: string) => void
  allowEmptySubmit?: boolean
  saved: (job: Job) => boolean
  onToggleSave: (job: Job) => void
  onSelect: (job: Job) => void
}

export default function MobileDiscoveryHome({
  onSearch, allowEmptySubmit = false, saved, onToggleSave, onSelect,
}: Props) {
  const [activeTab, setActiveTab] = useState<DestinationId>('hot')
  const [coachDomain, setCoachDomain] = useState<CoachDomainFilter>('All expertise')
  const [query, setQuery] = useState('')
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([])
  const hotJobsLoaded = useRef(false)
  const activeDestination = DESTINATIONS.find(destination => destination.id === activeTab) ?? DESTINATIONS[0]
  const mobileCoachGroups = useMemo(() => coachDomain === 'All expertise'
    ? CAREER_COACH_GROUPS
    : CAREER_COACH_GROUPS.filter(group => group.domain === coachDomain), [coachDomain])
  // The mobile landing view is a concise slice of the same workbook-backed
  // directory as /management-trainee. This avoids the live board leaving the
  // landing page with a single card while verified active applications exist.
  const openMtEmployers = useMemo(() => groupMTWorkbookProgrammesByEmployer(MT_WORKBOOK_PROGRAMMES)
    .filter(employer => employer.programmes.some(programme => programme.status === 'Active'))
    .sort((left, right) => compareMTProgrammePrestige(left.programmes[0], right.programmes[0]))
    .slice(0, 8), [])

  useEffect(() => {
    if (activeTab !== 'hot') {
      setLoading(false)
      setError(null)
      return
    }
    if (hotJobsLoaded.current) return
    let cancelled = false
    setLoading(true)
    setError(null)
    const request = fetchHighPayingRoles()
    request.then((roles: Job[]) => {
      if (cancelled) return
      setJobs(roles)
      hotJobsLoaded.current = true
    }).catch(() => {
      if (!cancelled) setError('This section is taking a moment to load.')
    }).finally(() => {
      if (!cancelled) setLoading(false)
    })
    return () => { cancelled = true }
  }, [activeTab])

  function submitSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (query.trim() || allowEmptySubmit) onSearch(query.trim())
  }

  function selectDestination(destination: DestinationId, focusTab = false) {
    setActiveTab(destination)
    if (focusTab) {
      const index = DESTINATIONS.findIndex(item => item.id === destination)
      tabRefs.current[index]?.focus()
    }
  }

  function handleTabKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, index: number) {
    let nextIndex: number | null = null
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') nextIndex = (index + 1) % DESTINATIONS.length
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') nextIndex = (index - 1 + DESTINATIONS.length) % DESTINATIONS.length
    if (event.key === 'Home') nextIndex = 0
    if (event.key === 'End') nextIndex = DESTINATIONS.length - 1
    if (nextIndex === null) return
    event.preventDefault()
    selectDestination(DESTINATIONS[nextIndex].id, true)
  }

  return (
    <main id="main-content" className="mobile-discovery">
      <div className="mobile-discovery__lead">
        <div className="mobile-discovery__intro">
          <h1>Find your next move in Hong Kong finance.</h1>
          <p>Explore open roles, Management Trainee programmes, career coaching and practical learning in one place.</p>
        </div>
        <div className="mobile-discovery__search-panel">
          <span className="mobile-discovery__search-label">Search the Careers board</span>
          <form className={`mobile-discovery__search${activeTab === 'hot' ? '' : ' mobile-discovery__search--secondary'}`} onSubmit={submitSearch} role="search">
              <Search size={20} aria-hidden="true" />
              <input
                type="search"
                value={query}
                onChange={event => setQuery(event.target.value)}
                placeholder="Search roles, skills or employers"
                aria-label="Search roles, skills or employers"
              />
              <button type="submit" aria-label="Search jobs"><ArrowRight size={20} aria-hidden="true" /></button>
          </form>
        </div>
      </div>

      <nav className="mobile-discovery__tabs" role="tablist" aria-label="FinEx discovery destinations">
        {DESTINATIONS.map((destination, index) => {
          const DestinationIcon = destination.icon
          return (
          <button
            key={destination.id}
            ref={element => { tabRefs.current[index] = element }}
            type="button"
            role="tab"
            aria-selected={activeTab === destination.id}
            aria-controls={`mobile-panel-${destination.id}`}
            tabIndex={activeTab === destination.id ? 0 : -1}
            className="mobile-discovery__tab"
            aria-label={destination.label}
            data-active={activeTab === destination.id || undefined}
            onClick={() => selectDestination(destination.id)}
            onKeyDown={event => handleTabKeyDown(event, index)}
          >
            <DestinationIcon className="mobile-discovery__tab-icon" size={21} strokeWidth={1.8} aria-hidden="true" />
            <span className="mobile-discovery__tab-copy">
              <span className="mobile-discovery__tab-label mobile-discovery__tab-label--mobile">{destination.label}</span>
              <span className="mobile-discovery__tab-label mobile-discovery__tab-label--desktop">{destination.desktopLabel}</span>
              <span className="mobile-discovery__tab-summary">{destination.summary}</span>
            </span>
          </button>
          )
        })}
      </nav>

      <div className="mobile-discovery__highlights" key={activeTab} data-focus={activeTab === 'mt' ? 'mt' : activeTab === 'coaching' ? 'coaches' : activeTab === 'education' ? 'videos' : 'roles'}>
        {activeTab === 'mt' ? (
          <MTOpenEmployerLogoBand companies={openMtEmployers.map(employer => employer.company)} />
        ) : (
          <WeeklyHighlights
            demoRoles={activeTab === 'hot' ? jobs : []}
            demoLabel="High-paying role"
            hideWhenEmpty={activeTab === 'hot'}
            surface={activeTab === 'hot' ? 'roles' : activeTab === 'coaching' ? 'coaches' : 'videos'}
          />
        )}
      </div>

      <section id={`mobile-panel-${activeTab}`} className="mobile-discovery__content" data-destination={activeTab} role="tabpanel" aria-label={`${activeDestination.label} content`}>
        {loading && <p className="mobile-discovery__status" role="status">Loading the latest {activeDestination.label.toLowerCase()}…</p>}
        {error && <p className="mobile-discovery__status mobile-discovery__status--error">{error}</p>}

        {activeTab === 'hot' && !loading && !error && (
          <>
            <div className="mobile-discovery__section-heading">
              <div><p className="mobile-discovery__kicker">The salary desk</p><h2>High-paying roles</h2></div>
              <BriefcaseBusiness size={20} aria-hidden="true" />
            </div>
            <p className="mobile-discovery__section-copy">Estimated ranges are shown where an employer has not disclosed a salary.</p>
            <div className="mobile-discovery__job-list">
              {jobs.map(job => <JobCard key={`${job.source}-${job.source_id}`} job={job} compact saved={saved(job)} onToggleSave={onToggleSave} onClick={onSelect} />)}
            </div>
            {jobs.length === 0 && <p className="mobile-discovery__status">No high-paying roles are listed right now. Explore the full Careers board for current openings.</p>}
            <Link className="mobile-discovery__more" to="/jobs" onClick={scrollToTop} aria-label="View more hot jobs on the careers board">More hot jobs <ArrowRight size={16} aria-hidden="true" /></Link>
          </>
        )}

        {activeTab === 'mt' && !loading && !error && (
          <>
            <div className="mobile-discovery__section-heading"><div><p className="mobile-discovery__kicker">Structured entry points</p><h2>Active MT openings</h2></div><GraduationCap size={20} aria-hidden="true" /></div>
            <div className="mobile-discovery__mt-list">
              {openMtEmployers.map(employer => <MTWorkbookProgrammeCard key={employer.company} employer={employer} />)}
            </div>
            {openMtEmployers.length === 0 && <p className="mobile-discovery__status">No open MT programmes are listed right now. Check back soon.</p>}
            <Link className="mobile-discovery__more" to="/management-trainee">See all MT programmes <ArrowRight size={16} aria-hidden="true" /></Link>
          </>
        )}

        {activeTab === 'coaching' && (
          <>
            <div className="mobile-discovery__section-heading"><div><p className="mobile-discovery__kicker">Human perspective</p><h2>Career coaching</h2></div><MessageCircleMore size={20} aria-hidden="true" /></div>
            <label className="mobile-discovery__coach-filters">
              <span>Browse by specialty</span>
              <select aria-label="Filter coaches by specialty" value={coachDomain} onChange={event => setCoachDomain(event.target.value as CoachDomainFilter)}>
                {(['All expertise', ...COACH_DOMAINS] as CoachDomainFilter[]).map(domain => <option key={domain}>{domain}</option>)}
              </select>
            </label>
            <div className="mobile-discovery__coach-groups">
              {mobileCoachGroups.map(group => (
                <section className="mobile-discovery__coach-group" key={group.domain} aria-labelledby={`mobile-coach-${group.domain}`}>
                  <header><h3 id={`mobile-coach-${group.domain}`}>{group.domain}</h3></header>
                  <div className="mobile-discovery__coach-list">
                    {group.coaches.map(coach => <a className="mobile-discovery__coach" href={coach.href} key={coach.id}><img src={coach.image} alt="" loading="lazy" /><span><strong>{coach.name}</strong><small>{coach.role}</small><small>{coach.focus}</small></span><ArrowRight size={16} aria-hidden="true" /></a>)}
                  </div>
                </section>
              ))}
            </div>
            <Link className="mobile-discovery__more" to="/career-coaches">Meet all coaches <ArrowRight size={16} aria-hidden="true" /></Link>
          </>
        )}

        {activeTab === 'education' && (
          <>
            <div className="mobile-discovery__section-heading"><div><p className="mobile-discovery__kicker">Keep learning</p><h2>Education for finance</h2></div><BookOpen size={20} aria-hidden="true" /></div>
            <div className="mobile-discovery__education-list">
              {STRANDS.slice(0, 2).map(strand => <Link className="mobile-discovery__education" to="/learning" key={strand.index}><span className="mobile-discovery__education-index">{strand.index}</span><span><strong>{strand.name}</strong><small>{strand.format}</small><small>{strand.body}</small></span><ArrowRight size={16} aria-hidden="true" /></Link>)}
            </div>
            <Link className="mobile-discovery__more" to="/learning">Explore education <ArrowRight size={16} aria-hidden="true" /></Link>
          </>
        )}
      </section>
    </main>
  )
}
