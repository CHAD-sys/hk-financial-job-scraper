import { MessageCircleMore } from 'lucide-react'
import { recommendedCoachForCompany } from '../content/careerCoachRecommendations'

export default function CareerCoachingTag({ company }: { company: string }) {
  const coach = recommendedCoachForCompany(company)

  return (
    <a
      className="career-coaching-tag"
      href={coach?.href ?? 'https://www.finexcareers.com/career-coaches'}
      target={coach ? '_blank' : undefined}
      rel={coach ? 'noopener noreferrer' : undefined}
      aria-label={coach ? `Career coaching with ${coach.name}` : 'Career coaching'}
    >
      <MessageCircleMore size={14} aria-hidden="true" />
      Career coaching
    </a>
  )
}
