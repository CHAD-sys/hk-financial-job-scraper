import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  BadgeCheck,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Undo2,
  X,
} from 'lucide-react'
import type {
  Job,
  RecommendedRole,
  RecommendationsResponse,
  ResumeMatchesResponse,
} from '../api/client'
import {
  fetchRecommendations,
  removeRecommendationFeedback,
  submitRecommendationFeedback,
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
  resumeMatches?: ResumeMatchesResponse | null
}

interface ToastState {
  message: string
  undo?: () => Promise<void>
}

const roleKey = (job: Job) => `${job.source}__${job.source_id}`

/** First-party recommendations shaped by settled activity and direct feedback. */
export default function RecommendedRoles({
  saved,
  onToggleSave,
  onSelect,
  resumeMatches = null,
}: Props) {
  const { seeker, loading: authLoading } = useAuth()
  const seekerId = seeker?.id
  const [feed, setFeed] = useState<RecommendationsResponse | null>(null)
  const [page, setPage] = useState(1)
  const [nonce, setNonce] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [pendingRef, setPendingRef] = useState<string | null>(null)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [undoing, setUndoing] = useState(false)

  useEffect(() => {
    if (authLoading) return
    if (!seekerId) {
      setFeed(null)
      setLoading(false)
      return
    }
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
  }, [authLoading, seekerId, page, nonce])

  useEffect(() => {
    if (!toast) return
    const id = window.setTimeout(() => setToast(null), 7_000)
    return () => window.clearTimeout(id)
  }, [toast])

  const refreshFeed = useCallback(() => {
    setPage(1)
    setNonce(value => value + 1)
  }, [])

  const showOthers = useCallback(() => {
    const totalPages = Math.max(1, feed?.total_pages ?? 1)
    const nextPage = page >= totalPages ? 1 : page + 1
    if (nextPage === page) setNonce(value => value + 1)
    else setPage(nextPage)
  }, [feed?.total_pages, page])

  const openRole = useCallback((job: Job) => {
    if (seekerId) {
      trackRecommendationClick(job.source, job.source_id, job.access_token).catch(console.error)
    }
    onSelect(job)
  }, [onSelect, seekerId])

  const setMoreLikeFeedback = useCallback((job: Job, active: boolean) => {
    setFeed(current => {
      if (!current) return current
      return {
        ...current,
        items: current.items.map(item => {
          if (roleKey(item.job) !== roleKey(job)) return item
          const previous = item.feedback ?? []
          const withoutOpposite = previous.filter(value => value !== 'not_interested')
          return {
            ...item,
            feedback: active
              ? [...withoutOpposite.filter(value => value !== 'more_like'), 'more_like']
              : withoutOpposite.filter(value => value !== 'more_like'),
          }
        }),
      }
    })
  }, [])

  const moreLike = async (item: RecommendedRole) => {
    const key = roleKey(item.job)
    const active = (item.feedback ?? []).includes('more_like')
    setPendingRef(key)
    try {
      if (active) {
        await removeRecommendationFeedback(item.job.source, item.job.source_id, 'more_like')
        setMoreLikeFeedback(item.job, false)
        setToast({ message: 'This Role is no longer shaping your recommendations.' })
      } else {
        await submitRecommendationFeedback(
          item.job.source,
          item.job.source_id,
          'more_like',
          item.job.access_token,
        )
        setMoreLikeFeedback(item.job, true)
        setToast({ message: 'We’ll show you more Roles like this.' })
      }
    } catch {
      setToast({ message: 'That preference did not save. Please try again.' })
    } finally {
      setPendingRef(null)
    }
  }

  const dismissRole = async (item: RecommendedRole) => {
    const key = roleKey(item.job)
    setPendingRef(key)
    try {
      await submitRecommendationFeedback(
        item.job.source,
        item.job.source_id,
        'not_interested',
        item.job.access_token,
      )
      setFeed(current => current
        ? { ...current, items: current.items.filter(value => roleKey(value.job) !== key) }
        : current)
      setToast({
        message: 'This Role will no longer appear in your recommendations.',
        undo: async () => {
          await removeRecommendationFeedback(
            item.job.source,
            item.job.source_id,
            'not_interested',
          )
          refreshFeed()
        },
      })
    } catch {
      setToast({ message: 'We could not hide that Role. Please try again.' })
    } finally {
      setPendingRef(null)
    }
  }

  const undo = async () => {
    if (!toast?.undo) return
    setUndoing(true)
    try {
      await toast.undo()
      setToast({ message: 'Your previous choice was restored.' })
    } catch {
      setToast({ message: 'We could not undo that choice. Please try again.' })
    } finally {
      setUndoing(false)
    }
  }

  if (!authLoading && !seeker) return null

  const experienceMatches = resumeMatches?.has_resume ? resumeMatches.items : []
  const experienceRefs = new Set(experienceMatches.map(item => roleKey(item.job)))
  const recommendedItems = (feed?.items ?? []).filter(
    item => !experienceRefs.has(roleKey(item.job)),
  )
  const hasResume = Boolean(resumeMatches?.has_resume)
  const hasRoles = experienceMatches.length > 0 || recommendedItems.length > 0

  return (
    <section className="mb-10 sm:mb-14" aria-labelledby="roles-for-you-heading">
      <div className="recommendation-heading mb-5">
        <div className="max-w-3xl">
          <div className="mb-1.5 flex items-center gap-2">
            <Sparkles size={17} strokeWidth={2.25} style={{ color: 'var(--color-gold)' }} aria-hidden="true" />
            <h2 id="roles-for-you-heading" className="text-xl font-bold sm:text-2xl" style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)' }}>
              Roles for you
            </h2>
          </div>
          <RecommendationContext
            loading={loading || !feed}
            personalized={Boolean(feed?.personalized)}
            hasResume={hasResume}
          />
        </div>

        <div className="recommendation-heading__actions">
          {hasResume && <Link to="/account" className="recommendation-manage-link">Manage resume</Link>}
          <button
            type="button"
            onClick={showOthers}
            disabled={loading || error}
            className="recommendation-action-button"
          >
            <RefreshCw size={14} strokeWidth={2.25} className={loading ? 'animate-spin' : undefined} aria-hidden="true" />
            Show me others
          </button>
        </div>
      </div>

      {error ? (
        <FeedMessage>
          <p className="text-sm font-semibold" style={{ color: 'var(--color-ink)' }}>We could not load your recommendations.</p>
          <button type="button" onClick={() => setNonce(value => value + 1)} className="mt-3 min-h-11 cursor-pointer text-sm font-semibold" style={{ color: 'var(--color-blue)' }}>
            Try again
          </button>
        </FeedMessage>
      ) : loading || !feed ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-label="Loading recommended Roles">
          {Array.from({ length: PAGE_SIZE }).map((_, index) => <SkeletonCard key={index} />)}
        </div>
      ) : !hasRoles ? (
        <FeedMessage>
          <p className="text-sm" style={{ color: 'var(--color-ink-muted)' }}>
            Start with a search above, save a relevant Role, or upload your resume to build this feed.
          </p>
          <button type="button" onClick={showOthers} className="recommendation-primary-button mt-4">
            <RefreshCw size={15} aria-hidden="true" /> Show me others
          </button>
        </FeedMessage>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-live="polite">
          {experienceMatches.map(item => (
            <article key={`resume__${roleKey(item.job)}`} className="resume-match-card">
              <JobCard
                job={item.job}
                saved={saved(item.job)}
                onToggleSave={onToggleSave}
                onClick={onSelect}
              />
              <p className="resume-match-card__reason">
                <BadgeCheck size={14} className="shrink-0" aria-hidden="true" />
                <strong>{item.match_score}%</strong>
                {item.reasons[0] || 'Relevant experience found in your resume'}
              </p>
            </article>
          ))}
          {recommendedItems.map(item => {
            const key = roleKey(item.job)
            const moreLikeActive = (item.feedback ?? []).includes('more_like')
            const isPending = pendingRef === key
            return (
              <article key={key} className="recommendation-card-shell">
                <JobCard
                  job={item.job}
                  saved={saved(item.job)}
                  onToggleSave={onToggleSave}
                  onClick={openRole}
                />
                {seeker && (
                  <div className="recommendation-feedback" aria-label="Recommendation feedback">
                    <button
                      type="button"
                      className="recommendation-feedback__button"
                      aria-pressed={moreLikeActive}
                      disabled={isPending}
                      onClick={() => moreLike(item)}
                    >
                      {isPending
                        ? <LoaderCircle size={14} className="animate-spin" aria-hidden="true" />
                        : <ThumbsUp size={14} aria-hidden="true" />}
                      More like this
                    </button>
                    <button
                      type="button"
                      className="recommendation-feedback__button"
                      disabled={isPending}
                      onClick={() => dismissRole(item)}
                    >
                      <ThumbsDown size={14} aria-hidden="true" />
                      Not for me
                    </button>
                  </div>
                )}
              </article>
            )
          })}
        </div>
      )}

      {toast && (
        <div className="recommendation-toast" role="status" aria-live="polite">
          <span className="min-w-0 flex-1">{toast.message}</span>
          {toast.undo && (
            <button type="button" onClick={undo} disabled={undoing} aria-label="Undo">
              {undoing ? <LoaderCircle size={14} className="animate-spin" /> : <Undo2 size={14} />}
              Undo
            </button>
          )}
          <button type="button" onClick={() => setToast(null)} aria-label="Dismiss message" className="recommendation-toast__close">
            <X size={15} />
          </button>
        </div>
      )}
    </section>
  )
}

function FeedMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl px-5 py-8 text-center" style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface)' }} role="status">
      {children}
    </div>
  )
}

function RecommendationContext({
  loading,
  personalized,
  hasResume,
}: {
  loading: boolean
  personalized: boolean
  hasResume: boolean
}) {
  if (loading) {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p className="text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
          Preparing Roles for you.
        </p>
        <PrivateLabel />
      </div>
    )
  }

  if (!personalized) {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p className="text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
          Run a search, save a relevant Role, or upload your resume to build this feed. Settled choices—not keystrokes—stay with your account.
        </p>
        <PrivateLabel />
      </div>
    )
  }

  if (hasResume) {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p className="text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
          Your strongest experience matches, plus Roles shaped by your activity.
        </p>
        <PrivateLabel />
      </div>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <PrivateLabel />
    </div>
  )
}

function PrivateLabel({ label = 'Private to your account' }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs font-semibold" style={{ color: 'var(--color-ink-muted)' }}>
      <ShieldCheck size={13} strokeWidth={2.25} aria-hidden="true" />
      {label}
    </span>
  )
}
