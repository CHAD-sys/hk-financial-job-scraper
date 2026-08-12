import { useMemo, useState } from 'react'
import { Search, ShieldCheck, Users } from 'lucide-react'
import type { AdminAccountsResponse, AdminEmployerAccount, AdminSeekerAccount } from '../../api/client'

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
          <table className="w-full min-w-[760px] border-collapse text-left text-sm">
            <thead style={{ backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink-muted)' }}>
              <tr>
                {['Email', 'Name', 'Status', 'Signed up', 'Last login'].map(heading => (
                  <th key={heading} scope="col" className="px-4 py-3 text-xs font-semibold">{heading}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {seekers.length === 0 ? (
                <tr><td colSpan={5} className="px-4 py-6 text-center text-sm" style={{ color: 'var(--color-ink-muted)' }}>No matching Seekers.</td></tr>
              ) : seekers.map((seeker: AdminSeekerAccount) => (
                <tr key={seeker.id} className="border-t" style={{ borderColor: 'var(--color-border)' }}>
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
                </tr>
              ))}
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
