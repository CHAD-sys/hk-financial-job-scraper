import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { ArrowLeft, ArrowUpRight, Bookmark, BriefcaseBusiness, CalendarDays, Check, DollarSign, MapPin, Tag } from 'lucide-react'
import { Link, useLocation, useParams } from 'react-router-dom'
import type { Job, JobDetail } from '../api/client'
import { fetchJobDetail } from '../api/client'
import Nav from '../components/Nav'
import { useSavedRoles } from '../savedRoles/useSavedRoles'
import { useDeviceMode } from '../deviceMode/useDeviceMode'
import {
  displayCompany,
  formatEstimatedSalary,
  formatRemoteType,
  formatSalary,
  getSectorColor,
  shortLocation,
  timeAgo,
} from '../utils/format'

interface RoleRouteState {
  job?: Job
  returnTo?: string
}

function routeState(value: unknown): RoleRouteState {
  if (!value || typeof value !== 'object') return {}
  const state = value as RoleRouteState
  return state.job && typeof state.job.source === 'string' ? state : {}
}

export default function RoleDetailPage() {
  const { source = '', sourceId = '' } = useParams()
  const location = useLocation()
  const { uiMode } = useDeviceMode()
  const { isSaved, toggle } = useSavedRoles()
  const state = useMemo(() => routeState(location.state), [location.state])
  const seed = state.job?.source === source && state.job.source_id === sourceId ? state.job : null
  const [detail, setDetail] = useState<JobDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    if (!source || !sourceId) {
      setLoading(false)
      setError(true)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(false)
    fetchJobDetail(source, sourceId, seed?.access_token)
      .then(result => {
        if (!cancelled) setDetail(result)
      })
      .catch(() => {
        if (!cancelled) setError(true)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [seed?.access_token, source, sourceId])

  const role = detail ?? seed
  const returnTo = state.returnTo?.startsWith('/') ? state.returnTo : '/jobs'

  if (!role && loading) {
    return (
      <div className="role-detail-page" data-layout={uiMode}>
        <Nav />
        <main className="role-detail-page__loading" id="main-content" aria-live="polite" aria-busy="true">
          <span aria-hidden="true" />
          <p>Opening Role…</p>
        </main>
      </div>
    )
  }

  if (!role) {
    return (
      <div className="role-detail-page" data-layout={uiMode}>
        <Nav />
        <main className="role-detail-page__unavailable" id="main-content">
          <p className="role-detail-page__eyebrow">Role unavailable</p>
          <h1>This Role cannot be opened right now.</h1>
          <p>Return to Careers and choose another live opportunity.</p>
          <Link to="/jobs">Back to Careers <ArrowUpRight size={16} aria-hidden="true" /></Link>
        </main>
      </div>
    )
  }

  const title = role.title_en || role.title
  const company = displayCompany(role.company, role.source_tier)
  const sector = getSectorColor(role.sector)
  const salary = formatSalary(role.salary_hkd_min, role.salary_hkd_max, role.salary_period)
  const estimatedSalary = salary ? null : formatEstimatedSalary(role.salary_estimated_min, role.salary_estimated_max)
  const description = detail?.description_summary || role.description_excerpt
  const destinationLabel = role.source_tier === 'social' ? 'View the original post' : 'Apply on company site'

  return (
    <div className="role-detail-page" data-layout={uiMode}>
      <title>{`${title} at ${company} | FinEx Careers`}</title>
      <meta name="description" content={`${title} at ${company} in Hong Kong.`} />
      <Nav />
      <header className="role-detail-page__hero">
        <div className="role-detail-page__inner">
          <Link className="role-detail-page__back" to={returnTo}>
            <ArrowLeft size={17} aria-hidden="true" /> Back to careers
          </Link>
          <div className="role-detail-page__title-block">
            <span className="role-detail-page__sector" style={{ color: sector.text, backgroundColor: sector.bg, borderColor: sector.border }}>{role.sector}</span>
            <p>{company}</p>
            <h1>{title}</h1>
          </div>
          <dl className="role-detail-page__facts" aria-label="Role facts">
            <Fact icon={<MapPin size={16} aria-hidden="true" />} label="Location" value={shortLocation(role.locations)} />
            <Fact icon={<BriefcaseBusiness size={16} aria-hidden="true" />} label="Work type" value={formatRemoteType(role.remote_type) || 'To be confirmed'} />
            <Fact icon={<Tag size={16} aria-hidden="true" />} label="Category" value={role.job_category || 'Finance'} />
            <Fact icon={<CalendarDays size={16} aria-hidden="true" />} label="Posted" value={timeAgo(role.posted_at)} />
          </dl>
        </div>
      </header>

      <main className="role-detail-page__main role-detail-page__inner" id="main-content">
        {error && <p className="role-detail-page__notice" role="status">Some additional Role details are unavailable. The essentials are still shown below.</p>}
        {(salary || estimatedSalary) && (
          <section className="role-detail-page__salary" aria-labelledby="role-pay">
            <DollarSign size={20} aria-hidden="true" />
            <div><p id="role-pay">{salary ? 'Compensation' : 'Estimated base salary'}</p><strong>{salary ?? estimatedSalary}</strong></div>
          </section>
        )}
        {description && (
          <section className="role-detail-page__section" aria-labelledby="role-description">
            <p className="role-detail-page__eyebrow">Role overview</p>
            <h2 id="role-description">What this Role involves</h2>
            <p>{description}</p>
          </section>
        )}
        {role.required_skills.length > 0 && role.source_tier !== 'social' && (
          <section className="role-detail-page__section" aria-labelledby="role-skills">
            <p className="role-detail-page__eyebrow">Requirements</p>
            <h2 id="role-skills">Skills and experience</h2>
            <ul className="role-detail-page__skills">{role.required_skills.map(skill => <li key={skill}><Check size={14} aria-hidden="true" /> {skill}</li>)}</ul>
          </section>
        )}
      </main>

      <div className="role-detail-page__action-bar">
        <div className="role-detail-page__inner">
          {role.closed ? (
            <p className="role-detail-page__closed">This Role is awaiting a status update.</p>
          ) : (
            <div className="role-detail-page__actions">
              <a href={role.url} target="_blank" rel="noopener noreferrer" className="role-detail-page__apply">
                {destinationLabel} <ArrowUpRight size={18} aria-hidden="true" />
              </a>
              <button type="button" onClick={() => toggle(role)} aria-pressed={isSaved(role)}>
                <Bookmark size={18} fill={isSaved(role) ? 'currentColor' : 'none'} aria-hidden="true" />
                {isSaved(role) ? 'Saved' : 'Save'}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Fact({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return <div><dt>{icon}<span>{label}</span></dt><dd>{value}</dd></div>
}
