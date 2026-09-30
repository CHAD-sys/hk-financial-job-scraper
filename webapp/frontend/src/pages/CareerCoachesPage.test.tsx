import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { DeviceModeContext } from '../deviceMode/DeviceModeContext'
import CareerCoachesPage from './CareerCoachesPage'

vi.mock('../components/Nav', () => ({ default: () => <nav>Navigation</nav> }))

function renderPage() {
  return render(
    <DeviceModeContext.Provider value={{
      deviceClass: 'desktop', uiMode: 'desktop', detectionSource: 'user-agent', touchCapable: false,
    }}>
      <MemoryRouter><CareerCoachesPage /></MemoryRouter>
    </DeviceModeContext.Provider>,
  )
}

describe('CareerCoachesPage', () => {
  it('features Morris, Benjamin, and Byron in the directory hero', () => {
    renderPage()

    const heroPortraits = screen.getByLabelText('Featured FinEx career coaches')
    expect(within(heroPortraits).getByText('Morris Hui, CFA')).toBeInTheDocument()
    expect(within(heroPortraits).getByText('Benjamin Chung')).toBeInTheDocument()
    expect(within(heroPortraits).getByText('Byron Gardiner')).toBeInTheDocument()
  })

  it('shows the full roster, then filters it by specialty', () => {
    renderPage()

    expect(screen.getAllByRole('article')).toHaveLength(32)
    fireEvent.click(screen.getByRole('button', { name: /digital assets & fintech/i }))

    expect(screen.getByRole('heading', { name: 'Hannah Hui' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Nicholas Yip' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Calvin Lee' })).not.toBeInTheDocument()
    expect(screen.getByText(/showing coaches specialising in digital assets & fintech/i)).toBeInTheDocument()
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
