import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowRight, Star, Sparkles, ShieldCheck, Layers, Languages,
  Coins, Gauge, Radar, Building2, CalendarClock, Puzzle, EyeOff,
} from 'lucide-react'
import Nav from '../components/Nav'
import { DataFlow, CoverageRadar, GrowthBars } from '../components/Illustrations'
import { fetchStats } from '../api/client'

// What the single daily AI pass adds to every posting.
const ENRICHMENTS = [
  { icon: Puzzle, title: 'Skills', body: '7–10 concrete skills per role — from AML and IFRS to Bloomberg, Murex and CFA.' },
  { icon: Layers, title: 'Seniority & category', body: 'Analyst → MD mapped to a consistent ladder, plus a functional category.' },
  { icon: Coins, title: 'Salary estimate', body: 'A Hong Kong monthly band, calibrated to the 2026 Hays Asia Salary Guide.' },
  { icon: Languages, title: 'English translation', body: 'Cantonese / Mandarin titles and descriptions rendered faithfully in English.' },
  { icon: Gauge, title: 'Work type & experience', body: 'On-site / hybrid / remote and required years, normalised across sources.' },
  { icon: Sparkles, title: 'Plain-language summary', body: 'A short, neutral précis of each role for fast scanning.' },
]

const SOURCES = [
  { icon: Radar, title: 'Straight from the employer', body: 'We read jobs directly from applicant-tracking systems (Workday, Eightfold) — structured data at the source, not fragile page-scraping.' },
  { icon: Building2, title: 'Major public boards', body: 'Widely-listed roles are folded in and de-duplicated so nothing is counted twice.' },
  { icon: Star, title: 'Boutique careers pages', body: 'Our Exclusive track reads roles published on the official sites of specialist firms — hedge funds, family offices, brokerages — that never reach the aggregators.', accent: 'gold' as const },
  { icon: EyeOff, title: 'Recruiter LinkedIn posts', body: 'Our Recruiter Posts track watches Hong Kong recruiters and headhunters on LinkedIn and extracts the roles they mention — mandates that never get formally posted anywhere.', accent: 'purple' as const },
]

