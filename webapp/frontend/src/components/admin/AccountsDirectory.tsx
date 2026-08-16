import { Fragment, useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, Download, LoaderCircle, Search, ShieldCheck, Users } from 'lucide-react'
import {
  downloadSeekerResume,
  fetchSeekerInterests,
  type AdminAccountsResponse,
  type AdminEmployerAccount,
  type AdminSeekerAccount,
  type AdminSeekerInterests,
} from '../../api/client'

function formatDate(value: string | null) {
  if (!value) return 'Never'
  return new Date(value).toLocaleString('en-HK', { timeZone: 'Asia/Hong_Kong', dateStyle: 'medium', timeStyle: 'short' })
}

function Flag({ label, on }: { label: string; on: boolean }) {
  return (
    <span
      className="inline-flex min-h-6 items-center rounded-full px-2 text-[11px] font-semibold"
      style={{
        backgroundColor: on ? 'var(--color-success-bg)' : 'var(--color-surface-2)',
        color: on ? 'var(--color-success)' : 'var(--color-ink-muted)',
        border: `1px solid ${on ? 'var(--color-success-border)' : 'var(--color-border)'}`,
      }}
    >
      {label}
    </span>
  )
}

function Tag({ children }: { children: string }) {
  return (
    <span
      className="inline-flex min-h-6 items-center rounded-full px-2 text-[11px] font-medium"
      style={{ backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink)', border: '1px solid var(--color-border)' }}
    >
      {children}
    </span>
  )
}

function TagRow({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) return null
  return (
    <div className="flex flex-wrap items-baseline gap-2">
      <span className="shrink-0 text-xs font-semibold" style={{ color: 'var(--color-ink-muted)' }}>{label}</span>
      <div className="flex flex-wrap gap-1">
        {values.map(value => <Tag key={value}>{value}</Tag>)}
      </div>
    </div>
  )
}

function hasNoInterestSignal(interests: AdminSeekerInterests) {
  return interests.resume_skills.length === 0
    && interests.resume_sectors.length === 0
    && interests.resume_role_families.length === 0
    && interests.searched_sectors.length === 0
    && interests.searched_skills.length === 0
    && interests.searched_seniority.length === 0
    && interests.recent_search_terms.length === 0
    && interests.saved_roles_count === 0
}

/**
 * Fetched only when its row expands — never bundled into the initial
 * account-directory load, which stays one flat, fast query regardless of how
 * many Seekers exist (see admin.py's get_seeker_interests_route docstring).
 */
function SeekerInterestsPanel({ seekerId }: { seekerId: string }) {
  const [interests, setInterests] = useState<AdminSeekerInterests | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setInterests(null)
    setError(null)
    fetchSeekerInterests(seekerId)
      .then(result => { if (!cancelled) setInterests(result) })
      .catch(err => { if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load interests.') })
    return () => { cancelled = true }
  }, [seekerId])

  if (error) return <p className="text-xs" style={{ color: 'var(--color-destructive)' }}>{error}</p>
  if (!interests) return <p className="text-xs" style={{ color: 'var(--color-ink-muted)' }}>Loading interests…</p>
  if (hasNoInterestSignal(interests)) {
    return <p className="text-xs" style={{ color: 'var(--color-ink-muted)' }}>No resume, search, or saved-Role activity on file yet.</p>
  }

  return (
    <div className="space-y-2.5">
      {interests.resume_seniority && <TagRow label="Resume seniority" values={[interests.resume_seniority]} />}
      <TagRow label="Resume skills" values={interests.resume_skills} />
      <TagRow label="Resume sectors" values={interests.resume_sectors} />
      <TagRow label="Resume role families" values={interests.resume_role_families} />
      <TagRow label="Searched sectors" values={interests.searched_sectors} />
      <TagRow label="Searched skills" values={interests.searched_skills} />
      <TagRow label="Searched seniority" values={interests.searched_seniority} />
      <TagRow label="Recent searches" values={interests.recent_search_terms} />
      <p className="text-xs" style={{ color: 'var(--color-ink-muted)' }}>
        {interests.saved_roles_count.toLocaleString()} saved Role{interests.saved_roles_count === 1 ? '' : 's'}
      </p>
    </div>
  )
}

/**
 * Downloads one Seeker's resume file, for troubleshooting a match that looks
 * wrong. Ultimate Admin only — the backend enforces that, this button merely
 * stops existing for rows with no resume.
 *
 * Every click writes an audit row naming the admin, the Seeker and the moment
 * (see admin.py's download_seeker_resume_route), so the label says so rather
 * than leaving that a surprise. The failure lands next to the button instead
 * of in a toast: it is almost always 403 or "no resume on file", both of which
 * are about this specific row.
 */
function ResumeDownloadButton({ seeker }: { seeker: AdminSeekerAccount }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  if (!seeker.has_resume) {
    return <span className="text-xs" style={{ color: 'var(--color-ink-faint)' }}>—</span>
  }

  const run = async () => {
    setBusy(true)
    setError('')
    try {
      await downloadSeekerResume(seeker.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Download failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={run}
        disabled={busy}
        title="Downloading is recorded against your account"
        aria-label={`Download the resume on file for ${seeker.email}`}
        className="inline-flex min-h-9 items-center gap-1.5 rounded px-2.5 text-xs font-semibold disabled:opacity-60"
        style={{ border: '1px solid var(--color-border-strong)', color: 'var(--color-blue)' }}
      >
        {busy
          ? <LoaderCircle size={14} className="animate-spin" aria-hidden="true" />
          : <Download size={14} aria-hidden="true" />}
        {busy ? 'Preparing…' : 'CV'}
      </button>
      {error && (
        <span role="alert" className="text-[11px]" style={{ color: 'var(--color-destructive)' }}>{error}</span>
      )}
    </div>
  )
}

function matches(query: string, ...fields: (string | null)[]) {
  if (!query) return true
  const needle = query.trim().toLowerCase()
  return fields.some(field => (field ?? '').toLowerCase().includes(needle))
}

/**
 * Ultimate Admin's read-only account directory — Seeker and Employer accounts
 * side by side, same read-only-but-full-visibility posture as the Job
 * Editor's write access to a Role. Two independent stores (ADR 0001), so two
 * tables rather than one merged list that would blur the distinction.
 */
export default function AccountsDirectory({ data }: { data: AdminAccountsResponse }) {
  const [query, setQuery] = useState('')
  const [expandedSeekerId, setExpandedSeekerId] = useState<string | null>(null)

  const seekers = useMemo(
    () => data.seekers.filter(s => matches(query, s.email, s.display_name, s.username)),
    [data.seekers, query],
  )
  const employers = useMemo(
    () => data.employers.filter(e => matches(query, e.email, e.company_name, e.contact_name)),
    [data.employers, query],
  )

  return (
    <div>
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="max-w-3xl">
          <p className="text-xs font-semibold uppercase tracking-[0.14em]" style={{ color: 'var(--color-gold)' }}>Ultimate Admin</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-display)' }}>Account directory</h2>
          <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
            Every Seeker and Employer account, read-only. {data.seekers.length.toLocaleString()} Seekers · {data.employers.length.toLocaleString()} Employers.
          </p>
        </div>
        <div className="relative self-start sm:self-auto">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--color-ink-muted)' }} aria-hidden="true" />
          <input
            type="search"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Filter by email or name…"
            aria-label="Filter accounts by email or name"
            className="min-h-11 w-full rounded-md py-2 pl-9 pr-3 text-sm sm:w-72"
            style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border-strong)', color: 'var(--color-ink)' }}
          />
        </div>
      </div>

      <section aria-labelledby="seekers-heading" className="mb-10">
        <div className="mb-3 flex items-center gap-2">
          <Users size={18} style={{ color: 'var(--color-gold)' }} aria-hidden="true" />
          <h3 id="seekers-heading" className="text-lg font-semibold" style={{ color: 'var(--color-ink)' }}>Seekers</h3>
          <span className="text-xs" style={{ color: 'var(--color-ink-muted)' }}>{seekers.length.toLocaleString()} of {data.seekers.length.toLocaleString()}</span>
        </div>
        <div className="overflow-x-auto rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2" tabIndex={0} role="region" aria-labelledby="seekers-heading" style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface)', outlineColor: 'var(--color-gold)' }}>
          <table className="w-full min-w-[820px] border-collapse text-left text-sm">
            <thead style={{ backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink-muted)' }}>
              <tr>
                {['', 'Email', 'Name', 'Status', 'Signed up', 'Last login', 'Resume'].map(heading => (
                  <th key={heading} scope="col" className="px-4 py-3 text-xs font-semibold">{heading}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {seekers.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-6 text-center text-sm" style={{ color: 'var(--color-ink-muted)' }}>No matching Seekers.</td></tr>
              ) : seekers.map((seeker: AdminSeekerAccount) => {
                const expanded = expandedSeekerId === seeker.id
                return (
                  <Fragment key={seeker.id}>
                    <tr className="border-t" style={{ borderColor: 'var(--color-border)' }}>
                      <td className="px-2 py-3">
                        <button
                          type="button"
                          onClick={() => setExpandedSeekerId(expanded ? null : seeker.id)}
                          aria-expanded={expanded}
                          aria-label={`${expanded ? 'Hide' : 'Show'} interests for ${seeker.email}`}
                          className="flex size-6 items-center justify-center rounded"
                          style={{ color: 'var(--color-ink-muted)' }}
                        >
                          {expanded ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronRight size={16} aria-hidden="true" />}
                        </button>
                      </td>
                      <th scope="row" className="px-4 py-3 font-semibold" style={{ color: 'var(--color-ink)' }}>{seeker.email}</th>
                      <td className="px-4 py-3" style={{ color: 'var(--color-ink-muted)' }}>{seeker.display_name || seeker.username || '—'}</td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1.5">
                          <Flag label="Verified" on={seeker.email_verified} />
                          {seeker.is_super_admin ? <Flag label="Ultimate Admin" on /> : seeker.is_admin ? <Flag label="Admin" on /> : null}
                        </div>
                      </td>
                      <td className="px-4 py-3 tabular-nums" style={{ color: 'var(--color-ink-muted)' }}>{formatDate(seeker.created_at)}</td>
                      <td className="px-4 py-3 tabular-nums" style={{ color: 'var(--color-ink-muted)' }}>{formatDate(seeker.last_login_at)}</td>
                      <td className="px-4 py-3"><ResumeDownloadButton seeker={seeker} /></td>
                    </tr>
                    {expanded && (
                      <tr style={{ borderTop: 'none' }}>
                        <td colSpan={7} className="px-4 pb-4" style={{ backgroundColor: 'var(--color-surface-2)' }}>
                          <div className="rounded-md p-3">
                            <SeekerInterestsPanel seekerId={seeker.id} />
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="employers-heading">
        <div className="mb-3 flex items-center gap-2">
          <ShieldCheck size={18} style={{ color: 'var(--color-gold)' }} aria-hidden="true" />
          <h3 id="employers-heading" className="text-lg font-semibold" style={{ color: 'var(--color-ink)' }}>Employers</h3>
          <span className="text-xs" style={{ color: 'var(--color-ink-muted)' }}>{employers.length.toLocaleString()} of {data.employers.length.toLocaleString()}</span>
        </div>
        <div className="overflow-x-auto rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2" tabIndex={0} role="region" aria-labelledby="employers-heading" style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface)', outlineColor: 'var(--color-gold)' }}>
          <table className="w-full min-w-[760px] border-collapse text-left text-sm">
            <thead style={{ backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink-muted)' }}>
              <tr>
                {['Email', 'Company', 'Contact', 'Status', 'Signed up', 'Last login'].map(heading => (
                  <th key={heading} scope="col" className="px-4 py-3 text-xs font-semibold">{heading}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {employers.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-6 text-center text-sm" style={{ color: 'var(--color-ink-muted)' }}>No matching Employers.</td></tr>
              ) : employers.map((employer: AdminEmployerAccount) => (
                <tr key={employer.id} className="border-t" style={{ borderColor: 'var(--color-border)' }}>
                  <th scope="row" className="px-4 py-3 font-semibold" style={{ color: 'var(--color-ink)' }}>{employer.email}</th>
                  <td className="px-4 py-3" style={{ color: 'var(--color-ink)' }}>{employer.company_name}</td>
                  <td className="px-4 py-3" style={{ color: 'var(--color-ink-muted)' }}>{employer.contact_name || '—'}</td>
                  <td className="px-4 py-3"><Flag label="Verified" on={employer.email_verified} /></td>
                  <td className="px-4 py-3 tabular-nums" style={{ color: 'var(--color-ink-muted)' }}>{formatDate(employer.created_at)}</td>
                  <td className="px-4 py-3 tabular-nums" style={{ color: 'var(--color-ink-muted)' }}>{formatDate(employer.last_login_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
