import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import CareerCoachesPage from './CareerCoachesPage'

vi.mock('../components/Nav', () => ({ default: () => <nav>Navigation</nav> }))

describe('CareerCoachesPage', () => {
  it('features Morris, Benjamin, and Byron in the directory hero', () => {
    render(<MemoryRouter><CareerCoachesPage /></MemoryRouter>)

    const heroPortraits = screen.getByLabelText('Featured FinEx career coaches')
    expect(within(heroPortraits).getByText('Morris Hui, CFA')).toBeInTheDocument()
    expect(within(heroPortraits).getByText('Benjamin Chung')).toBeInTheDocument()
    expect(within(heroPortraits).getByText('Byron Gardiner')).toBeInTheDocument()
  })

  it('shows the full roster, then filters it by specialty', () => {
    render(<MemoryRouter><CareerCoachesPage /></MemoryRouter>)

    expect(screen.getAllByRole('article')).toHaveLength(32)
    fireEvent.click(screen.getByRole('button', { name: /digital assets & fintech/i }))

    expect(screen.getByRole('heading', { name: 'Hannah Hui' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Nicholas Yip' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Calvin Lee' })).not.toBeInTheDocument()
    expect(screen.getByText(/coaches match this field/i)).toBeInTheDocument()
  })

  it('refines the directory by exact stated specialty and profile search', () => {
    render(<MemoryRouter><CareerCoachesPage /></MemoryRouter>)

    fireEvent.change(screen.getByRole('combobox', { name: /specialty/i }), { target: { value: 'Web3' } })
    expect(screen.getAllByRole('article')).toHaveLength(1)
    expect(screen.getByRole('heading', { name: 'John Wong' })).toBeInTheDocument()

    fireEvent.change(screen.getByRole('searchbox', { name: /search coaches/i }), { target: { value: 'Hannah' } })
    expect(screen.queryByRole('heading', { name: 'John Wong' })).not.toBeInTheDocument()
    expect(screen.getByText(/no coaches match these filters/i)).toBeInTheDocument()
  })
})
