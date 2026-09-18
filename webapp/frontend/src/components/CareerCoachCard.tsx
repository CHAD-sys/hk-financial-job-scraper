import { ArrowUpRight, CalendarCheck2 } from 'lucide-react'
import type { CareerCoach } from '../content/careerCoaches'

export default function CareerCoachCard({ coach }: { coach: CareerCoach }) {
  return (
    <article className="career-coach-card">
      <div className="career-coach-card__portrait">
        <img
          src={coach.image}
          alt={`${coach.name}, FinEx career coach`}
          loading="lazy"
          width={280}
          height={280}
        />
        <span>{coach.primaryDomain}</span>
      </div>
      <div className="career-coach-card__body">
        <h3>{coach.name}</h3>
        <p className="career-coach-card__role">{coach.role}</p>
        <p className="career-coach-card__focus">{coach.focus}</p>
        <a className="career-coach-card__profile" href={coach.href} target="_blank" rel="noopener noreferrer">
          View coach profile
          <ArrowUpRight size={14} aria-hidden="true" />
        </a>
        <ul aria-label={`${coach.name} expertise`}>
          {coach.domains.map(domain => <li key={domain}>{domain}</li>)}
        </ul>
      </div>
      <a
        className="career-coach-card__appointment"
        href={coach.appointmentUrl}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`Make an appointment with ${coach.name}`}
      >
        <CalendarCheck2 size={17} aria-hidden="true" />
        Make an appointment
        <ArrowUpRight size={16} aria-hidden="true" />
      </a>
    </article>
  )
}
