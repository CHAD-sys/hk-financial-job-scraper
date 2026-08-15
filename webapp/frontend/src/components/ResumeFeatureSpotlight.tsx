import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ArrowRight, BadgeCheck, FileSearch, FileText, LoaderCircle, RefreshCw, ShieldCheck, X } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
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

/**
 * The signed-out panel: what resume matching does, and the three steps it
 * takes. Every step needs an account, so the whole panel is a way in rather
 * than a static illustration — clicking anywhere on it opens the prompt below.
 *
 * The click target is a transparent button stretched over the panel, not the
 * panel itself: a <button> may only contain phrasing content, and this panel
 * holds an <ol>. Wrapping it would be invalid HTML, and <div role="button">
 * would mean re-implementing Enter/Space by hand. The overlay keeps a real
 * button — free keyboard activation — over content that stays plain markup for
 * a screen reader to walk. It carries an aria-label because it has no text of
 * its own; the visible affordance is the footer line inside the panel.
 */
function ResumeHowItWorks() {
  const [promptOpen, setPromptOpen] = useState(false)

  return (
    <div className="resume-feature-spotlight__proof resume-feature-spotlight__proof--interactive">
      <button
        type="button"
        className="resume-feature-spotlight__proof-trigger"
        aria-label="Sign in or create an account to upload your resume"
        aria-haspopup="dialog"
        onClick={() => setPromptOpen(true)}
      />
      <div className="resume-feature-spotlight__file">
        <span><FileSearch size={21} strokeWidth={1.9} aria-hidden="true" /></span>
        <div><strong>Evidence-led discovery</strong><small>Optional · private · based on live Roles</small></div>
      </div>
      <ol className="resume-feature-spotlight__steps" aria-label="How resume matching works">
        <li><span>1</span><div><strong>Upload</strong><small>PDF or DOCX.</small></div></li>
        <li><span>2</span><div><strong>Review strengths</strong><small>Skills, experience and sectors.</small></div></li>
        <li><span>3</span><div><strong>Explore matches</strong><small>Live Roles with a clear reason.</small></div></li>
      </ol>
      <p className="resume-feature-spotlight__proof-hint" aria-hidden="true">
        Sign in to start <ArrowRight size={14} strokeWidth={2} />
      </p>

      {promptOpen && <SignInPrompt onClose={() => setPromptOpen(false)} />}
    </div>
  )
}

/**
 * Asks a signed-out visitor to sign in or register before they can upload a
 * resume. A native <dialog> opened with showModal(), so focus trapping, the
 * inert background and Escape-to-close come from the platform rather than from
 * us — the same reasoning as JobDetailModal.tsx, without its enter/exit state
 * machine, because this one is small enough to fade in and close instantly.
 *
 * Deliberately NOT wired to useModalHistoryGuard, unlike JobDetailModal. That
 * hook pushes a history entry on open and pops it on unmount, which is right
 * for a modal you only ever dismiss — but every useful exit from THIS one is a
 * router navigation. Clicking "Create a Seeker account" pushes /register and
 * then unmounts the dialog, at which point the hook's cleanup fires
 * history.back() and fights the navigation it just triggered; in the browser
 * that wedges the tab outright. Escape, the close button and a backdrop click
 * all still work, so the only thing given up is the phone back gesture as a
 * dismiss — a fair trade for a prompt whose whole purpose is to send you
 * somewhere else.
 *
 * Both links carry the current path as `from`, which useReturnTo reads on the
 * other side, so signing in returns the visitor to the page they were reading
 * instead of dropping them on the board.
 */
function SignInPrompt({ onClose }: { onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const { pathname } = useLocation()

  // Ref so the effect below can stay mount-once while still calling the latest
  // onClose. The parent passes a fresh arrow every render, so depending on it
  // directly would tear down and re-run the effect on every re-render — and
  // that effect calls showModal(), which throws InvalidStateError on a dialog
  // that is already open. Same reasoning as useModalHistoryGuard's onCloseRef.
  const onCloseRef = useRef(onClose)
  useLayoutEffect(() => { onCloseRef.current = onClose }, [onClose])

  useEffect(() => {
    const dlg = dialogRef.current
    if (!dlg) return
    dlg.showModal()
    // Clicks on the ::backdrop are delivered with the dialog as their target,
    // so backdrop-click-to-close is wired here rather than in the markup.
    const onBackdropClick = (e: MouseEvent) => { if (e.target === dlg) onCloseRef.current() }
    const onCancel = (e: Event) => { e.preventDefault(); onCloseRef.current() }
    dlg.addEventListener('click', onBackdropClick)
    dlg.addEventListener('cancel', onCancel)
    return () => {
      dlg.removeEventListener('click', onBackdropClick)
      dlg.removeEventListener('cancel', onCancel)
      // Leave the top layer explicitly before React detaches the element.
      // showModal() puts the dialog in the top layer and makes the rest of the
      // document inert; unmounting alone does not reliably undo that in Chrome,
      // and the leftover inert state makes the whole page stop responding to
      // clicks. It bites hardest on the path this dialog exists for — clicking
      // a Link inside it navigates, which unmounts it mid-navigation and wedged
      // the tab outright.
      if (dlg.open) dlg.close()
    }
  }, [])

  return (
    <dialog ref={dialogRef} className="signin-prompt-dialog" aria-labelledby="signin-prompt-heading">
      <button
        type="button"
        className="signin-prompt-dialog__close"
        onClick={onClose}
        aria-label="Close"
      >
        <X size={18} strokeWidth={2} aria-hidden="true" />
      </button>

      <span className="signin-prompt-dialog__icon" aria-hidden="true">
        <FileSearch size={22} strokeWidth={1.9} />
      </span>
      <h2 id="signin-prompt-heading">Create an account to upload your resume</h2>
      <p>
        Resume matching needs somewhere private to keep your file, so it is for
        signed-in Seekers only. Browsing and searching Roles stays open to
        everyone — no account required.
      </p>

      <div className="signin-prompt-dialog__actions">
        <Link to="/register" state={{ from: pathname }} className="signin-prompt-dialog__primary">
          Create a Seeker account <ArrowRight size={16} strokeWidth={2} aria-hidden="true" />
        </Link>
        <Link to="/signin" state={{ from: pathname }} className="signin-prompt-dialog__secondary">
          Already have an account? Sign in
        </Link>
      </div>
    </dialog>
  )
}

function ResumeProof({ signedIn, loading, error, matches, onRetry }: {
  signedIn: boolean
  loading: boolean
  error: boolean
  matches: ResumeMatchesResponse | null
  onRetry: () => void
}) {
  if (!signedIn) return <ResumeHowItWorks />

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
          <Link className="resume-feature-spotlight__result-link" to="/jobs">Search Roles <ArrowRight size={14} aria-hidden="true" /></Link>
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
