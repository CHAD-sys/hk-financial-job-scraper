import { ArrowRight, ChevronRight, TrendingUp, Shield, Cpu, Star } from 'lucide-react'
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import Nav from '../components/Nav'
import StatCard from '../components/StatCard'
import { fetchStats } from '../api/client'

const TRUST_BADGES = [
  { icon: TrendingUp, text: 'Live market data' },
  { icon: Shield,     text: 'Verified institutions only' },
  { icon: Cpu,        text: 'AI-supported job data' },
]

export default function LandingPage() {
  const navigate = useNavigate()

  // Live figures from the API so the hero stats never go stale.
  const [roles, setRoles] = useState('2,500+')
  const [sectors, setSectors] = useState('5')
  useEffect(() => {
    fetchStats()
      .then(s => {
        setRoles(s.total_active_jobs.toLocaleString())
        setSectors(String(Object.keys(s.by_sector).length))
      })
      .catch(() => {}) // keep the conservative fallbacks on error
  }, [])

  const STATS = [
    { value: roles,   label: 'Active Roles', sub: 'Updated daily' },
    { value: '100+',  label: 'Institutions', sub: 'Banks, insurers, asset managers & more' },
    { value: sectors, label: 'Sectors',      sub: 'Banking · IB · Insurance · AM · Prof. Services' },
    { value: '100%',  label: 'AI-Supported', sub: 'Skills, seniority & salary signals' },
  ]

  return (
    <div style={{ backgroundColor: 'var(--color-bg)', minHeight: '100dvh' }}>
      <Nav />

      <main id="main-content">

        {/* ── Hero ──────────────────────────────────────────── */}
        <section
          aria-labelledby="hero-heading"
          className="relative overflow-hidden"
          style={{ borderBottom: '1px solid var(--color-border)' }}
        >
          {/* Subtle grid texture */}
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

          {/* Gold top rule — FT accent line */}
          <div
            aria-hidden="true"
            className="absolute top-0 inset-x-0 h-0.5"
            style={{ backgroundColor: 'var(--color-gold)' }}
          />

          <div className="relative mx-auto max-w-7xl px-6 lg:px-8 pt-24 pb-20 lg:pt-32 lg:pb-28">

            {/* Eyebrow */}
            <div className="flex items-center gap-2 mb-8">
              <span
                className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-widest"
                style={{
                  backgroundColor: 'var(--color-gold-light)',
                  color: 'var(--color-gold)',
                  border: '1px solid var(--color-gold)',
                }}
              >
                Hong Kong · 2026
              </span>
            </div>

            <div className="max-w-4xl">
              {/* Headline */}
              <h1
                id="hero-heading"
                className="leading-[1.08] tracking-tight mb-6"
                style={{
                  fontFamily: 'var(--font-display)',
                  fontSize: 'clamp(2.75rem, 5.5vw, 4.25rem)',
                  fontWeight: 700,
                  color: 'var(--color-ink)',
                  letterSpacing: '-0.02em',
                }}
              >
                Hong Kong's financial{' '}
                <em
                  className="not-italic"
                  style={{ color: 'var(--color-gold)' }}
                >
                  talent market
                </em>
                ,<br className="hidden sm:block" /> in one place.
              </h1>

              {/* Subhead */}
              <p
                className="max-w-2xl mb-10 text-lg leading-relaxed"
                style={{ color: 'var(--color-ink-muted)' }}
              >
                A curated, AI-supported index of 2,500+ open roles across leading institutions —
                investment banks, asset managers, fintechs and insurers. Built for investors,
                operators, and talent navigating the city's capital markets.
              </p>

              {/* CTAs */}
              <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
                <button
                  onClick={() => navigate('/jobs')}
                  className="inline-flex items-center gap-2 rounded px-6 py-3 text-sm font-semibold transition-all duration-200 cursor-pointer"
                  style={{ backgroundColor: 'var(--color-ink)', color: 'var(--color-ink-inverse)' }}
                  onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--color-blue)')}
                  onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--color-ink)')}
                >
                  Explore all roles
                  <ArrowRight size={16} strokeWidth={2} />
                </button>

                <button
                  onClick={() => navigate('/jobs?sector=Investment+Banking')}
                  className="inline-flex items-center gap-1.5 text-sm font-medium transition-colors duration-150 cursor-pointer"
                  style={{ color: 'var(--color-ink-muted)' }}
                  onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink)')}
                  onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink-muted)')}
                >
                  Browse Investment Banking
                  <ChevronRight size={14} strokeWidth={2} />
                </button>
              </div>

              {/* Trust badges */}
              <div className="flex flex-wrap items-center gap-x-6 gap-y-3 mt-10">
                {TRUST_BADGES.map(({ icon: Icon, text }) => (
                  <div
                    key={text}
                    className="flex items-center gap-2"
                    style={{ color: 'var(--color-ink-faint)' }}
                  >
                    <Icon size={14} strokeWidth={1.5} />
                    <span className="text-xs font-medium">{text}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* ── Stat Cards ────────────────────────────────────── */}
        <section
          aria-label="Platform statistics"
          style={{ backgroundColor: 'var(--color-surface-2)', borderBottom: '1px solid var(--color-border)' }}
        >
          <div className="mx-auto max-w-7xl px-6 lg:px-8 py-12">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {STATS.map(s => (
                <StatCard key={s.label} value={s.value} label={s.label} sub={s.sub} />
              ))}
            </div>
          </div>
        </section>

        {/* ── Exclusive listings callout ────────────────────── */}
        <section
          aria-labelledby="exclusive-heading"
          style={{ borderBottom: '1px solid var(--color-border)' }}
        >
          <div className="mx-auto max-w-7xl px-6 lg:px-8 py-14">
            <div
              className="rounded-xl p-8 lg:p-10 flex flex-col lg:flex-row lg:items-center gap-8"
              style={{
                backgroundColor: 'var(--color-surface)',
                border: '1px solid var(--color-gold)',
                boxShadow: 'var(--shadow-card)',
              }}
            >
              <div className="min-w-0 flex-1">
                <span
                  className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-widest mb-4"
                  style={{
                    backgroundColor: 'var(--color-gold-light)',
                    color: 'var(--color-gold)',
                    border: '1px solid var(--color-gold)',
                  }}
                >
                  <Star size={13} strokeWidth={2} fill="currentColor" aria-hidden="true" />
                  Exclusive
                </span>
                <h2
                  id="exclusive-heading"
                  className="text-2xl lg:text-3xl font-bold tracking-tight mb-3"
                  style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)', letterSpacing: '-0.02em' }}
                >
                  Roles you won't find on the major job boards
                </h2>
                <p
                  className="max-w-2xl text-base leading-relaxed"
                  style={{ color: 'var(--color-ink-muted)' }}
                >
                  Alongside mainstream listings, we index openings published directly on the
                  official careers pages of boutique and specialist financial firms — many of
                  which never reach the large aggregators. Every exclusive role is compiled from
                  information the employer has made <span style={{ color: 'var(--color-ink)', fontWeight: 600 }}>publicly available on its own website</span>,
                  then structured and translated with AI. No logins, no scraping behind
                  paywalls — just public postings, organised in one place.
                </p>
              </div>

              <div className="flex-shrink-0">
                <button
                  onClick={() => navigate('/jobs?tier=boutique')}
                  className="inline-flex items-center gap-2 rounded px-6 py-3 text-sm font-semibold transition-all duration-200 cursor-pointer whitespace-nowrap"
                  style={{ backgroundColor: 'var(--color-gold)', color: 'var(--color-ink-inverse)' }}
                  onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.opacity = '0.9')}
                  onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.opacity = '1')}
                >
                  <Star size={15} strokeWidth={2} fill="currentColor" aria-hidden="true" />
                  View Exclusive roles
                  <ArrowRight size={16} strokeWidth={2} />
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* ── Thin institutional stripe ─────────────────────── */}
        <section
          aria-label="Data freshness note"
          className="py-5"
          style={{ borderBottom: '1px solid var(--color-border)' }}
        >
          <div className="mx-auto max-w-7xl px-6 lg:px-8 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <p
              className="text-sm"
              style={{ color: 'var(--color-ink-muted)' }}
            >
              Data refreshed daily from public postings. Enriched with AI-derived skills,
              seniority classification, and compensation signals.
            </p>
            <a
              href="#"
              className="text-sm font-medium whitespace-nowrap flex items-center gap-1 cursor-pointer transition-colors duration-150"
              style={{ color: 'var(--color-gold)' }}
              onMouseEnter={e => (e.currentTarget.style.color = 'var(--color-blue)')}
              onMouseLeave={e => (e.currentTarget.style.color = 'var(--color-gold)')}
            >
              Read the methodology
              <ChevronRight size={14} strokeWidth={2} />
            </a>
          </div>
        </section>

      </main>

      {/* ── Footer ────────────────────────────────────────────── */}
      <footer
        className="mt-auto"
        style={{ borderTop: '1px solid var(--color-border)' }}
        role="contentinfo"
      >
        <div className="mx-auto max-w-7xl px-6 lg:px-8 py-10 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-6">
          <div className="flex items-center gap-2">
            <span
              className="text-sm font-semibold tracking-tight"
              style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)' }}
            >
              FinEx <em className="not-italic" style={{ color: 'var(--color-gold)' }}>Careers</em>
            </span>
            <span
              className="text-xs"
              style={{ color: 'var(--color-ink-faint)' }}
            >
              — Hong Kong Financial Jobs Index
            </span>
          </div>

          <nav
            className="flex flex-wrap gap-x-6 gap-y-2"
            aria-label="Footer navigation"
          >
            {['Browse', 'Companies', 'Sectors', 'API', 'About'].map(label => (
              <a
                key={label}
                href="#"
                className="text-xs font-medium transition-colors duration-150 cursor-pointer"
                style={{ color: 'var(--color-ink-faint)' }}
                onMouseEnter={e => (e.currentTarget.style.color = 'var(--color-ink-muted)')}
                onMouseLeave={e => (e.currentTarget.style.color = 'var(--color-ink-faint)')}
              >
                {label}
              </a>
            ))}
          </nav>

          <p
            className="text-xs"
            style={{ color: 'var(--color-ink-faint)' }}
          >
            © 2026 FinEx Careers. For informational use only.
          </p>
        </div>
      </footer>
    </div>
  )
}
