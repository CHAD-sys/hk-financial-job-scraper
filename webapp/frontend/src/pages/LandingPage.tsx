import { useState, useEffect } from 'react'
import { Briefcase } from 'lucide-react'
import { Link } from 'react-router-dom'
import Nav from '../components/Nav'
import ProductDoor from '../components/ProductDoor'
import ResumeFeatureSpotlight from '../components/ResumeFeatureSpotlight'
import useHashScroll from '../hooks/useHashScroll'
import { fetchStats } from '../api/client'
import { SUBSCRIBER_LINE } from '../content/featuredVideos'

const CONSULTATION_URL = 'https://www.finexclub.org/mentor-program'

/** One of the three named offerings inside the hero's positioning statement. */
function Pillar({ children }: { children: React.ReactNode }) {
  return <span style={{ color: 'var(--color-ink)', fontWeight: 500 }}>{children}</span>
}

/**
 * The portal.
 *
 * `/` is no longer a job-board landing page. FinEx offers three things —
 * opportunities, guidance, and learning — and this page is three doors onto
 * them. The board is still the traffic engine and still leads, but it is one
 * door of three rather than the whole site.
 *
 * Consultation's door points off-site to the Club's mentor programme
 * (CONSULTATION_URL). Careers and Learning are real pages (/jobs, /learning),
 * so theirs navigate.
 */
export default function LandingPage() {
  useHashScroll()

  return (
    <div style={{ backgroundColor: 'var(--color-bg)', minHeight: '100dvh' }}>
      {/* index.html carries no static title/description (see its own comment) —
          every route, including this one, sets its own via hoisting. */}
      <title>FinEx Careers — HK Finance Roles, Consultation &amp; Learning</title>
      <meta
        name="description"
        content="Hong Kong finance careers in one place: a daily, AI-enriched index of open roles across 230+ employers, plus consultation and professional learning."
      />
      <script type="application/ld+json">{JSON.stringify(ORG_JSONLD)}</script>
      <Nav />
      <main id="main-content">
        <PortalHero />
        <ResumeFeatureSpotlight />
        <PostRoleStripe />
      </main>
      <LandingFooter />
    </div>
  )
}

// Kept deliberately in step with `_organisation_jsonld` in webapp/backend/main.py:
// the server injects its copy for crawlers that never run JS, and main.tsx removes
// that copy once React boots — so THIS is the block Google reads when it renders.
// sameAs is the part that matters: it ties this domain to the Financial Executive
// Club's established presence, which is what tells a classifier we are a real
// organisation rather than a young domain wrapping an OAuth login.
const ORG_JSONLD = {
  '@context': 'https://schema.org',
  '@type': 'Organization',
  name: 'FinEx Careers',
  legalName: 'Financial Executive Club',
  url: 'https://www.finexcareers.com',
  logo: 'https://www.finexcareers.com/og-image.png',
  description:
    'A daily, AI-enriched index of open finance roles across Hong Kong employers.',
  areaServed: { '@type': 'Place', name: 'Hong Kong' },
  sameAs: [
    'https://www.finexclub.org',
    'https://www.linkedin.com/company/financial-executive-club',
  ],
}

// ── Hero + the three doors ────────────────────────────────────────────────────

