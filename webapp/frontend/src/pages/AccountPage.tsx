import { useState } from 'react'
import { AlertCircle, BadgeCheck, Bookmark, LogOut, ShieldAlert, Trash2 } from 'lucide-react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import Nav from '../components/Nav'
import { deleteAccount } from '../api/client'
import { useAuth } from '../auth/useAuth'
import { useSavedJobs } from '../hooks/useSavedJobs'

type DeleteStage = 'idle' | 'confirming' | 'deleting' | 'error'

// Typed by hand, not a checkbox. Deletion is irreversible and a checkbox is one
// mis-aimed tap away from being ticked.
const CONFIRM_WORD = 'DELETE'

/**
 * The Seeker's own account: what we hold, and how to leave.
 *
 * There is very little here on purpose. v1 stores an email address, a name, a
 * password hash and a list of Saved Roles — so this page shows exactly that and
 * does not invent settings for features that do not exist.
 */
export default function AccountPage() {
  const { seeker, loading, logout, refresh } = useAuth()
  const navigate = useNavigate()
  const { count } = useSavedJobs()
  const [stage, setStage] = useState<DeleteStage>('idle')
  const [confirmText, setConfirmText] = useState('')
  const [error, setError] = useState('')

  // Not a gate on the board — this page is simply about an account, so without
  // one there is nothing to render.
  if (!loading && !seeker) return <Navigate to="/signin" state={{ from: '/account' }} replace />

  async function handleSignOut() {
    await logout()
    navigate('/')
  }

  async function handleDelete() {
    if (confirmText.trim() !== CONFIRM_WORD) {
      setStage('error')
      setError(`Type ${CONFIRM_WORD} to confirm.`)
      return
    }
    setStage('deleting')
    setError('')
    try {
      await deleteAccount()
      await refresh() // the session is revoked; this settles the UI on "signed out"
      navigate('/', { replace: true })
    } catch (err) {
      setStage('error')
      setError(
        err instanceof Error && err.message
          ? err.message
          : 'Your account could not be deleted. Please try again.',
      )
    }
  }

  return (
    <div style={{ backgroundColor: 'var(--color-bg)', minHeight: '100dvh' }}>
      <Nav savedCount={count} />
      <main id="main-content" className="mx-auto max-w-2xl px-6 py-14 lg:px-8">
        <span
          className="text-xs font-semibold uppercase"
          style={{ color: 'var(--color-gold)', letterSpacing: '0.14em' }}
        >
          Seeker account
        </span>
        <h1
          className="mt-3 text-3xl lg:text-4xl tracking-tight"
          style={{
            fontFamily: 'var(--font-display)',
            fontWeight: 700,
            color: 'var(--color-ink)',
            letterSpacing: '-0.025em',
          }}
        >
          Your account
        </h1>

        {loading || !seeker ? (
          <p className="mt-6 text-sm" style={{ color: 'var(--color-ink-muted)' }} role="status">
            Loading…
          </p>
        ) : (
          <>
            {/* What we hold */}
            <section
              className="mt-8 rounded-xl p-6 lg:p-8"
              style={{
                backgroundColor: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
                boxShadow: 'var(--shadow-card)',
              }}
            >
              <Legend>Details</Legend>

              <Row label="Name" value={seeker.display_name || '—'} />
              <Row label="Email" value={seeker.email} />

              <div className="mt-5">
                <FieldLabel>Email status</FieldLabel>
                {seeker.email_verified ? (
                  <p className="mt-1 flex items-center gap-1.5 text-sm" style={{ color: 'var(--color-ink)' }}>
                    <BadgeCheck size={16} strokeWidth={2} style={{ color: 'var(--color-gold)' }} />
                    Verified
                  </p>
                ) : (
                  <>
                    <p className="mt-1 flex items-center gap-1.5 text-sm" style={{ color: 'var(--color-ink)' }}>
                      <AlertCircle size={16} strokeWidth={2} style={{ color: 'var(--color-ink-faint)' }} />
                      Not verified yet
                    </p>
                    <p className="mt-1.5 text-xs" style={{ color: 'var(--color-ink-faint)' }}>
                      Your account works exactly the same either way. Verifying only confirms we
                      can reach you before we ever send anything to this address.
                    </p>
                  </>
                )}
              </div>

              <div className="mt-5">
                <FieldLabel>Saved Roles</FieldLabel>
                <p className="mt-1 text-sm" style={{ color: 'var(--color-ink)' }}>
                  <Link
                    to="/saved"
                    className="inline-flex items-center gap-1.5"
                    style={{ color: 'var(--color-blue)', fontWeight: 500 }}
                  >
                    <Bookmark size={14} strokeWidth={2} />
                    {count === 1 ? '1 Saved Role' : `${count} Saved Roles`}
                  </Link>
                </p>
              </div>

              <button
                type="button"
                onClick={handleSignOut}
                className="mt-7 inline-flex min-h-11 items-center justify-center gap-2 rounded px-5 py-2.5 text-sm font-semibold cursor-pointer"
                style={{
                  backgroundColor: 'var(--color-ink)',
                  color: 'var(--color-ink-inverse)',
                }}
              >
                <LogOut size={15} strokeWidth={2} />
                Sign out
              </button>
            </section>

            {/* Deletion. Real deletion — see docs/adr/0007. */}
            <section
              className="mt-8 rounded-xl p-6 lg:p-8"
              style={{
                backgroundColor: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
                boxShadow: 'var(--shadow-card)',
              }}
            >
              <Legend>Delete account</Legend>

              <p className="text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
                Deleting your account removes your name, email address, password and Saved
                Roles from our records and signs you out everywhere. <strong style={{ color: 'var(--color-ink)' }}>
                This is permanent — there is no undo and we cannot restore it for you.</strong>{' '}
                The board itself stays open to you afterwards; you simply browse it without an
                account, and Saved Roles go back to living in this browser.
              </p>

              {stage === 'idle' ? (
                <button
                  type="button"
                  onClick={() => { setStage('confirming'); setConfirmText(''); setError('') }}
                  className="mt-6 inline-flex min-h-11 items-center justify-center gap-2 rounded px-5 py-2.5 text-sm font-semibold cursor-pointer"
                  style={{
                    backgroundColor: 'var(--color-surface)',
                    color: 'var(--color-destructive)',
                    border: '1px solid var(--color-destructive)',
                  }}
                >
                  <Trash2 size={15} strokeWidth={2} />
                  Delete my account
                </button>
              ) : (
                <div
                  className="mt-6 rounded-lg p-4"
                  style={{
                    backgroundColor: 'var(--color-surface-2)',
                    border: '1px solid var(--color-destructive)',
                  }}
                >
                  <p className="flex items-start gap-2 text-sm" style={{ color: 'var(--color-ink)' }}>
                    <ShieldAlert size={18} strokeWidth={2} className="mt-0.5 shrink-0" style={{ color: 'var(--color-destructive)' }} />
                    <span>
                      Last step. Type <strong>{CONFIRM_WORD}</strong> below to confirm you want
                      your account and everything in it gone for good.
                    </span>
                  </p>

                  <label
                    htmlFor="ac-confirm"
                    className="mt-4 mb-1.5 block text-xs font-semibold uppercase"
                    style={{ color: 'var(--color-ink-muted)', letterSpacing: '0.1em' }}
                  >
                    Type {CONFIRM_WORD} to confirm
                  </label>
                  <input
                    id="ac-confirm"
                    type="text"
                    value={confirmText}
                    onChange={e => setConfirmText(e.target.value)}
                    autoComplete="off"
                    autoCapitalize="characters"
                    spellCheck={false}
                    className="finex-input"
                    style={{ fontFamily: 'var(--font-mono)' }}
                  />

                  {stage === 'error' && (
                    <p
                      className="mt-4 flex items-start gap-2 text-sm"
                      style={{ color: 'var(--color-destructive)' }}
                      role="alert"
                    >
                      <AlertCircle size={16} strokeWidth={2} className="mt-0.5 shrink-0" />
                      {error}
                    </p>
                  )}

                  <div className="mt-5 flex flex-wrap gap-3">
                    <button
                      type="button"
                      onClick={handleDelete}
                      disabled={stage === 'deleting' || confirmText.trim() !== CONFIRM_WORD}
                      className="inline-flex min-h-11 items-center justify-center gap-2 rounded px-5 py-2.5 text-sm font-semibold"
                      style={{
                        backgroundColor: 'var(--color-destructive)',
                        color: 'var(--color-ink-inverse)',
                        cursor: stage === 'deleting' ? 'wait' : 'pointer',
                        opacity: stage === 'deleting' || confirmText.trim() !== CONFIRM_WORD ? 0.55 : 1,
                      }}
                    >
                      <Trash2 size={15} strokeWidth={2} />
                      {stage === 'deleting' ? 'Deleting…' : 'Permanently delete'}
                    </button>
                    <button
                      type="button"
                      onClick={() => { setStage('idle'); setConfirmText(''); setError('') }}
                      disabled={stage === 'deleting'}
                      className="inline-flex min-h-11 items-center justify-center rounded px-5 py-2.5 text-sm font-semibold cursor-pointer"
                      style={{
                        backgroundColor: 'var(--color-surface)',
                        color: 'var(--color-ink)',
                        border: '1px solid var(--color-border-strong)',
                      }}
                    >
                      Keep my account
                    </button>
                  </div>
                </div>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  )
}

function Legend({ children }: { children: React.ReactNode }) {
  return (
    <h2
      className="mb-5 pb-2 text-xs font-semibold uppercase"
      style={{
        color: 'var(--color-ink-faint)',
        letterSpacing: '0.14em',
        borderBottom: '1px solid var(--color-border)',
      }}
    >
      {children}
    </h2>
  )
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="block text-xs font-semibold uppercase"
      style={{ color: 'var(--color-ink-muted)', letterSpacing: '0.1em' }}
    >
      {children}
    </span>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="mt-5 first:mt-0">
      <FieldLabel>{label}</FieldLabel>
      <p className="mt-1 text-sm break-words" style={{ color: 'var(--color-ink)' }}>{value}</p>
    </div>
  )
}
