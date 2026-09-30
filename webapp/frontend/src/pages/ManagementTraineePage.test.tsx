import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { groupMTWorkbookProgrammesByEmployer, MT_WORKBOOK_PROGRAMMES } from '../content/mtWorkbookProgrammes'

vi.mock('../components/Nav', () => ({ default: () => <nav>Navigation</nav> }))

const { default: ManagementTraineePage } = await import('./ManagementTraineePage')

function renderDirectory() {
  return render(<MemoryRouter><ManagementTraineePage /></MemoryRouter>)
}

describe('ManagementTraineePage workbook directory', () => {
  it('renders one card per employer while retaining every workbook application link', () => {
    renderDirectory()

    expect(screen.getByRole('heading', { name: 'Apply while the window is open.' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Keep these on your radar.' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Start with a leading employer.' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Open Management Trainee employers' })).toBeInTheDocument()
    expect(screen.getAllByRole('article')).toHaveLength(groupMTWorkbookProgrammesByEmployer(MT_WORKBOOK_PROGRAMMES).length)
    expect(screen.getAllByRole('link', { name: /View all application links at/ })).toHaveLength(
      groupMTWorkbookProgrammesByEmployer(MT_WORKBOOK_PROGRAMMES).length,
    )
    expect(MT_WORKBOOK_PROGRAMMES).toHaveLength(169)
    expect(screen.queryByText('MT roles from the live careers database.')).not.toBeInTheDocument()
    expect(screen.queryByText('Active roles in FinEx Careers')).not.toBeInTheDocument()
  })

  it('places all active workbook entries before closed and unconfirmed cards', () => {
    renderDirectory()

    const cards = screen.getAllByRole('article')
    const firstClosed = cards.findIndex(card => card.textContent?.includes('CLSA'))
    const finalOpen = cards.findLastIndex(card => card.textContent?.includes('Open now'))

    expect(firstClosed).toBeGreaterThan(finalOpen)
    expect(cards[firstClosed]).toHaveTextContent('Closed')
    expect(screen.getByRole('link', { name: 'View all application links at CLSA' })).toHaveAttribute(
      'href', '/management-trainee/clsa',
    )
  })

  it('groups distinct employer links beneath one application card', () => {
    renderDirectory()

    const bankOfAmericaCards = screen.getAllByRole('article').filter(card => card.textContent?.includes('Bank of America (BofA)'))
    expect(bankOfAmericaCards).toHaveLength(1)
    expect(bankOfAmericaCards[0]).toHaveTextContent('8 application links')
    expect(screen.getByRole('link', { name: 'View all application links at Bank of America (BofA)' })).toHaveAttribute(
      'href', '/management-trainee/bank-of-america-bofa',
    )
  })

  it('orders employers by prestige inside each status group', () => {
    renderDirectory()

    const cards = screen.getAllByRole('article')
    const indexFor = (company: string) => cards.findIndex(card => card.textContent?.includes(company))

    expect(indexFor('Goldman Sachs')).toBeLessThan(indexFor('HSBC'))
    expect(indexFor('HSBC')).toBeLessThan(indexFor('Deloitte'))
    expect(indexFor('Mizuho')).toBeLessThan(indexFor('CLSA'))
  })

  it('uses the restored employer shortcuts to jump to the corresponding open cards', () => {
    renderDirectory()

    expect(screen.getByRole('link', { name: 'Jump to open application links at Goldman Sachs' })).toHaveAttribute(
      'href', '#mt-employer-goldman-sachs',
    )
    expect(document.getElementById('mt-employer-goldman-sachs')).toHaveTextContent('Goldman Sachs')
  })

  it('keeps the leading-employer shortcuts focused on the strongest active platforms', () => {
    renderDirectory()

    expect(screen.getByRole('link', { name: 'Jump to open application links at Standard Chartered' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Jump to open application links at Jardine Matheson' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Jump to open application links at Swire' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Jump to open application links at Cathay Pacific' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Jump to open application links at Jefferies' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Jump to open application links at Fidelity International' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Jump to open application links at MUFG (Mitsubishi UFJ Financial Group)' })).not.toBeInTheDocument()
  })

  it('filters the same card directory by employer name', () => {
    renderDirectory()

    fireEvent.change(screen.getByRole('textbox', { name: 'Search employers' }), { target: { value: 'CLSA' } })

    expect(screen.getAllByRole('article')).toHaveLength(1)
    expect(screen.getByRole('heading', { name: 'CLSA' })).toBeInTheDocument()
    expect(screen.getByText('Closed')).toBeInTheDocument()
  })
})
