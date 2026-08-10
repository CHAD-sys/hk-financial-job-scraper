import { ArrowRight, BadgeCheck, FileSearch, FileText, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'

/**
 * The homepage's one product-level explanation of resume intelligence.
 *
 * This is intentionally not another product door. Resume matching strengthens
 * the Careers door rather than becoming a fourth FinEx product, and the CTA
 * changes with identity without implying that browsing requires an account.
 */
export default function ResumeFeatureSpotlight() {
  const { seeker, loading } = useAuth()
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
            See where your experience is strongest across the market.
          </h2>
          <p className="resume-feature-spotlight__lead">
            Add one private resume and FinEx reads the experience you already have, compares it
            with the live Hong Kong finance market, and explains the Roles where that evidence
            aligns.
          </p>

          <ul className="resume-feature-spotlight__benefits" aria-label="What resume intelligence provides">
            <li><BadgeCheck size={17} aria-hidden="true" /> Evidence-led matches, with reasons</li>
            <li><FileText size={17} aria-hidden="true" /> PDF or DOCX, one resume at a time</li>
            <li><ShieldCheck size={17} aria-hidden="true" /> Private to your account and removable anytime</li>
          </ul>

          <div className="resume-feature-spotlight__actions">
            {!loading && (
              <Link to={cta.to} className="resume-feature-spotlight__primary">
                {cta.label} <ArrowRight size={16} strokeWidth={2} aria-hidden="true" />
              </Link>
            )}
            {!loading && !seeker && (
              <Link to="/signin" className="resume-feature-spotlight__secondary">
                Already have an account? Sign in
              </Link>
            )}
          </div>
          <p className="resume-feature-spotlight__public-note">
            The careers index stays free and open. A resume only unlocks private, personalised discovery.
          </p>
        </div>

        <div className="resume-feature-spotlight__proof" aria-label="Example of how resume matching works">
          <div className="resume-feature-spotlight__file">
            <span><FileText size={21} strokeWidth={1.9} aria-hidden="true" /></span>
            <div>
              <strong>Your resume</strong>
              <small>Skills · experience · sector evidence</small>
            </div>
            <em>Private</em>
          </div>

          <div className="resume-feature-spotlight__path" aria-hidden="true">
            <span />
            <span>Compared with today&rsquo;s market</span>
            <span />
          </div>

          <div className="resume-feature-spotlight__result">
            <p>Strong match</p>
            <h3>Credit Risk &amp; Portfolio Roles</h3>
            <div>
              <span>Credit risk</span>
              <span>SQL</span>
              <span>Portfolio monitoring</span>
            </div>
            <small>
              The real product shows live Roles and the specific evidence that aligned—not a hiring decision.
            </small>
          </div>
        </div>
      </div>
    </section>
  )
}
