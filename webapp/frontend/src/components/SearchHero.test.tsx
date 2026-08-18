import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import SearchHero from './SearchHero'

const CATEGORIES = [
  'Risk Management',
  'Accounting & Finance',
  'Treasury',
  'Investment',
  'Operations',
  'Technology & Transformation',
  'Sales and Business Development',
  'Private Banking',
  'Commercial Banking',
  'Investment Banking',
  'Retail Banking',
  'Sales & Marketing',
  'Legal, Compliance & Audit',
]

describe('SearchHero', () => {
  it('offers every major finance category as a search shortcut', () => {
    const onSearch = vi.fn()
    render(<SearchHero boardTotal={3869} employerCount={240} onSearch={onSearch} />)

    expect(screen.getByRole('heading', { name: 'Explore major categories' })).toBeInTheDocument()
    expect(screen.getByText('13 disciplines')).toBeInTheDocument()
    for (const category of CATEGORIES) {
      expect(screen.getByRole('link', { name: category })).toBeInTheDocument()
    }

    fireEvent.click(screen.getByRole('link', { name: 'Commercial Banking' }))
    expect(onSearch).toHaveBeenCalledWith('Commercial Banking')
  })

  it('gives every category a real href a crawler can follow', () => {
    // These were <button>s until 2026-08-18. Google cannot click a button, so
    // "/jobs" was a page promising jobs, showing none to a signed-out visitor,
    // and linking to no job anywhere — which Google classified as a Soft 404.
    // The href is the fix, so it is what this test pins.
    render(<SearchHero boardTotal={3869} employerCount={240} onSearch={vi.fn()} />)

    expect(screen.getByRole('link', { name: 'Risk Management' })).toHaveAttribute(
      'href',
      '/jobs?q=Risk%20Management',
    )
    // The ampersand categories are the ones a naive template breaks on.
    expect(screen.getByRole('link', { name: 'Accounting & Finance' })).toHaveAttribute(
      'href',
      '/jobs?q=Accounting%20%26%20Finance',
    )
  })

  it('leaves modified clicks to the browser so a category can open in a new tab', () => {
    const onSearch = vi.fn()
    render(<SearchHero boardTotal={3869} employerCount={240} onSearch={onSearch} />)

    fireEvent.click(screen.getByRole('link', { name: 'Treasury' }), { metaKey: true })
    expect(onSearch).not.toHaveBeenCalled()
  })
})
