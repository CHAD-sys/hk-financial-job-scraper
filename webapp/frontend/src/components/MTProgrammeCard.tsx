import { ArrowUpRight, CalendarClock, MessageCircleMore } from 'lucide-react'
import type { MTProgramme } from '../content/managementTraineePrograms'

const CONSULTATION_URL = 'https://www.finexclub.org/mentor-program'

export default function MTProgrammeCard({
  programme,
  compact = false,
  liveActive = false,
}: {
  programme: MTProgramme
  compact?: boolean
  /** True when a current live or curated MT role exists for this employer. */
  liveActive?: boolean
}) {
  const applicationLink = programme.masterApplicationUrl ?? programme.applicationUrls[0]
  const application = programme.application
  const verifiedOpen = application?.status === 'open'
  const openNow = liveActive || verifiedOpen
  const deadline = verifiedOpen && application?.deadline
    ? `Closes ${new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Hong_Kong' }).format(new Date(`${application.deadline}T00:00:00+08:00`))}`
    : openNow ? liveActive ? 'Active role listed above · deadline not stated' : 'Deadline not stated'
      : 'No verified active intake'
  const statusLabel = openNow ? 'Open now'
    : application?.status === 'closed' ? 'To be updated'
      : application?.status === 'upcoming' ? 'Upcoming'
        : application?.status === 'unavailable' ? 'Link unavailable'
          : 'Not currently open'
  const checkedAt = application && new Intl.DateTimeFormat('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Hong_Kong',
  }).format(new Date(`${application.checkedAt}T00:00:00+08:00`))

  return (
    <article className={`mt-programme-card${compact ? ' mt-programme-card--compact' : ''}`}>
      <div className={`mt-programme-card__deadline ${openNow ? 'mt-programme-card__deadline--open' : 'mt-programme-card__deadline--inactive'}`}>
        <CalendarClock size={18} aria-hidden="true" />
        <span><strong>{statusLabel}</strong> · {deadline}</span>
      </div>
      <div className="mt-programme-card__body">
        <p className="mt-programme-card__industry">{programme.industry}</p>
        <h3>{programme.company}</h3>
        <p className="mt-programme-card__chinese" lang="zh-HK">{programme.companyChinese}</p>
        <p className="mt-programme-card__type">{programme.programmeName ?? 'Management Trainee Programme'}</p>
        {checkedAt && <p className="mt-programme-card__checked">Checked {checkedAt}</p>}
      </div>
      <div className="mt-programme-card__actions">
        {applicationLink ? (
          <a href={applicationLink} target="_blank" rel="noopener noreferrer">
            {programme.linksVerified ? 'View official programme' : 'View programme'}
            <ArrowUpRight size={15} aria-hidden="true" />
          </a>
        ) : (
          <span className="mt-programme-card__pending" aria-label="Application link awaiting verification">
            Link pending
            <ArrowUpRight size={15} aria-hidden="true" />
          </span>
        )}
        <a className="mt-programme-card__coaching" href={CONSULTATION_URL} target="_blank" rel="noopener noreferrer">
          <MessageCircleMore size={16} aria-hidden="true" />
          Career coaching
        </a>
      </div>
    </article>
  )
}