function PortalHero() {
  // Live figures, so the board door never advertises a number we can't back.
  // Both fall back to nothing rather than to a guess — an empty slot is honest,
  // a stale hardcoded figure is not.
  const [roles, setRoles] = useState<number | null>(null)
  const [employers, setEmployers] = useState<number | null>(null)

  useEffect(() => {
    fetchStats().then(s => {
      setRoles(s.total_active_jobs)
      setEmployers(s.employer_count)
    }).catch(() => {})
  }, [])

  const boardFigure =
    roles === null
      ? null
      : `${roles.toLocaleString()} live roles${employers ? ` · ${employers} employers` : ''}`

  return (
    <section aria-labelledby="portal-heading" className="relative overflow-hidden">
      {/* Grid texture + gold top rule, carried over from the previous hero —
          the identity stays even though the structure is entirely new. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            'linear-gradient(var(--color-border) 1px, transparent 1px), linear-gradient(90deg, var(--color-border) 1px, transparent 1px)',
          backgroundSize: '48px 48px',
          opacity: 0.45,
        }}
      />
      <div aria-hidden="true" className="absolute inset-x-0 top-0 h-0.5" style={{ backgroundColor: 'var(--color-gold)' }} />

      <div className="relative mx-auto max-w-7xl px-6 lg:px-8 pt-14 pb-16 sm:pt-20 lg:pt-24">
        <span
          className="inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold uppercase"
          style={{
            backgroundColor: 'var(--color-gold-light)',
            color: 'var(--color-gold)',
            border: '1px solid var(--color-gold)',
            letterSpacing: '0.14em',
          }}
        >
          Hong Kong · Financial Executive Club
        </span>

        {/* The positioning statement is carried across the heading and the lead below
            it rather than crammed into one <h1>. Set as a single 150-character
            headline it had to drop to ~28px to fit a phone, which put the display
            serif at body-text scale and cost the hero the thing that makes it read
            as premium — large type. Split, the claim keeps the full display scale
            and the enumeration becomes the lead, which is where a list belongs.
            The three named pillars are also, in order, the three doors below, so
            the sentence now resolves into the page instead of just sitting on it. */}
        <h1
          id="portal-heading"
          className="mt-8 max-w-4xl leading-[1.06] tracking-tight text-balance"
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 'clamp(2.5rem, 5.2vw, 4rem)',
            fontWeight: 700,
            color: 'var(--color-ink)',
            letterSpacing: '-0.025em',
          }}
        >
          <em className="not-italic" style={{ color: 'var(--color-gold)' }}>
            Asia&rsquo;s{' '}
            <span style={{ fontSize: '1.4em', fontWeight: 800 }}>
              1<span style={{ fontSize: '0.55em', verticalAlign: '0.75em' }}>st</span>
            </span>
          </em>{' '}
          Premier Career Centre
        </h1>

        {/* Pillar names sit at ink weight against muted connective text, so the
            three-part structure is visible at a glance without a bullet list —
            purely a visual weight change, so <span> not <strong> (nothing here is
            more important to a screen reader than the rest of the sentence). */}
        <p
          className="mt-6 max-w-3xl leading-relaxed"
          style={{ fontSize: 'clamp(1.0625rem, 1.5vw, 1.25rem)', color: 'var(--color-ink-muted)' }}
        >
          Seamlessly integrating{' '}
          <Pillar>AI Job Acquisition</Pillar>,{' '}
          <Pillar>Career Consultation</Pillar>,{' '}
          <Pillar>Learning and Professional Development</Pillar>{' '}
          &mdash; under one roof.
        </p>

        {/* What the portal is worth to each of the two audiences, stated once
            each. A list rather than more prose: the two claims are addressed to
            different readers, and running them together as a paragraph makes
            each one read as qualifying the other. */}
        <ul className="mt-6 flex max-w-3xl flex-col gap-3">
          {[
            <>
              <Pillar>For job seekers</Pillar>, we improve your job hunting success rate by 30%.
            </>,
            <>
              <Pillar>For recruiters</Pillar>, we direct your jobs to an exclusive network of
              senior executives and finance professionals directly from the FinEx Club community,
              and significantly save your acquisition cost.
            </>,
          ].map((line, i) => (
            <li key={i} className="flex gap-3 leading-relaxed" style={{ fontSize: '1rem', color: 'var(--color-ink-muted)' }}>
              <span
                aria-hidden="true"
                className="mt-2.5 h-1.5 w-1.5 shrink-0 rounded-full"
                style={{ backgroundColor: 'var(--color-gold)' }}
              />
              <span>{line}</span>
            </li>
          ))}
        </ul>

        {/* The doors are the call to action — there is no separate CTA button. */}
        <div className="mt-14 grid gap-5 lg:grid-cols-3">
          <ProductDoor
            index="01"
            eyebrow="Careers"
            title="Every finance role in Hong Kong"
            description="Openings from across the market — banks, insurers, asset managers and boutiques — collected daily, de-duplicated, and enriched with skills, seniority and salary signals."
            figure={boardFigure}
            href="/jobs"
          />
          <ProductDoor
            index="02"
            eyebrow="Consultation"
            title="Executive career consultation"
            note={
              <>
                FinEx Club is Career Coaching Partner of Top-tier universities, such as{' '}
                <strong style={{ fontWeight: 700 }}>HKU Business School</strong>.
              </>
            }
            description="Confidential one-to-one guidance for senior finance professionals weighing a move, a change of function, or the step up to the next seat."
            figure="By enquiry"
            href={CONSULTATION_URL}
          />
          <ProductDoor
            index="03"
            eyebrow="Professional L&D"
            title="Learning from the people running the market"
            description="Seminars, technical workshops and the Club's interview series with the executives actually running Hong Kong's financial institutions."
            figure={SUBSCRIBER_LINE}
            href="/learning"
          />
        </div>
      </div>
    </section>
  )
}

