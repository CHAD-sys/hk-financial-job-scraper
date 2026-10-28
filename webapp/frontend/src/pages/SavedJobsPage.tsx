import { useCallback, useEffect, useState } from 'react'
import { Bookmark, ArrowLeft } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import type { ApplicationProgress, ApplicationStatus, Job } from '../api/client'
import { fetchApplicationProgress, recordApplicationClick, updateApplicationStatus } from '../api/client'
import { useAuth } from '../auth/useAuth'
import { useSavedRoles } from '../savedRoles/useSavedRoles'
import Nav from '../components/Nav'
import JobCard from '../components/JobCard'
import JobDetailModal from '../components/JobDetailModal'

export default function SavedJobsPage() {
  const navigate = useNavigate()
  const { seeker, loading: authLoading } = useAuth()
  const { savedList, toggle, isSaved, count } = useSavedRoles()
  const [selectedJob, setSelectedJob] = useState<Job | null>(null)
  const [progressByRole, setProgressByRole] = useState<Record<string, ApplicationProgress>>({})
  const [progressError, setProgressError] = useState('')

  useEffect(() => {
    if (authLoading || !seeker) {
      setProgressByRole({})
      return
    }
    let cancelled = false
    fetchApplicationProgress()
      .then(rows => {
        if (!cancelled) {
          setProgressByRole(Object.fromEntries(rows.map(row => [`${row.source}__${row.source_id}`, row])))
        }
      })
      .catch(() => {
        if (!cancelled) setProgressError('Application progress could not be loaded. Please refresh to try again.')
      })
    return () => { cancelled = true }
  }, [authLoading, seeker])

  const saveApplicationStatus = useCallback(async (job: Job, status: ApplicationStatus | null) => {
    const key = `${job.source}__${job.source_id}`
    const previous = progressByRole[key]
    setProgressError('')
    setProgressByRole(current => ({
      ...current,
      [key]: {
        source: job.source,
        source_id: job.source_id,
        status,
        status_updated_at: status ? new Date().toISOString() : null,
        apply_click_count: previous?.apply_click_count ?? 0,
        last_apply_clicked_at: previous?.last_apply_clicked_at ?? null,
      },
    }))
    try {
      const updated = await updateApplicationStatus(job, status)
      setProgressByRole(current => ({ ...current, [key]: updated }))
    } catch {
      setProgressByRole(current => {
        const next = { ...current }
        if (previous) next[key] = previous
        else delete next[key]
        return next
      })
      setProgressError('That update did not save. Please try again.')
    }
  }, [progressByRole])

  const noteApplicationClick = useCallback((job: Job) => {
    if (!seeker) return
    void recordApplicationClick(job)
      .then(() => {
        const key = `${job.source}__${job.source_id}`
        setProgressByRole(current => {
          const previous = current[key]
          return {
            ...current,
            [key]: {
              source: job.source,
              source_id: job.source_id,
              status: previous?.status ?? null,
              status_updated_at: previous?.status_updated_at ?? null,
              apply_click_count: (previous?.apply_click_count ?? 0) + 1,
              last_apply_clicked_at: new Date().toISOString(),
            },
          }
        })
      })
      .catch(() => {})
  }, [seeker])

  return (
    <div style={{ backgroundColor: 'var(--color-bg)', minHeight: '100dvh' }}>
      <Nav />

      {/* Header */}
      <section
        style={{
          backgroundColor: 'var(--color-masthead)',
          borderBottom: '1px solid rgba(255,255,255,0.08)',
        }}
      >
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8">
          <button type="button"
            onClick={() => navigate('/jobs')}
            className="flex items-center gap-1.5 text-sm mb-4 cursor-pointer transition-colors duration-150"
            style={{ color: 'rgba(248,250,252,0.5)' }}
            onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink-inverse)')}
            onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.color = 'rgba(248,250,252,0.5)')}
          >
            <ArrowLeft size={14} /> Back to Role search
          </button>
          <div className="flex items-center gap-3">
            <Bookmark size={22} style={{ color: 'var(--color-gold)' }} fill="currentColor" />
            <h1
              className="text-2xl font-bold"
              style={{
                fontFamily: 'var(--font-display)',
                color: 'var(--color-ink-inverse)',
                letterSpacing: '-0.02em',
              }}
            >
              Saved Roles
            </h1>
            <span
              className="text-sm tabular-nums px-2 py-0.5 rounded"
              style={{
                fontFamily: 'var(--font-mono)',
                backgroundColor: 'rgba(255,255,255,0.1)',
                color: 'rgba(248,250,252,0.7)',
              }}
            >
              {count}
            </span>
          </div>
        </div>
      </section>

      <main className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8">
        {!authLoading && !seeker && savedList.length > 0 && (
          <p className="mb-5 rounded-md border px-4 py-3 text-sm" style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-ink-muted)' }}>
            Sign in to track application progress across your devices.{' '}
            <Link to={`/signin?returnTo=${encodeURIComponent('/saved')}`} style={{ color: 'var(--color-blue)', fontWeight: 600 }}>
              Sign in
            </Link>
          </p>
        )}
        {progressError && <p className="mb-4 text-sm" role="status" style={{ color: 'var(--color-destructive)' }}>{progressError}</p>}
        {savedList.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <div
              className="flex h-16 w-16 items-center justify-center rounded-full mb-5"
              style={{ backgroundColor: 'var(--color-surface-2)', border: '1px solid var(--color-border)' }}
            >
              <Bookmark size={28} style={{ color: 'var(--color-ink-faint)' }} strokeWidth={1.5} />
            </div>
            <h2
              className="text-xl font-semibold mb-2"
              style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)' }}
            >
              No saved roles yet
            </h2>
            <p className="text-sm mb-6 max-w-sm" style={{ color: 'var(--color-ink-muted)' }}>
              Bookmark roles from the job board and they'll appear here for easy comparison.
            </p>
            <button type="button"
              onClick={() => navigate('/jobs')}
              className="inline-flex items-center gap-2 rounded px-5 py-2.5 text-sm font-medium transition-colors duration-150 cursor-pointer"
              style={{ backgroundColor: 'var(--color-ink)', color: 'var(--color-ink-inverse)' }}
              onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--color-blue)')}
              onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--color-ink)')}
            >
              Search Roles
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {savedList.map(job => (
              <JobCard
                key={`${job.source}__${job.source_id}`}
                job={job}
                saved={isSaved(job)}
                onToggleSave={toggle}
                onClick={setSelectedJob}
                applicationProgress={progressByRole[`${job.source}__${job.source_id}`]}
                onApplicationStatusChange={seeker ? saveApplicationStatus : undefined}
              />
            ))}
          </div>
        )}
      </main>

      {selectedJob && (
        <JobDetailModal
          job={selectedJob}
          saved={isSaved(selectedJob)}
          onToggleSave={toggle}
          onClose={() => setSelectedJob(null)}
          onApplyClick={noteApplicationClick}
        />
      )}
    </div>
  )
}
