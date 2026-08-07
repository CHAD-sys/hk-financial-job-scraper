import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react'
import type { Job, RecommendationsResponse } from '../api/client'
import {
  fetchRecommendations,
  trackRecommendationClick,
} from '../api/client'
import { useAuth } from '../auth/useAuth'
import JobCard from './JobCard'
import SkeletonCard from './SkeletonCard'

const PAGE_SIZE = 6

interface Props {
  saved: (job: Job) => boolean
  onToggleSave: (job: Job) => void
  onSelect: (job: Job) => void
  onExploreAll: () => void
}

/**
 * A first-party, explainable recommendation surface.
 *
 * Signed-in Seekers are ranked from their Saved Roles and settled searches /
 * filters. Anonymous visitors get the same component with an explicitly
 * labelled market fallback; we never imply personalization we do not have.
 */
export default function RecommendedRoles({
  saved,
  onToggleSave,
  onSelect,
  onExploreAll,
}: Props) {
  const { seeker, loading: authLoading } = useAuth()
  const [feed, setFeed] = useState<RecommendationsResponse | null>(null)
  const [page, setPage] = useState(1)
  const [nonce, setNonce] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    if (authLoading) return

    let cancelled = false
    setLoading(true)
    setError(false)

    fetchRecommendations(page, PAGE_SIZE)
      .then(response => {
        if (!cancelled) setFeed(response)
      })
      .catch(err => {
        console.error(err)
        if (!cancelled) setError(true)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [authLoading, seeker?.id, page, nonce])

  const showOthers = useCallback(() => {
    const totalPages = Math.max(1, feed?.total_pages ?? 1)
    const nextPage = page >= totalPages ? 1 : page + 1
    if (nextPage === page) setNonce(value => value + 1)
    else setPage(nextPage)
  }, [feed?.total_pages, page])

  const openRole = useCallback((job: Job) => {
    if (seeker) {
      trackRecommendationClick(job.source, job.source_id).catch(console.error)
    }
    onSelect(job)
  }, [onSelect, seeker])

  const activityCount = feed?.activity_count ?? 0
  const savedCount = feed?.saved_role_count ?? 0

  return (
    <section className="mb-10 sm:mb-14" aria-labelledby="roles-for-you-heading">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-3xl">
          <div className="mb-1.5 flex items-center gap-2">
            <Sparkles
              size={17}
              strokeWidth={2.25}
              style={{ color: 'var(--color-gold)' }}
              aria-hidden="true"
            />
            <h2
              id="roles-for-you-heading"
              className="text-xl font-bold sm:text-2xl"
              style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)' }}
            >
              Roles for you
            </h2>
          </div>
          <RecommendationContext
            signedIn={Boolean(seeker)}
            personalized={Boolean(feed?.personalized)}
            savedCount={savedCount}
            activityCount={activityCount}
          />
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={showOthers}
            disabled={loading || error}
            className="filter-pill inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded-md px-3.5 text-xs font-semibold outline-none"
            style={{
              border: '1px solid var(--color-border-strong)',
              backgroundColor: 'var(--color-surface)',
              color: 'var(--color-ink-muted)',
              opacity: loading || error ? 0.5 : 1,
            }}
          >
            <RefreshCw
              size={14}
              strokeWidth={2.25}
              className={loading ? 'animate-spin' : undefined}
              aria-hidden="true"
            />
            Show me others
          </button>
          <button
            type="button"
            onClick={onExploreAll}
            className="inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded-md px-3.5 text-xs font-semibold outline-none"
            style={{ color: 'var(--color-ink)' }}
          >
            Explore all Roles
            <ArrowRight size={14} strokeWidth={2.25} aria-hidden="true" />
          </button>
        </div>
      </div>

      {error ? (
        <div
          className="rounded-xl px-5 py-8 text-center"
          style={{
            border: '1px solid var(--color-border)',
            backgroundColor: 'var(--color-surface)',
          }}
          role="status"
        >
          <p className="text-sm font-semibold" style={{ color: 'var(--color-ink)' }}>
            We could not load your recommendations.
          </p>
          <button
            type="button"
            onClick={() => setNonce(value => value + 1)}
            className="mt-3 min-h-11 cursor-pointer text-sm font-semibold"
            style={{ color: 'var(--color-link)' }}
          >
            Try again
          </button>
        </div>
      ) : loading || !feed ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-label="Loading recommended Roles">
          {Array.from({ length: PAGE_SIZE }).map((_, index) => <SkeletonCard key={index} />)}
        </div>
      ) : feed.items.length === 0 ? (
        <div
          className="rounded-xl px-5 py-8 text-center"
          style={{
            border: '1px solid var(--color-border)',
            backgroundColor: 'var(--color-surface)',
          }}
        >
          <p className="text-sm" style={{ color: 'var(--color-ink-muted)' }}>
            No open Roles are available for this page right now.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-live="polite">
          {feed.items.map(item => (
            <div key={`${item.job.source}__${item.job.source_id}`} className="flex min-w-0 flex-col gap-2">
              <div
                className="flex min-h-9 items-start gap-2 rounded-md px-3 py-2 text-xs"
                style={{
                  backgroundColor: 'var(--color-surface-2)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-ink-muted)',
                }}
              >
                <Sparkles
                  size={13}
                  strokeWidth={2.25}
                  className="mt-0.5 shrink-0"
                  style={{ color: 'var(--color-gold)' }}
                  aria-hidden="true"
                />
                <span className="min-w-0 leading-relaxed">
                  <span className="font-semibold" style={{ color: 'var(--color-ink)' }}>
                    {feed.personalized ? 'Why it fits' : 'Market signal'}
                  </span>
                  {' · '}{item.reasons.join(' · ')}
                </span>
              </div>
              <JobCard
                job={item.job}
                saved={saved(item.job)}
                onToggleSave={onToggleSave}
                onClick={openRole}
              />
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function RecommendationContext({
  signedIn,
  personalized,
  savedCount,
  activityCount,
}: {
  signedIn: boolean
  personalized: boolean
  savedCount: number
  activityCount: number
}) {
  if (!signedIn) {
    return (
      <p className="text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
        A fresh cross-section of the market.{' '}
        <Link to="/signin?next=/jobs" className="font-semibold underline-offset-2 hover:underline">
          Sign in to shape this with Saved Roles and searches.
        </Link>
      </p>
    )
  }

  if (!personalized) {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p className="text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
          Save a Role or use filters to sharpen this feed. For now, these are fresh market Roles.
          {' '}Settled choices—not keystrokes—stay with your account.
        </p>
        <PrivateLabel />
      </div>
    )
  }

  const savedLabel = `${savedCount} Saved Role${savedCount === 1 ? '' : 's'}`
  const activityLabel = `${activityCount} recent search/filter choice${activityCount === 1 ? '' : 's'}`
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <p className="text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
        Built from {savedLabel} and {activityLabel}. Settled choices—not keystrokes—stay
        with your account.
      </p>
      <PrivateLabel />
    </div>
  )
}

function PrivateLabel() {
  return (
    <span
      className="inline-flex items-center gap-1 text-xs font-semibold"
      style={{ color: 'var(--color-ink-muted)' }}
    >
      <ShieldCheck size={13} strokeWidth={2.25} aria-hidden="true" />
      Private to your account
    </span>
  )
}