export default function AboutPage() {
  const navigate = useNavigate()
  const [roles, setRoles] = useState('2,400+')
  const [sectors, setSectors] = useState('6')
  const [boutique, setBoutique] = useState<number | null>(null)
  const [social, setSocial] = useState<number | null>(null)
  useEffect(() => {
    fetchStats().then(s => {
      setRoles((Math.floor(s.total_active_jobs / 100) * 100).toLocaleString() + '+')
      setSectors(String(Object.keys(s.by_sector).length))
      setBoutique(s.by_source_tier?.boutique ?? null)
      setSocial(s.by_source_tier?.social ?? null)
    }).catch(() => {})
  }, [])

  return (
    <div style={{ backgroundColor: 'var(--color-bg)', minHeight: '100dvh' }}>
      <Nav />
      <main id="main-content">

        {/* ── Hero: the mission (DataFlow art, distinct from Home) ── */}
        <section className="relative overflow-hidden"
                 style={{ backgroundColor: 'var(--color-nav)', borderBottom: '1px solid rgba(255,255,255,0.08)' }}
                 aria-labelledby="about-heading">
          <div aria-hidden="true" className="absolute top-0 inset-x-0 h-0.5" style={{ backgroundColor: 'var(--color-gold)' }} />
          <div className="relative mx-auto max-w-7xl px-6 lg:px-8 py-16 lg:py-20 grid lg:grid-cols-2 gap-10 items-center">
            <div>
              <p className="text-xs font-semibold uppercase tracking-widest mb-3" style={{ color: 'var(--color-gold)', letterSpacing: '0.14em' }}>
                About &middot; How it works
              </p>
              <h1 id="about-heading" className="font-bold leading-[1.1] tracking-tight mb-5"
                  style={{ fontFamily: 'var(--font-display)', fontSize: 'clamp(2.1rem, 4.2vw, 3.25rem)', color: 'var(--color-ink-inverse)', letterSpacing: '-0.02em' }}>
                Hong Kong&rsquo;s financial hiring,{' '}
                <em className="not-italic" style={{ color: 'var(--color-gold)' }}>made legible</em>.
              </h1>
              <p className="max-w-xl text-lg leading-relaxed" style={{ color: 'rgba(248,250,252,0.72)' }}>
                Openings are scattered across dozens of tracking systems, job boards and boutique
                career pages &mdash; many written in Chinese, rarely in one place. FinEx reads them
                all, every day, and turns the mess into a single structured index.
              </p>
            </div>
            <div className="hidden lg:block">
              <DataFlow className="w-full h-auto" style={{ maxWidth: 520, marginLeft: 'auto' }} />
            </div>
          </div>
        </section>

        {/* ── The problem we solve ─────────────────────────── */}
        <section className="mx-auto max-w-7xl px-6 lg:px-8 py-16 grid lg:grid-cols-[1.4fr_1fr] gap-12 items-center">
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest mb-2" style={{ color: 'var(--color-gold)', letterSpacing: '0.12em' }}>Why we built it</p>
            <h2 className="text-2xl lg:text-3xl font-bold tracking-tight mb-4"
                style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)', letterSpacing: '-0.02em' }}>
              Good roles hide in plain sight
            </h2>
            <ul className="flex flex-col gap-3">
              {[
                'Every firm posts on its own system — Workday here, Eightfold there, a bespoke page elsewhere.',
                'A large share of postings are in Cantonese or Mandarin, invisible to English-only search.',
                'Boutiques and specialist funds rarely appear on the big aggregators at all.',
                'And no one keeps the history — so the market’s direction is impossible to see.',
              ].map(t => (
                <li key={t} className="flex gap-3 text-base leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
                  <span className="flex-shrink-0 mt-2 h-1.5 w-1.5 rounded-full" style={{ backgroundColor: 'var(--color-gold)' }} />
                  {t}
                </li>
              ))}
            </ul>
          </div>
          <div className="flex justify-center">
            <CoverageRadar className="w-full h-auto" style={{ maxWidth: 300 }} />
          </div>
        </section>

        {/* ── Under the hood: the AI pass ──────────────────── */}
        <section aria-labelledby="hood-heading"
                 style={{ backgroundColor: 'var(--color-surface-2)', borderTop: '1px solid var(--color-border)', borderBottom: '1px solid var(--color-border)' }}>
          <div className="mx-auto max-w-7xl px-6 lg:px-8 py-16">
            <div className="flex items-center gap-2 mb-2">
              <Sparkles size={16} style={{ color: 'var(--color-gold)' }} />
              <p className="text-xs font-semibold uppercase tracking-widest" style={{ color: 'var(--color-gold)', letterSpacing: '0.12em' }}>Under the hood</p>
            </div>
            <h2 id="hood-heading" className="text-2xl lg:text-3xl font-bold tracking-tight mb-3"
                style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)', letterSpacing: '-0.02em' }}>
              One AI pass reads every posting
            </h2>
            <p className="max-w-2xl text-base leading-relaxed mb-8" style={{ color: 'var(--color-ink-muted)' }}>
              Raw postings are messy. A single language-model pass turns each one into clean,
              comparable fields &mdash; no extra calls, no manual tagging.
            </p>
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {ENRICHMENTS.map(({ icon: Icon, title, body }) => (
                <div key={title} className="rounded-xl p-5" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)' }}>
                  <span className="flex h-10 w-10 items-center justify-center rounded-lg mb-3" style={{ backgroundColor: 'var(--color-gold-light)', color: 'var(--color-gold)' }}>
                    <Icon size={18} strokeWidth={1.8} />
                  </span>
                  <h3 className="text-base font-semibold mb-1" style={{ color: 'var(--color-ink)' }}>{title}</h3>
                  <p className="text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>{body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── Market intelligence (the data vision) ────────── */}
        <section className="mx-auto max-w-7xl px-6 lg:px-8 py-16 grid lg:grid-cols-[1fr_1.3fr] gap-12 items-center">
          <div className="order-2 lg:order-1 rounded-2xl p-8" style={{ backgroundColor: 'var(--color-ink)' }}>
            <GrowthBars className="w-full h-24" />
          </div>
          <div className="order-1 lg:order-2">
            <div className="flex items-center gap-2 mb-2">
              <CalendarClock size={16} style={{ color: 'var(--color-gold)' }} />
              <p className="text-xs font-semibold uppercase tracking-widest" style={{ color: 'var(--color-gold)', letterSpacing: '0.12em' }}>What comes next</p>
            </div>
            <h2 className="text-2xl lg:text-3xl font-bold tracking-tight mb-4"
                style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)', letterSpacing: '-0.02em' }}>
              A day-by-day picture of the market
            </h2>
            <p className="text-base leading-relaxed mb-3" style={{ color: 'var(--color-ink-muted)' }}>
              Every daily run is recorded, so FinEx is quietly compiling how hiring moves &mdash; which
              firms are growing, which skills are rising, where salaries drift. That archive is the
              foundation for the trends and tips coming to this site.
            </p>
            <p className="text-sm" style={{ color: 'var(--color-ink-faint)' }}>
              Covering <span style={{ color: 'var(--color-ink)', fontWeight: 600 }}>{roles}</span> active roles
              across <span style={{ color: 'var(--color-ink)', fontWeight: 600 }}>100+</span> institutions
              and <span style={{ color: 'var(--color-ink)', fontWeight: 600 }}>{sectors}</span> sectors today.
            </p>
          </div>
        </section>

        {/* ── How we source (transparency; Exclusive framed as a source) ── */}
        <section aria-labelledby="src-heading"
                 style={{ backgroundColor: 'var(--color-surface-2)', borderTop: '1px solid var(--color-border)' }}>
          <div className="mx-auto max-w-7xl px-6 lg:px-8 py-16">
            <h2 id="src-heading" className="text-2xl lg:text-3xl font-bold tracking-tight mb-3"
                style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)', letterSpacing: '-0.02em' }}>
              Where the data comes from
            </h2>
            <p className="max-w-2xl text-base leading-relaxed mb-8" style={{ color: 'var(--color-ink-muted)' }}>
              Four kinds of sources, all public. The last two are what set FinEx apart.
            </p>
            <div className="grid sm:grid-cols-2 md:grid-cols-4 gap-4">
              {SOURCES.map(({ icon: Icon, title, body, accent }) => {
                const accentColor = accent === 'gold' ? 'var(--color-gold)' : accent === 'purple' ? '#6B4EFF' : null
                const accentLight = accent === 'gold' ? 'var(--color-gold-light)' : accent === 'purple' ? 'rgba(107,78,255,0.12)' : null
                return (
                  <div key={title} className="rounded-xl p-6"
                       style={{ backgroundColor: 'var(--color-surface)', border: `1px solid ${accentColor ?? 'var(--color-border)'}`, boxShadow: 'var(--shadow-card)' }}>
                    <span className="flex h-11 w-11 items-center justify-center rounded-lg mb-4"
                          style={{ backgroundColor: accent === 'gold' ? accentColor! : (accentLight ?? 'var(--color-gold-light)'), color: accent === 'gold' ? 'var(--color-nav)' : (accentColor ?? 'var(--color-gold)') }}>
                      <Icon size={20} strokeWidth={1.8} fill={accent === 'gold' ? 'currentColor' : 'none'} />
                    </span>
                    {accent === 'gold' && (
                      <span className="inline-block text-[10px] font-bold uppercase tracking-wider mb-2 px-2 py-0.5 rounded"
                            style={{ backgroundColor: 'var(--color-gold-light)', color: 'var(--color-gold)' }}>
                        Exclusive{boutique != null ? ` · ${boutique} live` : ''}
                      </span>
                    )}
                    {accent === 'purple' && (
                      <span className="inline-block text-[10px] font-bold uppercase tracking-wider mb-2 px-2 py-0.5 rounded"
                            style={{ backgroundColor: 'rgba(107,78,255,0.12)', color: '#6B4EFF' }}>
                        Recruiter Posts{social != null ? ` · ${social} live` : ''}
                      </span>
                    )}
                    <h3 className="text-base font-semibold mb-1" style={{ color: 'var(--color-ink)' }}>{title}</h3>
                    <p className="text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>{body}</p>
                  </div>
                )
              })}
            </div>
            <div className="flex items-start gap-3 mt-8 rounded-lg p-4" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
              <ShieldCheck size={18} style={{ color: 'var(--color-gold)', marginTop: 1 }} />
              <p className="text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
                Everything is compiled from information employers publish on their own public pages &mdash;
                no logins, no paywalls. Just organised, in one place.
              </p>
            </div>
          </div>
        </section>

        {/* ── Closing CTA (subtle, not a Home duplicate) ───── */}
        <section className="mx-auto max-w-7xl px-6 lg:px-8 py-14 flex flex-col sm:flex-row items-center justify-between gap-5"
                 style={{ borderTop: '1px solid var(--color-border)' }}>
          <p className="text-lg font-semibold" style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)' }}>
            See it in action.
          </p>
          <div className="flex items-center gap-3">
            <button type="button" onClick={() => navigate('/jobs')}
                    className="inline-flex items-center gap-2 rounded-md px-5 py-2.5 text-sm font-semibold cursor-pointer transition-colors duration-200"
                    style={{ backgroundColor: 'var(--color-ink)', color: 'var(--color-ink-inverse)' }}
                    onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'var(--color-blue)')}
                    onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'var(--color-ink)')}>
              Browse all roles <ArrowRight size={15} />
            </button>
            <button type="button" onClick={() => navigate('/jobs?tier=boutique')}
                    className="inline-flex items-center gap-1.5 text-sm font-semibold cursor-pointer"
                    style={{ color: 'var(--color-gold)' }}>
              <Star size={14} strokeWidth={2} fill="currentColor" /> Exclusive
            </button>
          </div>
        </section>
      </main>

      <footer style={{ borderTop: '1px solid var(--color-border)' }}>
        <div className="mx-auto max-w-7xl px-6 lg:px-8 py-8 flex flex-col sm:flex-row items-center justify-between gap-3">
          <span className="text-sm font-semibold tracking-tight" style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)' }}>
            FinEx <em className="not-italic" style={{ color: 'var(--color-gold)' }}>Careers</em>
            <span className="text-xs font-normal ml-2" style={{ color: 'var(--color-ink-faint)' }}>&mdash; Hong Kong Financial Jobs Index</span>
          </span>
          <span className="text-xs" style={{ color: 'var(--color-ink-faint)' }}>Data refreshed daily from public postings.</span>
        </div>
      </footer>
    </div>
  )
}
