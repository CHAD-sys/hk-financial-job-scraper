import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import CareerCoachingTag from './CareerCoachingTag'
import { recommendedCoachForCompany } from '../content/careerCoachRecommendations'

describe('CareerCoachingTag', () => {
  it.each(['HKJC', 'Hong Kong Monetary Authority (HKMA)', 'Standard Chartered Bank', 'HSBC'])
  ('recommends Morris Hui for %s roles', company => {
    render(<CareerCoachingTag company={company} />)
    expect(screen.getByRole('link', { name: 'Career coaching with Morris Hui, CFA' })).toHaveAttribute('href', 'https://www.finexclub.org/morris-hui')
    expect(screen.getByText('Career coaching')).toBeTruthy()
  })

  it('keeps the ordinary coaching route available for every other employer', () => {
    render(<CareerCoachingTag company="Citi" />)
    expect(screen.getByRole('link', { name: 'Career coaching' })).toHaveAttribute('href', 'https://www.finexcareers.com/career-coaches')
    expect(recommendedCoachForCompany('Citi')).toBeNull()
  })
})
