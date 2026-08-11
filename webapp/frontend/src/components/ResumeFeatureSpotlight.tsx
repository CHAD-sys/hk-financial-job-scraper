import { useEffect, useState } from 'react'
import { ArrowRight, BadgeCheck, FileSearch, FileText, LoaderCircle, RefreshCw, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { fetchResumeMatches, type ResumeMatchesResponse } from '../api/client'
import { useAuth } from '../auth/useAuth'

/**
 * The homepage's one product-level explanation of resume intelligence.
 *
 * This is intentionally not another product door. Resume matching strengthens
 * the Careers door rather than becoming a fourth FinEx product, and the CTA
 * changes with identity without implying that browsing requires an account.
 */
export default function ResumeFeatureSpotlight() {
  const { seeker, loading: authLoading } = useAuth()
  const [matches, setMatches] = useState<ResumeMatchesResponse | null>(null)
  const [matchLoading, setMatchLoading] = useState(Boolean(seeker))
  const [matchError, setMatchError] = useState(false)
  const [retry, setRetry] = useState(0)
  const seekerId = seeker?.id

  useEffect(() => {
    if (!seekerId) {
      setMatches(null)
      setMatchLoading(false)
      setMatchError(false)
      return
    }
    let cancelled = false
    setMatchLoading(true)
    setMatchError(false)
    fetchResumeMatches(1)
      .then(value => { if (!cancelled) setMatches(value) })
      .catch(() => { if (!cancelled) setMatchError(true) })
      .finally(() => { if (!cancelled) setMatchLoading(false) })
    return () => { cancelled = true }
  }, [retry, seekerId])

  const cta = seeker
    ? { to: '/account', label: 'Add or manage your resume' }
    : { to: '/register', label: 'Create a Seeker account' }

  return (
    <section
      className="resume-feature-spotlight"
      aria-labelledby="resume-feature-heading"
    >
      <div className="mx-auto grid max-w-7xl gap-12 px-6 py-16 lg:grid-cols-[0.9fr_1.1fr] lg:items-center lg:px-8 lg:py-20">
        <div>
          <div className="resume-feature-spotlight__kicker">
            <FileSearch size={16} strokeWidth={2} aria-hidden="true" />
            Resume intelligence
          </div>
          <h2 id="resume-feature-heading">
            Turn one resume into better job discovery.
          </h2>
          <p className="resume-feature-spotlight__lead">
            See the strengths we find and the live Roles they support.
          </p>

          <ul className="resume-feature-spotlight__benefits" aria-label="Resume matching essentials">
            <li><FileText size={17} aria-hidden="true" /> One file</li>
            <li><ShieldCheck size={17} aria-hidden="true" /> Private</li>
            <li><BadgeCheck size={17} aria-hidden="true" /> Updated daily</li>
          </ul>

          <div className="resume-feature-spotlight__actions">
            {!authLoading && (
              <Link to={cta.to} className="resume-feature-spotlight__primary">
                {cta.label} <ArrowRight size={16} strokeWidth={2} aria-hidden="true" />
              </Link>
            )}
            {!authLoading && !seeker && (
              <Link to="/signin" className="resume-feature-spotlight__secondary">
                Already have an account? Sign in
              </Link>
            )}
          </div>
        </div>

        <ResumeProof
          signedIn={Boolean(seeker)}
          loading={matchLoading}
          error={matchError}
          matches={matches}
          onRetry={() => setRetry(value => value + 1)}
        />
      </div>
    </section>
  )
}

function ResumeProof({ signedIn, loading, error, matches, onRetry }: {
  signedIn: boolean
  loading: boolean
  error: boolean
  matches: ResumeMatchesResponse | null
  onRetry: () => void
}) {
  if (!signedIn) {
    return (
      <div className="resume-feature-spotlight__proof" aria-label="How resume matching works">
        <div className="resume-feature-spotlight__file">
          <span><FileSearch size={21} strokeWidth={1.9} aria-hidden="true" /></span>
          <div><strong>Evidence-led discovery</strong><small>Optional · private · based on live Roles</small></div>
        </div>
        <ol className="resume-feature-spotlight__steps" aria-label="How resume matching works">
          <li><span>1</span><div><strong>Upload</strong><small>PDF or DOCX.</small></div></li>
          <li><span>2</span><div><strong>Review strengths</strong><small>Skills, experience and sectors.</small></div></li>
          <li><span>3</span><div><strong>Explore matches</strong><small>Live Roles with a clear reason.</small></div></li>
        </ol>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="resume-feature-spotlight__proof resume-feature-spotlight__proof--status" role="status" aria-live="polite">
        <LoaderCircle className="animate-spin" size={28} aria-hidden="true" />
        <div><strong>Checking your private resume status…</strong><small>Loading your latest evidence and live Role matches.</small></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="resume-feature-spotlight__proof resume-feature-spotlight__proof--status" role="status">
        <FileSearch size={28} aria-hidden="true" />
        <div><strong>Your resume status could not be loaded.</strong><small>Nothing has been assumed or displayed from an example.</small></div>
        <button type="button" onClick={onRetry}><RefreshCw size={14} aria-hidden="true" /> Try again</button>
      </div>
    )
  }

  if (!matches?.has_resume) {
    return (
      <div className="resume-feature-spotlight__proof" aria-labelledby="resume-empty-heading">
        <div className="resume-feature-spotlight__file">
          <span><FileText size={21} strokeWidth={1.9} aria-hidden="true" /></span>
          <div><strong>No resume added</strong><small>Your feed still learns from activity.</small></div>
          <em>Optional</em>
        </div>
        <div className="resume-feature-spotlight__path" aria-hidden="true"><span /><span>Ready when you are</span><span /></div>
        <div className="resume-feature-spotlight__result">
          <p>Your next step</p>
          <h3 id="resume-empty-heading">Add your resume to start matching.</h3>
          <small>Add one PDF or DOCX. You can replace or remove it anytime.</small>
          <Link className="resume-feature-spotlight__result-link" to="/account">Upload your resume <ArrowRight size={14} aria-hidden="true" /></Link>
        </div>
      </div>
    )
  }

  const match = matches.items[0]
  if (!match) {
    return (
      <div className="resume-feature-spotlight__proof" role="status">
        <div className="resume-feature-spotlight__file">
          <span><BadgeCheck size={21} strokeWidth={1.9} aria-hidden="true" /></span>
          <div><strong>Resume analysed</strong><small>Your evidence is ready and remains private.</small></div>
          <em>Current</em>
        </div>
        <div className="resume-feature-spotlight__path" aria-hidden="true"><span /><span>Compared with today&rsquo;s market</span><span /></div>
        <div className="resume-feature-spotlight__result">
          <p>Market check complete</p>
          <h3>No strong live Role match yet.</h3>
          <small>We’ll check again when the market refreshes.</small>
          <Link className="resume-feature-spotlight__result-link" to="/jobs">Browse all Roles <ArrowRight size={14} aria-hidden="true" /></Link>
        </div>
      </div>
    )
  }

  return (
    <div className="resume-feature-spotlight__proof" aria-label="Your latest live resume match">
      <div className="resume-feature-spotlight__file">
        <span><BadgeCheck size={21} strokeWidth={1.9} aria-hidden="true" /></span>
        <div><strong>Your resume</strong><small>Compared with currently open Roles</small></div>
        <em>Private</em>
      </div>
      <div className="resume-feature-spotlight__path" aria-hidden="true"><span /><span>Latest live match</span><span /></div>
      <div className="resume-feature-spotlight__result">
        <p>{match.match_score}% evidence match</p>
        <h3>{match.job.title}</h3>
        <div>{match.reasons.slice(0, 3).map(reason => <span key={reason}>{reason}</span>)}</div>
        <small>Evidence overlap only—not a hiring decision.</small>
        <Link className="resume-feature-spotlight__result-link" to="/jobs">View your live matches <ArrowRight size={14} aria-hidden="true" /></Link>
      </div>
    </div>
  )
}
