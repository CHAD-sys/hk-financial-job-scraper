import { useState, useEffect } from 'react'
import { ArrowUpRight, Briefcase } from 'lucide-react'
import { Link } from 'react-router-dom'
import Nav from '../components/Nav'
import ProductDoor from '../components/ProductDoor'
import EnquiryForm from '../components/EnquiryForm'
import useHashScroll from '../hooks/useHashScroll'
import { fetchStats, fetchFilters } from '../api/client'
import { SUBSCRIBER_LINE } from '../content/featuredVideos'

const CONSULTING_URL = 'https://www.finexclub.org/consulting'

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
 * Consultation is a section on this same page, so its door scrolls. Careers and
 * Learning are real pages (/jobs, /learning), so theirs navigate.
 */
export default function LandingPage() {
  useHashScroll()

  return (
    <div style={{ backgroundColor: 'var(--color-bg)', minHeight: '100dvh' }}>
      <Nav />
      <main id="main-content">
        <PortalHero />
        <ConsultationSection />
        <PostRoleStripe />
      </main>
      <LandingFooter />
    </div>
  )
}

// ── Hero + the three doors ────────────────────────────────────────────────────

function PortalHero() {
  // Live figures, so the board door never advertises a number we can't back.
  // Both fall back to nothing rather than to a guess — an empty slot is honest,
  // a stale hardcoded figure is not.
  const [roles, setRoles] = useState<number | null>(null)
  const [employers, setEmployers] = useState<number | null>(null)

  useEffect(() => {
    fetchStats().then(s => setRoles(s.total_active_jobs)).catch(() => {})
    fetchFilters().then(f => setEmployers(f.companies.length)).catch(() => {})
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
          <em className="not-italic" style={{ color: 'var(--color-gold)' }}>Asia&rsquo;s 1st</em>{' '}
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
            description="Confidential one-to-one guidance for senior finance professionals weighing a move, a change of function, or the step up to the next seat."
            figure="By enquiry"
            href="#consultation"
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

// ── 02 · Executive Career Consultation ────────────────────────────────────────

function ConsultationSection() {
  return (
    <section
      id="consultation"
      aria-labelledby="consultation-heading"
      className="scroll-mt-20 lg:scroll-mt-26"
      style={{ backgroundColor: 'var(--color-surface-2)', borderTop: '1px solid var(--color-border)' }}
    >
      <div className="mx-auto max-w-7xl px-6 lg:px-8 py-16 lg:py-20">
        {/* items-start: without it the grid stretches the form column to the
            text column's height, which leaves the short success card as a tall
            mostly-empty box after submitting. */}
        <div className="grid items-start gap-12 lg:grid-cols-[1fr_1fr] lg:gap-16">
          <div>
            <span
              className="text-xs font-semibold uppercase"
              style={{ color: 'var(--color-gold)', letterSpacing: '0.14em' }}
            >
              02 · Executive Career Consultation
            </span>

            <h2
              id="consultation-heading"
              className="mt-3 text-3xl lg:text-4xl tracking-tight"
              style={{ fontFamily: 'var(--font-display)', fontWeight: 700, color: 'var(--color-ink)', letterSpacing: '-0.025em' }}
            >
              The conversation before the decision
            </h2>

            <div className="mt-5 space-y-4 text-base leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
              <p>
                Senior moves in Hong Kong finance are rarely decided on a job description.
                They turn on what a desk is really being built for, who you would answer to,
                and whether the mandate survives the next budget.
              </p>
              <p>
                We sit down with a small number of senior professionals each month — one to one,
                in confidence — to work through exactly that. Not CV formatting. The judgement
                calls: whether to move, where the function is heading, and what the seat you are
                being offered is actually worth.
              </p>
              <p style={{ color: 'var(--color-ink)' }}>
                Tell us what you are weighing up. We read every enquiry personally.
              </p>
            </div>

            <a
              href={CONSULTING_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-8 inline-flex items-center gap-1.5 text-sm font-semibold"
              style={{ color: 'var(--color-blue)' }}
            >
              FinEx Consulting — our institutional advisory practice
              <ArrowUpRight size={15} strokeWidth={2} />
            </a>
          </div>

          <EnquiryForm />
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
          <FooterLink to="/#consultation">Consultation</FooterLink>
          <FooterLink to="/learning">Learning</FooterLink>
          <FooterLink to="/post-a-role">Post a role</FooterLink>
          <FooterLink to="/about">About</FooterLink>
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
