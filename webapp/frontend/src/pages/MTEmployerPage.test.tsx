import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../components/Nav', () => ({ default: () => <nav>Navigation</nav> }))

const { default: MTEmployerPage } = await import('./MTEmployerPage')

describe('MTEmployerPage', () => {
  it('makes every supplied employer route visible as its own application tile', () => {
    render(
      <MemoryRouter initialEntries={['/management-trainee/bank-of-america-bofa']}>
        <Routes><Route path="/management-trainee/:employerSlug" element={<MTEmployerPage />} /></Routes>
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: 'Bank of America (BofA)' })).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /Open .* at Bank of America/ })).toHaveLength(8)
    expect(screen.getByRole('link', { name: /Open Enterprise Credit Summer Analyst 2027 at Bank of America/ })).toHaveAttribute(
      'href', expect.stringContaining('enterprise-credit-summer-analyst'),
    )
    expect(screen.queryByText(/Application link \d+/)).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'All MT employers' })).toHaveAttribute('href', '/management-trainee')
  })

  it('uses the shared employer composition', () => {
    render(
        <MemoryRouter initialEntries={['/management-trainee/bank-of-america-bofa']}>
          <Routes><Route path="/management-trainee/:employerSlug" element={<MTEmployerPage />} /></Routes>
        </MemoryRouter>,

    )

    expect(screen.getByTestId('mt-employer-identity')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Bank of America (BofA) logo' })).toHaveClass('mt-employer-page__logo-image')
  })
})
