import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { CareerCoach } from '../content/careerCoaches'
import CareerCoachCard from './CareerCoachCard'

const coach: CareerCoach = {
  id: 'coach-example',
  kind: 'coach',
  name: 'Hannah Hui',
  role: 'CEO / Managing Director',
  focus: 'Fintech & Digital Assets · Virtual Banking',
  image: 'https://example.com/hannah.jpg',
  href: 'https://www.finexclub.org/hannah-hui',
  appointmentUrl: 'https://www.finexclub.org/mentor-program',
  primaryDomain: 'Digital Assets & FinTech',
  domains: ['Digital Assets & FinTech', 'Institutional Banking & Sales'],
}

describe('CareerCoachCard', () => {
  it('shows expertise and a direct appointment action for the coach', () => {
    render(<CareerCoachCard coach={coach} />)

    expect(screen.getByRole('heading', { name: 'Hannah Hui' })).toBeInTheDocument()
    expect(screen.getAllByText('Digital Assets & FinTech')).not.toHaveLength(0)
    expect(screen.getByRole('link', { name: /make an appointment with hannah hui/i })).toHaveAttribute(
      'href',
      coach.appointmentUrl,
    )
  })
})
