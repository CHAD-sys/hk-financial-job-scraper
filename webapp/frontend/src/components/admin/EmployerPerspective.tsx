import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Building2,
  CircleSlash,
  ExternalLink,
  Eye,
  EyeOff,
  Inbox,
  Search,
} from 'lucide-react'
import { useEmployerView } from '../../employerView/useEmployerView'
import {
  fetchEmployerActivity,
  type AdminEmployerAccount,
  type EmployerActivity,
  type EmployerStanding,
  type EmployerSubmission,
} from '../../api/client'

/**
 * The Employer's perspective — Ultimate Admin only.
 *
 * The panel that answers "where is my role?" without opening a JSONL file and
 * a SQLite shell. Everything an Employer did (submitted a Role) and everything
 * that became of it (approved, rejected, live, capped out) in one place, joined
 * server-side by webapp/backend/employer_view.py.
 *
 * Two things it must never do, both of which the read model already enforces
 * and this component is careful not to undo in the rendering:
 *
 *   - present an attribution as fact. /api/post-role records no employer_id,
 *     so a submission is tied to an account by email (strong) or by company
 *     name (weak). The badge says which, on every row.
 *   - call a Role "live" that a visitor cannot open. `board_roles` is
 *     job_read.list_jobs at BOARD visibility, and `standing.capped` names the
 *     Roles that are open, fresh and still off the board under ADR 0035.
 */

const STANDING_COPY: Record<keyof EmployerStanding, { label: string; detail: string }> = {
  on_board: { label: 'On the board', detail: 'A visitor can browse to these' },
  capped: { label: 'Capped out', detail: 'Open and fresh, but past the 60-per-employer limit (ADR 0035)' },
  aged_out: { label: 'Aged out', detail: 'Posted more than a calendar month ago' },
  undated: { label: 'Undated', detail: 'No posting date, so age cannot be verified' },
  hidden: { label: 'Hidden', detail: 'An admin took these off the board' },
  duplicate: { label: 'Cross-post copy', detail: 'The same vacancy, seen on another source' },
  closed: { label: 'Closed', detail: 'No longer open' },
}

const STANDING_ORDER: (keyof EmployerStanding)[] = [
  'on_board', 'capped', 'aged_out', 'undated', 'hidden', 'duplicate', 'closed',
]

function formatDate(value: string | null) {
  if (!value) return 'Never'
  return new Date(value).toLocaleString('en-HK', {
    timeZone: 'Asia/Hong_Kong', dateStyle: 'medium', timeStyle: 'short',
  })
}

function formatDay(value: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleDateString('en-HK', { timeZone: 'Asia/Hong_Kong', dateStyle: 'medium' })
}

const STATUS_TONE: Record<string, { bg: string; fg: string; border: string }> = {
  approved: { bg: 'var(--color-success-bg)', fg: 'var(--color-success)', border: 'var(--color-success-border)' },
  rejected: { bg: '#FEF2F2', fg: '#991B1B', border: '#FECACA' },
  pending: { bg: '#FFFBEB', fg: '#854D0E', border: '#FDE68A' },
}

function StatusPill({ status }: { status: string }) {
  const tone = STATUS_TONE[status] ?? STATUS_TONE.pending
  return (
    <span
      className="inline-flex min-h-6 items-center rounded-full px-2 text-[11px] font-semibold capitalize"
      style={{ backgroundColor: tone.bg, color: tone.fg, border: `1px solid ${tone.border}` }}
    >
      {status}
    </span>
  )
}

/**
 * How this row was tied to the account. Rendered on EVERY row, including the
 * strong one — a badge that appears only on weak matches would read as a
 * warning about that row rather than as the basis for the whole list.
 */
function MatchBadge({ matchedBy }: { matchedBy: EmployerSubmission['matched_by'] }) {
  const strong = matchedBy === 'email'
  return (
    <span
      className="inline-flex min-h-6 items-center gap-1 rounded-full px-2 text-[11px] font-medium"
      title={strong
        ? 'The submission came from this account’s own verified address.'
        : 'The company name matches but the address does not — a colleague, or another employer of the same name.'}
      style={{
        backgroundColor: 'var(--color-surface-2)',
        color: strong ? 'var(--color-ink)' : 'var(--color-ink-muted)',
        border: '1px solid var(--color-border)',
      }}
    >
      {strong ? <Eye size={11} aria-hidden="true" /> : <EyeOff size={11} aria-hidden="true" />}
      {strong ? 'Their address' : 'Company name only'}
    </span>
  )
}

