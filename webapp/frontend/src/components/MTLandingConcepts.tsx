import {
  ArrowRight,
  ArrowUpRight,
  CalendarClock,
  CheckCircle2,
  GraduationCap,
  Landmark,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import {
  MT_INDUSTRIES,
  MT_PROGRAMMES,
  VERIFIED_MT_PROGRAMMES,
  type MTProgramme,
} from '../content/managementTraineePrograms'
import type { MTLandingVariant } from '../content/mtLandingVariants'
import MTAnnouncementBand from './MTAnnouncementBand'
import MTProgrammeShowcase from './MTProgrammeShowcase'

function DirectoryLink({ inverse = false, children = 'Explore all programmes' }: { inverse?: boolean; children?: React.ReactNode }) {
  return (
    <Link className={`mt-concept-link${inverse ? ' mt-concept-link--inverse' : ''}`} to="/management-trainee">
      {children}
      <ArrowRight size={17} aria-hidden="true" />
    </Link>
  )
}

function OfficialProgrammeLink({ programme, inverse = false }: { programme: MTProgramme; inverse?: boolean }) {
  return (
    <a
      className={`mt-official-link${inverse ? ' mt-official-link--inverse' : ''}`}
      href={programme.applicationUrls[0]}
      target="_blank"
      rel="noopener noreferrer"
    >
      <span>
        <small>{programme.company}</small>
        <strong>{programme.programmeName}</strong>
      </span>
      <ArrowUpRight size={18} aria-hidden="true" />
    </a>
  )
}

function MTFirstHero() {
  return (
    <section id="mt-programmes" className="mt-first-hero" aria-labelledby="mt-first-heading">
      <div className="mx-auto max-w-7xl px-6 py-14 lg:px-8 lg:py-20">
        <div className="mt-first-hero__layout">
          <div className="mt-first-hero__copy">
            <p><GraduationCap size={17} /> The graduate deadline desk</p>
            <h1 id="mt-first-heading">Your first move<br />starts here.</h1>
            <p className="mt-first-hero__lead">
              One focused directory for Hong Kong Management Trainee and graduate programmes—
              {MT_PROGRAMMES.length} employers, eight industries, and no invented deadlines.
            </p>
            <DirectoryLink>Open the MT directory</DirectoryLink>
          </div>
          <div className="mt-first-hero__official" aria-label="Recently verified official programme links">
            <div className="mt-first-hero__official-head">
              <span>Recently verified</span>
              <strong>{VERIFIED_MT_PROGRAMMES.length} official links</strong>
            </div>
            {VERIFIED_MT_PROGRAMMES.map(programme => (
              <OfficialProgrammeLink key={programme.id} programme={programme} inverse />
            ))}
            <p><CalendarClock size={15} aria-hidden="true" /> Application deadlines are still to be confirmed.</p>
          </div>
        </div>
      </div>
    </section>
  )
}

function MTClassifiedNotice() {
  return (
    <aside id="mt-programmes" className="mt-classified-wrap" aria-labelledby="mt-classified-heading">
      <div className="mt-classified">
        <div className="mt-classified__mark" aria-hidden="true">MT</div>
        <div className="mt-classified__copy">
          <p>New on FinEx Careers</p>
          <h2 id="mt-classified-heading">Looking for a Management Trainee programme?</h2>
          <span>{MT_PROGRAMMES.length} Hong Kong employers · {MT_INDUSTRIES.length} industries · HKJC and HKMA official links added</span>
        </div>
        <DirectoryLink>Browse the MT desk</DirectoryLink>
      </div>
    </aside>
  )
}

function MTDeadlineDesk() {
  return (
    <section id="mt-programmes" className="mt-deadline-desk" aria-labelledby="mt-deadline-heading">
      <div className="mx-auto max-w-7xl px-6 py-14 lg:px-8 lg:py-18">
        <div className="mt-deadline-desk__head">
          <div>
            <p><CalendarClock size={17} /> Management Trainee desk</p>
            <h2 id="mt-deadline-heading">The windows worth<br />watching.</h2>
          </div>
          <div className="mt-deadline-desk__intro">
            <p>Track structured early-career routes across Hong Kong. We publish a date only when the source does.</p>
            <DirectoryLink inverse>See all {MT_PROGRAMMES.length} programmes</DirectoryLink>
          </div>
        </div>
        <div className="mt-deadline-desk__list">
          {VERIFIED_MT_PROGRAMMES.map((programme, index) => (
            <a key={programme.id} href={programme.applicationUrls[0]} target="_blank" rel="noopener noreferrer">
              <span className="mt-deadline-desk__number">0{index + 1}</span>
              <span className="mt-deadline-desk__company">
                <small>{programme.company}</small>
                <strong>{programme.programmeName}</strong>
              </span>
              <span className="mt-deadline-desk__status"><CheckCircle2 size={15} /> Official link</span>
              <span className="mt-deadline-desk__date">Deadline to be confirmed</span>
              <ArrowUpRight className="mt-deadline-desk__arrow" size={19} aria-hidden="true" />
            </a>
          ))}
        </div>
      </div>
    </section>
  )
}

function MTGraduateGateway() {
  return (
    <section id="mt-programmes" className="mt-gateway" aria-labelledby="mt-gateway-heading">
      <div className="mx-auto max-w-7xl px-6 py-12 lg:px-8 lg:py-16">
        <div className="mt-gateway__layout">
          <div className="mt-gateway__monogram" aria-hidden="true"><span>M</span><span>T</span></div>
          <div className="mt-gateway__copy">
            <p>Graduate gateway · Hong Kong</p>
            <h1 id="mt-gateway-heading">The market&rsquo;s trainee programmes, gathered.</h1>
            <p>Move from scattered bookmarks to one clear starting point. Browse {MT_PROGRAMMES.length} employers by industry, then go directly to verified official programme pages.</p>
            <div className="mt-gateway__actions">
              <DirectoryLink>Enter the directory</DirectoryLink>
              <span>{MT_INDUSTRIES.length} industry groups</span>
            </div>
          </div>
          <div className="mt-gateway__verified">
            <p>Official links now available</p>
            {VERIFIED_MT_PROGRAMMES.map(programme => (
              <OfficialProgrammeLink key={programme.id} programme={programme} />
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

function MTIndexMasthead() {
  return (
    <section id="mt-programmes" className="mt-index-masthead" aria-labelledby="mt-index-heading">
      <div className="mx-auto max-w-7xl px-6 py-10 lg:px-8 lg:py-12">
        <div className="mt-index-masthead__title">
          <p><Landmark size={16} /> FinEx graduate index</p>
          <h1 id="mt-index-heading">Management Trainee programmes across Hong Kong.</h1>
          <DirectoryLink>Search all {MT_PROGRAMMES.length}</DirectoryLink>
        </div>
        <div className="mt-index-masthead__rail" aria-label="Programme coverage by industry">
          {MT_INDUSTRIES.map((industry, index) => {
            const count = MT_PROGRAMMES.filter(programme => programme.industry === industry).length
            return (
              <div key={industry}>
                <span>{String(index + 1).padStart(2, '0')}</span>
                <strong>{industry}</strong>
                <b>{count}</b>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}

export function MTLandingAboveHero({ variant }: { variant: MTLandingVariant }) {
  if (variant === 1) return <MTAnnouncementBand />
  if (variant === 2) return <MTFirstHero />
  if (variant === 5) return <MTGraduateGateway />
  if (variant === 6) return <MTIndexMasthead />
  return null
}

export function MTLandingBelowHero({ variant }: { variant: MTLandingVariant }) {
  if (variant === 1) return <MTProgrammeShowcase />
  if (variant === 3) return <MTClassifiedNotice />
  if (variant === 4) return <MTDeadlineDesk />
  return null
}
