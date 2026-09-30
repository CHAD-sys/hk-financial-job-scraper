import { useState } from 'react'
import { ArrowRight, CalendarClock, MessageCircleMore } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { MTWorkbookEmployer, MTWorkbookProgramme } from '../content/mtWorkbookProgrammes'
import { mtEmployerSlug } from '../content/mtWorkbookProgrammes'
import { mtCompanyLogo } from '../content/mtCompanyLogos'

const CONSULTATION_URL = 'https://www.finexclub.org/mentor-program'

/** A fixed-size logo well prevents image loading from moving the card’s type.
 * The company heading remains the accessible name; this mark is a visual
 * recognition cue and degrades to a compact wordmark when no local asset
 * exists yet. */
function WorkbookCompanyLogo({ company }: { company: string }) {
  const [failed, setFailed] = useState(false)
  const logo = mtCompanyLogo(company)

  return (
    <div className="mt-workbook-card__logo" data-testid="mt-workbook-card-logo" aria-hidden="true">
      {logo.src && !failed
        ? <img src={logo.src} alt="" width={180} height={90} loading="lazy" decoding="async" onError={() => setFailed(true)} />
        : <span>{logo.wordmark}</span>}
    </div>
  )
}

export function formatMTDeadline(deadline: string | null) {
  if (!deadline) return null
  if (deadline === 'Ongoing') return 'Applications ongoing'
  const match = deadline.match(/^(\d{2})-([A-Za-z]{3})-(\d{4})$/)
  if (!match) return deadline
  const [, day, month, year] = match
  const monthNumber = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].indexOf(month)
  if (monthNumber < 0) return deadline
  const parsed = new Date(Date.UTC(Number(year), monthNumber, Number(day)))
  if (Number.isNaN(parsed.getTime())) return deadline
  return `Closes ${new Intl.DateTimeFormat('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Hong_Kong',
  }).format(parsed)}`
}

export function mtApplicationStatus(programme: MTWorkbookProgramme) {
  if (programme.status === 'Active') return formatMTDeadline(programme.deadline) ?? 'Open now'
  if (programme.status === 'Closed') return 'Closed'
  return 'Not currently open'
}

export function sortMTApplicationLinks(programmes: readonly MTWorkbookProgramme[]) {
  const statusOrder = { Active: 0, Closed: 1, 'N/A': 2 } as const
  return [...programmes].sort((a, b) => (
    statusOrder[a.status] - statusOrder[b.status]
    || a.employerLinkNumber - b.employerLinkNumber
  ))
}

export default function MTWorkbookProgrammeCard({
  employer,
  anchorId,
}: {
  employer: MTWorkbookEmployer
  anchorId?: string
}) {
  const programmes = sortMTApplicationLinks(employer.programmes)
  const openLinks = programmes.filter(programme => programme.status === 'Active')
  const closedLinks = programmes.filter(programme => programme.status === 'Closed')
  const open = openLinks.length > 0
  const statusLabel = open ? 'Open now' : closedLinks.length > 0 ? 'Closed' : 'Not currently open'
  const detail = open
    ? `${openLinks.length} active ${openLinks.length === 1 ? 'application' : 'applications'}`
    : closedLinks.length > 0 ? 'No active application recorded' : 'No current intake recorded'
  const linkCountLabel = `${programmes.length} application ${programmes.length === 1 ? 'link' : 'links'}`

  return (
    <article id={anchorId} className="mt-programme-card mt-workbook-card">
      <div className={`mt-programme-card__deadline ${open ? 'mt-programme-card__deadline--open' : 'mt-programme-card__deadline--inactive'}`}>
        <CalendarClock size={18} aria-hidden="true" />
        <span><strong>{statusLabel}</strong>{detail ? ` · ${detail}` : ''}</span>
      </div>
      <div className="mt-programme-card__body">
        <div className="mt-workbook-card__identity">
          <WorkbookCompanyLogo company={employer.company} />
          <div>
            <p className="mt-workbook-card__eyebrow">{linkCountLabel}</p>
            <h3>{employer.company}</h3>
          </div>
        </div>
      </div>
      <div className="mt-programme-card__actions">
        <Link to={`/management-trainee/${mtEmployerSlug(employer.company)}`} aria-label={`View all application links at ${employer.company}`}>
          View programmes <ArrowRight size={15} aria-hidden="true" />
        </Link>
        <a className="mt-programme-card__coaching" href={CONSULTATION_URL} target="_blank" rel="noopener noreferrer">
          <MessageCircleMore size={16} aria-hidden="true" />
          Interview prep
        </a>
      </div>
    </article>
  )
}