// ── Employer stripe ───────────────────────────────────────────────────────────

/**
 * The only thing on this page addressed to employers rather than candidates, so
 * it is a thin band rather than a fourth door — the portal is three doors and
 * adding a fourth for a different audience would blunt all of them.
 */
function PostRoleStripe() {
  return (
    <section
      aria-labelledby="post-role-heading"
      style={{ backgroundColor: 'var(--color-nav)', borderTop: '1px solid var(--color-border)' }}
    >
      <div className="mx-auto flex max-w-7xl flex-col gap-5 px-6 py-10 sm:flex-row sm:items-center sm:justify-between lg:px-8">
        <div>
          <h2
            id="post-role-heading"
            className="text-xl tracking-tight"
            style={{ fontFamily: 'var(--font-display)', fontWeight: 700, color: 'var(--color-ink-inverse)' }}
          >
            Hiring in Hong Kong finance?
          </h2>
          <p className="mt-1.5 text-sm" style={{ color: 'rgba(248,250,252,0.7)' }}>
            Recruiters and employers can put a mandate in front of this audience directly.
            Every submission is reviewed before it appears.
          </p>
        </div>
        <Link
          to="/post-a-role"
          className="inline-flex shrink-0 items-center justify-center gap-2 rounded px-6 py-3 text-sm font-semibold no-underline"
          style={{ backgroundColor: 'var(--color-gold)', color: '#fff' }}
        >
          <Briefcase size={15} strokeWidth={2} />
          Post a role
        </Link>
      </div>
    </section>
  )
}

// ── Footer ────────────────────────────────────────────────────────────────────

function LandingFooter() {
  return (
    <footer style={{ borderTop: '1px solid var(--color-border)' }}>
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-6 py-10 sm:flex-row sm:items-center sm:justify-between lg:px-8">
        <div className="flex items-center gap-2">
          <span
            className="text-sm font-semibold tracking-tight"
            style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)' }}
          >
            FinEx <em className="not-italic" style={{ color: 'var(--color-gold)' }}>Careers</em>
          </span>
          <span className="text-xs" style={{ color: 'var(--color-ink-faint)' }}>
            — a Financial Executive Club platform
          </span>
        </div>

        {/* Real destinations only. The previous footer linked five dead "#"s. */}
        <nav className="flex flex-wrap gap-x-6 gap-y-2" aria-label="Footer navigation">
          <FooterLink to="/jobs">Browse roles</FooterLink>
          <FooterLink to={CONSULTATION_URL}>Consultation</FooterLink>
          <FooterLink to="/learning">Learning</FooterLink>
          <FooterLink to="/post-a-role">Post a role</FooterLink>
          <FooterLink to="/about">About</FooterLink>
          <FooterLink to="/about#resume-policy">Resume policy</FooterLink>
          <FooterLink to="/about#privacy">Privacy</FooterLink>
        </nav>

        <p className="text-xs" style={{ color: 'var(--color-ink-faint)' }}>
          © 2026 FinEx Careers. For informational use only.
        </p>
      </div>
    </footer>
  )
}

function FooterLink({ to, children }: { to: string; children: React.ReactNode }) {
  // An external URL stays a plain <a> — react-router's <Link> resolves `to`
  // against the current route, so a full https:// URL passed to it would be
  // treated as an internal path rather than actually leaving the site.
  if (to.startsWith('http')) {
    return (
      <a
        href={to}
        target="_blank"
        rel="noopener noreferrer"
        className="text-xs font-medium no-underline"
        style={{ color: 'var(--color-ink-faint)' }}
      >
        {children}
      </a>
    )
  }

  return (
    <Link
      to={to}
      className="text-xs font-medium no-underline"
      style={{ color: 'var(--color-ink-faint)' }}
    >
      {children}
    </Link>
  )
}
