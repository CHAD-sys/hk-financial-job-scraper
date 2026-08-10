import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, BadgeCheck, FileSearch, RefreshCw, ShieldCheck } from 'lucide-react'
import type { Job, ResumeMatchesResponse } from '../api/client'
import { fetchResumeMatches } from '../api/client'
import { useAuth } from '../auth/useAuth'
import JobCard from './JobCard'
import SkeletonCard from './SkeletonCard'

interface Props {
  saved: (job: Job) => boolean
  onToggleSave: (job: Job) => void
  onSelect: (job: Job) => void
}

export default function ResumeMatches({ saved, onToggleSave, onSelect }: Props) {
  const { seeker } = useAuth()
  const seekerId = seeker?.id
  const [result, setResult] = useState<ResumeMatchesResponse | null>(null)
  const [loading, setLoading] = useState(Boolean(seeker))
  const [error, setError] = useState(false)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    if (!seekerId) {
      setResult(null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(false)
    fetchResumeMatches(3)
      .then(value => { if (!cancelled) setResult(value) })
      .catch(err => {
        console.error(err)
        if (!cancelled) setError(true)
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [nonce, seekerId])

  if (!seeker) {
    return (
      <section className="resume-match-prompt resume-match-prompt--featured mb-10 sm:mb-14" aria-labelledby="resume-prompt-heading">
        <span className="resume-match-prompt__mark" aria-hidden="true"><FileSearch size={25} strokeWidth={1.9} /></span>
        <div className="min-w-0 flex-1">
          <span className="resume-match-prompt__kicker">Resume intelligence</span>
          <h2 id="resume-prompt-heading">See where your experience fits.</h2>
          <p>Sign in to add one private resume and get evidence-led matches across today&rsquo;s Hong Kong finance market.</p>
        </div>
        <div className="resume-match-prompt__actions">
          <Link to="/register" className="resume-match-prompt__primary">Create account <ArrowRight size={14} aria-hidden="true" /></Link>
          <Link to="/signin">Sign in</Link>
        </div>
      </section>
    )
  }

  if (loading) {
    return (
      <section className="mb-10 sm:mb-14" aria-label="Loading strong resume matches">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, index) => <SkeletonCard key={index} />)}
        </div>
      </section>
    )
  }

  if (error) {
    return (
      <section className="resume-match-prompt mb-10 sm:mb-14" role="status">
        <FileSearch size={22} aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold">Your strong matches could not be loaded.</p>
          <p>Try again without re-uploading your resume.</p>
        </div>
        <button type="button" onClick={() => setNonce(value => value + 1)}>
          <RefreshCw size={14} aria-hidden="true" /> Try again
        </button>
      </section>
    )
  }

  if (!result?.has_resume) {
    return (
      <section className="resume-match-prompt resume-match-prompt--featured mb-10 sm:mb-14" aria-labelledby="resume-prompt-heading">
        <span className="resume-match-prompt__mark" aria-hidden="true"><FileSearch size={25} strokeWidth={1.9} /></span>
        <div className="min-w-0 flex-1">
          <span className="resume-match-prompt__kicker">Resume intelligence</span>
          <h2 id="resume-prompt-heading">Put your experience against today&rsquo;s market.</h2>
          <p>Add one PDF or DOCX resume to surface your strongest current Role matches—with clear reasons for each one.</p>
          <span className="resume-match-prompt__trust"><ShieldCheck size={13} aria-hidden="true" /> Private and removable anytime</span>
        </div>
        <div className="resume-match-prompt__actions">
          <Link to="/account" className="resume-match-prompt__primary">Upload your resume <ArrowRight size={14} aria-hidden="true" /></Link>
        </div>
      </section>
    )
  }

  return (
    <section className="mb-10 sm:mb-14" aria-labelledby="resume-matches-heading">
      <div className="resume-matches-heading mb-5">
        <div className="max-w-3xl">
          <div className="flex items-center gap-2">
            <BadgeCheck size={18} strokeWidth={2.2} style={{ color: 'var(--color-gold)' }} aria-hidden="true" />
            <h2 id="resume-matches-heading">Strong matches for your experience</h2>
          </div>
          <p>
            Based on observable skills and experience in your resume. This guides discovery—it
            does not decide eligibility or replace the employer’s requirements.
          </p>
          <span>
            <ShieldCheck size={13} strokeWidth={2.2} aria-hidden="true" /> Private to your account
          </span>
        </div>
        <Link to="/account">Manage resume</Link>
      </div>

      {result.items.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-live="polite">
          {result.items.map(item => (
            <article key={`${item.job.source}__${item.job.source_id}`} className="resume-match-card">
              <JobCard
                job={item.job}
                saved={saved(item.job)}
                onToggleSave={onToggleSave}
                onClick={onSelect}
              />
              <p className="resume-match-card__reason">
                <BadgeCheck size={14} className="shrink-0" aria-hidden="true" />
                {item.reasons[0] || 'Relevant experience found in your resume'}
              </p>
            </article>
          ))}
        </div>
      ) : (
        <div className="resume-matches-empty" role="status">
          <p>No current Roles crossed the strong-match threshold.</p>
          <span>We’ll keep checking the refreshed market using this resume.</span>
        </div>
      )}
    </section>
  )
}
