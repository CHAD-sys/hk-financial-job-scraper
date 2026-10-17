import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { CAREER_COACH_GROUPS } from '../content/careerCoaches'
import CareerCoachesPage from './CareerCoachesPage'

vi.mock('../components/Nav', () => ({ default: () => <nav>Navigation</nav> }))

function renderPage() {
  return render(
      <MemoryRouter><CareerCoachesPage /></MemoryRouter>,
  )
}

describe('CareerCoachesPage', () => {
  it('removes featured coach cards and explains how to use the directory', () => {
    renderPage()

    expect(screen.queryByLabelText('Featured FinEx career coaches')).not.toBeInTheDocument()
    expect(screen.getByRole('complementary', { name: 'How to find a career coach' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Start with the work, not the title.' })).toBeInTheDocument()
  })

  it('shows every category membership, then filters the roster by expertise', () => {
    renderPage()

    const groupedMembershipCount = CAREER_COACH_GROUPS.reduce((total, group) => total + group.coaches.length, 0)
    expect(screen.getAllByRole('article')).toHaveLength(groupedMembershipCount)
    expect(screen.getAllByRole('heading', { name: 'Nicholas Yip' })).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: /digital assets & fintech/i }))

    expect(screen.getByRole('heading', { name: 'Hannah Hui' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Nicholas Yip' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Calvin Lee' })).not.toBeInTheDocument()
    expect(screen.getByText(/showing coaches specialising in digital assets & fintech/i)).toBeInTheDocument()
  })

  it('shows renamed categories and omits categories that are paused', () => {
    renderPage()

    expect(screen.getByRole('button', { name: 'Custody, Funds, and Assets Servicing' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Private Equity, Family Offices, Wealth' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Strategy, Transformation & Consulting' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Private Banking & Wealth' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Insurance & Actuarial' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Investment Banking' })).not.toBeInTheDocument()
  })

  it('refines the directory by exact stated specialty and profile search', () => {
    renderPage()

    fireEvent.change(screen.getByRole('combobox', { name: /specialty/i }), { target: { value: 'Web3' } })
    expect(screen.getAllByRole('article')).toHaveLength(1)
    expect(screen.getByRole('heading', { name: 'John Wong' })).toBeInTheDocument()

    fireEvent.change(screen.getByRole('searchbox', { name: /search coaches/i }), { target: { value: 'Hannah' } })
    expect(screen.queryByRole('heading', { name: 'John Wong' })).not.toBeInTheDocument()
    expect(screen.getByText(/no coaches match these filters/i)).toBeInTheDocument()
  })
})
