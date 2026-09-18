import { useCallback, useEffect, useMemo, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { Check, CircleAlert, ExternalLink, Loader2, LockKeyhole, RefreshCw } from 'lucide-react'
import Nav from '../components/Nav'
import { useAuth } from '../auth/useAuth'
import { approveBannerCandidates, fetchBannerValidationQueue, fetchMTAmbiguousCandidates, type BannerValidationQueue, type MTAmbiguousCandidate } from '../api/client'

const hkDate = (value: string) => new Intl.DateTimeFormat('en-HK', { day: 'numeric', month: 'short', timeZone: 'Asia/Hong_Kong' }).format(new Date(`${value}T00:00:00+08:00`))

/** Ultimate Admin's editorial gate. Nothing here publishes automatically. */
export default function AsfPage() {
  const { seeker, loading } = useAuth()
  const [banner, setBanner] = useState<BannerValidationQueue | null>(null)
  const [mtCandidates, setMtCandidates] = useState<MTAmbiguousCandidate[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => {
    setBusy(true); setError(null)
    try { const [nextBanner, mt] = await Promise.all([fetchBannerValidationQueue(), fetchMTAmbiguousCandidates()]); setBanner(nextBanner); setMtCandidates(mt.roles); setSelected(new Set(nextBanner.roles.map(role => `${role.source}:${role.source_id}`))) }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not load validation queues.') }
    finally { setBusy(false) }
  }, [])
  useEffect(() => { if (!loading && seeker?.is_super_admin) void load() }, [loading, seeker?.is_super_admin, load])
  const selectedRoles = useMemo(() => banner?.roles.filter(role => selected.has(`${role.source}:${role.source_id}`)) ?? [], [banner, selected])
  if (!loading && !seeker?.is_super_admin) return <Navigate to="/signin" state={{ from: '/validate' }} replace />
  async function approve() { setBusy(true); setError(null); try { await approveBannerCandidates(selectedRoles); await load() } catch (err) { setError(err instanceof Error ? err.message : 'Could not lock next week’s banner.') } finally { setBusy(false) } }
  function toggle(key: string) {
    setSelected(current => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  return <div className="min-h-dvh" style={{ backgroundColor: 'var(--color-bg)' }}><Nav /><main className="mx-auto max-w-7xl px-4 pb-20 pt-10 sm:px-6 lg:px-8">
    <header className="grid gap-6 border-b pb-8 lg:grid-cols-[1fr_auto] lg:items-end" style={{ borderColor: 'var(--color-border)' }}><div><p className="text-xs font-semibold uppercase tracking-[.16em]" style={{ color: 'var(--color-gold)' }}>Ultimate Admin</p><h1 className="mt-2 text-4xl font-bold tracking-tight sm:text-5xl" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-display)' }}>Validate publication</h1><p className="mt-3 max-w-2xl text-base leading-7" style={{ color: 'var(--color-ink-muted)' }}>A deliberate checkpoint for what FinEx promotes and what it withholds. Nothing enters a public surface without your decision.</p></div><button type="button" onClick={() => void load()} disabled={busy} className="inline-flex min-h-11 items-center justify-center gap-2 border px-4 text-sm font-semibold" style={{ borderColor: 'var(--color-border-strong)', color: 'var(--color-ink)', backgroundColor: 'var(--color-surface)' }}>{busy ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />} Refresh queues</button></header>
    {error && <p role="alert" className="mt-6 border px-4 py-3 text-sm" style={{ borderColor: 'var(--color-destructive)', color: 'var(--color-destructive)', backgroundColor: 'var(--color-surface)' }}>{error}</p>}
    <section className="mt-10" aria-labelledby="banner-queue"><div className="flex flex-wrap items-end justify-between gap-4 border-b pb-4" style={{ borderColor: 'var(--color-border)' }}><div><p className="text-xs font-semibold uppercase tracking-[.14em]" style={{ color: 'var(--color-gold)' }}>Next week’s banner</p><h2 id="banner-queue" className="mt-1 text-2xl font-semibold" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-display)' }}>Approve the roles visitors will see first</h2></div>{banner && <span className="text-sm" style={{ color: 'var(--color-ink-muted)' }}>{hkDate(banner.week_start)}–{hkDate(banner.week_end)} · {banner.roles.length} suggested</span>}</div>
      {banner?.locked ? <div className="mt-5 flex items-center gap-3 border p-4 text-sm" style={{ borderColor: 'var(--color-border-strong)', backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink-muted)' }}><LockKeyhole size={17} /> This selection is locked for next week.</div> : <><div className="mt-5 divide-y border" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>{banner?.roles.map(role => { const key = `${role.source}:${role.source_id}`; return <label key={key} className="flex cursor-pointer items-center gap-4 px-4 py-4 hover:bg-[var(--color-surface-2)]"><input className="size-5 accent-[var(--color-blue)]" type="checkbox" checked={selected.has(key)} onChange={() => toggle(key)} /><span className="min-w-0 flex-1"><strong className="block truncate" style={{ color: 'var(--color-ink)' }}>{role.title}</strong><span className="mt-1 block text-sm" style={{ color: 'var(--color-ink-muted)' }}>{role.company} · {role.category} · posted {role.posted_at}</span></span><span className="hidden text-right text-sm sm:block" style={{ color: 'var(--color-ink-muted)' }}>HK${role.salary_min.toLocaleString()}–{role.salary_max.toLocaleString()}<br />{role.salary_confidence} confidence</span></label> })}</div><div className="mt-4 flex flex-wrap items-center justify-between gap-4"><p className="text-sm" style={{ color: 'var(--color-ink-muted)' }}>{selectedRoles.length} selected. Closed roles are removed automatically before the banner is shown.</p><button type="button" disabled={busy || selectedRoles.length === 0} onClick={() => void approve()} className="inline-flex min-h-11 items-center gap-2 px-5 text-sm font-semibold disabled:opacity-50" style={{ color: 'var(--color-ink-inverse)', backgroundColor: 'var(--color-ink)' }}><Check size={16} /> Approve & lock banner</button></div></>}</section>
    <section className="mt-14" aria-labelledby="mt-queue"><div className="border-b pb-4" style={{ borderColor: 'var(--color-border)' }}><p className="text-xs font-semibold uppercase tracking-[.14em]" style={{ color: 'var(--color-gold)' }}>MT review</p><h2 id="mt-queue" className="mt-1 text-2xl font-semibold" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-display)' }}>Potential Management Trainee postings</h2><p className="mt-2 max-w-2xl text-sm leading-6" style={{ color: 'var(--color-ink-muted)' }}>Workbook-company matches with a graduate or trainee signal, but not enough evidence for the public MT directory.</p></div><div className="mt-5 divide-y border" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>{mtCandidates.map(({ job, reason, watchlist_company }) => <article key={`${job.source}:${job.source_id}`} className="grid gap-4 p-5 md:grid-cols-[1fr_auto] md:items-center"><div><h3 className="font-semibold" style={{ color: 'var(--color-ink)' }}>{job.title}</h3><p className="mt-1 text-sm" style={{ color: 'var(--color-ink-muted)' }}>{job.company} → watchlist: {watchlist_company}</p><p className="mt-3 inline-flex items-center gap-2 text-sm" style={{ color: 'var(--color-ink-muted)' }}><CircleAlert size={15} /> {reason}</p></div><a href={job.url} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center justify-center gap-2 border px-4 text-sm font-semibold" style={{ borderColor: 'var(--color-border-strong)', color: 'var(--color-blue)' }}>Open source <ExternalLink size={15} /></a></article>)}</div>{!busy && mtCandidates.length === 0 && <p className="mt-5 border p-5 text-sm" style={{ borderColor: 'var(--color-border)', color: 'var(--color-ink-muted)' }}>No ambiguous MT candidates need review right now.</p>}</section>
  </main></div>
}
