import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import MTWorkbookProgrammeCard from './MTWorkbookProgrammeCard'

const activeProgramme = {
  id: 'mt-workbook-test',
  company: 'Goldman Sachs',
  status: 'Active' as const,
  deadline: 'Ongoing',
  applicationUrl: 'https://example.com/apply',
  employerLinkNumber: 1,
}

function renderCard(company = 'Goldman Sachs') {
  return render(
    <MemoryRouter>
      <MTWorkbookProgrammeCard employer={{ company, programmes: [{ ...activeProgramme, company }] }} />
    </MemoryRouter>,
  )
}

describe('MTWorkbookProgrammeCard', () => {
  it('shows the employer’s compressed colour logo in every programme card', () => {
    renderCard()

    expect(screen.getByTestId('mt-workbook-card-logo').querySelector('img'))
      .toHaveAttribute('src', '/company-logos/goldman-sachs.webp')
  })

  it('keeps a readable visual wordmark if a logo is unavailable', () => {
    renderCard('Example Employer')

    expect(screen.getByTestId('mt-workbook-card-logo')).toHaveTextContent('Example Employer')
  })

  it('falls back to the wordmark if a mapped image cannot load', () => {
    renderCard()

    fireEvent.error(screen.getByTestId('mt-workbook-card-logo').querySelector('img')!)

    expect(screen.getByTestId('mt-workbook-card-logo')).toHaveTextContent('Goldman Sachs')
  })
})
