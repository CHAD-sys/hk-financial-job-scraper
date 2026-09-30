import { useRef, useState } from 'react'
import { ArrowDown } from 'lucide-react'
import { Link } from 'react-router-dom'
import { mtEmployerSlug } from '../content/mtWorkbookProgrammes'
import { mtCompanyLogo } from '../content/mtCompanyLogos'
import { nextMarqueeTime, useSwipeableMarquee } from './highlights/useSwipeableMarquee'

export interface MTOpenEmployer {
  company: string
  targetId: string
  roleCount: number
}

function EmployerLogo({ company }: { company: string }) {
  const [failed, setFailed] = useState(false)
  const logo = mtCompanyLogo(company)

  if (!logo.src || failed) {
    return <span className="mt-open-employers__wordmark" aria-hidden="true">{logo.wordmark}</span>
  }

  return <img src={logo.src} alt="" width={240} height={120} loading="lazy" decoding="async" onError={() => setFailed(true)} />
}

/**
 * The shared, logo-first MT conveyor. It deliberately contains no programme
 * details: readers use it to recognise leading employers at a glance before
 * choosing a specific programme from the cards below.
 */
export function MTOpenEmployerLogoBand({ companies }: { companies: readonly string[] }) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const trackRef = useRef<HTMLDivElement>(null)
  useSwipeableMarquee(viewportRef, trackRef)

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    const track = trackRef.current
    const animation = track?.getAnimations?.()[0]
    const duration = animation?.effect?.getTiming().duration
    if (!track || !animation || typeof duration !== 'number') return

    animation.pause()
    animation.currentTime = nextMarqueeTime({
      currentTime: typeof animation.currentTime === 'number' ? animation.currentTime : 0,
      deltaX: event.key === 'ArrowRight' ? -220 : 220,
      duration,
      trackDistance: track.scrollWidth / 2,
      reversed: false,
    })
    window.setTimeout(() => animation.play(), 1_800)
  }

  return (
    <div className="mt-logo-band" aria-label="Management Trainee employers">
      <div
        ref={viewportRef}
        className="mt-logo-band__viewport"
        role="group"
        tabIndex={0}
        aria-label="Swipe through Management Trainee employer logos"
        onKeyDown={handleKeyDown}
      >
        <div ref={trackRef} className="mt-logo-band__track">
          {[...companies, ...companies].map((company, index) => {
            const isLoopClone = index >= companies.length
            return (
              <Link
                className="mt-logo-band__item"
                key={`${company}-${index}`}
                to={`/management-trainee/${mtEmployerSlug(company)}`}
                aria-label={isLoopClone ? undefined : `View ${company} Management Trainee programmes`}
                aria-hidden={isLoopClone || undefined}
                tabIndex={isLoopClone ? -1 : undefined}
              >
                <EmployerLogo company={company} />
                <span>{company}</span>
              </Link>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export default function MTOpenEmployerBanner({
  employers,
  logoCompanies,
  onSelect,
}: {
  employers: readonly MTOpenEmployer[]
  logoCompanies?: readonly string[]
  onSelect?: (targetId: string) => void
}) {
  if (!employers.length) return null

  const companies = [...new Set((logoCompanies?.length ? logoCompanies : employers.map(employer => employer.company)).map(company => company.trim()).filter(Boolean))]

  return (
    <section className="mt-open-employers" aria-labelledby="mt-open-employers-heading">
      <div className="mx-auto max-w-7xl px-6 py-7 lg:px-8">
        <MTOpenEmployerLogoBand companies={companies} />
        <div className="mt-open-employers__heading">
          <div>
            <p>Open now</p>
            <h2 id="mt-open-employers-heading">Start with a leading employer.</h2>
          </div>
          <span className="mt-open-employers__hint">Swipe to browse</span>
        </div>
        <nav className="mt-open-employers__rail" aria-label="Open Management Trainee employers">
          {employers.map(employer => (
            <a
              key={employer.targetId}
              href={`#${employer.targetId}`}
              aria-label={`Jump to open application links at ${employer.company}`}
              onClick={() => onSelect?.(employer.targetId)}
            >
              <EmployerLogo company={employer.company} />
              <span className="mt-open-employers__name">{employer.company}</span>
              {employer.roleCount > 1 && <small>{employer.roleCount} open roles</small>}
              <ArrowDown size={13} aria-hidden="true" />
            </a>
          ))}
        </nav>
      </div>
    </section>
  )
}
