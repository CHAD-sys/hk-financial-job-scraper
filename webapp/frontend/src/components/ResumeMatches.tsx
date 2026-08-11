import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, FileSearch, RefreshCw } from 'lucide-react'
import type { ResumeMatchesResponse } from '../api/client'
import { fetchResumeMatches } from '../api/client'
import { useAuth } from '../auth/useAuth'
import ResumeFlow from './ResumeFlow'
import SkeletonCard from './SkeletonCard'

interface Props {
  onResolved?: (result: ResumeMatchesResponse | null) => void
}

export default function ResumeMatches({
  onResolved,
}: Props) {
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
      onResolved?.(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(false)
    fetchResumeMatches(3)
      .then(value => {
        if (!cancelled) {
          setResult(value)
          onResolved?.(value)
        }
      })
      .catch(err => {
        console.error(err)
        if (!cancelled) {
          setError(true)
          onResolved?.(null)
        }
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [nonce, onResolved, seekerId])

  if (!seeker) {
    return (
      <section className="resume-match-prompt resume-match-prompt--featured mb-10 sm:mb-14" aria-labelledby="resume-prompt-heading">
        <span className="resume-match-prompt__mark" aria-hidden="true"><FileSearch size={25} strokeWidth={1.9} /></span>
        <div className="min-w-0 flex-1">
          <span className="resume-match-prompt__kicker">Resume intelligence</span>
          <h2 id="resume-prompt-heading">Find Roles that fit you.</h2>
          <ResumeFlow className="resume-match-prompt__flow" />
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
          <h2 id="resume-prompt-heading">Find Roles that fit you.</h2>
          <ResumeFlow className="resume-match-prompt__flow" />
        </div>
        <div className="resume-match-prompt__actions">
          <Link to="/account" className="resume-match-prompt__primary">Upload your resume <ArrowRight size={14} aria-hidden="true" /></Link>
        </div>
      </section>
    )
  }

  return null
}