function StandingGrid({ standing }: { standing: EmployerStanding }) {
  const total = STANDING_ORDER.reduce((sum, key) => sum + standing[key], 0)
  if (total === 0) {
    return (
      <p className="rounded-md p-4 text-sm" style={{ backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink-muted)' }}>
        No Role in the catalogue is attributed to this employer. If they have Roles under a
        different spelling, point the lens at it above.
      </p>
    )
  }
  return (
    <div className="grid grid-cols-2 overflow-hidden rounded-lg sm:grid-cols-4 lg:grid-cols-7" style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
      {STANDING_ORDER.map(key => {
        const { label, detail } = STANDING_COPY[key]
        const value = standing[key]
        const isLive = key === 'on_board'
        return (
          <div key={key} className="min-w-0 border-b border-r p-3 last:border-r-0" style={{ borderColor: 'var(--color-border)' }}>
            <div
              className="text-2xl font-semibold tabular-nums"
              style={{
                fontFamily: 'var(--font-mono)',
                color: isLive && value > 0 ? 'var(--color-success)'
                  : value === 0 ? 'var(--color-ink-muted)' : 'var(--color-ink)',
              }}
            >
              {value.toLocaleString()}
            </div>
            <div className="mt-1.5 text-xs font-semibold" style={{ color: 'var(--color-ink)' }}>{label}</div>
            <div className="mt-1 text-[11px] leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>{detail}</div>
          </div>
        )
      })}
    </div>
  )
}

function SubmissionsTable({ rows }: { rows: EmployerSubmission[] }) {
  if (rows.length === 0) {
    return (
      <p className="flex items-center gap-2 rounded-md p-4 text-sm" style={{ backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink-muted)' }}>
        <Inbox size={15} aria-hidden="true" />
        This Employer has never submitted a Role.
      </p>
    )
  }
  return (
    <div className="overflow-x-auto rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2" tabIndex={0} role="region" aria-label="Submitted Roles" style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface)', outlineColor: 'var(--color-gold)' }}>
      <table className="w-full min-w-[720px] border-collapse text-left text-sm">
        <thead style={{ backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink-muted)' }}>
          <tr>
            {['Role', 'Submitted', 'Status', 'Attributed by', 'Outcome'].map(heading => (
              <th key={heading} scope="col" className="px-4 py-3 text-xs font-semibold">{heading}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(row => (
            <tr key={row.id} className="border-t" style={{ borderColor: 'var(--color-border)' }}>
              <th scope="row" className="px-4 py-3 font-semibold" style={{ color: 'var(--color-ink)' }}>
                {row.title}
                <span className="block text-xs font-normal" style={{ color: 'var(--color-ink-muted)' }}>
                  {row.location || '—'} · {row.employment_type || '—'}
                  {row.salary_range ? ` · ${row.salary_range}` : ''}
                </span>
              </th>
              <td className="px-4 py-3 tabular-nums" style={{ color: 'var(--color-ink-muted)' }}>{formatDay(row.received_at)}</td>
              <td className="px-4 py-3"><StatusPill status={row.status} /></td>
              <td className="px-4 py-3"><MatchBadge matchedBy={row.matched_by} /></td>
              <td className="px-4 py-3 text-xs" style={{ color: 'var(--color-ink-muted)' }}>
                {row.status === 'rejected'
                  ? (row.rejected_reason || 'Rejected, no reason recorded')
                  : row.status === 'approved'
                    ? `Live as direct/${row.approved_source_id ?? '—'}`
                    : 'Waiting in the Verification queue'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function BoardRoles({ activity }: { activity: EmployerActivity }) {
  const { board_roles: roles, standing, board_sample_size: sampleSize } = activity
  if (roles.length === 0) {
    return (
      <p className="flex items-center gap-2 rounded-md p-4 text-sm" style={{ backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink-muted)' }}>
        <CircleSlash size={15} aria-hidden="true" />
        Nothing of this employer’s is on the board right now.
      </p>
    )
  }
  return (
    <>
      <ul className="grid gap-2 sm:grid-cols-2">
        {roles.map(role => (
          <li key={`${role.source}:${role.source_id}`} className="rounded-lg p-3" style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
            <a
              href={`/jobs/${encodeURIComponent(role.source)}/${encodeURIComponent(role.source_id)}`}
              className="inline-flex items-start gap-1.5 text-sm font-semibold no-underline hover:underline"
              style={{ color: 'var(--color-ink)' }}
            >
              {role.title}
              <ExternalLink size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
            </a>
            <p className="mt-1 text-xs" style={{ color: 'var(--color-ink-muted)' }}>
              {role.locations.join(' · ') || 'Location not stated'} · posted {formatDay(role.posted_at)} · {role.source}
            </p>
          </li>
        ))}
      </ul>
      {standing.on_board > sampleSize && (
        <p className="mt-3 text-xs" style={{ color: 'var(--color-ink-muted)' }}>
          Showing the {sampleSize} newest of {standing.on_board.toLocaleString()} on the board. The Job
          editor below searches all of them.
        </p>
      )}
    </>
  )
}


/**
 * Enters the Employer PREVIEW — the other half of this section.
 *
 * The tables below answer "what does this Employer have?" from our side. This
 * answers "what does an Employer see?" from theirs, which no admin could look
 * at before without registering a throwaway company into employers.db.
 *
 * Hidden rather than disabled when unavailable: the only reason an Ultimate
 * Admin cannot enter is that they are ALREADY signed in as a real Employer
 * (see EmployerViewProvider), and in that case there is nothing to preview —
 * they are looking at the real thing.
 */
function EmployerViewLauncher() {
  const { employerView, canUseEmployerView, setEmployerView } = useEmployerView()
  const navigate = useNavigate()

  if (!canUseEmployerView) return null

  return (
    <div
      className="mb-6 flex flex-col gap-3 rounded-lg p-4 sm:flex-row sm:items-center sm:justify-between"
      style={{ backgroundColor: 'var(--color-gold-light)', border: '1px solid var(--color-gold)' }}
    >
      <div className="flex items-start gap-2.5">
        <Eye size={17} className="mt-0.5 shrink-0" style={{ color: 'var(--color-gold)' }} aria-hidden="true" />
        <p className="text-sm leading-relaxed" style={{ color: 'var(--color-ink)' }}>
          <strong>See the site as an Employer.</strong>{' '}
          <span style={{ color: 'var(--color-ink-muted)' }}>
            Turns on the employer-facing nav and Post a role, without an Employer account.
            It is a preview: nothing you do in it acts on any Employer&rsquo;s behalf, and
            submitting is disabled.
          </span>
        </p>
      </div>
      <button
        type="button"
        onClick={() => {
          setEmployerView(!employerView)
          if (!employerView) navigate('/post-a-role')
        }}
        className="min-h-11 shrink-0 cursor-pointer rounded-md px-4 text-sm font-semibold"
        style={{
          backgroundColor: employerView ? 'var(--color-surface)' : 'var(--color-ink)',
          color: employerView ? 'var(--color-ink)' : 'var(--color-ink-inverse)',
          border: '1px solid var(--color-ink)',
        }}
      >
        {employerView ? 'Leave Employer view' : 'Enter Employer view'}
      </button>
    </div>
  )
}

/**
 * Chooses an Employer, then shows their side of FinEx.
 *
 * The account list is handed down from AdminPage rather than fetched again —
 * it is already loaded for the account directory on the same page, and a
 * second copy would be a second thing to keep in step. Only the per-Employer
 * activity is fetched here, and only once one is chosen: the join costs a
 * queue read plus two jobs.db queries, so it is never paid for an admin who
 * scrolled past this section.
 */
export default function EmployerPerspective({ employers }: { employers: AdminEmployerAccount[] }) {
  const [selectedId, setSelectedId] = useState('')
  const [lens, setLens] = useState('')
  const [activity, setActivity] = useState<EmployerActivity | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // The lens is per-Employer, so switching accounts must drop it — carrying
  // "Rival Bank" across to the next Employer would attribute one employer's
  // Roles to another, which is the one mistake this panel exists to avoid.
  useEffect(() => { setLens('') }, [selectedId])

  useEffect(() => {
    if (!selectedId) { setActivity(null); return }
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchEmployerActivity(selectedId, lens)
      .then(result => { if (!cancelled) { setActivity(result); setError(null) } })
      .catch(err => { if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load this Employer.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [selectedId, lens])

  return (
    <div>
      <div className="mb-6 max-w-3xl">
        <p className="text-xs font-semibold uppercase tracking-[0.14em]" style={{ color: 'var(--color-gold)' }}>Ultimate Admin</p>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-display)' }}>
          Employer view
        </h2>
        <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
          One Employer’s side of FinEx: what they submitted, what we did with it, and which of
          their Roles a visitor can actually open. An Employer has no dashboard of their own, so
          this is the only place that answer exists.
        </p>
      </div>

      <EmployerViewLauncher />

      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="flex-1">
          <span className="mb-1.5 block text-xs font-semibold" style={{ color: 'var(--color-ink)' }}>Employer</span>
          <select
            value={selectedId}
            onChange={e => setSelectedId(e.target.value)}
            className="min-h-11 w-full rounded-md px-3 text-sm"
            style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border-strong)', color: 'var(--color-ink)' }}
          >
            <option value="">Choose an Employer account…</option>
            {employers.map(employer => (
              <option key={employer.id} value={employer.id}>
                {employer.company_name} — {employer.email}
              </option>
            ))}
          </select>
        </label>
        <label className="flex-1">
          <span className="mb-1.5 block text-xs font-semibold" style={{ color: 'var(--color-ink)' }}>
            Attribute Roles by company name
          </span>
          <span className="relative block">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--color-ink-muted)' }} aria-hidden="true" />
            <input
              type="search"
              value={lens}
              disabled={!selectedId}
              onChange={e => setLens(e.target.value)}
              placeholder={activity?.employer.company_name || 'The account’s own name'}
              aria-label="Override the company name Roles are attributed by"
              className="min-h-11 w-full rounded-md py-2 pl-9 pr-3 text-sm disabled:opacity-60"
              style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border-strong)', color: 'var(--color-ink)' }}
            />
          </span>
        </label>
      </div>

      {!selectedId ? (
        <p className="flex items-center gap-2 rounded-lg p-5 text-sm" role="status" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', color: 'var(--color-ink-muted)' }}>
          <Building2 size={16} aria-hidden="true" />
          Choose an Employer to see their perspective. {employers.length.toLocaleString()} account
          {employers.length === 1 ? '' : 's'} registered.
        </p>
      ) : error ? (
        <div className="rounded-lg p-5 text-sm" role="alert" style={{ backgroundColor: '#FEF2F2', border: '1px solid #FECACA', color: '#991B1B' }}>
          {error}
        </div>
      ) : !activity ? (
        <p className="rounded-lg p-5 text-sm" role="status" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', color: 'var(--color-ink-muted)' }}>
          Loading this Employer’s activity…
        </p>
      ) : (
        <div className="space-y-8" aria-busy={loading}>
          <div className="rounded-lg p-5" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <h3 className="text-lg font-semibold" style={{ color: 'var(--color-ink)' }}>{activity.employer.company_name}</h3>
            <p className="mt-1 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
              {activity.employer.contact_name ? `${activity.employer.contact_name} · ` : ''}
              {activity.employer.email}
              {activity.employer.email_verified ? ' · verified' : ' · not verified'}
            </p>
            <p className="mt-1 text-xs" style={{ color: 'var(--color-ink-muted)' }}>
              Registered {formatDate(activity.employer.created_at)} · last signed in {formatDate(activity.employer.last_login_at)}
            </p>
            <p className="mt-3 text-xs leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
              {activity.lens.matched_spellings.length > 0
                ? <>Roles attributed to <strong style={{ color: 'var(--color-ink)' }}>{activity.lens.matched_spellings.join(', ')}</strong> in the catalogue.</>
                : <>No company in the catalogue is spelled “{activity.lens.company}”. Try the board’s own spelling above.</>}
              {activity.lens.overridden && ' The lens was moved off this account’s registered name.'}
            </p>
          </div>

          <section aria-labelledby="employer-standing-heading">
            <h3 id="employer-standing-heading" className="mb-3 text-lg font-semibold" style={{ color: 'var(--color-ink)' }}>
              Where their Roles stand
            </h3>
            <StandingGrid standing={activity.standing} />
          </section>

          <section aria-labelledby="employer-submissions-heading">
            <h3 id="employer-submissions-heading" className="mb-3 text-lg font-semibold" style={{ color: 'var(--color-ink)' }}>
              What they submitted
            </h3>
            <SubmissionsTable rows={activity.submissions} />
          </section>

          <section aria-labelledby="employer-board-heading">
            <h3 id="employer-board-heading" className="mb-3 text-lg font-semibold" style={{ color: 'var(--color-ink)' }}>
              What a visitor can open
            </h3>
            <BoardRoles activity={activity} />
          </section>
        </div>
      )}
    </div>
  )
}
