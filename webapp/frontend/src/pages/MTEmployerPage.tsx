import { ArrowLeft, ArrowUpRight, CalendarClock, MessageCircleMore } from 'lucide-react'
import { Link, Navigate, useParams } from 'react-router-dom'
import { useContext } from 'react'
import Nav from '../components/Nav'
import { mtCompanyLogo } from '../content/mtCompanyLogos'
import { findMTWorkbookEmployerBySlug, mtApplicationRoleLabel } from '../content/mtWorkbookProgrammes'
import {
  sortMTApplicationLinks,
  mtApplicationStatus,
} from '../components/MTWorkbookProgrammeCard'
import { DeviceModeContext } from '../deviceMode/DeviceModeContext'

const CONSULTATION_URL = 'https://www.finexclub.org/mentor-program'

function EmployerMark({ company }: { company: string }) {
  const logo = mtCompanyLogo(company)
  return logo.src
    ? <img src={logo.src} alt={`${company} logo`} width={240} height={120} decoding="async" />
    : <span aria-hidden="true">{logo.wordmark}</span>
}

export default function MTEmployerPage() {
  const uiMode = useContext(DeviceModeContext)?.uiMode ?? 'desktop'
  const { employerSlug = '' } = useParams()
  const employer = findMTWorkbookEmployerBySlug(employerSlug)

  if (!employer) return <Navigate to="/management-trainee" replace />

  const applications = sortMTApplicationLinks(employer.programmes)
  const activeCount = applications.filter(application => application.status === 'Active').length
  const headline = activeCount
    ? `${activeCount} ${activeCount === 1 ? 'application is' : 'applications are'} currently open.`
    : applications.some(application => application.status === 'Closed')
      ? 'No current application is recorded.'
      : 'No verified current intake is recorded.'

  return (
    <div className="mt-employer-page" data-layout={uiMode}>
      <title>{`${employer.company} MT programmes | FinEx Careers`}</title>
      <meta name="description" content={`Management trainee application links for ${employer.company}.`} />
      <Nav />
      <main id="main-content">
        <header className="mt-employer-page__hero">
          <div className="mx-auto max-w-7xl px-6 py-9 lg:px-8 lg:py-14 mt-employer-page__hero-inner">
            <Link className="mt-employer-page__back" to="/management-trainee">
              <ArrowLeft size={16} aria-hidden="true" /> All MT employers
            </Link>
            <div className="mt-employer-page__identity" data-testid="mt-employer-identity" data-layout={uiMode}>
              <div className="mt-employer-page__logo"><EmployerMark company={employer.company} /></div>
              <div>
                <p className="mt-employer-page__kicker">Management trainee opportunities</p>
                <h1>{employer.company}</h1>
                <p>{headline}</p>
              </div>
            </div>
          </div>
        </header>

        <section className="mx-auto max-w-7xl px-6 py-10 lg:px-8 lg:py-14 mt-employer-page__content" aria-labelledby="mt-employer-applications">
          <div className="mt-employer-page__section-head">
            <div>
              <p>Application desk</p>
              <h2 id="mt-employer-applications">Choose an application route.</h2>
            </div>
            <span>{applications.length} supplied {applications.length === 1 ? 'link' : 'links'}</span>
          </div>
          <div className="mt-employer-page__applications">
            {applications.map(application => {
              const roleLabel = mtApplicationRoleLabel(application)
              return <a
                key={application.id}
                className="mt-employer-page__application"
                data-status={application.status.toLocaleLowerCase()}
                href={application.applicationUrl}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`Open ${roleLabel} at ${employer.company}: ${mtApplicationStatus(application)}`}
              >
                <span className="mt-employer-page__application-index">{String(application.employerLinkNumber).padStart(2, '0')}</span>
                <span className="mt-employer-page__application-copy">
                  <strong>{roleLabel}</strong>
                  <small><CalendarClock size={15} aria-hidden="true" /> {mtApplicationStatus(application)}</small>
                </span>
                <ArrowUpRight size={19} aria-hidden="true" />
              </a>
            })}
          </div>
          <aside className="mt-employer-page__prep">
            <MessageCircleMore size={20} aria-hidden="true" />
            <div><strong>Want to sharpen your application?</strong><span>Prepare for interviews with a FinEx career coach.</span></div>
            <a href={CONSULTATION_URL} target="_blank" rel="noopener noreferrer">Interview prep <ArrowUpRight size={16} aria-hidden="true" /></a>
          </aside>
        </section>
      </main>
    </div>
  )
}
